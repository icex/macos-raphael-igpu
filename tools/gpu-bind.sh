#!/usr/bin/env bash
# Move the AMD iGPU from amdgpu to vfio-pci so QEMU can pass it through.
# Runtime only: nothing persists, a reboot restores normal behaviour.
set -euo pipefail
DEV="${1:-0000:7b:00.0}"
OWNER="${SUDO_UID:-1000}"
ROM_OUT="${2:-/home/bogdan/macos-vm/igpu-vbios.rom}"

[[ $EUID -eq 0 ]] || { echo "run me with sudo" >&2; exit 1; }

# Refuse to touch a device that is already stuck with no driver. Cycling
# vfio-pci -> amdgpu -> vfio-pci once left the bind wedged in uninterruptible
# kernel sleep, and the only way out was a reboot. See findings/GPU-RE.md.
if [[ ! -e "/sys/bus/pci/devices/${DEV}/driver" ]]; then
    echo "${DEV} has NO driver bound -- a previous bind probably wedged." >&2
    echo "Reboot to recover; do not try to bind it again from here." >&2
    exit 1
fi

modprobe vfio-pci

# Snapshot the IP discovery versions -- this is the measurement that decides which
# of Apple's per-IP version gates can ever match. Cheap, and safe to do first.
IPD="/home/bogdan/macos-vm/findings/hw/ip_discovery.txt"
if [[ -d "/sys/bus/pci/devices/${DEV}/ip_discovery/die/0" ]]; then
    mkdir -p "$(dirname "${IPD}")"
    ( cd "/sys/bus/pci/devices/${DEV}/ip_discovery/die/0"
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

cur="$(basename "$(readlink -f "/sys/bus/pci/devices/${DEV}/driver")" 2>/dev/null || echo none)"
echo "current driver: ${cur}"
if [[ "${cur}" != vfio-pci ]]; then
    echo "vfio-pci" > "/sys/bus/pci/devices/${DEV}/driver_override"
    [[ "${cur}" != none ]] && echo "${DEV}" > "/sys/bus/pci/drivers/${cur}/unbind"
    echo "${DEV}" > /sys/bus/pci/drivers_probe
fi

# CRITICAL, do not remove. On kernel 7.2.x, opening a runtime-SUSPENDED device
# with vfio-pci NULL-derefs in vfio_pci_core_runtime_resume (down_write+0x20):
# it kills QEMU instantly and leaves power/runtime_status stuck at "resuming",
# after which even `unbind` blocks in uninterruptible sleep and only a reboot
# recovers the device. vfio-pci re-enables runtime PM on probe, so pin it here,
# AFTER the bind. A udev rule does the same at boot as a belt-and-braces.
echo on > "/sys/bus/pci/devices/${DEV}/power/control"
echo "power/control pinned to: $(cat "/sys/bus/pci/devices/${DEV}/power/control")"
if [[ "$(cat "/sys/bus/pci/devices/${DEV}/power/runtime_status")" == suspended ]]; then
    echo "WARNING: device still reports runtime-suspended; QEMU would trip the oops" >&2
    exit 1
fi

grp="$(basename "$(readlink -f "/sys/bus/pci/devices/${DEV}/iommu_group")")"
chown "${OWNER}" "/dev/vfio/${grp}"
echo "now bound to: $(basename "$(readlink -f "/sys/bus/pci/devices/${DEV}/driver")")"
echo "iommu group ${grp}: $(ls -l "/dev/vfio/${grp}" | awk '{print $3, $1}')"
