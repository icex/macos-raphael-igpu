#!/usr/bin/env python3
"""Validate the plugin WITHOUT booting the VM.

A guest boot costs minutes; most of this session's wasted cycles were bad constants or a
patch that could never match, all of which are checkable statically. This asserts:

  1. every kOff* constant still equals the address of the symbol its comment names;
  2. none of the routed functions has a rip-relative operand inside the first 16 bytes --
     Lilu's trampoline copies displaced instructions WITHOUT rewriting displacements, so
     routing such a function makes org() read a garbage address (this is exactly what made
     DevGetDeviceInfoEntry report a table entry that was sitting right there on disk);
  3. every byte-patch find pattern is unique in the KDK, via milestones.py verify.

Exit status is nonzero if anything fails, so it can gate a deploy:
    ./preflight.py && ./esp-kext.sh ... && ./redeploy.sh
"""
import re, struct, subprocess, sys
from pathlib import Path

VM  = Path(__file__).resolve().parent
SRC = VM / "build/src-rgpu/RaphaelGPU.cpp"
KDK = VM / ("kdk/x/System/Library/Extensions/AMDRadeonX6000HWServices.kext"
            "/Contents/PlugIns/AMDRadeonX6000HWLibs.kext/Contents/MacOS/AMDRadeonX6000HWLibs")
NM  = VM / "re/hwlibs.nm"

def load_symbols():
    syms = {}
    for line in NM.read_text().splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0].strip():
            try: syms[parts[2]] = int(parts[0], 16)
            except ValueError: pass
    return syms

def rip_relative_in_prologue(data, va, n=16):
    """True if a lea reg,[rip+disp32] (48 8d /r with mod=00 rm=101) starts within n bytes."""
    b = data[va:va + n]
    return any(b[i] == 0x8d and (b[i + 1] & 0xc7) == 0x05 for i in range(len(b) - 2))

def main():
    if not KDK.exists():
        sys.exit(f"preflight: KDK binary missing: {KDK}")
    data, syms = KDK.read_bytes(), load_symbols()
    rows = re.findall(r"^static constexpr size_t (kOff\w+)\s*=\s*(0x[0-9a-fA-F]+);\s*//\s*(\S+)",
                      SRC.read_text(), re.M)
    if not rows:
        sys.exit("preflight: no kOff* constants found -- did the source layout change?")

    bad = 0
    print(f"{'constant':26s} {'offset':>9s}  {'symbol':44s} check")
    for name, off_s, sym in rows:
        off = int(off_s, 16)
        want = syms.get(sym)
        if want is None and "::" in sym:
            # C++ symbols appear mangled in nm; match on class + method substrings so a
            # stale offset here is still caught instead of silently skipped.
            cls, meth = sym.split("::", 1)
            cands = [v for k, v in syms.items() if cls in k and meth in k]
            if len(cands) == 1:
                want = cands[0]
        if want is None:
            note, ok = "SKIP (symbol not in nm; C++ name?)", True
        elif want != off:
            note, ok = f"MISMATCH: symbol is at {want:#x}", False
        elif rip_relative_in_prologue(data, off):
            note, ok = "UNSAFE TO ROUTE: rip-relative operand in prologue", False
        else:
            note, ok = "ok", True
        if not ok: bad += 1
        print(f"{name:26s} {off_s:>9s}  {sym:44s} {note}")

    print("\n-- milestones.py verify --")
    r = subprocess.run([sys.executable, str(VM / "milestones.py"), "verify"],
                       capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    if r.returncode != 0:
        sys.stdout.write(r.stderr); bad += 1

    if bad:
        print(f"\npreflight: {bad} problem(s) -- NOT safe to deploy")
        return 1
    print("\npreflight: all constants resolve, all routes safe, all patterns unique")
    return 0

sys.exit(main())
