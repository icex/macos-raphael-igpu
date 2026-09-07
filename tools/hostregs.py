#!/usr/bin/env python3
"""Read the iGPU's CP and RLC registers from the host, through BAR5.

WHY THIS EXISTS

Every register value this project has collected comes from inside the guest, where nothing
works. The same silicon runs correctly on the host, under amdgpu, a few seconds after every
boot -- so the host is a reference implementation sitting right there, and we have never once
read it.

The question it is built to answer: the microengine program counters read MEC1 = 0x44a and
MEC2 = 0x44c in the guest and never advance, which was long recorded as "the CP never
executes". They are not zero, though -- a cold device reads 0 -- so the engines did run their
boot and park. If the host reads the SAME parked values while idle, then the guest's CP is in
its normal idle state and the blocker is only that no work ever reaches it, which is software
we control. If the host reads something different, the guest's CP is genuinely wrong.

HOW

BAR5 is the 512 KB register aperture. Registers are addressed by dword index, and a SOC15
index is base_table[BASE_IDX] + reg -- the same arithmetic the in-guest plugin uses, with
GC segment 0 at 0x1260 and segment 1 at 0xa000. So the byte offset into BAR5 is
(base + reg) * 4, and every register below is inside the aperture, so none of them need the
indirect PCIE index/data path.

    sudo ./hostregs.py                  # read whatever driver currently owns 7b:00.0
    sudo ./hostregs.py --watch 20       # 20 samples, to see which registers move

Reads only. No writes, ever -- this runs against a live driver, and the point is to observe
a working configuration, not to perturb it.
"""
import argparse
import glob
import mmap
import os
import sys

DEV = "0000:7b:00.0"
BAR = 5
GC_SEG0 = 0x1260
GC_SEG1 = 0xA000

# name, base, reg
REGS = [
    ("GRBM_STATUS",            GC_SEG0, 0x0DA4),
    ("GRBM_STATUS2",           GC_SEG0, 0x0DA2),
    ("CP_MEC_CNTL",            GC_SEG0, 0x0F55),
    ("CP_ME_CNTL",             GC_SEG0, 0x0F56),
    ("CP_MEC1_INSTR_PNTR",     GC_SEG0, 0x0F48),
    ("CP_MEC2_INSTR_PNTR",     GC_SEG0, 0x0F49),
    ("CP_PFP_INSTR_PNTR",      GC_SEG0, 0x0F45),
    ("CP_ME_INSTR_PNTR",       GC_SEG0, 0x0F46),
    ("CP_CE_INSTR_PNTR",       GC_SEG0, 0x0F47),
    ("CP_STAT",                GC_SEG0, 0x0F40),
    ("CP_CPC_BUSY_STAT",       GC_SEG0, 0x0E25),
    ("CP_CPF_BUSY_STAT",       GC_SEG0, 0x0E28),
    ("GCMC_VM_FB_LOCATION_BASE", GC_SEG0, 0x16FC),
    ("GCMC_VM_FB_LOCATION_TOP",  GC_SEG0, 0x16FD),
    ("GCMC_VM_FB_OFFSET",      GC_SEG0, 0x16E7),
    ("CP_CPC_IC_BASE_LO",      GC_SEG1, 0x584C),
    ("CP_CPC_IC_BASE_HI",      GC_SEG1, 0x584D),
    ("CP_CPC_IC_BASE_CNTL",    GC_SEG1, 0x584E),
    ("CP_CPC_IC_OP_CNTL",      GC_SEG1, 0x584F),
    ("RLC_CNTL",               GC_SEG1, 0x4C00),
    ("RLC_STAT",               GC_SEG1, 0x4C04),
    ("RLC_GPM_STAT",           GC_SEG1, 0x4E6E),
    ("RLC_SAFE_MODE",          GC_SEG1, 0x4CA0),
    ("RLC_SRM_CNTL",           GC_SEG1, 0x4C80),
    ("RLC_RLCS_BOOTLOAD_STATUS", GC_SEG1, 0x4E8D),
    ("SCRATCH_REG0",           GC_SEG1, 0x2040),
]

