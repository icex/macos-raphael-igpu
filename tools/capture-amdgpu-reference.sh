#!/usr/bin/env bash
# Capture how amdgpu drives this iGPU, to use as the reference the guest is missing.
#
# RUN THIS RIGHT AFTER A BOOT, BEFORE gpu-bind.sh.
#
# WHY
#
# Two things are needed and both require the iGPU to be bound to amdgpu and working, which is
# only true between boot and the first gpu-bind.sh:
#
#   1. The connector topology. The iGPU's VBIOS has NO display object info table -- master
#      data table index 16 reads 0x0000 -- so Apple's AmdAtomObjectInfo_V1_4 parses an absent
#      table, every device_tag is zero, no connector survives, and all three framebuffers
#      report "Driver is offline". A monitor on the HDMI port stays dark. The fix is to
#      synthesise a display_object_info_table_v1_4 the way mkrom.py already synthesises
#      vram_info, but the content must be correct: a wrong atom_display_object_path_v2 fails
#      as memory corruption, not as an error, so the object ids cannot be guessed. amdgpu
#      does enumerate this board's connectors, so amdgpu is the ground truth.
#
#   2. The register reference. Every register value in this project came from inside the
#      guest, where nothing works. hostregs.py can read the same registers whatever driver
#      owns the device, but it has never been run against a WORKING configuration. The
#      specific question: the microengine program counters read MEC1 = 0x44a and MEC2 = 0x44c
#      in the guest and never advance. They are not zero -- a cold device reads 0 -- so the
#      engines ran their boot and parked. If amdgpu shows the same parked values while idle,
#      the guest's CP is in its normal idle state and the blocker is only that no work
#      reaches it. If amdgpu shows something else, the guest's CP is genuinely wrong.
#
# WHY NOT JUST HAND THE DEVICE BACK
#
# Because rebinding to vfio-pci afterwards is the cycle that wedges the device until a
# reboot, and because gpu-restore.sh would hand amdgpu a GPU whose GMC the guest has
# rewritten. A boot gives a clean amdgpu initialisation for free.
#
# Reads only. Writes nothing to the device.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

DEV=0000:7b:00.0
OUT=findings/hw
mkdir -p "$OUT"

drv="$(basename "$(readlink -f "/sys/bus/pci/devices/${DEV}/driver")" 2>/dev/null || echo none)"
echo "iGPU ${DEV} driver in use: ${drv}"
if [[ "$drv" != amdgpu ]]; then
    cat >&2 <<EOF

REFUSING: the iGPU is on '${drv}', not amdgpu, so there is no working configuration to read.

Reboot and run this before ./gpu-bind.sh. Do not try to get here with gpu-restore.sh: that
hands amdgpu a GPU the guest has reprogrammed, and rebinding to vfio-pci afterwards is the
cycle that wedges the device until a reboot.
EOF
    exit 1
fi

# Which DRM card is the iGPU? Match by the PCI path rather than assuming card0/card1 --
# connector names and card numbers both shift across boots on this machine.
card=""
for c in /sys/class/drm/card[0-9]*; do
    [[ -e "$c/device" ]] || continue
    if [[ "$(basename "$(readlink -f "$c/device")")" == "$DEV" ]]; then
        card="$(basename "$c")"; break
    fi
done
[[ -n "$card" ]] || { echo "could not find a DRM card for ${DEV}" >&2; exit 1; }
echo "DRM card: ${card}"

{
    echo "# amdgpu reference for ${DEV}, captured $(date -Is)"
    echo "# kernel: $(uname -r)"
    echo
    echo "## connectors"
    for c in /sys/class/drm/${card}-*/; do
        [[ -d "$c" ]] || continue
        n="$(basename "$c")"
        st="$(cat "$c/status" 2>/dev/null || echo '?')"
        en="$(cat "$c/enabled" 2>/dev/null || echo '?')"
        dpms="$(cat "$c/dpms" 2>/dev/null || echo '?')"
        edid_sz=$(stat -c %s "$c/edid" 2>/dev/null || echo 0)
        printf '%-28s status=%-12s enabled=%-8s dpms=%-4s edid=%s bytes\n' \
               "$n" "$st" "$en" "$dpms" "$edid_sz"
        if [[ "$edid_sz" != 0 ]]; then
            echo "    edid hex:"
            xxd -p "$c/edid" 2>/dev/null | sed 's/^/      /'
        fi
    done
    echo
    echo "## amdgpu kernel log for this device"
    journalctl -k -b --no-pager 2>/dev/null | grep "amdgpu ${DEV}" || echo "(none)"
} > "$OUT/amdgpu-connectors.txt" 2>&1
echo "wrote $OUT/amdgpu-connectors.txt"

echo
echo "## register reference (16 samples, so moving registers are visible)"
if [[ -x ./hostregs.py ]]; then
    ./hostregs.py --watch 16 > "$OUT/amdgpu-regs.txt" 2>&1 && {
        echo "wrote $OUT/amdgpu-regs.txt"
        grep -E 'INSTR_PNTR|RLC_STAT|CP_MEC_CNTL|IC_BASE|FB_LOCATION|FB_OFFSET' \
             "$OUT/amdgpu-regs.txt" | sed 's/^/  /'
    } || { echo "hostregs.py failed (needs root for the register BAR):" >&2
           tail -3 "$OUT/amdgpu-regs.txt" >&2; }
else
    echo "hostregs.py missing or not executable" >&2
fi

cat <<'EOF'

Done. The two questions this answers:

  * which connectors amdgpu finds, and whether the attached monitor's EDID is readable --
    the input to synthesising display_object_info_table_v1_4
  * whether CP_MEC1/2_INSTR_PNTR read 0x44a / 0x44c here too, which decides whether the
    guest's parked microengines are in their normal idle state or a wrong one

Then carry on as usual:

    SUDO_ASKPASS=$SUDO_ASKPASS sudo -A ./gpu-bind.sh
    QUIESCE=1 ./redeploy.sh --gpu
EOF
