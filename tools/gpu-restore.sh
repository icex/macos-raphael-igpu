#!/usr/bin/env bash
# Give the iGPU back to amdgpu.
#
# WARNING: going back to amdgpu and then forward to vfio-pci again wedged the
# bind once -- the write to /sys/bus/pci/drivers/vfio-pci/bind went into
# uninterruptible sleep and the device was left driverless until a reboot.
# If you need vfio again afterwards, prefer rebooting over re-running gpu-bind.sh.
set -euo pipefail
DEV="${1:-0000:7b:00.0}"
[[ $EUID -eq 0 ]] || { echo "run me with sudo" >&2; exit 1; }
cur="$(basename "$(readlink -f "/sys/bus/pci/devices/${DEV}/driver")" 2>/dev/null || echo none)"
# Give amdgpu a PSP with no stale GPCOM ring, the same courtesy amdgpu extends on unbind.
./gpu-quiesce.sh || echo "NOTE: PSP quiesce failed; amdgpu may re-init the ring anyway"

[[ "${cur}" != none ]] && echo "${DEV}" > "/sys/bus/pci/drivers/${cur}/unbind"
echo "" > "/sys/bus/pci/devices/${DEV}/driver_override"
echo "${DEV}" > /sys/bus/pci/drivers_probe
echo "restored to: $(basename "$(readlink -f "/sys/bus/pci/devices/${DEV}/driver")" 2>/dev/null || echo none)"
