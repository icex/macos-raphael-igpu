#!/usr/bin/env bash
# Pass a host USB device to the macOS guest on the iGPU console (CONSOLE_USBREDIR=on).
# QEMU exposes two usb-redir slots as Unix sockets in the run directory (only their owner can
# connect). This runs rgpu-usbredir-bridge.py, which starts the host's usbredirect for the
# device and relays only that process's connection, as a user service that outlives the
# shell. Detaching stops it, and libusb gives the device back to its Linux drivers.
#
#   rgpu-usb.sh list                      host USB devices
#   rgpu-usb.sh attach VID:PID [1|2]      redirect a device (default: first free slot)
#   rgpu-usb.sh detach [1|2|all]          give devices back to the host
#   rgpu-usb.sh status
#
# usbredirect needs write access to the device node (/dev/bus/usb/BBB/DDD). Seat devices
# often have it through logind; otherwise add a udev rule for the device, e.g.
#   SUBSYSTEM=="usb", ATTR{idVendor}=="0951", ATTR{idProduct}=="1666", TAG+="uaccess"
set -euo pipefail

unit() { echo "rgpu-usbredir-$1"; }
RUN_DIR="${RGPU_RUN_DIR:-$HOME/macos-vm/run}"
BRIDGE="$(dirname "$(readlink -f "$0")")/rgpu-usbredir-bridge.py"
slot_socket() { echo "${RUN_DIR}/usbredir-$(($1 - 1)).sock"; }
active() { systemctl --user -q is-active "$(unit "$1")"; }

case "${1:-status}" in
    list)
        lsusb
        ;;
    attach)
        device="${2:?usage: rgpu-usb.sh attach VID:PID [slot]}"
        [[ "${device}" =~ ^[0-9a-fA-F]{4}:[0-9a-fA-F]{4}$ ]] || { echo "device must be VID:PID" >&2; exit 2; }
        slot="${3:-}"
        if [[ -z "${slot}" ]]; then
            for s in 1 2; do active "${s}" || { slot="${s}"; break; }; done
            [[ -n "${slot}" ]] || { echo "both slots are in use; detach one first" >&2; exit 1; }
        fi
        [[ "${slot}" == 1 || "${slot}" == 2 ]] || { echo "slot must be 1 or 2" >&2; exit 2; }
        active "${slot}" && { echo "slot ${slot} is in use" >&2; exit 1; }
        command -v usbredirect >/dev/null || { echo "usbredirect not installed (package usbredir)" >&2; exit 1; }
        bus_dev=$(lsusb -d "${device}" | head -1 | awk '{print $2"/"substr($4,1,3)}')
        [[ -n "${bus_dev}" ]] || { echo "no host device ${device}" >&2; exit 1; }
        [[ -w "/dev/bus/usb/${bus_dev}" ]] || {
            echo "no write access to /dev/bus/usb/${bus_dev}; see the udev note in $0" >&2; exit 1; }
        [[ -S "$(slot_socket "${slot}")" ]] || {
            echo "no usb-redir slot at $(slot_socket "${slot}") (is the VM running with CONSOLE_USBREDIR=on?)" >&2; exit 1; }
        systemctl --user reset-failed "$(unit "${slot}")" 2>/dev/null || true
        systemd-run --user --unit "$(unit "${slot}")" --collect --quiet \
            python3 -B "${BRIDGE}" "$(slot_socket "${slot}")" "${device}"
        sleep 1
        active "${slot}" || { journalctl --user -u "$(unit "${slot}")" -n 5 --no-pager >&2; exit 1; }
        echo "slot ${slot}: ${device} attached to the guest"
        ;;
    detach)
        which="${2:-all}"
        for s in 1 2; do
            [[ "${which}" == all || "${which}" == "${s}" ]] || continue
            if active "${s}"; then systemctl --user stop "$(unit "${s}")"; echo "slot ${s}: detached"; fi
        done
        ;;
    status)
        for s in 1 2; do
            if active "${s}"; then
                echo "slot ${s}: $(systemctl --user show -p ExecStart --value "$(unit "${s}")" | grep -oE '[0-9a-fA-F]{4}:[0-9a-fA-F]{4}' | head -1)"
            else
                echo "slot ${s}: free"
            fi
        done
        ;;
    *) echo "usage: rgpu-usb.sh list|attach VID:PID [slot]|detach [slot|all]|status" >&2; exit 2 ;;
esac
