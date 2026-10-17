#!/usr/bin/env bash
# Walk the milestone ladder unattended.
#
#   ./autorun.sh              # cumulative: m1, m1+m2, m1+m2+m3 ... m1..m7
#   ./autorun.sh m1 m2 m3     # only these rungs
#   ./autorun.sh --only m4    # exactly one set, nothing else enabled
#
# For each rung it deploys, boots, waits for a verdict on the serial console,
# classifies it, and appends to findings/autorun-log.md. It STOPS on anything it
# cannot interpret, and refuses to keep booting into a known-bad host state.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
DEV=0000:7b:00.0
S=/sys/bus/pci/devices/$DEV
LOG=findings/autorun-log.md
BOOT_TIMEOUT=${BOOT_TIMEOUT:-420}

# Passthrough during an unattended loop is how the host was lost for three hours.
#
# redeploy.sh's default is now no-passthrough, so this loop is GPU-less unless you ask
# otherwise -- and a GPU-less rung cannot produce a meaningful verdict about the graphics
# core, so say which mode we are in rather than letting the log imply the other one.
#
# The first host hang came from exactly this script: roughly 33 launches over three hours,
# each one handing the iGPU to a guest, with nobody at the machine. If you want GPU rungs,
# AUTORUN_GPU=1 turns them back on -- but run them a few at a time and stay in the room.
REDEPLOY_GPU_ARG=()
if [[ "${AUTORUN_GPU:-0}" == 1 ]]; then
    REDEPLOY_GPU_ARG=(--gpu)
    say "AUTORUN_GPU=1: rungs run WITH the iGPU passed through, unattended."
    say "  All three host hangs happened with the device open. Do not leave this running."
else
    say "GPU passthrough OFF for this loop (AUTORUN_GPU=1 to enable)."
    say "  Verdicts below describe the guest without the iGPU, not the graphics core."
fi

