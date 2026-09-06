#!/usr/bin/env bash
# Leave the iGPU's PSP in a CLEAN state. Run this after the VM stops and before handing
# the device back to amdgpu.
#
# Why this is necessary: the guest's AMD driver creates a PSP GPCOM ring and QEMU is
# killed without ever tearing it down, so C2PMSG_64 keeps an unacknowledged
# INIT_GPCOM_RING response. Apple's psp_ring_create_11_0 only calls psp_ring_stop on its
# TEE path, so on the next boot it issues INIT_GPCOM_RING against a ring that already
# exists and the mailbox never goes ready again -- every later boot then fails at
# "psp_ring_create: KM ring creation failed" until the host is rebooted. amdgpu does this
# teardown properly on unbind, which is why exactly one guest boot works after a reboot.
#
#   sudo -A ./gpu-quiesce.sh            # SUDO_ASKPASS must point at an askpass helper
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
DEV="${DEV:-0000:7b:00.0}"
[[ $EUID -eq 0 ]] || { echo "gpu-quiesce: needs root (sudo -A $0)" >&2; exit 1; }
exec python3 - "$DEV" <<'PY'
import mmap, os, struct, sys, time
dev  = "/sys/bus/pci/devices/" + sys.argv[1]
BASE = 0x16000            # MP0_BASE__INST0_SEG0
C2PMSG_64 = BASE + 0x80
DESTROY_RINGS      = 0x00030000   # RBI/UM *and* GPCOM
DESTROY_GPCOM_RING = 0x000C0000
READY_MASK, READY_FLAG = 0x8000FFFF, 0x80000000

path = os.path.join(dev, "resource5")
try:
    size = os.path.getsize(path)
    fd = os.open(path, os.O_RDWR | os.O_SYNC)
except OSError as e:
    sys.exit(f"gpu-quiesce: cannot open BAR5 ({e}); is the device present?")
m = mmap.mmap(fd, size, prot=mmap.PROT_READ | mmap.PROT_WRITE)
off = C2PMSG_64 * 4
# Destroy unconditionally. A status-0 mailbox does NOT mean there is no ring: after a boot
# that reached ENABLE_INT, C2PMSG_64 reads 0x80050000 -- clean by every "ready" test --
# while that boot's GPCOM ring is still alive, so the next INIT_GPCOM_RING fails because
# the ring already exists.
# There are TWO rings and DESTROY_GPCOM_RING clears only one: a boot that reaches
# initialize_bgd_security also creates a UM/RBI ring, and leaving that behind makes the
# next boot fail at "psp_ring_create: UM ring creation failed".
def ctrl(cmd, what):
    before = struct.unpack_from("<I", m, off)[0]
    struct.pack_into("<I", m, off, cmd)
    v = before
    for i in range(2000):
        v = struct.unpack_from("<I", m, off)[0]
        if (v & READY_MASK) == READY_FLAG and ((v >> 16) & 0x7fff) == (cmd >> 16):
            print(f"gpu-quiesce: {what}: 0x{before:08x} -> 0x{v:08x} after {i} ms")
            return
        time.sleep(0.001)
    print(f"gpu-quiesce: WARNING {what}: 0x{before:08x} -> 0x{v:08x}, not confirmed")

ctrl(DESTROY_RINGS, "destroy all rings")
ctrl(DESTROY_GPCOM_RING, "destroy GPCOM ring")
m.flush(); m.close(); os.close(fd)
PY
