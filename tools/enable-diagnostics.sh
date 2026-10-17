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

systemctl restart systemd-journald

echo
echo "journald now:"
systemd-analyze cat-config systemd/journald.conf 2>/dev/null |
    grep -E '^(SyncIntervalSec|Storage)=' | tail -4

# pstore: present, and off, and it takes a boot-config change to turn on.
#
# This kernel has CONFIG_EFI_VARS_PSTORE=y but also
# CONFIG_EFI_VARS_PSTORE_DEFAULT_DISABLE=y, so efi_pstore is built in and deliberately
# inert -- /sys/module/pstore/parameters/backend reads (null) and modprobe is a no-op
# because there is no module to load. It cannot be enabled from userspace; it needs
# efi_pstore.pstore_disable=0 on the kernel command line. Say so plainly rather than
# writing a modules-load.d drop-in that would look like it had done something.
backend="$(cat /sys/module/pstore/parameters/backend 2>/dev/null || echo '(none)')"
echo "pstore backend: ${backend}"
if [[ "$backend" == "(null)" || "$backend" == "(none)" ]]; then
    cat <<'EOF'

pstore is NOT capturing anything, and this script cannot change that. The kernel is built
with CONFIG_EFI_VARS_PSTORE_DEFAULT_DISABLE=y, so efi_pstore is compiled in but inert until
the command line says otherwise. To turn it on, add to KERNEL_CMDLINE[default] in
/etc/default/limine:

    efi_pstore.pstore_disable=0

then run limine-update and reboot. That is a boot-config change on a Secure Boot install
with hash-pinned images, so it is left as your decision rather than done here -- and it only
helps for a hang the kernel actually notices (a panic or oops). A fabric-level lockup that
stops the CPU dead leaves nothing either way.
EOF
fi

cat <<'EOF'

The journald change is active now, no reboot needed, and it is the one that matters: the
kernel log is durable to within a second of a hang instead of losing up to five minutes.

After any future hang, look in this order:

    journalctl -k -b -1 | tail -50      # now durable to within a second
    tr -d '\r' < run/serial.log | tail  # guest side, fsynced per chunk
    ls /sys/fs/pstore/                  # only if the cmdline change above was made

Also unchanged, deliberately: the command line carries "nowatchdog", so a hang cannot
self-recover and needs the reset button.
EOF
