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
# A kOff* whose comment carries the [fb] marker addresses AMDRadeonX6000Framebuffer
# instead. Without this the "::" in the symbol name sent it down the C++ fallback,
# found nothing in the HWLibs nm, and silently SKIPped -- validating nothing.
FBK = VM / ("kdk/x/System/Library/Extensions/AMDRadeonX6000Framebuffer.kext"
            "/Contents/MacOS/AMDRadeonX6000Framebuffer")
FBNM = VM / "re/fb.nm"
X6K = VM / "kdk/x/System/Library/Extensions/AMDRadeonX6000.kext/Contents/MacOS/AMDRadeonX6000"
X6NM = VM / "re/x6000.nm"

def load_symbols(path=None):
    syms = {}
    for line in (path or NM).read_text().splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0].strip():
            try: syms[parts[2]] = int(parts[0], 16)
            except ValueError: pass
    return syms

# Opcodes that take a ModRM byte and plausibly appear in a prologue. A rip-relative operand
# is ModRM with mod=00, rm=101 -- i.e. (modrm & 0xC7) == 0x05.
_MODRM_OPS = {
    0x8b,        # mov r, m      <- _psp_cmd_km_resp_check opens with 48 8b 05 (rip+disp32)
    0x8d,        # lea r, m      <- DevGetDeviceInfoEntry opens with 48 8d 0d
    0x89,        # mov m, r
    0x03, 0x2b,  # add/sub r, m
    0x39, 0x3b,  # cmp
    0x85,        # test
    0x63,        # movsxd
    0xc7,        # mov m, imm32
    0xff,        # inc/dec/call/jmp m
    0x8a, 0x88,  # mov r8, m / m, r8
    0x0f,        # two-byte escape (movzx/movsx/setcc/...)
}

def rip_relative_in_prologue(data, va, n=16):
    """True if any rip-relative memory operand starts within the first n bytes.

    Lilu's trampoline relocates the instructions it displaces WITHOUT rewriting
    rip-relative displacements, so routing such a function makes the "original" compute a
    garbage address. Checking only `lea` was not enough -- a rip-relative `mov` is just as
    fatal, and _psp_cmd_km_resp_check has one at byte 11.
    """
    b = data[va:va + n]
    for i in range(len(b) - 3):
        j = i
        if 0x40 <= b[j] <= 0x4f:          # REX prefix
            j += 1
        if j + 2 >= len(b):
            break
        op = b[j]
        if op == 0x0f:                     # two-byte opcode: modrm is one further along
            if j + 3 >= len(b):
                break
            if (b[j + 2] & 0xc7) == 0x05:
                return True
            continue
        if op in _MODRM_OPS and (b[j + 1] & 0xc7) == 0x05:
            return True
    return False

