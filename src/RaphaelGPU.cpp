//
//  RaphaelGPU -- a Lilu plugin that lets Apple's Navi 2x stack bind to an AMD
//  Raphael / Granite Ridge iGPU (GC 10.3.6) passed through with vfio-pci and
//  spoofed as a Navi 23 (PCI 1002:73ff).
//
//  WHY A KEXT AND NOT OpenCore Kernel>Patch:
//  the AMD graphics kexts are prelinked into SystemKernelExtensions.kc, which the
//  OS loads long after the bootloader is gone. OpenCore only patches the BOOT
//  kernel collection, so its Kernel>Patch entries never reach these kexts --
//  verified empirically: both an HWLibs and a Framebuffer patch silently failed
//  to apply. Lilu patches kexts in-kernel as they load, which is why NootedRed and
//  NootRX are built this way too.
//
//  Each patch below retargets ONE hardware-version comparison at an implementation
//  Apple already ships. Every find-pattern was confirmed unique in the KDK 24G830
//  binary. Nothing here adds new driver code -- see findings/GPU-RE.md.
//
//  Select which patches to apply with a boot-arg bitmask, so the ladder can be
//  walked without rebuilding:   rgpu=0x01  ... rgpu=0x7f     (0 = do nothing)
//

#include <IOKit/IOService.h>
#include <IOKit/IORegistryEntry.h>
#include <IOKit/IOLib.h>
#include <kern/thread.h>
#include <stdarg.h>
#include <Headers/kern_api.hpp>
#include <Headers/kern_patcher.hpp>
#include <Headers/kern_util.hpp>
#include <Headers/plugin_start.hpp>

// This machine's own RLC firmware, generated at build time by mkrlcfw.py from
// /lib/firmware/amdgpu/gc_10_3_6_rlc.bin. Not committed: AMD firmware is redistributable
// only under its own licence. Absent header => build without RLC substitution.
#if __has_include("rlc_fw.h")
#include "rlc_fw.h"
#define RGPU_HAVE_RLC_FW 1
#endif

static const char *pathHWLibs[] {
    "/System/Library/Extensions/AMDRadeonX6000HWServices.kext/Contents/PlugIns/"
    "AMDRadeonX6000HWLibs.kext/Contents/MacOS/AMDRadeonX6000HWLibs"
};
static const char *pathFB[] {
    "/System/Library/Extensions/AMDRadeonX6000Framebuffer.kext/Contents/MacOS/"
    "AMDRadeonX6000Framebuffer"
};

// sys[0] == SysFlags::Loaded: invoke the callback even if the kext is already loaded.
// Both of these are prelinked into SystemKernelExtensions.kc, so by the time a Lilu
// plugin in the auxiliary collection starts, their load event is long past. Their
// IOService start() has NOT run yet though -- the serial log shows rgpu start before
// the first GPUCAP line -- so patching here is still early enough to matter.
// LiluAPI::onKextLoadForce takes an ARRAY of KextInfo plus the callback in a
// SINGLE call. Registering the kexts and the callback separately (and passing
// nullptr/0 for the callback-only registration) does not work -- pluginStart
// stopped executing right there, with no further log output.
enum { KextHWLibs, KextFB };
static KernelPatcher::KextInfo kexts[] {
    {"com.apple.kext.AMDRadeonX6000HWLibs", pathHWLibs, arrsize(pathHWLibs),
     {true}, {}, KernelPatcher::KextInfo::Unloaded},
    {"com.apple.kext.AMDRadeonX6000Framebuffer", pathFB, arrsize(pathFB),
     {true}, {}, KernelPatcher::KextInfo::Unloaded},
};

// ---- the patch table --------------------------------------------------------
// bit 0 = m1 ... bit 6 = m7, matching milestones.py

enum : uint32_t {
    P1 = 1u << 9,   // after patching, make IOKit re-probe the GPU so start() runs again
    R1 = 1u << 8,   // remap IP versions in Apple's table (see remaps[] below)
    D1 = 1u << 7,   // diagnostic: dump Apple's internal IP table and trace bif_ip_create
    M1 = 1u << 0,   // NBIF 7.3.0 + stop the PPLIB panic
    M2 = 1u << 1,   // MP0 13.0.5
    M3 = 1u << 2,   // SMUIO 13.0.10
    M4 = 1u << 3,   // GC 10.3.6
    M5 = 1u << 4,   // GMC/VM 10.3.6
    M6 = 1u << 5,   // UMC 9.5.0
    M7 = 1u << 6,   // ATHUB 2.4.1
    X1 = 1u << 11,  // report PCIe link status OK when the chip has no PCIe capability
    X2 = 1u << 12,  // match the ASIC capability entry ignoring the internal revision id
    X3 = 1u << 13,  // trace the firmware directory lookups
    X4 = 1u << 14,  // no SMU microcode file for this device type; use the fallback
    X5 = 1u << 15,  // trace PSP register reads (mailbox handshake diagnosis)
    X6 = 1u << 16,  // dump the IP-firmware descriptor array Apple hands the PSP
    X7 = 1u << 17,  // destroy a stale PSP GPCOM ring before Apple tries to create one
    X8 = 1u << 18,  // do not offer the RLC save/restore lists to the PSP
    X9 = 1u << 19,  // substitute this chip's own RLC firmware for Apple's Navi 23 blobs
    XA = 1u << 20,  // transcribe every PSP GPCOM command as it is marshalled
    XB = 1u << 21,  // substitute this chip's own signed PSP TOC for Apple's
    XC = 1u << 22,  // unload any pre-existing PSP TMR before Apple establishes one
    XD = 1u << 23,  // decline the tap-delay blobs this chip's RLC firmware does not have
    XE = 1u << 24,  // survive Apple's SMU failure-cleanup instead of panicking in it
    XF = 1u << 25,  // hand SMU HW_INIT to Apple's own dummy back end
};

struct RPatch {
    uint32_t bit;
    bool onHWLibs;              // false => Framebuffer
    // True for a patch that widens a version gate so this chip's REAL version is
    // accepted. R1 solves the same problem from the other side -- it rewrites the
    // version Apple sees to one already accepted -- so the two cancel out: R1 hands
    // bif_ip_create 7.2.0 while m1a has just patched it to demand 7.3.0, and the
    // compare misses. Measured: "bif_ip_create returned 1", stage 0xc00c0203.
    // Hence these are mutually exclusive with R1 and are skipped when it is on.
    bool r1Conflict;
    const uint8_t *find;
    const uint8_t *repl;
    size_t size;
    const char *what;
};

// m1a  bif_ip_create @0x239a84: cmp r15d,0x70200 -> 0x70300, so NBIF 7.3.0 reaches
//      nbio7_2_initialize (which is what Linux maps IP_VERSION(7,3,0) to).
static const uint8_t m1aF[] {0x41,0x81,0xff,0x00,0x02,0x07,0x00,0x0f,0x85,0xe8,0xfe,0xff,0xff};
static const uint8_t m1aR[] {0x41,0x81,0xff,0x00,0x03,0x07,0x00,0x0f,0x85,0xe8,0xfe,0xff,0xff};
// m1b  doGPUPanic @0x4e6f9: je +0x48 -> +0x1b, so a TTL failure logs instead of panicking.
static const uint8_t m1bF[] {0x4c,0x8b,0x83,0x48,0x79,0x00,0x00,0x4d,0x85,0xc0,0x74,0x48};
static const uint8_t m1bR[] {0x4c,0x8b,0x83,0x48,0x79,0x00,0x00,0x4d,0x85,0xc0,0x74,0x1b};
// m2   mp0_ip_create @0x24410c: add ecx,0xfff50000 -> 0xfff2fffb, so MP0 13.0.5
//      lands on bit 0 of the 0x38a1 mask and reaches mp0_11_0_0_initialize.
static const uint8_t m2F[]  {0x81,0xc1,0x00,0x00,0xf5,0xff,0x83,0xf9,0x0d};
static const uint8_t m2R[]  {0x81,0xc1,0xfb,0xff,0xf2,0xff,0x83,0xf9,0x0d};
// m3   smuio_ip_create @0x249a08: cmp eax,0xd0007 -> 0xd000a (SMUIO 13.0.10 -> the
//      smuio13_0_7_* handlers; same 13.0.x generation).
static const uint8_t m3F[]  {0x3d,0x07,0x00,0x0d,0x00,0x0f,0x85,0x30,0x01,0x00,0x00};
static const uint8_t m3R[]  {0x3d,0x0a,0x00,0x0d,0x00,0x0f,0x85,0x30,0x01,0x00,0x00};
// m4   gc_init_fcn_ptr_list @0x8f38: cmp eax,6 -> 7, widening GC 10.3.0-10.3.5 to
//      include 10.3.6 on the shared GFX10 pointers that already serve 10.3.4.
static const uint8_t m4F[]  {0x41,0x8d,0x86,0x00,0xfd,0xf5,0xff,0x83,0xf8,0x06,0x72};
static const uint8_t m4R[]  {0x41,0x8d,0x86,0x00,0xfd,0xf5,0xff,0x83,0xf8,0x07,0x72};
// m5..m7 are rows of *_ip_version_mapping: {u16 major; u16 minor; u16 rev; u16 pad;
// void *fn[4]} on a 40-byte stride, matched exactly on all three version fields by
// _gvm_get_ip_function. Each retargets a spare row at this chip's version.
static const uint8_t m5F[]  {0x0a,0x00,0x03,0x00,0x05,0x00,0x00,0x00,0x8d,0x5a,0x03,0x00,0x00,0x00,0x00,0x00};
static const uint8_t m5R[]  {0x0a,0x00,0x03,0x00,0x06,0x00,0x00,0x00,0x8d,0x5a,0x03,0x00,0x00,0x00,0x00,0x00};
static const uint8_t m6F[]  {0x0a,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0xbd,0xdd,0x03,0x00,0x00,0x00,0x00,0x00};
static const uint8_t m6R[]  {0x09,0x00,0x05,0x00,0x00,0x00,0x00,0x00,0xbd,0xdd,0x03,0x00,0x00,0x00,0x00,0x00};
static const uint8_t m7F[]  {0x02,0x00,0x04,0x00,0x00,0x00,0x00,0x00,0x33,0xe6,0x03,0x00,0x00,0x00,0x00,0x00};
static const uint8_t m7R[]  {0x02,0x00,0x04,0x00,0x01,0x00,0x00,0x00,0x33,0xe6,0x03,0x00,0x00,0x00,0x00,0x00};