RLC_STAT_BITS = ["RLC_BUSY", "RLC_SRM_BUSY", "RLC_GPM_BUSY", "RLC_SPM_BUSY",
                 "MC_BUSY", "THREAD_0_BUSY", "THREAD_1_BUSY", "THREAD_2_BUSY"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", type=int, default=1,
                    help="samples to take; >1 reports which registers changed")
    ap.add_argument("--device", default=DEV)
    ap.add_argument("--via-debugfs", action="store_true",
                    help="read through amdgpu's debugfs register window (required while "
                         "amdgpu owns the device; needs debugfs mounted and root)")
    a = ap.parse_args()

    base = f"/sys/bus/pci/devices/{a.device}"
    try:
        driver = os.path.basename(os.path.realpath(f"{base}/driver"))
    except OSError:
        driver = "(none)"

    if a.via_debugfs:
        # amdgpu exposes its own register window: position is the byte offset of the dword
        # index, i.e. (base + reg) * 4 -- the same SOC15 arithmetic as the raw BAR path.
        cands = sorted(glob.glob("/sys/kernel/debug/dri/*/amdgpu_regs"))
        target = None
        for c in cands:
            dri = os.path.dirname(c)
            link = os.path.join(dri, "device")
            try:
                if os.path.basename(os.path.realpath(link)) == a.device:
                    target = c; break
            except OSError:
                continue
        if target is None:
            sys.exit("no amdgpu_regs under /sys/kernel/debug/dri/* for "
                     f"{a.device} (debugfs mounted? is amdgpu bound? are you root?)")
        print(f"device {a.device}, driver in use: {driver}, via {target}")
        print()
        with open(target, "rb", buffering=0) as rf:
            def rdd(bse, reg):
                try:
                    rf.seek((bse + reg) * 4)
                    b = rf.read(4)
                    return int.from_bytes(b, "little") if len(b) == 4 else None
                except OSError:
                    return None
            samples = [{n: rdd(b, r) for n, b, r in REGS} for _ in range(max(1, a.watch))]
        report(samples)
        return

    path = f"{base}/resource{BAR}"
    size = os.path.getsize(path)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_SYNC)
    except PermissionError:
        sys.exit("need root to read the register BAR (run with sudo)")
    mm = mmap.mmap(fd, size, mmap.MAP_SHARED, mmap.PROT_READ)

    def rd(bse, reg):
        off = (bse + reg) * 4
        if off + 4 > size:
            return None
        return int.from_bytes(mm[off:off + 4], "little")

    # A BAR read of all-ones is a non-responding aperture, not data.
    #
    # This tool works while vfio-pci owns the device and returns sane values. Under amdgpu it
    # returned 0xffffffff for every register, and the first version happily printed those --
    # even decoding RLC_STAT = 0xffffffff as "every bit busy", which reads like a finding and
    # is nothing of the kind. Refuse to interpret it. amdgpu claims the MMIO region, so the
    # correct interface there is its own debugfs window, not a raw resource mmap.
    probe = [rd(b, r) for _, b, r in REGS[:6]]
    if probe and all(v == 0xFFFFFFFF for v in probe if v is not None):
        mm.close(); os.close(fd)
        sys.exit(
            f"every register reads 0xffffffff: BAR{BAR} is not responding under driver "
            f"'{driver}'.\n"
            "This is not data and must not be recorded as a reference. Under amdgpu use its\n"
            "debugfs register window instead, which respects the driver's own MMIO claim:\n"
            "  sudo ./hostregs.py --via-debugfs\n"
            "Under vfio-pci the raw BAR mmap works and this message should not appear.")

    print(f"device {a.device}, driver in use: {driver}, BAR{BAR} = {size} bytes")
    print()

    samples = []
    for _ in range(max(1, a.watch)):
        samples.append({n: rd(b, r) for n, b, r in REGS})

    report(samples)
    mm.close()
    os.close(fd)


def report(samples):
    first, last = samples[0], samples[-1]
    for name, b, r in REGS:
        v = first[name]
        if v is None:
            print(f"  {name:<28} <outside BAR>")
            continue
        moved = ""
        if len(samples) > 1:
            vals = {s[name] for s in samples}
            if len(vals) > 1:
                moved = f"  MOVES ({len(vals)} distinct, last {last[name]:#x})"
        note = ""
        if name == "RLC_STAT":
            on = [RLC_STAT_BITS[i] for i in range(8) if (v >> i) & 1]
            note = "  " + (" | ".join(on) if on else "(nothing busy)")
        print(f"  {name:<28} {v:#010x}{note}{moved}")

    lo, hi = first["CP_CPC_IC_BASE_LO"], first["CP_CPC_IC_BASE_HI"]
    fbb, fbo = first["GCMC_VM_FB_LOCATION_BASE"], first["GCMC_VM_FB_OFFSET"]
    if None not in (lo, hi, fbb, fbo):
        ic = (hi << 32) | lo
        print()
        print(f"  CP_CPC_IC_BASE = {ic:#x}")
        print(f"  FB_LOCATION_BASE = {(fbb & 0xffffff) << 24:#x}   "
              f"FB_OFFSET = {(fbo & 0xffffff) << 24:#x}")


if __name__ == "__main__":
    main()
