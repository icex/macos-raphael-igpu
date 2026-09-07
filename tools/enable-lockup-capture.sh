#!/usr/bin/env bash
# Turn the kernel's lockup detectors on, so the NEXT host hang leaves a backtrace.
#
# WHY THIS EXISTS
#
# The host has hard-hung three times, always with the iGPU passed through to the guest,
# and all three investigations died in the same place: there was nothing to investigate.
# The journal stops mid-line, there is no shutdown sequence, no panic, no oops, no
# machine check, and /sys/fs/pstore is empty.
#
# The second crash was blamed on journald holding up to five minutes of log in RAM, and
# enable-diagnostics.sh fixed that -- SyncIntervalSec is 1s now. The third crash happened
# anyway and STILL produced nothing, which rules that explanation out: the kernel is not
# saying anything before it dies, so there is nothing for journald to flush.
#
# That is not surprising, because this kernel has been told not to look:
#
#     $ cat /proc/cmdline
#     quiet nowatchdog splash ...
#
#     /proc/sys/kernel/nmi_watchdog        0
#     /proc/sys/kernel/watchdog            0
#     /proc/sys/kernel/hardlockup_panic    0
#     /proc/sys/kernel/hung_task_panic     0
#
# Meanwhile the kernel is built with every detector available:
#
#     CONFIG_HARDLOCKUP_DETECTOR=y      CONFIG_HARDLOCKUP_DETECTOR_PERF=y
#     CONFIG_SOFTLOCKUP_DETECTOR=y      CONFIG_DETECT_HUNG_TASK=y
#     CONFIG_EFI_VARS_PSTORE=y          (inert: ..._DEFAULT_DISABLE=y)
#
# So the machine is fully capable of noticing a CPU that has stopped responding, panicking,
# and writing the tail of the kernel log somewhere that survives a power cycle. All three
# of those are switched off. "No evidence" has been a configuration choice, not a fact
# about the failure.
#
# WHAT THIS CHANGES, in KERNEL_CMDLINE[default] in /etc/default/limine
#
#   -nowatchdog                  stop disabling the NMI/perf hard-lockup detector
#   +nmi_watchdog=panic          enable it, and panic when it fires, so a wedged CPU dies
#                                loudly instead of hanging silently
#   +efi_pstore.pstore_disable=0 the panic's dmesg tail goes to EFI variables, which
#                                survive the reboot and reappear in /sys/fs/pstore
#   +panic=20                    reboot 20s after a panic instead of sitting dead, so a
#                                hang no longer needs the reset button
#
# and, because the boot parameters alone did not stick on this kernel, a sysctl drop-in:
#
#   /etc/sysctl.d/99-lockup-capture.conf   kernel.nmi_watchdog=1
#                                          kernel.hardlockup_panic=1
#
# The first version of this script wrote "nmi_watchdog=1 hardlockup_panic=1" and both were
# silently ignored: after the reboot /proc/cmdline carried them but
# /proc/sys/kernel/nmi_watchdog and .../hardlockup_panic both still read 0. There is no
# hardlockup_panic= boot parameter -- kernel/watchdog.c registers a single __setup for
# "nmi_watchdog=" which accepts panic / nopanic / 0 / 1, and that is the only way to reach
# hardlockup_panic from the command line. The sysctl drop-in is the belt to that braces, and
# it is the part that is verifiable after the fact.
#
# WHAT IT CANNOT DO
#
# If the failure stops the CPUs or wedges the data fabric outright, no software on this
# machine can report it, and this changes nothing. That is a real possibility given the
# signature. But the hard-lockup detector runs off a performance counter NMI, which fires
# even when a CPU is spinning with interrupts disabled -- the case that is invisible today
# and would be the single most useful thing to learn. It is worth the boot-config change to
# find out which of the two we are dealing with.
#
# ONE THING TO WEIGH: efi_pstore writes to UEFI NVRAM
#
# Records are small (CONFIG_PSTORE_DEFAULT_KMSG_BYTES=10240, so ~10 KB) and pstore frees a
# record once you delete it from /sys/fs/pstore, which you should do after reading one. It
# is a standard, widely used mechanism. It does write to firmware variable storage, though,
# so if you would rather not, drop the efi_pstore.pstore_disable=0 token and keep the rest:
# you still get the panic and the auto-reboot, you just have to catch the backtrace on
# screen instead of reading it back afterwards.
#
# SAFETY
#
# This edits the kernel command line, not the kernel, so Secure Boot and Limine's blake2b
# hash pinning are not involved -- nothing needs signing and no image is regenerated.
# limine-update rewrites /boot/limine.conf from this file. The previous command line is
# backed up next to it, and Limine's limine_history entries keep the previous boot entry,
# which is the fallback if the new one misbehaves.
#
# Requires a reboot to take effect, and does nothing until then.
set -euo pipefail

