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

static KernelPatcher::KextInfo kextHWLibs {
    "com.apple.kext.AMDRadeonX6000HWLibs", pathHWLibs, arrsize(pathHWLibs),
    {}, {}, KernelPatcher::KextInfo::Unloaded
};
static KernelPatcher::KextInfo kextFB {
    "com.apple.kext.AMDRadeonX6000Framebuffer", pathFB, arrsize(pathFB),
    {}, {}, KernelPatcher::KextInfo::Unloaded
};

// ---- the patch table --------------------------------------------------------
// bit 0 = m1 ... bit 6 = m7, matching milestones.py

enum : uint32_t {
    M1 = 1u << 0,   // NBIF 7.3.0 + stop the PPLIB panic
    M2 = 1u << 1,   // MP0 13.0.5
    M3 = 1u << 2,   // SMUIO 13.0.10
    M4 = 1u << 3,   // GC 10.3.6
    M5 = 1u << 4,   // GMC/VM 10.3.6
    M6 = 1u << 5,   // UMC 9.5.0
    M7 = 1u << 6,   // ATHUB 2.4.1
};

struct RPatch {
    uint32_t bit;
    bool onHWLibs;              // false => Framebuffer
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
    {M1, true,  m1aF, m1aR, sizeof(m1aF), "m1 bif_ip_create: accept NBIF 7.3.0"},
    {M1, false, m1bF, m1bR, sizeof(m1bF), "m1 doGPUPanic: do not panic on TTL failure"},
    {M2, true,  m2F,  m2R,  sizeof(m2F),  "m2 mp0_ip_create: accept MP0 13.0.5"},
    {M3, true,  m3F,  m3R,  sizeof(m3F),  "m3 smuio_ip_create: accept SMUIO 13.0.10"},
    {M4, true,  m4F,  m4R,  sizeof(m4F),  "m4 gc dispatch: accept GC 10.3.6"},
    {M5, true,  m5F,  m5R,  sizeof(m5F),  "m5 vm mapping: 10.3.5 row -> 10.3.6"},
    {M6, true,  m6F,  m6R,  sizeof(m6F),  "m6 mc mapping: 10.0.0 row -> UMC 9.5.0"},
    {M7, true,  m7F,  m7R,  sizeof(m7F),  "m7 athub mapping: 2.4.0 -> 2.4.1"},
};

static uint32_t mask = 0;

static void applyFor(KernelPatcher &patcher, bool hwlibs) {
    for (auto &p : patches) {
        if (!(p.bit & mask) || p.onHWLibs != hwlibs) continue;
        KernelPatcher::LookupPatch lp {
            hwlibs ? &kextHWLibs : &kextFB, p.find, p.repl, p.size, 1
        };
        patcher.applyLookupPatch(&lp);
        auto err = patcher.getError();
        patcher.clearError();
        if (err == KernelPatcher::Error::NoError)
            SYSLOG("rgpu", "APPLIED  %s", p.what);
        else
            SYSLOG("rgpu", "FAILED(%d) %s", static_cast<int>(err), p.what);
    }
}

static void processKext(void *, KernelPatcher &patcher, size_t index,
                        mach_vm_address_t, size_t) {
    if (kextHWLibs.loadIndex == index) {
        SYSLOG("rgpu", "HWLibs loaded, mask=0x%x", mask);
        applyFor(patcher, true);
    } else if (kextFB.loadIndex == index) {
        SYSLOG("rgpu", "Framebuffer loaded, mask=0x%x", mask);
        applyFor(patcher, false);
    }
}

static void pluginStart() {
    if (!PE_parse_boot_argn("rgpu", &mask, sizeof(mask))) mask = 0;
    SYSLOG("rgpu", "start, patch mask=0x%x (%lu patches known)", mask, arrsize(patches));
    if (mask == 0) {
        SYSLOG("rgpu", "no rgpu= boot-arg, staying inert");
        return;
    }
    lilu.onKextLoadForce(&kextHWLibs);
    lilu.onKextLoadForce(&kextFB);
    lilu.onKextLoadForce(nullptr, 0, processKext, nullptr);
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
