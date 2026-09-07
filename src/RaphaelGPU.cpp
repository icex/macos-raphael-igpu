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
static const char *pathX6000[] {
    "/System/Library/Extensions/AMDRadeonX6000.kext/Contents/MacOS/AMDRadeonX6000"
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
enum { KextHWLibs, KextFB, KextX6000 };
static KernelPatcher::KextInfo kexts[] {
    {"com.apple.kext.AMDRadeonX6000HWLibs", pathHWLibs, arrsize(pathHWLibs),
     {true}, {}, KernelPatcher::KextInfo::Unloaded},
    {"com.apple.kext.AMDRadeonX6000Framebuffer", pathFB, arrsize(pathFB),
     {true}, {}, KernelPatcher::KextInfo::Unloaded},
    {"com.apple.kext.AMDRadeonX6000", pathX6000, arrsize(pathX6000),
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
    XG = 1u << 26,  // take the framebuffer aperture from the GFXHUB copy
    XH = 1u << 27,  // give the accelerator's memory pools a range that is not inverted
    XI = 1u << 28,  // tell PowerPlay it is unsupported instead of letting it power down
    XJ = 1u << 29,  // trace the accelerator's hardware power-up chain
    XK = 1u << 30,  // start the RLC microcontroller before the engines power up
    XL = 1u << 31,  // accept the RLC firmware autoload on BOOTLOAD_COMPLETE alone
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
static constexpr size_t kOffGcAutoloadDone = 0xf5b1;   // _gc_fw_autoload_is_completed
static constexpr size_t kOffGcCheckRegEq   = 0xb3a0;   // _gc_check_register_equal_ext
static constexpr size_t kOffSdmaAutoloadDone = 0x6028c; // _sdma_5_2_fw_autoload_is_completed
static constexpr size_t kOffBifDbAperCtl   = 0x23a0f2; // _bif_doorbell_aperture_control
static constexpr size_t kOffBif62EnableDb  = 0x23c22b; // _bif6_2_enable_doorbell_aperture
static constexpr size_t kOffBif61EnableDb  = 0x23b627; // _bif6_1_enable_doorbell_aperture
static constexpr size_t kOffBif50EnableDb  = 0x23ac1b; // _bif50_enable_doorbell_aperture
static constexpr size_t kOffNbio72EnableDb = 0x24137e; // _nbio7_2_enable_doorbell_aperture
static constexpr size_t kOffNbio23EnableDb = 0x23ddcb; // _nbio2_3_enable_doorbell_aperture
static constexpr size_t kOffBcsReadMmr     = 0x23579c; // _bcs_read_mmr (called, not routed)
static constexpr size_t kOffGcCgsWrite2    = 0xb519;   // _gc_cgs_write_register_ext2
static constexpr size_t kOffGcCgsWrite     = 0xb4de;   // _gc_cgs_write_register
static constexpr size_t kOffGcCgsWriteExt  = 0xb4a0;   // _gc_cgs_write_register_ext

// AMDRadeonX6000Framebuffer, not HWLibs.
static constexpr size_t kOffFbXgmiConfig = 0x3b3e0;    // AmdAsicInfoNavi2::populateXGmiConfig [fb]
static constexpr size_t kOffPpPowerUp    = 0x101a0;    // AmdPowerPlayHelper::powerUp [fb]

// AMDRadeonX6000, the accelerator.
static constexpr size_t kOffHwMemVram   = 0x527a4;    // AMDHWMemory::initVRAMInfo [x6]
static constexpr size_t kOffHwMemEnable = 0x52a1e;    // AMDHWMemory::enableAllocations [x6]
static constexpr size_t kOffAccPowerUpHW = 0x4e0c;   // AMDGraphicsAccelerator::powerUpHW [x6]
static constexpr size_t kOffHwPowerUp    = 0x99618;  // AMDNavi23Hardware::powerUp [x6]
static constexpr size_t kOffHwEngPowerUp = 0x6fe9a;  // AMDHardware::powerUpHWEngines [x6]
static constexpr size_t kOffHwEngStart   = 0x6ffd2;  // AMDHardware::startHWEngines [x6]
static constexpr size_t kOffPm4Mqd       = 0x69362;  // AMDGFX10PM4Engine::initComputeMQD [x6]
static constexpr size_t kOffKiqStart     = 0x8e670;  // AMDGFX10KIQHWChannel::startKIQ [x6]
static constexpr size_t kOffPm4GfxMqd    = 0x6952a;  // AMDGFX10PM4Engine::initGraphicsMQD [x6]
static constexpr size_t kOffKiqMapQ      = 0x8e45e;  // AMDGFX10KIQHWChannel::submitMapQueuesPacket [x6]
static constexpr size_t kOffKiqSubmit    = 0x5c716;  // AMDKIQHWChannel::submitKIQFrame [x6]
static constexpr size_t kOffWaitStamp    = 0x4c520;  // AMDHWChannel::waitForHwStamp [x6]
// GFX_CTRL command encodings, from upstream psp_gfx_if.h.
static constexpr uint32_t kC2PMsg64        = 0x80;       // MP0 C2PMSG_64, IP-relative
static constexpr uint32_t kHwIpMp0         = 0x4b;
static constexpr uint32_t kDestroyGpcomRing = 0x000C0000;
static constexpr uint32_t kDestroyRings     = 0x00030000;   // destroys RBI/UM *and* GPCOM
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
static mach_vm_address_t orgGcAutoloadDone {};
static mach_vm_address_t orgGcCheckRegEq {};
static mach_vm_address_t orgSdmaAutoloadDone {};
static mach_vm_address_t orgBifDbAperCtl {};
static mach_vm_address_t orgBif62EnableDb {};
static mach_vm_address_t orgBif61EnableDb {};
static mach_vm_address_t orgBif50EnableDb {};
static mach_vm_address_t orgNbio72EnableDb {};
static mach_vm_address_t orgNbio23EnableDb {};
static mach_vm_address_t orgGcCgsWrite2 {};
static mach_vm_address_t orgGcCgsWrite {};
static mach_vm_address_t orgGcCgsWriteExt {};
static mach_vm_address_t orgFbXgmiConfig {};
static mach_vm_address_t orgHwMemVram {};
static mach_vm_address_t orgHwMemEnable {};
static mach_vm_address_t orgAccPowerUpHW {};
static mach_vm_address_t orgHwPowerUp {};
static mach_vm_address_t orgHwEngPowerUp {};
static mach_vm_address_t orgHwEngStart {};
static mach_vm_address_t orgPm4Mqd {};
static mach_vm_address_t orgKiqStart {};
static mach_vm_address_t orgPm4GfxMqd {};
static mach_vm_address_t orgKiqMapQ {};
static mach_vm_address_t orgKiqSubmit {};
static mach_vm_address_t orgWaitStamp {};

// AmdAsicInfoNavi2 keeps the register accessor this whole file uses to read GPU
// registers: [asicInfo+0x28] is the accessor object and its vtable slot 0x140 is
// read32(index). Remembered on the first populateXGmiConfig so the accelerator hooks,
// which have no AsicInfo of their own, can read the graphics core's status registers.
static void *asicInfo {};
// AMDRadeonX6000_AMDHardware, captured on the way into powerUpHWEngines. Its
// mapDoorbellMemory stores the BAR2 mapping at +0x520 and that mapping's virtual address
// at +0x528, so [hwObj+0x528] is the base of the doorbell aperture as the guest sees it.
static void *hwObj {};
static bool cpcWedged = false;
// A GC context, captured from any TTL register write, so this plugin can use TTL's own
// register path (_gc_cgs_write_register_ext2) rather than only the framebuffer accessor.
static void *gcCtx {};
static uint64_t kiqEopHint {};

// AmdRegisterAccess vtable: 0x138 writeReg32(index, value), 0x140 hwReadReg32(index).
static void fbWrite(void *self, uint32_t idx, uint32_t val) {
    if (self == nullptr) return;
    auto obj = *reinterpret_cast<void **>(reinterpret_cast<uint8_t *>(self) + 0x28);
    if (obj == nullptr) return;
    auto vt = *reinterpret_cast<uint64_t **>(obj);
    auto wr = reinterpret_cast<void (*)(void *, uint32_t, uint32_t)>(vt[0x138 / 8]);
    wr(obj, idx, val);
}

static uint32_t fbRead(void *self, uint32_t idx) {
    auto obj = *reinterpret_cast<void **>(reinterpret_cast<uint8_t *>(self) + 0x28);
    if (obj == nullptr) return 0xdeadbeef;
    auto vt = *reinterpret_cast<uint64_t **>(obj);
    auto rd = reinterpret_cast<uint32_t (*)(void *, uint32_t)>(vt[0x140 / 8]);
    return rd(obj, idx);
}

// SOC15 register offsets are base_table[BASE_IDX] + reg, and HWLibs uses exactly that:
// gc_reg_offset(table, reg, base_idx) is reg + table[base_idx] (0xb197), and
// gc_enter_rlc_safe_mode_10_3 passes RLC_CNTL 0x4c00 with base_idx 1. Getting this wrong
// is silent: reads land on some other register and come back plausible. RLC_* and
// SCRATCH_REG0 are BASE_IDX 1; GRBM/CP/GCVM/GCMC are BASE_IDX 0.
static constexpr uint32_t kGcSeg0 = 0x1260;
static constexpr uint32_t kGcSeg1 = 0xa000;

static constexpr uint32_t kGcGrbmStatus  = kGcSeg0 + 0x0da4;
static constexpr uint32_t kGcGrbmStatus2 = kGcSeg0 + 0x0da2;
static constexpr uint32_t kGcCpStat      = kGcSeg0 + 0x0f40;
static constexpr uint32_t kGcCpMeCntl    = kGcSeg0 + 0x0f56;
static constexpr uint32_t kGcCpMecCntl   = kGcSeg0 + 0x0f55;
static constexpr uint32_t kGcRlcCntl     = kGcSeg1 + 0x4c00;
static constexpr uint32_t kGcRlcStat     = kGcSeg1 + 0x4c04;
static constexpr uint32_t kGcRlcBootStat = kGcSeg1 + 0x4e8d;   // RLC_RLCS_BOOTLOAD_STATUS
// The same register, at the offset the GC 10.3.x parts actually use. Upstream carries
// both: gfx_v10_0.c defines mmRLC_RLCS_BOOTLOAD_STATUS_Sienna_Cichlid = 0x4e7e (BASE_IDX 1)
// as a file-local and reads it, not the 0x4e8d in gc_10_3_0_offset.h, for GC 10.3.0/1/3/4/
// 5/6/7 -- i.e. for every Navi 2x and every RDNA2 APU, this chip included.
static constexpr uint32_t kGcRlcBootStatSc = kGcSeg1 + 0x4e7e;
static constexpr uint32_t kGcRlcGpmStat  = kGcSeg1 + 0x4e6e;
static constexpr uint32_t kGcRlcSafeMode = kGcSeg1 + 0x4ca0;
static constexpr uint32_t kGcCpfStatus   = kGcSeg0 + 0x0e27;
static constexpr uint32_t kGcCpcStatus   = kGcSeg0 + 0x0e24;
static constexpr uint32_t kGcVmFaultSts  = kGcSeg0 + 0x15c8;   // GCVM_L2_PROTECTION_FAULT_STATUS
static constexpr uint32_t kGcVmFaultLo   = kGcSeg0 + 0x15c9;
static constexpr uint32_t kGcVmFaultHi   = kGcSeg0 + 0x15ca;
static constexpr uint32_t kGcHqdActive   = kGcSeg0 + 0x1fab;
static constexpr uint32_t kGcRlcCgcg     = kGcSeg1 + 0x4c49;   // RLC_CGCG_CGLS_CTRL
static constexpr uint32_t kGcRlcPgCntl   = kGcSeg1 + 0x4c43;   // RLC_PG_CNTL
static constexpr uint32_t kGcScratch0    = kGcSeg1 + 0x2040;   // SCRATCH_REG0
static constexpr uint32_t kGcGrbmGfxCntl = kGcSeg0 + 0x0dc2;
static constexpr uint32_t kGcGrbmGfxIndex = kGcSeg1 + 0x2200;   // GRBM_GFX_INDEX   // GRBM_GFX_CNTL
static constexpr uint32_t kGcVmFaultCntl = kGcSeg0 + 0x15c4;   // GCVM_L2_PROTECTION_FAULT_CNTL, bit 0 clears the latched status
// The KIQ lives on a compute pipe, and CP_HQD_* are per-queue: GRBM_GFX_CNTL selects
// which one is visible (PIPEID bits 0-1, MEID bits 2-3, VMID 4-7, QUEUEID 8-10), the
// same thing upstream's nv_grbm_select does.
static constexpr uint32_t kGcMecHeaderDump = kGcSeg0 + 0x0e2e;   // CP_MEC_ME1_HEADER_DUMP
static constexpr uint32_t kGcMecDbLower    = kGcSeg0 + 0x1dfc;
static constexpr uint32_t kGcMecDbUpper    = kGcSeg0 + 0x1dfd;
static constexpr uint32_t kGcHqdPqBase     = kGcSeg0 + 0x1fb1;
static constexpr uint32_t kGcHqdPqRptr     = kGcSeg0 + 0x1fb3;
static constexpr uint32_t kGcHqdPqDbCtl    = kGcSeg0 + 0x1fb8;
static constexpr uint32_t kGcHqdPqWptrLo   = kGcSeg0 + 0x1fdf;
static constexpr uint32_t kGcHqdDequeue    = kGcSeg0 + 0x1fc1;   // CP_HQD_DEQUEUE_REQUEST
static constexpr uint32_t kGcGrbmSoftReset = kGcSeg0 + 0x0da8;   // GRBM_SOFT_RESET

// The command processor's instruction RAM, readable back through the same address/data
// pair the direct-load path writes it with. On the PSP load path nothing in the driver
// writes these -- the RLC's bootloader copies each microengine's ucode out of the
// PSP-verified copy in the TMR -- so reading them answers the one question the queue
// dumps cannot: is there any microcode in the CP at all. All BASE_IDX 1.
static constexpr uint32_t kGcPfpUcodeAddr  = kGcSeg1 + 0x5814;
static constexpr uint32_t kGcPfpUcodeData  = kGcSeg1 + 0x5815;
static constexpr uint32_t kGcMeRamRaddr    = kGcSeg1 + 0x5816;
static constexpr uint32_t kGcMeRamData     = kGcSeg1 + 0x5817;
static constexpr uint32_t kGcCeUcodeAddr   = kGcSeg1 + 0x5818;
static constexpr uint32_t kGcCeUcodeData   = kGcSeg1 + 0x5819;
static constexpr uint32_t kGcMec1UcodeAddr = kGcSeg1 + 0x581a;
static constexpr uint32_t kGcMec1UcodeData = kGcSeg1 + 0x581b;
static constexpr uint32_t kGcMec2UcodeAddr = kGcSeg1 + 0x581c;
static constexpr uint32_t kGcMec2UcodeData = kGcSeg1 + 0x581d;
static constexpr uint32_t kGcMec2HeaderDump = kGcSeg0 + 0x0e2f;

// The rest of the HQD, so a queue dump says which VMID it runs under and where its
// MQD is, not just that it is active.
static constexpr uint32_t kGcHqdPqBaseHi   = kGcSeg0 + 0x1fb2;
static constexpr uint32_t kGcHqdVmid       = kGcSeg0 + 0x1fac;
static constexpr uint32_t kGcHqdPqControl  = kGcSeg0 + 0x1fba;
static constexpr uint32_t kGcHqdPqWptrHi   = kGcSeg0 + 0x1fe0;
static constexpr uint32_t kGcHqdPollAddr   = kGcSeg0 + 0x1fb6;   // CP_HQD_PQ_WPTR_POLL_ADDR
static constexpr uint32_t kGcHqdPollAddrHi = kGcSeg0 + 0x1fb7;
static constexpr uint32_t kGcHqdRptrRpt    = kGcSeg0 + 0x1fb4;   // CP_HQD_PQ_RPTR_REPORT_ADDR
static constexpr uint32_t kGcHqdRptrRptHi  = kGcSeg0 + 0x1fb5;
static constexpr uint32_t kGcHqdEopBase    = kGcSeg0 + 0x1fce;
static constexpr uint32_t kGcHqdEopBaseHi  = kGcSeg0 + 0x1fcf;
static constexpr uint32_t kGcHqdEopControl = kGcSeg0 + 0x1fd0;
static constexpr uint32_t kGcHqdIbControl  = kGcSeg0 + 0x1fbe;
static constexpr uint32_t kGcHqdPqBaseHi2  = kGcSeg0 + 0x1fb2;   // same as kGcHqdPqBaseHi
static constexpr uint32_t kGcRlcSrmCntl    = kGcSeg1 + 0x4c80;
static constexpr uint32_t kGcRlcSrmStat    = kGcSeg1 + 0x4c9b;
static constexpr uint32_t kGcRlcCsibLo     = kGcSeg1 + 0x4ca2;
static constexpr uint32_t kGcRlcCsibLen    = kGcSeg1 + 0x4ca4;
// Per-queue error and status, and the microengines' instruction pointers. CP_HQD_ERROR
// carries one UTCL1-error bit per client the queue touches (PQ, IB, EOP, IQ, rptr-report,
// wptr-poll, ...), and CP_HQD_HQ_STATUS0 has QUEUE_IDLE plus DB_UPDATED_MSG_EN -- the bit
// that decides whether a doorbell write is even reported to the microengine.
static constexpr uint32_t kGcHqdError      = kGcSeg0 + 0x1fdc;
static constexpr uint32_t kGcHqdStatus0    = kGcSeg0 + 0x1fc9;
static constexpr uint32_t kGcHqdStatus1    = kGcSeg0 + 0x1fcc;
static constexpr uint32_t kGcMqdControl    = kGcSeg0 + 0x1fcb;
static constexpr uint32_t kGcHqdQuantum    = kGcSeg0 + 0x1fb0;
static constexpr uint32_t kGcHqdIqTimer    = kGcSeg0 + 0x1fbf;
static constexpr uint32_t kGcMec1InstrPntr = kGcSeg0 + 0x0f48;
static constexpr uint32_t kGcMec2InstrPntr = kGcSeg0 + 0x0f49;
// The CP's instruction caches. On GFX10 a microengine does not run purely out of internal
// RAM: it fetches through an instruction cache backed by a GPU address held in these
// registers, which upstream's direct-load path programs alongside the microcode.
static constexpr uint32_t kGcCpcIcBaseLo   = kGcSeg1 + 0x584c;
static constexpr uint32_t kGcCpcIcBaseHi   = kGcSeg1 + 0x584d;
static constexpr uint32_t kGcCpcIcBaseCntl = kGcSeg1 + 0x584e;
static constexpr uint32_t kGcCpcIcOpCntl   = kGcSeg1 + 0x584f;
static constexpr uint32_t kGcPfpIcBaseLo   = kGcSeg1 + 0x5840;
static constexpr uint32_t kGcPfpIcBaseHi   = kGcSeg1 + 0x5841;
static constexpr uint32_t kGcMeIcBaseLo    = kGcSeg1 + 0x5844;
static constexpr uint32_t kGcMeIcBaseHi    = kGcSeg1 + 0x5845;
static constexpr uint32_t kGcPfpInstrPntr  = kGcSeg0 + 0x0f45;
static constexpr uint32_t kGcMeInstrPntr   = kGcSeg0 + 0x0f46;
// What is the command processor stalled ON. CP_STAT only says which blocks are busy;
// these say which back-pressure signal is holding them, per block.
static constexpr uint32_t kGcCpStalled1    = kGcSeg0 + 0x0f3d;
static constexpr uint32_t kGcCpStalled2    = kGcSeg0 + 0x0f3e;
static constexpr uint32_t kGcCpStalled3    = kGcSeg0 + 0x0f3c;
static constexpr uint32_t kGcCpBusyStat    = kGcSeg0 + 0x0f3f;
static constexpr uint32_t kGcCpcBusyStat   = kGcSeg0 + 0x0e25;
static constexpr uint32_t kGcCpcStalled1   = kGcSeg0 + 0x0e26;
static constexpr uint32_t kGcCpfBusyStat   = kGcSeg0 + 0x0e28;
static constexpr uint32_t kGcCpfStalled1   = kGcSeg0 + 0x0e29;
// The graphics ring, which CP_STAT says has PFP and ME permanently busy.
static constexpr uint32_t kGcRb0Base       = kGcSeg0 + 0x1de0;
static constexpr uint32_t kGcRb0BaseHi     = kGcSeg0 + 0x1e51;
static constexpr uint32_t kGcRb0Cntl       = kGcSeg0 + 0x1de1;
static constexpr uint32_t kGcRb0Rptr       = kGcSeg0 + 0x0f60;
static constexpr uint32_t kGcRb0Wptr       = kGcSeg0 + 0x1df4;
static constexpr uint32_t kGcRbVmid        = kGcSeg0 + 0x1df1;
static constexpr uint32_t kGcRbDbCtl       = kGcSeg0 + 0x1e8d;
static constexpr uint32_t kGcMqdBase       = kGcSeg0 + 0x1fa9;
static constexpr uint32_t kGcMqdBaseHi     = kGcSeg0 + 0x1faa;
static constexpr uint32_t kGcHqdPersist    = kGcSeg0 + 0x1fad;   // CP_HQD_PERSISTENT_STATE

// The two switches that decide whether a doorbell write ever reaches a MEC pipe:
// CP_PQ_STATUS.DOORBELL_ENABLE (bit 0) gates the whole aperture at the CP, and
// CP_PQ_WPTR_POLL_CNTL.EN picks the alternative -- polling each queue's write pointer
// out of memory. Upstream sets the first in gfx_v10_0_enable_doorbell_aperture; if
// Apple's Navi 2x path leaves it clear on this part, every doorbell is dropped and the
// symptom is exactly what we see: an active HQD whose MEC fetches nothing.
static constexpr uint32_t kGcCpPqStatus    = kGcSeg0 + 0x1e58;
static constexpr uint32_t kGcCpPqWptrPoll  = kGcSeg0 + 0x1e23;

// GFXHUB address translation. Apple programs its GMC through the MMHUB copies, which
// on this part read back unprogrammed, so these are the registers the graphics core
// actually walks. All BASE_IDX 0.
static constexpr uint32_t kGcVmSysApLow    = kGcSeg0 + 0x1701;
static constexpr uint32_t kGcVmSysApHigh   = kGcSeg0 + 0x1702;
static constexpr uint32_t kGcVmAgpBase     = kGcSeg0 + 0x1700;
static constexpr uint32_t kGcVmAgpBot      = kGcSeg0 + 0x16ff;
static constexpr uint32_t kGcVmAgpTop      = kGcSeg0 + 0x16fe;
static constexpr uint32_t kGcVmCtx0Cntl    = kGcSeg0 + 0x15fc;
static constexpr uint32_t kGcVmCtx0PtbLo   = kGcSeg0 + 0x1667;
static constexpr uint32_t kGcVmCtx0PtbHi   = kGcSeg0 + 0x1668;
static constexpr uint32_t kGcVmCtx0Start   = kGcSeg0 + 0x1687;
static constexpr uint32_t kGcVmCtx0End     = kGcSeg0 + 0x16a7;
static constexpr uint32_t kGcVmCtx1Cntl    = kGcSeg0 + 0x15fd;
static constexpr uint32_t kGcVmCtx1PtbLo   = kGcSeg0 + 0x1669;
// GFXHUB translation enables and the invalidation engine. If the L1 TLB or the L2 cache is
// not enabled, every CP memory access stalls with no fault raised anywhere -- which is what
// both rings and the 37 timed-out _vm_10_1_is_eng_ack waits look like.
static constexpr uint32_t kGcVmL1TlbCntl   = kGcSeg0 + 0x1703;
static constexpr uint32_t kGcVmL2Cntl      = kGcSeg0 + 0x15bc;
static constexpr uint32_t kGcVmL2Cntl2     = kGcSeg0 + 0x15bd;
static constexpr uint32_t kGcVmL2Cntl3     = kGcSeg0 + 0x15be;
static constexpr uint32_t kGcVmL2Status    = kGcSeg0 + 0x15bf;
static constexpr uint32_t kGcVmL2Cntl4     = kGcSeg0 + 0x15d4;
static constexpr uint32_t kGcVmL2Cntl5     = kGcSeg0 + 0x15dc;
static constexpr uint32_t kGcVmCtxDisable  = kGcSeg0 + 0x160c;
static constexpr uint32_t kGcVmInvEng0Req  = kGcSeg0 + 0x161f;
static constexpr uint32_t kGcVmInvEng0Ack  = kGcSeg0 + 0x1631;
static constexpr uint32_t kGcVmInvEng0Sem  = kGcSeg0 + 0x160d;

// Defined further down; they read the constants above.
static void dumpGfxState(const char *when);
static void dumpMecQueues(const char *when);
static void dumpCpUcode(const char *when);
// GRBM_GFX_CNTL selector for Apple's KIQ, established by the queue walk: it answers under
// pipe 1, MEID 2, queue 0 -- the walk's other seven hits are selector aliases of this same
// HQD, all reporting the identical MQD address.
static constexpr uint32_t kKiqSelector = 1u | (2u << 2);
static void dumpGfxHubVm(const char *when);
static void enableDoorbellMsg(uint64_t mqdAddr, uint64_t eopAddr);
static void relocateRingToVram();
static void startMecEngines();
static void programL2LikeUpstream();

static mach_vm_address_t orgPpPowerUp {};
static mach_vm_address_t fbBase {};
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
static void pspRingCtrl(void *psp, uint32_t cmd, const char *what) {
    auto wr = reinterpret_cast<void (*)(void *, uint32_t, uint32_t, uint32_t, uint32_t)>(
                  hwlibsBase + kOffPspRegWrite);
    auto rd = reinterpret_cast<uint32_t (*)(void *, uint32_t, uint32_t, uint32_t)>(
                  hwlibsBase + kOffPspRegRead);
    uint32_t before = rd(psp, kC2PMsg64, 0, kHwIpMp0);
    wr(psp, kC2PMsg64, 0, cmd, kHwIpMp0);
    uint32_t v = before;
    int ms = 0;
    for (; ms < 2000; ms++) {
        v = rd(psp, kC2PMsg64, 0, kHwIpMp0);
        if ((v & kMboxReadyMask) == kMboxReadyFlag &&
            ((v >> 16) & 0x7fff) == (cmd >> 16))
            break;
        IOSleep(1);
    }
    RLOG("X7: %s: 0x%08x -> 0x%08x after %dms%s", what, before, v, ms,
         (v & kMboxReadyMask) == kMboxReadyFlag ? " (ready)" : " (TIMEOUT)");
}

// Ask the PSP to MODE1-reset the GPU, so it re-autoloads the graphics firmware itself.
//
// This is the only remaining route to a command processor this guest can drive, and it is
// deliberately OFF unless the boot-arg rgpureset=1 is given -- kept separate from the rgpu
// mask because it is the one intervention here that can plausibly take the host down with
// it rather than merely failing.
//
// The reasoning: CP_CPC_IC_BASE, CP_HQD_EOP_BASE_ADDR, CP_PQ_WPTR_POLL_CNTL and
// CP_CPC_IC_OP_CNTL's PRIME_ICACHE bit are all locked for the life of this reset, while
// CP_MEC_CNTL and every GMC register are writable. That is the PSP holding the addresses the
// command processor fetches from. The instruction-cache base still points at the host
// driver's buffers, and even after moving the framebuffer aperture so that address lands on
// microcode this plugin wrote and verified by readback, the cache will not prime and the
// engines will not run. GFX_CMD_ID_AUTOLOAD_RLC -- the command that would hand the CP back
// -- answers TEE_ERROR_BUSY.
//
// A MODE1 reset makes the PSP re-run its own bootloader, which autoloads the GFX firmware
// and starts the microengines with addresses of its own choosing. amdgpu does exactly this
// on bare metal through the same mailbox, in psp_v13_0_mode1_reset: wait for the TOS-ready
// flag in C2PMSG_64, write GFX_CTRL_CMD_ID_MODE1_RST, sleep, then wait for bit 31 of
// C2PMSG_33. It needs no PCI re-enumeration, which is what makes it usable from a guest.
//
// The honest risk: this is an integrated GPU on the same die as the CPU, reached through
// vfio, and resetting the graphics block is not guaranteed to leave the host's fabric alone.
// Recovery if it goes wrong is a host reboot. Hence the separate opt-in.
static bool pspResetRequested = false;
static bool pspResetDone = false;
static constexpr uint32_t kModeReset1 = 0x00070000;   // GFX_CTRL_CMD_ID_MODE1_RST
static constexpr uint32_t kC2PMsg33   = 0x61;         // MP0_SMN_C2PMSG_33

static void pspMode1Reset(void *psp) {
    if (!pspResetRequested || pspResetDone || hwlibsBase == 0 || psp == nullptr) return;
    pspResetDone = true;
    auto wr = reinterpret_cast<void (*)(void *, uint32_t, uint32_t, uint32_t, uint32_t)>(
                  hwlibsBase + kOffPspRegWrite);
    auto rd = reinterpret_cast<uint32_t (*)(void *, uint32_t, uint32_t, uint32_t)>(
                  hwlibsBase + kOffPspRegRead);
    uint32_t before = rd(psp, kC2PMsg64, 0, kHwIpMp0);
    RLOG("XQ: MODE1 reset requested; C2PMSG_64=%#x", before);
    wr(psp, kC2PMsg64, 0, kModeReset1, kHwIpMp0);
    IOSleep(500);
    int ms = 0;
    uint32_t v = 0;
    for (; ms < 5000; ms++) {
        v = rd(psp, kC2PMsg33, 0, kHwIpMp0);
        if ((v & 0x80000000u) != 0) break;
        IOSleep(1);
    }
    RLOG("XQ: MODE1 reset: C2PMSG_33=%#x after %dms%s; C2PMSG_64 now %#x", v, ms,
         (v & 0x80000000u) ? " (complete)" : " (TIMEOUT)", rd(psp, kC2PMsg64, 0, kHwIpMp0));
}

static uint32_t wrapPspRingCreate(void *psp, uint32_t ringType) {
    pspMode1Reset(psp);
    if ((mask & X7) != 0 && ringType == 2 && hwlibsBase != 0 && psp != nullptr) {
        // Destroy UNCONDITIONALLY. A clean mailbox does not mean there is no ring: after a
        // boot that got as far as ENABLE_INT, C2PMSG_64 reads 0x80050000 -- status 0, so
        // it passes every "ready" test -- while the GPCOM ring from that boot is still
        // very much alive, and INIT_GPCOM_RING then fails because it already exists.
        // Gating the destroy on the status being non-zero is exactly the mistake that
        // made this look fixed when it was not. Upstream's psp_v11_0_ring_create calls
        // psp_v11_0_ring_stop unconditionally for the same reason.
        //
        // DESTROY_RINGS first, because there are TWO rings and DESTROY_GPCOM_RING clears
        // only one of them. The very first boot to complete TTL::initialize() created a
        // UM/RBI ring as well (psp_hdcp_initialize, during initialize_bgd_security) and
        // left it behind; the next boot then died at "psp_ring_create: UM ring creation
        // failed" -- the same failure as the GPCOM one, one ring type over, and it looked
        // for a while like a regression from the framebuffer-aperture fix. The KM ring is
        // created first, so clearing both here is enough for the UM create that follows.
        pspRingCtrl(psp, kDestroyRings, "destroy all rings");
        pspRingCtrl(psp, kDestroyGpcomRing, "destroy GPCOM ring");
    } else if ((mask & X7) != 0 && psp != nullptr) {
        RLOG("X7: psp_ring_create(type=%u) -- not the KM ring, leaving it alone", ringType);
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
// Is the BIF doorbell aperture ever enabled?
//
// The doorbell store lands in a real BAR2 mapping -- QEMU reports the guest's BAR2 as
// 2 MB at 0xf0000000, AMDHardware::mapDoorbellMemory maps it via config offset 0x18, and
// writing index 0 by hand from this plugin changes nothing. That leaves the NBIO gate:
// a doorbell write only reaches the command processor if BIF_DOORBELL_APER_EN is set.
// CP_PQ_STATUS.DOORBELL_ENABLE, which reads 1, is only the CP's half of it.
//
// HWLibs has the code: _bif_doorbell_aperture_control dispatches on its argument's first
// word and, for 0, calls [ctx+0x378] with 1 -- the per-generation enable. For this
// generation that is _bif6_2_enable_doorbell_aperture, which is
//
//     reg = 0xc0 + [ctx+0x3c]          RCC_DEV0_EPF0_RCC_DOORBELL_APER_EN
//     val = (bcs_read_mmr(dev, reg, 0x42) & ~1) | enable
//
// i.e. bit 0 of one register, addressed through a base the bif context carries at +0x3c
// rather than through gc_reg_offset. Log every call, from all three generations, with the
// register it computed -- if none of them fires, nothing has enabled the aperture and the
// MEC is never being told anything.
static uint32_t wrapBifDbAperCtl(void *ctx, uint32_t *arg) {
    auto r = FunctionCast(wrapBifDbAperCtl, orgBifDbAperCtl)(ctx, arg);
    static unsigned n = 0;
    if (n < 8) { n++;
        RLOG("XK: bif_doorbell_aperture_control(op=%u) -> %u", arg ? *arg : 0xffffffff, r);
    }
    return r;
}
static uint32_t wrapBifEnableDb(void *ctx, uint32_t enable, const char *which,
                                mach_vm_address_t org) {
    uint32_t base = 0;
    void *dev = nullptr;
    if (ctx != nullptr) {
        base = *reinterpret_cast<uint32_t *>(reinterpret_cast<uint8_t *>(ctx) + 0x3c);
        dev  = *reinterpret_cast<void **>(ctx);
    }
    auto r = reinterpret_cast<uint32_t (*)(void *, uint32_t)>(org)(ctx, enable);
    // Read the register back through the same accessor the function itself uses, so the
    // answer does not depend on guessing how this client's indices map onto BAR5.
    uint32_t val = 0xdeadbeef;
    if (dev != nullptr && hwlibsBase != 0) {
        auto rd = reinterpret_cast<uint32_t (*)(void *, uint32_t, uint32_t)>(
                      hwlibsBase + kOffBcsReadMmr);
        val = rd(dev, base + 0xc0, 0x42);
    }
    RLOG("XK: %s(enable=%u) -> %u  reg=%#x (base %#x + 0xc0) reads %#x, "
         "BIF_DOORBELL_APER_EN=%u", which, enable, r, base + 0xc0, base, val, val & 1);
    return r;
}
static uint32_t wrapBif62EnableDb(void *ctx, uint32_t e) {
    return wrapBifEnableDb(ctx, e, "bif6_2_enable_doorbell_aperture", orgBif62EnableDb);
}
static uint32_t wrapBif61EnableDb(void *ctx, uint32_t e) {
    return wrapBifEnableDb(ctx, e, "bif6_1_enable_doorbell_aperture", orgBif61EnableDb);
}
static uint32_t wrapBif50EnableDb(void *ctx, uint32_t e) {
    return wrapBifEnableDb(ctx, e, "bif50_enable_doorbell_aperture", orgBif50EnableDb);
}
static uint32_t wrapNbio72EnableDb(void *ctx, uint32_t e) {
    return wrapBifEnableDb(ctx, e, "nbio7_2_enable_doorbell_aperture", orgNbio72EnableDb);
}
static uint32_t wrapNbio23EnableDb(void *ctx, uint32_t e) {
    return wrapBifEnableDb(ctx, e, "nbio2_3_enable_doorbell_aperture", orgNbio23EnableDb);
}

// The SDMA half of the same gate. With GC HW_INIT through, hw_init fails one client
// later at SDMA, on a predicate that is one register read:
//
//     6028c: mov esi, 0x4e8d ; mov edx, 1 ; mov ecx, 0xb ; call sdma_cgs_read_register_ext2
//     602aa: shr eax, 0x1f
//
// i.e. bit 31 of RLC_RLCS_BOOTLOAD_STATUS -- the same latch the GC gate wanted, read
// through the SDMA client instead. Upstream's sdma_v5_2_start has no such wait at all:
// on the PSP load path it goes straight to sdma_v5_2_enable. Answer it the same way the
// GC gate is answered, from the same evidence: a live RLC.
static uint8_t wrapSdmaAutoloadDone(void *ctx) {
    auto r = FunctionCast(wrapSdmaAutoloadDone, orgSdmaAutoloadDone)(ctx);
    if ((mask & XL) == 0 || r != 0) return r;
    if (asicInfo == nullptr || fbRead(asicInfo, kGcRlcStat) != 0x25) return r;
    static bool told = false;
    if (!told) { told = true;
        RLOG("XL: SDMA autoload gate reads the same BOOTLOAD_STATUS latch (still %#x); "
             "RLC_STAT=0x25, so reporting complete as upstream's sdma_v5_2_start assumes",
             fbRead(asicInfo, kGcRlcBootStat));
    }
    return 1;
}

// The same halt filter on the other two GC write helpers.
//
// _gc_halt_micro_engines_10_3 goes through _gc_cgs_write_register_ext2, and dropping the
// halt bits there caught exactly one write -- 0x10000000, MEC_ME2_HALT alone -- while
// CP_MEC_CNTL had already been seen at 0x50000000, both halts. So the other bit arrives
// through a different helper: HWLibs has three, _gc_cgs_write_register,
// _gc_cgs_write_register_ext and _gc_cgs_write_register_ext2, all taking (ctx, reg, val,
// ...) and differing only in which function pointer they forward to. Filter all three.
static uint32_t wrapGcCgsWrite(void *ctx, uint32_t reg, uint32_t val) {
    if ((mask & XL) != 0 && reg == kGcCpMecCntl && (val & ((1u << 28) | (1u << 30))) != 0) {
        static unsigned n = 0;
        if (n < 4) { n++; RLOG("XK: dropped MEC halt via write_register: %#x", val); }
        val &= ~((1u << 28) | (1u << 30));
    }
    return FunctionCast(wrapGcCgsWrite, orgGcCgsWrite)(ctx, reg, val);
}
static uint32_t wrapGcCgsWriteExt(void *ctx, uint32_t reg, uint32_t val, uint32_t client) {
    if ((mask & XL) != 0 && reg == kGcCpMecCntl && (val & ((1u << 28) | (1u << 30))) != 0) {
        static unsigned n = 0;
        if (n < 4) { n++; RLOG("XK: dropped MEC halt via write_register_ext: %#x", val); }
        val &= ~((1u << 28) | (1u << 30));
    }
    return FunctionCast(wrapGcCgsWriteExt, orgGcCgsWriteExt)(ctx, reg, val, client);
}

// Never let the first HQD dequeue be requested.
//
// The decisive measurement: CP_CPC_STALLED_STAT1 already reads 0x210000 --
// MEC2_DECODING_PACKET | MEC2_WAIT_ON_ROQ_DATA -- *before* Apple submits its first KIQ
// frame. Sampled from inside submitKIQFrame ahead of the original call, with a ring in VRAM
// holding a correct PACKET3_SET_RESOURCES and the doorbell rung with the right dword count,
// the engine is already wedged. So none of it is about Apple's packet, its write pointer's
// unit, or where the ring lives.
//
// What wedges it is the dequeue in _gc_create_kiq_queue_10_3. That function finds a live
// HQD, writes CP_HQD_DEQUEUE_REQUEST = 1, and waits 500 ms for CP_HQD_ACTIVE to fall. It
// never falls, and milestone xl then does what upstream does on that timeout -- clear
// CP_HQD_ACTIVE by hand and carry on. Upstream gets away with it because on real silicon
// the dequeue retires; here the request is left outstanding, and CP_CPF_BUSY_STAT's
// HQD_EOP_FETCHER_BUSY and HQD_ROQ_EOP_BUSY are exactly what an unfinished dequeue draining
// to the end-of-pipe queue looks like. Forcing ACTIVE to 0 underneath a dequeue in flight
// leaves MEC2 in it forever, and every queue programmed afterwards -- Apple's KIQ included
// -- waits behind an engine that will never come back.
//
// So do not paper over the dequeue: prevent it. Drop the one write that starts it. The wait
// afterwards still fails, xl still clears CP_HQD_ACTIVE, the queue is still torn down -- but
// the microengine is never asked to do the thing it cannot finish.
static uint32_t wrapGcCgsWrite2(void *ctx, uint32_t reg, uint32_t val, uint32_t client,
                                uint32_t flag) {
    if (gcCtx == nullptr) gcCtx = ctx;
    // Never let the compute microengines be halted.
    //
    // This is the finding the whole KIQ investigation was circling. The wedge detector
    // caught CP_CPC_STALLED_STAT1 going 0 -> 0x210000 on a routine GRBM_GFX_INDEX = 0
    // broadcast write -- but with CP_MEC_CNTL reading 0x50000000 at that instant, i.e. TTL
    // had just set MEC_ME1_HALT | MEC_ME2_HALT. Sampling the register across a deliberate
    // halt and unhalt afterwards shows 0x210000 in all three states: it does not track the
    // halt bits, it was latched by the first one. On this part halting the MECs is not
    // reversible -- MEC2 reports MEC2_DECODING_PACKET | MEC2_WAIT_ON_ROQ_DATA from then on,
    // CP_MEC1_INSTR_PNTR sits at the same 0x10000 the halted PFP and ME report, and every
    // queue programmed afterwards waits behind an engine that never comes back.
    //
    // Upstream only calls gfx_v10_0_cp_compute_enable(false) on the way down, or before a
    // direct microcode load. Neither applies here: the microcode is already in the engines,
    // placed by the PSP's cold-boot autoload, and read back through
    // CP_MEC_ME{1,2}_UCODE_ADDR/DATA as real instruction words. So drop the halt and keep
    // the rest of the register -- pipe resets and MEC_INVALIDATE_ICACHE still get through.
    if ((mask & XL) != 0 && reg == kGcCpMecCntl &&
        (val & ((1u << 28) | (1u << 30))) != 0) {
        static unsigned nh = 0;
        if (nh < 6) { nh++;
            RLOG("XK: dropped CP_MEC_CNTL halt bits: %#x -> %#x (halting the MECs on this "
                 "part is one-way)", val, val & ~((1u << 28) | (1u << 30)));
        }
        val &= ~((1u << 28) | (1u << 30));
        return FunctionCast(wrapGcCgsWrite2, orgGcCgsWrite2)(ctx, reg, val, client, flag);
    }
    if ((mask & XL) != 0 && reg == kGcHqdDequeue && val != 0) {
        static unsigned n = 0;
        if (n < 4) { n++;
            RLOG("XK: dropped CP_HQD_DEQUEUE_REQUEST=%#x (client %#x) -- an outstanding "
                 "dequeue is what leaves MEC2 in WAIT_ON_ROQ_DATA for the rest of the boot",
                 val, client);
        }
        return 0;
    }
    auto r = FunctionCast(wrapGcCgsWrite2, orgGcCgsWrite2)(ctx, reg, val, client, flag);
    // Catch the write that wedges the microengine.
    //
    // CP_CPC_STALLED_STAT1 is already 0x210000 before Apple submits anything, and dropping
    // the dequeue request did not prevent it, so the wedge happens somewhere inside TTL's
    // own GC HW_INIT. Every GC register write in this stack goes through this function, so
    // sample the stall bit after each one until it first goes non-zero and name the write
    // that did it. One extra MMIO read per GC write, and only until it trips.
    if ((mask & XL) != 0 && !cpcWedged && asicInfo != nullptr) {
        // Keep the last few writes so the transition can be attributed to a sequence
        // rather than to whichever write happened to be in flight when the bit flipped.
        static uint32_t histReg[6] {}, histVal[6] {};
        static unsigned histAt = 0;
        histReg[histAt % 6] = reg; histVal[histAt % 6] = val; histAt++;
        uint32_t st = fbRead(asicInfo, kGcCpcStalled1);
        if (st != 0) {
            cpcWedged = true;
            char h[160]; size_t hn = 0;
            for (unsigned i = histAt >= 6 ? histAt - 6 : 0; i < histAt && hn + 24 < sizeof(h); i++)
                hn += snprintf(h + hn, sizeof(h) - hn, "%#x=%#x ", histReg[i % 6], histVal[i % 6]);
            RLOG("XK: last writes before the wedge: %s", h);
            RLOG("XK: CP_CPC_STALLED_STAT1 went 0 -> %#x on write reg=%#x val=%#x "
                 "client=%#x flag=%#x", st, reg, val, client, flag);
            RLOG("XK: at wedge: CPC_BUSY=%#x CPF_BUSY=%#x CP_STAT=%#x MEC_CNTL=%#x "
                 "HQD_ACTIVE=%#x EOP=%#x_%08x eop_ctl=%#x",
                 fbRead(asicInfo, kGcCpcBusyStat), fbRead(asicInfo, kGcCpfBusyStat),
                 fbRead(asicInfo, kGcCpStat), fbRead(asicInfo, kGcCpMecCntl),
                 fbRead(asicInfo, kGcHqdActive), fbRead(asicInfo, kGcHqdEopBaseHi),
                 fbRead(asicInfo, kGcHqdEopBase), fbRead(asicInfo, kGcHqdEopControl));
        }
    }
    return r;
}

// Give up on a compute queue whose dequeue request never retires, the way upstream does.
//
// With the autoload gate satisfied, GC HW_INIT gets one block further and dies in
// _gc_create_kiq_queue_10_3. That function is a faithful copy of upstream's
// gfx_v10_0_kiq_init_register: clear CP_PQ_WPTR_POLL_CNTL, clear DOORBELL_EN in
// CP_HQD_PQ_DOORBELL_CONTROL, and if CP_HQD_ACTIVE says the selected queue is live,
// write CP_HQD_DEQUEUE_REQUEST = 1 and wait for CP_HQD_ACTIVE bit 0 to fall --
//
//     15454: mov qword [pred + 0xc], 0x1     mask 1, shift 0
//     1545d: mov dword [pred + 0x14], 0x0    expected 0
//     15473: mov ecx, 0x1f4                  500 ms
//
// -- and here it never falls. Measured by hand earlier through this plugin's own
// accessor: every active HQD reports "active=1 after 2000us". CP_HQD_DEQUEUE_REQUEST is
// serviced by MEC firmware, which has to write the queue's MQD back before it can
// retire, so a queue whose MQD or ring lies at an address the GPU cannot translate can
// never finish dequeuing. Every one of these HQDs points at a ring at 0xFFBFEA0000 --
// outside this part's 0xf400000000-0xf41fffffff carveout, and exactly the address in the
// latched GCVM fault -- so that is the shape of it.
//
// Upstream anticipates this and does not treat it as fatal:
//
//     if (j == adev->usec_timeout) {
//             DRM_DEBUG("KIQ dequeue request failed.\n");
//             /* Manual disable if dequeue request times out */
//             WREG32_SOC15(GC, 0, mmCP_HQD_ACTIVE, 0);
//     }
//
// It then writes the whole HQD register set anyway, which overwrites the dead queue.
// Apple keeps the wait and drops the fallback, so a stuck HQD fails hw_init instead.
// Restore the fallback: after enough polls to be sure the queue really is wedged, clear
// CP_HQD_ACTIVE through TTL's own register path -- _gc_cgs_write_register_ext2 with the
// GC client id and the selector TTL has already programmed -- and answer yes.
//
// Deliberately narrow: only the (CP_HQD_ACTIVE, mask 1, shift 0, expect 0) predicate is
// touched, so the same helper's other callers -- RLC safe mode and RLC logging setup --
// keep timing out honestly.
static uint8_t wrapGcCheckRegEq(void *arg) {
    auto r = FunctionCast(wrapGcCheckRegEq, orgGcCheckRegEq)(arg);
    if ((mask & XL) == 0 || r != 0 || arg == nullptr) return r;
    auto a = reinterpret_cast<uint8_t *>(arg);
    void *ctx      = *reinterpret_cast<void **>(a);
    uint32_t reg   = *reinterpret_cast<uint32_t *>(a + 0x08);
    uint32_t msk   = *reinterpret_cast<uint32_t *>(a + 0x0c);
    uint8_t  shift = *(a + 0x10);
    uint32_t want  = *reinterpret_cast<uint32_t *>(a + 0x14);
    if (msk != 1 || shift != 0 || want != 0) return r;

    // reg is already an absolute SOC15 index (gc_reg_offset has been applied), so it can
    // be compared against this file's constants directly.
    //   RLC_SAFE_MODE  -- the RLC has not acknowledged the safe-mode request. Upstream
    //                     proceeds anyway; there is nothing to clear by hand, the whole
    //                     handshake is advisory.
    //   CP_HQD_ACTIVE  -- the dequeue never retired. Upstream clears CP_HQD_ACTIVE itself
    //                     and carries on to write the rest of the HQD, which replaces the
    //                     dead queue outright.
    bool isSafeMode = reg == kGcRlcSafeMode;
    bool isHqd      = reg == kGcHqdActive;
    if (!isSafeMode && !isHqd) return r;

    // Poll for a while first: both predicates are the normal success path for hardware
    // that does answer, and conceding early would cut short a wait about to succeed.
    static uint32_t lastReg = 0;
    static unsigned polls = 0;
    if (reg != lastReg) { lastReg = reg; polls = 0; }
    if (++polls < 64) return r;
    polls = 0;

    if (isHqd && hwlibsBase != 0 && ctx != nullptr) {
        auto wr = reinterpret_cast<uint32_t (*)(void *, uint32_t, uint32_t, uint32_t, uint32_t)>(
                      hwlibsBase + kOffGcCgsWrite2);
        wr(ctx, reg, 0, 0xb, 1);
    }
    static uint32_t told = 0;
    if ((told & reg) != reg) {
        told |= reg;
        if (isHqd)
            RLOG("XL: CP_HQD_DEQUEUE_REQUEST never retired; wrote CP_HQD_ACTIVE=0 "
                 "(upstream's manual disable). ring=%#x_%08x doorbell_ctl=%#x",
                 fbRead(asicInfo, kGcHqdPqBaseHi), fbRead(asicInfo, kGcHqdPqBase),
                 fbRead(asicInfo, kGcHqdPqDbCtl));
        else
            RLOG("XL: RLC never acknowledged safe mode (RLC_SAFE_MODE=%#x, RLC_CNTL=%#x, "
                 "RLC_STAT=%#x); proceeding as upstream does",
                 fbRead(asicInfo, kGcRlcSafeMode), fbRead(asicInfo, kGcRlcCntl),
                 fbRead(asicInfo, kGcRlcStat));
    }
    return 1;
}

// Accept the RLC firmware autoload as complete on BOOTLOAD_COMPLETE alone.
//
// GC HW_INIT dies here. _gc_check_ucode_loaded_10_1 spins on this predicate for 50 ms
// and, when it never becomes true, asserts (GC event 0xc0100206) -- after which
// _gc_check_register_equal_ext times out too and ttl_hw_init fails with
// "GC init/power-up failed". The predicate reads two registers, both cached as
// gc_reg_offset() results at ttl+0xb38 and +0xb3c by the GC context builder:
//
//     [ctx+0xb38] = gc_reg_offset(0x4c04, base_idx 1) = RLC_STAT
//     [ctx+0xb3c] = gc_reg_offset(0x4e8d, base_idx 1) = RLC_RLCS_BOOTLOAD_STATUS
//
// and requires BOOTLOAD_STATUS to have BOOTLOAD_COMPLETE (bit 31) -- plus bit 0 unless
// [ctx+0x326] -- AND RLC_STAT to equal exactly 0x25 on Navi 2x ([ctx+0x329] set):
// RLC_BUSY | RLC_GPM_BUSY | RLC_THREAD_0_BUSY. Upstream's
// gfx_v10_0_wait_for_rlc_autoload_complete asks for BOOTLOAD_COMPLETE and CP_STAT == 0
// and nothing else; the RLC_STAT clause is Apple's own addition, and it is a liveness
// sample rather than a completion latch. On this part BOOTLOAD_STATUS reads 0xc0000001
// -- complete -- while RLC_STAT reads 0, so the exact-match clause is what fails, and
// whether it ever happens to read 0x25 during the 50 ms window is a race: the same
// binary reached the accelerator on an earlier host boot and fails here on a fresh one.
//
// So: run Apple's predicate, and if it says no, fall back to upstream's condition. Log
// both registers either way, because if the RLC threads really are idle then the CP has
// no microcode and the KIQ timeout downstream is the same root cause one block later.
static uint8_t wrapGcAutoloadDone(void *ctx) {
    auto r = FunctionCast(wrapGcAutoloadDone, orgGcAutoloadDone)(ctx);
    if ((mask & XL) == 0 || r != 0 || ctx == nullptr) return r;
    static unsigned logged = 0;
    uint32_t rlcStat = 0xdeadbeef, bootStat = 0xdeadbeef, bootStatSc = 0xdeadbeef;
    uint32_t cpStat = 0xdeadbeef;
    if (asicInfo != nullptr) {
        rlcStat    = fbRead(asicInfo, kGcRlcStat);
        bootStat   = fbRead(asicInfo, kGcRlcBootStat);
        bootStatSc = fbRead(asicInfo, kGcRlcBootStatSc);
        cpStat     = fbRead(asicInfo, kGcCpStat);
    }
    // Measured, not assumed. At this point in GC HW_INIT:
    //
    //     RLC_STAT                  = 0x25   RLC_BUSY | RLC_GPM_BUSY | RLC_THREAD_0_BUSY
    //     RLC_RLCS_BOOTLOAD_STATUS  = 0      at 0x4e8d (Apple's offset)
    //                               = 0      at 0x4e7e (the Sienna Cichlid offset upstream
    //                                        uses for every GC 10.3.x, this chip included)
    //     CP_STAT                   = 0x84028000
    //     PFP/ME/CE/MEC1/MEC2 instruction RAM: real instruction words, not zeroes
    //
    // So the RLC's threads are running and the command processor's microcode is in place --
    // this PSP loads it whether or not GFX_CMD_ID_AUTOLOAD_RLC is accepted, and here it is
    // refused with 0xffff000d, TEE_ERROR_BUSY. BOOTLOAD_COMPLETE is a latch the RLC's own
    // backdoor-autoload bootloader sets; when the PSP places the firmware itself, nothing
    // sets it, and neither offset ever reads back complete. Apple's gate is therefore
    // unsatisfiable on this part, and waiting longer would not help.
    //
    // Treat a live RLC as the completion signal, which is what the register is standing in
    // for. Deliberately not unconditional: if RLC_STAT ever stops reading 0x25 the answer
    // goes back to Apple's, so a genuinely dead RLC still fails here rather than one block
    // later with no explanation.
    bool complete = ((bootStat | bootStatSc) & 0x80000000u) != 0 || rlcStat == 0x25;
    if (logged < 3) {
        logged++;
        RLOG("XL: autoload check: RLC_STAT=%#x (Apple wants 0x25) BOOTLOAD_STATUS "
             "0x4e8d=%#x 0x4e7e=%#x CP_STAT=%#x -> %s", rlcStat, bootStat, bootStatSc,
             cpStat, complete ? "complete (RLC threads live)" : "not complete");
        dumpCpUcode("gc hw_init");
    }
    return complete ? 1 : r;
}

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
    orgGcAutoloadDone = patcher.routeFunction(base + kOffGcAutoloadDone,
                      reinterpret_cast<mach_vm_address_t>(wrapGcAutoloadDone), true);
    RLOG("route gc_fw_autoload_is_completed -> %s (org=0x%llx)",
         orgGcAutoloadDone ? "ok" : "FAILED", orgGcAutoloadDone);
    patcher.clearError();
    orgGcCheckRegEq = patcher.routeFunction(base + kOffGcCheckRegEq,
                      reinterpret_cast<mach_vm_address_t>(wrapGcCheckRegEq), true);
    RLOG("route gc_check_register_equal_ext -> %s (org=0x%llx)",
         orgGcCheckRegEq ? "ok" : "FAILED", orgGcCheckRegEq);
    patcher.clearError();
    orgSdmaAutoloadDone = patcher.routeFunction(base + kOffSdmaAutoloadDone,
                      reinterpret_cast<mach_vm_address_t>(wrapSdmaAutoloadDone), true);
    RLOG("route sdma_5_2_fw_autoload_is_completed -> %s (org=0x%llx)",
         orgSdmaAutoloadDone ? "ok" : "FAILED", orgSdmaAutoloadDone);
    patcher.clearError();
    struct { size_t off; mach_vm_address_t *org; void *fn; const char *name; } dbRoutes[] {
        {kOffBifDbAperCtl,  &orgBifDbAperCtl,  reinterpret_cast<void *>(wrapBifDbAperCtl),
         "bif_doorbell_aperture_control"},
        {kOffBif62EnableDb, &orgBif62EnableDb, reinterpret_cast<void *>(wrapBif62EnableDb),
         "bif6_2_enable_doorbell_aperture"},
        {kOffBif61EnableDb, &orgBif61EnableDb, reinterpret_cast<void *>(wrapBif61EnableDb),
         "bif6_1_enable_doorbell_aperture"},
        {kOffBif50EnableDb, &orgBif50EnableDb, reinterpret_cast<void *>(wrapBif50EnableDb),
         "bif50_enable_doorbell_aperture"},
        {kOffNbio72EnableDb, &orgNbio72EnableDb, reinterpret_cast<void *>(wrapNbio72EnableDb),
         "nbio7_2_enable_doorbell_aperture"},
        {kOffNbio23EnableDb, &orgNbio23EnableDb, reinterpret_cast<void *>(wrapNbio23EnableDb),
         "nbio2_3_enable_doorbell_aperture"},
        {kOffGcCgsWrite2, &orgGcCgsWrite2, reinterpret_cast<void *>(wrapGcCgsWrite2),
         "gc_cgs_write_register_ext2"},
        {kOffGcCgsWrite, &orgGcCgsWrite, reinterpret_cast<void *>(wrapGcCgsWrite),
         "gc_cgs_write_register"},
        {kOffGcCgsWriteExt, &orgGcCgsWriteExt, reinterpret_cast<void *>(wrapGcCgsWriteExt),
         "gc_cgs_write_register_ext"},
    };
    for (auto &e : dbRoutes) {
        *e.org = patcher.routeFunction(base + e.off,
                     reinterpret_cast<mach_vm_address_t>(e.fn), true);
        RLOG("route %s -> %s (org=0x%llx)", e.name, *e.org ? "ok" : "FAILED", *e.org);
        patcher.clearError();
    }
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

// Find the framebuffer aperture.
//
// With TTL up, the accelerator attaches and then dies on the first command buffer:
//     AMD ERROR! Failed to allocate size:65536. There is 0 free memory remaining
//     panic: page fault CR2=0 in AMDAccelResource::BatchPrepareMappings
// because GPUCAP reports "FB Base: 0x100000000, Top: 0x100000000" -- a zero-wide
// range. The host kernel says where this iGPU's carveout really is:
//     amdgpu 0000:7b:00.0: VRAM: 512M 0x000000F400000000 - 0x000000F41FFFFFFF
// so the base should read 0xf400, not 0x100, and the top 0xf41f.
//
// It is NOT the MMHUB version remap: this read never goes through TTL's IP dispatch.
// AmdAsicInfoNavi2::populateXGmiConfig reads five raw MMIO dword indices --
//     0x1a867 xgmi cntl   -> node count (low nibble), mode (bits 4-7, +1)
//     0x1a868 xgmi size
//     0x1a86c FB_LOCATION_BASE >> 24     (masked to 24 bits, then << 24)
//     0x1a86d FB_LOCATION_TOP  >> 24
//     0x1a857 FB_OFFSET       >> 24
// -- i.e. MMHUB at Apple's base 0x1a800 with the MMHUB 2.0 register offsets
// 0x6c/0x6d/0x57/0x67/0x68. MMHUB 2.4 on this silicon may well put them elsewhere.
// (Navi1's AmdAsicInfoNavi::populateFbLocation uses 0x2980/0x2981/0x296b instead,
// which is GC base 0x1260 plus the gc_10_1_0 offsets 0x1720/0x1721/0x170b -- the
// GFXHUB copy. Worth scanning too, since gc_10_3 moved those to 0x16fc/0x16fd/0x16e7.)
//
// Scanning both windows answered it in one boot:
//     0x1a86c=0x100  0x1a86d=0  0x1a857=0        <- what Apple reads: wrong
//     0x295c=0xf400  0x295d=0xf41f  0x2947=0x840 <- GC base 0x1260 + gc_10_3 0x16fc/
//                                                   0x16fd/0x16e7
// 0xf400 << 24 = 0xF400000000 and (0xf41f << 24) | 0xffffff = 0xF41FFFFFFF -- exactly
// the host kernel's "VRAM: 512M 0x000000F400000000 - 0x000000F41FFFFFFF". Two
// independent matches pin the GC base at 0x1260, so 0x2947 is FB_OFFSET (0x840, and
// 0x2951/0x2952 = 0x840/0x85f, the system aperture, agree).
//
// So Apple is not reading the wrong offsets for MMHUB -- it is reading MMHUB at all.
// The MMHUB copy of the FB location is simply not programmed on this part; the GFXHUB
// copy is. Take the GFXHUB one.
static constexpr uint32_t kGcFbBase   = 0x295c;   // GC 0x1260 + gc_10_3 0x16fc
static constexpr uint32_t kGcFbTop    = 0x295d;   // GC 0x1260 + gc_10_3 0x16fd
static constexpr uint32_t kGcFbOffset = 0x2947;   // GC 0x1260 + gc_10_3 0x16e7

// Give the accelerator's two memory pools a range that is not inverted.
//
// With TTL up and the aperture corrected, the first command buffer still dies on
//     AMD ERROR! Failed to allocate size:65536. There is 0 free memory remaining
// AMDHWMemory::initVRAMInfo asks [this+0x10]->vtable[0x2c0]() for a provider and calls
// its vtable[0x18] with a 0x48-byte out struct, keeping
//     [this+0x50] = s[0x00]   base        measured 0xf400000000
//     [this+0x58] = s[0x18]   reserved    measured 0
//     [this+0x40] = s[0x08]   pool 0 size measured 0x20000000  (512 MB, the whole FB)
//     [this+0x48] = s[0x10]   pool 1 size measured 0x10000000  (256 MB, the PCI aperture)
// Those two are per-pool: canAllocate indexes them as [this + 8*pool + 0x40].
//
// enableAllocations then branches on whether they are equal:
//     equal   -> IOAccelMemoryAllocator::init_pool(base, size)          for both pools
//     unequal -> IOAccelMemoryAllocator::init_pool(base + [0x40],
//                                                  base + [0x48], 0)    for both pools
// (names recovered from the external relocations at 0x52a58/0x52a6b/0x52a7e/0x52a9a).
// The unequal form wants [0x40] <= [0x48]; here it is 512 MB vs 256 MB, so the pool is
// handed 0xf420000000..0xf410000000 -- backwards, hence a pool with nothing in it.
//
// Every Navi 2x Mac has a resizable BAR as large as its VRAM, so on Apple hardware
// these are always equal and the two-argument path is the one that ships. This iGPU's
// BAR0 is 256 MB against a 512 MB carveout ("Memory at fc20000000 [size=256M]", no
// rebar capability), which is why the rarely-taken branch is reached at all.
//
// So equalise on the SMALLER of the two. That is the aperture, so every byte the pool
// hands out is inside the BAR the CPU can actually reach; the cost is half the
// carveout. Raising it to the full 512 MB is a separate experiment.
static uint32_t wrapHwMemVram(void *self) {
    auto r = FunctionCast(wrapHwMemVram, orgHwMemVram)(self);
    if (self == nullptr) return r;
    auto f = reinterpret_cast<uint8_t *>(self);
    auto q = [f](size_t o) -> uint64_t & { return *reinterpret_cast<uint64_t *>(f + o); };
    RLOG("XH: initVRAMInfo -> %u  base=%#llx reserved=%#llx base-reserved=%#llx "
         "pool0=%#llx pool1=%#llx",
         r, q(0x50), q(0x58), q(0x60), q(0x40), q(0x48));
    if ((mask & XH) != 0 && q(0x40) != q(0x48) && q(0x40) != 0 && q(0x48) != 0) {
        uint64_t use = q(0x40) < q(0x48) ? q(0x40) : q(0x48);
        RLOG("XH: pool sizes differ (%#llx vs %#llx) -- enableAllocations would build an "
             "inverted range; using %#llx (%llu MB) for both",
             q(0x40), q(0x48), use, use >> 20);
        q(0x40) = use;
        q(0x48) = use;
    }
    return r;
}

// Stop PowerPlay from powering the GPU back down.
//
// The pools are still empty with the sizes equalised, and the log order says why:
//     [PPLIB] handleCriticalError() !!! Failed Power Play Initialization.
//     [PPLIB] handleCriticalError() !!! PowerUp Failed. Shut back down.
//     AmdRadeonControllerNavi23::powerUp() ??? Power Play Initialization Failed
//                                              (Safe-Mode?). err:general error.
//     ... 100 lines later ...
//     AMD ERROR! Failed to allocate size:65536. There is 0 free memory remaining
// "Shut back down" is literal. AmdPowerPlayHelper::powerUp (0x101a0) reads
//     101c0: call [vtable+0x118]        ; isSupported()
//     10240: cmp  byte [this+0x28f8], 1 ; NOT isSupported() -- the raw flag
//     1025e: call handleCriticalError("PowerUp Failed. Shut back down.")
//     10269: call [vtable+0x198]        ; <- powerDown
//     1026f: mov  byte [this+0x28f8], 0
// so a GPU whose PowerPlay init fails while the flag is set gets powered down, which is
// what empties the pools between the accelerator attaching and WindowServer's first
// command buffer.
//
// With the SMU on a dummy back end, PowerPlay genuinely is not supported here, and Apple
// has a path for exactly that: isSupported() is
//     [this+0x28f8] == 1 && [this+0x68] != 0
// and when it is false powerUp logs "SKIP: Not Supported", returns 0xe00002c7 without
// ever calling into PPLIB, and -- because 0x10240 tests the same flag -- skips
// handleCriticalError and powerDown as well. The controller already treats 0xe00002c7 as
// a warning ("Power Play Initialization Failed (Safe-Mode?)") and carries on.
//
// The flag comes from controller->getFeatures()->supportsFeature(8) in
// initWithController, whose prologue has a relative call inside the first 16 bytes and is
// not safe to route. Clearing it here, before the original runs, has the same effect at
// the only place it is read.
// Does enableAllocations even run, and which branch does it take? The pools report
// zero free with the sizes equalised and with PowerPlay no longer powering the GPU
// down, so the question is now whether IOAccelMemoryAllocator::init_pool is reached at
// all. enableAllocations bails silently when either pool pointer is null.
// Where does the power-up chain actually stop? AMDGraphicsAccelerator::powerUpHW only
// reaches AMDHWMemory::enableAllocations (its vtable slot 0x118, at 0x5099) after
//     0x5058  hardware->powerUp()                     (vtable 0x208)
//     0x5081  hardware->initializeHardwareRegisters() (vtable 0x250, always returns 1)
// and AMDHardware::powerUp in turn needs powerUpHWEngines (0x608) and startHWEngines
// (0x618) -- both reported 0 in the accelerator's own progress bitfield. Trace all four
// rather than keep reading disassembly.
// PM4 powerUp goes straight to AMDGFX10PM4Engine::doStart(false), which fails if
// either initComputeMQD(4) returns false or startKIQ returns non-zero. Split them.
static uint32_t wrapPm4Mqd(void *self, uint32_t ring) {
    auto r = FunctionCast(wrapPm4Mqd, orgPm4Mqd)(self, ring);
    RLOG("XJ:   PM4 initComputeMQD(ring=%u) -> %u", ring, r & 0xff);
    return r;
}

static uint32_t wrapKiqStart(void *self, uint64_t a, uint64_t b, void *spec, uint32_t *out) {
    auto r = FunctionCast(wrapKiqStart, orgKiqStart)(self, a, b, spec, out);
    RLOG("XJ:   PM4 startKIQ(%#llx, %#llx) -> %#x (0 is success)", a, b, r);
    kiqEopHint = b;
    if (mask & XK) {
        enableDoorbellMsg(a, b);
        // Before the frame is submitted and the doorbell rung, not after: once MEC2 is
        // stalled in WAIT_ON_ROQ_DATA the fetch is already outstanding and no TLB
        // invalidate brings it back.
        // relocateRingToVram() is deliberately not called any more: it answered its
        // question (the fetch hangs from VRAM too) and leaving it in only corrupts Apple's
        // ring mapping for every later experiment.
    }
    // startKIQ is where Apple's own KIQ HQD is written, so this is the first moment the
    // walk can distinguish Apple's queue from the ones TTL left behind.
    if (mask & XJ) dumpMecQueues("after startKIQ");
    return r;
}

// After startKIQ the ring loop runs: for each ring index it builds an MQD (graphics for
// ring 0, compute for ring 5) and submits a MAP_QUEUES packet, AND-ing the results.
// submitSetResourcesPacket sits between the two and cannot be routed -- its prologue has
// a relative call inside the first 16 bytes -- so infer it: if neither of these two fires,
// that is where doStart stopped.
static uint32_t wrapPm4GfxMqd(void *self) {
    auto r = FunctionCast(wrapPm4GfxMqd, orgPm4GfxMqd)(self);
    RLOG("XJ:   PM4 initGraphicsMQD -> %u", r & 0xff);
    return r;
}

static uint32_t wrapKiqMapQ(void *self, uint32_t ring, uint32_t a, uint64_t b,
                            void *spec, uint64_t c) {
    auto r = FunctionCast(wrapKiqMapQ, orgKiqMapQ)(self, ring, a, b, spec, c);
    RLOG("XJ:   PM4 submitMapQueuesPacket(ring=%u) -> %u", ring, r & 0xff);
    return r;
}

// The KIQ frame goes: ring enabled? -> commit -> ring the doorbell -> waitForHwStamp.
// Its two failure messages ("KIQ ring is disabled. Will not submit to ring!" and
// "Stamp Timeout for KIQ Submission!") never reach the serial console, so log the two
// steps directly, and dump the graphics core's own status registers alongside -- if the
// command processor is not executing, GRBM_STATUS and CP_STAT say so.

static void dumpGfxState(const char *when) {
    if (asicInfo == nullptr) { RLOG("XJ: %s: no AsicInfo yet", when); return; }
    RLOG("XJ: %s: GRBM_STATUS=%#x GRBM_STATUS2=%#x CP_STAT=%#x CP_ME_CNTL=%#x "
         "CP_MEC_CNTL=%#x RLC_CNTL=%#x RLC_STAT=%#x",
         when, fbRead(asicInfo, kGcGrbmStatus), fbRead(asicInfo, kGcGrbmStatus2),
         fbRead(asicInfo, kGcCpStat), fbRead(asicInfo, kGcCpMeCntl),
         fbRead(asicInfo, kGcCpMecCntl), fbRead(asicInfo, kGcRlcCntl),
         fbRead(asicInfo, kGcRlcStat));
    RLOG("XJ: %s: RLC_BOOTLOAD_STATUS=%#x RLC_GPM_STAT=%#x RLC_SAFE_MODE=%#x "
         "CP_CPF_STATUS=%#x CP_CPC_STATUS=%#x HQD_ACTIVE=%#x "
         "VM_FAULT_STATUS=%#x addr=%#x_%08x",
         when, fbRead(asicInfo, kGcRlcBootStat), fbRead(asicInfo, kGcRlcGpmStat),
         fbRead(asicInfo, kGcRlcSafeMode), fbRead(asicInfo, kGcCpfStatus),
         fbRead(asicInfo, kGcCpcStatus), fbRead(asicInfo, kGcHqdActive),
         fbRead(asicInfo, kGcVmFaultSts), fbRead(asicInfo, kGcVmFaultHi),
         fbRead(asicInfo, kGcVmFaultLo));
}

// Which compute queue, if any, is live? Walk the MEC queues with GRBM_GFX_CNTL and
// report every one whose HQD is active, plus the ring it points at and its doorbell.
static void dumpMecQueues(const char *when) {
    if (asicInfo == nullptr) return;
    RLOG("XJ: %s: MEC doorbell range %#x..%#x  ME1_HEADER_DUMP=%#x  "
         "CP_PQ_STATUS=%#x (doorbell_en=%u) CP_PQ_WPTR_POLL_CNTL=%#x", when,
         fbRead(asicInfo, kGcMecDbLower), fbRead(asicInfo, kGcMecDbUpper),
         fbRead(asicInfo, kGcMecHeaderDump), fbRead(asicInfo, kGcCpPqStatus),
         fbRead(asicInfo, kGcCpPqStatus) & 1, fbRead(asicInfo, kGcCpPqWptrPoll));
    unsigned found = 0;
    for (uint32_t me = 1; me <= 2; me++)
        for (uint32_t pipe = 0; pipe < 4; pipe++)
            for (uint32_t q = 0; q < 8; q++) {
                fbWrite(asicInfo, kGcGrbmGfxCntl, pipe | (me << 2) | (q << 8));
                if (fbRead(asicInfo, kGcHqdActive) & 1) {
                    uint32_t db = fbRead(asicInfo, kGcHqdPqDbCtl);
                    RLOG("XJ:   me%u pipe%u q%u ACTIVE  ring=%#x_%08x00 rptr=%#x "
                         "wptr=%#x_%08x vmid=%u ctl=%#x db_off=%#x en=%u",
                         me, pipe, q, fbRead(asicInfo, kGcHqdPqBaseHi),
                         fbRead(asicInfo, kGcHqdPqBase), fbRead(asicInfo, kGcHqdPqRptr),
                         fbRead(asicInfo, kGcHqdPqWptrHi), fbRead(asicInfo, kGcHqdPqWptrLo),
                         fbRead(asicInfo, kGcHqdVmid) & 0xf,
                         fbRead(asicInfo, kGcHqdPqControl),
                         (db >> 2) & 0x3ffffff, (db >> 30) & 1);
                    RLOG("XJ:     mqd=%#x_%08x persist=%#x", fbRead(asicInfo, kGcMqdBaseHi),
                         fbRead(asicInfo, kGcMqdBase), fbRead(asicInfo, kGcHqdPersist));
                    found++;
                }
            }
    fbWrite(asicInfo, kGcGrbmGfxCntl, 0);
    if (!found) RLOG("XJ:   no active compute queue on any MEC pipe");
}

// Is there any microcode in the command processor?
//
// The queue dumps say the MEC never fetches: CP_MEC_ME1_HEADER_DUMP keeps returning its
// 0xdefNdefN fill pattern, and CP_HQD_DEQUEUE_REQUEST -- which is serviced by MEC
// firmware, not by hardware -- never clears CP_HQD_ACTIVE. Both are consistent with the
// microengines simply having nothing to run.
//
// On the PSP load path nobody in the driver writes the ucode: LOAD_IP_FW hands each blob
// to the PSP, and GFX_CMD_ID_AUTOLOAD_RLC then asks it to have the RLC bootloader copy
// them into the microengines. In this guest that command is the one PSP command that
// fails (status 0xffff000d), so this reads the instruction RAM back through the same
// address/data pair the direct-load path uses. All zeroes means the CP was never loaded
// and AUTOLOAD_RLC is the blocker; real instruction words mean the ucode is there and
// the fault is in how the queue is mapped.
static void dumpCpUcode(const char *when) {
    if (asicInfo == nullptr) return;
    struct { const char *name; uint32_t addr, data; } eng[] {
        { "PFP ", kGcPfpUcodeAddr,  kGcPfpUcodeData  },
        { "ME  ", kGcMeRamRaddr,    kGcMeRamData     },
        { "CE  ", kGcCeUcodeAddr,   kGcCeUcodeData   },
        { "MEC1", kGcMec1UcodeAddr, kGcMec1UcodeData },
        { "MEC2", kGcMec2UcodeAddr, kGcMec2UcodeData },
    };
    for (auto &e : eng) {
        uint32_t w[6] {};
        uint32_t nonzero = 0;
        fbWrite(asicInfo, e.addr, 0);
        for (unsigned i = 0; i < 6; i++) { w[i] = fbRead(asicInfo, e.data); nonzero |= w[i]; }
        RLOG("XL: %s: %s ucode[0..5] = %08x %08x %08x %08x %08x %08x  %s", when, e.name,
             w[0], w[1], w[2], w[3], w[4], w[5], nonzero ? "LOADED" : "EMPTY");
    }
    RLOG("XL: %s: ME1_HEADER_DUMP=%#x ME2_HEADER_DUMP=%#x", when,
         fbRead(asicInfo, kGcMecHeaderDump), fbRead(asicInfo, kGcMec2HeaderDump));
}

// What does the graphics core's own address translation look like? Apple's GMC drives
// the MMHUB copies, which read back unprogrammed on this part -- the framebuffer
// aperture had to be taken from the GFXHUB copy for the same reason. If a ring lives
// outside the framebuffer aperture it goes through these, so a ring at a virtual
// address the GFXHUB cannot translate is one explanation for a CP that fetches nothing.
static void dumpGfxHubVm(const char *when) {
    if (asicInfo == nullptr) return;
    RLOG("XM: %s: SYS_APERTURE %#x..%#x  AGP base=%#x bot=%#x top=%#x", when,
         fbRead(asicInfo, kGcVmSysApLow), fbRead(asicInfo, kGcVmSysApHigh),
         fbRead(asicInfo, kGcVmAgpBase), fbRead(asicInfo, kGcVmAgpBot),
         fbRead(asicInfo, kGcVmAgpTop));
    RLOG("XM: %s: CTX0 cntl=%#x ptb=%#x_%08x start=%#x end=%#x | CTX1 cntl=%#x ptb_lo=%#x",
         when, fbRead(asicInfo, kGcVmCtx0Cntl), fbRead(asicInfo, kGcVmCtx0PtbHi),
         fbRead(asicInfo, kGcVmCtx0PtbLo), fbRead(asicInfo, kGcVmCtx0Start),
         fbRead(asicInfo, kGcVmCtx0End), fbRead(asicInfo, kGcVmCtx1Cntl),
         fbRead(asicInfo, kGcVmCtx1PtbLo));
    uint32_t tlb = fbRead(asicInfo, kGcVmL1TlbCntl), l2 = fbRead(asicInfo, kGcVmL2Cntl);
    RLOG("XM: %s: MX_L1_TLB_CNTL=%#x (l1_tlb_en=%u sys_access_mode=%u) L2_CNTL=%#x "
         "(l2_cache_en=%u) L2_CNTL2=%#x L2_CNTL3=%#x L2_STATUS=%#x CONTEXTS_DISABLE=%#x",
         when, tlb, tlb & 1, (tlb >> 3) & 3, l2, l2 & 1,
         fbRead(asicInfo, kGcVmL2Cntl2), fbRead(asicInfo, kGcVmL2Cntl3),
         fbRead(asicInfo, kGcVmL2Status), fbRead(asicInfo, kGcVmCtxDisable));
    RLOG("XM: %s: INVALIDATE_ENG0 req=%#x ack=%#x sem=%#x  L2_FAULT_CNTL=%#x",
         when, fbRead(asicInfo, kGcVmInvEng0Req), fbRead(asicInfo, kGcVmInvEng0Ack),
         fbRead(asicInfo, kGcVmInvEng0Sem), fbRead(asicInfo, kGcVmFaultCntl));
}

static uint32_t wrapWaitStamp(void *self, uint32_t stamp) {
    auto r = FunctionCast(wrapWaitStamp, orgWaitStamp)(self, stamp);
    RLOG("XJ:   waitForHwStamp(%u) -> %u", stamp, r & 0xff);
    if (!(r & 0xff)) {
        dumpGfxState("after stamp timeout");
        dumpMecQueues("after stamp timeout");
        dumpCpUcode("after stamp timeout");
        dumpGfxHubVm("after stamp timeout");
    }
    return r;
}

// Program the GFXHUB L2 the way upstream does.
//
// The CP's ring fetch is issued and never returns -- MEC2_WAIT_ON_ROQ_DATA with every
// UTCL wait bit clear -- and it does not return from VRAM either, so this is the path
// between the CP and the GL2/UTCL2 complex rather than anything about the ring's memory.
// That complex is the one part of the GFXHUB never checked field by field against
// gfxhub_v2_1_init_cache_regs, and it does not match:
//
//     GCVM_L2_CNTL  = 0xc0603   ENABLE_L2_FRAGMENT_PROCESSING set (upstream clears it),
//                               ENABLE_DEFAULT_PAGE_OUT_TO_SYSTEM_MEMORY clear (upstream
//                               sets it), PDE_FAULT_CLASSIFICATION set (upstream clears it)
//     GCVM_L2_CNTL3 = 0x80120007  BANK_SELECT 7 and L2_CACHE_BIGK_FRAGMENT_SIZE 4;
//                                 upstream writes 9 and 6 from mmGCVM_L2_CNTL3_DEFAULT
//
// Write upstream's values, including CNTL4 and CNTL5 from their defaults with
// VMC_TAP_PDE/PTE_REQUEST_PHYSICAL and L2_CACHE_SMALLK_FRAGMENT_SIZE cleared, then
// invalidate so nothing is left cached under the old organisation. Done from
// powerUpHWEngines, which is before initComputeMQD and startKIQ.
static void programL2LikeUpstream() {
    if (asicInfo == nullptr) return;
    uint32_t cntl = fbRead(asicInfo, kGcVmL2Cntl);
    uint32_t want = cntl;
    want |=  (1u << 0);            // ENABLE_L2_CACHE
    want &= ~(1u << 1);            // ENABLE_L2_FRAGMENT_PROCESSING
    want |=  (1u << 11);           // ENABLE_DEFAULT_PAGE_OUT_TO_SYSTEM_MEMORY
    want &= ~(1u << 8);            // L2_PDE0_CACHE_TAG_GENERATION_MODE
    want &= ~(1u << 18);           // PDE_FAULT_CLASSIFICATION
    want = (want & ~(3u << 19)) | (1u << 19);      // CONTEXT1_IDENTITY_ACCESS_MODE = 1
    want &= ~(0x1fu << 21);        // IDENTITY_MODE_FRAGMENT_SIZE = 0
    fbWrite(asicInfo, kGcVmL2Cntl, want);

    uint32_t c3 = 0x80100007u;                              // mmGCVM_L2_CNTL3_DEFAULT
    c3 = (c3 & ~0x3fu) | 9u;                                // BANK_SELECT = 9
    c3 = (c3 & ~(0x1fu << 15)) | (6u << 15);                // BIGK_FRAGMENT_SIZE = 6
    fbWrite(asicInfo, kGcVmL2Cntl3, c3);
    uint32_t c4 = 0x000000c1u & ~((1u << 6) | (1u << 7));   // CNTL4 default, TAP_*_PHYSICAL 0
    fbWrite(asicInfo, kGcVmL2Cntl4, c4);
    uint32_t c5 = 0x00003fe0u & ~0x1fu;                     // CNTL5 default, SMALLK 0
    fbWrite(asicInfo, kGcVmL2Cntl5, c5);
    // One-shot invalidate bits, as gfxhub_v2_1_init_cache_regs sets in CNTL2.
    fbWrite(asicInfo, kGcVmL2Cntl2, fbRead(asicInfo, kGcVmL2Cntl2) | 3u);

    RLOG("XN: L2 upstream config: CNTL %#x -> %#x (want %#x) CNTL3 -> %#x (want %#x) "
         "CNTL4 -> %#x CNTL5 -> %#x", cntl, fbRead(asicInfo, kGcVmL2Cntl), want,
         fbRead(asicInfo, kGcVmL2Cntl3), c3, fbRead(asicInfo, kGcVmL2Cntl4),
         fbRead(asicInfo, kGcVmL2Cntl5));
}

// Start the compute microengines with an explicit halt-to-unhalt transition.
//
// CP_MEC_CNTL reads 0 at every point measured -- before TTL, during GC HW_INIT and after
// the accelerator powers up -- so nothing in this stack ever performs the 1-to-0 edge that
// releases the MECs from halt. Upstream always does, in gfx_v10_0_cp_compute_enable:
//
//     if (enable) {
//             WREG32_SOC15(GC, 0, mmCP_MEC_CNTL, 0);
//     } else {
//             WREG32_SOC15(GC, 0, mmCP_MEC_CNTL, (CP_MEC_CNTL__MEC_ME1_HALT_MASK |
//                                                 CP_MEC_CNTL__MEC_ME2_HALT_MASK));
//             ...
//     }
//     udelay(50);
//
// and it runs cp_compute_enable(true) before kiq_resume, i.e. before any HQD is
// programmed. The measurements say the engines are in the state that edge is supposed to
// resolve: CP_MEC1_INSTR_PNTR sits at 0x10000, the same value the halted PFP and ME report,
// while CP_MEC2_INSTR_PNTR holds a real address and CP_CPC_STATUS reports MEC2_BUSY alone.
// One of the two engines is executing and the other has never started.
//
// Do the full edge -- halt both, invalidate the instruction cache, unhalt -- here, from
// powerUpHWEngines, which is upstream's ordering: ahead of initComputeMQD and startKIQ, so
// the queue is programmed onto engines that are already running.
static void startMecEngines() {
    if (asicInfo == nullptr) return;
    // Is 0x210000 a wedge or just the halted signature?
    //
    // The write that first turned CP_CPC_STALLED_STAT1 non-zero was a routine
    // GRBM_GFX_INDEX = 0 broadcast-select -- but CP_MEC_CNTL read 0x50000000 at that
    // moment, i.e. TTL had just halted both MECs. So MEC2_DECODING_PACKET |
    // MEC2_WAIT_ON_ROQ_DATA may be nothing more than what a halted MEC2 reports, and the
    // whole "the engine is stuck waiting on a fetch" reading would be wrong. Sample the
    // register across a deliberate halt and unhalt to find out: if it tracks the halt bits
    // it is a status artefact, and if it sticks after the unhalt the engine really is stuck.
    // No halt/unhalt edge here any more. It was modelled on upstream's
    // gfx_v10_0_cp_compute_enable, but halting the MECs on this part is one-way: the first
    // halt latches CP_CPC_STALLED_STAT1 at 0x210000 and MEC2 never executes again. Only the
    // instruction-cache invalidate is kept, which does not touch the halt bits.
    uint32_t before = fbRead(asicInfo, kGcCpMecCntl);
    uint32_t st0 = fbRead(asicInfo, kGcCpcStalled1);
    uint32_t stHalted = st0;
    fbWrite(asicInfo, kGcCpMecCntl, before | (1u << 27));       // MEC_INVALIDATE_ICACHE
    IODelay(50);
    fbWrite(asicInfo, kGcCpMecCntl, before);
    IODelay(50);
    uint32_t p1 = fbRead(asicInfo, kGcMec1InstrPntr), p2 = fbRead(asicInfo, kGcMec2InstrPntr);
    IODelay(50);
    RLOG("XK: stall across halt: CP_MEC_CNTL %#x (stalled %#x) -> halted (stalled %#x) "
         "-> unhalted (stalled %#x)", before, st0, stHalted,
         fbRead(asicInfo, kGcCpcStalled1));
    RLOG("XK: MEC halt/unhalt: CP_MEC_CNTL %#x -> %#x  CPC_STATUS=%#x  "
         "MEC1 instr %#x->%#x  MEC2 instr %#x->%#x", before,
         fbRead(asicInfo, kGcCpMecCntl), fbRead(asicInfo, kGcCpcStatus),
         p1, fbRead(asicInfo, kGcMec1InstrPntr), p2, fbRead(asicInfo, kGcMec2InstrPntr));
}

// Tell the MEC when the doorbell moves.
//
// This is the whole KIQ blocker, and the queue dump names it exactly:
//
//     CP_HQD_ACTIVE      = 1          the queue is live
//     CP_HQD_PQ_WPTR     = 0x20       the doorbell store reached the hardware
//     CP_HQD_PQ_RPTR     = 0          nothing has been consumed
//     CP_HQD_ERROR       = 0          no UTCL1 error on any client
//     CP_HQD_HQ_STATUS0  = 0          DB_UPDATED_MSG_EN clear
//     CP_MEC2_INSTR_PNTR = 0x23a, unchanged 20 us later
//     CP_CPC_STATUS      = 0xa0000002 MEC2_BUSY
//
// So the microengine is running and parked in a loop, the write pointer is correct, and
// nothing tells the engine to look. CP_HQD_HQ_STATUS0.DB_UPDATED_MSG_EN is that
// notification, and on RDNA2 it is not optional -- upstream added it as an explicitly
// version-gated step in gfx_v10_0_compute_mqd_init:
//
//     if (amdgpu_ip_version(adev, GC_HWIP, 0) >= IP_VERSION(10, 3, 0)) {
//             tmp = RREG32_SOC15(GC, 0, mmCP_HQD_HQ_STATUS0);
//             tmp = REG_SET_FIELD(tmp, CP_HQD_HQ_STATUS0, DB_UPDATED_MSG_EN, 1);
//             mqd->cp_hqd_hq_status0 = tmp;
//     }
//
// Apple's AMDGFX10PM4Engine::initComputeMQD leaves the register at 0, so set it here, on
// the HQD startKIQ has just programmed and before the frame is submitted, so Apple's own
// doorbell write is the one that gets delivered.
static void enableDoorbellMsg(uint64_t mqdAddr, uint64_t eopAddr) {
    if (asicInfo == nullptr) return;
    fbWrite(asicInfo, kGcGrbmGfxCntl, kKiqSelector);

    // CP_HQD_HQ_STATUS0.DB_UPDATED_MSG_EN. Recorded as a NEGATIVE result: it does stick
    // (0 -> 0x80000000) and it changes nothing, and upstream's gfx_v10_0 never writes this
    // register at all -- CP_HQD_HQ_STATUS0 appears in gfx_v10_0.c only in a register-dump
    // table. Left in place because it is harmless and the readback is useful evidence.
    uint32_t st0 = fbRead(asicInfo, kGcHqdStatus0);
    fbWrite(asicInfo, kGcHqdStatus0, st0 | (1u << 31));

    // The fields Apple leaves at zero. Against upstream's gfx_v10_0_compute_mqd_init and
    // gfx_v10_0_kiq_init_register, the measured HQD matches on everything that carries an
    // address or a size -- PQ base, PQ control's QUEUE_SIZE, MQD base, rptr-report and
    // wptr-poll addresses, VMID, and CP_HQD_PERSISTENT_STATE, whose PRELOAD_SIZE field is
    // 0x53, exactly upstream's constant. Three things are missing:
    //
    //   CP_HQD_EOP_BASE_ADDR/_HI + CP_HQD_EOP_CONTROL   read 0; upstream always points the
    //       queue at an end-of-pipe buffer of GFX10_MEC_HPD_SIZE (2048) bytes.
    //   CP_HQD_QUANTUM                                  reads 0; upstream sets QUANTUM_EN
    //       with scale 1 and duration 1.
    //   CP_HQD_IB_CONTROL.MIN_IB_AVAIL_SIZE             upstream sets 3.
    //
    // startKIQ's two arguments are the MQD address and a second address 0x800 above it,
    // which is the size of struct v10_compute_mqd and also GFX10_MEC_HPD_SIZE -- an EOP
    // buffer allocated immediately after the MQD. Program it as upstream would, so the
    // queue has somewhere to retire to.
    // Why the EOP registers matter, and why they refuse writes.
    //
    // CP_CPF_BUSY_STAT = 0x48460000 decodes to HQD_SIGNAL_SEMAPHORE_BUSY,
    // HQD_MESSAGE_BUSY, HQD_EOP_FETCHER_BUSY, HQD_CONSUMED_RPTR_BUSY, HQD_ROQ_EOP_BUSY and
    // HQD_PQ_BUSY -- and, crucially, NOT HQD_PQ_FETCHER_BUSY and NOT HQD_ROQ_PQ_BUSY. The
    // fetcher that is busy is the EOP one, and the ROQ that is busy is the EOP ROQ. So
    // MEC2_WAIT_ON_ROQ_DATA is not waiting on the ring at all: it is waiting on the
    // end-of-pipe queue, whose base address reads 0 while CP_HQD_EOP_CONTROL reads a size
    // of 6. A sized EOP buffer at address 0 is a fetch that can never complete, and it
    // blocks the packet decode behind it.
    //
    // And the reason the address will not take a write is the RLC. RLC_SRM_CNTL reads 0x3
    // -- SRM_ENABLE and AUTO_INCR_ADDR -- so the save/restore machine is live, and it
    // continuously restores its register list from the SRM image. This chip's own
    // gc_10_3_6 SRM list was substituted for Apple's Navi 23 one (milestone x9, and it is
    // the one blob whose length differs: 0x4480 against Apple's 0x5ec0), so a list that
    // covers CP_HQD_EOP_BASE_ADDR with a zero value would clobber every write within
    // microseconds -- from Apple's driver exactly as from here.
    //
    // Stop the SRM, program the EOP registers, confirm, and leave the SRM off: it exists
    // for GFXOFF and clock-gating save/restore, which this configuration does not use
    // anyway (PowerPlay is reported unsupported by milestone xi).
    uint32_t srm = fbRead(asicInfo, kGcRlcSrmCntl);
    fbWrite(asicInfo, kGcRlcSrmCntl, srm & ~1u);
    IODelay(50);
    uint64_t eop = eopAddr >> 8;
    fbWrite(asicInfo, kGcHqdEopBase, static_cast<uint32_t>(eop));
    fbWrite(asicInfo, kGcHqdEopBaseHi, static_cast<uint32_t>(eop >> 32));
    fbWrite(asicInfo, kGcHqdEopControl, 8);          // 2^(8+1) dwords = 2048 bytes
    RLOG("XK: SRM %#x -> %#x (SRM_STAT=%#x); EOP now %#x_%08x ctl=%#x", srm,
         fbRead(asicInfo, kGcRlcSrmCntl), fbRead(asicInfo, kGcRlcSrmStat),
         fbRead(asicInfo, kGcHqdEopBaseHi), fbRead(asicInfo, kGcHqdEopBase),
         fbRead(asicInfo, kGcHqdEopControl));
    fbWrite(asicInfo, kGcHqdQuantum, 1u | (1u << 4) | (1u << 8));
    uint32_t ib = fbRead(asicInfo, kGcHqdIbControl);
    fbWrite(asicInfo, kGcHqdIbControl, (ib & ~(0xfu << 20)) | (3u << 20));

    RLOG("XK: HQD gap fill (mqd=%#llx eop=%#llx): HQ_STATUS0=%#x EOP=%#x_%08x "
         "EOP_CONTROL=%#x QUANTUM=%#x IB_CONTROL=%#x",
         mqdAddr, eopAddr, fbRead(asicInfo, kGcHqdStatus0),
         fbRead(asicInfo, kGcHqdEopBaseHi), fbRead(asicInfo, kGcHqdEopBase),
         fbRead(asicInfo, kGcHqdEopControl), fbRead(asicInfo, kGcHqdQuantum),
         fbRead(asicInfo, kGcHqdIbControl));
    fbWrite(asicInfo, kGcGrbmGfxCntl, 0);
}

// Report a bad page instead of retrying it forever.
//
// The KIQ's write pointer does reach the hardware -- read with the right GRBM_GFX_CNTL
// selector, CP_HQD_PQ_WPTR is 0x20 after submitKIQFrame, so the doorbell store lands
// through BAR2 exactly as it should -- and CP_CPC_STATUS reads 0xa0000002, MEC2_BUSY, so
// the microengine is executing. The read pointer still never moves, and
// GCVM_L2_PROTECTION_FAULT_STATUS stays 0 throughout.
//
// A stall with no fault is what retry mode looks like. GCVM_CONTEXT0_CNTL reads 0x1555481,
// which has bit 7 -- RETRY_PERMISSION_OR_INVALID_PAGE_FAULT -- set, so an invalid or
// unpermitted page does not raise a fault: the request is retried indefinitely while the
// hardware waits for someone to fill the page in. Nothing in this guest ever will.
//
// Upstream turns this off for context 0 specifically. gfxhub_v2_1_enable_system_domain
// enables the context, sets PAGE_TABLE_DEPTH to 0 and clears
// RETRY_PERMISSION_OR_INVALID_PAGE_FAULT; only CONTEXT1..15, the user VMs, get retry (and
// then only when !adev->gmc.noretry). Do the same, so the next run either fetches or names
// the address it cannot translate.
static void disableCtx0Retry() {
    if (asicInfo == nullptr) return;
    uint32_t c = fbRead(asicInfo, kGcVmCtx0Cntl);
    if ((c & (1u << 7)) == 0) return;
    fbWrite(asicInfo, kGcVmCtx0Cntl, c & ~(1u << 7));
    RLOG("XK: GCVM_CONTEXT0_CNTL %#x -> %#x (cleared RETRY_PERMISSION_OR_INVALID_PAGE_FAULT, "
         "as gfxhub_v2_1_enable_system_domain does)", c, fbRead(asicInfo, kGcVmCtx0Cntl));
}

// Why does the KIQ never run?
//
// Everything about the queue reads correct after startKIQ: one active HQD, MQD at
// 0xf40b706000 in VRAM, ring at 0xFFBFEA0000 -- inside GCVM context 0's window, which the
// GFXHUB dump puts at 0xFFBFA00000..0xFFFFE00000 with a valid page-table base -- doorbell
// enabled at index 0 (which is where Navi puts the KIQ: AMDGPU_NAVI10_DOORBELL_KIQ = 0),
// CP_PQ_STATUS.DOORBELL_ENABLE set, CP_MEC_DOORBELL_RANGE covering it, and no VM fault
// before or after. Yet CP_HQD_PQ_WPTR stays 0 and CP_MEC_ME2_HEADER_DUMP keeps returning
// its fill pattern, so the MEC has not fetched a single packet header.
//
// Two candidates remain, and one register separates them. A doorbell write is the only
// thing telling the MEC the write pointer moved; if that write never reaches the device --
// it is a BAR2 store, and this is a passed-through iGPU -- the queue sits exactly like
// this. CP_PQ_WPTR_POLL_CNTL.EN is the alternative path: with it set the MEC polls each
// queue's write pointer out of memory at CP_HQD_PQ_WPTR_POLL_ADDR instead of waiting to be
// rung. So enable polling and watch the read pointer. If it advances, the doorbell is what
// is broken; if nothing moves, the microengine is not executing and the doorbell is
// innocent.
// Walk the GART page table the graphics core is actually using.
//
// Every other candidate for the dead KIQ has been eliminated by measurement, and the one
// asymmetry left is memory the MEC reads rather than memory it is told about. For a
// doorbell queue the engine takes the authoritative write pointer from
// CP_HQD_PQ_WPTR_POLL_ADDR (0xFFBFDE0050) and reports the read pointer to
// CP_HQD_PQ_RPTR_REPORT_ADDR (0xFFBFDE0048) -- both in the GART, i.e. guest system memory
// reached through the GFXHUB page tables and then the host IOMMU. A GPU that reads zeros
// there behaves exactly as observed: woken by the doorbell, it sees write pointer 0,
// concludes the queue is empty, sets QUEUE_IDLE, and touches neither the ring nor the
// report address -- no fault, no error bit, no header fetched.
//
// So read the page table. GCVM_CONTEXT0_CNTL has PAGE_TABLE_DEPTH 0, which means a flat
// array of 8-byte PTEs indexed by (va - PAGE_TABLE_START) >> 12, based at
// GCVM_CONTEXT0_PAGE_TABLE_BASE_ADDR with its low bits carrying flags rather than address.
// That base -- 0x0fdfc000 -- is a framebuffer-relative address inside the 256 MB BAR0
// aperture, so BAR0 is enough to read it: map it the same way AMDHardware::mapDoorbellMemory
// maps BAR2, through the IOPCIDevice at [hwObj+0x10] and its mapDeviceMemoryWithRegister,
// asking for config offset 0x10 instead of 0x18.
//
// An invalid PTE would explain the stall, though not the absent fault. A valid PTE gives
// the guest-physical page the GPU is reading, which is the number to compare against where
// Apple actually wrote the write pointer.
static volatile uint32_t *fbAperture() {
    static volatile uint32_t *cached {};
    static bool tried = false;
    if (tried) return cached;
    tried = true;
    if (hwObj == nullptr) return nullptr;
    auto pci = *reinterpret_cast<void **>(reinterpret_cast<uint8_t *>(hwObj) + 0x10);
    if (pci == nullptr) return nullptr;
    auto vt = *reinterpret_cast<uint64_t **>(pci);
    auto mapFn = reinterpret_cast<void *(*)(void *, uint32_t, uint32_t)>(vt[0x908 / 8]);
    auto map = mapFn(pci, 0x10, 0);
    if (map == nullptr) { RLOG("XN: BAR0 map failed"); return nullptr; }
    auto mvt = *reinterpret_cast<uint64_t **>(map);
    auto getVA = reinterpret_cast<uint64_t (*)(void *)>(mvt[0x118 / 8]);
    cached = reinterpret_cast<volatile uint32_t *>(getVA(map));
    RLOG("XN: BAR0 mapped at %p", cached);
    return cached;
}

// The physical pages the PTEs name are read from the HOST instead of from here.
// IOMemoryDescriptor::withPhysicalAddress + map() links against symbols the injected boot
// collection would not resolve, and the whole plugin then fails to load -- the guest falls
// back to a stale copy on disk and panics during matching. QEMU's monitor can dump guest
// physical memory directly ("xp /8x <pa>"), which answers the same question with nothing
// at risk inside the guest.
static void walkGart(const char *what, uint64_t va) {
    auto fb = fbAperture();
    if (fb == nullptr || asicInfo == nullptr) return;
    uint64_t start = static_cast<uint64_t>(fbRead(asicInfo, kGcVmCtx0Start)) << 12;
    uint64_t ptb   = (static_cast<uint64_t>(fbRead(asicInfo, kGcVmCtx0PtbHi)) << 32) |
                      fbRead(asicInfo, kGcVmCtx0PtbLo);
    ptb &= ~0xfffULL;
    if (va < start) { RLOG("XN: %s va %#llx below GART start %#llx", what, va, start); return; }
    uint64_t idx = (va - start) >> 12;
    uint64_t off = ptb + idx * 8;
    if (off + 8 > 0x10000000ULL) {
        RLOG("XN: %s PTE at fb offset %#llx is outside the 256 MB BAR0 aperture", what, off);
        return;
    }
    uint32_t lo = fb[off / 4], hi = fb[off / 4 + 1];
    uint64_t pte = (static_cast<uint64_t>(hi) << 32) | lo;
    RLOG("XN: %s va=%#llx idx=%#llx pte@fb+%#llx = %#llx -> pa %#llx flags%s%s%s%s%s",
         what, va, idx, off, pte, pte & 0x0000fffffffff000ULL,
         (pte & 1) ? " VALID" : " !VALID", (pte & 2) ? " SYSTEM" : "",
         (pte & 4) ? " SNOOPED" : "", (pte & 0x20) ? " READ" : "",
         (pte & 0x40) ? " WRITE" : "");
}

// Dump the MQD image the MEC reloads the HQD from.
//
// This is the last place the two views can disagree. The registers say the queue is
// active, points at a ring holding a valid PACKET3_SET_RESOURCES, and has taken the
// doorbell; guest memory confirms the packet and a write pointer of 0x20 at the physical
// page the GART names. Yet the engine reports QUEUE_IDLE and fetches nothing -- and
// writes to CP_HQD_EOP_BASE_ADDR do not stick even with CP_HQD_ACTIVE forced to 0, which
// is what an HQD being continuously restored from its MQD looks like. If the MQD image
// carries different values from the registers, the image is what the engine believes.
//
// Field offsets are struct v10_compute_mqd's, and the MQD lives in the framebuffer at
// CP_MQD_BASE_ADDR, so it is readable through the same BAR0 aperture as the page table.
static void dumpMqd(uint64_t mqdVa) {
    auto fb = fbAperture();
    if (fb == nullptr) return;
    uint64_t fbBase = static_cast<uint64_t>(fbRead(asicInfo, kGcFbBase) & 0xffffff) << 24;
    if (mqdVa < fbBase) { RLOG("XN: mqd %#llx below fb base %#llx", mqdVa, fbBase); return; }
    uint64_t off = mqdVa - fbBase;
    if (off + 0x800 > 0x10000000ULL) {
        RLOG("XN: mqd at fb offset %#llx is outside BAR0", off); return;
    }
    auto d = [fb, off](uint32_t f) { return fb[(off + f) / 4]; };
    RLOG("XN: MQD@fb+%#llx: header=%#x mqd_base=%#x active=%#x vmid=%#x persistent=%#x",
         off, d(0x000), d(0x200), d(0x208), d(0x20c), d(0x210));
    RLOG("XN: MQD: pq_base=%#x rptr=%#x doorbell_ctl=%#x pq_control=%#x",
         d(0x220), d(0x228), d(0x23c), d(0x244));
    RLOG("XN: MQD: eop_base=%#x eop_control=%#x wptr_lo=%#x wptr_hi=%#x",
         d(0x294), d(0x29c), d(0x2d8), d(0x2dc));
}

// Program the HQD from the MQD image, the way upstream's kiq_init_register does.
//
// The MQD image and the register file disagree, and the MQD is right:
//
//     field                   MQD image      HQD register
//     cp_hqd_eop_base_addr    0xf40b7068     0
//     cp_hqd_eop_control      0x8            0x6
//     cp_hqd_pq_control       0xd130860d     0xc030860d   (bits 20, 24, 28 missing)
//     cp_hqd_persistent_state 0xbe05301      0xbe05300    (PRELOAD_REQ missing)
//     cp_hqd_active           1              1
//     cp_hqd_pq_base          0xffbfea00     0xffbfea00
//     cp_hqd_pq_doorbell_ctl  0x40000000     0x40000000 (+ HIT, set by hardware)
//
// So startKIQ built a correct MQD and then did not get all of it into the register file --
// and the missing fields are exactly the ones this plugin also could not write, including
// with CP_HQD_ACTIVE forced to 0. Nothing loads the MQD on this path either: on GFX10 the
// driver writes the HQD itself and the MEC never fetches the image, which is why the
// register file is what the engine acts on and why a queue with no EOP address and no
// PRELOAD_REQ sits idle.
//
// Copy the image into the registers in upstream's order, with the MECs halted so the
// writes are not racing the engine, then unhalt and let the caller ring the doorbell.
// Report every field that still refuses to take, because that list is the finding either
// way.
static void loadHqdFromMqd(uint64_t mqdVa) {
    auto fb = fbAperture();
    if (fb == nullptr || asicInfo == nullptr) return;
    uint64_t fbBase = static_cast<uint64_t>(fbRead(asicInfo, kGcFbBase) & 0xffffff) << 24;
    if (mqdVa < fbBase || (mqdVa - fbBase) + 0x800 > 0x10000000ULL) return;
    uint64_t off = mqdVa - fbBase;
    auto d = [fb, off](uint32_t f) { return fb[(off + f) / 4]; };

    // Deliberately not halting the MECs here either -- see wrapGcCgsWrite2.
    uint32_t mecBefore = fbRead(asicInfo, kGcCpMecCntl);
    fbWrite(asicInfo, kGcGrbmGfxCntl, kKiqSelector);

    struct { uint32_t reg; uint32_t mqd; const char *name; } fields[] {
        {kGcHqdActive,      0x208, "ACTIVE=0 first"},   // handled specially below
        {kGcHqdEopBase,     0x294, "EOP_BASE"},
        {kGcHqdEopBaseHi,   0x298, "EOP_BASE_HI"},
        {kGcHqdEopControl,  0x29c, "EOP_CONTROL"},
        {kGcMqdBase,        0x200, "MQD_BASE"},
        {kGcMqdBaseHi,      0x204, "MQD_BASE_HI"},
        {kGcMqdControl,     0x288, "MQD_CONTROL"},
        {kGcHqdPqBase,      0x220, "PQ_BASE"},
        {kGcHqdPqBaseHi,    0x224, "PQ_BASE_HI"},
        {kGcHqdPqControl,   0x244, "PQ_CONTROL"},
        {kGcHqdRptrRpt,     0x22c, "RPTR_REPORT"},
        {kGcHqdRptrRptHi,   0x230, "RPTR_REPORT_HI"},
        {kGcHqdPollAddr,    0x234, "WPTR_POLL"},
        {kGcHqdPollAddrHi,  0x238, "WPTR_POLL_HI"},
        {kGcHqdPqDbCtl,     0x23c, "DOORBELL_CONTROL"},
        {kGcHqdIbControl,   0x254, "IB_CONTROL"},
        {kGcHqdQuantum,     0x21c, "QUANTUM"},
        {kGcHqdVmid,        0x20c, "VMID"},
        {kGcHqdPersist,     0x210, "PERSISTENT_STATE"},
    };
    fbWrite(asicInfo, kGcHqdActive, 0);
    IODelay(20);
    char bad[128];
    size_t n = 0;
    for (auto &f : fields) {
        if (f.reg == kGcHqdActive) continue;
        uint32_t want = d(f.mqd);
        fbWrite(asicInfo, f.reg, want);
        uint32_t got = fbRead(asicInfo, f.reg);
        if (got != want && n + 24 < sizeof(bad))
            n += snprintf(bad + n, sizeof(bad) - n, "%s(%#x!=%#x) ", f.name, got, want);
    }
    fbWrite(asicInfo, kGcHqdActive, d(0x208));
    IODelay(20);
    // Deliberately NOT restoring GRBM_GFX_CNTL here: the caller set the KIQ selector and
    // goes on reading this queue afterwards. Resetting it to 0 mid-sequence pointed every
    // later read at me0/pipe0/queue0, an empty HQD, which made a whole run's worth of
    // measurements read as zeroes.
    RLOG("XN: HQD loaded from MQD; refused: %s", n ? bad : "(none)");
    RLOG("XN: after load: active=%u eop=%#x_%08x eop_ctl=%#x pq_control=%#x persistent=%#x "
         "CP_MEC_CNTL %#x->%#x", fbRead(asicInfo, kGcHqdActive) & 1,
         fbRead(asicInfo, kGcHqdEopBaseHi), fbRead(asicInfo, kGcHqdEopBase),
         fbRead(asicInfo, kGcHqdEopControl), fbRead(asicInfo, kGcHqdPqControl),
         fbRead(asicInfo, kGcHqdPersist), mecBefore, fbRead(asicInfo, kGcCpMecCntl));
}

// Move the ring into VRAM and see whether the engine then runs it.
//
// CP_CPC_STALLED_STAT1 = 0x210000 is MEC2_DECODING_PACKET | MEC2_WAIT_ON_ROQ_DATA, and
// CP_CPC_BUSY_STAT = 0x8080000 is MEC2_MESSAGE_BUSY | MEC2_PIPE1_BUSY. So the queue is
// dispatched on the pipe the selector walk found, the engine has begun decoding, and it is
// stalled waiting for the ring fetch to come back. Neither UTCL2IU_WAITING_ON_FREE/TAGS nor
// UTCL1_WAITING_ON_TRANS is set, so it is not stuck in translation: the read was issued and
// the data never arrived. The host logs no AMD-Vi IO_PAGE_FAULT for the device either.
//
// Everything this stack has been proven to read so far -- the PSP ring, the TMR, the MQD,
// the page tables themselves, the RLC clear-state buffer -- lives in the framebuffer, which
// the hardware reaches through the FB aperture and GCMC_VM_FB_OFFSET without any DMA. The
// KIQ ring is the first thing it has been asked to fetch from guest system memory, through
// a SYSTEM|SNOOPED PTE, and that is the fetch that hangs.
//
// So test exactly that: copy the ring page into an unused framebuffer page, rewrite its GART
// PTE to point at VRAM instead of system memory (clearing SYSTEM and SNOOPED and the MTYPE
// bits), invalidate the TLB the way upstream does, and ring the doorbell. If the engine then
// consumes the packet, the fault is the GPU's path to guest system memory and not anything
// about how the queue is programmed.
// Scratch framebuffer offsets. These MUST stay clear of the GART page table, which sits at
// GCVM_CONTEXT0_PAGE_TABLE_BASE (fb+0x0fdfc000) and, for context 0's 1 GB window, runs about
// 2 MB from there -- the earlier 0x0ff00000 choice was inside it.
// Where the MEC microcode has to live: the framebuffer offset that the locked
// CP_CPC_IC_BASE resolves to once the aperture has been moved. See relocateFbAperture.
static constexpr uint64_t kMecFwFbOffset    = 0x0f904000;
// gc_10_3_6_mec.bin's own header fields, for the jump-table half of the direct load.
static constexpr uint32_t kMecJtOffsetDwords = 0x1052c;
static constexpr uint32_t kMecJtSizeDwords   = 0xe0;
static constexpr uint32_t kMecFwVersion      = 0x1c;
static constexpr uint64_t kRingCopyFbOffset = 0x0f100000;
static constexpr uint64_t kProbeFbOffsetOld = 0;

static void relocateRingToVram() {
    auto fb = fbAperture();
    if (fb == nullptr || asicInfo == nullptr) return;
    uint64_t start = static_cast<uint64_t>(fbRead(asicInfo, kGcVmCtx0Start)) << 12;
    uint64_t ptb   = ((static_cast<uint64_t>(fbRead(asicInfo, kGcVmCtx0PtbHi)) << 32) |
                       fbRead(asicInfo, kGcVmCtx0PtbLo)) & ~0xfffULL;
    uint64_t ringVa = static_cast<uint64_t>(fbRead(asicInfo, kGcHqdPqBase)) << 8;
    if (ringVa < start) return;
    uint64_t pteOff = ptb + ((ringVa - start) >> 12) * 8;
    if (pteOff + 8 > 0x10000000ULL) return;

    uint64_t old = (static_cast<uint64_t>(fb[pteOff / 4 + 1]) << 32) | fb[pteOff / 4];
    if ((old & 1) == 0) { RLOG("XN: ring PTE not valid, not relocating"); return; }

    // The framebuffer aperture is a window onto VRAM, so the copy can be done with plain
    // dword moves -- but read the source through the PTE's own physical page rather than
    // through any CPU mapping, which is not available here. The page the PTE names is
    // already known to hold the packet (confirmed from the host with the QEMU monitor), and
    // the only copy available in-guest is via the FB aperture, so copy from the ring's
    // current GART view is impossible: instead reconstruct the one packet Apple submitted.
    // PACKET3_SET_RESOURCES, 8 dwords, exactly as read from guest RAM at the ring base.
    static const uint32_t kSetResources[] {
        0xc006a000, 0x0028ffff, 0xffffffff, 0x00000000,
        0x00000000, 0x00000000, 0x00000000, 0x00000000,
    };
    for (unsigned i = 0; i < sizeof(kSetResources) / 4; i++)
        fb[(kRingCopyFbOffset / 4) + i] = kSetResources[i];
    for (unsigned i = sizeof(kSetResources) / 4; i < 0x400; i++)
        fb[(kRingCopyFbOffset / 4) + i] = 0x80000000u;   // PACKET2 nops

    uint64_t nw = (old & ~0x0000fffffffff000ULL & ~(3ULL << 48)) | kRingCopyFbOffset;
    nw &= ~0x6ULL;                                        // clear SYSTEM and SNOOPED
    fb[pteOff / 4]     = static_cast<uint32_t>(nw);
    fb[pteOff / 4 + 1] = static_cast<uint32_t>(nw >> 32);

    // Invalidate, the way gmc_v10_0_flush_gpu_tlb builds its request: VMID 0, all levels.
    fbWrite(asicInfo, kGcVmInvEng0Req, 0x00f80001u);
    int us = 0;
    for (; us < 2000; us++) {
        if ((fbRead(asicInfo, kGcVmInvEng0Ack) & 0xffff) != 0) break;
        IODelay(1);
    }
    RLOG("XN: ring PTE %#llx -> %#llx (VRAM fb+%#llx); invalidate acked after %dus, "
         "ack=%#x; pte reads back %#llx", old, nw, kRingCopyFbOffset, us,
         fbRead(asicInfo, kGcVmInvEng0Ack),
         (static_cast<uint64_t>(fb[pteOff / 4 + 1]) << 32) | fb[pteOff / 4]);
}

static void kickKiq(uint64_t eopHint) {
    if (asicInfo == nullptr) return;
    fbWrite(asicInfo, kGcGrbmGfxCntl, kKiqSelector);
    RLOG("XK: KIQ before kick: active=%u rptr=%#x wptr=%#x_%08x poll_addr=%#x_%08x "
         "rptr_report=%#x_%08x eop=%#x",
         fbRead(asicInfo, kGcHqdActive) & 1, fbRead(asicInfo, kGcHqdPqRptr),
         fbRead(asicInfo, kGcHqdPqWptrHi), fbRead(asicInfo, kGcHqdPqWptrLo),
         fbRead(asicInfo, kGcHqdPollAddrHi), fbRead(asicInfo, kGcHqdPollAddr),
         fbRead(asicInfo, kGcHqdRptrRptHi), fbRead(asicInfo, kGcHqdRptrRpt),
         fbRead(asicInfo, kGcHqdEopBase));
    RLOG("XK: CP stalls: STALLED_STAT1=%#x 2=%#x 3=%#x BUSY_STAT=%#x | "
         "CPC busy=%#x stalled=%#x | CPF busy=%#x stalled=%#x",
         fbRead(asicInfo, kGcCpStalled1), fbRead(asicInfo, kGcCpStalled2),
         fbRead(asicInfo, kGcCpStalled3), fbRead(asicInfo, kGcCpBusyStat),
         fbRead(asicInfo, kGcCpcBusyStat), fbRead(asicInfo, kGcCpcStalled1),
         fbRead(asicInfo, kGcCpfBusyStat), fbRead(asicInfo, kGcCpfStalled1));
    RLOG("XK: gfx ring: RB0_BASE=%#x_%08x CNTL=%#x RPTR=%#x WPTR=%#x VMID=%#x "
         "RB_DOORBELL=%#x ME_CNTL=%#x",
         fbRead(asicInfo, kGcRb0BaseHi), fbRead(asicInfo, kGcRb0Base),
         fbRead(asicInfo, kGcRb0Cntl), fbRead(asicInfo, kGcRb0Rptr),
         fbRead(asicInfo, kGcRb0Wptr), fbRead(asicInfo, kGcRbVmid),
         fbRead(asicInfo, kGcRbDbCtl), fbRead(asicInfo, kGcCpMeCntl));
    RLOG("XK: RLC: SRM_CNTL=%#x CSIB_LO=%#x CSIB_LEN=%#x GPM_STAT=%#x STAT=%#x "
         "BOOTLOAD 0x4e8d=%#x 0x4e7e=%#x",
         fbRead(asicInfo, kGcRlcSrmCntl), fbRead(asicInfo, kGcRlcCsibLo),
         fbRead(asicInfo, kGcRlcCsibLen), fbRead(asicInfo, kGcRlcGpmStat),
         fbRead(asicInfo, kGcRlcStat), fbRead(asicInfo, kGcRlcBootStat),
         fbRead(asicInfo, kGcRlcBootStatSc));
    uint32_t st0 = fbRead(asicInfo, kGcHqdStatus0);
    RLOG("XK: KIQ HQD: ERROR=%#x HQ_STATUS0=%#x (queue_idle=%u db_updated_msg_en=%u) "
         "HQ_STATUS1=%#x MQD_CONTROL=%#x QUANTUM=%#x IQ_TIMER=%#x DEQUEUE_REQ=%#x",
         fbRead(asicInfo, kGcHqdError), st0, (st0 >> 30) & 1, (st0 >> 31) & 1,
         fbRead(asicInfo, kGcHqdStatus1), fbRead(asicInfo, kGcMqdControl),
         fbRead(asicInfo, kGcHqdQuantum), fbRead(asicInfo, kGcHqdIqTimer),
         fbRead(asicInfo, kGcHqdDequeue));
    // Are the microengines advancing or parked? Two samples a few microseconds apart say
    // which, and an instruction pointer that does not move is a spin loop, not progress.
    uint32_t m1a = fbRead(asicInfo, kGcMec1InstrPntr), m2a = fbRead(asicInfo, kGcMec2InstrPntr);
    uint32_t pfa = fbRead(asicInfo, kGcPfpInstrPntr),  mea = fbRead(asicInfo, kGcMeInstrPntr);
    IODelay(20);
    RLOG("XK: instr pntr: MEC1 %#x->%#x MEC2 %#x->%#x PFP %#x->%#x ME %#x->%#x CP_MEC_CNTL=%#x",
         m1a, fbRead(asicInfo, kGcMec1InstrPntr), m2a, fbRead(asicInfo, kGcMec2InstrPntr),
         pfa, fbRead(asicInfo, kGcPfpInstrPntr), mea, fbRead(asicInfo, kGcMeInstrPntr),
         fbRead(asicInfo, kGcCpMecCntl));
    dumpGfxHubVm("at KIQ kick");
    walkGart("ring", (static_cast<uint64_t>(fbRead(asicInfo, kGcHqdPqBase)) << 8));
    walkGart("wptr poll", (static_cast<uint64_t>(fbRead(asicInfo, kGcHqdPollAddrHi)) << 32) |
                          fbRead(asicInfo, kGcHqdPollAddr));
    walkGart("rptr report", (static_cast<uint64_t>(fbRead(asicInfo, kGcHqdRptrRptHi)) << 32) |
                            fbRead(asicInfo, kGcHqdRptrRpt));
    uint64_t mqdVa = (static_cast<uint64_t>(fbRead(asicInfo, kGcMqdBaseHi)) << 32) |
                     fbRead(asicInfo, kGcMqdBase);
    dumpMqd(mqdVa);
    loadHqdFromMqd(mqdVa);
    // Does the doorbell reach the queue, and can the HQD be reprogrammed at all?
    //
    // CP_HQD_PQ_DOORBELL_CONTROL carries DOORBELL_HIT in bit 31: hardware sets it when a
    // doorbell for this queue arrives. Printing the raw register answers whether the store
    // gets as far as the HQD. And CP_HQD_EOP_BASE_ADDR ignored a write earlier while
    // CP_HQD_QUANTUM and CP_HQD_IB_CONTROL accepted theirs, which is what an HQD owned by a
    // live queue looks like -- upstream always deactivates before it reprograms. So try it
    // upstream's way round: CP_HQD_ACTIVE = 0, write the EOP registers, CP_HQD_ACTIVE = 1.
    {
        uint32_t db = fbRead(asicInfo, kGcHqdPqDbCtl);
        RLOG("XK: DOORBELL_CONTROL=%#x (offset=%#x en=%u hit=%u source=%u schd_hit=%u)",
             db, (db >> 2) & 0x3ffffff, (db >> 30) & 1, (db >> 31) & 1, (db >> 28) & 1,
             (db >> 29) & 1);
        uint64_t eop = eopHint >> 8;
        fbWrite(asicInfo, kGcHqdActive, 0);
        IODelay(20);
        fbWrite(asicInfo, kGcHqdEopBase, static_cast<uint32_t>(eop));
        fbWrite(asicInfo, kGcHqdEopBaseHi, static_cast<uint32_t>(eop >> 32));
        fbWrite(asicInfo, kGcHqdEopControl, 8);
        uint32_t got = fbRead(asicInfo, kGcHqdEopBase);
        fbWrite(asicInfo, kGcHqdActive, 1);
        IODelay(20);
        RLOG("XK: EOP while deactivated: wrote %#llx>>8=%#x, reads %#x, EOP_CONTROL=%#x, "
             "active back to %u", eopHint, static_cast<uint32_t>(eop), got,
             fbRead(asicInfo, kGcHqdEopControl), fbRead(asicInfo, kGcHqdActive) & 1);
    }
    // Ring the doorbell by hand.
    //
    // CP_HQD_PQ_WPTR_LO reading 0x20 does not prove the doorbell landed: upstream's
    // gfx_v10_0_kiq_init_register writes that register out of the MQD too, so Apple could
    // have put it there itself. CP_HQD_HQ_STATUS0.QUEUE_IDLE is set, which says the MEC has
    // looked at the queue and found nothing to run -- and for a doorbell queue the value
    // the engine acts on comes from the doorbell, not from this register. So write the
    // doorbell directly, 64-bit, at index 0 (AMDGPU_NAVI10_DOORBELL_KIQ, and the offset the
    // HQD itself carries), and see whether the read pointer moves. If it does, Apple's own
    // store is not reaching BAR2; if it does not, the doorbell path is innocent.
    if (hwObj != nullptr) {
        auto dbBase = *reinterpret_cast<volatile uint64_t **>(
                          reinterpret_cast<uint8_t *>(hwObj) + 0x528);
        uint32_t wptr = fbRead(asicInfo, kGcHqdPqWptrLo);
        // Ring with EIGHT dwords, not the 0x20 the queue carries.
        //
        // Read from the host, the ring holds exactly one packet: 0xc006a000, which is
        // PACKET3(PACKET3_SET_RESOURCES, 6) to the dword -- upstream's
        // gfx_v10_0_kiq_set_resources builds the identical header -- followed by its seven
        // payload dwords. That is 8 dwords. The next dword is 0xffff1000, which is not a
        // packet: as a type-3 header it claims a count of 0x3fff, so a command processor
        // that reads it will wait for 16384 dwords that will never arrive. Which is exactly
        // the state the CP is in: MEC2_DECODING_PACKET | MEC2_WAIT_ON_ROQ_DATA, with
        // HQD_PQ_FETCHER_BUSY and HQD_ROQ_PQ_BUSY both clear because the ring read it needed
        // has already happened.
        //
        // CP_HQD_PQ_WPTR reads 0x20 = 32. On GFX10 a compute queue's write pointer is in
        // DWORDS -- amdgpu's gfx_v10_0_ring_set_wptr_compute rings the doorbell with
        // ring->wptr, which counts dwords -- and 32 bytes is 8 dwords. So if the value that
        // reached the doorbell is a byte count, the engine has been told there are 24 dwords
        // of packets past the end of the real one.
        //
        // Ringing with 8 tests that directly: if the stall clears and the read pointer
        // moves, the write pointer is being submitted in the wrong unit.
        if (dbBase != nullptr) {
            dbBase[0] = 8;
            RLOG("XK: rang doorbell 0 at %p with 8 dwords (queue carries wptr %#x)",
                 dbBase, wptr);
        } else {
            RLOG("XK: no doorbell mapping at [hwObj+0x528]");
        }
    }
    for (unsigned i = 0; i < 8; i++) {
        IODelay(500);
        RLOG("XK: KIQ +%u00us: rptr=%#x wptr=%#x active=%u ME2_HDR=%#x CP_STAT=%#x "
             "CPC_STATUS=%#x fault=%#x addr=%#x_%08x", (i + 1) * 5,
             fbRead(asicInfo, kGcHqdPqRptr), fbRead(asicInfo, kGcHqdPqWptrLo),
             fbRead(asicInfo, kGcHqdActive) & 1, fbRead(asicInfo, kGcMec2HeaderDump),
             fbRead(asicInfo, kGcCpStat), fbRead(asicInfo, kGcCpcStatus),
             fbRead(asicInfo, kGcVmFaultSts), fbRead(asicInfo, kGcVmFaultHi),
             fbRead(asicInfo, kGcVmFaultLo));
    }
    fbWrite(asicInfo, kGcGrbmGfxCntl, 0);
}

#if RGPU_HAVE_MEC_FW
// Load the MEC microcode and point the instruction cache at it, as upstream's direct path does.
//
// This is the root cause of the dead command processor. After amdgpu hands the device over,
// the CP's instruction-cache base registers still hold the HOST driver's addresses:
//
//     CP_CPC_IC_BASE = 0x8_5f904000    CP_PFP_IC_BASE = 0x8_5f87c000
//     CP_ME_IC_BASE  = 0x8_5f8c0000    CP_CPC_IC_BASE_CNTL = 0x10 (ADDRESS_CLAMP)
//
// The host's framebuffer offset is 0x840000000, so those are addresses inside the host's own
// carveout -- memory this guest has since reused. On GFX10 a microengine does not run out of
// internal RAM; it fetches through that cache, so pointing it at foreign memory is why MEC2's
// instruction pointer parks at 0x310 and never moves across sixteen samples, why MEC1 reads
// the same 0x10000 the halted graphics engines report, and why nothing -- not Apple's
// SET_RESOURCES, not a WRITE_DATA packet of our own with a correct doorbell -- ever executes.
// GFX_CMD_ID_AUTOLOAD_RLC, which is what would have reprogrammed this on the PSP path,
// answers TEE_ERROR_BUSY.
//
// Upstream programs it directly, in gfx_v10_0_cp_compute_load_microcode:
//
//     WREG32(mmCP_CPC_IC_BASE_LO, lower_32_bits(mec_fw_gpu_addr) & 0xFFFFF000);
//     WREG32(mmCP_CPC_IC_BASE_HI, upper_32_bits(mec_fw_gpu_addr));
//     ... CP_CPC_IC_BASE_CNTL: VMID 0, CACHE_POLICY 0, EXE_DISABLE 0, ADDRESS_CLAMP 1
//     ... CP_CPC_IC_OP_CNTL.INVALIDATE_CACHE = 1
//
// so copy this chip's own gc_10_3_6 MEC payload into the framebuffer through BAR0, take the
// framebuffer's own MC address for it, and do the same. VRAM needs no page tables -- it is
// reached through the FB aperture -- so the address is simply fb base plus the offset.
static void loadMecMicrocode() {
    auto fb = fbAperture();
    if (fb == nullptr || asicInfo == nullptr) return;
    static bool done = false;
    if (done) return;
    done = true;

    uint64_t fbBase = static_cast<uint64_t>(fbRead(asicInfo, kGcFbBase) & 0xffffff) << 24;
    uint64_t mcAddr = fbBase + kMecFwFbOffset;
    if (kMecFwFbOffset + kMecFwSize > 0x10000000ULL) {
        RLOG("XP: MEC ucode does not fit under the 256 MB BAR0 aperture"); return;
    }
    auto src = reinterpret_cast<const uint32_t *>(kMecFw);
    for (uint32_t i = 0; i < kMecFwSize / 4; i++) fb[(kMecFwFbOffset / 4) + i] = src[i];

    // Confirm the microcode is really where the CP will look, and that the power state lets
    // the engines run at all. RLC_PG_CNTL bit 0 is GFX_POWER_GATING_ENABLE and bit 15 is
    // CP_PG_DISABLE; upstream turns graphics power gating off through the SMU, and this
    // guest's SMU is Apple's dummy back end, so nothing has. RLC_GPM_STAT bits 1, 2 and 4
    // are GFX_POWER_STATUS, GFX_CLOCK_STATUS and GFX_PIPELINE_POWER_STATUS.
    {
        auto rd = reinterpret_cast<const uint32_t *>(kMecFw);
        RLOG("XP: ucode readback at fb+%#llx: %08x %08x %08x %08x (want %08x %08x %08x %08x)",
             kMecFwFbOffset, fb[kMecFwFbOffset / 4], fb[kMecFwFbOffset / 4 + 1],
             fb[kMecFwFbOffset / 4 + 2], fb[kMecFwFbOffset / 4 + 3],
             rd[0], rd[1], rd[2], rd[3]);
        uint32_t pg = fbRead(asicInfo, kGcRlcPgCntl), gpm = fbRead(asicInfo, kGcRlcGpmStat);
        RLOG("XP: RLC_PG_CNTL=%#x (gfx_pg_en=%u cp_pg_disable=%u) RLC_GPM_STAT=%#x "
             "(gfx_power=%u gfx_clock=%u pipeline_power=%u) CGCG=%#x", pg, pg & 1,
             (pg >> 15) & 1, gpm, (gpm >> 1) & 1, (gpm >> 2) & 1, (gpm >> 4) & 1,
             fbRead(asicInfo, kGcRlcCgcg));
        // Turn graphics power gating off the only way available without an SMU: clear the
        // RLC's own enables and set PG_OVERRIDE with CP_PG_DISABLE.
        fbWrite(asicInfo, kGcRlcPgCntl, (1u << 14) | (1u << 15));
        fbWrite(asicInfo, kGcRlcCgcg, 0);
        IODelay(100);
        RLOG("XP: after PG override: RLC_PG_CNTL=%#x RLC_GPM_STAT=%#x",
             fbRead(asicInfo, kGcRlcPgCntl), fbRead(asicInfo, kGcRlcGpmStat));
    }
    uint32_t oldLo = fbRead(asicInfo, kGcCpcIcBaseLo), oldHi = fbRead(asicInfo, kGcCpcIcBaseHi);

    // Now do the rest of what gfx_v10_0_cp_compute_load_microcode does, in its order. The
    // base registers are locked, but everything else in that function is available and the
    // aperture move has already made the locked value correct:
    //
    //   1 halt the MECs (here the edge is wanted -- the cache is about to be repointed)
    //   2 CP_CPC_IC_OP_CNTL.INVALIDATE_CACHE, then poll INVALIDATE_CACHE_COMPLETE
    //   3 CP_CPC_IC_BASE_CNTL: VMID 0, CACHE_POLICY 0, EXE_DISABLE 0, ADDRESS_CLAMP 1
    //   4 the jump table into internal RAM: CP_MEC_ME1_UCODE_ADDR = 0, then jt_size dwords
    //     from the payload at jt_offset, then ADDR = the firmware's ucode_version
    //   5 unhalt
    //
    // The jump table is the part that was missing. For gc_10_3_6 it is 0xe0 dwords starting
    // at dword 0x1052c of the payload -- byte 0x414b0, which is exactly the size of Apple's
    // Navi 23 MEC blob, so Apple ships the microcode without a jump table and this file
    // carries both. Upstream loads MEC1's only: both engines fetch through the same
    // instruction cache base.
    // Which of the CP's control registers can this guest actually write? The instruction
    // cache base is known locked; if CP_MEC_CNTL is locked too then the engines cannot be
    // started from here at all and only the PSP can do it, which changes what the fix has to
    // be. Toggle one bit and put it back.
    {
        auto probe = [&](const char *name, uint32_t reg, uint32_t bit) {
            uint32_t was = fbRead(asicInfo, reg);
            fbWrite(asicInfo, reg, was ^ bit);
            uint32_t got = fbRead(asicInfo, reg);
            fbWrite(asicInfo, reg, was);
            RLOG("XP: writable? %-24s was %#x, toggled %#x -> %#x : %s", name, was, bit, got,
                 got != was ? "WRITABLE" : "LOCKED");
        };
        probe("CP_MEC_CNTL", kGcCpMecCntl, 1u << 28);
        probe("CP_ME_CNTL", kGcCpMeCntl, 1u << 28);
        probe("CP_CPC_IC_BASE_LO", kGcCpcIcBaseLo, 1u << 12);
        probe("CP_HQD_EOP_BASE_ADDR", kGcHqdEopBase, 1u);
        probe("CP_PQ_WPTR_POLL_CNTL", kGcCpPqWptrPoll, 1u);
        probe("SCRATCH_REG0 (control)", kGcScratch0, 1u);
    }
    fbWrite(asicInfo, kGcCpMecCntl, (1u << 30) | (1u << 28));
    IODelay(50);

    fbWrite(asicInfo, kGcCpcIcOpCntl, fbRead(asicInfo, kGcCpcIcOpCntl) | 1u);
    int inv = 0;
    for (; inv < 50000; inv++) {
        if ((fbRead(asicInfo, kGcCpcIcOpCntl) & 2u) != 0) break;
        IODelay(1);
    }
    uint32_t bc = fbRead(asicInfo, kGcCpcIcBaseCntl);
    bc &= ~0xfu;                    // VMID 0
    bc &= ~(1u << 23);              // EXE_DISABLE 0
    bc &= ~(3u << 24);              // CACHE_POLICY 0
    bc |=  (1u << 4);               // ADDRESS_CLAMP 1
    fbWrite(asicInfo, kGcCpcIcBaseCntl, bc);

    // Ask the instruction cache to prime itself from the address it is locked to.
    //
    // CP_CPC_IC_OP_CNTL has PRIME_ICACHE (bit 4) and ICACHE_PRIMED (bit 5) beside the
    // invalidate pair. This is the one direct test of whether the CP can fetch from
    // 0x85f904000 now that the aperture move has made that address land on microcode we
    // wrote and read back: priming completes only if the fetch works. If it primes, the
    // fetch path is fine and whatever stops the engines is elsewhere; if it never primes,
    // the address is still unreachable to the CP whatever the memory controller says.
    fbWrite(asicInfo, kGcCpcIcOpCntl, fbRead(asicInfo, kGcCpcIcOpCntl) | (1u << 4));
    int prime = 0;
    for (; prime < 50000; prime++) {
        if ((fbRead(asicInfo, kGcCpcIcOpCntl) & (1u << 5)) != 0) break;
        IODelay(1);
    }
    RLOG("XP: icache prime %s after %dus (op_cntl=%#x)",
         prime < 50000 ? "COMPLETED" : "never completed", prime,
         fbRead(asicInfo, kGcCpcIcOpCntl));

    auto jt = reinterpret_cast<const uint32_t *>(kMecFw) + kMecJtOffsetDwords;
    fbWrite(asicInfo, kGcMec1UcodeAddr, 0);
    for (uint32_t i = 0; i < kMecJtSizeDwords; i++) fbWrite(asicInfo, kGcMec1UcodeData, jt[i]);
    fbWrite(asicInfo, kGcMec1UcodeAddr, kMecFwVersion);
    RLOG("XP: icache invalidate took %dus (op_cntl=%#x); base_cntl %#x; jump table %u dwords "
         "from dword %#x written to MEC1 internal RAM", inv,
         fbRead(asicInfo, kGcCpcIcOpCntl), fbRead(asicInfo, kGcCpcIcBaseCntl),
         kMecJtSizeDwords, kMecJtOffsetDwords);

    // Unhalt: the engines start from their reset vector, and the cache now points at real
    // microcode.
    fbWrite(asicInfo, kGcCpMecCntl, 0);
    IODelay(500);

    uint32_t a = fbRead(asicInfo, kGcMec2InstrPntr), b = a;
    for (unsigned k = 0; k < 200 && b == a; k++) { IODelay(50); b = fbRead(asicInfo, kGcMec2InstrPntr); }
    RLOG("XP: MEC ucode %u bytes -> fb+%#llx (mc %#llx); IC base %#x_%08x -> %#x_%08x "
         "cntl=%#x; MEC2 instr %#x -> %#x, MEC1=%#x", kMecFwSize, kMecFwFbOffset, mcAddr,
         oldHi, oldLo, fbRead(asicInfo, kGcCpcIcBaseHi), fbRead(asicInfo, kGcCpcIcBaseLo),
         fbRead(asicInfo, kGcCpcIcBaseCntl), a, b, fbRead(asicInfo, kGcMec1InstrPntr));
}
#else
static void loadMecMicrocode() {}
#endif

// Does the command processor execute anything at all?
//
// With CP_CPC_STALLED_STAT1 withdrawn as evidence, the only trustworthy instruments left are
// the read pointer and the ring's contents -- and both are Apple's. So stop inferring and
// run a packet of our own choosing through the queue.
//
// PACKET3_WRITE_DATA with DST_SEL = memory and WR_CONFIRM stores one dword at an address of
// our choosing. Point it at a spare framebuffer page, zero that page first, put the packet
// at the head of a ring in VRAM, repoint the queue's GART PTE at it, ring the doorbell with
// the packet's dword count, and watch the page. If 0xcafebabe appears, the CP executes and
// the problem is somewhere in Apple's frame or its fence; if it never does, this queue does
// not run and nothing about Apple's software is implicated.
static constexpr uint64_t kProbeFbOffset = 0x0f110000;   // spare page, next to the ring copy
// The aperture window this plugin moves the framebuffer to, in the register's own 16 MB
// units, chosen so the locked CP_CPC_IC_BASE lands at kMecFwFbOffset.
static constexpr uint32_t kFbBaseWanted = 0x850;
static constexpr uint32_t kFbTopWanted  = 0x86f;

static void cpSelfTest() {
    auto fb = fbAperture();
    if (fb == nullptr || asicInfo == nullptr || hwObj == nullptr) return;
    uint64_t fbBase = static_cast<uint64_t>(fbRead(asicInfo, kGcFbBase) & 0xffffff) << 24;
    uint64_t probeVa = fbBase + kProbeFbOffset;
    fb[kProbeFbOffset / 4] = 0;

    // PACKET3(PACKET3_WRITE_DATA, 3), then control, addr_lo, addr_hi, data.
    //   header  = 0xC0000000 | (3 << 16) | (0x37 << 8)
    //   control = WRITE_DATA_DST_SEL(5) | WR_CONFIRM, engine ME
    const uint32_t pkt[] {
        0xc0033700u,
        (5u << 8) | (1u << 20),
        static_cast<uint32_t>(probeVa),
        static_cast<uint32_t>(probeVa >> 32),
        0xcafebabeu,
    };
    for (unsigned i = 0; i < sizeof(pkt) / 4; i++) fb[(kRingCopyFbOffset / 4) + i] = pkt[i];
    for (unsigned i = sizeof(pkt) / 4; i < 0x400; i++)
        fb[(kRingCopyFbOffset / 4) + i] = 0x80000000u;   // PACKET2 nops

    relocateRingToVram();   // repoints the ring PTE at kRingCopyFbOffset and invalidates

    auto dbBase = *reinterpret_cast<volatile uint64_t **>(
                      reinterpret_cast<uint8_t *>(hwObj) + 0x528);
    if (dbBase == nullptr) { RLOG("XP: no doorbell mapping"); return; }
    dbBase[0] = sizeof(pkt) / 4;
    RLOG("XP: self-test: wrote WRITE_DATA(%#llx <- 0xcafebabe) at fb+%#llx, rang %zu dwords",
         probeVa, kRingCopyFbOffset, sizeof(pkt) / 4);
    // Is the microengine executing at all? Sixteen samples of its instruction pointer over
    // a few hundred microseconds: a running engine moves, a stopped one does not. Two
    // samples 20 us apart, which is all the earlier probe took, cannot tell the difference.
    {
        uint32_t seen[16];
        for (unsigned i = 0; i < 16; i++) { seen[i] = fbRead(asicInfo, kGcMec2InstrPntr); IODelay(20); }
        unsigned distinct = 1;
        for (unsigned i = 1; i < 16; i++) if (seen[i] != seen[i - 1]) distinct++;
        RLOG("XP: IC bases: CPC=%#x_%08x cntl=%#x op=%#x | PFP=%#x_%08x | ME=%#x_%08x",
             fbRead(asicInfo, kGcCpcIcBaseHi), fbRead(asicInfo, kGcCpcIcBaseLo),
             fbRead(asicInfo, kGcCpcIcBaseCntl), fbRead(asicInfo, kGcCpcIcOpCntl),
             fbRead(asicInfo, kGcPfpIcBaseHi), fbRead(asicInfo, kGcPfpIcBaseLo),
             fbRead(asicInfo, kGcMeIcBaseHi), fbRead(asicInfo, kGcMeIcBaseLo));
        RLOG("XP: MEC2 instr pntr over 16 samples: %#x %#x %#x %#x ... %#x  (%u changes) "
             "MEC1=%#x CP_MEC_CNTL=%#x", seen[0], seen[1], seen[2], seen[3], seen[15],
             distinct - 1, fbRead(asicInfo, kGcMec1InstrPntr), fbRead(asicInfo, kGcCpMecCntl));
    }
    for (unsigned i = 0; i < 6; i++) {
        IODelay(1000);
        uint32_t got = fb[kProbeFbOffset / 4];
        RLOG("XP: +%ums: probe=%#x rptr=%#x wptr=%#x active=%u %s", i + 1, got,
             fbRead(asicInfo, kGcHqdPqRptr), fbRead(asicInfo, kGcHqdPqWptrLo),
             fbRead(asicInfo, kGcHqdActive) & 1,
             got == 0xcafebabeu ? "<-- THE CP EXECUTES" : "");
        if (got == 0xcafebabeu) break;
    }
}

static uint32_t wrapKiqSubmit(void *self) {
    // The VM fault status reads the same before and after the KIQ submit, so it is
    // latched from something earlier. Clear it first (FAULT_CNTL bit 0 is
    // CLEAR_PROTECTION_FAULT_STATUS_ADDR) so that whatever shows up afterwards is
    // definitely the command processor's.
    if (mask & XK) {
        uint32_t c = fbRead(asicInfo, kGcVmFaultCntl);
        fbWrite(asicInfo, kGcVmFaultCntl, c | 1u);
        fbWrite(asicInfo, kGcVmFaultCntl, c);
        RLOG("XK: cleared VM fault latch, status now %#x",
             fbRead(asicInfo, kGcVmFaultSts));
    }
    if (mask & XK) disableCtx0Retry();
    dumpGfxState("before KIQ submit");
    // Run the ring by hand BEFORE Apple submits, with both halves right.
    //
    // Ringing with 8 dwords after Apple has already rung with 0x20 proves nothing: by then
    // MEC2 has latched WAIT_ON_ROQ_DATA on the bogus dword-8 header and lowering the write
    // pointer does not retract that. So do it first -- put a ring in VRAM holding exactly
    // PACKET3(PACKET3_SET_RESOURCES, 6) and its seven payload dwords followed by PACKET2
    // no-ops, repoint the GART PTE at it, invalidate, and ring with 8. If the read pointer
    // then moves and CP_CPC_STALLED_STAT1 clears, the queue works and the problem is the
    // write pointer's unit; if it still sits, the packet is being fetched and ignored.
    if ((mask & XK) != 0 && hwObj != nullptr && asicInfo != nullptr) {
        fbWrite(asicInfo, kGcGrbmGfxCntl, kKiqSelector);
        cpSelfTest();
        fbWrite(asicInfo, kGcGrbmGfxCntl, 0);
    }
    auto r = FunctionCast(wrapKiqSubmit, orgKiqSubmit)(self);
    RLOG("XJ:   submitKIQFrame -> %u", r & 0xff);
    if (mask & XK) kickKiq(kiqEopHint);
    return r;
}

static const char *const kEngineNames[] {
    "PM4", "SDMA0", "SDMA1", "SDMA2", "SDMA3", "UVD0", "UVD1", "VCE", "VCN0", "VCN1", "SAMU",
};

// powerUpHWEngines walks [this + 8*i + 0x3b0] for i in 0..10 and calls each engine's
// vtable[0x138], bailing on the first failure -- and its failure message does not reach
// the serial console. Replicate the loop so every engine's result is logged. Skipping
// the original is deliberate: calling it as well would power each engine up twice. The
// only thing not reproduced is the progress-bitfield update at 0x6ff26, which is
// diagnostic.
// Start the RLC microcontroller.
//
// The KIQ submission times out, and the graphics core's own registers say why:
//     RLC_CNTL=0  RLC_STAT=0  RLC_GPM_STAT=0  RLC_RLCS_BOOTLOAD_STATUS=0
// RLC_CNTL bit 0 is RLC_ENABLE_F32, so the RLC's F32 microcontroller is simply not
// running -- and on GFX10 the command processor cannot execute a ring without it. The
// CP itself is fine: gc_unhalt_micro_engines_10_3 cleared the halt bits in CP_ME_CNTL
// and CP_MEC_CNTL (both read 0), and CP_CPF_STATUS goes to 0x88008001 once the doorbell
// is rung, so the fetcher does start -- it just never gets anywhere.
//
// Upstream sets this itself. gfx_v10_0_rlc_resume takes the autoload path only when
// psp.autoload_supported; otherwise it stops the RLC, clears RLC_CGCG_CGLS_CTRL and
// RLC_PG_CNTL, and calls gfx_v10_0_rlc_start, which is one field write:
//     WREG32_FIELD15(GC, 0, RLC_CNTL, RLC_ENABLE_F32, 1)
// Apple has _gc_unhalt_rlc_10_1 and _gc_setup_rlc_10_1 but no 10_3 equivalent, so on
// Navi 2x its GC path must be relying on the PSP autoloading and starting the RLC --
// which this PSP, loading each blob individually via LOAD_IP_FW, does not do.
//
// Do it here, before any engine powers up, which is upstream's order (rlc_resume runs
// ahead of cp_resume).
static void startRlc() {
    if (asicInfo == nullptr) { RLOG("XK: no register accessor yet"); return; }
    dumpGfxState("before RLC start");
    fbWrite(asicInfo, kGcRlcCgcg, 0);
    fbWrite(asicInfo, kGcRlcPgCntl, 0);
    uint32_t cntl = fbRead(asicInfo, kGcRlcCntl);
    fbWrite(asicInfo, kGcRlcCntl, cntl | 1u);
    IOSleep(1);
    RLOG("XK: RLC_CNTL %#x -> %#x", cntl, fbRead(asicInfo, kGcRlcCntl));
    // Control experiment: is the write path working at all? SCRATCH_REG0/1 are plain
    // read/write registers in the CP block. If these do not stick either, nothing in the
    // graphics domain is writable and the block is gated off -- which on an APU is the
    // SMU's doing, not the driver's.
    uint32_t s0 = fbRead(asicInfo, kGcScratch0);
    fbWrite(asicInfo, kGcScratch0, 0xa5a5a5a5u);
    uint32_t s0b = fbRead(asicInfo, kGcScratch0);
    fbWrite(asicInfo, kGcScratch0, s0);
    RLOG("XK: SCRATCH_REG0 %#x -> wrote 0xa5a5a5a5 -> %#x (%s)",
         s0, s0b, s0b == 0xa5a5a5a5u ? "writes work" : "WRITE DROPPED");

    // Clear the compute queues the host driver left running.
    //
    // Walking the MEC queues after the KIQ timeout found eight "active" HQD selectors,
    // every one of them reporting the same ring: pq_base 0xffbfea00, i.e. a ring at
    // 0xFFBFEA0000 -- outside this iGPU's 0xf400000000..0xf41fffffff carveout, and
    // exactly the address in the latched GCVM_L2_PROTECTION_FAULT_ADDR. That is amdgpu's
    // KIQ, in the host's GART, still mapped in the MEC from before the device was handed
    // to vfio-pci, now pointing at memory that no longer exists. Meanwhile
    // CP_MEC_ME1_HEADER_DUMP reads 0xdef1def1 -- MEC1 has never fetched a packet, so the
    // queue Apple's startKIQ set up is not the one running.
    //
    // Same shape as the stale PSP ring x7 destroys: this GPU is never reset, so whatever
    // the previous driver left behind is still live. Upstream clears it with one
    // register -- gfx_v10_0_cp_compute_enable(false) writes CP_MEC_CNTL (0x0f55 on
    // 10.3.x) with MEC_ME1_HALT | MEC_ME2_HALT, and (true) writes 0.
    // Halting the MEC is not enough: it stops the microengine but leaves the HQD
    // registers loaded, so CP_HQD_ACTIVE stays 1. The queue has to be dequeued, which is
    // what upstream does before writing a new MQD -- if CP_HQD_ACTIVE is set, write
    // CP_HQD_DEQUEUE_REQUEST and poll until it clears.
    //
    // First check that queue selection works at all. Eight selectors reporting byte-identical
    // HQD contents is equally consistent with "eight queues, all amdgpu's" and with
    // "GRBM_GFX_CNTL is not sticking and every read hits whichever queue is selected".
    // GRBM_GFX_CNTL may simply not read back, so test selection FUNCTIONALLY: park two
    // different values in a per-queue register under two different selectors and see
    // whether they stay apart. If they do not, every HQD access -- Apple's included --
    // is landing on whichever queue happens to be selected, which would explain both the
    // eight byte-identical "queues" and a KIQ that never runs.
    fbWrite(asicInfo, kGcGrbmGfxCntl, 0x0105u);
    uint32_t sel = fbRead(asicInfo, kGcGrbmGfxCntl);
    fbWrite(asicInfo, kGcGrbmGfxCntl, (0u) | (1u << 2) | (0u << 8));
    fbWrite(asicInfo, kGcHqdPqBase, 0xaaaaaaaau);
    fbWrite(asicInfo, kGcGrbmGfxCntl, (0u) | (1u << 2) | (1u << 8));
    fbWrite(asicInfo, kGcHqdPqBase, 0xbbbbbbbbu);
    fbWrite(asicInfo, kGcGrbmGfxCntl, (0u) | (1u << 2) | (0u << 8));
    uint32_t qa = fbRead(asicInfo, kGcHqdPqBase);
    fbWrite(asicInfo, kGcGrbmGfxCntl, (0u) | (1u << 2) | (1u << 8));
    uint32_t qb = fbRead(asicInfo, kGcHqdPqBase);
    fbWrite(asicInfo, kGcGrbmGfxCntl, 0);
    RLOG("XK: GRBM_GFX_CNTL readback %#x; per-queue test q0=%#x q1=%#x (%s)", sel, qa, qb,
         (qa == 0xaaaaaaaau && qb == 0xbbbbbbbbu) ? "SELECTION WORKS"
                                                 : "SELECTION BROKEN -- all queues alias");

    // Diagnostic only from here on. The dequeue loop that used to live here did clear
    // the eight queues TTL leaves behind, and the KIQ timed out exactly the same way
    // afterwards -- so they are not what blocks it. Worse, every dequeue reported
    // "active=1 after 2000us": CP_HQD_DEQUEUE_REQUEST is serviced by MEC firmware, so a
    // request that never retires is itself evidence that the microengine is not running.
    // That is what dumpCpUcode is here to settle.
    programL2LikeUpstream();
    loadMecMicrocode();
    startMecEngines();
    dumpMecQueues("post-TTL");
    dumpCpUcode("post-TTL");
    dumpGfxHubVm("post-TTL");
    dumpGfxState("after RLC start");
}

static uint32_t wrapHwEngPowerUp(void *self) {
    hwObj = self;
    if (mask & XK) startRlc();
    if ((mask & XJ) == 0 || self == nullptr)
        return FunctionCast(wrapHwEngPowerUp, orgHwEngPowerUp)(self);
    auto f = reinterpret_cast<uint8_t *>(self);
    uint32_t ok = 1;
    for (unsigned i = 0; i < 11; i++) {
        auto eng = *reinterpret_cast<void **>(f + 0x3b0 + 8 * i);
        if (eng == nullptr) continue;
        auto vt = *reinterpret_cast<uint64_t **>(eng);
        auto up = reinterpret_cast<uint32_t (*)(void *)>(vt[0x138 / 8]);
        uint32_t r = up(eng) & 0xff;
        RLOG("XJ:   engine %u %-5s at %p vtable=%p powerUp -> %u",
             i, kEngineNames[i], eng, reinterpret_cast<void *>(vt), r);
        if (!r) { ok = 0; break; }
    }
    RLOG("XJ: AMDHardware::powerUpHWEngines -> %u", ok);
    return ok;
}

static uint32_t wrapHwEngStart(void *self) {
    auto r = FunctionCast(wrapHwEngStart, orgHwEngStart)(self);
    RLOG("XJ: AMDHardware::startHWEngines -> %u", r & 0xff);
    return r;
}

static uint32_t wrapHwPowerUp(void *self) {
    uint8_t already = self ? *(reinterpret_cast<uint8_t *>(self) + 0x30f) : 0xff;
    auto r = FunctionCast(wrapHwPowerUp, orgHwPowerUp)(self);
    RLOG("XJ: AMDNavi23Hardware::powerUp -> %u (already-powered flag was %u)",
         r & 0xff, already);
    return r;
}

static uint32_t wrapAccPowerUpHW(void *self) {
    RLOG("XJ: AMDGraphicsAccelerator::powerUpHW entry");
    auto r = FunctionCast(wrapAccPowerUpHW, orgAccPowerUpHW)(self);
    RLOG("XJ: AMDGraphicsAccelerator::powerUpHW -> %u", r & 0xff);
    return r;
}

static uint32_t wrapHwMemEnable(void *self) {
    if (self != nullptr) {
        auto f = reinterpret_cast<uint8_t *>(self);
        auto q = [f](size_t o) { return *reinterpret_cast<uint64_t *>(f + o); };
        RLOG("XH: enableAllocations entry: pool0=%p pool1=%p size0=%#llx size1=%#llx "
             "base=%#llx",
             reinterpret_cast<void *>(q(0x68)), reinterpret_cast<void *>(q(0x70)),
             q(0x40), q(0x48), q(0x50));
    }
    auto r = FunctionCast(wrapHwMemEnable, orgHwMemEnable)(self);
    RLOG("XH: enableAllocations -> %u", r);
    return r;
}

//
// Clearing the flag alone is not enough. Apple's SKIP path returns kIOReturnUnsupported
// (0xe00002c7), and the accelerator's own progress bitfield shows that counts as a
// failure just as much as an error does:
//     ttlPowerUp           : 0     <- first thing to fail
//     accelPowerUpHW       : 0
//     hardwarePowerUp      : 0
//     powerUpHWEngines     : 0
//     startHWEngines       : 0
// and AMDHWMemory::enableAllocations is never reached at all -- which is the real reason
// the pools are empty, not the aperture and not the powerDown. So report success: the
// GPU on this part is powered and clocked by the platform SMU before macOS is even
// running, which is exactly what "powered up" has to mean here.
static uint32_t wrapPpPowerUp(void *self) {
    if ((mask & XI) == 0 || self == nullptr)
        return FunctionCast(wrapPpPowerUp, orgPpPowerUp)(self);
    auto flag = reinterpret_cast<uint8_t *>(self) + 0x28f8;
    uint8_t was = *flag;
    *flag = 0;
    auto r = FunctionCast(wrapPpPowerUp, orgPpPowerUp)(self);
    RLOG("XI: PowerPlay supported flag was %u -- cleared, powerUp returned %#x, "
         "reporting success so the accelerator powers its engines up", was, r);
    return 0;
}

// Soft-reset the command processor before TTL brings the graphics core up.
//
// Dequeuing amdgpu's leftover compute queues works -- and they come straight back. The
// MEC's hardware scheduler is still walking a runlist the host driver left in memory, so
// every queue it names is re-mapped as fast as it is torn down, and the queue Apple's
// startKIQ programs never gets to run (CP_MEC_ME1_HEADER_DUMP stays at its 0xdefNdefN
// fill pattern, so MEC1 fetches nothing). This GPU is never reset between the host driver
// and the guest one, which is the same root cause as the stale PSP ring and the stale
// UM ring, one block further in.
//
// Upstream's gfx_v10_0_soft_reset is block-scoped, not a device reset: halt the CP, pulse
// GRBM_SOFT_RESET with SOFT_RESET_CP | SOFT_RESET_GFX, release. Do it here, on the first
// AsicInfo refresh -- which runs before TTL::initialize -- so TTL's own GC hw_init loads
// and starts the CP afterwards, on a clean block. Doing it later would leave the CP
// reset with nobody to re-initialise it.
static bool cpResetDone = false;

static void softResetCp() {
    if (cpResetDone || asicInfo == nullptr) return;
    cpResetDone = true;
    uint32_t before = fbRead(asicInfo, kGcGrbmStatus);
    fbWrite(asicInfo, kGcCpMeCntl, (1u << 28) | (1u << 29) | (1u << 30));   // PFP/CE/ME halt
    fbWrite(asicInfo, kGcCpMecCntl, (1u << 30) | (1u << 28));               // MEC1/2 halt
    IOSleep(1);
    uint32_t rst = fbRead(asicInfo, kGcGrbmSoftReset);
    fbWrite(asicInfo, kGcGrbmSoftReset, rst | (1u << 0) | (1u << 16));      // CP | GFX
    IODelay(50);
    fbWrite(asicInfo, kGcGrbmSoftReset, rst);
    IODelay(50);
    fbWrite(asicInfo, kGcCpMeCntl, 0);
    fbWrite(asicInfo, kGcCpMecCntl, 0);
    IOSleep(1);
    RLOG("XK: CP soft reset: GRBM_STATUS %#x -> %#x, CP_ME_CNTL=%#x CP_MEC_CNTL=%#x",
         before, fbRead(asicInfo, kGcGrbmStatus), fbRead(asicInfo, kGcCpMeCntl),
         fbRead(asicInfo, kGcCpMecCntl));
    dumpMecQueues("after CP soft reset");
}

// Move the framebuffer aperture so the CP's locked instruction-cache address means something.
//
// CP_CPC_IC_BASE_LO/HI hold 0x8_5f904000 and cannot be written -- not through the
// framebuffer accessor, not through TTL's own _gc_cgs_write_register_ext2, not with
// GRBM_GFX_INDEX broadcasting, not in RLC safe mode, not with both MECs halted. It is
// locked for the life of the reset, which is exactly what one would expect of the register
// that decides which code the command processor executes. Meanwhile every GMC register
// tried IS writable: FB_LOCATION_BASE and TOP, the context-0 page-table bounds, the system
// aperture.
//
// So stop trying to point the register at the microcode and point the microcode at the
// register. MC-to-physical for the framebuffer aperture is
//
//     physical = MC - GCMC_VM_FB_LOCATION_BASE + GCMC_VM_FB_OFFSET
//
// with FB_OFFSET fixed at 0x840000000, the real carveout base, and BASE settable in 16 MB
// steps. Choosing BASE = 0x850000000 puts the locked address at aperture offset
// 0x85f904000 - 0x850000000 = 0x0f904000, i.e. 249 MB in -- inside the 256 MB BAR0 window,
// so the CPU can write it, and clear of both the page table at 0x0fdfc000 and everything
// Apple allocates lower down. TOP goes to BASE + 512 MB - 1.
//
// This has to happen before TTL::initialize, so that every address Apple and TTL derive is
// consistent with the new window -- which is why it runs from populateXGmiConfig, the same
// hook milestone xg already uses to read the aperture back. Apple programs the MMHUB copies
// of these registers, not the GFXHUB ones (that is why xg exists at all), so nothing
// downstream overwrites this.
static void relocateFbAperture() {
    if (asicInfo == nullptr) return;
    static bool done = false;
    if (done) return;
    done = true;

    uint32_t oldBase = fbRead(asicInfo, kGcFbBase) & 0xffffff;
    uint32_t oldTop  = fbRead(asicInfo, kGcFbTop) & 0xffffff;
    uint32_t oldOff  = fbRead(asicInfo, kGcFbOffset) & 0xffffff;
    if (oldBase == kFbBaseWanted) return;

    fbWrite(asicInfo, kGcFbBase, kFbBaseWanted);
    fbWrite(asicInfo, kGcFbTop, kFbTopWanted);
    // The system aperture marks which MC range bypasses the page tables; it is in 256 KB
    // units, so it has to follow the window rather than stay behind on the old one.
    fbWrite(asicInfo, kGcVmSysApLow, static_cast<uint32_t>(kFbBaseWanted) << 6);
    fbWrite(asicInfo, kGcVmSysApHigh, (static_cast<uint32_t>(kFbTopWanted) << 6) | 0x3f);
    RLOG("XP: FB aperture %#x..%#x (offset %#x) -> %#x..%#x; sys aperture %#x..%#x; "
         "locked IC base %#x lands at fb+%#llx",
         oldBase, oldTop, oldOff, fbRead(asicInfo, kGcFbBase) & 0xffffff,
         fbRead(asicInfo, kGcFbTop) & 0xffffff, fbRead(asicInfo, kGcVmSysApLow),
         fbRead(asicInfo, kGcVmSysApHigh), 0x5f904000u, kMecFwFbOffset);
}

static uint32_t wrapFbXgmiConfig(void *self) {
    asicInfo = self;
    if (mask & XL) relocateFbAperture();
    // NOT calling softResetCp() here. Tried it, and it costs the whole run: the block
    // reset takes GRBM_STATUS from 0x3028 (idle) to 0xa0003028 (CP_BUSY | GUI_ACTIVE)
    // and never settles, TTL's GC hw_init then times out in cosWaitForFunc, and
    // ttl_initialize fails 0x00000004 with SW_IP_CLIENT_ID__GC / EVENT__HW_INIT first
    // in the SWIP error log -- taking SMU and PSP uninit down with it. Upstream pulses
    // GRBM_SOFT_RESET only from inside RLC safe mode with the CP already halted and
    // re-initialised afterwards; a bare pulse here just wedges the block.
    //
    // The premise was wrong anyway. On a freshly booted host the pre-TTL walk reports
    // "no active compute queue on any MEC pipe", so the eight me2 HQDs at
    // pq_base=0xffbfea00 are not amdgpu's leftovers -- amdgpu does a MODE2 reset on
    // unbind and vfio-pci resets again on open. They appear during TTL's own GC hw_init.
    auto r = FunctionCast(wrapFbXgmiConfig, orgFbXgmiConfig)(self);
    if ((mask & XG) != 0 && self != nullptr) {
        auto f = reinterpret_cast<uint8_t *>(self);
        auto fld = [f](size_t o) -> uint32_t & {
            return *reinterpret_cast<uint32_t *>(f + o);
        };
        uint32_t gbase = fbRead(self, kGcFbBase)   & 0xffffff;
        uint32_t gtop  = fbRead(self, kGcFbTop)    & 0xffffff;
        uint32_t goff  = fbRead(self, kGcFbOffset) & 0xffffff;
        RLOG("XG: mmhub base=%#x top=%#x offset=%#x | gfxhub base=%#x top=%#x offset=%#x",
             fld(0x140), fld(0x144), fld(0x14c), gbase, gtop, goff);
        // Only override when the GFXHUB pair describes a real, non-empty range --
        // otherwise leave Apple's values alone and say so.
        if (gtop > gbase) {
            fld(0x140) = gbase;
            fld(0x144) = gtop;
            fld(0x14c) = goff;
            RLOG("XG: framebuffer aperture -> %#llx..%#llx (%llu MB)",
                 static_cast<uint64_t>(gbase) << 24,
                 (static_cast<uint64_t>(gtop) << 24) | 0xffffff,
                 ((static_cast<uint64_t>(gtop) + 1 - gbase) << 24) >> 20);
        } else {
            RLOG("XG: GFXHUB says top(%#x) <= base(%#x) -- leaving Apple's values alone",
                 gtop, gbase);
        }
    }
    return r;
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
        fbBase = addr;
        applyFor(patcher, false);
        if (mask & XI) {
            orgPpPowerUp = patcher.routeFunction(addr + kOffPpPowerUp,
                             reinterpret_cast<mach_vm_address_t>(wrapPpPowerUp), true);
            RLOG("route AmdPowerPlayHelper::powerUp -> %s (org=0x%llx)",
                 orgPpPowerUp ? "ok" : "FAILED", orgPpPowerUp);
            patcher.clearError();
        }
        if (mask & XG) {
            orgFbXgmiConfig = patcher.routeFunction(addr + kOffFbXgmiConfig,
                                reinterpret_cast<mach_vm_address_t>(wrapFbXgmiConfig), true);
            RLOG("route AmdAsicInfoNavi2::populateXGmiConfig -> %s (org=0x%llx)",
                 orgFbXgmiConfig ? "ok" : "FAILED", orgFbXgmiConfig);
            patcher.clearError();
        }
        // Both kexts are patched by now, so this is the moment to retry start().
        if (mask & P1) reprobeGpu();
    } else if (kexts[KextX6000].loadIndex == index) {
        RLOG("X6000 loaded, mask=0x%x", mask);
        if (mask & XH) {
            orgHwMemVram = patcher.routeFunction(addr + kOffHwMemVram,
                             reinterpret_cast<mach_vm_address_t>(wrapHwMemVram), true);
            RLOG("route AMDHWMemory::initVRAMInfo -> %s (org=0x%llx)",
                 orgHwMemVram ? "ok" : "FAILED", orgHwMemVram);
            patcher.clearError();
            orgHwMemEnable = patcher.routeFunction(addr + kOffHwMemEnable,
                               reinterpret_cast<mach_vm_address_t>(wrapHwMemEnable), true);
            RLOG("route AMDHWMemory::enableAllocations -> %s (org=0x%llx)",
                 orgHwMemEnable ? "ok" : "FAILED", orgHwMemEnable);
            patcher.clearError();
        }
        if (mask & XJ) {
            struct { size_t off; mach_vm_address_t *org; void *fn; const char *name; } t[] {
                {kOffAccPowerUpHW, &orgAccPowerUpHW,
                 reinterpret_cast<void *>(wrapAccPowerUpHW), "AMDGraphicsAccelerator::powerUpHW"},
                {kOffHwPowerUp, &orgHwPowerUp,
                 reinterpret_cast<void *>(wrapHwPowerUp), "AMDNavi23Hardware::powerUp"},
                {kOffHwEngPowerUp, &orgHwEngPowerUp,
                 reinterpret_cast<void *>(wrapHwEngPowerUp), "AMDHardware::powerUpHWEngines"},
                {kOffHwEngStart, &orgHwEngStart,
                 reinterpret_cast<void *>(wrapHwEngStart), "AMDHardware::startHWEngines"},
                {kOffPm4Mqd, &orgPm4Mqd,
                 reinterpret_cast<void *>(wrapPm4Mqd), "AMDGFX10PM4Engine::initComputeMQD"},
                {kOffKiqStart, &orgKiqStart,
                 reinterpret_cast<void *>(wrapKiqStart), "AMDGFX10KIQHWChannel::startKIQ"},
                {kOffPm4GfxMqd, &orgPm4GfxMqd,
                 reinterpret_cast<void *>(wrapPm4GfxMqd), "AMDGFX10PM4Engine::initGraphicsMQD"},
                {kOffKiqMapQ, &orgKiqMapQ,
                 reinterpret_cast<void *>(wrapKiqMapQ), "AMDGFX10KIQHWChannel::submitMapQueuesPacket"},
                {kOffKiqSubmit, &orgKiqSubmit,
                 reinterpret_cast<void *>(wrapKiqSubmit), "AMDKIQHWChannel::submitKIQFrame"},
                {kOffWaitStamp, &orgWaitStamp,
                 reinterpret_cast<void *>(wrapWaitStamp), "AMDHWChannel::waitForHwStamp"},
            };
            for (auto &e : t) {
                *e.org = patcher.routeFunction(addr + e.off,
                             reinterpret_cast<mach_vm_address_t>(e.fn), true);
                RLOG("route %s -> %s (org=0x%llx)", e.name, *e.org ? "ok" : "FAILED", *e.org);
                patcher.clearError();
            }
        }
    }
}

static void pluginStart() {
    if (!PE_parse_boot_argn("rgpu", &mask, sizeof(mask))) mask = 0;
    uint32_t d = 0;
    // Its own boot-arg rather than a mask bit: this is the one thing here that can take the
    // host with it, so it should not be reachable by editing a hex mask.
    uint32_t rst = 0;
    if (PE_parse_boot_argn("rgpureset", &rst, sizeof(rst)) && rst == 1) {
        pspResetRequested = true;
        RLOG("rgpureset=1: a PSP MODE1 reset will be issued before the PSP ring is created");
    }
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
