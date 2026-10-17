#!/usr/bin/env bash
# Desktop launcher: start macOS on the Raphael iGPU in QEMU's window, with clipboard, USB
# redirection and audio, through the same safety cycle as every run (writeback/SDMA
# quiesce, DMCUB halt, MODE2 reset, staged release kext, GPU ledger, recovery receipt).
#
#   raphael-macos.sh            start (or report that it is already running)
#   raphael-macos.sh stop       ask macOS to shut down and wait for the cycle to finish
#   raphael-macos.sh status
#   raphael-macos.sh usb             choose host USB devices for the running macOS
#
# The release is named in ~/.config/raphael-macos/release.conf (written by
# tools/install-desktop.sh): RELEASE_WORKTREE, CANDIDATE, CARD, PINS. Each start is a new
# attempt of that release, because the cycle refuses to reuse a run identity. The host
# sleep/idle block covers startup, the VM and recovery, then releases on exit.
set -euo pipefail

CONF="${RAPHAEL_MACOS_CONF:-$HOME/.config/raphael-macos/release.conf}"
VM_DIR="${VM_DIR:-$HOME/macos-vm}"
RUN="${VM_DIR}/run"
DEV=/sys/bus/pci/devices/0000:7b:00.0
CONTAINER=macos-sequoia
TITLE="macOS (Raphael iGPU)"

notify() { notify-send -a "${TITLE}" -i computer "$@" 2>/dev/null || true; echo "$*"; }
fail() { notify -u critical "${TITLE}" "$1"; exit 1; }

