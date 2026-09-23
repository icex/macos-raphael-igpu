#!/usr/bin/env bash
# Move the AMD iGPU from amdgpu to vfio-pci so QEMU can pass it through.
# Runtime only: nothing persists, a reboot restores normal behaviour.
set -euo pipefail
DEV="${1:-0000:7b:00.0}"
OWNER_UID="${RGPU_OWNER_UID:-${SUDO_UID:-}}"
OWNER_GID="${RGPU_OWNER_GID:-${SUDO_GID:-}}"
VM="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROM_OUT="${2:-$VM/igpu-vbios.rom}"
DEVICE_SYSFS="/sys/bus/pci/devices/${DEV}"

[[ $EUID -eq 0 ]] || { echo "run me with sudo" >&2; exit 1; }
if [[ ! "${OWNER_UID}" =~ ^[0-9]+$ || ! "${OWNER_GID}" =~ ^[0-9]+$ ]] ||
        (( 10#${OWNER_UID} == 0 || 10#${OWNER_GID} == 0 )); then
    echo "cannot identify the invoking user; use sudo or set RGPU_OWNER_UID and RGPU_OWNER_GID" >&2
    exit 1
fi
OWNER="${OWNER_UID}:${OWNER_GID}"

# Refuse to touch a device that is already stuck with no driver. Cycling
# vfio-pci -> amdgpu -> vfio-pci once left the bind wedged in uninterruptible
# kernel sleep, and the only way out was a reboot. See findings/GPU-RE.md.
if [[ ! -e "${DEVICE_SYSFS}/driver" ]]; then
    echo "${DEV} has NO driver bound -- a previous bind probably wedged." >&2
    echo "Reboot to recover; do not try to bind it again from here." >&2
    exit 1
fi

modprobe vfio-pci

# Snapshot the IP discovery versions -- this is the measurement that decides which
# of Apple's per-IP version gates can ever match. Cheap, and safe to do first.
IPD="$VM/findings/hw/ip_discovery.txt"
if [[ -d "${DEVICE_SYSFS}/ip_discovery/die/0" ]]; then
    mkdir -p "$(dirname "${IPD}")"
    ( cd "${DEVICE_SYSFS}/ip_discovery/die/0"
      for ip in */; do
          ip="${ip%/}"
          [[ -r "${ip}/0/major" ]] || continue
          printf '%-10s %s.%s.%s\n' "${ip}" \
              "$(cat ${ip}/0/major)" "$(cat ${ip}/0/minor)" "$(cat ${ip}/0/revision)"
      done ) | sort > "${IPD}"
    chown "${OWNER}" "${IPD}"
    echo "ip_discovery snapshot -> ${IPD} ($(grep -c . "${IPD}") IP blocks)"
fi

# The video BIOS must be read while amdgpu still owns the device: an integrated
# GPU has no ROM BAR, its ATOMBIOS image lives in system firmware.
if [[ ! -s "${ROM_OUT}" ]]; then
    found=""
    for d in /sys/kernel/debug/dri/*/; do
        n="$(cat "${d}name" 2>/dev/null || true)"
        [[ "$n" == *"${DEV}"* ]] || continue
        [[ -f "${d}amdgpu_vbios" ]] || continue
        cat "${d}amdgpu_vbios" > "${ROM_OUT}"
        chown "${OWNER}" "${ROM_OUT}"
        found="${d}"
        break
    done
    [[ -n "$found" ]] && echo "vbios dumped from ${found} -> ${ROM_OUT} ($(stat -c%s "${ROM_OUT}") bytes)" \
                      || echo "WARNING: could not find amdgpu_vbios for ${DEV}"
else
    echo "vbios already present: ${ROM_OUT} ($(stat -c%s "${ROM_OUT}") bytes)"
fi


# While amdgpu still owns the device, record its own DDC/EDID register sequence on the iGPU
# HDMI connector (root-only tracepoints). Non-fatal; RGPU_DDC_TRACE=off skips it. The guest's
# EDID read on the same port is NACKed, and this is the reference to diff it against.
if [[ "${RGPU_DDC_TRACE:-on}" != off && "$(basename "$(readlink -f "${DEVICE_SYSFS}/driver")" 2>/dev/null)" == amdgpu ]]; then
    conn="$(ls -d /sys/class/drm/card*-HDMI-A-* 2>/dev/null | while read -r c; do
        [[ "$(readlink -f "$c/device")" == "${DEVICE_SYSFS}" ]] && basename "$c"; done | head -1)"
    if [[ -n "${conn}" && -x "${VM}/host-ddc-trace.sh" ]]; then
        trace_out="${VM}/run/host-ddc-trace-$(cat /proc/sys/kernel/random/boot_id | cut -c1-8).txt"
        if RGPU_OWNER_UID="${OWNER_UID}" SUDO_UID="${OWNER_UID}" "${VM}/host-ddc-trace.sh" "${conn}" "${trace_out}"; then
            chown "${OWNER}" "${trace_out}"
        else
            echo "WARNING: host DDC trace failed (continuing)" >&2
        fi
    else
        echo "host DDC trace skipped: no iGPU HDMI connector under amdgpu or helper missing"
    fi
fi
cur="$(basename "$(readlink -f "${DEVICE_SYSFS}/driver")" 2>/dev/null || echo none)"
echo "current driver: ${cur}"
if [[ "${cur}" != vfio-pci ]]; then
    echo "vfio-pci" > "${DEVICE_SYSFS}/driver_override"
    [[ "${cur}" != none ]] && echo "${DEV}" > "/sys/bus/pci/drivers/${cur}/unbind"
    echo "${DEV}" > /sys/bus/pci/drivers_probe
fi

cur="$(basename "$(readlink -f "${DEVICE_SYSFS}/driver")" 2>/dev/null || echo none)"
[[ "${cur}" == vfio-pci ]] || {
    echo "${DEV} did not bind to vfio-pci -- refusing unsafe VFIO handoff" >&2
    exit 1
}

# Opening or closing a legacy VFIO device calls the PCI reset path. Raphael
# advertises only `bus`, and that bus also contains the host CCP and xHCI
# functions. Disable every PCI reset method before QEMU or an unprivileged
# cleanup process can acquire the VFIO device fd. Linux documents a whitespace-
# only write as the reset_method ABI for disabling reset support.
[[ -w "${DEVICE_SYSFS}/reset_method" ]] || {
    echo "${DEV} has no writable reset_method -- refusing unsafe VFIO handoff" >&2
    exit 1
}
printf '\n' > "${DEVICE_SYSFS}/reset_method"
reset_methods="$(tr -d '[:space:]' < "${DEVICE_SYSFS}/reset_method")"
[[ -z "${reset_methods}" ]] || {
    echo "${DEV} still exposes PCI reset methods '${reset_methods}' -- refusing unsafe VFIO handoff" >&2
    exit 1
}
echo "PCI reset methods disabled for ${DEV}"

# CRITICAL, do not remove. On kernel 7.2.x, opening a runtime-SUSPENDED device
# with vfio-pci NULL-derefs in vfio_pci_core_runtime_resume (down_write+0x20):
# it kills QEMU instantly and leaves power/runtime_status stuck at "resuming",
# after which even `unbind` blocks in uninterruptible sleep and only a reboot
# recovers the device. vfio-pci re-enables runtime PM on probe, so pin it here,
# AFTER the bind. A udev rule does the same at boot as a belt-and-braces.
echo on > "${DEVICE_SYSFS}/power/control"
echo "power/control pinned to: $(cat "${DEVICE_SYSFS}/power/control")"
if [[ "$(cat "${DEVICE_SYSFS}/power/runtime_status")" == suspended ]]; then
    echo "WARNING: device still reports runtime-suspended; QEMU would trip the oops" >&2
    exit 1
fi

grp="$(basename "$(readlink -f "${DEVICE_SYSFS}/iommu_group")")"
VFIO_GROUP="/dev/vfio/${grp}"
chown "${OWNER}" "${VFIO_GROUP}"
echo "now bound to: $(basename "$(readlink -f "${DEVICE_SYSFS}/driver")")"
echo "iommu group ${grp}: $(ls -l "${VFIO_GROUP}" | awk '{print $3, $1}')"

# Guest LAN NIC: a macvtap child of the host LAN interface, handed to the user like the VFIO
# group. The launcher attaches it as the guest's second NIC (fixed MAC so the guest keeps its
# saved network service and address). RGPU_LAN=off skips it; RGPU_LAN_PARENT picks the port.
if [[ "${RGPU_LAN:-on}" != off ]]; then
    LAN_PARENT="${RGPU_LAN_PARENT:-enp9s0}"
    LAN_IF="${RGPU_LAN_IF:-rgpu-lan}"
    LAN_MAC="${RGPU_LAN_MAC:-52:54:00:52:47:44}"
    if [[ -d "/sys/class/net/${LAN_PARENT}" ]]; then
        [[ -d "/sys/class/net/${LAN_IF}" ]] || ip link add link "${LAN_PARENT}" name "${LAN_IF}" type macvtap mode bridge
        ip link set "${LAN_IF}" address "${LAN_MAC}"
        ip link set "${LAN_IF}" up
        lan_node="/dev/tap$(cat "/sys/class/net/${LAN_IF}/ifindex")"
        for _ in $(seq 1 50); do [[ -c "${lan_node}" ]] && break; sleep 0.1; done
        chown "${OWNER}" "${lan_node}" && chmod 0600 "${lan_node}"
        echo "guest LAN: ${LAN_IF} on ${LAN_PARENT}, mac ${LAN_MAC}, ${lan_node} -> ${OWNER}"
    else
        echo "WARNING: no ${LAN_PARENT}; guest LAN NIC skipped (set RGPU_LAN_PARENT)" >&2
    fi
fi