ONLY=0; [[ "${1:-}" == --only ]] && { ONLY=1; shift; }
SETS=("$@"); [[ ${#SETS[@]} -eq 0 ]] && SETS=(m1 m2 m3 m4 m5 m6 m7)

say() { printf '%s\n' "$*"; }
note() { printf '%s\n' "$*" >> "$LOG"; }

# ---- preflight ---------------------------------------------------------------
preflight() {
    local bad=0
    local drv rpm ctl
    drv=$(basename "$(readlink -f $S/driver)" 2>/dev/null || echo none)
    rpm=$(cat $S/power/runtime_status 2>/dev/null || echo '?')
    ctl=$(cat $S/power/control 2>/dev/null || echo '?')
    say "preflight: driver=$drv runtime=$rpm power/control=$ctl"
    [[ "$drv" == vfio-pci ]] || { say "  FAIL: not bound to vfio-pci (run recover-igpu.sh)"; bad=1; }
    # This is the one that matters: opening a runtime-suspended device NULL-derefs
    # in vfio_pci_core_runtime_resume on this kernel and kills QEMU.
    [[ "$ctl" == on ]] || { say "  FAIL: power/control must be 'on' or QEMU will trip the vfio runtime-PM oops"; bad=1; }
    [[ "$rpm" == resuming ]] && { say "  FAIL: PM state machine stuck; reboot or recover-igpu.sh"; bad=1; }
    [[ -r /dev/vfio/$(basename "$(readlink -f $S/iommu_group)") ]] || { say "  FAIL: /dev/vfio group not readable"; bad=1; }
    return $bad
}

host_oopsed_since() {   # $1 = ISO timestamp
    # grep -c and a captured count, never "grep -q" in this pipeline. grep -q exits on the
    # first match, journalctl is still writing, so it dies of SIGPIPE with 141 -- and this
    # script runs under "set -o pipefail", which then reports the pipeline as failed. The
    # effect was that a REAL host oops read as "no oops", so the loop that is supposed to
    # stop before wedging the machine never stopped. grep -c reads to EOF.
    local n
    n="$(journalctl -k --since "$1" --no-pager 2>/dev/null \
         | grep -cE 'BUG: kernel NULL pointer|general protection fault|vfio_pci_core_runtime_resume' \
         || true)"
    (( ${n:-0} > 0 ))
}

qemu_zombie() {
    local d cmd
    for d in /proc/[0-9]*; do
        [ -r "$d/cmdline" ] || continue
        cmd=$(tr '\0' ' ' < "$d/cmdline" 2>/dev/null) || continue
        [ -n "$cmd" ] || continue
        case "$cmd" in *qemu-system-x86_64*)
            [[ "$(awk '{print $3}' "$d/stat" 2>/dev/null)" == Z ]] && return 0 ;;
        esac
    done
    return 1
}

# ---- verdict ----------------------------------------------------------------
MARKERS='event_id=0xc00c02|TTL::initialize\(\) Failed|Could NOT Create Controller|panic\(|ASSERT REASON|GraphicsAccelerator.*start\(\)'
LATE='com.apple.xpc.launchd|Loaded kext|login window|WindowServer'

wait_for_verdict() {
    local t=0
    while (( t < BOOT_TIMEOUT )); do
        # Same SIGPIPE-under-pipefail hazard as host_oopsed_since: tr is still streaming a
        # ~200 KB log when grep -q exits, so a found marker read as "not found".
        if (( $(tr -d '\r' < run/serial.log 2>/dev/null | grep -cE "$MARKERS" || true) > 0 )); then
            echo marker; return 0
        fi
        if qemu_zombie; then echo qemu-died; return 0; fi
        if (( $(tr -d '\r' < run/serial.log 2>/dev/null | grep -cE "$LATE" || true) > 0 )); then
            # guest is late in boot; give the AMD stack a moment then take what we have
            sleep 30; echo late; return 0
        fi
        sleep 5; t=$((t+5))
    done
    echo timeout
}

classify() {
    local s; s=$(tr -d '\r' < run/serial.log 2>/dev/null)
    local stage; stage=$(grep -oE 'event_id=0xc00c02[0-9a-f]{2}' <<<"$s" | tail -1)
    local reasons; reasons=$(grep -E 'ASSERT (FUNCTION|REASON)' <<<"$s" | tail -6 | sed 's/^/      /')
    local gpucap; gpucap=$(grep -E 'GPUCAP\] refresh' <<<"$s" | tail -6 | sed 's/^/      /')
    local panic;  panic=$(grep -cE 'panic\(' <<<"$s")
    local ttl;    ttl=$(grep -cE 'TTL::initialize\(\) Failed' <<<"$s")
    local accel;  accel=$(grep -cE 'GraphicsAccelerator' <<<"$s")
    # The plugin logs one line per patch -- but to os_log, NOT serial. Pull it from
    # the guest, or every verdict reports a false patches_applied=0.
    local plog; plog=$(./guest-log.sh rgpu 2>/dev/null | grep -oE 'rgpu: @ .*' || true)
    local applied; applied=$(grep -c 'APPLIED' <<<"$plog")
    local pfailed; pfailed=$(grep -c 'FAILED'  <<<"$plog")
    local rgpu;    rgpu=$(tail -8 <<<"$plog" | sed 's/^/      /')
    printf 'stage=%s patches_applied=%s patches_failed=%s panic=%s ttl_fail=%s accel_mentions=%s serial_bytes=%s\n' \
        "${stage:-none}" "$applied" "$pfailed" "$panic" "$ttl" "$accel" "$(stat -c%s run/serial.log 2>/dev/null || echo 0)"
    [[ -n "$rgpu" ]] && { echo "    plugin:"; echo "$rgpu"; }
    [[ -n "$gpucap" ]] && { echo "    GPUCAP:"; echo "$gpucap"; }
    [[ -n "$reasons" ]] && { echo "    asserts:"; echo "$reasons"; }
}

# ---- main -------------------------------------------------------------------
mkdir -p findings
note ""; note "## autorun $(date '+%Y-%m-%d %H:%M:%S')"
# Baseline measured with no patches at all: bgm_create fails at stage 3,
# bif_ip_create, because this chip reports NBIF 7.3.0. Seeding it means a rung
# whose patch silently fails to apply is caught immediately instead of looking
# like a result.
prev_stage="stage=event_id=0xc00c0203"
for i in "${!SETS[@]}"; do
    if (( ONLY )); then enable=("${SETS[$i]}"); else enable=("${SETS[@]:0:$((i+1))}"); fi
    label="${enable[*]}"
    say ""; say "================ rung: $label ================"

    preflight || { say "ABORTING: host not in a safe state"; note "- **$label**: aborted, preflight failed"; exit 1; }
    t0=$(date '+%Y-%m-%d %H:%M:%S')

    ./milestones.py only "${enable[@]}" >/dev/null 2>&1 || { say "milestones.py refused (pattern check failed)"; exit 1; }
    ./redeploy.sh "${REDEPLOY_GPU_ARG[@]}" >/dev/null 2>&1 || { say "redeploy failed"; note "- **$label**: redeploy failed"; exit 1; }

    v=$(wait_for_verdict)
    res=$(classify)
    say "  verdict[$v] $res"
    note "- **$label** — verdict \`$v\`"
    note "  \`\`\`"; note "  $res"; note "  \`\`\`"

    if host_oopsed_since "$t0"; then
        say "  HOST KERNEL OOPS during this rung -- stopping so we do not wedge the box"
        note "  > host kernel oops (vfio runtime-PM); stopped"
        exit 2
    fi
    if [[ "$v" == qemu-died ]]; then
        say "  QEMU died without a guest-side verdict -- stopping"
        note "  > qemu died; stopped"
        exit 2
    fi
    stage=$(grep -oE 'stage=[^ ]+' <<<"$res")
    if [[ -n "$prev_stage" && "$stage" == "$prev_stage" ]]; then
        say "  stage did not advance ($stage) -- the patch for this rung did not take effect"
        note "  > stage unchanged from previous rung; stopped"
        exit 3
    fi
    prev_stage="$stage"
done
say ""; say "ladder complete; see $LOG"