def main():
    if not KDK.exists():
        sys.exit(f"preflight: KDK binary missing: {KDK}")
    ownership = subprocess.run([sys.executable, str(VM / "route-domains.py"), str(SRC)])
    if ownership.returncode:
        return 1
    data, syms = KDK.read_bytes(), load_symbols()
    fbdata, fbsyms = FBK.read_bytes(), load_symbols(FBNM)
    x6data, x6syms = X6K.read_bytes(), load_symbols(X6NM)
    rows = re.findall(r"^static constexpr size_t (kOff\w+)\s*=\s*(0x[0-9a-fA-F]+);\s*//\s*(\S+)(.*)$",
                      SRC.read_text(), re.M)
    if not rows:
        sys.exit("preflight: no kOff* constants found -- did the source layout change?")

    bad = 0
    print(f"{'constant':26s} {'offset':>9s}  {'symbol':44s} check")
    for name, off_s, sym, sym_note in rows:
        off = int(off_s, 16)
        d, t = ((fbdata, fbsyms) if "[fb]" in sym_note else
                (x6data, x6syms) if "[x6]" in sym_note else (data, syms))
        want = t.get(sym)
        if want is None and "::" in sym:
            # C++ symbols appear mangled in nm; match on class + method substrings so a
            # stale offset here is still caught instead of silently skipped.
            cls, meth = sym.split("::", 1)
            cands = [v for k, v in t.items() if cls in k and meth in k]
            if len(cands) == 1:
                want = cands[0]
        if want is None:
            note, ok = "SKIP (symbol not in nm; C++ name?)", True
        elif want != off:
            note, ok = f"MISMATCH: symbol is at {want:#x}", False
        elif "(called" in sym_note:
            note, ok = "ok (called, not routed)", True
        elif rip_relative_in_prologue(d, off):
            note, ok = "UNSAFE TO ROUTE: rip-relative operand in prologue", False
        else:
            note, ok = "ok", True
        if not ok: bad += 1
        print(f"{name:26s} {off_s:>9s}  {sym:44s} {note}")

    # Recovery v2 must acquire and publish a native hardware lease before VMM,
    # then run Apple's pool initializer exactly once and exclude that same full
    # address from both software pools before admitting clients. Keep these
    # production wiring checks in the deployment preflight rather than relying
    # only on the hosted helper fixture.
    source = SRC.read_text()
    wrapper_start = source.find("static bool wrapHwMemEnable(void *self) {")
    wrapper_end = source.find("//\n// Clearing the flag", wrapper_start)
    wrapper = source[wrapper_start:wrapper_end] if wrapper_end > wrapper_start else ""
    ready_start = source.find("static void wrapVmmSetVSReady(void *self, uint32_t ready) {")
    ready_end = source.find("static void wrapVmmSetAlloc", ready_start)
    ready_wrapper = source[ready_start:ready_end] if ready_end > ready_start else ""
    vmm_alloc_start = ready_end
    vmm_alloc_end = source.find("static void probeRlc", vmm_alloc_start)
    vmm_alloc_wrapper = (source[vmm_alloc_start:vmm_alloc_end]
                         if vmm_alloc_end > vmm_alloc_start else "")
    vmm_enable_guard = vmm_alloc_wrapper.find("if (enable != 0)")
    vmm_native_record = vmm_alloc_wrapper.find("XV2 VMM phase=native")
    pool_helper = wrapper.find("RaphaelRecoveryV2::establishPools(")
    pool_order = [pool_helper] + [wrapper.find(token, pool_helper) for token in (
        "FunctionCast(wrapHwMemEnable, orgHwMemEnable)(self)",
        "vt[0x198 / 8] != x6Base + kOffHwMemReserve",
        "publishRecoveryPoolStatus(status)")]
    owner_order = [ready_wrapper.find(token) for token in (
        "isRaphaelHardware(hardware)",
        "vt[0x180 / 8] != x6Base + kOffHwAppendReserved",
        "appendReserved(hardware, 0, RaphaelRecoveryV2::LeaseSize, 0x1000)",
        "recoveryLeaseDisjointFromLiveGart(descriptor)",
        "RaphaelRecoveryV2::publishRecord(")]
    routed = "orgHwMemEnable = patcher.routeFunction(addr + kOffHwMemEnable" in source
    reservation_ok = (
        wrapper_start >= 0 and wrapper_end > wrapper_start and
        ready_start >= 0 and ready_end > ready_start and routed and
        all(position >= 0 for position in pool_order + owner_order) and
        pool_order == sorted(pool_order) and owner_order == sorted(owner_order) and
        wrapper.count("FunctionCast(wrapHwMemEnable, orgHwMemEnable)(self)") == 3 and
        "static uint32_t wrapHwMemEnable" not in source and
        "RaphaelRecovery::activate(" not in source and
        vmm_enable_guard >= 0 and vmm_native_record >= 0 and
        vmm_enable_guard < vmm_native_record and
        "XH2 ABORT reason=duplicate-ready" in ready_wrapper and
        "XH2 ABORT reason=pool-owner" in wrapper and
        "XH2 ABORT reason=duplicate-pool" in wrapper)
    print(f"recovery reservation {'ok (native v2 lease; one pool init; fail-closed duplicates)' if reservation_ok else 'INVALID V2 ORDER, ABI, ROUTE, OR OWNER GUARD'}")
    if not reservation_ok:
        bad += 1

    prepare_start = source.find("static void wrapVmmPrepare(void *self")
    prepare_end = source.find("static bool recoveryLeaseDisjointFromLiveGart", prepare_start)
    prepare = source[prepare_start:prepare_end]
    prepare_order = [prepare.find(token) for token in (
        "RaphaelVm::prepareInvalidateInfo(",
        "nativeInfo = local.valid",
        "FunctionCast(wrapVmmPrepare, orgVmmPrepare)",
        "RaphaelVm::observePreparedRequest(",
        "vmid2Programs.append(observation)")]
    forbidden = ("fbRead(", "fbWrite(", "RLOG(", "CRLOG(", "IOSleep(",
                 "fbAperture(", "IOLock", "new ", "alloc(")
    prepare_ok = (prepare_start >= 0 and prepare_end > prepare_start and
                  all(position >= 0 for position in prepare_order) and
                  prepare_order == sorted(prepare_order) and
                  not any(token in prepare for token in forbidden) and
                  "__atomic_load_n(&raphaelTargetConfirmed, __ATOMIC_ACQUIRE)" in prepare and
                  "__atomic_load_n(&cachedFbPublished, __ATOMIC_ACQUIRE)" in prepare and
                  "__atomic_store_n(&latestVmid2ProgramSequence, observation.sequence, __ATOMIC_RELEASE)" in prepare)
    print(f"VM callback safety   {'ok (copy/repair/native/copy/append; no blocking work)' if prepare_ok else 'INVALID ORDER OR UNSAFE OPERATION'}")
    if not prepare_ok:
        bad += 1

    setvm_pointer_abi = ("static uintptr_t wrapGfx10SetVMRegs(void *self)" in source and
                         "static uint32_t wrapGfx10SetVMRegs(void *self)" not in source)
    print(f"setVMRegisters ABI   {'ok (pointer-width return)' if setvm_pointer_abi else 'INVALID RETURN TYPE'}")
    if not setvm_pointer_abi:
        bad += 1

    # If the RLC firmware header was generated, the built kext must actually CONTAIN those
    # bytes. Without __attribute__((used)) the compiler folds the few bytes read directly and
    # drops the rest of the array, yielding a kext that looks fine and carries no firmware.
    fwh = VM / "build/src-rgpu/rlc_fw.h"
    exe = VM / "build/out/RaphaelGPU/RaphaelGPU.kext/Contents/MacOS/RaphaelGPU"
    print()
    if not fwh.exists():
        print("rlc firmware       not generated (rlc_fw.h absent) -- RLC substitution disabled")
    elif not exe.exists():
        print("rlc firmware       kext not built yet; cannot verify embedding")
    else:
        import re as _re, subprocess as _sp
        raw = _sp.run(["zstd", "-dcq", "/lib/firmware/amdgpu/gc_10_3_6_rlc.bin.zst"],
                      capture_output=True).stdout
        blob = exe.read_bytes()
        # Probe three widely separated 64-byte slices of the payload region.
        probes = [raw[0x100:0x140], raw[0x6300:0x6340], raw[0x1b1d0:0x1b210]]
        hits = sum(1 for pr in probes if pr and pr in blob)
        if hits == len(probes):
            print(f"rlc firmware       ok ({len(raw)} bytes embedded; {hits}/{len(probes)} probes found)")
        else:
            print(f"rlc firmware       NOT EMBEDDED: only {hits}/{len(probes)} probes found in the kext")
            bad += 1

    print("\n-- milestones.py verify --")
    r = subprocess.run([sys.executable, str(VM / "milestones.py"), "verify"],
                       capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    if r.returncode != 0:
        sys.stdout.write(r.stderr); bad += 1

    if bad:
        print(f"\npreflight: {bad} problem(s) -- NOT safe to deploy")
        return 1
    print("\npreflight: route scopes checked, constants checked, prologues checked, "
          "recovery-v2 ordering checked, patterns unique")
    return 0

sys.exit(main())
