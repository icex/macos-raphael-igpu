#!/usr/bin/env bash
# Undo enable-early-vfio.sh: give the iGPU back to amdgpu at boot.
#
# WHY
#
# The host has hard-hung twice with the VM running and the iGPU passed through. Both times
# the evidence is identical and useless: the journal stops mid-line, with no shutdown
# sequence, no panic, no oops, and /sys/fs/pstore empty. What differs is how long each
# configuration survived.
#
#   amdgpu binds at boot, gpu-bind.sh hands the device over afterwards
#       ~33 VM launches across three hours before the host died (boot -3, 01:22)
#
#   vfio-pci claims the device from boot, so it reaches the guest exactly as the system
#   firmware left it -- never initialised or quiesced by any driver
#       53 seconds into the FIRST launch (boot -1, 12:39)
#
# That is not a proven mechanism and is not offered as one; the evidence needed to find the
# mechanism was never captured, and enable-diagnostics.sh exists to fix that. It is enough
# to say the virgin path is far more dangerous, and it bought nothing -- the host died before
# the guest kernel even loaded, so it never told us whether the command processor would have
# been usable.
#
# WHAT THIS UNDOES
#
#   /etc/modprobe.d/vfio-igpu.conf   removed
#   /etc/mkinitcpio.conf             MODULES restored from the backup enable- wrote
#   initramfs + /boot/limine.conf    regenerated together by limine-mkinitcpio
#
# After the reboot the iGPU is back on amdgpu and gpu-bind.sh is needed again before
# ./redeploy.sh, which is what redeploy.sh's guard now insists on.
set -euo pipefail

CONF=/etc/modprobe.d/vfio-igpu.conf
MKI=/etc/mkinitcpio.conf

[[ $EUID -eq 0 ]] || { echo "run me with sudo" >&2; exit 1; }

if [[ -f "$CONF" ]]; then
    rm -f "$CONF"
    echo "removed $CONF"
else
    echo "$CONF already absent"
fi

if [[ -f "${MKI}.pre-vfio" ]]; then
    cp -a "${MKI}.pre-vfio" "$MKI"
    echo "restored $MKI from ${MKI}.pre-vfio"
else
    # No backup: strip only what enable- added, leaving anything else in MODULES alone.
    sed -i -E 's/^MODULES=\(vfio_pci vfio vfio_iommu_type1 ?(.*)\)$/MODULES=(\1)/' "$MKI"
    echo "no backup found; removed the vfio modules from $MKI by hand"
fi
grep -E '^MODULES' "$MKI"

# Same reason as in enable-early-vfio.sh: limine.conf pins each initramfs by blake2b hash,
# so the image and the pin have to be regenerated together or Limine refuses the entry.
limine-mkinitcpio

cat <<'EOF'

Done. Reboot to activate.

After the reboot:

    lspci -nnks 7b:00.0 | grep 'driver in use'      # expect amdgpu
    SUDO_ASKPASS=/tmp/askpass.sh sudo -A ./gpu-bind.sh
    ./redeploy.sh
EOF