static const RPatch patches[] {
    {M1, true,  true,  m1aF, m1aR, sizeof(m1aF), "m1 bif_ip_create: accept NBIF 7.3.0"},
    // Not a version gate -- unrelated to R1, so it always applies.
    {M1, false, false, m1bF, m1bR, sizeof(m1bF), "m1 doGPUPanic: do not panic on TTL failure"},
    {M2, true,  true,  m2F,  m2R,  sizeof(m2F),  "m2 mp0_ip_create: accept MP0 13.0.5"},
    {M3, true,  true,  m3F,  m3R,  sizeof(m3F),  "m3 smuio_ip_create: accept SMUIO 13.0.10"},
    {M4, true,  true,  m4F,  m4R,  sizeof(m4F),  "m4 gc dispatch: accept GC 10.3.6"},
    // m5..m7 rewrite rows of the *_ip_version_mapping tables. Their find patterns
    // include the row's 8-byte function pointers, which the kernel collection
    // REBASES at load (verified: those addresses appear in the kext's DYSYMTAB
    // local relocations), so the pattern can never match at runtime. The version
    // fields alone are not unique enough to search on, so these rows are handled
    // by the computed-address table edits below instead of by a byte search.
    {M5, true,  true,  m5F,  m5R,  sizeof(m5F),  "m5 vm mapping: 10.3.5 row -> 10.3.6"},
    {M6, true,  true,  m6F,  m6R,  sizeof(m6F),  "m6 mc mapping: 10.0.0 row -> UMC 9.5.0"},
    {M7, true,  true,  m7F,  m7R,  sizeof(m7F),  "m7 athub mapping: 2.4.0 -> 2.4.1"},
};

// ---- readable diagnostics -------------------------------------------------------
// Two channels, both of which fail on their own:
//  * Serial gets everything, but other CPUs write to the 16550 concurrently and our
//    lines come out shredded mid-character ("id=0x3d" arrived as "id=0x 3" + "d" on the
//    next line, which cost a whole wrong conclusion). Unusable for multi-line dumps.
//  * os_log is atomic per line, but since the plugin moved into the boot kernel
//    collection it runs long before logd exists, so nothing logged during driver
//    start-up ever lands in the unified log.
// So buffer every diagnostic line here and re-emit the whole buffer from a thread once
// userspace is up. The deferred copy is clean, ordered, and greppable with
// `log show`; the live serial copy stays as a crash-time fallback.
static char   diagBuf[32768];
static size_t diagLen;

static void diagAppend(const char *fmt, ...) {
    if (diagLen + 512 >= sizeof(diagBuf)) return;
    va_list ap;
    va_start(ap, fmt);
    int n = vsnprintf(diagBuf + diagLen, sizeof(diagBuf) - diagLen - 2, fmt, ap);
    va_end(ap);
    if (n <= 0) return;
    diagLen += static_cast<size_t>(n);
    diagBuf[diagLen++] = '\n';
    diagBuf[diagLen] = '\0';
}

