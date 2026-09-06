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

static void diagDumpThread(void *, wait_result_t) {
    IOSleep(75000);   // logd is up well before this; the login window is not yet reached
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
};

static mach_vm_address_t orgIpcfgGet {};
static mach_vm_address_t orgBifIpCreate {};
static bool dumpedTable = false;

static mach_vm_address_t orgTtlSetDevCap {};
static mach_vm_address_t orgGvmGetIpFn {};
static mach_vm_address_t hwlibsBase {};

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
        if (mask & (D1 | R1 | X1 | X2)) installDiagnostics(patcher, addr);
    } else if (kexts[KextFB].loadIndex == index) {
        RLOG("Framebuffer loaded, mask=0x%x", mask);
        applyFor(patcher, false);
        // Both kexts are patched by now, so this is the moment to retry start().
        if (mask & P1) reprobeGpu();
    }
}

static void pluginStart() {
    if (!PE_parse_boot_argn("rgpu", &mask, sizeof(mask))) mask = 0;
    RLOG("start, patch mask=0x%x (%lu patches known)", mask, arrsize(patches));
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
