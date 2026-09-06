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
    # d1 is pure instrumentation implemented as Lilu function routes inside the
    # plugin, so it has no find/replace patterns to verify.
    "d1": [],
    # r1 is implemented as a Lilu function route inside the plugin, not a byte patch.
    "r1": [],
    # p1 is an IOKit re-probe performed by the plugin, not a byte patch.
    "p1": [],
    # x1 wraps check_pcie_link_status via a Lilu route, not a byte patch.
    "x1": [],
    # x2 wraps ttlSetDeviceCapabilityEntry via a Lilu route, not a byte patch.
    "x2": [],
    # x3 traces AMDFirmwareDirectory::getFirmware via a Lilu route, not a byte patch.
    "x3": [],
    # x4 wraps smu_set_fw_entry_info_from_file via a Lilu route, not a byte patch.
    "x4": [],
    # x5 traces psp_cgs_read_register via a Lilu route, not a byte patch.
    "x5": [],
    # x6 dumps psp_np_fw_init's descriptor array via a Lilu route, not a byte patch.
    "x6": [],
    # x7 wraps psp_ring_create_11_0 via a Lilu route, not a byte patch.
    "x7": [],
    # x8 wraps psp_np_fw_load_capability_check via a Lilu route, not a byte patch.
    "x8": [],
    # x9 rewrites the firmware descriptors in the psp_np_fw_init wrapper, not a byte patch.
    "x9": [],
    # xa transcribes PSP GPCOM commands via a Lilu route, not a byte patch.
    "xa": [],
    # xb replaces _aPSP_TOC_SIGNED via applyLookupPatch over the whole container.
    "xb": [],
    # xc calls psp_tmr_unload before psp_tmr_init via a Lilu route, not a byte patch.
    "xc": [],
    # xd declines the tap-delay firmware types in the capability-check wrapper.
    "xd": [],
    # xe guards AmdTtlServices::cosReleaseMemoryHandle via a Lilu route, not a byte patch.
    "xe": [],
    "xf": [],
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
    "p1": "after both kexts are patched, call requestProbe(0) on the GPU's IOPCIDevice so IOKit re-matches and AmdRadeonControllerNavi23::start() runs AGAIN -- this time against patched code. Needed because our plugin lives in the AuxKC and cannot load before the AMD stack: measured ordering shows start() failing at serial line 1298 and our patch landing at 1455.",
    "r1": "remap IP versions in Apple's internal table at the ipconfig_get_ip_discovery_info chokepoint: NBIF 7.3.0->7.2.0, GC 10.3.6->10.3.4, MMHUB 2.4.1->2.3.0 (guess), ATHUB 2.4.1->2.4.0, SMUIO 13.0.10->13.0.7. Replaces the per-gate byte patches and can populate a version that is ABSENT, which a byte patch cannot.",
    "d1": "diagnostic only: hook ipconfig_get_ip_discovery_info to DUMP Apple's whole internal IP table (id + version per entry) and trace bif_ip_create's arguments. No patching. This is what tells us which IPs Apple actually resolved.",
    "x2": "ASIC capability entry: DevGetDeviceInfoEntry matches _DeviceCapabilityTbl on device id + INTERNAL revision + EXTERNAL revision. Entry 268 is exactly {0x8f, 0x73ff, internal 0, external 0xcb} and 0xcb is this chip's real PCI revision, so only the internal revision id can be missing. A miss makes ipi_bgm_create abort with \"Failed to create bgm context\" regardless of how many BGM stages pass. Retries the lookup with the internal revision Apple's own table uses.",
    "xf": "hand SMU HW_INIT to Apple's own dummy back end. smu_11_0_7 drives the Navi 2x mailbox (MP1_SMN_C2PMSG_66/82/90 = register indices 0x282/0x292/0x29a); this silicon puts the SMU mailbox at MP1_C2PMSG_2/33/34, SMN 0x3b10508/0x3b10984/0x3b10988, so every message times out and check_fw_version reports a mismatch. On an APU the SMU is the platform's anyway, so the right answer is Apple's own PP_PhmUseDummyBackEnd=1 (a device property, no patch), which swaps hw_init/dpm/thermal/fan/power/gfx_off for dummy_* stubs that return 0. This clears the one slot that property leaves behind: dummy_smu_internal_hw_init still calls [smu+0x798] = smu_11_0_7_dummy_hw_init, which goes straight back into check_fw_status. Requires the property; logs loudly if it did not arrive.",
    "xe": "survive Apple's SMU failure-cleanup. Once PSP HW_INIT completes the failure moves to SMU HW_INIT, whose teardown calls cosReleaseMemoryHandle on a handle with a null vtable and faults on 0x28 -- it null-checks both arguments but not the vtable inside the handle. Adds the missing check so a failed SMU init only logs, keeping the guest bootable and readable (the same role m1's doGPUPanic patch plays for PPLIB).",
    "xd": "decline the tap-delay firmware (Apple types 0x1e/0x1f/0x20 -> wire 27/28/29 GLOBAL/SE0/SE1 TAP_DELAYS). gc_10_3_6_rlc.bin is header v2_2, whose layout stops before the v2_4 tap-delay fields, so this chip's firmware has none; upstream only loads them when a v2_4 header declares them. Apple submits Navi 23's and the PSP answers 0x8000030a. With xb in place every other blob loads with status 0, so this is the last rejected type.",
    "xc": "unload any pre-existing PSP TMR before Apple establishes one. LOAD_TOC is the single root failure (0x8000030a) and everything after it -- SETUP_TMR's TEE_ERROR_BAD_PARAMETERS on size 0, RLC_G's 0x80000203 'context not initialised' -- is a consequence. The leading explanation is ownership: this iGPU cannot be reset, so the PSP may still hold a TOC/TMR from amdgpu or the platform BIOS. Same shape as the stale-ring problem x7 fixes. Calls psp_tmr_unload (DESTROY_TMR) only, not psp_tmr_destroy, which would free allocations that do not exist yet.",
    "xb": "substitute this chip's own signed PSP TOC (psp_13_0_5_toc.bin) for Apple's _aPSP_TOC_SIGNED. LOAD_TOC is the FIRST PSP command and the first failure (status 0x8000030a, tmr_size 0), so SETUP_TMR then fails with TEE_ERROR_BAD_PARAMETERS and every later firmware load builds on a TMR that was never established. Both are 0x600-byte $PS1 containers signed with the same key; Apple's is fw_type 0x0000200e version 0, this chip's is 0x0101200e version 3. Same size, straight drop-in. Expect LOAD_TOC to return a non-zero tmr_size.",
    "xa": "diagnostic only: transcribe every PSP GPCOM command at psp_cmd_km_buf_prep, the single marshalling point. Shows command order, whether SETUP_TMR precedes the firmware loads, and the wire fw_type/address/size actually handed to the PSP. The Apple->wire type map is already known correct (0x0b -> 8 RLC_G etc.), so this answers what is left: ordering and prerequisites.",
    "x9": "substitute this chip's own RLC firmware (gc_10_3_6_rlc.bin, embedded at build time by mkrlcfw.py) for Apple's Navi 23 blobs, by repointing the descriptor data pointer and length in the psp_np_fw_init wrapper. The header's payload lengths match Apple's descriptor sizes EXACTLY for 4 of 6 RLC types, which is what pins the convention (payload at ucode_array_offset_bytes, length ucode_size_bytes); the two that differ are the ASIC-specific SRM register list and LX6 dram. Mutually exclusive with x8, which declines those types instead of fixing them.",
    "x8": "decline the RLC save/restore lists (Apple types 0x16 GPM / 0x17 SRM / 0x18 CNTL). Seventeen of eighteen IP firmware blobs load, so the Raphael PSP accepts Navi 23 microcode in general; it refuses only these, which are ASIC-specific RLC register lists describing GC 10.3.4 rather than this chip's 10.3.6. Upstream loads them only when the RLC header declares them, so skipping is a supported configuration. Cost: no GFXOFF power-gating.",
    "x7": "destroy a stale PSP GPCOM ring before Apple creates one. The guest never tears its ring down (QEMU is killed) and Apple's psp_ring_create_11_0 only calls ring_stop on its TEE path, so every boot after the first dies at 'psp_ring_create: KM ring creation failed' until the host reboots. Upstream's psp_v11_0_ring_create calls ring_stop unconditionally, so this is upstream behaviour rather than a workaround. gpu-quiesce.sh does the same from the host after the VM stops.",
    "x6": "diagnostic only: dump the 40-byte IP-firmware descriptor array Apple hands psp_np_fw_init. The PSP rejects GFX_CMD_ID_LOAD_IP_FW for RLC restore list CNTL; no Apple kext ships GC/RLC microcode, so the blobs come from the VBIOS PSP directory -- which our grafted ROM declares with 0 entries. A zero count here confirms that.",
    "x5": "diagnostic only: trace psp_cgs_read_register. psp_ring_create's mailbox wait times out; this shows the resolved absolute register offset and the value read, so a broken register base or an unmapped aperture can be told apart from a PSP that is simply not ready. Index 0x80 is C2PMSG_64.",
    "x4": "SMU microcode: we present _AMD_DEVICE_TYPE 0x8, for which Apple registers no PP_SMC_UCODE_SBIN at all -- on that part the SMU microcode comes from the VBIOS via PSP, not the driver. smu_get_fw_constants already has a fallback path for exactly that case, reached when smu_set_fw_entry_info_from_file returns nonzero (which it does by itself when flag bit 0x40 is set). Returns 2 so the fallback is used instead of erroring.",
    "x3": "diagnostic only: trace AMDFirmwareDirectory::getFirmware. HW_INIT fails because the firmware directory has no entry for the device type we present; HWLibs registers firmware for only five _AMD_DEVICE_TYPE values (0x3-0x6 and 0x8, the last with no SMU image). This says which one we are.",
    "x1": "PCIe link status: bgm_create's last stage bio_sw_init can only succeed via pcie_ip_sw_init -> check_pcie_link_status, which needs one of device_inf slots 3/1/7 to expose a PCIe capability offset. All it computes is the cached link speed/width at pcie+0x268, which an APU GPU on the internal fabric does not have. Logs the three offsets first, then reports link OK. Expect 0xc00c020b to clear.",
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

BITS = {"m1": 1, "m2": 2, "m3": 4, "m4": 8, "m5": 16, "m6": 32, "m7": 64, "d1": 128,
        "r1": 256, "p1": 512, "x1": 2048, "x2": 4096, "x3": 8192, "x4": 16384, "x5": 32768, "x6": 65536, "x7": 131072, "x8": 262144, "x9": 524288, "xa": 1048576, "xb": 2097152, "xc": 4194304, "xd": 8388608, "xe": 16777216, "xf": 33554432}
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
_ba = d["NVRAM"]["Add"][BA_UUID].get("boot-args", "")
_m  = re.search(r"rgpu=(\S+)", _ba)
cur = {n for n, b in BITS.items() if _m and int(_m.group(1), 0) & b}
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
