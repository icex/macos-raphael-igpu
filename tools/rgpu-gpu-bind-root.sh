#!/usr/bin/env bash
# Root helper for the desktop launcher: hand the Raphael iGPU to vfio-pci for the user who
# asked (pkexec), with the same safety steps as tools/gpu-bind.sh and nothing else.
#
# Installed root-owned as /usr/local/libexec/rgpu-gpu-bind by tools/install-desktop.sh,
# which also adds a polkit rule letting the local active desktop user run exactly this file.
# It takes no arguments, runs nothing from the user's home and writes no files there; the
# development extras of gpu-bind.sh (VBIOS dump, IP-discovery snapshot, DDC trace) stay in
# that script.
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin

DEV=0000:7b:00.0
SYSFS="/sys/bus/pci/devices/${DEV}"
LAN_PARENT=enp9s0
LAN_IF=rgpu-lan
LAN_MAC=52:54:00:52:47:44

[[ $EUID -eq 0 ]] || { echo "run through pkexec" >&2; exit 1; }
(( $# == 0 )) || { echo "takes no arguments" >&2; exit 2; }
OWNER_UID="${PKEXEC_UID:-${SUDO_UID:-}}"
[[ "${OWNER_UID}" =~ ^[0-9]+$ ]] && (( 10#${OWNER_UID} != 0 )) || {
    echo "cannot identify the invoking user" >&2; exit 1; }
OWNER_GID="$(id -g "${OWNER_UID}")"
OWNER="${OWNER_UID}:${OWNER_GID}"

[[ -e "${SYSFS}" ]] || { echo "no device ${DEV}" >&2; exit 1; }
# A device left with no driver means an earlier bind wedged: only a reboot recovers it.
[[ -e "${SYSFS}/driver" ]] || { echo "${DEV} has no driver bound; reboot first" >&2; exit 1; }

cur="$(basename "$(readlink -f "${SYSFS}/driver")")"
if [[ "${cur}" != vfio-pci ]]; then
    # Host safety: bind only from amdgpu (initialised this boot), never cycle back.
    [[ "${cur}" == amdgpu ]] || { echo "${DEV} is bound to ${cur}, expected amdgpu" >&2; exit 1; }
    modprobe vfio-pci
    echo vfio-pci > "${SYSFS}/driver_override"
    echo "${DEV}" > /sys/bus/pci/drivers/amdgpu/unbind
    echo "${DEV}" > /sys/bus/pci/drivers_probe
    cur="$(basename "$(readlink -f "${SYSFS}/driver")")"
    [[ "${cur}" == vfio-pci ]] || { echo "${DEV} did not bind to vfio-pci" >&2; exit 1; }
fi

# Raphael's only reset method is a bus reset shared with host functions: disable them all.
printf '\n' > "${SYSFS}/reset_method"
[[ -z "$(tr -d '[:space:]' < "${SYSFS}/reset_method")" ]] || {
    echo "${DEV} still exposes PCI reset methods" >&2; exit 1; }
# Opening a runtime-suspended device through vfio-pci oopses the kernel: pin it awake.
echo on > "${SYSFS}/power/control"
[[ "$(cat "${SYSFS}/power/runtime_status")" != suspended ]] || {
    echo "${DEV} still runtime-suspended" >&2; exit 1; }

group="/dev/vfio/$(basename "$(readlink -f "${SYSFS}/iommu_group")")"
chown "${OWNER}" "${group}"

# Guest LAN NIC: a macvtap child of the host LAN port, handed to the user.
if [[ -d "/sys/class/net/${LAN_PARENT}" ]]; then
    [[ -d "/sys/class/net/${LAN_IF}" ]] || ip link add link "${LAN_PARENT}" name "${LAN_IF}" type macvtap mode bridge
    ip link set "${LAN_IF}" address "${LAN_MAC}"
    ip link set "${LAN_IF}" up
    node="/dev/tap$(cat "/sys/class/net/${LAN_IF}/ifindex")"
    for _ in $(seq 1 50); do [[ -c "${node}" ]] && break; sleep 0.1; done
    chown "${OWNER}" "${node}" && chmod 0600 "${node}"
fi
echo "${DEV}: vfio-pci, reset disabled, power pinned, ${group} -> ${OWNER}"