[[ -r "${CONF}" ]] || fail "No release configured: run tools/install-desktop.sh"
# shellcheck source=/dev/null
source "${CONF}"
: "${RELEASE_WORKTREE:?}" "${CANDIDATE:?}" "${CARD:?}" "${PINS:?}"
[[ "${PINS}" = /* ]] || PINS="${RELEASE_WORKTREE}/${PINS}"
INHIBITOR="${RAPHAEL_MACOS_INHIBITOR:-$HOME/.local/libexec/raphael-macos-inhibitor.py}"

running_unit() { systemctl --user list-units --state=active,activating,deactivating --plain --no-legend 'raphael-macos-d*.service' | awk '$1 ~ /^raphael-macos-d[0-9]+\.service$/ && !found {print $1; found=1}'; }
vm_running() { [[ -n "$(docker ps --filter "name=^${CONTAINER}$" --format '{{.Names}}')" ]]; }

case "${1:-start}" in
    status)
        unit="$(running_unit)"
        if vm_running; then echo "running (${unit:-no launcher unit})";
        elif [[ -n "${unit}" ]]; then echo "starting or finishing (${unit})";
        else echo "stopped"; fi
        exit 0 ;;
    stop)
        vm_running || { echo "not running"; exit 0; }
        unit="$(running_unit)"
        attempt="${unit#raphael-macos-}"; attempt="${attempt%.service}"
        results="${RUN}/candidate-${CANDIDATE}-attempt-${attempt}-results"
        [[ -d "${results}" ]] || fail "No run directory for ${unit}; shut macOS down from its menu"
        touch "${results}/stop-requested"
        notify "${TITLE}" "Shutting macOS down…"
        exit 0 ;;
    usb)
        vm_running || fail "macOS is not running"
        exec "${RELEASE_WORKTREE}/tools/rgpu-usb-picker.sh" ;;
    start) ;;
    *) echo "usage: $0 [start|stop|status|usb]" >&2; exit 2 ;;
esac

if vm_running || [[ -n "$(running_unit)" ]]; then
    notify "${TITLE}" "macOS is already running or starting."
    exit 0
fi

# The iGPU must be on vfio-pci with runtime PM pinned on.
driver="$(basename "$(readlink -f "${DEV}/driver" 2>/dev/null)" 2>/dev/null || true)"
if [[ "${driver}" != vfio-pci || "$(cat "${DEV}/power/control")" != on ]]; then
    notify "${TITLE}" "Handing the iGPU to the VM…"
    pkexec /usr/local/libexec/rgpu-gpu-bind || fail "Could not bind the iGPU to vfio-pci"
fi

# A fresh attempt of the release: its own kext copy and identity record.
attempt="d$(date +%Y%m%d%H%M%S)"
base="${RUN}/candidate-${CANDIDATE}"
[[ -d "${base}/RaphaelGPU.kext" && -r "${base}-build-identities.json" ]] ||
    fail "Release candidate-${CANDIDATE} is not staged in ${RUN}"
mkdir "${base}-attempt-${attempt}"
cp -a "${base}/build-manifest.json" "${base}/RaphaelGPU.kext" "${base}-attempt-${attempt}/"
python3 -B - "${base}" "${attempt}" <<'PY'
import json, sys
base, attempt = sys.argv[1], sys.argv[2]
identities = json.load(open(base + "-build-identities.json"))
identities["extracted_candidate"] = f"{base}-attempt-{attempt}"
json.dump(identities, open(f"{base}-attempt-{attempt}-build-identities.json", "w"), indent=2)
PY

# The cycle requires a clean release worktree; a previous run's status append is saved.
if ! git -C "${RELEASE_WORKTREE}" diff --quiet; then
    dirty="$(git -C "${RELEASE_WORKTREE}" status --porcelain | grep -v '^ M status.md$' || true)"
    [[ -z "${dirty}" ]] || fail "Release worktree has local changes: ${dirty}"
    git -C "${RELEASE_WORKTREE}" diff status.md > "${RUN}/raphael-macos-status-$(date +%s).diff"
    git -C "${RELEASE_WORKTREE}" checkout -q status.md
fi

log="${RUN}/raphael-macos-${attempt}.log"
session=(
    bash -c '
        cd "$1" || exit 1
        python3 -B tools/cycle.py --worktree "$1" --candidate "$2" --card "$3" --attempt "$4" --pins "$5" \
            --skip-tests > "$6" 2>&1
        rc=$?
        systemctl --user stop "raphael-macos-usb-$4.path" 2>/dev/null || true
        tools/rgpu-usb.sh detach all >/dev/null 2>&1 || true
        if ! git diff --quiet status.md; then
            git diff status.md > "$7/raphael-macos-$4-status.diff"; git checkout -q status.md
        fi
        results="$7/candidate-$2-attempt-$4-results"
        ready=false
        grep -q "\"authorizes_launch\": true" "$results/recovery.json" 2>/dev/null && ready=true
        # Since 515 the supervised wrapper owns this fallback and stores the
        # separate authorizing receipt. Never issue a second MODE2 here.
        if [ "$ready" = false ] && [ "$2" -ge 515 ] &&
                grep -q "\"status\": \"recovered\"" "$results/postrun-mode2-noqueue.json" 2>/dev/null &&
                grep -q "\"authorizes_launch\": true" "$results/postrun-mode2-noqueue.json" 2>/dev/null &&
                grep -q "\"postrun_recovery\"" "$results/wrapper-result.json" 2>/dev/null; then
            ready=true
        fi
        # Older releases retain their existing explicit stopped-device path.
        if [ "$ready" = false ] && [ "$2" -lt 515 ] &&
                grep -Eq "\"status\": \"(failed|incomplete)\"" "$results/recovery.json" 2>/dev/null &&
                python3 -B tools/mode2-noqueue-recover.py --vm-dir "$HOME/macos-vm" --run-dir "$results" \
                    --output "$results-noqueue.json" --execute >> "$6" 2>&1; then
            grep -q "\"authorizes_launch\": true" "$results-noqueue.json" 2>/dev/null && ready=true
        fi
        # The refusing step reports its reason as an "error" field; else the abort line itself.
        aborted="$(grep -o "\"error\": \"[^\"]*\"" "$6" | tail -1 | cut -d\" -f4 | cut -c1-200)"
        [ -n "$aborted" ] || aborted="$(grep -m1 "CYCLE ABORTED" "$6" | cut -c1-200)"
        if grep -q "CYCLE ABORTED" "$6"; then
            notify-send -a "$8" -u critical -i computer "$8" "macOS did not start: ${aborted:-see $6}" || true
            exit $rc
        fi
        if [ "$ready" = true ]; then
            notify-send -a "$8" -i computer "$8" "macOS stopped; the iGPU is ready for the next start." || true
        else
            notify-send -a "$8" -u critical -i computer "$8" \
                "macOS stopped, but GPU recovery did not complete. See $6" || true
        fi
        exit $rc
    ' raphael-macos "${RELEASE_WORKTREE}" "${CANDIDATE}" "${CARD}" "${attempt}" "${PINS}" "${log}" "${RUN}" "${TITLE}"
)
# QEMU's Machine > USB Devices... rewrites this file (RGPU_USB_REQUEST); open the picker then.
usb_request="${RUN}/usb-picker.request"
rm -f "${usb_request}"; : > "${usb_request}"; chmod 0600 "${usb_request}"
systemd-run --user --unit "raphael-macos-usb-${attempt}" --collect --quiet \
    --path-property=PathChanged="${usb_request}" \
    --setenv=DISPLAY="${DISPLAY:-:0}" \
    --setenv=XAUTHORITY="${XAUTHORITY:-$(ls -t /run/user/"$(id -u)"/xauth_* 2>/dev/null | head -1)}" \
    --setenv=DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=/run/user/$(id -u)/bus}" \
    "${RELEASE_WORKTREE}/tools/rgpu-usb-picker.sh" || true
systemd-run --user --unit "raphael-macos-${attempt}" --collect --quiet \
    --property="ExecStopPost=/usr/bin/python3 -B ${INHIBITOR} --pins ${PINS} --owner ${attempt} --cleanup" \
    --setenv=DISPLAY="${DISPLAY:-:0}" \
    --setenv=XAUTHORITY="${XAUTHORITY:-$(ls -t /run/user/"$(id -u)"/xauth_* 2>/dev/null | head -1)}" \
    --setenv=DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=/run/user/$(id -u)/bus}" \
    systemd-inhibit --what=sleep:idle --mode=block --who=Raphael-macOS \
    --why="macOS VM startup, running and recovery" \
    python3 -B "${INHIBITOR}" --pins "${PINS}" --owner "${attempt}" -- "${session[@]}"
notify "${TITLE}" "Starting macOS… the window opens in about a minute."
