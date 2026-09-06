#!/usr/bin/env python3
"""
Milestone ladder for pushing Apple's AMD stack onto the Raphael iGPU.

Every entry is a byte patch or device property whose bytes were read out of the
KDK 24G830 binaries and whose find-pattern was confirmed UNIQUE. Nothing here is
guessed; `verify` re-checks each pattern against the KDK before you deploy.

  ./milestones.py list
  ./milestones.py verify
  ./milestones.py only m1            # enable exactly this set, disable the rest
  ./milestones.py enable m2
  ./milestones.py disable m2
then  ./redeploy.sh                  # rewrites the ESP and restarts the VM

Read the result with:  tr -d '\r' < run/serial.log | grep -E 'c00c02|ASSERT|GPUCAP|Accel'
"""
import argparse, plistlib, re, sys, pathlib

VM   = pathlib.Path(__file__).resolve().parent
KDK  = VM / "kdk/x/System/Library/Extensions"
HWL  = "com.apple.kext.AMDRadeonX6000HWLibs"
FBK  = "com.apple.kext.AMDRadeonX6000Framebuffer"
GPU_PATH = "PciRoot(0x0)/Pci(0x6,0x0)"

BIN = {
    HWL: KDK / "AMDRadeonX6000HWServices.kext/Contents/PlugIns/AMDRadeonX6000HWLibs.kext/Contents/MacOS/AMDRadeonX6000HWLibs",
    FBK: KDK / "AMDRadeonX6000Framebuffer.kext/Contents/MacOS/AMDRadeonX6000Framebuffer",
}

# set -> list of patches; each patch is (identifier, find_hex, replace_hex, comment)
PATCHES = {
    "m1": [
        (HWL, "4181ff000207000f85e8feffff", "4181ff000307000f85e8feffff",
         "bif_ip_create: accept NBIF 7.3.0 (Linux maps 7.3.0 -> nbio_v7_2) @0x239a84"),
        (FBK, "4c8b83487900004d85c07448", "4c8b83487900004d85c0741b",
         "doGPUPanic: skip the panic path so a TTL failure only logs @0x4e6f9"),
    ],
    "m2": [
        (HWL, "81c10000f5ff83f90d", "81c1fbfff2ff83f90d",
         "mp0_ip_create: map MP0 13.0.5 onto the 11.0.0 handler @0x24410c"),
    ],
    "m3": [
        (HWL, "3d07000d000f8530010000", "3d0a000d000f8530010000",
         "smuio_ip_create: route SMUIO 13.0.10 to the 13.0.7 handlers @0x249a08"),
    ],
    "m4": [
        (HWL, "418d8600fdf5ff83f80672", "418d8600fdf5ff83f80772",
         "gc_init_fcn_ptr_list: widen GC 10.3.0-10.3.5 to include 10.3.6 @0x8f38"),
    ],
    # The *_ip_version_mapping tables are arrays of
    #   { u16 major; u16 minor; u16 rev; u16 pad; void *fn[4]; }   (40-byte stride)
    # matched EXACTLY on all three version fields by _gvm_get_ip_function (0x19258).
    # So each of these is one version field repointed at a handler that already exists.
    "m5": [
        (HWL, "0a000300050000008d5a030000000000", "0a000300060000008d5a030000000000",
         "vm_ip_version_mapping: retarget the 10.3.5 row to 10.3.6 (same fn as 10.3.4) @0x115cc88"),
    ],
    "m6": [
        (HWL, "0a00000000000000bddd030000000000", "0900050000000000bddd030000000000",
         "mc_ip_version_mapping: retarget the 10.0.0 row to UMC 9.5.0 @0x115c610"),
    ],
    "m7": [
        (HWL, "020004000000000033e6030000000000", "020004000100000033e6030000000000",
         "athub_ip_version_mapping: 2.4.0 -> 2.4.1, one revision byte @0x115da18"),
    ],
}

# device properties per set. Value must be bytes.
PROPS = {
    # AmdProjectFeatures::readRegistryProperties computes feature bit 8 as (value == 0),
    # i.e. INVERTED, so 0x00 here means "no PowerPlay". AmdPowerPlayHelper::powerUp then
    # skips handleCriticalError entirely. Do NOT also inject '@0,name': readProjectName
    # uses it to select the ATY,Henbury sub-dict, whose aty_config sets CFG_NO_PP=false
    # and is setProperty'd onto the same IOPCIDevice before the read-back.
    "m1": {"CFG_NO_PP": b"\x00"},
}

DESCR = {
    "m1": "survivable boot: clear the NBIF gate + stop the PPLIB panic. Expect stage 0xc00c0203 -> 0xc00c0205.",
    "m2": "MP0: point PSP-11 code at MP0 13.0.5. RISK: shared SoC security processor. Expect 0xc00c0205 -> 0xc00c0207 (SMUIO).",
    "m3": "SMUIO 13.0.10 -> the 13.0.7 handlers. Same generation, so the register map should be close. Expect BGM to finish and the failure to move into the SWIP layer (GC).",
    "m4": "GC 10.3.6 accepted via a one-byte range widen; routes to the shared GFX10 pointers that already serve 10.3.4. Expect the next failure at GMC/VM, UMC or ATHUB.",
    "m5": "GMC/VM 10.3.6 via the 10.3.5 table row. Low risk: Linux drives 10.3.0-10.3.6 with the same gfx10 GMC code.",
    "m6": "UMC 9.5.0 by repurposing the 10.0.0 row. Higher risk than m5 -- this is the memory controller and 9.5 is a DDR5 APU UMC, so the borrowed handler is a real guess. Without it mc_sw_init fails outright.",
    "m7": "ATHUB 2.4.1 via the 2.4.0 row -- literally one revision byte, and 2.4.0 already shares its handler with 1.3.1.",
}