DEF=/etc/default/limine
ADD=(nmi_watchdog=panic efi_pstore.pstore_disable=0 panic=20)
SYSCTL=/etc/sysctl.d/99-lockup-capture.conf

[[ $EUID -eq 0 ]] || { echo "run me with sudo" >&2; exit 1; }
[[ -f "$DEF" ]] || { echo "$DEF not found -- is this still a Limine install?" >&2; exit 1; }

command -v limine-update >/dev/null 2>&1 ||
    { echo "limine-update not found; refusing to edit $DEF with no way to apply it" >&2; exit 1; }

cp -a "$DEF" "${DEF}.pre-lockup-capture"
echo "backed up $DEF -> ${DEF}.pre-lockup-capture"

python3 - "$DEF" "${ADD[@]}" <<'PY'
import re, sys
path, add = sys.argv[1], sys.argv[2:]
src = open(path).read()

# Only the [default] entry: the fallback/LTS entries stay as they are, so there is always
# one boot option on the menu with the command line that is known to work today.
m = re.search(r'^(KERNEL_CMDLINE\[default\]\+?=")(.*)(")\s*$', src, re.M)
if not m:
    sys.exit("could not find KERNEL_CMDLINE[default] in %s -- not touching it" % path)

toks = m.group(2).split()
toks = [t for t in toks if t != 'nowatchdog']
for a in add:
    key = a.split('=')[0]
    toks = [t for t in toks if t.split('=')[0] != key]
    toks.append(a)

new = m.group(1) + ' '.join(toks) + m.group(3)
open(path, 'w').write(src[:m.start()] + new + src[m.end():])
print("new cmdline:\n    " + ' '.join(toks))
PY

cat > "$SYSCTL" <<'EOF'
# Written by macos-vm/enable-lockup-capture.sh
#
# The boot parameters alone did not stick on this kernel: /proc/cmdline carried
# nmi_watchdog=1 and hardlockup_panic=1 after a reboot while both sysctls still read 0.
# There is no hardlockup_panic= boot parameter at all, and this is the mechanism that can be
# read back and verified.
kernel.nmi_watchdog = 1
kernel.hardlockup_panic = 1
EOF
echo "wrote $SYSCTL"

# Apply now as well as at boot, and report the readback rather than assuming: if the
# perf-based detector is unavailable on this CPU, nmi_watchdog stays 0 and the whole plan
# needs rethinking, which is worth knowing immediately and not after the next hang.
sysctl -p "$SYSCTL" >/dev/null 2>&1 || true
echo "  kernel.nmi_watchdog     = $(cat /proc/sys/kernel/nmi_watchdog)"
echo "  kernel.hardlockup_panic = $(cat /proc/sys/kernel/hardlockup_panic)"
if [[ "$(cat /proc/sys/kernel/nmi_watchdog)" != 1 ]]; then
    echo "  WARNING: the hard-lockup detector did not come up; a wedged CPU will still be" >&2
    echo "           invisible. Check dmesg for 'perf' or 'watchdog' errors." >&2
fi

echo
limine-update
echo
echo "Done. Reboot to activate, then confirm it took:"
cat <<'EOF'

    grep -o 'nowatchdog' /proc/cmdline || echo "nowatchdog gone: good"
    cat /proc/sys/kernel/nmi_watchdog        # expect 1  -- 0 means no hard-lockup detector
    cat /proc/sys/kernel/hardlockup_panic    # expect 1
    cat /sys/module/pstore/parameters/backend  # expect efi_pstore, not (null)

The first two are the ones that were silently 0 the first time round. Do not trust
/proc/cmdline here: it showed the parameters while the sysctls showed 0.

After any future hang, in this order:

    ls /sys/fs/pstore/                  # a dmesg-efi-* record is the backtrace
    cat /sys/fs/pstore/dmesg-efi-*
    journalctl -k -b -1 | tail -50      # durable to 1s via enable-diagnostics.sh

Delete the pstore record once you have copied it out, or the next panic has nowhere to go:

    sudo rm /sys/fs/pstore/dmesg-efi-*

To revert: cp /etc/default/limine.pre-lockup-capture /etc/default/limine && limine-update
EOF
