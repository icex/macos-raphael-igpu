#!/usr/bin/env bash
# Make the next host hang leave evidence behind.
#
# THE PROBLEM THIS SOLVES
#
# The host has hard-hung twice with the VM running and the iGPU passed through, and both
# times the investigation hit a wall in the same place: there was nothing to investigate.
#
#   - the journal stops mid-line, with no shutdown sequence -- so it was a hard hang or
#     reset, not a clean stop
#   - no panic, no oops, no BUG, no machine-check anywhere in the surviving log
#   - /sys/fs/pstore is empty, so no dmesg tail was persisted
#   - journald's SyncIntervalSec defaults to FIVE MINUTES, so up to five minutes of kernel
#     log was sitting in RAM when the machine died, and went with it
#
# The last point is the important one. Whatever the kernel did or did not manage to say, we
# would never have seen it. Two crashes produced zero diagnostic information, which is why
# the root cause is still unknown.
#
# WHAT THIS CHANGES
#
#   journald SyncIntervalSec=1s     kernel messages reach disk within a second instead of
#                                   being held for five minutes
#   journald Storage=persistent     never fall back to volatile storage
#   efi_pstore loaded at boot       a panic's dmesg tail is written to EFI variables, which
#                                   survive a power cycle; pstore_dump then appears under
#                                   /sys/fs/pstore on the next boot
#
# efi_pstore only helps for a hang the kernel notices -- a panic or an oops. A fabric-level
# lockup that stops the CPU dead will still leave nothing, and no software can change that.
# The journald change is what covers the rest: if the kernel says anything at all in the
# seconds before it dies, it will be on disk.
#
# All of it is reversible: rm the two drop-ins and reload.
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "run me with sudo" >&2; exit 1; }

install -d /etc/systemd/journald.conf.d
cat > /etc/systemd/journald.conf.d/10-crash-durability.conf <<'EOF'
# Written by macos-vm/enable-diagnostics.sh
#
# The default SyncIntervalSec is 5 minutes. Two host hangs during GPU-passthrough work left
# no kernel log at all because of it. One second costs nothing on NVMe and means a hang is
# diagnosable.
[Journal]
Storage=persistent
SyncIntervalSec=1s
EOF
echo "wrote /etc/systemd/journald.conf.d/10-crash-durability.conf"

cat > /etc/modules-load.d/pstore.conf <<'EOF'
# Written by macos-vm/enable-diagnostics.sh
# Persist a panic's dmesg tail into EFI variables, so it survives the power cycle and shows
# up under /sys/fs/pstore on the next boot.
efi_pstore
EOF
echo "wrote /etc/modules-load.d/pstore.conf"

systemctl restart systemd-journald
modprobe efi_pstore 2>/dev/null || echo "note: efi_pstore did not load now; it will at next boot"

echo
echo "journald sync interval now:"
systemd-analyze cat-config systemd/journald.conf 2>/dev/null | grep -iE 'SyncIntervalSec|Storage' | tail -4
echo "pstore backend: $(cat /sys/module/pstore/parameters/backend 2>/dev/null || echo '(none yet)')"
echo
cat <<'EOF'
Active now, no reboot needed. After any future hang, look for:

    ls /sys/fs/pstore/                  # a dmesg-efi-* file if the kernel panicked
    journalctl -k -b -1 | tail -50      # now durable to within a second of the hang
    tr -d '\r' < run/serial.log | tail  # guest side, fsynced per chunk since this change

One thing this deliberately does NOT change: the kernel command line still carries
"nowatchdog", so a hang cannot self-recover and needs the reset button. Turning the
watchdog back on would let the machine reboot itself instead of sitting frozen, but that is
a boot-config change on a Secure Boot install with hash-pinned images, so it is left as a
decision rather than done here.
EOF