def load(p):
    raw = p.read_bytes(); i = raw.index(b"<?xml")
    return raw[:i], plistlib.loads(raw[i:])

def save(p, head, d):
    p.write_bytes(head + plistlib.dumps(d))

def verify():
    ok = True
    for name, entries in PATCHES.items():
        for ident, find, repl, comment in entries:
            b = BIN[ident]
            if not b.exists():
                print(f"  {name}: MISSING BINARY {b}"); ok = False; continue
            data = b.read_bytes()
            f, r = bytes.fromhex(find), bytes.fromhex(repl)
            nf = len(re.findall(re.escape(f), data))
            nr = len(re.findall(re.escape(r), data))
            flag = "ok " if (nf == 1 and nr == 0 and len(f) == len(r)) else "BAD"
            if flag == "BAD": ok = False
            print(f"  [{flag}] {name} {ident.split('.')[-1]:26s} find={nf} replace_present={nr} len={len(f)}")
    return ok

BITS = {"m1": 1, "m2": 2, "m3": 4, "m4": 8, "m5": 16, "m6": 32, "m7": 64}
BA_UUID = "7C436110-AB2A-4BBB-A880-FE41995C9F82"

def apply(sets_on):
    """The patches are applied in-kernel by RaphaelGPU.kext (a Lilu plugin), selected
    by the rgpu= boot-arg bitmask. OpenCore Kernel>Patch cannot be used: the AMD kexts
    are prelinked into SystemKernelExtensions.kc, which the OS loads long after the
    bootloader is gone -- verified empirically, both patches silently no-oped."""
    head, d = load(VM / "config.plist")
    # strip the dead Kernel>Patch entries from the earlier approach
    kp = d.setdefault("Kernel", {}).setdefault("Patch", [])
    d["Kernel"]["Patch"] = [p for p in kp if not str(p.get("Comment", "")).startswith(("MS:", "RE:"))]
    mask = sum(BITS[n] for n in sets_on if n in BITS)
    nv = d["NVRAM"]["Add"][BA_UUID]
    ba = re.sub(r"\s*rgpu=\S+", "", nv.get("boot-args", "")).strip()
    nv["boot-args"] = f"{ba} rgpu={mask:#04x}".strip()
    # CFG_NO_PP demonstrably did not stop the panic; m1's doGPUPanic patch does.
    dev = d.setdefault("DeviceProperties", {}).setdefault("Add", {}).setdefault(GPU_PATH, {})
    dev.pop("CFG_NO_PP", None)
    save(VM / "config.plist", head, d)
    return mask, nv["boot-args"]

def show():
    head, d = load(VM / "config.plist")
    ba = d["NVRAM"]["Add"][BA_UUID].get("boot-args", "")
    m = re.search(r"rgpu=(\S+)", ba)
    mask = int(m.group(1), 0) if m else 0
    on = sorted(n for n, b in BITS.items() if mask & b)
    kexts = [k.get("BundlePath") for k in d.get("Kernel", {}).get("Add", []) if k.get("Enabled")]
    print(f"  mechanism: RaphaelGPU.kext (Lilu plugin), rgpu={mask:#04x}")
    print(f"  plugin registered: {'RaphaelGPU.kext' in kexts}   Lilu: {'Lilu.kext' in kexts}")
    for n in sorted(BITS):
        print(f"  {'ON ' if n in on else 'off'} {n}  {DESCR.get(n,'')[:100]}")
    dev = d.get("DeviceProperties", {}).get("Add", {}).get(GPU_PATH, {})
    print(f"  ATY,bin_image: {len(dev.get('ATY,bin_image', b''))} bytes")
    print("  boot-args:", ba)
    print("  enabled sets:", on or "none")

ap = argparse.ArgumentParser()
ap.add_argument("cmd", choices=["list", "verify", "only", "enable", "disable"])
ap.add_argument("sets", nargs="*")
a = ap.parse_args()

if a.cmd == "list":
    show(); sys.exit(0)
if a.cmd == "verify":
    sys.exit(0 if verify() else 1)

head, d = load(VM / "config.plist")
cur = {str(p.get("Comment",""))[3:].split(":")[0]
       for p in d.get("Kernel", {}).get("Patch", [])
       if str(p.get("Comment","")).startswith("MS:") and p.get("Enabled")}
if a.cmd == "only":    new = set(a.sets)
elif a.cmd == "enable":  new = cur | set(a.sets)
else:                    new = cur - set(a.sets)
bad = new - set(PATCHES)
if bad: sys.exit(f"unknown set(s): {sorted(bad)}; known: {sorted(PATCHES)}")
if not verify(): sys.exit("refusing to deploy: a find-pattern is not unique in the KDK binary")
apply(new)
print(f"\nenabled sets now: {sorted(new) or 'none'}")
show()
print("\nnext: ./redeploy.sh")
