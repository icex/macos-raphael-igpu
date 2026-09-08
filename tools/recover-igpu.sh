#!/usr/bin/env bash
# Recover the iGPU after a vfio_pci_core runtime-PM oops, and pin it awake so the
# oops cannot recur.
#
# The bug: on kernel 7.2.3-1-cachyos-bore, opening a runtime-SUSPENDED device with
# vfio-pci NULL-derefs in vfio_pci_core_runtime_resume (down_write+0x20). It kills
# QEMU and leaves power/runtime_status stuck at "resuming" forever.
# The fix: power/control = on BEFORE anything opens the device, so the runtime
# resume path never runs.
#
# Every dangerous sysfs write is wrapped in `timeout` so a hung write cannot take
# the caller down with it.
set -uo pipefail
DEV=0000:7b:00.0
OWNER_UID="${RGPU_OWNER_UID:-${SUDO_UID:-}}"
OWNER_GID="${RGPU_OWNER_GID:-${SUDO_GID:-}}"
S=/sys/bus/pci/devices/$DEV
w() { local t=$1 val=$2 path=$3; timeout "$t" sh -c "echo '$val' > '$path'" 2>&1 \
        && echo "  ok: $val > ${path#/sys/bus/pci/}" || echo "  TIMEOUT/FAIL: $val > ${path#/sys/bus/pci/}"; }
st() { echo "  driver=$(basename "$(readlink -f $S/driver)" 2>/dev/null || echo none)" \
            "rpm=$(cat $S/power/runtime_status 2>/dev/null || echo ?)" \
            "control=$(cat $S/power/control 2>/dev/null || echo ?)" \
            "pstate=$(cat $S/power_state 2>/dev/null || echo ?)"; }

[[ $EUID -eq 0 ]] || { echo "run me with sudo" >&2; exit 1; }
if [[ ! "${OWNER_UID}" =~ ^[0-9]+$ || ! "${OWNER_GID}" =~ ^[0-9]+$ ]] ||
        (( 10#${OWNER_UID} == 0 || 10#${OWNER_GID} == 0 )); then
    echo "cannot identify the invoking user; use sudo or set RGPU_OWNER_UID and RGPU_OWNER_GID" >&2
    exit 1
fi
OWNER="${OWNER_UID}:${OWNER_GID}"

echo "before:"; st

if [[ "$(cat $S/power/runtime_status 2>/dev/null)" == resuming ]]; then
    echo "PM state machine is stuck; re-enumerating the device to reset it"
    cur="$(basename "$(readlink -f $S/driver)" 2>/dev/null || echo none)"
    [[ "$cur" != none ]] && w 20 "$DEV" "/sys/bus/pci/drivers/$cur/unbind"
    w 20 1 "$S/remove"
    w 60 1 /sys/bus/pci/rescan
    sleep 3
    echo "after rescan:"; st
fi

[[ -e $S ]] || { echo "device did not come back from rescan -- reboot required" >&2; exit 1; }

# Pin it awake FIRST. This is the whole point.
w 10 on "$S/power/control"
[[ "$(cat $S/power/control)" == on ]] || { echo "could not pin power/control=on -- reboot required" >&2; exit 1; }

cur="$(basename "$(readlink -f $S/driver)" 2>/dev/null || echo none)"
if [[ "$cur" != vfio-pci ]]; then
    modprobe vfio-pci
    w 10 vfio-pci "$S/driver_override"
    [[ "$cur" != none ]] && w 20 "$DEV" "/sys/bus/pci/drivers/$cur/unbind"
    w 30 "$DEV" /sys/bus/pci/drivers_probe
    sleep 2
    # vfio-pci re-enables runtime PM on probe, so pin it again afterwards.
    w 10 on "$S/power/control"
fi

# Legacy VFIO otherwise invokes the device's only advertised method (`bus`) on
# open/close. That bus contains host APU functions, so disable reset support
# before granting the caller access to the group node.
[[ -w "$S/reset_method" ]] || { echo "reset_method is not writable -- reboot required" >&2; exit 1; }
w 10 "" "$S/reset_method"
[[ -z "$(tr -d '[:space:]' < "$S/reset_method")" ]] || {
    echo "could not disable PCI reset methods -- reboot required" >&2
    exit 1
}

echo "after:"; st
grp="$(basename "$(readlink -f $S/iommu_group)" 2>/dev/null || echo '?')"
[[ -e /dev/vfio/$grp ]] && { chown "$OWNER" "/dev/vfio/$grp"; echo "  chowned /dev/vfio/$grp"; }
[[ "$(cat $S/power/control)" == on && "$(basename "$(readlink -f $S/driver)")" == vfio-pci ]] \
    && echo "READY" || echo "NOT READY"