#define RLOG(fmt, ...) do { \
    SYSLOG("rgpu", fmt, ## __VA_ARGS__);  \
    diagAppend(fmt, ## __VA_ARGS__);      \
} while (0)

static uint32_t diagDumpDelayMs = 75000;

static void diagDumpThread(void *, wait_result_t) {
    // Tunable with the rgpudump=<ms> boot-arg: the whole AMD bring-up finishes well
    // before the default, and each iteration costs a boot, so this can be shortened once
    // you know how early the sequence completes on a given configuration.
    IOSleep(diagDumpDelayMs);
    SYSLOG("rgpu", "==== deferred diagnostics: %lu bytes ====", diagLen);
    size_t i = 0;
    unsigned n = 0;
    while (i < diagLen) {
        size_t e = i;
        while (e < diagLen && diagBuf[e] != '\n') e++;
        diagBuf[e] = '\0';
        SYSLOG("rgpu", "d%03u| %s", n++, diagBuf + i);
        i = e + 1;
    }
    SYSLOG("rgpu", "==== deferred diagnostics end (%u lines) ====", n);
    thread_terminate(current_thread());
}

static uint32_t mask = 0;

// An EXPORTED symbol of HWLibs, used to derive the kext slide before any
// kext-load callback arrives. VMA taken from the KDK 24G830 binary; __TEXT
// vmaddr is 0, so base = runtime(anchor) - kHWLibsAnchorVMA.
static constexpr const char *kHWLibsAnchorSym =
    "__ZN30AMDRadeonX6000_AMDRadeonHWLibs20callPlatformFunctionEPK8OSSymbolbPvS3_S3_S3_";
static constexpr size_t kHWLibsAnchorVMA = 0x1700;

// ---- diagnostics (D1) -------------------------------------------------------
// HWLibs builds an internal IP table in ipconfig_create and every *_ip_create
// consults it via ipconfig_get_ip_discovery_info(ipconfig, apple_internal_id).
// Apple's ids are NOT the discovery hw_ids (BIF is 0x42 here, while this chip
// reports NBIF as hw_id 108), so the only way to know what Apple actually
// resolved is to read its table. Layout, decoded from the disassembly of
// ipconfig_get_ip_discovery_info (VMA 0x245040):
//     count            at ipconfig + 0x1c
//     entries          at ipconfig + 0x20, stride 0x260
//     entry + 0x00 u32 apple internal ip id
//     entry + 0x08 u16 major   + 0x0c u16 minor   + 0x10 u16 rev
static constexpr size_t kOffIpcfgGet     = 0x245040;   // _ipconfig_get_ip_discovery_info
static constexpr size_t kOffBifIpCreate  = 0x239931;   // _bif_ip_create
static constexpr size_t kOffCheckPcie    = 0x246a4e;   // _check_pcie_link_status
static constexpr size_t kOffGetDevInf    = 0x234dec;   // _bcs_get_device_inf
static constexpr size_t kOffTtlSetDevCap = 0xaf02d;    // _ttlSetDeviceCapabilityEntry
static constexpr size_t kOffGvmGetIpFn   = 0x19258;    // _gvm_get_ip_function
static constexpr size_t kOffFwDirGet     = 0xb0c10;    // AMDFirmwareDirectory::getFirmware
static constexpr size_t kOffSmuFwFile    = 0x70961;    // _smu_set_fw_entry_info_from_file
static constexpr size_t kOffPspRegRead   = 0x516ce;    // _psp_cgs_read_register
static constexpr size_t kOffPspRegWrite  = 0x516f5;    // _psp_cgs_write_register
static constexpr size_t kOffPspNpFwInit  = 0x5304c;    // _psp_np_fw_init
static constexpr size_t kOffPspRingCreate = 0x5beb3;   // _psp_ring_create_11_0
static constexpr size_t kOffPspFwCapChk   = 0x5317e;   // _psp_np_fw_load_capability_check
static constexpr size_t kOffPspBufPrep    = 0x524e9;   // _psp_cmd_km_buf_prep
static constexpr size_t kOffPspTmrInit    = 0x52bbd;   // _psp_tmr_init
static constexpr size_t kOffPspTmrUnload  = 0x52ee7;   // _psp_tmr_unload
static constexpr size_t kOffCosRelMemHnd  = 0xb3670;   // AmdTtlServices::cosReleaseMemoryHandle
static constexpr size_t kOffSmuInitFnPtrs = 0x72b33;   // _smu_init_function_pointer_list
static constexpr size_t kOffSmuUpdFnPtrs  = 0x73a2f;   // _smu_update_function_pointers (called, not routed)
// GFX_CTRL command encodings, from upstream psp_gfx_if.h.
static constexpr uint32_t kC2PMsg64        = 0x80;       // MP0 C2PMSG_64, IP-relative
static constexpr uint32_t kHwIpMp0         = 0x4b;
static constexpr uint32_t kDestroyGpcomRing = 0x000C0000;
static constexpr uint32_t kMboxReadyMask   = 0x8000FFFF;
static constexpr uint32_t kMboxReadyFlag   = 0x80000000;

// Set from the kext-load callback; every computed-address route below needs it.
static mach_vm_address_t hwlibsBase {};

// bgm_create's last stage, bio_sw_init (failure => event_id 0xc00c020b), is
//     mov eax,1; test byte [bio+8],1; je out; call pcie_ip_sw_init ...
// so it can only succeed through pcie_ip_sw_init -> check_pcie_link_status.
// That function asks bcs_get_device_inf for slots 3, 1 and 7 and needs at least one
// to carry a nonzero PCIe capability offset at +0x18; if none does it returns 1 and
// the whole BGM tears down. All it ever computes is the cached link speed/width word
// at pcie+0x268, which is meaningless for a GPU on an APU's internal fabric with no
// discrete PCIe link to train. The wrapper logs the three offsets either way, so the
// diagnosis is recorded before anything is bypassed.
// ipi_bgm_create -> ttlSetDeviceCapabilityEntry -> DevGetDeviceInfoEntry walks the
// static _DeviceCapabilityTbl (VMA 0x557240, stride 0x50) and needs all three keys to
// agree: entry+0x10 == device id, entry+0x18 == INTERNAL revision id, entry+0x20 ==
// EXTERNAL revision id, where 0xdeadcafe in either revision field is a wildcard. The
// table does carry an exact entry for what we present -- index 268 is
// {family 0x8f, devid 0x73ff, internal 0, external 0xcb} and 0xcb is this chip's real
// PCI revision -- so only the internal revision id can be missing it. Failing this
// lookup makes ttlSetDeviceCapabilityEntry return false and ipi_bgm_create abort with
// "Failed to create bgm context", which is the failure that outlives every BGM stage
// patch. X2 retries the lookup with the internal revision forced to the value Apple's
// own table uses for this device, rather than editing Apple's table in place.
using GetDevInfFn = void *(*)(void *, uint32_t);
static mach_vm_address_t orgCheckPcieLink {};
static mach_vm_address_t addrGetDevInf {};

static int wrapCheckPcieLink(void *pcie) {
    uint32_t cap[3] = {0, 0, 0};
    static const uint32_t slots[3] = {3, 1, 7};
    auto handle = (pcie != nullptr) ? *reinterpret_cast<void **>(pcie) : nullptr;
    if (handle != nullptr && addrGetDevInf != 0) {
        auto getInf = reinterpret_cast<GetDevInfFn>(addrGetDevInf);
        for (size_t i = 0; i < 3; i++)
            if (auto inf = getInf(handle, slots[i]))
                cap[i] = *reinterpret_cast<const uint32_t *>(static_cast<const uint8_t *>(inf) + 0x18);
    }
    int r = FunctionCast(wrapCheckPcieLink, orgCheckPcieLink)(pcie);
    RLOG("check_pcie_link_status -> %d  (pcie cap offset: dev3=0x%x dev1=0x%x dev7=0x%x)",
           r, cap[0], cap[1], cap[2]);
    if (r != 0 && (mask & X1)) {
        RLOG("X1: no usable PCIe capability -- reporting link OK");
        return 0;
    }
    return r;
}

// ---- IP version remapping (R1) ----------------------------------------------
// Every *_ip_create in HWLibs obtains its hardware version through the single
// chokepoint ipconfig_get_ip_discovery_info(ipconfig, apple_internal_id), then
// dispatches on get_hw_revision(major, minor, rev) == major<<16|minor<<8|rev.
// So rather than byte-patching each dispatch site, rewrite the version Apple
// SEES for a given IP. One table, no find/replace patterns, and a remapping can
// be added or changed without re-deriving byte offsets from the KDK.
//
// Legitimacy varies per IP and is noted per row. Pointing Apple at a
// near-neighbour implementation is sound where Linux itself shares one driver
// across those versions; it is a guess where the implementations genuinely differ.
struct Remap {
    uint32_t appleId;                     // Apple internal ip id
    uint16_t maj, min, rev;               // version to report instead
    const char *why;
};
static const Remap remaps[] {
    // Linux maps IP_VERSION(7,3,0) onto nbio_v7_2_funcs, and Apple ships a 7.2
    // handler (nbio7_2_initialize), so reporting 7.2.0 for NBIF is what Linux does.
    {0x42, 7, 2, 0, "NBIF 7.3.0 -> 7.2.0 (Linux uses nbio_v7_2 for 7.3.0)"},
    // GC: Apple accepts 10.3.0-10.3.5 and ships gc_10_3_4 microcode; 10.3.6 and
    // 10.3.4 share Linux's gfx_v10_0 driver and register file.
    {0x0b, 10, 3, 4, "GC 10.3.6 -> 10.3.4 (same Linux gfx_v10_0 driver)"},
    // MMHUB: not a guess. gmc_v10_0.c:581 selects mmhub_v2_3_funcs for 2.3.0, 2.4.0
    // AND 2.4.1 in the same case block, so upstream drives this chip's MMHUB with
    // exactly the 2.3.0 implementation Apple ships.
    {0x1b, 2, 3, 0, "MMHUB 2.4.1 -> 2.3.0 (gmc_v10_0 uses mmhub_v2_3 for both)"},
    // ATHUB: Apple's table already has a 2.4.0 row; ours is 2.4.1.
    {0x1c, 2, 4, 0, "ATHUB 2.4.1 -> 2.4.0 (one revision apart)"},
    // SMUIO: Apple ships smuio13_0_7_*; ours is 13.0.10, same generation.
    {0x07, 13, 0, 7, "SMUIO 13.0.10 -> 13.0.7 (same 13.0.x generation)"},
    // UMC: the host's own IP discovery reports 9.5.0 and Apple's mc_ip_version_mapping
    // has no 9.5.0 row at all, so mc_sw_init's lookup misses and GVM tears down.
    // 8.7.0 is not a guess: gmc_v10_0_set_umc_funcs wires UMC for IP_VERSION(8,7,0) and
    // nothing else across the whole of Navi 2x -- the offset constant is literally
    // UMC_V8_7_PER_CHANNEL_OFFSET_SIENNA -- so 8.7.0 is what a real Navi 23 reports and
    // what Apple's Navi 23 support is written against.
    {0x46, 8, 7, 0, "UMC 9.5.0 -> 8.7.0 (the Navi 2x UMC; Linux wires only 8.7.0)"},
    // MP0/PSP. psp_asic_type_init (0x4e08d) dispatches on the MP0 version and, for
    // major 13, accepts ONLY minor 0 revisions 0-3; this chip is 13.0.5, so it returns
    // 1 and PSP's SW_INIT fails. Its major-11 branch is the Navi 2x family, and
    // upstream psp_v11_0 handles 11.0.7 / 11.0.11 / 11.0.12 / 11.0.13 -- Sienna
    // Cichlid, Navy Flounder, Dimgrey Cavefish and Beige Goby. Navi 23 IS Dimgrey
    // Cavefish, so 11.0.12 is the MP0 version belonging to the identity we already
    // present everywhere else, and Apple's table accepts revision 12.
    {0x4b, 11, 0, 12, "MP0 13.0.5 -> 11.0.12 (Navi 23 is Dimgrey Cavefish = MP0 11.0.12)"},
    // MP1/SMU, the same story one client further on. smu_get_hw_version (0x726ac) maps
    // the version to an internal enum and smu_init_function_pointer_list (0x72b33)
    // handles only enum <= 0xa, asserting "Unsupported hw version!" above that.
    // Decoding both of its jump tables:
    //     13.0.5  -> enum 0x12   unsupported
    //     11.0.12 -> enum 0x9    smu_11_0 function pointer list
    // and the enum order over the 11.0.x table is exactly Sienna Cichlid (11.0.7 -> 6),
    // Navy Flounder (11.0.11 -> 8), Dimgrey Cavefish (11.0.12 -> 9), Beige Goby
    // (11.0.13 -> 0xa). Navi 23 is Dimgrey Cavefish, so 11.0.12 is both the version
    // belonging to the identity we present and one Apple actually implements.
    {0x04, 11, 0, 12, "MP1/SMU 13.0.5 -> 11.0.12 (enum 0x12 is unsupported; 0x9 is Navi 23)"},
};

static mach_vm_address_t orgIpcfgGet {};
static mach_vm_address_t orgBifIpCreate {};
static bool dumpedTable = false;

static mach_vm_address_t orgTtlSetDevCap {};
static mach_vm_address_t orgGvmGetIpFn {};
static mach_vm_address_t orgFwDirGet {};
static mach_vm_address_t orgSmuFwFile {};
static mach_vm_address_t orgSmuInitFnPtrs {};
static mach_vm_address_t orgPspRegRead {};

// psp_ring_create's mailbox handshake times out. Before concluding anything about the
// PSP itself, check the plumbing: psp_cgs_read_register resolves an IP-relative index
// against a per-instance base held in the PSP context,
//     516e1: add esi, dword ptr [rdi + 4*rdx + 0x5c]
// and then calls out through the COS callback table. If that base is wrong, or the
// aperture is not mapped, every read returns 0xffffffff or 0 and every wait times out
// for reasons that have nothing to do with the PSP's state. Index 0x80 is C2PMSG_64 --
// the mailbox status register the ring-create wait polls -- and 0x8000ffff/0x80000000
// are its ready/response mask and flag. Capped so the log stays readable.
static mach_vm_address_t orgPspRegWrite {};
static mach_vm_address_t orgPspNpFwInit {};
static mach_vm_address_t orgPspRingCreate {};
static mach_vm_address_t orgPspFwCapChk {};

// Of the eighteen IP firmware blobs Apple hands the PSP, seventeen load. The Raphael PSP
// is therefore accepting Navi 23 microcode in general; it rejects exactly one family.
// Decoding psp_print_fw_load_failure_msg's jump table gives Apple's own type names:
//     0x16 RLC restore list GPM   0x17 RLC restore list SRM   0x18 RLC restore list CNTL
// and 0x18 is the one that fails, with the TOS returning 0x8000030a to LOAD_IP_FW three
// times before psp_np_fw_load gives up and the whole PSP HW_INIT aborts.
//
// These three are not code: they are ASIC-specific RLC save/restore REGISTER LISTS, used
// for GFXOFF and RLC power-gating. A Navi 23 list describes GC 10.3.4's register file, so
// a PSP validating it against this chip's GC 10.3.6 has every reason to refuse it.
// Upstream loads them only when the RLC header actually declares them
// (adev->gfx.rlc.is_rlc_v2_1 plus non-zero save_restore_list_*_size_bytes) and skips them
// otherwise, so declining them is a configuration upstream already supports rather than a
// bypass of a real check.
//
// The honest cost: without a save/restore list the RLC cannot do GFXOFF, so deep
// graphics power-gating is unavailable. That is a power-management feature, not a
// prerequisite for bringing the engine up.
// psp_np_fw_load indexes the failure-message table with (type - 1):
//     53ab8: lea eax, [r15 - 0x1]
// so "RLC restore list CNTL", message 0x18, is really fw TYPE 0x19, and the family is
// 0x17 GPM / 0x18 SRM / 0x19 CNTL. Log every call rather than trusting that arithmetic.
#ifdef RGPU_HAVE_RLC_FW
// Substitute this chip's own RLC firmware for Apple's Navi 23 blobs.
//
// Apple hands the PSP the full Navi 23 IP set and the Raphael PSP rejects the RLC members.
// The sizes say why, and they also pin the calling convention. rlc_firmware_header_v2_2
// in gc_10_3_6_rlc.bin (this chip's own signed firmware) declares payloads whose lengths
// match Apple's descriptor sizes EXACTLY for four of the six RLC types:
//
//     type          Apple (Navi 23)   gc_10_3_6      
//     0x0b RLC_G          0x6200        0x6200   same
//     0x19 CNTL            0x250         0x250   same
//     0x17 GPM             0x600         0x600   same
//     0x1a LX6 iram      0x10200       0x10200   same
//     0x18 SRM            0x5ec0        0x4480   DIFFERS
//     0x1b LX6 dram       0x4200       0x10200   DIFFERS
//
// Four exact matches establish that Apple passes the PAYLOAD at ucode_array_offset_bytes
// with length ucode_size_bytes, not the container. And the two that differ are precisely
// the ASIC-specific ones: the SRM list is a register list over the GC register file, so
// Navi 23's 32 CUs need 0x5ec0 where this chip's 2 CUs need 0x4480. Handing a PSP a
// register list for the wrong register file is exactly the kind of thing it should refuse.
//
// So: parse the header out of the embedded bytes at runtime -- no offsets baked into the
// plugin, they cannot drift from the firmware -- and repoint each descriptor's data
// pointer (+0x10) and length (+0x18) before psp_np_fw_init memmoves the array.
struct RlcPayload { uint32_t appleType; uint32_t offField; uint32_t sizeField; const char *name; };
static const RlcPayload kRlcPayloads[] {
    {0x0b, 0x18, 0x14, "RLC_G"},          // common_firmware_header.ucode_{array_offset,size}_bytes
    {0x19, 0x78, 0x74, "restore CNTL"},   // save_restore_list_cntl_*
    {0x17, 0x88, 0x84, "restore GPM"},    // save_restore_list_gpm_*
    {0x18, 0x98, 0x94, "restore SRM"},    // save_restore_list_srm_*
    {0x1a, 0xa0, 0x9c, "LX6 iram"},       // rlc_iram_ucode_*
    {0x1b, 0xa8, 0xa4, "LX6 dram"},       // rlc_dram_ucode_*
};

static uint32_t rlcField(uint32_t off) {
    return *reinterpret_cast<const uint32_t *>(kRlcFw + off);
}

static void substituteRlcFirmware(uint8_t *arr, uint32_t count) {
    // Refuse to touch anything unless the embedded bytes really are the header we expect.
    uint16_t hvMaj = *reinterpret_cast<const uint16_t *>(kRlcFw + 0x08);
    uint16_t hvMin = *reinterpret_cast<const uint16_t *>(kRlcFw + 0x0a);
    if (rlcField(0x00) != kRlcFwSize || rlcField(0x04) != 0xac || hvMaj != 2 || hvMin != 2) {
        RLOG("X9: embedded RLC firmware is not rlc_firmware_header_v2_2 "
             "(size=0x%x hdr=0x%x v%u.%u) -- not substituting",
             rlcField(0x00), rlcField(0x04), hvMaj, hvMin);
        return;
    }
    for (uint32_t i = 0; i < count; i++) {
        auto e = arr + static_cast<size_t>(i) * 40;
        uint32_t type = *reinterpret_cast<const uint32_t *>(e + 0x04);
        for (auto &p : kRlcPayloads) {
            if (p.appleType != type) continue;
            uint32_t off = rlcField(p.offField), len = rlcField(p.sizeField);
            if (len == 0 || off + len > kRlcFwSize) {
                RLOG("X9: %s payload out of range (off=0x%x len=0x%x) -- left alone",
                     p.name, off, len);
                break;
            }
            uint64_t oldPtr = *reinterpret_cast<const uint64_t *>(e + 0x10);
            uint32_t oldLen = *reinterpret_cast<const uint32_t *>(e + 0x18);
            *reinterpret_cast<uint64_t *>(e + 0x10) =
                reinterpret_cast<uint64_t>(kRlcFw + off);
            *reinterpret_cast<uint32_t *>(e + 0x18) = len;
            RLOG("X9: type 0x%02x %-12s Apple 0x%llx/0x%-6x -> gc_10_3_6+0x%-6x/0x%-6x%s",
                 type, p.name, oldPtr, oldLen, off, len,
                 oldLen == len ? "" : "  (LENGTH CHANGED)");
            break;
        }
    }
}
#endif

static mach_vm_address_t orgPspBufPrep {};
static uint32_t bufPrepCount = 0;
// psp_gfx_resp sits at command-buffer +864: status +0, fw_addr_lo +8, fw_addr_hi +12,
// tmr_size +16. buf_prep runs BEFORE submission, so the response to command N only exists
// by the time command N+1 is marshalled -- carry the previous buffer forward and read it
// then. Without this we see what Apple asks for but never what the PSP answered.
static const uint32_t *prevCmdBuf = nullptr;
static uint32_t prevWireCmd = 0;
static uint32_t prevWireType = 0;

// Transcribe every PSP GPCOM command. psp_cmd_km_buf_prep is the single point where Apple
// marshals its internal command descriptor into a psp_gfx_cmd_resp:
//     524fd: ecx = [rdx]                        ; slot index, < 0x10
//     52509: edx = [rsi]                        ; Apple's command id
//     52517: rbx = [rdi + slot*0x38 + 0x760]    ; the GPCOM buffer for that slot
// and for LOAD_IP_FW it copies [rsi+0x04/0x08/0x0c] to the command's fw_phy_addr_lo/hi and
// fw_size, then translates [rsi+0x10] through psp_cmd_km_fw_id_map into the wire fw_type.
// That map is correct -- it produces exactly upstream's GFX_FW_TYPE values (Apple 0x0b -> 8
// RLC_G, 0x17 -> 20, 0x18 -> 21, 0x19 -> 22, 0x1a -> 26, 0x1b -> 48) -- so the transcript is
// here to answer what remains: in what ORDER commands are issued, whether SETUP_TMR (wire
// cmd 5) precedes the firmware loads, and what physical address the PSP is actually given.
static uint32_t wrapPspBufPrep(void *psp, void *desc, uint32_t *slot) {
    uint32_t slotIdx = (slot != nullptr) ? *slot : 0xffffffff;
    uint32_t r = FunctionCast(wrapPspBufPrep, orgPspBufPrep)(psp, desc, slot);
    if ((mask & XA) != 0 && bufPrepCount < 64 && desc != nullptr && slotIdx < 0x10) {
        auto dw = static_cast<const uint32_t *>(desc);
        auto buf = reinterpret_cast<const uint32_t *>(
            static_cast<const uint8_t *>(psp) + slotIdx * 0x38 + 0x760);
        // psp_gfx_cmd_resp: +0x08 cmd_id; LOAD_IP_FW: +0x1c/+0x20 addr, +0x24 size, +0x28 type
        const uint32_t *b = (buf != nullptr) ? *reinterpret_cast<const uint32_t *const *>(buf) : nullptr;
        if (b != nullptr) {
            if (prevCmdBuf != nullptr) {
                uint32_t st = prevCmdBuf[216];           // psp_gfx_resp.status at +864
                RLOG("   resp cmd_id=%-3u wireType=%-3u status=0x%08x tmr_size=0x%x%s",
                     prevWireCmd, prevWireType, st, prevCmdBuf[220],
                     st == 0 ? "" : "   <-- FAILED");
            }
            // Log addr/size for EVERY command, not just LOAD_IP_FW: LOAD_TOC (32) and
            // SETUP_TMR (5) carry them in the same places (+0x1c/+0x20 addr, +0x24 size),
            // and since LOAD_TOC is the first failure its arguments are what matter.
            uint32_t wireCmd = b[2];
            RLOG("cmd[%02u] wire=%-3u apple=%-2u type=%-3u addr=0x%08x%08x size=0x%-8x",
                 bufPrepCount, wireCmd, dw[0], wireCmd == 6 ? b[10] : 0,
                 b[8], b[7], b[9]);
            prevWireType = (wireCmd == 6) ? b[10] : 0;
            prevCmdBuf = b;
            prevWireCmd = wireCmd;
            bufPrepCount++;
        }
    }
    return r;
}

static mach_vm_address_t orgCosRelMemHnd {};

// Keep the guest alive through Apple's SMU failure-cleanup.
//
// With the TOC accepted, PSP HW_INIT completes and the failure moves to SMU HW_INIT. Its
// teardown then panics the machine:
//     cosReleaseMemoryHandle(this, handle):
//         b367e: mov rax, qword ptr [rsi]     ; handle's vtable
//         b3684: call qword ptr [rax + 0x28]  ; virtual release
// It null-checks BOTH arguments but not the vtable pointer inside the handle, and on this
// path the handle is non-null with a null vtable, so it faults on 0x28 (observed: RAX=0,
// CR2=0x28). That is a latent bug in Apple's cleanup, reachable here because the SMU
// sequence fails in a way a real Navi 23 never does. Add the missing check so a failed
// SMU init only logs, the way m1's doGPUPanic patch does for the PPLIB path -- otherwise
// the guest dies before anything can be read out of it.
static uint32_t wrapCosRelMemHnd(void *self, void *handle) {
    if ((mask & XE) != 0 && handle != nullptr &&
        *reinterpret_cast<void *const *>(handle) == nullptr) {
        RLOG("XE: cosReleaseMemoryHandle(%p) has a null vtable -- skipping the release", handle);
        return 0;
    }
    return FunctionCast(wrapCosRelMemHnd, orgCosRelMemHnd)(self, handle);
}

static mach_vm_address_t orgPspTmrInit {};

// Unload any pre-existing TMR before Apple tries to establish one.
//
// The whole failure cascade has a single root: LOAD_TOC is rejected with 0x8000030a, so
// tmr_size comes back 0, so SETUP_TMR is handed size 0 and returns TEE_ERROR_BAD_PARAMETERS,
// so there is no TMR -- and RLC_G then fails with 0x80000203, which decoding the PSP sys_drv
// images embedded in HWLibs shows means "required context not initialised", returned before
// the request is even parsed. Substituting firmware never mattered: the RLC blobs were never
// the problem.
//
// Why LOAD_TOC itself is refused is the open question, and the leading explanation is
// ownership. This iGPU cannot be reset -- the host's amdgpu drove it first and the platform
// BIOS before that -- so the PSP may still hold a TOC/TMR from an earlier owner and refuse
// to establish a second one. That is precisely the shape of the stale-GPCOM-ring problem
// already fixed in x7, and it has the same style of fix: issue the teardown the previous
// owner never did. psp_tmr_unload submits DESTROY_TMR (Apple cmd 7 -> wire 7) and nothing
// else; psp_tmr_destroy also frees allocations that do not exist yet, so call the unload
// alone.
static uint32_t wrapPspTmrInit(void *psp) {
    if ((mask & XC) != 0 && hwlibsBase != 0 && psp != nullptr) {
        auto unload = reinterpret_cast<uint32_t (*)(void *)>(hwlibsBase + kOffPspTmrUnload);
        uint32_t u = unload(psp);
        RLOG("XC: psp_tmr_unload before TMR init -> %u", u);
    }
    return FunctionCast(wrapPspTmrInit, orgPspTmrInit)(psp);
}

static uint32_t fwCapCount = 0;
static uint32_t wrapPspFwCapChk(void *psp, uint32_t fwType) {
    // X8 declines the RLC save/restore lists. It is now OBSOLETE and must stay off: with
    // this chip's own TOC accepted, those three load with status 0.
    bool decline = (mask & X8) != 0 && fwType >= 0x17 && fwType <= 0x19;
    // XD declines the tap-delay blobs, Apple types 0x1e/0x1f/0x20 (wire 27/28/29 GLOBAL /
    // SE0 / SE1 TAP_DELAYS). gc_10_3_6_rlc.bin is header v2_2, whose layout stops before
    // the v2_4 tap-delay fields, so this chip's firmware does not contain them at all --
    // upstream only loads them when the v2_4 header declares them, so declining is what
    // upstream does here. Apple submits Navi 23's, and the PSP answers 0x8000030a,
    // "unrecognised firmware type".
    if ((mask & XD) != 0 && fwType >= 0x1e && fwType <= 0x21) decline = true;
    uint32_t r = decline ? 0 : FunctionCast(wrapPspFwCapChk, orgPspFwCapChk)(psp, fwType);
    if (fwCapCount < 48) {
        RLOG("fw_cap(type=0x%02x) -> %u%s", fwType, r,
             decline ? "   <- X8 declined (RLC save/restore list, no GFXOFF)" : "");
        fwCapCount++;
    }
    return r;
}

// Destroy a stale GPCOM ring before Apple creates one.
//
// The guest's driver never tears its ring down -- QEMU is killed outright -- so
// C2PMSG_64 keeps an unacknowledged INIT_GPCOM_RING response across VM restarts. And
// Apple's psp_ring_create_11_0 only calls psp_ring_stop on its TEE path: for ring type 2
// it branches at 0x5bf5e straight to 0x5bfc7, writes the ring registers and issues
// INIT_GPCOM_RING against a ring that already exists. The mailbox then never returns to
// status 0 and every boot after the first dies at "psp_ring_create: KM ring creation
// failed" until the host is rebooted -- which is exactly why one host reboot bought
// exactly one working boot.
//
// Upstream does not have this problem because psp_v11_0_ring_create calls
// psp_v11_0_ring_stop unconditionally, and amdgpu tears the ring down on unbind (after
// which C2PMSG_64 reads 0x80030000, status 0). So issuing DESTROY_GPCOM_RING first is
// upstream's own behaviour, not a workaround. gpu-quiesce.sh does the same from the host
// after the VM stops; this is the belt to that braces.
static uint32_t wrapPspRingCreate(void *psp, uint32_t ringType) {
    if ((mask & X7) != 0 && ringType == 2 && hwlibsBase != 0 && psp != nullptr) {
        auto wr = reinterpret_cast<void (*)(void *, uint32_t, uint32_t, uint32_t, uint32_t)>(
                      hwlibsBase + kOffPspRegWrite);
        auto rd = reinterpret_cast<uint32_t (*)(void *, uint32_t, uint32_t, uint32_t)>(
                      hwlibsBase + kOffPspRegRead);
        // Destroy UNCONDITIONALLY. A clean mailbox does not mean there is no ring: after a
        // boot that got as far as ENABLE_INT, C2PMSG_64 reads 0x80050000 -- status 0, so
        // it passes every "ready" test -- while the GPCOM ring from that boot is still
        // very much alive, and INIT_GPCOM_RING then fails because it already exists.
        // Gating the destroy on the status being non-zero is exactly the mistake that
        // made this look fixed when it was not. Upstream's psp_v11_0_ring_create calls
        // psp_v11_0_ring_stop unconditionally for the same reason.
        uint32_t before = rd(psp, kC2PMsg64, 0, kHwIpMp0);
        wr(psp, kC2PMsg64, 0, kDestroyGpcomRing, kHwIpMp0);
        uint32_t v = before;
        int ms = 0;
        for (; ms < 2000; ms++) {
            v = rd(psp, kC2PMsg64, 0, kHwIpMp0);
            if ((v & kMboxReadyMask) == kMboxReadyFlag &&
                ((v >> 16) & 0x7fff) == (kDestroyGpcomRing >> 16))
                break;
            IOSleep(1);
        }
        RLOG("X7: destroy GPCOM ring: 0x%08x -> 0x%08x after %dms%s", before, v, ms,
             (v & kMboxReadyMask) == kMboxReadyFlag ? " (ready)" : " (TIMEOUT)");
    }
    return FunctionCast(wrapPspRingCreate, orgPspRingCreate)(psp, ringType);
}

// psp_np_fw_load fails with "[FW] psp_np_fw_load: RLC restore list CNTL failed to load"
// and the TOS returns 0x8000030a to GFX_CMD_ID_LOAD_IP_FW (cmd 0x6). The blobs are not
// Apple's: no kext in the stack calls putFirmware for anything but VCN and SMU, and none
// of them carries GC or RLC microcode at all. They arrive through an OS-side callback,
//     a9d8f: call qword ptr [r15 + 0x2a0]      ; r15 = ttlGetExtSvcs()
// which ends at psp_np_fw_init(psp, descriptors, count) -- an array of 40-byte entries
// memmove'd to psp+0x2c08. Dump it: a zero count means Apple has no IP firmware to give
// the PSP (consistent with our grafted VBIOS carrying a PSP directory of 0 entries),
// while a non-zero count shows which types it does have and whether their buffers are
// real. Everything downstream depends on which of those two it is.
static void dumpFwDescriptors(const uint8_t *arr, uint32_t count) {
    RLOG("np_fw_init: %u descriptor(s) at %p", count, arr);
    if (arr == nullptr) return;
    // Dump raw: the first guess at this layout was wrong (offset 0 is a constant 0x28,
    // the struct size, and the type sits at +0x04), so print all 40 bytes and decode
    // from the actual data rather than from an assumed shape.
    for (uint32_t i = 0; i < count && i < 40; i++) {
        auto e = arr + static_cast<size_t>(i) * 40;
        RLOG("  fw[%02u] %08x %08x %08x %08x %08x %08x %08x %08x %08x %08x", i,
             *reinterpret_cast<const uint32_t *>(e + 0x00),
             *reinterpret_cast<const uint32_t *>(e + 0x04),
             *reinterpret_cast<const uint32_t *>(e + 0x08),
             *reinterpret_cast<const uint32_t *>(e + 0x0c),
             *reinterpret_cast<const uint32_t *>(e + 0x10),
             *reinterpret_cast<const uint32_t *>(e + 0x14),
             *reinterpret_cast<const uint32_t *>(e + 0x18),
             *reinterpret_cast<const uint32_t *>(e + 0x1c),
             *reinterpret_cast<const uint32_t *>(e + 0x20),
             *reinterpret_cast<const uint32_t *>(e + 0x24));
    }
}

static uint32_t wrapPspNpFwInit(void *psp, void *arr, uint32_t count) {
    if (mask & X6) dumpFwDescriptors(static_cast<const uint8_t *>(arr), count);
#ifdef RGPU_HAVE_RLC_FW
    // Before the original memmoves the array to psp+0x2c08, so the substitution is what
    // gets copied and every later consumer sees it.
    if ((mask & X9) != 0 && arr != nullptr)
        substituteRlcFirmware(static_cast<uint8_t *>(arr), count);
#endif
    if (mask & X6) {
        RLOG("np_fw_init: descriptors after substitution --");
        dumpFwDescriptors(static_cast<const uint8_t *>(arr), count);
    }
    return FunctionCast(wrapPspNpFwInit, orgPspNpFwInit)(psp, arr, count);
}
static uint32_t pspReadCount = 0;
static uint32_t pspWriteCount = 0;

// Reads alone cannot tell whose command left a status in C2PMSG_64, so log the writes
// too. The GFX_CTRL command is the top half: 0x10000 INIT_RBI_RING, 0x20000
// INIT_GPCOM_RING, 0x30000 DESTROY_RINGS, 0x40000 CAN_INIT_RINGS, 0x70000 MODE1_RST.
static void wrapPspRegWrite(void *psp, uint32_t index, uint32_t instance,
                            uint32_t value, uint32_t hwip) {
    if (pspWriteCount < 32) {
        RLOG("psp_write(idx=0x%x inst=%u ip=0x%x) <- 0x%08x%s", index, instance, hwip, value,
             index == 0x80 ? "   <- C2PMSG_64 command" : "");
        pspWriteCount++;
    }
    FunctionCast(wrapPspRegWrite, orgPspRegWrite)(psp, index, instance, value, hwip);
}
static uint32_t wrapPspRegRead(void *psp, uint32_t index, uint32_t instance, uint32_t hwip) {
    uint32_t v = FunctionCast(wrapPspRegRead, orgPspRegRead)(psp, index, instance, hwip);
    if (pspReadCount < 48) {
        uint32_t regBase = 0;
        if (psp != nullptr && instance < 8)
            regBase = *reinterpret_cast<const uint32_t *>(
                static_cast<const uint8_t *>(psp) + 0x5c + 4 * instance);
        RLOG("psp_read(idx=0x%x inst=%u ip=0x%x) base=0x%x abs=0x%x -> 0x%08x%s",
             index, instance, hwip, regBase, regBase + index, v,
             index == 0x80 ? "   <- C2PMSG_64" : "");
        pspReadCount++;
    }
    return v;
}

// We present _AMD_DEVICE_TYPE 0x8, and HWLibs registers NO PP_SMC_UCODE_SBIN for it --
// only the VCN blob. That is Apple's own configuration, not a gap we introduced: of the
// five device types it registers firmware for, 0x8 is deliberately given no SMU image,
// because on that part the SMU microcode comes from the VBIOS via PSP rather than from
// the driver ("side loading" is the debug alternative, hence the companion property name
// SMU_FalconEnableSideLoading). smu_get_fw_constants already handles that:
//     709fd: test byte [smu+0x2d8], 1     ; skip firmware constants entirely
//     70a10: call smu_set_fw_entry_info_from_file
//     70a17: je  success
//     70a19: rcx = [smu+0x7a8]            ; else fall back to the driver's own source
//     70a2f: call rcx
// and smu_set_fw_entry_info_from_file itself returns 2 without even looking when bit
// 0x40 of that flags word is set. So returning 2 is exactly the documented "no file
// firmware for this part" answer, and it routes to the fallback instead of erroring.
static uint32_t wrapSmuFwFile(void *smu, void *out) {
    if (mask & X4) {
        RLOG("X4: no SMU microcode file for this device type; using the fallback source");
        return 2;
    }
    return FunctionCast(wrapSmuFwFile, orgSmuFwFile)(smu, out);
}

// Hand SMU HW_INIT to Apple's own dummy back end.
//
// With PSP HW_INIT complete the failure is SW_IP_CLIENT_ID__SMU / EVENT__HW_INIT.
// The chain is smu_internal_hw_init -> [smu+0x6c8] = smu_11_0_7_internal_hw_init ->
// smu_11_0_7_core_hw_init -> check_fw_status -> check_fw_version, which sends SMU
// message 3 (GetSmuVersion) on the Navi 2x mailbox and times out. That mailbox is
// MP1_SMN_C2PMSG_66/82/90 -- register indices 0x282 (msg), 0x292 (param), 0x29a
// (response), read straight out of smu_11_0_7_send_message and wait_for_response.
// This silicon does not have it there: upstream's smu_v13_0_5 uses MP1_C2PMSG_2/33/34
// at SMN 0x3b10508/0x3b10984/0x3b10988, an entirely different aperture.
//
// Retargeting those registers is possible -- smu_cgs_read_register already falls
// through to an indirect SMN accessor for any byte address above smu+0x2cc (0x80000)
// -- but it would put Navi 2x PPSMC message ids on the mailbox of the SMU that also
// governs this machine's CPU cores, whose message enum is completely different. Not
// something to do casually.
//
// It is also the wrong model. On an APU the SMU is the platform's, brought up by the
// x86 firmware long before macOS exists, and it stays up whether or not a guest driver
// talks to it. Apple already has a name for a GPU whose power management is somebody
// else's problem: PP_PhmUseDummyBackEnd. Setting that IORegistry property to 1 makes
// smu_init_function_pointer_list call smu_update_function_pointers after the 11_0_7
// list is built, which overwrites hw_init/dpm/thermal/fan/power/ulv/gfx_off and the
// rest with dummy_* stubs that return 0 -- so nothing downstream times out either.
//
// One hardware call survives that: dummy_smu_internal_hw_init still calls [smu+0x798],
// which the 11_0_7 list set to smu_11_0_7_dummy_hw_init, and that goes back into
// check_fw_status. smu_update_function_pointers does not clear the slot; nothing else
// in the SMU context reads it. So clear it here and dummy_smu_internal_hw_init returns
// 0 on its own (0x73952: xor r14d, r14d).
static uint32_t wrapSmuInitFnPtrs(void *smu, void *a, void *b) {
    auto r = FunctionCast(wrapSmuInitFnPtrs, orgSmuInitFnPtrs)(smu, a, b);
    if ((mask & XF) != 0 && smu != nullptr) {
        auto ctx = reinterpret_cast<uint8_t *>(smu);
        uint32_t hwver = *reinterpret_cast<uint32_t *>(ctx + 0x2c8);
        uint32_t dummy = *reinterpret_cast<uint32_t *>(ctx + 0x338);
        uint16_t flags = *reinterpret_cast<uint16_t *>(ctx + 0x2d8);
        auto slot = reinterpret_cast<void **>(ctx + 0x798);
        RLOG("XF: smu_init_function_pointer_list -> %u  hw_version=%u  flags=0x%04x  "
             "PP_PhmUseDummyBackEnd=%u  asic_dummy_hw_init=%p",
             r, hwver, flags, dummy, *slot);
        // The property does not reach HWLibs -- injected on the IOPCIDevice it reads back
        // as 0 here -- so do not depend on it. smu_update_function_pointers is what
        // PP_PhmUseDummyBackEnd would have caused; call it directly. It is idempotent:
        // it only stores pointers.
        if (dummy != 1 && hwlibsBase != 0) {
            auto upd = reinterpret_cast<uint32_t (*)(void *)>(hwlibsBase + kOffSmuUpdFnPtrs);
            RLOG("XF: PP_PhmUseDummyBackEnd is not set; calling smu_update_function_pointers "
                 "directly -> %u", upd(smu));
        }
        if (*slot != nullptr) {
            *slot = nullptr;
            RLOG("XF: cleared [smu+0x798] so the dummy back end makes no hardware call");
        }
        RLOG("XF: hw_init is now %p (dummy_smu_internal_hw_init)",
             *reinterpret_cast<void **>(ctx + 0x6c8));
    }
    return r;
}

// HW_INIT fails with "Firmware PP_SMC_UCODE_SBIN not found in directory, for deviceId
// 0x000073ff". The directory is keyed on _AMD_DEVICE_TYPE, not the PCI id, and HWLibs
// only ever registers five of them (putFirmware is called nine times, for device types
// 0x3, 0x4, 0x5, 0x6 and 0x8 -- and 0x8 gets only the VCN blob, no SMU image). So the
// question is which device type we present. Log it.
static void *wrapFwDirGet(void *dir, uint32_t devType, const char *name) {
    auto r = FunctionCast(wrapFwDirGet, orgFwDirGet)(dir, devType, name);
    RLOG("fw_dir_get(devType=0x%x, \"%s\") -> %s", devType, name ? name : "(null)",
         r != nullptr ? "hit" : "MISS");
    return r;
}

// gvm_sw_init runs mc_sw_init -> vm_sw_init -> hdp_sw_init -> athub_sw_init and returns
// the first nonzero, with no per-stage event id, so "SW_IP_CLIENT_ID__GVM
// event_id=0xc00c0205" does not say which one failed. All four resolve their handlers
// through this one function, and its table argument identifies the caller exactly:
//   +0x115c430 mc   +0x115c750 hdp   +0x115c9e0 vm   +0x115d9a0 athub
// A MISS here is an IP version this chip reports that Apple ships no row for.
static uint64_t wrapGvmGetIpFn(uint32_t maj, uint32_t min, uint32_t rev, uint32_t idx,
                               void *tbl, uint32_t count) {
    auto r = FunctionCast(wrapGvmGetIpFn, orgGvmGetIpFn)(maj, min, rev, idx, tbl, count);
    RLOG("gvm_get_ip_function(%u.%u.%u fn=%u tbl=+0x%llx n=%u) -> %s",
         maj, min, rev, idx,
         static_cast<uint64_t>(reinterpret_cast<mach_vm_address_t>(tbl) - hwlibsBase),
         count, r != 0 ? "ok" : "MISS");
    return r;
}

// Route the CALLER, never DevGetDeviceInfoEntry itself. That function's prologue is
//     af0e0: push rbp; mov rbp,rsp; lea rcx,[rip + _DeviceCapabilityTbl]; ...
// and the rip-relative lea sits inside the bytes Lilu overwrites to install its jump.
// Lilu's trampoline copies those instructions to a new address WITHOUT rewriting the
// displacement, so calling the "original" through it loads a garbage table pointer and
// every lookup misses -- including (0x73ff, 0, 0xcb), which is a verbatim entry in the
// table. That produced a completely misleading "no entry at any revision".
// ttlSetDeviceCapabilityEntry's own prologue is pushes and reg-to-reg moves only, so it
// is safe to route, and re-calling it redoes the whole side effect (it stores the entry
// at ttl+0xe8 and then rebuilds the HWIP->SWIP mappings) instead of half of it.
static bool wrapTtlSetDevCap(void *ttl, uint32_t devId, uint32_t intRev, uint32_t extRev) {
    auto org = FunctionCast(wrapTtlSetDevCap, orgTtlSetDevCap);
    bool r = org(ttl, devId, intRev, extRev);
    RLOG("ttlSetDeviceCapabilityEntry(dev=0x%x int=0x%x ext=0x%x) -> %d",
           devId, intRev, extRev, r);
    if (r || !(mask & X2)) return r;
    // Apple's table only ever uses internal revision 0, 1 or 2; this chip reports 0xf.
    for (uint32_t cand = 0; cand < 3; cand++) {
        if (cand == intRev) continue;
        r = org(ttl, devId, cand, extRev);
        RLOG("X2: retry with internal revision %u -> %d", cand, r);
        if (r) return r;
    }
    RLOG("X2: device 0x%x external revision 0x%x is not in the table",
           devId, extRev);
    return false;
}


// Rewrite the versions in the ipconfig table ITSELF, every entry, the first time we see
// it -- not lazily inside the accessor. mc_sw_init does not use the accessor at all:
//     1aaec: cmp dword ptr [r15 + rax - 0x10], 0x46   ; scan entries, stride 0x260
// it walks a copy of these entries directly, so a version rewritten only when
// ipconfig_get_ip_discovery_info happens to be called for that id never reaches it, and
// nothing ever looks UMC up through the accessor. Rewriting the table keeps every
// consumer -- accessor or not -- seeing one consistent version.
static void applyRemapsToTable(void *ipconfig) {
    auto base = static_cast<uint8_t *>(ipconfig);
    uint32_t n = *reinterpret_cast<const uint32_t *>(base + 0x1c);
    if (n > 64) return;
    for (uint32_t i = 0; i < n; i++) {
        auto e = base + 0x20 + static_cast<size_t>(i) * 0x260;
        uint32_t id = *reinterpret_cast<const uint32_t *>(e);
        for (auto &rm : remaps) {
            if (rm.appleId != id) continue;
            auto maj = reinterpret_cast<uint16_t *>(e + 0x08);
            auto mn  = reinterpret_cast<uint16_t *>(e + 0x0c);
            auto rv  = reinterpret_cast<uint16_t *>(e + 0x10);
            if (*maj == rm.maj && *mn == rm.min && *rv == rm.rev) break;
            RLOG("REMAP id=0x%x %u.%u.%u -> %u.%u.%u  (%s)",
                 id, *maj, *mn, *rv, rm.maj, rm.min, rm.rev, rm.why);
            *maj = rm.maj; *mn = rm.min; *rv = rm.rev;
            break;
        }
    }
}

static void *wrapIpcfgGet(void *ipconfig, uint32_t id) {
    if (!dumpedTable && ipconfig != nullptr) {
        dumpedTable = true;
        auto base = static_cast<const uint8_t *>(ipconfig);
        uint32_t n = *reinterpret_cast<const uint32_t *>(base + 0x1c);
        RLOG("ipconfig table: %u entries", n);
        if (n <= 64) {
            for (uint32_t i = 0; i < n; i++) {
                auto e = base + 0x20 + static_cast<size_t>(i) * 0x260;
                RLOG("  ip[%u] id=0x%x ver=%u.%u.%u", i,
                     *reinterpret_cast<const uint32_t *>(e + 0x00),
                     *reinterpret_cast<const uint16_t *>(e + 0x08),
                     *reinterpret_cast<const uint16_t *>(e + 0x0c),
                     *reinterpret_cast<const uint16_t *>(e + 0x10));
            }
        }
        if (mask & R1) applyRemapsToTable(ipconfig);
    }
    void *r = FunctionCast(wrapIpcfgGet, orgIpcfgGet)(ipconfig, id);
    if (r == nullptr) RLOG("ipcfg_get(id=0x%x) -> NOT FOUND", id);
    return r;
}

static int wrapBifIpCreate(void *bcs, void *info, void *out) {
    if (info != nullptr) {
        auto p = static_cast<const uint8_t *>(info);
        uint16_t maj = *reinterpret_cast<const uint16_t *>(p + 0x08);
        uint16_t min = *reinterpret_cast<const uint16_t *>(p + 0x0c);
        uint16_t rev = *reinterpret_cast<const uint16_t *>(p + 0x10);
        RLOG("bif_ip_create: id=0x%x ver=%u.%u.%u packed=0x%x",
               *reinterpret_cast<const uint32_t *>(p + 0x00), maj, min, rev,
               (static_cast<uint32_t>(maj) << 16) | (static_cast<uint32_t>(min) << 8) | rev);
    } else {
        RLOG("bif_ip_create: info == NULL");
    }
    int r = FunctionCast(wrapBifIpCreate, orgBifIpCreate)(bcs, info, out);
    RLOG("bif_ip_create returned %d", r);
    return r;
}

static void installDiagnostics(KernelPatcher &patcher, mach_vm_address_t base) {
    RLOG("installDiagnostics: entered, base=0x%llx", base);
    orgIpcfgGet = patcher.routeFunction(base + kOffIpcfgGet,
                      reinterpret_cast<mach_vm_address_t>(wrapIpcfgGet), true);
    RLOG("route ipconfig_get_ip_discovery_info -> %s (org=0x%llx)",
           orgIpcfgGet ? "ok" : "FAILED", orgIpcfgGet);
    patcher.clearError();
    orgBifIpCreate = patcher.routeFunction(base + kOffBifIpCreate,
                      reinterpret_cast<mach_vm_address_t>(wrapBifIpCreate), true);
    RLOG("route bif_ip_create -> %s (org=0x%llx)",
           orgBifIpCreate ? "ok" : "FAILED", orgBifIpCreate);
    patcher.clearError();
    addrGetDevInf = base + kOffGetDevInf;
    orgCheckPcieLink = patcher.routeFunction(base + kOffCheckPcie,
                      reinterpret_cast<mach_vm_address_t>(wrapCheckPcieLink), true);
    RLOG("route check_pcie_link_status -> %s (org=0x%llx)",
           orgCheckPcieLink ? "ok" : "FAILED", orgCheckPcieLink);
    patcher.clearError();
    hwlibsBase = base;
    orgCosRelMemHnd = patcher.routeFunction(base + kOffCosRelMemHnd,
                      reinterpret_cast<mach_vm_address_t>(wrapCosRelMemHnd), true);
    RLOG("route cosReleaseMemoryHandle -> %s (org=0x%llx)",
         orgCosRelMemHnd ? "ok" : "FAILED", orgCosRelMemHnd);
    patcher.clearError();
    orgPspTmrInit = patcher.routeFunction(base + kOffPspTmrInit,
                      reinterpret_cast<mach_vm_address_t>(wrapPspTmrInit), true);
    RLOG("route psp_tmr_init -> %s (org=0x%llx)",
         orgPspTmrInit ? "ok" : "FAILED", orgPspTmrInit);
    patcher.clearError();
    orgPspBufPrep = patcher.routeFunction(base + kOffPspBufPrep,
                      reinterpret_cast<mach_vm_address_t>(wrapPspBufPrep), true);
    RLOG("route psp_cmd_km_buf_prep -> %s (org=0x%llx)",
         orgPspBufPrep ? "ok" : "FAILED", orgPspBufPrep);
    patcher.clearError();
    orgPspFwCapChk = patcher.routeFunction(base + kOffPspFwCapChk,
                      reinterpret_cast<mach_vm_address_t>(wrapPspFwCapChk), true);
    RLOG("route psp_np_fw_load_capability_check -> %s (org=0x%llx)",
         orgPspFwCapChk ? "ok" : "FAILED", orgPspFwCapChk);
    patcher.clearError();
    orgPspRingCreate = patcher.routeFunction(base + kOffPspRingCreate,
                      reinterpret_cast<mach_vm_address_t>(wrapPspRingCreate), true);
    RLOG("route psp_ring_create_11_0 -> %s (org=0x%llx)",
         orgPspRingCreate ? "ok" : "FAILED", orgPspRingCreate);
    patcher.clearError();
    orgPspNpFwInit = patcher.routeFunction(base + kOffPspNpFwInit,
                      reinterpret_cast<mach_vm_address_t>(wrapPspNpFwInit), true);
    RLOG("route psp_np_fw_init -> %s (org=0x%llx)",
         orgPspNpFwInit ? "ok" : "FAILED", orgPspNpFwInit);
    patcher.clearError();
    orgPspRegWrite = patcher.routeFunction(base + kOffPspRegWrite,
                      reinterpret_cast<mach_vm_address_t>(wrapPspRegWrite), true);
    RLOG("route psp_cgs_write_register -> %s (org=0x%llx)",
         orgPspRegWrite ? "ok" : "FAILED", orgPspRegWrite);
    patcher.clearError();
    orgPspRegRead = patcher.routeFunction(base + kOffPspRegRead,
                      reinterpret_cast<mach_vm_address_t>(wrapPspRegRead), true);
    RLOG("route psp_cgs_read_register -> %s (org=0x%llx)",
         orgPspRegRead ? "ok" : "FAILED", orgPspRegRead);
    patcher.clearError();
    orgSmuFwFile = patcher.routeFunction(base + kOffSmuFwFile,
                      reinterpret_cast<mach_vm_address_t>(wrapSmuFwFile), true);
    RLOG("route smu_set_fw_entry_info_from_file -> %s (org=0x%llx)",
         orgSmuFwFile ? "ok" : "FAILED", orgSmuFwFile);
    patcher.clearError();
    orgSmuInitFnPtrs = patcher.routeFunction(base + kOffSmuInitFnPtrs,
                      reinterpret_cast<mach_vm_address_t>(wrapSmuInitFnPtrs), true);
    RLOG("route smu_init_function_pointer_list -> %s (org=0x%llx)",
         orgSmuInitFnPtrs ? "ok" : "FAILED", orgSmuInitFnPtrs);
    patcher.clearError();
    orgFwDirGet = patcher.routeFunction(base + kOffFwDirGet,
                      reinterpret_cast<mach_vm_address_t>(wrapFwDirGet), true);
    RLOG("route AMDFirmwareDirectory::getFirmware -> %s (org=0x%llx)",
         orgFwDirGet ? "ok" : "FAILED", orgFwDirGet);
    patcher.clearError();
    orgGvmGetIpFn = patcher.routeFunction(base + kOffGvmGetIpFn,
                      reinterpret_cast<mach_vm_address_t>(wrapGvmGetIpFn), true);
    RLOG("route gvm_get_ip_function -> %s (org=0x%llx)",
         orgGvmGetIpFn ? "ok" : "FAILED", orgGvmGetIpFn);
    patcher.clearError();
    orgTtlSetDevCap = patcher.routeFunction(base + kOffTtlSetDevCap,
                      reinterpret_cast<mach_vm_address_t>(wrapTtlSetDevCap), true);
    RLOG("route ttlSetDeviceCapabilityEntry -> %s (org=0x%llx)",
           orgTtlSetDevCap ? "ok" : "FAILED", orgTtlSetDevCap);
    patcher.clearError();
}

#if defined(RGPU_HAVE_RLC_FW) && RGPU_HAVE_TOC_FW
// Substitute this chip's own signed PSP TOC for Apple's.
//
// LOAD_TOC is the FIRST command Apple sends the PSP and it is the first thing that fails:
//     cmd[00] wire 32 LOAD_TOC   -> status=0x8000030a  tmr_size=0
//     cmd[01] wire  5 SETUP_TMR  -> status=0xffff0006  (TEE_ERROR_BAD_PARAMETERS)
//     cmd[02] wire  4 LOAD_ASD   -> status=0x00000007
// With no TOC there is no TMR size, so the TMR is never established and every firmware
// load afterwards is building on nothing. That, not the RLC blobs, is the root failure --
// the 0x8000030a I had earlier attributed to the RLC restore list is LOAD_TOC's status.
//
// Apple's TOC is _aPSP_TOC_SIGNED at HWLibs VMA 0x1155d40: a $PS1 container, total 0x600,
// fw_type 0x0000200e, fw_version 0. This chip's own psp_13_0_5_toc.bin carries the same
// 0x600-byte container with fw_type 0x0101200e and fw_version 3, signed with the identical
// key (30b8865125424499aeff3ac35ce621a6). Same size, so this is a straight drop-in.
//
// Note the pattern: Apple's blob has the high half of $PS1+0x58 unstamped and version 0,
// where this chip's firmware is stamped and versioned. The same difference shows up across
// Apple's RLC blobs, which is consistent with an MP0 13.0.5 PSP that requires the stamp
// where MP0 11.0.12 did not.
//
// Done through applyLookupPatch rather than a raw memcpy so Lilu handles the kext's
// memory protection, and matched on the whole 0x600-byte container so it cannot hit
// anything else.
static void substituteOneToc(KernelPatcher &patcher, const char *what, const uint8_t *find) {
    KernelPatcher::LookupPatch lp {&kexts[KextHWLibs], find, kRaphaelToc, kTocSize, 1};
    patcher.applyLookupPatch(&lp);
    auto err = patcher.getError();
    patcher.clearError();
    RLOG("XB: %s fw_type 0x%x ver %u -> 0x%x ver %u : %s", what,
         *reinterpret_cast<const uint32_t *>(find + 0x58),
         *reinterpret_cast<const uint32_t *>(find + 0x60),
         *reinterpret_cast<const uint32_t *>(kRaphaelToc + 0x58),
         *reinterpret_cast<const uint32_t *>(kRaphaelToc + 0x60),
         err == KernelPatcher::Error::NoError ? "substituted" : "NOT FOUND");
}

static void substituteToc(KernelPatcher &patcher) {
    // psp_tmr_init reads its TOC from runtime fields psp+0x3588 (pointer) and psp+0x3580
    // (size), so which of the two 0x600-byte $PS1 containers is actually submitted cannot be
    // determined statically. Replace both. _TOC_TABLE is the more likely one: its $PS1 FW ID
    // is 0, and 0x8000030a is precisely "unrecognised firmware type".
    substituteOneToc(patcher, "_aPSP_TOC_SIGNED", kAppleToc);
    substituteOneToc(patcher, "_TOC_TABLE      ", kAppleToc2);
}
#endif

static void applyFor(KernelPatcher &patcher, bool hwlibs) {
    for (auto &p : patches) {
        if (!(p.bit & mask) || p.onHWLibs != hwlibs) continue;
        if (p.r1Conflict && (mask & R1)) {
            RLOG("SKIPPED  %s (R1 already remaps this version)", p.what);
            continue;
        }
        KernelPatcher::LookupPatch lp {
            &kexts[hwlibs ? KextHWLibs : KextFB], p.find, p.repl, p.size, 1
        };
        patcher.applyLookupPatch(&lp);
        auto err = patcher.getError();
        patcher.clearError();
        if (err == KernelPatcher::Error::NoError)
            RLOG("APPLIED  %s", p.what);
        else
            RLOG("FAILED(%d) %s", static_cast<int>(err), p.what);
    }
}

// Patch as soon as the kernel patcher exists. THIS IS THE POINT OF THE WHOLE
// EXERCISE: the kext-load callback arrives far too late. Measured from serial,
// one boot:
//     1189  rgpu start
//     1211  [GPUCAP] -- the AMD driver's start() is ALREADY RUNNING
//     1243  bgm_create assert
//     1309  event_id=0xc00c0203  -- BGM has already failed
//     1459  our HWLibs patch finally applies (~200 lines too late)
//     1474  doGPUPanic runs -- AFTER our patch, which is the only reason that
//           one patch ever had a visible effect
// onPatcherLoad fires at ~1189, ahead of the driver, so patches land in time.
static void onPatcher(void *, KernelPatcher &patcher) {
    // Informational only. loadKinfo() here maps the kext's FILE (so symbols can be
    // solved) but leaves the running address at 0 until the kext is actually loaded,
    // and applyLookupPatch(patch) dereferences exactly that address -- patching from
    // here page-faults on a null base. Since Lilu now comes from the boot KC via
    // OpenCore's Kernel>Add, the ordinary kext-load callback already runs before the
    // AMD driver's start(), which is the whole reason the early path was attempted.
    RLOG("patcher ready, mask=0x%x -- waiting for the kext-load callback", mask);
    if (mask == 0) return;
    for (size_t i = 0; i < arrsize(kexts); i++) {
        patcher.loadKinfo(&kexts[i]);
        auto err = patcher.getError();
        patcher.clearError();
        RLOG("loadKinfo(%s) -> loadIndex=%lu err=%d", kexts[i].id,
               kexts[i].loadIndex, static_cast<int>(err));
    }
}

// Our plugin lives in the AuxKC, which loads AFTER the boot KC that holds the AMD
// stack -- so by the time we can patch anything, AmdRadeonControllerNavi23::start()
// has already run and failed. Measured ordering on one boot:
//     1125  rgpu start            1195  [GPUCAP]  (start() already running)
//     1298  event_id=0xc00c0203   1455  our patch finally lands
// Lilu's onPatcherLoad does not help: its patcher is initialised before our
// pluginStart registers, so the callback is never invoked (verified -- it logged
// nothing at all).
// The patches themselves are live from 1455 onward. So instead of loading earlier,
// ask IOKit to re-probe the GPU's PCI device: matching re-runs and the controller's
// start() executes again, this time against patched code.
static void reprobeGpu() {
    auto matching = IOService::serviceMatching("IOPCIDevice");
    if (matching == nullptr) { RLOG("reprobe: serviceMatching failed"); return; }
    auto iter = IOService::getMatchingServices(matching);
    matching->release();
    if (iter == nullptr) { RLOG("reprobe: no IOPCIDevice iterator"); return; }
    unsigned found = 0;
    while (auto obj = iter->getNextObject()) {
        auto svc = OSDynamicCast(IOService, obj);
        if (svc == nullptr) continue;
        auto vid = OSDynamicCast(OSData, svc->getProperty("vendor-id"));
        if (vid == nullptr || vid->getLength() < 2) continue;
        uint16_t v = *static_cast<const uint16_t *>(vid->getBytesNoCopy());
        if (v != 0x1002) continue;
        uint16_t d = 0;
        if (auto did = OSDynamicCast(OSData, svc->getProperty("device-id")))
            if (did->getLength() >= 2) d = *static_cast<const uint16_t *>(did->getBytesNoCopy());
        found++;
        auto r = svc->requestProbe(0);
        RLOG("reprobe %04x:%04x -> 0x%x", v, d, r);
    }
    iter->release();
    RLOG("reprobe: %u AMD device(s) touched", found);
}

static void processKext(void *, KernelPatcher &patcher, size_t index,
                        mach_vm_address_t addr, size_t sz) {
    RLOG("kext callback: index=%lu hwlibs=%lu fb=%lu addr=%llx size=%lu",
           index, kexts[KextHWLibs].loadIndex, kexts[KextFB].loadIndex, addr, sz);
    if (kexts[KextHWLibs].loadIndex == index) {
        RLOG("HWLibs loaded, mask=0x%x", mask);
        applyFor(patcher, true);
        RLOG("post-patch: mask=0x%x D1=%d R1=%d base=0x%llx",
               mask, (mask & D1) != 0, (mask & R1) != 0, addr);
#if defined(RGPU_HAVE_RLC_FW) && RGPU_HAVE_TOC_FW
        if (mask & XB) substituteToc(patcher);
#endif
        if (mask & (D1 | R1 | X1 | X2 | X3 | X4 | X5 | X6 | X7 | X8 | XA | XC | XE | XF)) installDiagnostics(patcher, addr);
    } else if (kexts[KextFB].loadIndex == index) {
        RLOG("Framebuffer loaded, mask=0x%x", mask);
        applyFor(patcher, false);
        // Both kexts are patched by now, so this is the moment to retry start().
        if (mask & P1) reprobeGpu();
    }
}

static void pluginStart() {
    if (!PE_parse_boot_argn("rgpu", &mask, sizeof(mask))) mask = 0;
    uint32_t d = 0;
    if (PE_parse_boot_argn("rgpudump", &d, sizeof(d)) && d >= 5000 && d <= 300000)
        diagDumpDelayMs = d;
    RLOG("start, patch mask=0x%x (%lu patches known)", mask, arrsize(patches));
#ifdef RGPU_HAVE_RLC_FW
    RLOG("embedded RLC firmware: %u bytes, size_bytes field 0x%x", kRlcFwSize,
         *reinterpret_cast<const uint32_t *>(kRlcFw));
#else
    RLOG("no embedded RLC firmware (rlc_fw.h absent)");
#endif
    if (mask == 0) {
        RLOG("no rgpu= boot-arg, staying inert");
        return;
    }
    thread_t th {};
    if (kernel_thread_start(diagDumpThread, nullptr, &th) == KERN_SUCCESS)
        thread_deallocate(th);
    else
        RLOG("could not start the deferred diagnostics thread");
    lilu.onPatcherLoadForce(onPatcher);
    lilu.onKextLoadForce(kexts, arrsize(kexts), processKext, nullptr);
    RLOG("registered %lu kexts (Loaded flag set)", arrsize(kexts));
}

static const char *bootargOff[]   { "-rgpuoff" };
static const char *bootargDebug[] { "-rgpudbg" };
static const char *bootargBeta[]  { "-rgpubeta" };

PluginConfiguration ADDPR(config) {
    xStringify(PRODUCT_NAME),
    parseModuleVersion(xStringify(MODULE_VERSION)),
    LiluAPI::AllowNormal | LiluAPI::AllowSafeMode,
    bootargOff,   arrsize(bootargOff),
    bootargDebug, arrsize(bootargDebug),
    bootargBeta,  arrsize(bootargBeta),
    KernelVersion::Catalina,
    KernelVersion::Sequoia,
    pluginStart
};
