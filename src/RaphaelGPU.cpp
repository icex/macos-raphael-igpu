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
#include "KiqAddresses.hpp"
#include "KiqQueuePreparation.hpp"
#include "GartAddresses.hpp"
#include "DiagnosticRecords.hpp"
#include "SdmaTopology.hpp"
#include "SdmaAddresses.hpp"
#include "GpuVmDiagnostics.hpp"
#include "ObservationBuffer.hpp"
#include "SubmissionTrace.hpp"
#include "EngineLifecycle.hpp"
#include "RecoveryReservation.hpp"
#if __has_include("BuildIdentity.hpp")
#include "BuildIdentity.hpp"
#else
#define RGPU_BUILD_ID "unidentified"
#endif

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
static rgpu::DiagnosticRecords<256, 512> diagnostics {};
// Candidate submission tracing can add at most 174 records: 64 ordinary, 32
// notable, 32 original summaries, 8 phase samples, 32 phase summaries and 6
// route/readiness records. 512 retains that bounded set alongside the existing
// VM/SDMA evidence budget.
static rgpu::DiagnosticRecords<rgpu::kCriticalRecordCapacity, 512> criticalRecords {};
static rgpu::SuccessRecordBudget waitStampRecordBudget {};
static rgpu::SuccessRecordBudget kiqSubmitRecordBudget {};
static rgpu::SuccessRecordBudget preClearFaultRecordBudget {};
static rgpu::ObservationBuffer<RaphaelVm::PreparedRequest, 8> vmid2Programs {};
static rgpu::ObservationBuffer<RaphaelSdma::SubmitInfoObservation, 8> vmid2Submits {};
static RaphaelSubmit::Store<64, 32> submissionTrace {};
static RaphaelSubmit::MapPhaseStore<RaphaelSubmit::MapSamplesPerPhase>
    submissionMapPhases {};
static volatile uint32_t nextSubmissionTraceSequence = 0;
static bool submissionTraceEnabled = false;
static volatile bool submissionTraceRoutesReady = false;
static bool vmRootFixEnabled = false;
static volatile bool raphaelTargetConfirmed = false;
// Published once by the early framebuffer callback and read later by the VM
// callback. Keeping this snapshot avoids MMIO under X6000's unknown VM locks.
static volatile uint32_t cachedFbBase = 0;
static volatile uint32_t cachedFbTop = 0;
static volatile uint32_t cachedFbOffset = 0;
static volatile bool cachedFbPublished = false;
static volatile uint32_t nextVmObservationSequence = 0;
static volatile uint32_t latestVmid2ProgramSequence = 0;

static void diagAppend(bool critical, const char *fmt, ...) {
    char text[512];
    va_list ap;
    va_start(ap, fmt);
    int n = vsnprintf(text, sizeof(text), fmt, ap);
    va_end(ap);
    if (n < 0) { text[0] = '\0'; }
    bool truncated = n < 0 || static_cast<size_t>(n) >= sizeof(text);
    diagnostics.append(text, truncated);
    if (critical) criticalRecords.append(text, truncated);
}

#define RLOG(fmt, ...) do { \
    diagAppend(false, fmt, ## __VA_ARGS__); \
    SYSLOG("rgpu", fmt, ## __VA_ARGS__); \
} while (0)
#define CRLOG(fmt, ...) do { \
    diagAppend(true, fmt, ## __VA_ARGS__); \
    SYSLOG("rgpu", fmt, ## __VA_ARGS__); \
} while (0)

static uint32_t diagDumpDelayMs = 75000;

// Ask the CP's instruction cache to prime itself, from boot-arg rgpuic=1, and nothing else.
// Separate from rgpucp, which bundles the prime with loadMecMicrocode() -- correct only
// under rgpufb=2, and wrong under the identity map, where the CP fetches from aperture
// offset 0x1f904000 and 0x0f904000 is an unrelated page.
static bool icachePrimeEnabled = false;

// Probe the RLC, from boot-arg rgpurlc=1.
//
// The RLC is the microcontroller that primes the CP instruction caches and releases the
// microengines on a healthy GFX10. Two facts point at it being the real blocker rather than
// the CP registers being locked, which may be the same thing seen from the other side:
//
//   - milestone xl exists because the driver writes RLC_SAFE_MODE and polls its command bit
//     for the RLC to clear it, and the RLC never does. On real silicon only a running RLC
//     clears that bit, so that is a positive liveness test with a negative result.
//   - RLC_STAT reads 0 in every run -- no RLC_BUSY, no RLC_GPM_BUSY, none of the three
//     thread bits -- while RLC_CNTL reads 0x1 (RLC_ENABLE) and the PSP reports
//     RLC_RLCS_BOOTLOAD_STATUS = 0xc0000001, autoload complete.
//
// So: firmware loaded, enable bit set, microcontroller apparently not running.
static bool rlcProbeEnabled = false;
// rgpurlc=2: additionally cycle RLC_ENABLE. Destructive -- see the comment at the cycle.
static bool rlcProbeEnabled2 = false;

// rgpuvmm: hook AMDHWVMM's channel setup. 1 = observe, 2 = also clear the guard.
//
// This is the panic that actually stops Metal, and it is our bug, not Apple's.
// WindowServer submits a command buffer, IOAccelCommandQueue reaches
// AMDAccelResource::BatchPrepareMappings, and AMDHWVMM::endVMPTUpdate dereferences NULL:
//
//     589ea: dec dword ptr [rdi + 0x3c]      nesting counter, work only when it hits 0
//     589f9: mov rdi, qword ptr [rdi + 0x28] the DMA paging channel  -> NULL
//     589fd: mov rax, qword ptr [rdi]        FAULT (panic RDI=0, CR2=0, +0x13)
//
// m_0x28 is written in exactly one place in the whole kext,
// AMDHWVMM::setMemoryAllocationsEnabled(true) at 0x579a3, right after it creates a channel
// and immediately before it casts the same pointer to AMDRadeonX6000_AMDDMAHWChannel and
// stores that at m_0x30. But the creation sits behind an idempotency guard:
//
//     57930: test esi, esi
//     57932: je   0x57a7b        enable == false -> teardown path
//     57938: cmp  qword ptr [rbx + 0x20], 0x0
//     5793d: jne  0x57ba8        m_0x20 already set -> SKIP creation entirely
//
// and AMDHWVMM::init also writes m_0x20, at 0x56db3, from IAMDHWInterface vtable slot
// 0x2d8 -- the same value it splatters across m_0x18, m_0x50, m_0x58, m_0x60, m_0x78 and
// m_0x80. On working hardware that call must return NULL at init time, leaving the guard
// open so setMemoryAllocationsEnabled builds the channel and sets m_0x20 itself at 0x5795c.
// If it returns non-NULL here, the guard closes and m_0x28 is never assigned.
//
// So: observe first (which of the two is happening), and only then decide.
static uint32_t vmmProbeMode = 0;

// rgpumem: 1 = report AMDHWMemory's pool state, 2 = also call enableAllocations().
//
// The accelerator's PerformanceStatisticsAccum shows the driver allocating happily in GART
// (gartUsedBytes ~4.8 MB, 19 surfaces, 105 textures, 4 2D contexts) while VRAM is flat zero:
//
//     vramFreeBytes = 0        inUseVidMemoryBytes = 0
//     HWChannel GFX  | Commands Submitted = 0, Completed = 0
//     HWChannel KIQ  | Commands Submitted = 0, Completed = 0
//     HWChannel SDMA0| Commands Submitted = 0, Completed = 0
//
// Not one command has ever reached any hardware channel, and the VRAM heap has no bytes in
// it. AMDHWMemory::enableAllocations (x6+0x52a1e) is what populates that heap and it is never
// called: the XH hook logs "initVRAMInfo" every boot but "enableAllocations entry" never
// appears, because it sits downstream of the ttlPowerUp failure.
//
// enableAllocations takes no arguments -- only `this` -- so it is graftable the same way
// setMemoryAllocationsEnabled was. But it gates on two POOL POINTERS:
//
//     52a2b: mov rdi, qword ptr [rdi + 0x68]   ; pool A, null-tested
//     52a38: cmp qword ptr [rbx + 0x70], 0x0   ; pool B, compared to 0
//
// and those have never been logged -- the XH hook's "pool0/pool1" are the SIZES at +0x40 and
// +0x48, which is a different thing. If the pool objects at +0x68/+0x70 are null because
// powerUp never built them, calling enableAllocations achieves nothing and the real fix is
// upstream. So mode 1 only reports, and mode 2 acts. Do not skip mode 1.
static uint32_t memProbeMode = 0;

// rgpuptb=1 retains the legacy post-invalidation root-register experiment.
// Mode 2 supplies the GC physical FB_OFFSET to HWLibs' native physical-base
// getter before it exports memory information and programs the GART. It changes
// only vm+0x210, with no direct PTB writes or global UMA classification changes.
// FB_LOCATION_BASE is logical MC; a non-SYSTEM PTB instead uses FB_OFFSET + offset.
static uint32_t ptbFixMode = 0;

// rgpumqd=0 reports; 1 retains the legacy post-timeout pointer repair experiment.
// Mode 2 validates and converts the MQD/EOP addresses before startKIQ, after a real
// dequeue. Apple programs the initial KIQ HQD directly; a stale MQD being continuously
// restored has not been demonstrated. The first submission is a 32-dword SET_RESOURCES
// frame, including its completion WRITE_DATA at dword 16.
static uint32_t mqdFixMode = 0;
static void *hwMemObject = nullptr;
static volatile uint32_t *fbAperture();
static uint32_t wrapHwMemEnable(void *self);

static void reportCpState(const char *when);
static void primeIcacheOnly();
static void probeRlc();
static void repairMqdPointers();
static bool prepareKiq(uint64_t &mqdAddr, uint64_t &eopAddr, const void *spec);
static void reportKiqPreparation(const char *stage);
static mach_vm_address_t orgVmmInit = 0;
static mach_vm_address_t orgVmmSetAlloc = 0;
static mach_vm_address_t orgVmmSetVSReady = 0;
static mach_vm_address_t orgHwMemSetVSReady = 0;
static mach_vm_address_t orgVmmFillRegs = 0;
static mach_vm_address_t orgVmmPrepare = 0;
static mach_vm_address_t orgVmmProgInv = 0;
static mach_vm_address_t orgProcessCommandBuffer = 0;
static mach_vm_address_t orgBatchPrepareMappings = 0;
static mach_vm_address_t orgBatchPrepare = 0;
static mach_vm_address_t orgBatchMemoryMapPrepare = 0;
static mach_vm_address_t orgSubmitBuffer = 0;
// Slide of AMDRadeonX6000, so a captured return address can be reported as a file offset
// that llvm-nm can name. Static analysis could not identify the caller of
// setMemoryAllocationsEnabled: it is a virtual call, and vtable slot 0x148 is used by
// AMDHWEngine, AMDHWChannel, AMDBltMgr and others, so "who calls [rax+0x148]" is unanswerable
// from the disassembly. The return address is unambiguous.
static mach_vm_address_t x6Base = 0;
static void *vmmObject = nullptr;
static void publishPendingVmObservations();

static void vmObservationThread(void *, wait_result_t) {
    // Driver hooks only copy small immutable structures into bounded buffers.
    // All formatting, serial output and MMIO happens here, outside unknown
    // caller lock contexts. The bounded experiment never exceeds 180 seconds.
    for (unsigned poll = 0; poll < 18000; ++poll) {
        publishPendingVmObservations();
        IOSleep(10);
    }
    thread_terminate(current_thread());
}

static void diagDumpThread(void *, wait_result_t) {
    // Tunable with the rgpudump=<ms> boot-arg: the whole AMD bring-up finishes well
    // before the default, and each iteration costs a boot, so this can be shortened once
    // you know how early the sequence completes on a given configuration.
    IOSleep(diagDumpDelayMs);
    // The prime runs HERE, not from startRlc.
    //
    // startRlc is called from inside TTL::initialize, and halting both MECs plus
    // invalidating the instruction cache at that point breaks the GC HW_INIT that comes
    // next: the run fills with "cosWaitForFunc: Timeout while waiting for function" and
    // never reaches the accelerator. That is the same failure softResetCp() caused from the
    // same hook. By the time this thread wakes, TTL has finished and the accelerator has
    // registered, so poking the CP can no longer derail bring-up -- and the engines have
    // never executed in any run, so there is nothing to interrupt.
    if (icachePrimeEnabled) { primeIcacheOnly(); reportCpState("after-prime"); }
    if (rlcProbeEnabled) { probeRlc(); reportCpState("after-rlc"); }
    SYSLOG("rgpu", "==== deferred diagnostics: %lu records ====", diagnostics.size());
    char text[512];
    for (size_t i = 0; i < diagnostics.size(); ++i) {
        if (diagnostics.read(i, text)) SYSLOG("rgpu", "d%03lu| %s", i, text);
    }
    SYSLOG("rgpu", "==== deferred diagnostics end (dropped=%llu truncated=%llu) ====",
           diagnostics.dropped(), diagnostics.truncated());
    // Replay only critical records. Native startup can finish after the first dump.
    // Immutable slots allow snapshots while callbacks append, without serial under
    // a lock. A pending reservation is retried at the next snapshot, never read.
    for (unsigned replay = 0; replay < 18; ++replay) {
        size_t count = criticalRecords.size();
        SYSLOG("rgpu", "RGPU_RECORDS build=%s count=%lu dropped=%llu truncated=%llu",
               RGPU_BUILD_ID, count, criticalRecords.dropped(), criticalRecords.truncated());
        for (size_t i = 0; i < count; ++i) {
            if (criticalRecords.read(i, text))
                SYSLOG("rgpu", "RGPU_EVENT build=%s seq=%lu %s", RGPU_BUILD_ID, i, text);
        }
        IOSleep(10000);
    }
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
static constexpr size_t kOffTtlHybrid = 0x9876b;       // _TtlCreateHybridEngine
static constexpr size_t kOffTtlAvailable = 0xafa40;    // _ttlIsHwAvailable (called, not routed)
static constexpr size_t kOffSdmaFindInstance = 0xa7312; // _IpiSdmaFindInstanceByEngineIndexAndType
static constexpr size_t kOffTtlSetDevCap = 0xaf02d;    // _ttlSetDeviceCapabilityEntry
static constexpr size_t kOffVmPhysicalFb = 0x33370;   // _vm_10_1_get_uma_physical_fb_offset
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
static constexpr size_t kOffGcCgsRead2     = 0xb598;   // _gc_cgs_read_register_ext2 (called only)
static constexpr size_t kOffGcCgsWrite2    = 0xb519;   // _gc_cgs_write_register_ext2
static constexpr size_t kOffGcCgsWrite     = 0xb4de;   // _gc_cgs_write_register
static constexpr size_t kOffGcCgsWriteExt  = 0xb4a0;   // _gc_cgs_write_register_ext

// AMDRadeonX6000Framebuffer, not HWLibs.
static constexpr size_t kOffFbXgmiConfig = 0x3b3e0;    // AmdAsicInfoNavi2::populateXGmiConfig [fb]
static constexpr size_t kOffPpPowerUp    = 0x101a0;    // AmdPowerPlayHelper::powerUp [fb]

// AMDRadeonX6000, the accelerator.
static constexpr size_t kOffHwMemVram   = 0x527a4;    // AMDHWMemory::initVRAMInfo [x6]
static constexpr size_t kOffHwMemEnable = 0x52a1e;    // AMDHWMemory::enableAllocations [x6]
static constexpr size_t kOffVmmInit     = 0x56d3a;    // AMDHWVMM::init [x6]
static constexpr size_t kOffVmmSetAlloc = 0x5791e;    // AMDHWVMM::setMemoryAllocationsEnabled [x6]
static constexpr size_t kOffVmmSetVSReady = 0x578ce;  // AMDHWVMM::setVirtualSpaceReady [x6]
static constexpr size_t kOffHwMemSetVSReady = 0x52c3a; // AMDHWMemory::setVirtualSpaceReady [x6]
static constexpr size_t kOffVmmFillRegs = 0x62400;    // AMDGFX10VMM::fillVMRegisters [x6]
static constexpr size_t kOffVmmPrepare  = 0x6249c;    // __ZN26AMDRadeonX6000_AMDGFX10VMM26prepareVMInvalidateRequestEP25AMD_VM_INVALIDATE_REQUESTPK22AMD_VM_INVALIDATE_INFOb [x6]
static constexpr size_t kOffVmmProgInv  = 0x6278a;    // AMDGFX10VMM::programAndInvalidateVM [x6]
static constexpr size_t kOffAccPowerUpHW = 0x4e0c;   // AMDGraphicsAccelerator::powerUpHW [x6]
static constexpr size_t kOffHwPowerUp    = 0x99618;  // AMDNavi23Hardware::powerUp [x6]
static constexpr size_t kOffGfx10PowerUp = 0x73e68;  // AMDGFX10Hardware::powerUp [x6]
static constexpr size_t kOffGfx10SetVMRegs = 0x74320; // AMDGFX10Hardware::setVMRegisters [x6]
static constexpr size_t kOffHwEngInit    = 0x6fd4e;  // AMDHardware::initializeHWEngines [x6]
static constexpr size_t kOffHwEngPowerUp = 0x6fe9a;  // AMDHardware::powerUpHWEngines [x6]
static constexpr size_t kOffHwEngPowerOff = 0x6ff58; // AMDHardware::powerOffHWEngines [x6]
static constexpr size_t kOffHwEngStart   = 0x6ffd2;  // AMDHardware::startHWEngines [x6]
static constexpr size_t kOffHwEngStop    = 0x70086;  // AMDHardware::stopHWEngines [x6]
static constexpr size_t kOffHwPowerOff   = 0x70360;  // __ZN26AMDRadeonX6000_AMDHardware8powerOffEv [x6]
static constexpr size_t kOffHwGetChannel = 0x7097c;  // __ZN26AMDRadeonX6000_AMDHardware12getHWChannelE20_eAMD_HW_ENGINE_TYPE18_eAMD_HW_RING_TYPE [x6]
static constexpr size_t kOffSdmaCommitIb = 0x66e06; // __ZN34AMDRadeonX6000_AMDGFX10SDMAChannel27commitIndirectCommandBufferEP30AMD_SUBMIT_COMMAND_BUFFER_INFO [x6]
static constexpr size_t kOffPm4Mqd       = 0x69362;  // AMDGFX10PM4Engine::initComputeMQD [x6]
static constexpr size_t kOffKiqStart     = 0x8e670;  // AMDGFX10KIQHWChannel::startKIQ [x6]
static constexpr size_t kOffPm4GfxMqd    = 0x6952a;  // AMDGFX10PM4Engine::initGraphicsMQD [x6]
static constexpr size_t kOffKiqMapQ      = 0x8e45e;  // AMDGFX10KIQHWChannel::submitMapQueuesPacket [x6]
static constexpr size_t kOffKiqSubmit    = 0x5c716;  // AMDKIQHWChannel::submitKIQFrame [x6]
static constexpr size_t kOffWaitStamp    = 0x4c520;  // AMDHWChannel::waitForHwStamp [x6]
// Observation-only submission boundaries in the exact 24G830 X6000 image. Keep
// the full symbols here because BatchPrepare is a substring of BatchPrepareMappings.
static constexpr size_t kOffProcessCommandBuffer = 0x9ca6; // __ZN35AMDRadeonX6000_AMDAccelCommandQueue20processCommandBufferEjj [x6]
static constexpr size_t kOffBatchPrepareMappings = 0x18256; // __ZN31AMDRadeonX6000_AMDAccelResource20BatchPrepareMappingsEP37AMDRadeonX6000_AMDGraphicsAcceleratorPKPS_j [x6]
static constexpr size_t kOffBatchPrepare = 0x184d8; // __ZN31AMDRadeonX6000_AMDAccelResource12BatchPrepareEP37AMDRadeonX6000_AMDGraphicsAcceleratorPKPS_j [x6]
static constexpr size_t kOffBatchMemoryMapPrepare = 0x6550; // __ZN37AMDRadeonX6000_AMDGraphicsAccelerator21batchMemoryMapPrepareEP16IOAccelMemoryMap [x6]
static constexpr size_t kOffSubmitBuffer = 0xb83e; // __ZN30AMDRadeonX6000_AMDAccelChannel12submitBufferEP24IOAccelCommandDescriptor [x6]
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
static mach_vm_address_t orgVmPhysicalFb {};
static bool raphaelGcSeen = false; // original discovery version, before R1 remaps
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
static mach_vm_address_t orgGfx10PowerUp {};
static mach_vm_address_t orgGfx10SetVMRegs {};
static mach_vm_address_t orgHwEngInit {};
static mach_vm_address_t orgHwEngPowerUp {};
static mach_vm_address_t orgHwEngPowerOff {};
static mach_vm_address_t orgHwEngStart {};
static mach_vm_address_t orgHwEngStop {};
static mach_vm_address_t orgHwPowerOff {};
static mach_vm_address_t orgHwGetChannel {};
static mach_vm_address_t orgSdmaCommitIb {};
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
static bool sdmaTopologyEnabled = false;
static bool sdmaTopologyRoutesReady = false;
static void *sdmaTopologyOwner {};
// A GC context, captured from any TTL register write, so this plugin can use TTL's own
// register path (_gc_cgs_write_register_ext2) rather than only the framebuffer accessor.
static void *gcCtx {};
static bool nativeGcReadVerified = false;
// GRBM_GFX_CNTL readback is not a reliable queue identity. This shadow records
// only writes already made by the driver/plugin; it never programs the selector.
static uint32_t lastSelectorWrite = 0;
static void *lastSelectorContext = nullptr;
static bool lastSelectorWasNative = false, selectorWriteSeen = false;
static void noteSelectorWrite(void *ctx, uint32_t reg, uint32_t val, bool native);


// AmdRegisterAccess vtable: 0x138 writeReg32(index, value), 0x140 hwReadReg32(index).
static void fbWrite(void *self, uint32_t idx, uint32_t val) {
    if (self == nullptr) return;
    auto obj = *reinterpret_cast<void **>(reinterpret_cast<uint8_t *>(self) + 0x28);
    if (obj == nullptr) return;
    auto vt = *reinterpret_cast<uint64_t **>(obj);
    auto wr = reinterpret_cast<void (*)(void *, uint32_t, uint32_t)>(vt[0x138 / 8]);
    wr(obj, idx, val);
    noteSelectorWrite(nullptr, idx, val, false);
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
static constexpr uint32_t kGcVmInvCntl   = kGcSeg0 + 0x15c3;   // GCVM_INVALIDATE_CNTL
// SDMA0 shares GC segment zero. The generated header's byte base 0x4980 is
// kGcSeg0 in dwords, so these are the discovery-correct GC 10.3.6 indices.
static constexpr uint32_t kSdmaCntl       = kGcSeg0 + 0x001c;
static constexpr uint32_t kSdmaStatus0    = kGcSeg0 + 0x0025;
static constexpr uint32_t kSdmaStatus1    = kGcSeg0 + 0x0026;
static constexpr uint32_t kSdmaUcodeCsum  = kGcSeg0 + 0x0029;
static constexpr uint32_t kSdmaF32Cntl    = kGcSeg0 + 0x002a;
static constexpr uint32_t kSdmaStatus2    = kGcSeg0 + 0x0038;
static constexpr uint32_t kSdmaUtclCntl   = kGcSeg0 + 0x003c;
static constexpr uint32_t kSdmaUtclRd     = kGcSeg0 + 0x003e;
static constexpr uint32_t kSdmaUtclWr     = kGcSeg0 + 0x003f;
static constexpr uint32_t kSdmaRdXnack0   = kGcSeg0 + 0x0043;
static constexpr uint32_t kSdmaRdXnack1   = kGcSeg0 + 0x0044;
static constexpr uint32_t kSdmaWrXnack0   = kGcSeg0 + 0x0045;
static constexpr uint32_t kSdmaWrXnack1   = kGcSeg0 + 0x0046;
static constexpr uint32_t kSdmaUtclPage   = kGcSeg0 + 0x0048;
static constexpr uint32_t kSdmaStatus3    = kGcSeg0 + 0x004c;
static constexpr uint32_t kSdmaPageIbCntl = kGcSeg0 + 0x00e2;
static constexpr uint32_t kSdmaPageIbRptr = kGcSeg0 + 0x00e3;
static constexpr uint32_t kSdmaPageIbOff  = kGcSeg0 + 0x00e4;
static constexpr uint32_t kSdmaPageIbLo   = kGcSeg0 + 0x00e5;
static constexpr uint32_t kSdmaPageIbHi   = kGcSeg0 + 0x00e6;
static constexpr uint32_t kSdmaPageIbSize = kGcSeg0 + 0x00e7;
static constexpr uint32_t kSdmaPageCtx    = kGcSeg0 + 0x00e9;
static constexpr uint32_t kSdmaPageStatus = kGcSeg0 + 0x0100;
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
static constexpr uint32_t kGcVmCtx0StartHi = kGcSeg0 + 0x1688;
static constexpr uint32_t kGcVmCtx0End     = kGcSeg0 + 0x16a7;
static constexpr uint32_t kGcVmCtx0EndHi   = kGcSeg0 + 0x16a8;
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
static void reportCpState(const char *when);
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
static uint64_t prevRequestAddr = 0;
static uint32_t prevRequestSize = 0;

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
                // psp_gfx_resp is at +864: status, session, fw_addr_lo, fw_addr_hi, tmr_size.
                // Linux retains fw_addr for each successful LOAD_IP_FW as the firmware's
                // address inside TMR. Record it with the submitted source address/size; this
                // is placement evidence only and never dereferences protected TMR memory.
                const uint32_t st = prevCmdBuf[216];
                const uint64_t fwAddr = (static_cast<uint64_t>(prevCmdBuf[219]) << 32) |
                                        prevCmdBuf[218];
                RLOG("   resp cmd_id=%-3u wireType=%-3u status=0x%08x fw=0x%08x%08x "
                     "tmr_size=0x%x%s", prevWireCmd, prevWireType, st, prevCmdBuf[219],
                     prevCmdBuf[218], prevCmdBuf[220], st == 0 ? "" : "   <-- FAILED");
                if (prevWireCmd == 6)
                    RLOG("   LOAD_IP_FW type=%-3u source=0x%llx/0x%x -> tmr=0x%llx",
                         prevWireType, prevRequestAddr, prevRequestSize, fwAddr);
            }
            // Log addr/size for EVERY command, not just LOAD_IP_FW: LOAD_TOC (32) and
            // SETUP_TMR (5) carry them in the same places (+0x1c/+0x20 addr, +0x24 size),
            // and since LOAD_TOC is the first failure its arguments are what matter.
            uint32_t wireCmd = b[2];
            RLOG("cmd[%02u] wire=%-3u apple=%-2u type=%-3u addr=0x%08x%08x size=0x%-8x",
                 bufPrepCount, wireCmd, dw[0], wireCmd == 6 ? b[10] : 0,
                 b[8], b[7], b[9]);
            prevWireType = (wireCmd == 6) ? b[10] : 0;
            prevRequestAddr = (static_cast<uint64_t>(b[8]) << 32) | b[7];
            prevRequestSize = b[9];
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
// Everything that exists only to compensate for a command processor locked by the PSP is
// gated on this, and it is OFF by default.
//
// Those interventions were written against a device amdgpu had already claimed and released,
// where the microengines were dead and CP_CPC_IC_BASE pointed into the host's memory. On a
// device that reaches the guest as the system firmware left it, the PSP's own autoload has
// already run: the engines are live, the instruction-cache bases mean something, and
// BOOTLOAD_COMPLETE is genuinely set. Relocating the framebuffer aperture, reloading MEC
// microcode, rewriting GART entries and halting microengines underneath all of that is not
// just pointless there, it is a good way to hang the fabric -- and the host has hard-hung
// twice during this work with no evidence left behind.
//
// So: rgpucp=1 to get the workarounds back on a locked device, nothing by default.
static bool cpSurgeryEnabled = false;
static bool hybridProbeEnabled = false;
static mach_vm_address_t orgTtlHybrid {};
static mach_vm_address_t addrTtlAvailable {};
static mach_vm_address_t orgSdmaFindInstance {};
static mach_vm_address_t sdmaTraceBase {};
static size_t sdmaTraceSize {};

// Observe the native selector's actual return, only at the verified hybrid
// caller (HWLibs+0xa7a79). Its next instruction branches on a null instance.
// No extra selector calls, MMIO, queue changes, or fabricated success.
static void *wrapSdmaFindInstance(void *context, uint32_t index, uint32_t type) {
    auto caller = reinterpret_cast<mach_vm_address_t>(__builtin_return_address(0));
    void *instance = FunctionCast(wrapSdmaFindInstance, orgSdmaFindInstance)(context, index, type);
    static unsigned calls = 0;
    if (caller == sdmaTraceBase + 0xa7a79 && context &&
        __sync_fetch_and_add(&calls, 1u) < 8) {
        auto ctx = reinterpret_cast<const uint8_t *>(context);
        auto counts = reinterpret_cast<const uint32_t *>(ctx + 0x2c);
        uint32_t q0 = 0, q1 = 0, q2 = 0, occupied = 0;
        uint64_t callback = ~0ULL;
        if (instance) {
            auto selected = reinterpret_cast<const uint8_t *>(instance);
            auto queues = reinterpret_cast<const uint32_t *>(selected + 0x58);
            q0 = queues[0]; q1 = queues[1]; q2 = queues[2];
            occupied = (*reinterpret_cast<void *const *>(selected + 0x30) ? 1u : 0u) |
                       (*reinterpret_cast<void *const *>(selected + 0x48) ? 2u : 0u);
            auto function = *reinterpret_cast<const mach_vm_address_t *>(selected + 0x70);
            if (function >= sdmaTraceBase && function - sdmaTraceBase < sdmaTraceSize)
                callback = function - sdmaTraceBase;
        }
        CRLOG("HY: SDMA select index=%u queue-type=%u found=%u counts=%u,%u,%u,%u queues=%u,%u,%u occupied=%u callback=%#llx",
              index, type, instance != nullptr, counts[0], counts[1], counts[2], counts[3],
              q0, q1, q2, occupied, callback);
    }
    return instance;
}

// The availability helper is read-only in 24G830. Status 4 from the original
// create routine covers BOTH unavailable hardware and a failed GC/SDMA queue.
// Sample availability immediately before the native call; concurrent state can
// change before the original checks it. Never override it or write request/output.
static uint32_t wrapTtlHybrid(void *ttl, void *request, void *output) {
    static unsigned calls = 0;
    bool report = __sync_fetch_and_add(&calls, 1u) < 8;
    bool valid = ttl != nullptr && request != nullptr && output != nullptr;
    bool available = false;
    uint32_t engineType = 0xffffffffu;
    if (report && valid) {
        available = reinterpret_cast<bool (*)(void *)>(addrTtlAvailable)(ttl);
        if (available) engineType = *reinterpret_cast<const uint32_t *>(request);
        CRLOG("HY: createHybridEngine enter: engine=%u available=%u", engineType, available);
    }
    uint32_t result = FunctionCast(wrapTtlHybrid, orgTtlHybrid)(ttl, request, output);
    if (report) CRLOG("HY: createHybridEngine exit: engine=%u valid=%u available-before=%u status=%u",
                     engineType, valid, available, result);
    return result;
}

// Which framebuffer-aperture layout to program, from boot-arg rgpufb.
//
//   0  leave it exactly as Apple programmed it (default)
//   1  identity map: FB_LOCATION_BASE = FB_OFFSET, the host's own configuration
//   2  the old relocation, BASE = 0x850000000, which brings the locked IC base inside
//      BAR0 so loadMecMicrocode() can write microcode there (needs rgpucp=1 too)
//
// Its own boot-arg rather than a mask bit for the same reason as rgpucp: the mask is out of
// bits, and this changes where every GPU fabric master sends its reads.
static uint32_t fbApertureMode = 0;
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

// The trace uses the native read ABI at HWLibs0xb598: (ctx, reg, client, flag)
// forwards via [ctx+8]+0x118, replacing ctx with the callback cookie. Its entry
// bytes are checked at load; no new function route or trampoline is installed.
static void noteSelectorWrite(void *ctx, uint32_t reg, uint32_t val, bool native) {
    if (ptbFixMode != 2 || mqdFixMode != 2 || reg != kGcGrbmGfxCntl) return;
    lastSelectorWrite = val;
    lastSelectorContext = ctx;
    lastSelectorWasNative = native;
    selectorWriteSeen = true;
}

static void traceNativeKiqState(unsigned n, const char *stage, void *ctx,
                                uint32_t client, uint32_t flag) {
    auto nativeRead = reinterpret_cast<uint32_t (*)(void *, uint32_t, uint32_t, uint32_t)>(
        hwlibsBase + kOffGcCgsRead2);
    for (unsigned path = 0; path < 2; path++) {
        auto read = [=](uint32_t reg) {
            return path == 0 ? fbRead(asicInfo, reg) : nativeRead(ctx, reg, client, flag);
        };
        const uint32_t active = read(kGcHqdActive), error = read(kGcHqdError);
        const uint32_t eopLo = read(kGcHqdEopBase), eopHi = read(kGcHqdEopBaseHi);
        const uint32_t eopControl = read(kGcHqdEopControl);
        const uint32_t ptbLo = read(kGcVmCtx0PtbLo), ptbHi = read(kGcVmCtx0PtbHi);
        RLOG("XQ3: #%u %s %s ACTIVE=%#x ERROR=%#x EOP=%#x_%08x ctl=%#x PTB=%#x_%08x",
             n, stage, path == 0 ? "fb" : "gc", active, error, eopHi, eopLo,
             eopControl, ptbHi, ptbLo);
    }
}

static int beginNativeKiqTrace(void *ctx, uint64_t caller, uint32_t reg,
                               uint32_t val, uint32_t client, uint32_t flag) {
    if (ptbFixMode != 2 || mqdFixMode != 2) return -1;
    uint32_t expected = 0;
    switch (caller) {
        case 0x15253: expected = kGcHqdEopBase; break;
        case 0x1527b: expected = kGcHqdEopBaseHi; break;
        case 0x1533c: expected = kGcHqdEopControl; break;
        case 0x159e5: expected = kGcHqdActive; break;
        default: return -1;
    }
    // Eight native writes total, including rejected samples. Atomic reservation
    // keeps the logging/read budget bounded if two callers happen to overlap.
    static unsigned count = 0;
    if (__atomic_load_n(&count, __ATOMIC_RELAXED) >= 8) return -1;
    const unsigned n = __atomic_fetch_add(&count, 1, __ATOMIC_RELAXED);
    if (n >= 8) return -1;
    RLOG("XQ3: #%u caller=+%#llx reg=%#x val=%#x client=%#x flag=%#x",
         n, caller, reg, val, client, flag);
    RLOG("XQ3: #%u last selector write=%#x seen=%u native=%u sameCtx=%u",
         n, lastSelectorWrite, selectorWriteSeen, lastSelectorWasNative,
         lastSelectorContext == ctx);
    const void *callbacks = ctx == nullptr ? nullptr :
        *reinterpret_cast<void **>(reinterpret_cast<uint8_t *>(ctx) + 8);
    const bool hasRead = callbacks != nullptr &&
        *reinterpret_cast<void *const *>(reinterpret_cast<const uint8_t *>(callbacks) + 0x118);
    if (reg != expected || client != 0xb || flag != 1 || !nativeGcReadVerified ||
        !hasRead || asicInfo == nullptr || !selectorWriteSeen ||
        !lastSelectorWasNative || lastSelectorContext != ctx || lastSelectorWrite != kKiqSelector) {
        RLOG("XQ3: #%u snapshots skipped: expected=%#x nativeRead=%u callback=%u selector=%#x",
             n, expected, nativeGcReadVerified, hasRead, lastSelectorWrite);
        return -1;
    }
    traceNativeKiqState(n, "before", ctx, client, flag);
    return static_cast<int>(n);
}

// Keep the legacy XL halt experiment in modes0/1. Mode2 forwards the original
// halt bits, including failure cleanup. Run157's only observed halt interception
// occurred after the stamp timeout; it did not establish an initial-stall cause.
static uint32_t wrapGcCgsWrite(void *ctx, uint32_t reg, uint32_t val) {
    if ((mask & XL) != 0 && mqdFixMode != 2 && reg == kGcCpMecCntl && (val & ((1u << 28) | (1u << 30))) != 0) {
        static unsigned n = 0;
        if (n < 4) { n++; RLOG("XK: dropped MEC halt via write_register: %#x", val); }
        val &= ~((1u << 28) | (1u << 30));
    }
    auto r = FunctionCast(wrapGcCgsWrite, orgGcCgsWrite)(ctx, reg, val);
    noteSelectorWrite(ctx, reg, val, true);
    return r;
}
static uint32_t wrapGcCgsWriteExt(void *ctx, uint32_t reg, uint32_t val, uint32_t client) {
    if ((mask & XL) != 0 && mqdFixMode != 2 && reg == kGcCpMecCntl && (val & ((1u << 28) | (1u << 30))) != 0) {
        static unsigned n = 0;
        if (n < 4) { n++; RLOG("XK: dropped MEC halt via write_register_ext: %#x", val); }
        val &= ~((1u << 28) | (1u << 30));
    }
    auto r = FunctionCast(wrapGcCgsWriteExt, orgGcCgsWriteExt)(ctx, reg, val, client);
    noteSelectorWrite(ctx, reg, val, true);
    return r;
}

// Legacy modes suppress dequeue requests; mode2 requires genuine queue shutdown
// and observes the native EOP programming sequence without changing its writes.
static uint32_t wrapGcCgsWrite2(void *ctx, uint32_t reg, uint32_t val, uint32_t client,
                                uint32_t flag) {
    if (gcCtx == nullptr) gcCtx = ctx;
    const uint64_t caller = reinterpret_cast<uint64_t>(__builtin_return_address(0)) - hwlibsBase;
    const int trace = beginNativeKiqTrace(ctx, caller, reg, val, client, flag);
    // Compatibility experiment only; mode2 preserves native halt/unhalt ordering.
    if ((mask & XL) != 0 && mqdFixMode != 2 && reg == kGcCpMecCntl &&
        (val & ((1u << 28) | (1u << 30))) != 0) {
        static unsigned nh = 0;
        if (nh < 6) { nh++;
            RLOG("XK: legacy dropped CP_MEC_CNTL halt bits: %#x -> %#x",
                 val, val & ~((1u << 28) | (1u << 30)));
        }
        val &= ~((1u << 28) | (1u << 30));
        return FunctionCast(wrapGcCgsWrite2, orgGcCgsWrite2)(ctx, reg, val, client, flag);
    }
    if ((mask & XL) != 0 && mqdFixMode != 2 && reg == kGcHqdDequeue && val != 0) {
        static unsigned n = 0;
        if (n < 4) { n++;
            RLOG("XK: legacy dropped CP_HQD_DEQUEUE_REQUEST=%#x (client %#x)", val, client);
        }
        return 0;
    }
    auto r = FunctionCast(wrapGcCgsWrite2, orgGcCgsWrite2)(ctx, reg, val, client, flag);
    noteSelectorWrite(ctx, reg, val, true);
    if (trace >= 0) traceNativeKiqState(static_cast<unsigned>(trace), "after", ctx, client, flag);
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
    if (isHqd && mqdFixMode == 2) return r; // require genuine dequeue completion

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
        if (mqdFixMode != 2) dumpCpUcode("gc hw_init");
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


// Rewrite the versions in each ipconfig table ITSELF, every entry, before returning
// from the accessor. mc_sw_init does not use the accessor at all:
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
    if (ipconfig != nullptr) {
        auto base = static_cast<const uint8_t *>(ipconfig);
        uint32_t n = *reinterpret_cast<const uint32_t *>(base + 0x1c);
        if (!dumpedTable) RLOG("ipconfig table: %u entries", n);
        if (n <= 64) {
            for (uint32_t i = 0; i < n; i++) {
                auto e = base + 0x20 + static_cast<size_t>(i) * 0x260;
                if (*reinterpret_cast<const uint32_t *>(e) == 0x0b &&
                    *reinterpret_cast<const uint16_t *>(e + 0x08) == 10 &&
                    *reinterpret_cast<const uint16_t *>(e + 0x0c) == 3 &&
                    *reinterpret_cast<const uint16_t *>(e + 0x10) == 6)
                    raphaelGcSeen = true;
                if (!dumpedTable)
                    RLOG("  ip[%u] id=0x%x ver=%u.%u.%u", i,
                         *reinterpret_cast<const uint32_t *>(e + 0x00),
                         *reinterpret_cast<const uint16_t *>(e + 0x08),
                         *reinterpret_cast<const uint16_t *>(e + 0x0c),
                         *reinterpret_cast<const uint16_t *>(e + 0x10));
            }
        }
        dumpedTable = true;
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
//     [this+0x58] = s[0x18]   physical FB base (historically 0; corrected to 0x840000000)
//     [this+0x60] = base - physical FB base, computed at x6+0x52820..0x52823
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
    hwMemObject = self;
    RLOG("XH: initVRAMInfo -> %u  base(+50)=%#llx fbPhysical(+58)=%#llx delta(+60)=%#llx "
         "size0=%#llx size1=%#llx | poolA(0x68)=%#llx poolB(0x70)=%#llx",
         r, q(0x50), q(0x58), q(0x60), q(0x40), q(0x48), q(0x68), q(0x70));
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
    if (mqdFixMode == 2 && !prepareKiq(a, b, spec)) {
        RLOG("XQ2: startKIQ refused: preflight or genuine dequeue failed");
        return 0xe00002bc; // same failure used by Apple's startKIQ queue-spec check
    }
    auto r = FunctionCast(wrapKiqStart, orgKiqStart)(self, a, b, spec, out);
    RLOG("XJ:   PM4 startKIQ(%#llx, %#llx) -> %#x (0 is success)", a, b, r);
    if (mqdFixMode == 2) {
        fbWrite(asicInfo, kGcGrbmGfxCntl, kKiqSelector);
        reportKiqPreparation("after native startKIQ");
        fbWrite(asicInfo, kGcGrbmGfxCntl, 0);
    }
    // The old HQD experiment remains opt-in outside mode 2.
    if ((mask & XK) && cpSurgeryEnabled && mqdFixMode != 2) enableDoorbellMsg(a, b);
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

// Read-only report on the command processor. Never writes anything.
//
// The interventions are gated behind rgpucp now, and the diagnostics that told us whether
// the microengines were alive lived inside them -- so with the gate closed a run would say
// nothing at all about the one question that matters. This is those same reads with none of
// the writes, safe to call on a device the firmware still owns.
//
// What each line answers, on a virgin device:
//   IC bases      should point somewhere the PSP's own autoload chose, not into host memory
//   BOOTLOAD      should have bit 31 set for real, so the GC/SDMA gates pass without xl
//   MEC instr     movement across samples is the difference between a live engine and a
//                 parked one; two samples 20 us apart cannot tell them apart, sixteen can
//   FB location   the aperture as the firmware left it, before anything moves it
static void reportCpState(const char *when) {
    if (asicInfo == nullptr) return;
    RLOG("XR: %s: IC bases CPC=%#x_%08x cntl=%#x op=%#x | PFP=%#x_%08x | ME=%#x_%08x", when,
         fbRead(asicInfo, kGcCpcIcBaseHi), fbRead(asicInfo, kGcCpcIcBaseLo),
         fbRead(asicInfo, kGcCpcIcBaseCntl), fbRead(asicInfo, kGcCpcIcOpCntl),
         fbRead(asicInfo, kGcPfpIcBaseHi), fbRead(asicInfo, kGcPfpIcBaseLo),
         fbRead(asicInfo, kGcMeIcBaseHi), fbRead(asicInfo, kGcMeIcBaseLo));
    uint32_t bl = fbRead(asicInfo, kGcRlcBootStat);
    RLOG("XR: %s: BOOTLOAD 0x4e8d=%#x (complete=%u) 0x4e7e=%#x RLC_CNTL=%#x RLC_STAT=%#x "
         "RLC_SAFE_MODE=%#x", when, bl, (bl >> 31) & 1, fbRead(asicInfo, kGcRlcBootStatSc),
         fbRead(asicInfo, kGcRlcCntl), fbRead(asicInfo, kGcRlcStat),
         fbRead(asicInfo, kGcRlcSafeMode));
    uint32_t a[16];
    for (unsigned i = 0; i < 16; i++) { a[i] = fbRead(asicInfo, kGcMec2InstrPntr); IODelay(20); }
    unsigned moves = 0;
    for (unsigned i = 1; i < 16; i++) if (a[i] != a[i - 1]) moves++;
    RLOG("XR: %s: MEC2 instr %#x %#x %#x ... %#x (%u changes -> %s) MEC1=%#x CP_MEC_CNTL=%#x",
         when, a[0], a[1], a[2], a[15], moves,
         moves ? "EXECUTING" : "not executing", fbRead(asicInfo, kGcMec1InstrPntr),
         fbRead(asicInfo, kGcCpMecCntl));
    RLOG("XR: %s: CP_STAT=%#x CPC_STATUS=%#x CPC_STALLED=%#x CPF_BUSY=%#x | FB base=%#x "
         "top=%#x offset=%#x", when, fbRead(asicInfo, kGcCpStat),
         fbRead(asicInfo, kGcCpcStatus), fbRead(asicInfo, kGcCpcStalled1),
         fbRead(asicInfo, kGcCpfBusyStat), fbRead(asicInfo, kGcFbBase) & 0xffffff,
         fbRead(asicInfo, kGcFbTop) & 0xffffff, fbRead(asicInfo, kGcFbOffset) & 0xffffff);
}

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
    RLOG("XM: %s: INVALIDATE_ENG0 req=%#x ack=%#x sem=unread(acquire-risk)  "
         "L2_FAULT_CNTL=%#x",
         when, fbRead(asicInfo, kGcVmInvEng0Req), fbRead(asicInfo, kGcVmInvEng0Ack),
         fbRead(asicInfo, kGcVmFaultCntl));
}

static uint32_t wrapWaitStamp(void *self, uint32_t stamp) {
    uint64_t caller = reinterpret_cast<uint64_t>(__builtin_return_address(0)) - x6Base;
    auto r = FunctionCast(wrapWaitStamp, orgWaitStamp)(self, stamp);
    if (waitStampRecordBudget.take((r & 0xff) != 0, 8))
        CRLOG("XJ:   waitForHwStamp(%u) -> %u caller=x6+%#llx",
              stamp, r & 0xff, caller);
    // This native call can run while X6000 holds a spin lock. Large MMIO walks and
    // serial output here delayed the failure path until lck_spinlock_timeout fired,
    // obscuring the original KIQ timeout with a recursive trap. The critical record
    // is safe and sufficient in this context; collect wider state only from a later,
    // lock-free lifecycle hook or from the host after QEMU has stopped.
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

// BAR0 maps the visible portion of VRAM. The GART walker below converts a
// validated physical framebuffer root into an offset within this existing map.
static volatile uint32_t *fbAperture() {
    static void *cached {};
    auto result = RaphaelRecovery::establishBarMapping(
        cached, hwObj, hwMemObject, [](void *pci) -> void * {
            auto vt = *reinterpret_cast<uint64_t **>(pci);
            auto mapFn = reinterpret_cast<void *(*)(void *, uint32_t, uint32_t)>(
                vt[0x908 / 8]);
            auto map = mapFn(pci, 0x10, 0);
            if (map == nullptr) return nullptr;
            auto mvt = *reinterpret_cast<uint64_t **>(map);
            auto getVA = reinterpret_cast<uint64_t (*)(void *)>(mvt[0x118 / 8]);
            return reinterpret_cast<void *>(getVA(map));
        });
    switch (result.status) {
        case RaphaelRecovery::BarMappingStatus::OwnerUnavailable:
            RLOG("XN: BAR0 mapping unavailable: hardware owner absent");
            break;
        case RaphaelRecovery::BarMappingStatus::PciUnavailable:
            RLOG("XN: BAR0 mapping unavailable: PCI owner absent");
            break;
        case RaphaelRecovery::BarMappingStatus::MappingFailed:
            RLOG("XN: BAR0 map failed");
            break;
        case RaphaelRecovery::BarMappingStatus::Mapped:
            RLOG("XN: BAR0 mapped at %p", result.address);
            break;
        case RaphaelRecovery::BarMappingStatus::Cached:
            break;
    }
    return reinterpret_cast<volatile uint32_t *>(result.address);
}

// The recorded memory sizes bound the existing 256MiB BAR0 mapping; never infer
// that a full logical framebuffer aperture is CPU-visible.
static bool gartApertureInfo(RaphaelGart::Aperture &ap) {
    if (asicInfo == nullptr || hwMemObject == nullptr) return false;
    const uint32_t base = fbRead(asicInfo, kGcFbBase);
    const uint32_t top = fbRead(asicInfo, kGcFbTop);
    const uint32_t physical = fbRead(asicInfo, kGcFbOffset);
    if (((base | top | physical) & 0xff000000u) || base == 0 || physical == 0 || top < base)
        return false;
    auto memory = reinterpret_cast<const uint8_t *>(hwMemObject);
    const uint64_t size0 = *reinterpret_cast<const uint64_t *>(memory + 0x40);
    const uint64_t size1 = *reinterpret_cast<const uint64_t *>(memory + 0x48);
    if (size0 == 0 || size1 == 0) return false;
    uint64_t visible = RaphaelRecovery::barVisibleBytes(size0, size1);
    if (visible > 0x10000000ULL) visible = 0x10000000ULL;
    ap = {*reinterpret_cast<const uint64_t *>(memory + 0x50),
          *reinterpret_cast<const uint64_t *>(memory + 0x58),
          static_cast<uint64_t>(base) << 24,
          (static_cast<uint64_t>(top) << 24) | 0xffffffULL,
          static_cast<uint64_t>(physical) << 24, visible,
          *reinterpret_cast<const uint64_t *>(memory + 0x60),
          ptbFixMode == 2 ? RaphaelGart::MemoryForm::NativePhysical
                          : RaphaelGart::MemoryForm::LegacyRelocation};
    return true;
}

static bool gartRange(RaphaelGart::Range &range) {
    return RaphaelGart::rangeFromRegisters(fbRead(asicInfo, kGcVmCtx0Start),
        fbRead(asicInfo, kGcVmCtx0StartHi), fbRead(asicInfo, kGcVmCtx0End),
        fbRead(asicInfo, kGcVmCtx0EndHi), range);
}

// A flat non-SYSTEM root names physical framebuffer memory, not logical MC.
// No BAR0 access occurs until the complete table and requested VA are bounded.
static void walkGart(const char *what, uint64_t va) {
    if (asicInfo == nullptr) return;
    const uint64_t root = (static_cast<uint64_t>(fbRead(asicInfo, kGcVmCtx0PtbHi)) << 32) |
                           fbRead(asicInfo, kGcVmCtx0PtbLo);
    const uint32_t control = fbRead(asicInfo, kGcVmCtx0Cntl);
    RaphaelGart::Aperture aperture {};
    RaphaelGart::Range range {};
    uint64_t off = 0, idx = 0;
    if (!gartApertureInfo(aperture) || !gartRange(range) ||
        !RaphaelGart::pteOffset(aperture, range, control, root, va, off, idx)) {
        RLOG("XN: %s refused GART walk va=%#llx root=%#llx ctrl=%#x "
             "pages=%#llx..%#llx physicalFB=%#llx visible=%#llx", what, va, root,
             control, range.firstPage, range.lastPage, aperture.physicalBase, aperture.visibleBytes);
        return;
    }
    auto fb = fbAperture();
    if (fb == nullptr) return;
    const uint64_t pte = (static_cast<uint64_t>(fb[off / 4 + 1]) << 32) | fb[off / 4];
    RLOG("XN: %s va=%#llx idx=%#llx pte@fb+%#llx = %#llx -> pa %#llx flags%s%s%s%s%s",
         what, va, idx, off, pte, pte & 0x0000fffffffff000ULL,
         (pte & 1) ? " VALID" : " !VALID", (pte & 2) ? " SYSTEM" : "",
         (pte & 4) ? " SNOOPED" : "", (pte & 0x20) ? " READ" : "",
         (pte & 0x40) ? " WRITE" : "");
}

// HWLibs 0x33370 has a RIP-free 14-byte prologue and a void ABI. Its native UMA
// branch reads FB_OFFSET then stores vm+0x210. The active VM10.3.4 HW_INIT calls
// it at 0x33edc and exports that field at 0x33f0d, before native GART programming.
static void wrapVmPhysicalFb(void *vm) {
    const uint64_t caller = reinterpret_cast<uint64_t>(__builtin_return_address(0)) - hwlibsBase;
    FunctionCast(wrapVmPhysicalFb, orgVmPhysicalFb)(vm);
    static unsigned reports = 0;
    const bool report = reports++ < 8;
    if (ptbFixMode != 2 || !raphaelGcSeen || caller != 0x33ee1 || vm == nullptr ||
        asicInfo == nullptr) {
        if (report) RLOG("XT2: physical getter skipped: GC10.3.6=%u caller=+%#llx vm=%p asic=%p",
                         raphaelGcSeen, caller, vm, asicInfo);
        return;
    }
    auto fields = reinterpret_cast<uint8_t *>(vm);
    const uint64_t logical = *reinterpret_cast<const uint64_t *>(fields + 0x198);
    const uint64_t bytes = *reinterpret_cast<const uint64_t *>(fields + 0x1a0);
    auto physical = reinterpret_cast<uint64_t *>(fields + 0x210);
    const uint64_t before = *physical;
    const uint32_t base = fbRead(asicInfo, kGcFbBase), top = fbRead(asicInfo, kGcFbTop);
    const uint32_t offset = fbRead(asicInfo, kGcFbOffset);
    uint64_t desired = 0;
    const bool valid = RaphaelGart::physicalFbField(base, top, offset, logical, bytes, before, desired);
    if (valid) *physical = desired;
    if (report) RLOG("XT2: physical getter caller=+%#llx flags=%#x logical=%#llx size=%#llx "
                     "GC=%#x..%#x OFFSET=%#x native=%#llx -> %#llx %s", caller,
                     *reinterpret_cast<const uint32_t *>(fields + 0xc), logical, bytes,
                     base, top, offset, before, *physical, valid ? "validated" : "REJECTED");
}

static void reportGartRoot(const char *when) {
    if (asicInfo == nullptr) return;
    RaphaelGart::Aperture aperture {};
    RaphaelGart::Range range {};
    RaphaelGart::Table table {};
    const uint64_t root = (static_cast<uint64_t>(fbRead(asicInfo, kGcVmCtx0PtbHi)) << 32) |
                           fbRead(asicInfo, kGcVmCtx0PtbLo);
    const uint32_t control = fbRead(asicInfo, kGcVmCtx0Cntl);
    const bool valid = gartApertureInfo(aperture) && gartRange(range) &&
        RaphaelGart::physicalTable(aperture, range, control, root, table);
    RLOG("XT2: %s CTX0 root=%#llx ctrl=%#x pages=%#llx..%#llx",
         when, root, control, range.firstPage, range.lastPage);
    RLOG("XT2: physicalFB=%#llx table@BAR0+%#llx bytes=%#llx",
         aperture.physicalBase, table.offset, table.bytes);
    RLOG("XT2: field58=%#llx delta60=%#llx %s", aperture.field58, aperture.delta60,
         valid ? "physical table in bounds" : "unsupported or out of bounds");
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
    // CP_MQD_BASE_ADDR turns up in three different forms on this part, all naming the same
    // page, and only one of them is an MC address the GPU can use:
    //
    //     reserved + off = 0xebcb706000    what dumpMqd was handed
    //     base     + off = 0xf40b706000    what the per-queue walk logs (BAR-relative)
    //     fbHW     + off = 0x84b706000     the MC address, inside the framebuffer aperture
    //
    // Exactly the confusion that put a reserved-relative address in the page-table base
    // register. Accept any of the three, say which it was, and convert to a BAR0 offset so
    // the descriptor can actually be read -- previously this bailed with "outside BAR0" and
    // the MQD was never inspected once.
    uint64_t fbBase = static_cast<uint64_t>(fbRead(asicInfo, kGcFbBase) & 0xffffff) << 24;
    uint64_t swBase = 0, reserved = 0;
    if (hwMemObject != nullptr) {
        auto mf = reinterpret_cast<uint8_t *>(hwMemObject);
        swBase   = *reinterpret_cast<uint64_t *>(mf + 0x50);
        reserved = *reinterpret_cast<uint64_t *>(mf + 0x58);
    }
    uint64_t off;
    const char *form;
    if (swBase != 0 && mqdVa >= swBase)        { off = mqdVa - swBase;   form = "BAR-relative"; }
    else if (reserved != 0 && mqdVa >= reserved) { off = mqdVa - reserved; form = "reserved-relative"; }
    else if (mqdVa >= fbBase)                  { off = mqdVa - fbBase;   form = "MC"; }
    else { RLOG("XN: mqd %#llx below every known base (fb %#llx sw %#llx reserved %#llx)",
                mqdVa, fbBase, swBase, reserved); return; }
    RLOG("XN: mqd va=%#llx is %s, offset %#llx -> correct MC would be %#llx", mqdVa, form, off,
         fbBase + off);
    if (off + 0x800 > 0x10000000ULL) {
        RLOG("XN: mqd offset %#llx is outside the 256 MB BAR0 aperture", off); return;
    }
    auto d = [fb, off](uint32_t f) { return fb[(off + f) / 4]; };
    RLOG("XN: MQD@fb+%#llx: header=%#x mqd_base=%#x active=%#x vmid=%#x persistent=%#x",
         off, d(0x000), d(0x200), d(0x208), d(0x20c), d(0x210));
    RLOG("XN: MQD: pq_base=%#x rptr=%#x doorbell_ctl=%#x pq_control=%#x",
         d(0x220), d(0x228), d(0x23c), d(0x244));
    RLOG("XN: MQD: eop_base=%#x eop_control=%#x wptr_lo=%#x wptr_hi=%#x",
         d(0x294), d(0x29c), d(0x2d8), d(0x2dc));
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

// Observe the native frame without changing HQD contents or ringing a second doorbell.
static void kickKiq() {
    if (asicInfo == nullptr) return;
    fbWrite(asicInfo, kGcGrbmGfxCntl, kKiqSelector);
    RLOG("XK: KIQ observation: active=%u rptr=%#x wptr=%#x_%08x poll_addr=%#x_%08x "
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

    if (!cpSurgeryEnabled) return;   // never rewrite a live GPU's GART entries
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
    uint64_t caller = reinterpret_cast<uint64_t>(__builtin_return_address(0)) - x6Base;
    // The VM fault status reads the same before and after the KIQ submit, so it is
    // latched from something earlier. Clear it first (FAULT_CNTL bit 0 is
    // CLEAR_PROTECTION_FAULT_STATUS_ADDR) so that whatever shows up afterwards is
    // definitely the command processor's.
    if (mask & XK) {
        uint32_t c = fbRead(asicInfo, kGcVmFaultCntl);
        if (vmRootFixEnabled) {
            const uint32_t sequence = __atomic_load_n(
                &latestVmid2ProgramSequence, __ATOMIC_ACQUIRE);
            if (sequence != 0) {
                const uint32_t status = fbRead(asicInfo, kGcVmFaultSts);
                const uint64_t address = RaphaelVm::decodeFaultAddress(
                    fbRead(asicInfo, kGcVmFaultLo), fbRead(asicInfo, kGcVmFaultHi));
                if (preClearFaultRecordBudget.take(
                        status == 0, rgpu::kRoutinePreClearRecordLimit))
                    CRLOG("VM: pre-clear-fault seq=%u cntl=%#x status=%#x addr=%#llx",
                          sequence, c, status, address);
            }
        }
        fbWrite(asicInfo, kGcVmFaultCntl, c | 1u);
        fbWrite(asicInfo, kGcVmFaultCntl, c);
        RLOG("XK: cleared VM fault latch, status now %#x",
             fbRead(asicInfo, kGcVmFaultSts));
    }
    if (mask & XK) disableCtx0Retry();
    dumpGfxState("before KIQ submit");
    // Keep the legacy standalone CP test separate from mode 2. Apple's native frame
    // has 32 dwords: SET_RESOURCES, valid single-dword NOPs, and a stamp at dword 16.
    // Replacing its doorbell value with 8 would exclude the completion packet.
    if ((mask & XK) != 0 && hwObj != nullptr && asicInfo != nullptr) {
        fbWrite(asicInfo, kGcGrbmGfxCntl, kKiqSelector);
        if (cpSurgeryEnabled && mqdFixMode != 2) cpSelfTest();
        fbWrite(asicInfo, kGcGrbmGfxCntl, 0);
    }
    auto r = FunctionCast(wrapKiqSubmit, orgKiqSubmit)(self);
    if (kiqSubmitRecordBudget.take((r & 0xff) != 0, 8))
        CRLOG("XJ:   submitKIQFrame -> %u caller=x6+%#llx", r & 0xff, caller);
    if (mask & XK) kickKiq();
    if (mqdFixMode != 2) repairMqdPointers(); // mode 2 prepares before startKIQ
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
// Prime the CP instruction cache from the address it is locked to, and nothing else.
//
// Worth re-running under rgpufb=1 for a reason that did not hold before: the earlier attempt
// primed while CP_CPC_IC_BASE resolved to 0xff1c9f904000 -- nowhere -- so failing to prime
// proved only that the address was unreachable. Under the identity map the same register
// resolves to physical 0x8_5f904000, where the PSP's own autoloaded microcode is.
//
// Two controls, because the first version of this test proved nothing. It polled
// INVALIDATE_CACHE_COMPLETE while that bit was already set on entry (op_cntl = 0x2), so the
// loop exited at zero microseconds, and a prime that then failed could not be told apart
// from a register that ignores writes altogether:
//
//   writes-land   toggle a harmless CACHE_POLICY bit in BASE_CNTL and read it back
//   invalidate    clear the completion bit, confirm it reads clear, then command an
//                 invalidate and watch the bit come back -- proof the block executes
//                 commands at all
//
// Only with both established does "PRIME never completes" mean the fetch itself fails.
// Is a GC register actually writable? Toggle the given bits, read back, restore.
//
// Every "the guest cannot write X" claim in this project needs this, because a write that
// silently does nothing is indistinguishable from a write that never left the plugin. The
// controls that matter are the ones known to work: CP_MEC_CNTL and SCRATCH_REG0 both take
// writes, so a failure here is a property of the register, not of the access path.
static bool regWritable(const char *name, uint32_t reg, uint32_t xorMask) {
    uint32_t before = fbRead(asicInfo, reg);
    fbWrite(asicInfo, reg, before ^ xorMask);
    uint32_t during = fbRead(asicInfo, reg);
    fbWrite(asicInfo, reg, before);
    bool ok = (during != before);
    RLOG("XS:   %-22s %#010x ^%#010x -> %#010x  %s", name, before, xorMask, during,
         ok ? "WRITABLE" : "ignored");
    return ok;
}

static bool wrapVmmInit(void *self, void *hwIface, uint32_t flags) {
    auto r = FunctionCast(wrapVmmInit, orgVmmInit)(self, hwIface, flags);
    if (self != nullptr) {
        auto f = reinterpret_cast<uint8_t *>(self);
        auto q = [f](size_t o) { return *reinterpret_cast<void **>(f + o); };
        vmmObject = self;
        RLOG("XV: AMDHWVMM::init(iface=%p, flags=%u) -> %u | m_0x10=%p m_0x18=%p m_0x20=%p "
             "m_0x28=%p m_0x30=%p  [caller x6+%#llx]", hwIface, flags, r, q(0x10), q(0x18),
             q(0x20), q(0x28), q(0x30),
             reinterpret_cast<uint64_t>(__builtin_return_address(0)) - x6Base);
        if (q(0x20) != nullptr)
            RLOG("XV: m_0x20 is NON-NULL after init -- this is what closes the guard in "
                 "setMemoryAllocationsEnabled and leaves the DMA paging channel unbuilt");
    }
    return r;
}

// setVirtualSpaceReady is slot 0x140, immediately before setMemoryAllocationsEnabled at
// 0x148 in AMDHWVMM's vtable, so whatever brings virtual memory up is expected to call both.
// If this one arrives with true and the other never does, that is the ordering to graft onto:
// mode 3 calls setMemoryAllocationsEnabled(true) right here, which is late enough that the
// hardware interface is alive and early enough to beat WindowServer's first submission --
// the deferred diagnostic thread at T+40s is far too late, the guest has already panicked.
// AMDHWMemory::setVirtualSpaceReady is the memory-side twin of the VMM one that already
// proved graftable, and it is the natural place to enable allocations: by the time virtual
// space is ready the pools should exist. Report the pool pointers here, and only act on them
// under rgpumem=2.
// Legacy mode1 experiment, retained for reproducing previous runs. Its target
// uses logical FB_LOCATION_BASE and is valid only when that equals FB_OFFSET.
// Mode2 never invokes it: native HWLibs owns root programming and invalidation.
static bool repairPageTableBase(const char *when) {
    if (ptbFixMode == 2 || asicInfo == nullptr) return false;
    uint64_t fbHW  = static_cast<uint64_t>(fbRead(asicInfo, kGcFbBase) & 0xffffff) << 24;
    uint64_t fbTop = (static_cast<uint64_t>(fbRead(asicInfo, kGcFbTop) & 0xffffff) << 24)
                     | 0xffffffULL;
    uint32_t lo = fbRead(asicInfo, kGcVmCtx0PtbLo);
    uint32_t hi = fbRead(asicInfo, kGcVmCtx0PtbHi);
    uint64_t ptb = (static_cast<uint64_t>(hi) << 32) | lo;
    uint64_t flags = ptb & 0xfffULL;
    uint64_t addr = ptb & ~0xfffULL;

    // Historical reserved-relative heuristic. Do not use this path for the
    // relocated FB_LOCATION_BASE != FB_OFFSET configuration tested by mode2.
    if (hwMemObject == nullptr) {
        RLOG("XT: %s: CTX0 ptb=%#llx but AMDHWMemory has not been seen yet, so the VRAM "
             "offset cannot be derived -- needs the XH hook (rgpu mask bit xh) active", when,
             ptb);
        return false;
    }
    auto mf = reinterpret_cast<uint8_t *>(hwMemObject);
    uint64_t swBase   = *reinterpret_cast<uint64_t *>(mf + 0x50);
    uint64_t reserved = *reinterpret_cast<uint64_t *>(mf + 0x58);

    if (reserved == 0 || addr < reserved) {
        RLOG("XT: %s: ptb=%#llx reserved=%#llx -- not reserved-relative, leaving it alone",
             when, ptb, reserved);
        return false;
    }
    uint64_t off  = addr - reserved;
    uint64_t want = fbHW + off;
    bool addrOutside = (addr < fbHW || addr > fbTop);
    bool wantInside  = (want >= fbHW && want <= fbTop);
    bool baseMatches = (swBase - reserved) == fbHW;

    RLOG("XT: %s: ptb=%#llx addr=%#llx | sw base=%#llx reserved=%#llx base-reserved=%#llx "
         "(matches GFXHUB base %#llx: %u)", when, ptb, addr, swBase, reserved,
         swBase - reserved, fbHW, baseMatches);
    RLOG("XT: %s: VRAM offset=%#llx -> correct MC=%#llx | FB=%#llx..%#llx "
         "addr outside=%u want inside=%u", when, off, want, fbHW, fbTop, addrOutside,
         wantInside);

    if (!baseMatches || !addrOutside || !wantInside) {
        RLOG("XT: %s: leaving it alone -- the arithmetic does not support the repair", when);
        return false;
    }
    if (ptbFixMode < 1) {
        RLOG("XT: %s: would rewrite ptb %#llx -> %#llx (rgpuptb=1 to do it)", when, ptb,
             want | flags);
        return false;
    }
    uint64_t nv = want | flags;
    fbWrite(asicInfo, kGcVmCtx0PtbLo, static_cast<uint32_t>(nv));
    fbWrite(asicInfo, kGcVmCtx0PtbHi, static_cast<uint32_t>(nv >> 32));
    uint64_t rb = (static_cast<uint64_t>(fbRead(asicInfo, kGcVmCtx0PtbHi)) << 32) |
                   fbRead(asicInfo, kGcVmCtx0PtbLo);
    RLOG("XT: %s: rewrote CTX0 ptb %#llx -> %#llx, reads back %#llx %s", when, ptb, nv, rb,
         rb == nv ? "OK" : "MISMATCH (register refused the write)");
    return rb == nv;
}

// Convert one FB-resident pointer from BAR-relative to MC, guarded by the arithmetic.
// enc8 means the register stores the address shifted right by 8, as PQ_BASE and EOP_BASE do.
static bool fixFbPointer(const char *name, uint32_t regLo, uint32_t regHi, bool enc8,
                         uint64_t swBase, uint64_t fbHW, uint64_t fbTop, uint32_t *outLo,
                         uint32_t *outHi) {
    uint64_t enc = (static_cast<uint64_t>(fbRead(asicInfo, regHi)) << 32) |
                    fbRead(asicInfo, regLo);
    uint64_t addr = enc8 ? (enc << 8) : enc;
    if (addr == 0) { RLOG("XQ:   %-16s is 0, skipping", name); return false; }
    if (addr >= fbHW && addr <= fbTop) {
        RLOG("XQ:   %-16s %#llx is already an MC address, leaving it", name, addr);
        return false;
    }
    if (swBase == 0 || addr < swBase) {
        RLOG("XQ:   %-16s %#llx is neither MC nor BAR-relative (sw base %#llx), leaving it",
             name, addr, swBase);
        return false;
    }
    uint64_t want = addr - swBase + fbHW;
    if (want < fbHW || want > fbTop) {
        RLOG("XQ:   %-16s %#llx -> %#llx would fall outside %#llx..%#llx, leaving it",
             name, addr, want, fbHW, fbTop);
        return false;
    }
    uint64_t nenc = enc8 ? (want >> 8) : want;
    *outLo = static_cast<uint32_t>(nenc);
    *outHi = static_cast<uint32_t>(nenc >> 32);
    RLOG("XQ:   %-16s %#llx -> %#llx  (reg %#llx -> %#llx)", name, addr, want, enc, nenc);
    if (mqdFixMode < 1) return false;
    fbWrite(asicInfo, regLo, *outLo);
    fbWrite(asicInfo, regHi, *outHi);
    return true;
}

// Record queue-local errors as well as the pointers; clearing the hub's fault latch
// does not establish that an earlier PQ/TC UTCL1 error has retired.
static void reportKiqPreparation(const char *stage) {
    RLOG("XQ2: %s: ACTIVE=%#x RPTR=%#x WPTR=%#x_%08x HQD_ERROR=%#x "
         "DEQUEUE=%#x MQD=%#x_%08x EOP=%#x_%08x EOP_CONTROL=%#x", stage,
         fbRead(asicInfo, kGcHqdActive), fbRead(asicInfo, kGcHqdPqRptr),
         fbRead(asicInfo, kGcHqdPqWptrHi), fbRead(asicInfo, kGcHqdPqWptrLo),
         fbRead(asicInfo, kGcHqdError), fbRead(asicInfo, kGcHqdDequeue),
         fbRead(asicInfo, kGcMqdBaseHi), fbRead(asicInfo, kGcMqdBase),
         fbRead(asicInfo, kGcHqdEopBaseHi), fbRead(asicInfo, kGcHqdEopBase),
         fbRead(asicInfo, kGcHqdEopControl));
}

// Two phases: validate the complete one-page image before changing queue state, then
// require an inactive queue before changing the image and passing corrected arguments.
// startKIQ compares spec[0..2] with its returned ME/pipe/queue at x6+0x8e711..0x8e728;
// HWLibs create_kiq_queue_10_3 returns 2/1/0 on this part at +0x15114..0x1511c.
// Restrict this experiment to that proven selector rather than guessing from a queue walk.
static bool prepareKiq(uint64_t &mqdAddr, uint64_t &eopAddr, const void *spec) {
    if (asicInfo == nullptr || hwMemObject == nullptr || spec == nullptr) {
        RLOG("XQ2: preflight failed: missing ASIC, memory object, or queue spec");
        return false;
    }
    auto queue = static_cast<const uint32_t *>(spec);
    if (queue[0] != 2 || queue[1] != 1 || queue[2] != 0) {
        RLOG("XQ2: preflight failed: unsupported spec ME=%u pipe=%u queue=%u",
             queue[0], queue[1], queue[2]);
        return false;
    }
    auto fb = fbAperture();
    if (fb == nullptr) {
        RLOG("XQ2: preflight failed: BAR0 mapping unavailable");
        return false;
    }
    // Native +0x58 is the physical FB base exported by HWLibs, and +0x60
    // is base minus physical. It is not a queue-address relocation. The old
    // assumption remains isolated in the legacy form selected by ptb modes0/1.
    RaphaelGart::Aperture aperture {};
    RaphaelKiq::Addresses planned {};
    if (!gartApertureInfo(aperture) ||
        !RaphaelKiq::planAddresses(aperture, mqdAddr, eopAddr, planned)) {
        RLOG("XQ2: preflight failed: MQD=%#llx EOP=%#llx sw=%#llx field58=%#llx "
             "delta60=%#llx physicalFB=%#llx FB=%#llx..%#llx form=%s", mqdAddr,
             eopAddr, aperture.swBase, aperture.field58, aperture.delta60,
             aperture.physicalBase, aperture.mcBase, aperture.mcTop,
             ptbFixMode == 2 ? "native physical" : "legacy relocation");
        return false;
    }
    auto get = [fb, &planned](uint32_t byteOffset) {
        return fb[(planned.imageOffset + byteOffset) / 4];
    };
    uint64_t imageMqd = (static_cast<uint64_t>(get(0x204)) << 32) | get(0x200);
    uint64_t imageEop = (static_cast<uint64_t>(get(0x298)) << 32) | get(0x294);
    RaphaelKiq::Addresses imagePlan {};
    if (get(0) != 0xc0310800 || get(0x20c) != 0 || imageEop > 0xffffffffffULL ||
        !RaphaelKiq::planAddresses(aperture, imageMqd, imageEop << 8, imagePlan) ||
        imagePlan.mqdMc != planned.mqdMc || imagePlan.eopMc != planned.eopMc) {
        RLOG("XQ2: preflight failed: MQD image header=%#x VMID=%#x MQD=%#llx "
             "EOP(encoded)=%#llx disagrees with startKIQ", get(0), get(0x20c),
             imageMqd, imageEop);
        return false;
    }
    RLOG("XQ2: preflight OK: selector=%#x MQD=%#llx->%#llx EOP=%#llx->%#llx "
         "image=BAR0+%#llx fbPhysical=%#llx field58=%#llx delta60=%#llx form=%s",
         kKiqSelector, mqdAddr, planned.mqdMc, eopAddr, planned.eopMc, planned.imageOffset,
         aperture.physicalBase, aperture.field58, aperture.delta60,
         ptbFixMode == 2 ? "native physical" : "legacy relocation");

    fbWrite(asicInfo, kGcGrbmGfxCntl, kKiqSelector);
    reportKiqPreparation("before dequeue");
    auto queueReg = [](RaphaelKiq::QueueRegister reg) {
        switch (reg) {
            case RaphaelKiq::QueueRegister::Active: return kGcHqdActive;
            case RaphaelKiq::QueueRegister::Dequeue: return kGcHqdDequeue;
            case RaphaelKiq::QueueRegister::Rptr: return kGcHqdPqRptr;
            case RaphaelKiq::QueueRegister::WptrHi: return kGcHqdPqWptrHi;
            case RaphaelKiq::QueueRegister::WptrLo: return kGcHqdPqWptrLo;
            case RaphaelKiq::QueueRegister::Poll: return kGcCpPqWptrPoll;
            case RaphaelKiq::QueueRegister::Doorbell: return kGcHqdPqDbCtl;
        }
        return kGcHqdActive;
    };
    auto prepared = RaphaelKiq::prepareQueueForNativeStart(
        [=](RaphaelKiq::QueueRegister reg) { return fbRead(asicInfo, queueReg(reg)); },
        [=](RaphaelKiq::QueueRegister reg, uint32_t value) {
            fbWrite(asicInfo, queueReg(reg), value);
        },
        [](unsigned us) { IODelay(us); });
    reportKiqPreparation("after queue preparation");
    if (!prepared.ready()) {
        using Status = RaphaelKiq::QueuePreparationStatus;
        if (prepared.status == Status::DequeueTimeout) {
            CRLOG("XQ2: dequeue TIMEOUT after %u us; descriptor unchanged, startKIQ blocked",
                  prepared.elapsedUs);
        } else if (prepared.status == Status::Inaccessible) {
            CRLOG("XQ2: preparation refused: inaccessible queue registers");
        } else {
            CRLOG("XQ2: preparation refused: status=%u ACTIVE=%#x DEQUEUE=%#x "
                  "RPTR=%#x WPTR=%#x_%08x POLL=%#x DB=%#x",
                  static_cast<unsigned>(prepared.status), prepared.state.active,
                  prepared.state.dequeue, prepared.state.rptr, prepared.state.wptrHi,
                  prepared.state.wptrLo, prepared.state.poll, prepared.state.doorbell);
        }
        reportKiqPreparation("preparation refused");
        fbWrite(asicInfo, kGcGrbmGfxCntl, 0);
        return false;
    }
    if (prepared.elapsedUs != 0) {
        RLOG("XQ2: genuine dequeue completed after %u us", prepared.elapsedUs);
    }

    auto put = [fb, &planned](uint32_t byteOffset, uint32_t value) {
        fb[(planned.imageOffset + byteOffset) / 4] = value;
    };
    put(0x200, static_cast<uint32_t>(planned.mqdMc));
    put(0x204, static_cast<uint32_t>(planned.mqdMc >> 32));
    put(0x294, static_cast<uint32_t>(planned.eopMc >> 8));
    put(0x298, static_cast<uint32_t>(planned.eopMc >> 40));
    bool imageWritten = get(0x200) == static_cast<uint32_t>(planned.mqdMc) &&
        get(0x204) == static_cast<uint32_t>(planned.mqdMc >> 32) &&
        get(0x294) == static_cast<uint32_t>(planned.eopMc >> 8) &&
        get(0x298) == static_cast<uint32_t>(planned.eopMc >> 40);
    fbWrite(asicInfo, kGcGrbmGfxCntl, 0);
    if (!imageWritten) {
        RLOG("XQ2: MQD image readback failed; startKIQ blocked");
        return false;
    }
    mqdAddr = planned.mqdMc;
    eopAddr = planned.eopMc;
    RLOG("XQ2: preparation complete after %u us; calling native startKIQ with MC pointers",
         prepared.elapsedUs);
    return true;
}

// Legacy mode-1 experiment, retained separately from mode-2 preparation.
static void repairMqdPointers() {
    if (mqdFixMode == 2) return;
    auto fb = fbAperture();
    if (fb == nullptr || asicInfo == nullptr || hwMemObject == nullptr) {
        RLOG("XQ: cannot run -- fb=%s asicInfo=%p hwMem=%p", fb ? "ok" : "null",
             asicInfo, hwMemObject);
        return;
    }
    auto mf = reinterpret_cast<uint8_t *>(hwMemObject);
    uint64_t swBase = *reinterpret_cast<uint64_t *>(mf + 0x50);
    uint64_t fbHW   = static_cast<uint64_t>(fbRead(asicInfo, kGcFbBase) & 0xffffff) << 24;
    uint64_t fbTop  = (static_cast<uint64_t>(fbRead(asicInfo, kGcFbTop) & 0xffffff) << 24)
                      | 0xffffffULL;

    uint32_t sel = fbRead(asicInfo, kGcGrbmGfxCntl);
    fbWrite(asicInfo, kGcGrbmGfxCntl, kKiqSelector);
    IODelay(20);

    RLOG("XQ: repairing KIQ HQD pointers (sw base %#llx, FB %#llx..%#llx)%s", swBase, fbHW,
         fbTop, mqdFixMode < 1 ? "  [report only, rgpumqd=1 to apply]" : "");

    uint32_t mLo = 0, mHi = 0, eLo = 0, eHi = 0;
    bool mqdFixed = fixFbPointer("MQD_BASE", kGcMqdBase, kGcMqdBaseHi, false, swBase, fbHW,
                                 fbTop, &mLo, &mHi);
    bool eopFixed = fixFbPointer("EOP_BASE", kGcHqdEopBase, kGcHqdEopBaseHi, true, swBase,
                                 fbHW, fbTop, &eLo, &eHi);

    // Keep the image consistent with any legacy register repair. This does not prove
    // that the initial KIQ HQD is automatically restored from its MQD.
    uint64_t mqdEnc = (static_cast<uint64_t>(fbRead(asicInfo, kGcMqdBaseHi)) << 32) |
                       fbRead(asicInfo, kGcMqdBase);
    uint64_t imgOff = (mqdEnc >= fbHW && mqdEnc <= fbTop) ? mqdEnc - fbHW
                    : (swBase != 0 && mqdEnc >= swBase) ? mqdEnc - swBase : ~0ULL;
    if (imgOff == ~0ULL || imgOff + 0x800 > 0x10000000ULL) {
        RLOG("XQ: MQD image at %#llx is not reachable through BAR0, image left alone", mqdEnc);
    } else if (mqdFixMode >= 1) {
        auto put = [fb, imgOff](uint32_t f, uint32_t v) { fb[(imgOff + f) / 4] = v; };
        auto get = [fb, imgOff](uint32_t f) { return fb[(imgOff + f) / 4]; };
        RLOG("XQ: MQD image at fb+%#llx before: mqd_base=%#x_%08x eop_base=%#x_%08x",
             imgOff, get(0x204), get(0x200), get(0x298), get(0x294));
        if (mqdFixed) { put(0x200, mLo); put(0x204, mHi); }

        // Repair EOP from the IMAGE, not the register.
        //
        // CP_HQD_EOP_BASE_ADDR reads 0 while the image holds 0xf40b7068 (<<8 =
        // 0xf40b706800, BAR-relative), so the register-driven path above skips it. A zero
        // register with a non-zero image is the measured EOP programming discrepancy;
        // its cause has not been established by this post-timeout experiment.
        uint64_t iEnc = (static_cast<uint64_t>(get(0x298)) << 32) | get(0x294);
        uint64_t iAddr = iEnc << 8;
        if (iAddr != 0 && swBase != 0 && iAddr >= swBase) {
            uint64_t iWant = iAddr - swBase + fbHW;
            if (iWant >= fbHW && iWant <= fbTop) {
                uint64_t nEnc = iWant >> 8;
                put(0x294, static_cast<uint32_t>(nEnc));
                put(0x298, static_cast<uint32_t>(nEnc >> 32));
                RLOG("XQ:   EOP image      %#llx -> %#llx", iAddr, iWant);
                // Try the register too, and say plainly whether it takes the write.
                fbWrite(asicInfo, kGcHqdEopBase, static_cast<uint32_t>(nEnc));
                fbWrite(asicInfo, kGcHqdEopBaseHi, static_cast<uint32_t>(nEnc >> 32));
                uint64_t rb = (static_cast<uint64_t>(fbRead(asicInfo, kGcHqdEopBaseHi)) << 32)
                              | fbRead(asicInfo, kGcHqdEopBase);
                RLOG("XQ:   EOP register   wrote %#llx, reads back %#llx %s", nEnc, rb,
                     rb == nEnc ? "STUCK" : "did not stick");
            } else {
                RLOG("XQ:   EOP image      %#llx -> %#llx outside FB, leaving it", iAddr, iWant);
            }
        } else if (eopFixed) {
            put(0x294, eLo); put(0x298, eHi);
        }
        RLOG("XQ: MQD image at fb+%#llx after:  mqd_base=%#x_%08x eop_base=%#x_%08x",
             imgOff, get(0x204), get(0x200), get(0x298), get(0x294));
    }

    RLOG("XQ: after repair: MQD_BASE=%#x_%08x EOP_BASE=%#x_%08x ACTIVE=%#x rptr=%#x "
         "wptr=%#x_%08x", fbRead(asicInfo, kGcMqdBaseHi), fbRead(asicInfo, kGcMqdBase),
         fbRead(asicInfo, kGcHqdEopBaseHi), fbRead(asicInfo, kGcHqdEopBase),
         fbRead(asicInfo, kGcHqdActive), fbRead(asicInfo, kGcHqdPqRptr),
         fbRead(asicInfo, kGcHqdPqWptrHi), fbRead(asicInfo, kGcHqdPqWptrLo));

    // Does the engine consume anything now? rptr moving off zero is the whole question.
    uint32_t r0 = fbRead(asicInfo, kGcHqdPqRptr);
    for (unsigned i = 0; i < 20; i++) {
        IOSleep(5);
        uint32_t r = fbRead(asicInfo, kGcHqdPqRptr);
        if (r != r0) {
            RLOG("XQ: rptr MOVED %#x -> %#x after %u ms  <-- THE CP IS CONSUMING THE RING",
                 r0, r, (i + 1) * 5);
            break;
        }
        if (i == 19)
            RLOG("XQ: rptr still %#x after 100 ms (wptr=%#x) -- engine still not consuming",
                 r0, fbRead(asicInfo, kGcHqdPqWptrLo));
    }
    fbWrite(asicInfo, kGcGrbmGfxCntl, sel);
}

static uint32_t wrapVmmFillRegs(void *self) {
    auto r = FunctionCast(wrapVmmFillRegs, orgVmmFillRegs)(self);
    // fillVMRegisters fills register-number arrays; it does not program PTB.
    if (ptbFixMode != 2) repairPageTableBase("fillVMRegisters (legacy)");
    return r;
}

static uint32_t wrapVmmProgInv(void *self, void *info) {
    auto r = FunctionCast(wrapVmmProgInv, orgVmmProgInv)(self, info);
    if (ptbFixMode != 2) repairPageTableBase("programAndInvalidateVM (legacy)");
    return r;
}

static void wrapVmmPrepare(void *self, void *prepared, const void *info, bool alternate) {
    // This callback can run under X6000 locks. Its complete operation is:
    // bounded stack copy -> pure arithmetic -> native call on the copy ->
    // bounded output copy -> lock-free append. No MMIO, allocation, logging,
    // lazy mapping, lock, or wait is permitted here.
    const bool marked = __atomic_load_n(&raphaelTargetConfirmed, __ATOMIC_ACQUIRE);
    const bool aperturePublished = __atomic_load_n(&cachedFbPublished, __ATOMIC_ACQUIRE);
    const uint32_t fbBaseSnapshot = __atomic_load_n(&cachedFbBase, __ATOMIC_RELAXED);
    const uint32_t fbTopSnapshot = __atomic_load_n(&cachedFbTop, __ATOMIC_RELAXED);
    const uint32_t fbOffsetSnapshot = __atomic_load_n(&cachedFbOffset, __ATOMIC_RELAXED);
    auto local = RaphaelVm::prepareInvalidateInfo(
        reinterpret_cast<const uint8_t *>(info), info != nullptr ? 0x28 : 0,
        vmRootFixEnabled, marked && aperturePublished, fbBaseSnapshot, fbTopSnapshot,
        fbOffsetSnapshot);
    const void *nativeInfo = local.valid ? static_cast<const void *>(local.bytes) : info;
    FunctionCast(wrapVmmPrepare, orgVmmPrepare)(self, prepared, nativeInfo, alternate);
    auto observation = RaphaelVm::observePreparedRequest(
        reinterpret_cast<const uint8_t *>(info), info != nullptr ? 0x28 : 0,
        reinterpret_cast<const uint8_t *>(nativeInfo), nativeInfo != nullptr ? 0x28 : 0,
        reinterpret_cast<const uint8_t *>(prepared), prepared != nullptr ? 0x54 : 0,
        alternate, local.repaired, local.reason);
    if (observation.valid && observation.request.hub == 0 &&
            observation.request.vmid == 2) {
        observation.sequence = __sync_add_and_fetch(&nextVmObservationSequence, 1u);
        observation.threadToken = reinterpret_cast<uintptr_t>(current_thread());
        vmid2Programs.append(observation);
        __atomic_store_n(&latestVmid2ProgramSequence, observation.sequence, __ATOMIC_RELEASE);
    }
}

static uint32_t wrapHwMemSetVSReady(void *self, uint32_t ready) {
    auto r = FunctionCast(wrapHwMemSetVSReady, orgHwMemSetVSReady)(self, ready);
    if (self == nullptr) return r;
    hwMemObject = self;
    auto f = reinterpret_cast<uint8_t *>(self);
    auto q = [f](size_t o) -> uint64_t & { return *reinterpret_cast<uint64_t *>(f + o); };
    RLOG("XM: AMDHWMemory::setVirtualSpaceReady(%u) | size0=%#llx size1=%#llx "
         "poolA(0x68)=%#llx poolB(0x70)=%#llx  [caller x6+%#llx]",
         ready, q(0x40), q(0x48), q(0x68), q(0x70),
         reinterpret_cast<uint64_t>(__builtin_return_address(0)) - x6Base);
    static bool tried = false;
    if (ready != 0 && memProbeMode >= 2 && !tried && orgHwMemEnable != 0) {
        tried = true;
        if (q(0x68) == 0 || q(0x70) == 0) {
            RLOG("XM: NOT calling enableAllocations: pool pointers are null (A=%#llx B=%#llx), "
                 "so it would bail silently -- the pools are built upstream of the ttlPowerUp "
                 "failure and that is the thing to fix",
                 q(0x68), q(0x70));
        } else {
            RLOG("XM: calling AMDHWMemory::enableAllocations() -- nothing else does, and the "
                 "VRAM heap is empty without it");
            wrapHwMemEnable(self);
            RLOG("XM: after enableAllocations: size0=%#llx size1=%#llx poolA=%#llx poolB=%#llx",
                 q(0x40), q(0x48), q(0x68), q(0x70));
        }
    }
    return r;
}

static uint32_t wrapVmmSetVSReady(void *self, uint32_t ready) {
    auto r = FunctionCast(wrapVmmSetVSReady, orgVmmSetVSReady)(self, ready);
    if (self == nullptr) return r;
    vmmObject = self;
    auto f = reinterpret_cast<uint8_t *>(self);
    auto q = [f](size_t o) { return *reinterpret_cast<void **>(f + o); };
    RLOG("XV: setVirtualSpaceReady(%u) -> %u | m_0x20=%p m_0x28=%p  [caller x6+%#llx]",
         ready, r, q(0x20), q(0x28),
         reinterpret_cast<uint64_t>(__builtin_return_address(0)) - x6Base);
    if (ready != 0 && vmmProbeMode >= 3 && q(0x28) == nullptr && orgVmmSetAlloc != 0) {
        RLOG("XV: driving setMemoryAllocationsEnabled(true) from here, because nothing else "
             "does and m_0x28 is the DMA paging channel endVMPTUpdate dereferences");
        reinterpret_cast<uint32_t (*)(void *, uint32_t)>(orgVmmSetAlloc)(self, 1);
        RLOG("XV: after forced enable: m_0x20=%p m_0x28=%p m_0x30=%p -> %s",
             q(0x20), q(0x28), *reinterpret_cast<void **>(f + 0x30),
             q(0x28) != nullptr ? "DMA PAGING CHANNEL PRESENT"
                                : "still NULL, endVMPTUpdate will panic");
    }
    return r;
}

static uint32_t wrapVmmSetAlloc(void *self, uint32_t enable) {
    if (self == nullptr)
        return FunctionCast(wrapVmmSetAlloc, orgVmmSetAlloc)(self, enable);
    auto f = reinterpret_cast<uint8_t *>(self);
    auto slot = [f](size_t o) -> void *& { return *reinterpret_cast<void **>(f + o); };
    vmmObject = self;
    RLOG("XV: setMemoryAllocationsEnabled(%u) entry: m_0x20=%p m_0x28=%p m_0x30=%p "
         "nest(0x3c)=%u  [caller x6+%#llx]", enable, slot(0x20), slot(0x28), slot(0x30),
         *reinterpret_cast<uint32_t *>(f + 0x3c),
         reinterpret_cast<uint64_t>(__builtin_return_address(0)) - x6Base);
    if (enable != 0 && vmmProbeMode >= 2 && slot(0x20) != nullptr && slot(0x28) == nullptr) {
        RLOG("XV: clearing m_0x20 so the guard at 0x5793d falls through and the channel is "
             "built; setMemoryAllocationsEnabled reassigns m_0x20 itself at 0x5795c");
        slot(0x20) = nullptr;
    }
    auto r = FunctionCast(wrapVmmSetAlloc, orgVmmSetAlloc)(self, enable);
    RLOG("XV: setMemoryAllocationsEnabled(%u) exit:  m_0x20=%p m_0x28=%p m_0x30=%p -> %s",
         enable, slot(0x20), slot(0x28), slot(0x30),
         slot(0x28) != nullptr ? "DMA PAGING CHANNEL PRESENT"
                               : "still NULL, endVMPTUpdate will panic");
    return r;
}

static void probeRlc() {
    if (asicInfo == nullptr) return;

    RLOG("XS: RLC state ----------------------------------------------");
    RLOG("XS:   RLC_CNTL=%#x RLC_STAT=%#x RLC_GPM_STAT=%#x RLC_SAFE_MODE=%#x",
         fbRead(asicInfo, kGcRlcCntl), fbRead(asicInfo, kGcRlcStat),
         fbRead(asicInfo, kGcRlcGpmStat), fbRead(asicInfo, kGcRlcSafeMode));
    RLOG("XS:   RLC_SRM_CNTL=%#x RLC_SRM_STAT=%#x RLC_PG_CNTL=%#x RLC_CGCG=%#x",
         fbRead(asicInfo, kGcRlcSrmCntl), fbRead(asicInfo, kGcRlcSrmStat),
         fbRead(asicInfo, kGcRlcPgCntl), fbRead(asicInfo, kGcRlcCgcg));
    RLOG("XS:   BOOTLOAD 0x4e8d=%#x 0x4e7e=%#x CSIB_ADDR_LO=%#x CSIB_LEN=%#x",
         fbRead(asicInfo, kGcRlcBootStat), fbRead(asicInfo, kGcRlcBootStatSc),
         fbRead(asicInfo, kGcRlcCsibLo), fbRead(asicInfo, kGcRlcCsibLen));
    RLOG("XS:   GRBM_STATUS=%#x GRBM_STATUS2=%#x",
         fbRead(asicInfo, kGcGrbmStatus), fbRead(asicInfo, kGcGrbmStatus2));

    RLOG("XS: writability (CP_MEC_CNTL and SCRATCH_REG0 are the positive controls) -------");
    bool ctlScratch = regWritable("SCRATCH_REG0", kGcScratch0, 0xa5a5a5a5u);
    bool ctlMec     = regWritable("CP_MEC_CNTL", kGcCpMecCntl, 1u << 28);
    bool wRlcCntl   = regWritable("RLC_CNTL", kGcRlcCntl, 1u << 3);
    bool wSafeMode  = regWritable("RLC_SAFE_MODE", kGcRlcSafeMode, 1u << 1);
    bool wPgCntl    = regWritable("RLC_PG_CNTL", kGcRlcPgCntl, 1u << 14);
    bool wSrmCntl   = regWritable("RLC_SRM_CNTL", kGcRlcSrmCntl, 1u << 1);
    RLOG("XS:   controls: scratch=%u mec_cntl=%u | RLC: cntl=%u safe_mode=%u pg=%u srm=%u",
         ctlScratch, ctlMec, wRlcCntl, wSafeMode, wPgCntl, wSrmCntl);

    // The liveness test, made explicit and timed. Upstream's enter-safe-mode writes CMD=1
    // and waits for the RLC to clear it; only a running RLC does that.
    uint32_t sm0 = fbRead(asicInfo, kGcRlcSafeMode);
    fbWrite(asicInfo, kGcRlcSafeMode, sm0 | 1u);
    uint32_t smAfterWrite = fbRead(asicInfo, kGcRlcSafeMode);
    int ack = 0;
    for (; ack < 50000; ack++) {
        if ((fbRead(asicInfo, kGcRlcSafeMode) & 1u) == 0) break;
        IODelay(1);
    }
    RLOG("XS: safe-mode handshake: wrote CMD=1 (%#x -> %#x), RLC %s after %dus -> %s",
         sm0, smAfterWrite, ack < 50000 ? "ACKNOWLEDGED" : "never acknowledged", ack,
         ack < 50000 ? "RLC IS RUNNING" : "RLC IS NOT RUNNING");
    fbWrite(asicInfo, kGcRlcSafeMode, sm0);

    // Most invasive, so last: if RLC_CNTL takes writes, try stopping and restarting the F32
    // microcontroller and see whether anything wakes up. Bit 0 is RLC_ENABLE_F32.
    // The RLC_ENABLE cycle is behind rgpurlc=2, because it BREAKS A WORKING RLC.
    //
    // Measured: RLC_STAT went 0x25 (RLC_BUSY | RLC_GPM_BUSY | THREAD_0_BUSY) -> 0x5 with
    // RLC_ENABLE cleared -> 0x0 after setting it again, and it stayed 0 for the rest of the
    // run. Re-enabling the F32 does not restart it; the microcontroller has to be reloaded,
    // which only the PSP can do. So this stops the one part of the block that was working,
    // and it did not move the microengines either.
    if (wRlcCntl && rlcProbeEnabled2) {
        uint32_t c0 = fbRead(asicInfo, kGcRlcCntl);
        fbWrite(asicInfo, kGcRlcCntl, c0 & ~1u);
        IODelay(1000);
        uint32_t statOff = fbRead(asicInfo, kGcRlcStat);
        fbWrite(asicInfo, kGcRlcCntl, c0 | 1u);
        IOSleep(20);
        uint32_t statOn = fbRead(asicInfo, kGcRlcStat);

        uint32_t f2 = fbRead(asicInfo, kGcMec2InstrPntr), l2 = f2, ch2 = 0;
        uint32_t f1 = fbRead(asicInfo, kGcMec1InstrPntr), l1 = f1, ch1 = 0;
        for (unsigned i = 0; i < 16; i++) {
            IODelay(20);
            uint32_t v2 = fbRead(asicInfo, kGcMec2InstrPntr);
            uint32_t v1 = fbRead(asicInfo, kGcMec1InstrPntr);
            if (v2 != l2) { ch2++; l2 = v2; }
            if (v1 != l1) { ch1++; l1 = v1; }
        }
        RLOG("XS: RLC_ENABLE cycle: cntl %#x -> off(stat=%#x) -> on(stat=%#x); "
             "MEC2 %#x..%#x (%u) MEC1 %#x..%#x (%u) -> %s",
             c0, statOff, statOn, f2, l2, ch2, f1, l1, ch1,
             (ch1 || ch2) ? "THE CP EXECUTES" : "still not executing");
    } else {
        RLOG("XS: RLC_ENABLE cycle skipped (rgpurlc=2 arms it; it breaks a working RLC)");
    }
    RLOG("XS: RLC probe end ------------------------------------------");
}

static void primeIcacheOnly() {
    if (asicInfo == nullptr) return;

    uint32_t mecBefore = fbRead(asicInfo, kGcCpMecCntl);
    fbWrite(asicInfo, kGcCpMecCntl, (1u << 30) | (1u << 28));   // ME1_HALT | ME2_HALT
    uint32_t mecHalted = fbRead(asicInfo, kGcCpMecCntl);
    IODelay(50);

    uint32_t bc0 = fbRead(asicInfo, kGcCpcIcBaseCntl);
    fbWrite(asicInfo, kGcCpcIcBaseCntl, bc0 ^ (1u << 24));
    uint32_t bcToggled = fbRead(asicInfo, kGcCpcIcBaseCntl);
    bool writesLand = (bcToggled != bc0);
    fbWrite(asicInfo, kGcCpcIcBaseCntl, bc0);

    fbWrite(asicInfo, kGcCpcIcOpCntl, fbRead(asicInfo, kGcCpcIcOpCntl) & ~2u);
    bool completeCleared = (fbRead(asicInfo, kGcCpcIcOpCntl) & 2u) == 0;
    fbWrite(asicInfo, kGcCpcIcOpCntl, fbRead(asicInfo, kGcCpcIcOpCntl) | 1u);
    int inv = 0;
    for (; inv < 50000; inv++) {
        if ((fbRead(asicInfo, kGcCpcIcOpCntl) & 2u) != 0) break;
        IODelay(1);
    }
    bool invalidated = inv < 50000;

    uint32_t bc = fbRead(asicInfo, kGcCpcIcBaseCntl);
    bc &= ~0xfu;            // VMID 0
    bc &= ~(1u << 23);      // EXE_DISABLE 0
    bc &= ~(3u << 24);      // CACHE_POLICY 0
    bc |=  (1u << 4);       // ADDRESS_CLAMP 1
    fbWrite(asicInfo, kGcCpcIcBaseCntl, bc);

    fbWrite(asicInfo, kGcCpcIcOpCntl, fbRead(asicInfo, kGcCpcIcOpCntl) | (1u << 4));
    uint32_t opAfterRequest = fbRead(asicInfo, kGcCpcIcOpCntl);
    bool requestStuck = (opAfterRequest & (1u << 4)) != 0;
    int prime = 0;
    for (; prime < 50000; prime++) {
        if ((fbRead(asicInfo, kGcCpcIcOpCntl) & (1u << 5)) != 0) break;
        IODelay(1);
    }
    bool primed = prime < 50000;

    fbWrite(asicInfo, kGcCpMecCntl, 0);     // unhalt both
    IODelay(200);

    uint32_t first2 = fbRead(asicInfo, kGcMec2InstrPntr), last2 = first2, ch2 = 0;
    uint32_t first1 = fbRead(asicInfo, kGcMec1InstrPntr), last1 = first1, ch1 = 0;
    for (unsigned i = 0; i < 16; i++) {
        IODelay(20);
        uint32_t v2 = fbRead(asicInfo, kGcMec2InstrPntr);
        uint32_t v1 = fbRead(asicInfo, kGcMec1InstrPntr);
        if (v2 != last2) { ch2++; last2 = v2; }
        if (v1 != last1) { ch1++; last1 = v1; }
    }
    RLOG("XP: controls: writes-land=%u (base_cntl %#x ^bit24 -> %#x) complete-bit-cleared=%u "
         "| MEC_CNTL %#x -> halted %#x", writesLand, bc0, bcToggled, completeCleared,
         mecBefore, mecHalted);
    RLOG("XP: INVALIDATE %s after %dus | PRIME request-stuck=%u (op=%#x) %s after %dus "
         "(op_cntl=%#x base_cntl=%#x)", invalidated ? "completed" : "NEVER COMPLETED", inv,
         requestStuck, opAfterRequest, primed ? "completed" : "NEVER COMPLETED", prime,
         fbRead(asicInfo, kGcCpcIcOpCntl), fbRead(asicInfo, kGcCpcIcBaseCntl));
    RLOG("XP: MEC2 %#x..%#x (%u changes) MEC1 %#x..%#x (%u changes) -> %s",
         first2, last2, ch2, first1, last1, ch1,
         (ch1 || ch2) ? "THE CP EXECUTES" : "still not executing");
}

static void startRlc() {
    if (asicInfo == nullptr) { RLOG("XK: no register accessor yet"); return; }
    dumpGfxState("before RLC start");
    fbWrite(asicInfo, kGcRlcCgcg, 0);
    fbWrite(asicInfo, kGcRlcPgCntl, 0);
    uint32_t cntl = fbRead(asicInfo, kGcRlcCntl);
    fbWrite(asicInfo, kGcRlcCntl, cntl | 1u);
    IOSleep(1);
    RLOG("XK: RLC_CNTL %#x -> %#x", cntl, fbRead(asicInfo, kGcRlcCntl));
    // Previous selector diagnostics wrote artificial PQ_BASE values into two queues
    // without dequeue or restoration. They could corrupt live queue descriptors and
    // did not prove selection works. Keep bring-up free of that experiment.
    if (cpSurgeryEnabled) {
        programL2LikeUpstream();
        loadMecMicrocode();
        startMecEngines();
    }
    reportCpState("post-TTL");
    dumpMecQueues("post-TTL");
    if (mqdFixMode != 2) dumpCpUcode("post-TTL");
    dumpGfxHubVm("post-TTL");
    dumpGfxState("after RLC start");
}

// Navi23's allocator always constructs two SDMA objects. Raphael's IP discovery
// contains only SDMA0, and hybrid-002 proved that the second object reaches the
// native selector as global instance index 1 and is rejected before its callback.
// Remove that false object before AMDHardware::initializeHWEngines assigns indices,
// allocates channels or powers engines. The generic initialize/power/free loops all
// tolerate null slots. startHWEngines does not, so its one-instance equivalent lives
// below and preserves the first engine's real Boolean result.
static bool isRaphaelHardware(void *self) {
    if (!raphaelGcSeen || self == nullptr) return false;
    auto rawPci = *reinterpret_cast<void **>(reinterpret_cast<uint8_t *>(self) + 0x10);
    auto pci = OSDynamicCast(IOService, reinterpret_cast<OSObject *>(rawPci));
    if (pci == nullptr) return false;
    auto vendor = OSDynamicCast(OSData, pci->getProperty("vendor-id"));
    auto device = OSDynamicCast(OSData, pci->getProperty("device-id"));
    auto atom = OSDynamicCast(OSData, pci->getProperty("ATY,bin_image"));
    auto marker = OSDynamicCast(OSData, pci->getProperty("rgpu,raphael-target"));
    static constexpr uint8_t expectedMarker[] = {
        'R', 'G', 'P', 'U', '-', 'R', 'A', 'P', 'H', 'A', 'E', 'L', 1
    };
    if (vendor == nullptr || vendor->getLength() < sizeof(uint16_t) ||
        device == nullptr || device->getLength() < sizeof(uint16_t) ||
        atom == nullptr || atom->getLength() < 512 || marker == nullptr ||
        marker->getLength() != sizeof(expectedMarker))
        return false;
    auto markerBytes = static_cast<const uint8_t *>(marker->getBytesNoCopy());
    bool markerMatches = true;
    for (size_t i = 0; i < sizeof(expectedMarker); i++)
        markerMatches &= markerBytes[i] == expectedMarker[i];
    const bool matches = markerMatches &&
        *static_cast<const uint16_t *>(vendor->getBytesNoCopy()) == 0x1002 &&
        *static_cast<const uint16_t *>(device->getBytesNoCopy()) == 0x73ff;
    if (matches) {
        // The framebuffer snapshot is published earlier in startup. Make the
        // exact marker match the release barrier for later VM callbacks.
        __atomic_store_n(&raphaelTargetConfirmed, true, __ATOMIC_RELEASE);
    }
    return matches;
}

static uint32_t wrapHwEngInit(void *self) {
    if (sdmaTopologyEnabled && sdmaTopologyRoutesReady && isRaphaelHardware(self)) {
        auto slots = reinterpret_cast<void **>(reinterpret_cast<uint8_t *>(self) + 0x3b8);
        auto topology = RaphaelSdma::plan(1);
        void *detached = RaphaelSdma::detachExtra(slots, 2, topology);
        if (detached != nullptr) {
            auto vt = *reinterpret_cast<uint64_t **>(detached);
            auto release = reinterpret_cast<void (*)(void *)>(vt[0x28 / 8]);
            release(detached);
            sdmaTopologyOwner = self;
            CRLOG("SD: topology applied: discovered=1 kept=SDMA0 removed=SDMA1 before initialize");
        } else if (sdmaTopologyOwner == self && slots[0] != nullptr && slots[1] == nullptr) {
            CRLOG("SD: topology already applied to this hardware object");
        } else {
            if (sdmaTopologyOwner == self) sdmaTopologyOwner = nullptr;
            CRLOG("SD: topology NOT applied: second Navi23 SDMA object was absent");
        }
    } else if (sdmaTopologyEnabled && sdmaTopologyRoutesReady) {
        CRLOG("SD: topology NOT applied: hardware object is not the Raphael target");
    }
    auto result = FunctionCast(wrapHwEngInit, orgHwEngInit)(self);
    CRLOG("SD: AMDHardware::initializeHWEngines -> %u (topology-applied=%u)",
          result & 0xff, sdmaTopologyOwner == self);
    return result;
}

static void *wrapHwGetChannel(void *self, uint32_t engineType, uint32_t ringType) {
    auto slots = self != nullptr
        ? reinterpret_cast<void **>(reinterpret_cast<uint8_t *>(self) + 0x3b8)
        : nullptr;
    auto topology = RaphaelSdma::plan(1);
    bool repaired = sdmaTopologyEnabled && sdmaTopologyRoutesReady &&
        RaphaelSdma::ownsRepairedSlots(sdmaTopologyOwner, self, slots, 2, topology);
    uint32_t selected = RaphaelSdma::engineForPhysicalTopology(engineType, repaired);
    if (selected != engineType) {
        static unsigned reports = 0;
        if (__sync_fetch_and_add(&reports, 1u) < 16)
            CRLOG("SD: channel engine remap %u -> %u ring=%u", engineType, selected,
                  ringType);
    }
    return FunctionCast(wrapHwGetChannel, orgHwGetChannel)(self, selected, ringType);
}

static uint32_t wrapSdmaCommitIb(void *self, void *submitInfo) {
    // X6000 copies its fixed channel template from self+0x138, then emits one
    // SDMA INDIRECT packet per AMD_SUBMIT_COMMAND_BUFFER_INFO entry. Static
    // disassembly shows the packet address comes from submitInfo+0x58+0x28*i;
    // the old wrapper changed template[1:2], an unrelated driver-owned address.
    // The packet carries a VMID, so these are GPU virtual addresses. Observe
    // the actual submit entries before the native encoder reads them, but do
    // not translate them into physical framebuffer addresses.
    if (sdmaTopologyEnabled && sdmaTopologyRoutesReady && submitInfo != nullptr) {
        auto observation = RaphaelSdma::observeSubmitInfo(
            reinterpret_cast<const uint8_t *>(submitInfo), 0xe8);
        if (observation.vmid == 2) {
            observation.eventOrder = __sync_add_and_fetch(&nextVmObservationSequence, 1u);
            observation.threadToken = reinterpret_cast<uintptr_t>(current_thread());
            observation.vmProgramSequence = __atomic_load_n(
                &latestVmid2ProgramSequence, __ATOMIC_ACQUIRE);
            vmid2Submits.append(observation);
        }
    }
    return FunctionCast(wrapSdmaCommitIb, orgSdmaCommitIb)(self, submitInfo);
}

static const char *rootRepairReasonName(uint32_t reason) {
    using R = RaphaelVm::RootRepairReason;
    switch (static_cast<R>(reason)) {
        case R::InvalidInput: return "invalid-input";
        case R::Disabled: return "disabled";
        case R::TargetUnmarked: return "target-unmarked";
        case R::WrongHub: return "wrong-hub";
        case R::WrongVmid: return "wrong-vmid";
        case R::NotReprogrammed: return "not-reprogrammed";
        case R::InvalidAperture: return "invalid-aperture";
        case R::SystemRoot: return "system-root";
        case R::UnsupportedFlags: return "unsupported-flags";
        case R::AlreadyPhysical: return "already-physical";
        case R::OutsideFramebuffer: return "outside-framebuffer";
        case R::Overflow: return "overflow";
        case R::Repaired: return "repaired";
    }
    return "unknown";
}

static const char *invalidateRegisterKindName(RaphaelVm::InvalidateRegisterKind kind) {
    using K = RaphaelVm::InvalidateRegisterKind;
    switch (kind) {
        case K::Semaphore: return "sem";
        case K::Request: return "req";
        case K::Acknowledge: return "ack";
        case K::Unknown: return "other";
    }
    return "other";
}

static bool vmid2Aperture(RaphaelVm::FramebufferAperture &aperture) {
    if (!__atomic_load_n(&cachedFbPublished, __ATOMIC_ACQUIRE)) return false;
    const uint32_t base = __atomic_load_n(&cachedFbBase, __ATOMIC_RELAXED);
    const uint32_t top = __atomic_load_n(&cachedFbTop, __ATOMIC_RELAXED);
    const uint32_t offset = __atomic_load_n(&cachedFbOffset, __ATOMIC_RELAXED);
    if (base == 0 || offset == 0 || top < base ||
        ((base | top | offset) & 0xff000000u) || hwMemObject == nullptr)
        return false;
    auto memory = reinterpret_cast<const uint8_t *>(hwMemObject);
    uint64_t size0 = *reinterpret_cast<const uint64_t *>(memory + 0x40);
    uint64_t size1 = *reinterpret_cast<const uint64_t *>(memory + 0x48);
    uint64_t visible = RaphaelRecovery::barVisibleBytes(size0, size1);
    if (visible > 0x10000000ULL) visible = 0x10000000ULL;
    aperture = {static_cast<uint64_t>(base) << 24,
                (static_cast<uint64_t>(top) << 24) | 0xffffffULL,
                static_cast<uint64_t>(offset) << 24, visible};
    return RaphaelVm::validAperture(aperture);
}

static bool submitFitsProgram(const RaphaelSdma::SubmitInfoObservation &submit,
                              const RaphaelVm::PreparedRequest &program) {
    if (!submit.layoutValid || submit.vmid != 2 || !program.valid ||
        program.request.hub != 0 || program.request.vmid != 2 ||
        !program.request.reprogram || submit.entries == 0 || submit.entries > 4)
        return false;
    bool sawAddress = false;
    for (uint32_t n = 0; n < submit.entries; ++n) {
        const uint64_t address = submit.addresses[n];
        if (address == 0) continue;
        sawAddress = true;
        if (address < program.request.start || address > program.request.end) return false;
    }
    return sawAddress;
}

static void reportVmid2Walk(uint32_t sequence, const RaphaelVm::PreparedRequest &program,
                            const RaphaelSdma::SubmitInfoObservation &submit) {
    RaphaelVm::FramebufferAperture aperture {};
    auto fb = fbAperture();
    if (fb == nullptr || !vmid2Aperture(aperture)) {
        CRLOG("VM: walk seq=%u refused: BAR0/aperture unavailable", sequence);
        return;
    }
    auto reader = [&](uint64_t physical, uint64_t &value) {
        if (physical < aperture.physicalBase ||
            physical - aperture.physicalBase > aperture.visibleBytes - 8)
            return false;
        const uint64_t dword = (physical - aperture.physicalBase) / 4;
        const uint32_t lo = fb[dword], hi = fb[dword + 1];
        value = RaphaelVm::join(lo, hi);
        return true;
    };
    uint64_t targets[7] {0x400100000ULL, 0x4000c0000ULL, 0x400200000ULL};
    size_t targetCount = 3;
    for (uint32_t n = 0; n < submit.entries && n < 4; ++n) {
        const uint64_t address = submit.addresses[n];
        if (address == 0) continue;
        bool duplicate = false;
        for (size_t existing = 0; existing < targetCount; ++existing)
            duplicate |= targets[existing] == address;
        if (!duplicate && targetCount < sizeof(targets) / sizeof(targets[0]))
            targets[targetCount++] = address;
    }
    for (size_t target = 0; target < targetCount; ++target) {
        const uint64_t va = targets[target];
        auto walk = RaphaelVm::walkPageTables(program.nativeRoot,
            // The prepared request does not carry context control. The live
            // value is read here, outside the callback and its caller locks.
            fbRead(asicInfo, kGcSeg0 + RaphaelVm::contextRegisters(2).control),
            va, aperture, reader);
        CRLOG("VM: walk seq=%u va=%#llx root=%#llx valid=%u complete=%u count=%u",
              sequence, va, program.nativeRoot, walk.valid, walk.complete, walk.count);
        for (uint32_t n = 0; n < walk.count; ++n) {
            const auto &e = walk.entries[n];
            CRLOG("VM: walk-entry seq=%u va=%#llx n=%u level=%u index=%llu table=%#llx "
                  "raw=%#llx addr=%#llx V=%u S=%u C=%u X=%u R=%u W=%u P=%u TF=%u "
                  "child-mc2pa=%u",
                  sequence, va, n, e.level, e.index, e.tablePhysical, e.raw, e.address,
                  e.valid, e.system, e.snooped, e.executable, e.readable, e.writeable,
                  e.pdeAsPte, e.translateFurther, e.childConverted);
        }
    }
}

static void reportVmid2Runtime(const char *phase, uint32_t sequence,
                               const RaphaelVm::PreparedRequest &program,
                               const RaphaelSdma::SubmitInfoObservation *submit, bool walk) {
    if (asicInfo == nullptr) return;
    constexpr auto ctx = RaphaelVm::contextRegisters(2);
    auto rd = [](uint32_t relative) { return fbRead(asicInfo, kGcSeg0 + relative); };
    const uint32_t control = rd(ctx.control);
    const uint64_t liveRoot = RaphaelVm::join(rd(ctx.ptbLo), rd(ctx.ptbHi));
    const uint64_t start = RaphaelVm::join(rd(ctx.startLo), rd(ctx.startHi)) << 12;
    const uint64_t end = (RaphaelVm::join(rd(ctx.endLo), rd(ctx.endHi)) << 12) | 0xfffULL;
    const uint64_t preparedRoot = RaphaelVm::join(program.words[1], program.words[3]);
    CRLOG("VM: state seq=%u phase=%s vmid=2 ctl=%#x root=%#llx start=%#llx end=%#llx "
          "requested=%#llx native=%#llx prepared=%#llx repaired=%u reason=%s "
          "prepared-match=%u live-match=%u",
          sequence, phase, control, liveRoot, start, end, program.request.root,
          program.nativeRoot, preparedRoot, program.rootRepaired,
          rootRepairReasonName(program.repairReason), program.preparedRootMatches,
          liveRoot == program.nativeRoot);
    CRLOG("VM: context-snapshot vmid=2 root=%#llx ctl=%#x start=%#llx end=%#llx",
          liveRoot, control, start, end);

    const uint32_t faultControl = fbRead(asicInfo, kGcVmFaultCntl);
    const uint32_t faultStatus = fbRead(asicInfo, kGcVmFaultSts);
    const uint64_t faultAddress = RaphaelVm::decodeFaultAddress(
        fbRead(asicInfo, kGcVmFaultLo), fbRead(asicInfo, kGcVmFaultHi));
    const uint32_t invControl = fbRead(asicInfo, kGcVmInvCntl);
    const uint32_t req0 = fbRead(asicInfo, kGcVmInvEng0Req);
    const uint32_t ack0 = fbRead(asicInfo, kGcVmInvEng0Ack);
    CRLOG("VM: fault seq=%u phase=%s cntl=%#x status=%#x addr=%#llx | invalidate-order=%#x "
          "eng0-sem=unread req=%#x ack=%#x bit2=%u/%u prepared-mask=%#x/%#x",
          sequence, phase, faultControl, faultStatus, faultAddress, invControl,
          req0, ack0, (req0 >> 2) & 1u, (ack0 >> 2) & 1u,
          program.words[19], program.words[20]);
    const uint32_t preparedRegs[] {program.words[12], program.words[14],
                                   program.words[16], program.words[18]};
    for (uint32_t reg : preparedRegs) {
        auto decoded = RaphaelVm::decodeInvalidateRegister(
            reg, kGcVmInvEng0Sem, kGcVmInvEng0Req, kGcVmInvEng0Ack);
        uint32_t mmioReg = reg;
        if (!decoded.valid) {
            decoded = RaphaelVm::decodeInvalidateRegister(
                reg, kGcVmInvEng0Sem - kGcSeg0, kGcVmInvEng0Req - kGcSeg0,
                kGcVmInvEng0Ack - kGcSeg0);
            if (decoded.valid) mmioReg += kGcSeg0;
        }
        if (decoded.valid) {
            const auto sample = RaphaelVm::sampleInvalidateRegister(
                mmioReg, decoded,
                [](uint32_t registerOffset) { return fbRead(asicInfo, registerOffset); });
            if (!sample.read) {
                CRLOG("VM: invalidate-live seq=%u phase=%s reg=%#x kind=%s engine=%u "
                      "value=unread",
                      sequence, phase, mmioReg, invalidateRegisterKindName(decoded.kind),
                      decoded.engine);
            } else {
                CRLOG("VM: invalidate-live seq=%u phase=%s reg=%#x kind=%s engine=%u "
                      "value=%#x bit2=%u",
                      sequence, phase, mmioReg, invalidateRegisterKindName(decoded.kind),
                      decoded.engine, sample.value, (sample.value >> 2) & 1u);
            }
        }
    }

    CRLOG("SD: runtime seq=%u phase=%s cntl=%#x ucode=%#x f32=%#x "
          "status=%#x/%#x/%#x/%#x "
          "utcl-cntl=%#x page=%#x rd=%#x wr=%#x",
          sequence, phase, fbRead(asicInfo, kSdmaCntl),
          fbRead(asicInfo, kSdmaUcodeCsum), fbRead(asicInfo, kSdmaF32Cntl),
          fbRead(asicInfo, kSdmaStatus0),
          fbRead(asicInfo, kSdmaStatus1), fbRead(asicInfo, kSdmaStatus2),
          fbRead(asicInfo, kSdmaStatus3), fbRead(asicInfo, kSdmaUtclCntl),
          fbRead(asicInfo, kSdmaUtclPage), fbRead(asicInfo, kSdmaUtclRd),
          fbRead(asicInfo, kSdmaUtclWr));
    CRLOG("SD: xnack seq=%u phase=%s rd=%#x/%#x wr=%#x/%#x",
          sequence, phase, fbRead(asicInfo, kSdmaRdXnack0),
          fbRead(asicInfo, kSdmaRdXnack1), fbRead(asicInfo, kSdmaWrXnack0),
          fbRead(asicInfo, kSdmaWrXnack1));
    CRLOG("SD: page seq=%u phase=%s status=%#x context=%#x ib-cntl=%#x rptr=%#x "
          "offset=%#x base=%#x_%08x size=%#x",
          sequence, phase, fbRead(asicInfo, kSdmaPageStatus),
          fbRead(asicInfo, kSdmaPageCtx), fbRead(asicInfo, kSdmaPageIbCntl),
          fbRead(asicInfo, kSdmaPageIbRptr), fbRead(asicInfo, kSdmaPageIbOff),
          fbRead(asicInfo, kSdmaPageIbHi), fbRead(asicInfo, kSdmaPageIbLo),
          fbRead(asicInfo, kSdmaPageIbSize));
    if (walk && submit != nullptr) reportVmid2Walk(sequence, program, *submit);
}

static bool submissionTraceCaptureActive() {
    return submissionTraceEnabled &&
        __atomic_load_n(&submissionTraceRoutesReady, __ATOMIC_ACQUIRE) &&
        __atomic_load_n(&raphaelTargetConfirmed, __ATOMIC_ACQUIRE);
}

static void captureSubmissionTrace(RaphaelSubmit::Kind kind, RaphaelSubmit::Phase phase,
                                   const void *subject, const void *object,
                                   uint32_t requested, uint32_t result, uint32_t before) {
    if (!submissionTraceCaptureActive()) return;
    RaphaelSubmit::Record record {
        kind, phase, reinterpret_cast<uintptr_t>(subject),
        reinterpret_cast<uintptr_t>(object), reinterpret_cast<uintptr_t>(current_thread()),
        requested, result, before,
        __sync_add_and_fetch(&nextSubmissionTraceSequence, 1u)
    };
    submissionTrace.append(record);
}

static void wrapProcessCommandBuffer(void *queue, uint32_t first, uint32_t second) {
    if (!submissionTraceCaptureActive()) {
        FunctionCast(wrapProcessCommandBuffer, orgProcessCommandBuffer)(queue, first, second);
        return;
    }
    auto error = reinterpret_cast<volatile uint32_t *>(
        static_cast<uint8_t *>(queue) + 0x610);
    uint32_t before = __atomic_load_n(error, __ATOMIC_RELAXED);
    captureSubmissionTrace(RaphaelSubmit::Kind::ProcessCommandBuffer,
                           RaphaelSubmit::Phase::Entry, queue, nullptr,
                           first, second, before);
    FunctionCast(wrapProcessCommandBuffer, orgProcessCommandBuffer)(queue, first, second);
    uint32_t after = __atomic_load_n(error, __ATOMIC_RELAXED);
    captureSubmissionTrace(RaphaelSubmit::Kind::ProcessCommandBuffer,
                           RaphaelSubmit::Phase::Exit, queue, nullptr,
                           first, after, before);
}

static uint32_t wrapBatchPrepareMappings(void *accelerator, void *const *resources,
                                         uint32_t count) {
    captureSubmissionTrace(RaphaelSubmit::Kind::BatchPrepareMappings,
                           RaphaelSubmit::Phase::Entry, accelerator, resources,
                           count, 0, 0);
    auto result = FunctionCast(wrapBatchPrepareMappings, orgBatchPrepareMappings)(
        accelerator, resources, count);
    captureSubmissionTrace(RaphaelSubmit::Kind::BatchPrepareMappings,
                           RaphaelSubmit::Phase::Exit, accelerator, resources,
                           count, result, 0);
    return result;
}

static bool wrapBatchPrepare(void *accelerator, void *const *resources, uint32_t count) {
    captureSubmissionTrace(RaphaelSubmit::Kind::BatchPrepare,
                           RaphaelSubmit::Phase::Entry, accelerator, resources,
                           count, 0, 0);
    bool result = FunctionCast(wrapBatchPrepare, orgBatchPrepare)(
        accelerator, resources, count);
    captureSubmissionTrace(RaphaelSubmit::Kind::BatchPrepare,
                           RaphaelSubmit::Phase::Exit, accelerator, resources,
                           count, result, 0);
    return result;
}

static RaphaelSubmit::MapSnapshot captureMapSnapshot(void *accelerator,
                                                     void *memoryMap) {
    if (accelerator == nullptr || memoryMap == nullptr)
        return RaphaelSubmit::MapSnapshot {};
    auto acceleratorBytes = static_cast<uint8_t *>(accelerator);
    auto mapBytes = static_cast<uint8_t *>(memoryMap);
    return RaphaelSubmit::MapSnapshot {
        __atomic_load_n(reinterpret_cast<volatile uint32_t *>(
                            acceleratorBytes + 0x1fb0), __ATOMIC_RELAXED),
        __atomic_load_n(reinterpret_cast<volatile uint32_t *>(
                            mapBytes + 0xc), __ATOMIC_RELAXED),
        __atomic_load_n(reinterpret_cast<volatile uint32_t *>(
                            mapBytes + 0x10), __ATOMIC_RELAXED),
        __atomic_load_n(reinterpret_cast<volatile uint64_t *>(
                            mapBytes + 0x98), __ATOMIC_RELAXED),
        true
    };
}

static bool wrapBatchMemoryMapPrepare(void *accelerator, void *memoryMap) {
    if (!submissionTraceCaptureActive())
        return FunctionCast(wrapBatchMemoryMapPrepare, orgBatchMemoryMapPrepare)(
            accelerator, memoryMap);
    auto before = captureMapSnapshot(accelerator, memoryMap);
    captureSubmissionTrace(RaphaelSubmit::Kind::MemoryMapPrepare,
                           RaphaelSubmit::Phase::Entry, accelerator, memoryMap,
                           0, 0, 0);
    bool result = FunctionCast(wrapBatchMemoryMapPrepare, orgBatchMemoryMapPrepare)(
        accelerator, memoryMap);
    auto after = captureMapSnapshot(accelerator, memoryMap);
    captureSubmissionTrace(RaphaelSubmit::Kind::MemoryMapPrepare,
                           RaphaelSubmit::Phase::Exit, accelerator, memoryMap,
                           0, result, 0);
    submissionMapPhases.append(RaphaelSubmit::MapPrepareObservation {
        reinterpret_cast<uintptr_t>(accelerator),
        reinterpret_cast<uintptr_t>(memoryMap),
        reinterpret_cast<uintptr_t>(current_thread()), result, before, after,
        __sync_add_and_fetch(&nextSubmissionTraceSequence, 1u)
    });
    return result;
}

static void wrapSubmitBuffer(void *channel, void *descriptor) {
    captureSubmissionTrace(RaphaelSubmit::Kind::SubmitBuffer,
                           RaphaelSubmit::Phase::Entry, channel, descriptor,
                           0, 0, 0);
    FunctionCast(wrapSubmitBuffer, orgSubmitBuffer)(channel, descriptor);
    captureSubmissionTrace(RaphaelSubmit::Kind::SubmitBuffer,
                           RaphaelSubmit::Phase::Exit, channel, descriptor,
                           0, 0, 0);
}

static void publishPendingSubmissionTrace() {
    if (!submissionTraceEnabled) return;
    static size_t recordCursor = 0;
    static size_t notableCursor = 0;
    static size_t phaseCursors[RaphaelSubmit::MapPhaseCount] {};
    static uint64_t lastTotal = 0;
    static unsigned quietPolls = 0;
    static unsigned summaryRecords = 0;
    static bool dirty = false;
    static uint64_t lastPhaseTotal = 0;
    static unsigned phaseQuietPolls = 0;
    static unsigned phaseSummaryRecords = 0;
    static bool phaseDirty = false;
    bool publishedNotable = false;
    RaphaelSubmit::Record record {};
    while (recordCursor < submissionTrace.records().size() &&
           submissionTrace.records().read(recordCursor, record)) {
        ++recordCursor;
        CRLOG("SUB: trace seq=%u kind=%s phase=%s subject=%#llx object=%#llx thread=%#llx "
              "requested=%u result=%u before=%u",
              record.sequence, RaphaelSubmit::kindName(record.kind),
              RaphaelSubmit::phaseName(record.phase),
              static_cast<uint64_t>(record.subject), static_cast<uint64_t>(record.object),
              static_cast<uint64_t>(record.threadToken), record.requested, record.result,
              record.before);
    }
    while (notableCursor < submissionTrace.notableRecords().size() &&
           submissionTrace.notableRecords().read(notableCursor, record)) {
        ++notableCursor;
        publishedNotable = true;
        CRLOG("SUB: notable seq=%u kind=%s subject=%#llx object=%#llx thread=%#llx "
              "requested=%u result=%u before=%u",
              record.sequence, RaphaelSubmit::kindName(record.kind),
              static_cast<uint64_t>(record.subject), static_cast<uint64_t>(record.object),
              static_cast<uint64_t>(record.threadToken), record.requested, record.result,
              record.before);
    }
    RaphaelSubmit::MapPrepareObservation mapObservation {};
    for (size_t index = 1; index < RaphaelSubmit::MapPhaseCount; ++index) {
        auto mapPhase = static_cast<RaphaelSubmit::MapPhase>(index);
        const auto &samples = submissionMapPhases.samples(mapPhase);
        while (phaseCursors[index] < samples.size() &&
               samples.read(phaseCursors[index], mapObservation)) {
            ++phaseCursors[index];
            CRLOG("SUB: map-phase seq=%u class=%s accel=%#llx map=%#llx thread=%#llx "
                  "pre=%u/%u/%#x/%#llx post=%u/%u/%#x/%#llx",
                  mapObservation.sequence, RaphaelSubmit::mapPhaseName(mapPhase),
                  static_cast<uint64_t>(mapObservation.accelerator),
                  static_cast<uint64_t>(mapObservation.memoryMap),
                  static_cast<uint64_t>(mapObservation.threadToken),
                  mapObservation.before.batchCount, mapObservation.before.prepareCount,
                  mapObservation.before.flags,
                  mapObservation.before.gpuVirtualAddress,
                  mapObservation.after.batchCount, mapObservation.after.prepareCount,
                  mapObservation.after.flags,
                  mapObservation.after.gpuVirtualAddress);
        }
    }

    uint64_t entries[RaphaelSubmit::KindCount] {};
    uint64_t exits[RaphaelSubmit::KindCount] {};
    uint64_t notable[RaphaelSubmit::KindCount] {};
    uint64_t total = 0;
    for (size_t i = 0; i < RaphaelSubmit::KindCount; ++i) {
        auto kind = static_cast<RaphaelSubmit::Kind>(i);
        entries[i] = submissionTrace.entries(kind);
        exits[i] = submissionTrace.exits(kind);
        notable[i] = submissionTrace.notable(kind);
        total += entries[i] + exits[i];
    }
    if (total != lastTotal) {
        dirty = true;
        quietPolls = 0;
    } else if (dirty && quietPolls < 10) {
        ++quietPolls;
    }
    // A zero-count record proves that the worker saw an armed route set. Thereafter
    // summarize settled bursts and retained anomalies, with an explicit global cap.
    bool initial = summaryRecords == 0 &&
        __atomic_load_n(&submissionTraceRoutesReady, __ATOMIC_ACQUIRE);
    bool settled = dirty && quietPolls >= 10;
    if (summaryRecords < 32 && (initial || publishedNotable || settled)) {
        CRLOG("SUB: summary process=%llu/%llu/%llu mappings=%llu/%llu/%llu "
              "prepare=%llu/%llu/%llu map=%llu/%llu/%llu submit=%llu/%llu/%llu "
              "dropped=%llu/%llu",
              entries[0], exits[0], notable[0], entries[1], exits[1], notable[1],
              entries[2], exits[2], notable[2], entries[3], exits[3], notable[3],
              entries[4], exits[4], notable[4], submissionTrace.records().dropped(),
              submissionTrace.notableRecords().dropped());
        ++summaryRecords;
        dirty = false;
        quietPolls = 0;
    }
    lastTotal = total;

    uint64_t phaseCounts[RaphaelSubmit::MapPhaseCount] {};
    uint64_t phaseDrops[RaphaelSubmit::MapPhaseCount] {};
    uint64_t phaseTotal = 0;
    for (size_t index = 1; index < RaphaelSubmit::MapPhaseCount; ++index) {
        auto phase = static_cast<RaphaelSubmit::MapPhase>(index);
        phaseCounts[index] = submissionMapPhases.count(phase);
        phaseDrops[index] = submissionMapPhases.samples(phase).dropped();
        phaseTotal += phaseCounts[index];
    }
    if (phaseTotal != lastPhaseTotal) {
        phaseDirty = true;
        phaseQuietPolls = 0;
    } else if (phaseDirty && phaseQuietPolls < 10) {
        ++phaseQuietPolls;
    }
    bool initialPhase = phaseSummaryRecords == 0 &&
        __atomic_load_n(&submissionTraceRoutesReady, __ATOMIC_ACQUIRE);
    bool settledPhase = phaseDirty && phaseQuietPolls >= 10;
    if (phaseSummaryRecords < RaphaelSubmit::MapPhaseSummaryLimit &&
        (initialPhase || settledPhase)) {
        CRLOG("SUB: map-phase-summary total=%llu capacity=%llu va=%llu "
              "backing-pte=%llu unknown=%llu dropped=%llu/%llu/%llu/%llu",
              phaseTotal, phaseCounts[1], phaseCounts[2], phaseCounts[3],
              phaseCounts[4], phaseDrops[1], phaseDrops[2], phaseDrops[3],
              phaseDrops[4]);
        ++phaseSummaryRecords;
        phaseDirty = false;
        phaseQuietPolls = 0;
    }
    lastPhaseTotal = phaseTotal;
}

static void publishPendingVmObservations() {
    static size_t programCursor = 0;
    static size_t submitCursor = 0;
    static RaphaelVm::PreparedRequest programCache[8] {};
    static size_t programCount = 0;
    static uint32_t sampledSequence = 0;
    RaphaelVm::PreparedRequest program {};
    while (programCursor < vmid2Programs.size() && vmid2Programs.read(programCursor, program)) {
        ++programCursor;
        const auto &request = program.request;
        const auto *i = program.infoWords;
        const auto *w = program.words;
        CRLOG("VM: prepared hub=%u vmid=%u start=%#llx end=%#llx root=%#llx flags=%#x "
              "reprogram=%u alternate=%u info="
              "%08x,%08x,%08x,%08x,%08x,%08x,%08x,%08x,%08x,%08x words="
              "%08x,%08x,%08x,%08x,%08x,%08x,%08x,%08x,%08x,%08x,%08x,"
              "%08x,%08x,%08x,%08x,%08x,%08x,%08x,%08x,%08x,%08x",
              request.hub, request.vmid, request.start, request.end, request.root,
              request.flags, request.reprogram, program.alternate,
              i[0], i[1], i[2], i[3], i[4], i[5], i[6], i[7], i[8], i[9],
              w[0], w[1], w[2], w[3], w[4], w[5], w[6], w[7], w[8], w[9],
              w[10], w[11], w[12], w[13], w[14], w[15], w[16], w[17], w[18],
              w[19], w[20]);
        CRLOG("VM: root-repair seq=%u vmid=%u original=%#llx native=%#llx repaired=%u "
              "reason=%s prepared-match=%u",
              program.sequence, request.vmid, request.root, program.nativeRoot,
              program.rootRepaired, rootRepairReasonName(program.repairReason),
              program.preparedRootMatches);
        if (programCount < sizeof(programCache) / sizeof(programCache[0]))
            programCache[programCount++] = program;
        // This is the earliest worker-side sample, normally before SDMA dispatch
        // and therefore before a later KIQ diagnostic clears the fault latch.
        if (programCount == 1)
            reportVmid2Runtime("prepared", program.sequence, program, nullptr, false);
    }
    RaphaelSdma::SubmitInfoObservation submit {};
    while (submitCursor < vmid2Submits.size() && vmid2Submits.read(submitCursor, submit)) {
        ++submitCursor;
        const RaphaelVm::PreparedRequest *matched = nullptr;
        for (size_t n = programCount; n > 0; --n) {
            const auto &candidate = programCache[n - 1];
            if (candidate.threadToken == submit.threadToken &&
                candidate.sequence == submit.vmProgramSequence &&
                candidate.sequence < submit.eventOrder &&
                submitFitsProgram(submit, candidate)) {
                matched = &candidate;
                break;
            }
        }
        // A later prepare on the same thread can publish between the target prepare
        // and this callback. Recover the exact predecessor from the bounded copies,
        // but never pair across threads or outside the captured VM range.
        if (matched == nullptr) {
            for (size_t n = programCount; n > 0; --n) {
                const auto &candidate = programCache[n - 1];
                if (candidate.threadToken == submit.threadToken &&
                    candidate.sequence < submit.eventOrder &&
                    submitFitsProgram(submit, candidate)) {
                    matched = &candidate;
                    break;
                }
            }
        }
        submit.vmProgramSequence = matched != nullptr ? matched->sequence : 0;
        CRLOG("SD: submit vmid=%u flags=%#x entries=%u valid=%u IB0=%#llx IB1=%#llx seq=%u",
              submit.vmid, submit.flags, submit.entries, submit.layoutValid,
              submit.addresses[0], submit.addresses[1], submit.vmProgramSequence);
        if (matched == nullptr) {
            CRLOG("VM: submit-correlation refused: vmid=%u thread=%#llx no in-range program",
                  submit.vmid, static_cast<uint64_t>(submit.threadToken));
        }
        if (submit.layoutValid && matched != nullptr && sampledSequence == 0) {
            sampledSequence = matched->sequence;
            reportVmid2Runtime("dispatch+0ms", sampledSequence, *matched, &submit, true);
            IOSleep(1);
            reportVmid2Runtime("dispatch+1ms", sampledSequence, *matched, &submit, false);
            IOSleep(9);
            reportVmid2Runtime("dispatch+10ms", sampledSequence, *matched, &submit, false);
            IOSleep(90);
            reportVmid2Runtime("dispatch+100ms", sampledSequence, *matched, &submit, false);
        }
    }
    publishPendingSubmissionTrace();
}

static bool startOneSdmaEngine(void *engine) {
    auto vt = *reinterpret_cast<uint64_t **>(engine);
    auto start = reinterpret_cast<uint32_t (*)(void *)>(vt[0x148 / 8]);
    return (start(engine) & 0xff) != 0;
}

static void updateHwEngineStartTrace(void *self, bool success) {
    if (self == nullptr) return;
    auto handler = *reinterpret_cast<void **>(reinterpret_cast<uint8_t *>(self) + 0x18);
    if (handler == nullptr) return;
    auto vt = *reinterpret_cast<uint64_t **>(handler);
    auto getTrace = reinterpret_cast<uint8_t *(*)(void *)>(vt[0x178 / 8]);
    auto trace = getTrace(handler);
    if (trace == nullptr) return;
    auto field = reinterpret_cast<uint16_t *>(trace + 8);
    *field = static_cast<uint16_t>((*field & ~0x200u) | (success ? 0x200u : 0));
}

static uint32_t wrapHwEngPowerUp(void *self) {
    hwObj = self;
    if (mask & XK) startRlc();
    if (!RaphaelLifecycle::customPowerUpReady(
            (mask & XJ) != 0, self, orgHwEngPowerOff != 0))
        return FunctionCast(wrapHwEngPowerUp, orgHwEngPowerUp)(self);
    auto engines = reinterpret_cast<void **>(reinterpret_cast<uint8_t *>(self) + 0x3b0);
    size_t failed = 11;
    bool ok = RaphaelLifecycle::powerUpAll(
        engines, 11,
        [&](void *eng, size_t i) {
            auto vt = *reinterpret_cast<uint64_t **>(eng);
            auto up = reinterpret_cast<uint32_t (*)(void *)>(vt[0x138 / 8]);
            uint32_t result = up(eng) & 0xff;
            RLOG("XJ:   engine %u %-5s at %p vtable=%p powerUp -> %u",
                 static_cast<unsigned>(i), kEngineNames[i], eng,
                 reinterpret_cast<void *>(vt), result);
            return result != 0;
        },
        [&] {
            auto powerOff = reinterpret_cast<uint32_t (*)(void *)>(orgHwEngPowerOff);
            uint32_t result = powerOff(self) & 0xff;
            CRLOG("LC: partial engine power-up cleaned before DMA teardown -> %u", result);
        }, failed);
    if (!ok)
        CRLOG("LC: engine %u power-up failed; cleanup ran with guest mappings live",
              static_cast<unsigned>(failed));
    CRLOG("XJ: AMDHardware::powerUpHWEngines -> %u", ok);
    return ok ? 1u : 0u;
}

static uint32_t wrapHwEngStart(void *self) {
    uint32_t r = 0;
    auto slots = self != nullptr
        ? reinterpret_cast<void **>(reinterpret_cast<uint8_t *>(self) + 0x3b8)
        : nullptr;
    auto topology = RaphaelSdma::plan(1);
    if (sdmaTopologyEnabled && sdmaTopologyRoutesReady &&
        RaphaelSdma::ownsRepairedSlots(sdmaTopologyOwner, self, slots, 2, topology)) {
        bool success = RaphaelSdma::start(slots, 2, topology, startOneSdmaEngine);
        updateHwEngineStartTrace(self, success);
        r = success ? 1u : 0u;
        CRLOG("SD: one-instance start -> %u (SDMA0=%p SDMA1=%p)", r,
              slots[0], slots[1]);
    } else {
        r = FunctionCast(wrapHwEngStart, orgHwEngStart)(self);
    }
    CRLOG("XJ: AMDHardware::startHWEngines -> %u", r & 0xff);
    return r;
}

static uint32_t wrapHwEngStop(void *self) {
    auto result = FunctionCast(wrapHwEngStop, orgHwEngStop)(self);
    CRLOG("LC: AMDHardware::stopHWEngines -> %u", result & 0xff);
    return result;
}

static uint32_t wrapHwEngPowerOff(void *self) {
    auto result = FunctionCast(wrapHwEngPowerOff, orgHwEngPowerOff)(self);
    CRLOG("LC: AMDHardware::powerOffHWEngines -> %u", result & 0xff);
    return result;
}

static uint32_t wrapHwPowerOff(void *self) {
    CRLOG("LC: AMDHardware::powerOff enter");
    auto result = FunctionCast(wrapHwPowerOff, orgHwPowerOff)(self);
    CRLOG("LC: AMDHardware::powerOff -> %u", result & 0xff);
    return result;
}

// AMDNavi23Hardware::powerUp returns false on exactly two conditions, decoded at 0x99618:
//
//     99621: cmp byte [rdi+0x30f], 0                 already-powered? -> jump to success
//     99634: call [AMDGFX10Hardware vtable + 0x218]  superclass powerUp (x6+0x73e68)
//     9963c: je  fail                                (a) superclass returned false
//     9963e: mov rdi, [r14 + 0x3b0]
//     9964f: call <safe cast to AMDPM4HWEngine>
//     99657: je  fail                                (b) [this+0x3b0] is not a PM4HWEngine
//     99659: mov byte [rax + 0x230], 1               success
//     99662: xor ebx, ebx                            fail -> returns 0
//
// It returns 0 here with the already-powered flag clear, so (a) or (b) is failing and they
// need telling apart: (a) is a hardware bring-up problem, (b) means the PM4 engine object was
// never constructed, which is an entirely different repair.
static uint32_t wrapHwPowerUp(void *self) {
    uint8_t already = self ? *(reinterpret_cast<uint8_t *>(self) + 0x30f) : 0xff;
    void *pm4 = self ? *reinterpret_cast<void **>(reinterpret_cast<uint8_t *>(self) + 0x3b0)
                     : nullptr;
    auto r = FunctionCast(wrapHwPowerUp, orgHwPowerUp)(self);
    RLOG("XJ: AMDNavi23Hardware::powerUp -> %u (already-powered=%u, PM4 engine "
         "[this+0x3b0]=%p%s)", r & 0xff, already, pm4,
         pm4 == nullptr ? "  <-- NULL: the AMDPM4HWEngine cast fails and this returns 0 "
                          "whatever the superclass did" : "");
    return r;
}

// AMDHardware::powerUp (x6+0x701ba) returns r14d and needs BOTH of these to be true:
//
//     7021a: call [vtable + 0x608]   = AMDGFX10Hardware::setVMRegisters   (x6+0x74320)
//     70222: je  fail                -> r14d = 0
//     7022a: call [vtable + 0x618]   = AMDHardware::powerUpHWEngines      (x6+0x6fe9a)
//     70235: je  fail
//     70237: mov al, 1               both true: sets the powered flags at +0x30c and +0x30f
//
// powerUpHWEngines is already routed; setVMRegisters was not, and it is the more interesting
// of the two here because it programs the very VM registers whose page-table base was found
// to be wrong.
static uintptr_t wrapGfx10SetVMRegs(void *self) {
    auto r = FunctionCast(wrapGfx10SetVMRegs, orgGfx10SetVMRegs)(self);
    RLOG("XJ: AMDGFX10Hardware::setVMRegisters -> %p  <-- pointer return; null here fails "
         "powerUp before powerUpHWEngines is even reached", reinterpret_cast<void *>(r));
    return r;
}

static uint32_t wrapGfx10PowerUp(void *self) {
    auto r = FunctionCast(wrapGfx10PowerUp, orgGfx10PowerUp)(self);
    RLOG("XJ: AMDGFX10Hardware::powerUp -> %u  <-- branch (a): 1 means the failure is the PM4 "
         "engine cast, 0 means it is here", r & 0xff);
    return r;
}

static uint32_t wrapAccPowerUpHW(void *self) {
    CRLOG("XJ: AMDGraphicsAccelerator::powerUpHW entry");
    auto r = FunctionCast(wrapAccPowerUpHW, orgAccPowerUpHW)(self);
    CRLOG("XJ: AMDGraphicsAccelerator::powerUpHW -> %u", r & 0xff);
    return r;
}

static uint32_t wrapHwMemEnable(void *self) {
    if (self != nullptr) {
        auto f = reinterpret_cast<uint8_t *>(self);
        auto q = [f](size_t o) -> uint64_t & {
            return *reinterpret_cast<uint64_t *>(f + o);
        };
        // The coordinator writes a launch-bound PENDING challenge before QEMU.
        // Activate it immediately before Apple's only two BAR0 allocators are
        // constructed. Capping both pool sizes reserves the final 16 MiB for
        // the descriptor, temporary host KIQ, and the independently validated
        // GART table. A missing/stale challenge leaves the normal sizes alone.
        if ((mask & XH) != 0) {
            auto fb = fbAperture();
            if (fb != nullptr) {
                RaphaelRecovery::Descriptor descriptor {};
                auto words = reinterpret_cast<uint32_t *>(&descriptor);
                constexpr size_t count = sizeof(descriptor) / sizeof(uint32_t);
                for (size_t i = 0; i < count; ++i)
                    words[i] = fb[RaphaelRecovery::ReservationOffset / 4 + i];
                uint64_t pool0 = q(0x40), pool1 = q(0x48);
                if (RaphaelRecovery::activate(descriptor, pool0, pool1)) {
                    q(0x40) = pool0;
                    q(0x48) = pool1;
                    for (size_t i = 0; i < count; ++i)
                        fb[RaphaelRecovery::ReservationOffset / 4 + i] = words[i];
                    bool readback = true;
                    for (size_t i = 0; i < count; ++i)
                        readback &= fb[RaphaelRecovery::ReservationOffset / 4 + i] == words[i];
                    RLOG("XH: recovery reservation ACTIVE nonce=%#llx_%016llx heap=%#llx "
                         "scratch=%#llx readback=%u", descriptor.nonceHi,
                         descriptor.nonceLo, pool0, descriptor.scratchOffset, readback);
                } else {
                    RLOG("XH: no valid pending recovery reservation; allocator sizes remain "
                         "%#llx/%#llx", q(0x40), q(0x48));
                }
            } else {
                RLOG("XH: recovery reservation unavailable: BAR0 mapping not established; "
                     "allocator sizes remain %#llx/%#llx", q(0x40), q(0x48));
            }
        }
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
    if (asicInfo == nullptr || fbApertureMode == 0) return;
    static bool done = false;
    if (done) return;
    done = true;

    uint32_t oldBase = fbRead(asicInfo, kGcFbBase) & 0xffffff;
    uint32_t oldTop  = fbRead(asicInfo, kGcFbTop) & 0xffffff;
    uint32_t oldOff  = fbRead(asicInfo, kGcFbOffset) & 0xffffff;

    // Read FB_OFFSET rather than hardcoding the carveout base: it is whatever the platform
    // firmware chose on this machine, and mode 1 is defined relative to it.
    uint32_t wantBase = (fbApertureMode == 1) ? oldOff : kFbBaseWanted;
    uint32_t wantTop  = wantBase + (oldTop - oldBase);
    if (oldBase == wantBase) return;

    fbWrite(asicInfo, kGcFbBase, wantBase);
    fbWrite(asicInfo, kGcFbTop, wantTop);
    // The system aperture marks which MC range bypasses the page tables; it is in 256 KB
    // units, so it has to follow the window rather than stay behind on the old one.
    fbWrite(asicInfo, kGcVmSysApLow, wantBase << 6);
    fbWrite(asicInfo, kGcVmSysApHigh, (wantTop << 6) | 0x3f);

    uint64_t icBase = (static_cast<uint64_t>(fbRead(asicInfo, kGcCpcIcBaseHi)) << 32) |
                      fbRead(asicInfo, kGcCpcIcBaseLo);
    uint64_t phys = icBase - (static_cast<uint64_t>(wantBase) << 24) +
                    (static_cast<uint64_t>(oldOff) << 24);
    RLOG("XP: rgpufb=%u: FB aperture %#x..%#x (offset %#x) -> %#x..%#x; sys aperture "
         "%#x..%#x; locked IC base %#llx now resolves to physical %#llx = carveout+%#llx",
         fbApertureMode, oldBase, oldTop, oldOff, fbRead(asicInfo, kGcFbBase) & 0xffffff,
         fbRead(asicInfo, kGcFbTop) & 0xffffff, fbRead(asicInfo, kGcVmSysApLow),
         fbRead(asicInfo, kGcVmSysApHigh), icBase, phys,
         phys - (static_cast<uint64_t>(oldOff) << 24));
}

static uint32_t wrapFbXgmiConfig(void *self) {
    asicInfo = self;
    relocateFbAperture();   // no-op unless rgpufb is set
    if (mask & XK) reportCpState("pre-TTL");
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
    if (self != nullptr) {
        __atomic_store_n(&cachedFbBase, fbRead(self, kGcFbBase) & 0xffffff,
                         __ATOMIC_RELAXED);
        __atomic_store_n(&cachedFbTop, fbRead(self, kGcFbTop) & 0xffffff,
                         __ATOMIC_RELAXED);
        __atomic_store_n(&cachedFbOffset, fbRead(self, kGcFbOffset) & 0xffffff,
                         __ATOMIC_RELAXED);
        __atomic_store_n(&cachedFbPublished, true, __ATOMIC_RELEASE);
    }
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

static bool entryMatches(mach_vm_address_t base, size_t imageSize, size_t offset,
                         const uint8_t *expected, size_t expectedSize) {
    if (expected == nullptr || offset > imageSize || expectedSize > imageSize - offset)
        return false;
    auto entry = reinterpret_cast<const uint8_t *>(base + offset);
    for (size_t i = 0; i < expectedSize; ++i)
        if (entry[i] != expected[i]) return false;
    return true;
}

static void processKext(void *, KernelPatcher &patcher, size_t index,
                        mach_vm_address_t addr, size_t sz) {
    RLOG("kext callback: index=%lu hwlibs=%lu fb=%lu addr=%llx size=%lu",
           index, kexts[KextHWLibs].loadIndex, kexts[KextFB].loadIndex, addr, sz);
    if (kexts[KextHWLibs].loadIndex == index) {
        RLOG("HWLibs loaded, mask=0x%x", mask);
        if (hybridProbeEnabled) {
            // Bind both offsets to HWLibs and verify complete displaced instructions.
            // Builds 160/161 used an X6000 base here and were invalid experiments.
            static const uint8_t hybridEntry[] = {0x55, 0x48, 0x89, 0xe5, 0x41, 0x57,
                0x41, 0x56, 0x41, 0x55, 0x41, 0x54, 0x53, 0x50, 0xbb, 0x02, 0, 0, 0};
            static const uint8_t availableEntry[] = {0x55, 0x48, 0x89, 0xe5, 0x53, 0x50,
                0x48, 0x89, 0xfb, 0xe8, 0x66, 0x81, 0xfe, 0xff};
            bool matches = kOffTtlHybrid + sizeof(hybridEntry) <= sz &&
                           kOffTtlAvailable + sizeof(availableEntry) <= sz;
            auto hybrid = reinterpret_cast<const uint8_t *>(addr + kOffTtlHybrid);
            auto available = reinterpret_cast<const uint8_t *>(addr + kOffTtlAvailable);
            for (size_t i = 0; matches && i < sizeof(hybridEntry); i++)
                matches = hybrid[i] == hybridEntry[i];
            for (size_t i = 0; matches && i < sizeof(availableEntry); i++)
                matches = available[i] == availableEntry[i];
            if (matches) {
                addrTtlAvailable = addr + kOffTtlAvailable;
                orgTtlHybrid = patcher.routeFunction(addr + kOffTtlHybrid,
                    reinterpret_cast<mach_vm_address_t>(wrapTtlHybrid), true);
            }
            CRLOG("HY: HWLibs hybrid trace route=%s entries-match=%u (max 8 calls)",
                 orgTtlHybrid ? "ok" : "OFF", matches);
            patcher.clearError();
            // Exactly 16 complete, position-independent bytes. The first
            // conditional branch starts at +16 and is not displaced.
            static const uint8_t selectEntry[] = {0x55, 0x48, 0x89, 0xe5,
                0x44, 0x8b, 0x47, 0x2c, 0x45, 0x31, 0xc9, 0x89, 0xd1, 0x4d, 0x85, 0xc0};
            bool selectMatches = kOffSdmaFindInstance + sizeof(selectEntry) <= sz;
            auto select = reinterpret_cast<const uint8_t *>(addr + kOffSdmaFindInstance);
            for (size_t i = 0; selectMatches && i < sizeof(selectEntry); ++i)
                selectMatches = select[i] == selectEntry[i];
            if (orgTtlHybrid && selectMatches) {
                sdmaTraceBase = addr; sdmaTraceSize = sz;
                orgSdmaFindInstance = patcher.routeFunction(addr + kOffSdmaFindInstance,
                    reinterpret_cast<mach_vm_address_t>(wrapSdmaFindInstance), true);
            }
            CRLOG("HY: SDMA selector trace route=%s entries-match=%u (max 8 hybrid calls)",
                  orgSdmaFindInstance ? "ok" : "OFF", selectMatches);
            patcher.clearError();
        }
        applyFor(patcher, true);
        RLOG("post-patch: mask=0x%x D1=%d R1=%d base=0x%llx",
               mask, (mask & D1) != 0, (mask & R1) != 0, addr);
#if defined(RGPU_HAVE_RLC_FW) && RGPU_HAVE_TOC_FW
        if (mask & XB) substituteToc(patcher);
#endif
        if (mask & (D1 | R1 | X1 | X2 | X3 | X4 | X5 | X6 | X7 | X8 | XA | XC | XE | XF)) installDiagnostics(patcher, addr);
        if (ptbFixMode == 2) {
            hwlibsBase = addr;
            if (mqdFixMode == 2) {
                static const uint8_t readEntry[] = {0x55, 0x48, 0x89, 0xe5, 0x4c, 0x8b, 0x47,
                    0x08, 0x49, 0x8b, 0x80, 0x18, 0x01, 0x00, 0x00};
                nativeGcReadVerified = kOffGcCgsRead2 + sizeof(readEntry) <= sz;
                auto entry = reinterpret_cast<const uint8_t *>(addr + kOffGcCgsRead2);
                for (size_t i = 0; nativeGcReadVerified && i < sizeof(readEntry); i++)
                    nativeGcReadVerified = entry[i] == readEntry[i];
                RLOG("XQ3: native GC read entry verified=%u; EOP trace capped at8 writes",
                     nativeGcReadVerified);
            }
            // Verify the exact trampoline footprint before routing this new ABI.
            static const uint8_t prologue[] = {0x55, 0x48, 0x89, 0xe5, 0x41, 0x56, 0x53,
                                               0x48, 0x83, 0xec, 0x10, 0x48, 0x89, 0xfb};
            bool matches = kOffVmPhysicalFb + sizeof(prologue) <= sz;
            auto entry = reinterpret_cast<const uint8_t *>(addr + kOffVmPhysicalFb);
            for (size_t i = 0; matches && i < sizeof(prologue); i++)
                matches = entry[i] == prologue[i];
            if (matches) orgVmPhysicalFb = patcher.routeFunction(addr + kOffVmPhysicalFb,
                reinterpret_cast<mach_vm_address_t>(wrapVmPhysicalFb), true);
            RLOG("XT2: route vm_10_1_get_uma_physical_fb_offset -> %s (prologue=%u org=%#llx)",
                 orgVmPhysicalFb ? "ok" : "FAILED", matches, orgVmPhysicalFb);
            patcher.clearError();
        }
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
        if ((mask & XG) || vmRootFixEnabled) {
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
        x6Base = addr;
        if (vmmProbeMode != 0 || memProbeMode != 0 || ptbFixMode != 0 ||
            vmRootFixEnabled) {
            orgVmmInit = patcher.routeFunction(addr + kOffVmmInit,
                           reinterpret_cast<mach_vm_address_t>(wrapVmmInit), true);
            RLOG("route AMDHWVMM::init -> %s (org=0x%llx)",
                 orgVmmInit ? "ok" : "FAILED", orgVmmInit);
            patcher.clearError();
            orgVmmSetAlloc = patcher.routeFunction(addr + kOffVmmSetAlloc,
                               reinterpret_cast<mach_vm_address_t>(wrapVmmSetAlloc), true);
            RLOG("route AMDHWVMM::setMemoryAllocationsEnabled -> %s (org=0x%llx)",
                 orgVmmSetAlloc ? "ok" : "FAILED", orgVmmSetAlloc);
            patcher.clearError();
            orgVmmFillRegs = patcher.routeFunction(addr + kOffVmmFillRegs,
                             reinterpret_cast<mach_vm_address_t>(wrapVmmFillRegs), true);
            RLOG("route AMDGFX10VMM::fillVMRegisters -> %s (org=0x%llx)",
                 orgVmmFillRegs ? "ok" : "FAILED", orgVmmFillRegs);
            patcher.clearError();
            orgVmmPrepare = patcher.routeFunction(addr + kOffVmmPrepare,
                            reinterpret_cast<mach_vm_address_t>(wrapVmmPrepare), true);
            CRLOG("VM: route AMDGFX10VMM::prepareVMInvalidateRequest -> %s (org=0x%llx)",
                  orgVmmPrepare ? "ok" : "FAILED", orgVmmPrepare);
            patcher.clearError();
            if (ptbFixMode != 2) {
                orgVmmProgInv = patcher.routeFunction(addr + kOffVmmProgInv,
                                reinterpret_cast<mach_vm_address_t>(wrapVmmProgInv), true);
                RLOG("route AMDGFX10VMM::programAndInvalidateVM -> %s (org=0x%llx)",
                     orgVmmProgInv ? "ok" : "FAILED", orgVmmProgInv);
                patcher.clearError();
            }
            orgHwMemSetVSReady = patcher.routeFunction(addr + kOffHwMemSetVSReady,
                                 reinterpret_cast<mach_vm_address_t>(wrapHwMemSetVSReady), true);
            RLOG("route AMDHWMemory::setVirtualSpaceReady -> %s (org=0x%llx)",
                 orgHwMemSetVSReady ? "ok" : "FAILED", orgHwMemSetVSReady);
            patcher.clearError();
            orgVmmSetVSReady = patcher.routeFunction(addr + kOffVmmSetVSReady,
                                 reinterpret_cast<mach_vm_address_t>(wrapVmmSetVSReady), true);
            RLOG("route AMDHWVMM::setVirtualSpaceReady -> %s (org=0x%llx)",
                 orgVmmSetVSReady ? "ok" : "FAILED", orgVmmSetVSReady);
            patcher.clearError();
        }
        if (mask & XJ) {
            struct { size_t off; mach_vm_address_t *org; void *fn; const char *name; } t[] {
                {kOffAccPowerUpHW, &orgAccPowerUpHW,
                 reinterpret_cast<void *>(wrapAccPowerUpHW), "AMDGraphicsAccelerator::powerUpHW"},
                {kOffHwPowerUp, &orgHwPowerUp,
                 reinterpret_cast<void *>(wrapHwPowerUp), "AMDNavi23Hardware::powerUp"},
                {kOffGfx10PowerUp, &orgGfx10PowerUp,
                 reinterpret_cast<void *>(wrapGfx10PowerUp), "AMDGFX10Hardware::powerUp"},
                {kOffGfx10SetVMRegs, &orgGfx10SetVMRegs,
                 reinterpret_cast<void *>(wrapGfx10SetVMRegs), "AMDGFX10Hardware::setVMRegisters"},
                {kOffHwEngPowerUp, &orgHwEngPowerUp,
                 reinterpret_cast<void *>(wrapHwEngPowerUp), "AMDHardware::powerUpHWEngines"},
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
        if (submissionTraceEnabled) {
            // Each pattern ends on an instruction boundary and stops before the
            // first RIP-relative instruction. They are exact for 24G830.
            static const uint8_t processEntry[] = {0x55, 0x48, 0x89, 0xe5, 0x41,
                0x57, 0x41, 0x56, 0x41, 0x54, 0x53, 0x41, 0x89, 0xd6, 0x41, 0x89, 0xf7};
            static const uint8_t mappingsEntry[] = {0x55, 0x48, 0x89, 0xe5, 0x41,
                0x57, 0x41, 0x56, 0x41, 0x55, 0x41, 0x54, 0x53, 0x48, 0x83, 0xec, 0x18};
            static const uint8_t prepareEntry[] = {0x55, 0x48, 0x89, 0xe5, 0x41,
                0x57, 0x41, 0x56, 0x41, 0x55, 0x41, 0x54, 0x53, 0x48, 0x83, 0xec, 0x68};
            static const uint8_t mapEntry[] = {0x55, 0x48, 0x89, 0xe5, 0x41, 0x57,
                0x41, 0x56, 0x53, 0x50, 0x48, 0x89, 0xf3, 0x49, 0x89, 0xfe};
            static const uint8_t submitEntry[] = {0x55, 0x48, 0x89, 0xe5, 0x41,
                0x57, 0x41, 0x56, 0x41, 0x55, 0x41, 0x54, 0x53, 0x48, 0x81, 0xec,
                0x08, 0x01, 0x00, 0x00};
            bool entriesMatch =
                entryMatches(addr, sz, kOffProcessCommandBuffer,
                             processEntry, sizeof(processEntry)) &&
                entryMatches(addr, sz, kOffBatchPrepareMappings,
                             mappingsEntry, sizeof(mappingsEntry)) &&
                entryMatches(addr, sz, kOffBatchPrepare,
                             prepareEntry, sizeof(prepareEntry)) &&
                entryMatches(addr, sz, kOffBatchMemoryMapPrepare,
                             mapEntry, sizeof(mapEntry)) &&
                entryMatches(addr, sz, kOffSubmitBuffer,
                             submitEntry, sizeof(submitEntry));
            if (entriesMatch) {
                struct { size_t off; mach_vm_address_t *org; void *fn; const char *name; } t[] {
                    {kOffProcessCommandBuffer, &orgProcessCommandBuffer,
                     reinterpret_cast<void *>(wrapProcessCommandBuffer), "processCommandBuffer"},
                    {kOffBatchPrepareMappings, &orgBatchPrepareMappings,
                     reinterpret_cast<void *>(wrapBatchPrepareMappings), "BatchPrepareMappings"},
                    {kOffBatchPrepare, &orgBatchPrepare,
                     reinterpret_cast<void *>(wrapBatchPrepare), "BatchPrepare"},
                    {kOffBatchMemoryMapPrepare, &orgBatchMemoryMapPrepare,
                     reinterpret_cast<void *>(wrapBatchMemoryMapPrepare), "batchMemoryMapPrepare"},
                    {kOffSubmitBuffer, &orgSubmitBuffer,
                     reinterpret_cast<void *>(wrapSubmitBuffer), "submitBuffer"},
                };
                for (auto &e : t) {
                    *e.org = patcher.routeFunction(addr + e.off,
                                 reinterpret_cast<mach_vm_address_t>(e.fn), true);
                    CRLOG("SUB: route %s -> %s (org=%#llx)", e.name,
                          *e.org ? "ok" : "FAILED", *e.org);
                    patcher.clearError();
                }
            }
            bool ready = entriesMatch && orgProcessCommandBuffer &&
                orgBatchPrepareMappings && orgBatchPrepare && orgBatchMemoryMapPrepare &&
                orgSubmitBuffer;
            __atomic_store_n(&submissionTraceRoutesReady, ready, __ATOMIC_RELEASE);
            CRLOG("SUB: routes=%s count=5 entries-match=%u capture=%s",
                  ready ? "ok" : "FAILED", entriesMatch, ready ? "armed" : "disabled");
        }
        // Exact complete instructions displaced by the five new X6000 routes.
        // The start/powerOff patterns extend to 21 bytes because byte 16 is in
        // the middle of their first memory-operand instruction.
        static const uint8_t engInitEntry[] = {0x55, 0x48, 0x89, 0xe5, 0x41, 0x57,
            0x41, 0x56, 0x53, 0x50, 0x49, 0x89, 0xfe, 0x45, 0x31, 0xff};
        static const uint8_t engPowerOffEntry[] = {0x55, 0x48, 0x89, 0xe5, 0x41, 0x57,
            0x41, 0x56, 0x53, 0x50, 0x49, 0x89, 0xfe, 0x45, 0x31, 0xff};
        static const uint8_t engStartEntry[] = {0x55, 0x48, 0x89, 0xe5, 0x41, 0x57,
            0x41, 0x56, 0x41, 0x54, 0x53, 0x48, 0x89, 0xfb, 0x0f, 0xb6,
            0x87, 0xc2, 0x00, 0x00, 0x00};
        static const uint8_t engStopEntry[] = {0x55, 0x48, 0x89, 0xe5, 0x41, 0x57,
            0x41, 0x56, 0x53, 0x50, 0x49, 0x89, 0xfe, 0x45, 0x31, 0xff};
        static const uint8_t hwPowerOffEntry[] = {0x55, 0x48, 0x89, 0xe5, 0x41, 0x57,
            0x41, 0x56, 0x41, 0x54, 0x53, 0x48, 0x89, 0xfb, 0x80, 0xbf,
            0x31, 0x05, 0x00, 0x00, 0x01};
        static const uint8_t hwGetChannelEntry[] = {0x55, 0x48, 0x89, 0xe5, 0x89, 0xf0,
            0x48, 0x8b, 0xbc, 0xc7, 0xb0, 0x03, 0x00, 0x00, 0x48, 0x85, 0xff};
        static const uint8_t sdmaCommitIbEntry[] = {0x55, 0x48, 0x89, 0xe5, 0x41, 0x57,
            0x41, 0x56, 0x53, 0x48, 0x81, 0xec, 0x08, 0x02, 0x00, 0x00};
        bool engInitMatches = entryMatches(addr, sz, kOffHwEngInit,
                                           engInitEntry, sizeof(engInitEntry));
        bool engPowerOffMatches = entryMatches(addr, sz, kOffHwEngPowerOff,
                                               engPowerOffEntry, sizeof(engPowerOffEntry));
        bool engStartMatches = entryMatches(addr, sz, kOffHwEngStart,
                                            engStartEntry, sizeof(engStartEntry));
        bool engStopMatches = entryMatches(addr, sz, kOffHwEngStop,
                                           engStopEntry, sizeof(engStopEntry));
        bool hwPowerOffMatches = entryMatches(addr, sz, kOffHwPowerOff,
                                              hwPowerOffEntry, sizeof(hwPowerOffEntry));
        bool hwGetChannelMatches = entryMatches(addr, sz, kOffHwGetChannel,
                                                hwGetChannelEntry,
                                                sizeof(hwGetChannelEntry));
        bool sdmaCommitIbMatches = entryMatches(addr, sz, kOffSdmaCommitIb,
                                                sdmaCommitIbEntry,
                                                sizeof(sdmaCommitIbEntry));
        bool sdmaEntriesMatch = engInitMatches && engPowerOffMatches && engStartMatches &&
                                engStopMatches && hwPowerOffMatches && hwGetChannelMatches &&
                                sdmaCommitIbMatches;
        if (((mask & XJ) || sdmaTopologyEnabled) && engStartMatches &&
            (!sdmaTopologyEnabled || sdmaEntriesMatch)) {
            orgHwEngStart = patcher.routeFunction(addr + kOffHwEngStart,
                              reinterpret_cast<mach_vm_address_t>(wrapHwEngStart), true);
            RLOG("route AMDHardware::startHWEngines -> %s entries-match=%u (org=0x%llx)",
                 orgHwEngStart ? "ok" : "FAILED", engStartMatches, orgHwEngStart);
            patcher.clearError();
        }
        if (sdmaTopologyEnabled) {
            struct { size_t off; mach_vm_address_t *org; void *fn; const char *name; } t[] {
                {kOffHwEngInit, &orgHwEngInit,
                 reinterpret_cast<void *>(wrapHwEngInit), "AMDHardware::initializeHWEngines"},
                {kOffHwEngStop, &orgHwEngStop,
                 reinterpret_cast<void *>(wrapHwEngStop), "AMDHardware::stopHWEngines"},
                {kOffHwEngPowerOff, &orgHwEngPowerOff,
                 reinterpret_cast<void *>(wrapHwEngPowerOff), "AMDHardware::powerOffHWEngines"},
                {kOffHwPowerOff, &orgHwPowerOff,
                 reinterpret_cast<void *>(wrapHwPowerOff), "AMDHardware::powerOff"},
                {kOffHwGetChannel, &orgHwGetChannel,
                 reinterpret_cast<void *>(wrapHwGetChannel), "AMDHardware::getHWChannel"},
                {kOffSdmaCommitIb, &orgSdmaCommitIb,
                 reinterpret_cast<void *>(wrapSdmaCommitIb),
                 "AMDGFX10SDMAChannel::commitIndirectCommandBuffer"},
            };
            for (auto &e : t) {
                if (sdmaEntriesMatch)
                    *e.org = patcher.routeFunction(addr + e.off,
                                 reinterpret_cast<mach_vm_address_t>(e.fn), true);
                CRLOG("SD: route %s -> %s (org=0x%llx)", e.name,
                      *e.org ? "ok" : "FAILED", *e.org);
                patcher.clearError();
            }
            sdmaTopologyRoutesReady = sdmaEntriesMatch && orgHwEngStart && orgHwEngInit &&
                                      orgHwEngStop && orgHwEngPowerOff && orgHwPowerOff &&
                                      orgHwGetChannel && orgSdmaCommitIb;
            CRLOG("SD: topology routes=%s count=7 entries-match=%u",
                  sdmaTopologyRoutesReady ? "ok" : "FAILED", sdmaEntriesMatch);
        }
    }
}

static void pluginStart() {
    CRLOG("BUILD: identity=%s", RGPU_BUILD_ID);
    if (!PE_parse_boot_argn("rgpu", &mask, sizeof(mask))) mask = 0;
    uint32_t d = 0;
    // Its own boot-arg rather than a mask bit: this is the one thing here that can take the
    // host with it, so it should not be reachable by editing a hex mask.
    uint32_t rst = 0;
    uint32_t hybridProbe = 0;
    hybridProbeEnabled = PE_parse_boot_argn("rgpuhybrid", &hybridProbe, sizeof(hybridProbe)) &&
                         hybridProbe == 1;
    RLOG("rgpuhybrid=%u: guarded hybrid-engine diagnostics %s", hybridProbeEnabled,
         hybridProbeEnabled ? "enabled" : "disabled");
    uint32_t sdmaTopology = 0;
    sdmaTopologyEnabled = PE_parse_boot_argn("rgpusdma", &sdmaTopology,
                                             sizeof(sdmaTopology)) && sdmaTopology == 1;
    RLOG("rgpusdma=%u: Raphael one-instance SDMA topology correction %s",
         sdmaTopologyEnabled, sdmaTopologyEnabled ? "enabled" : "disabled");
    uint32_t submissionTrace = 0;
    submissionTraceEnabled = PE_parse_boot_argn("rgpusubmit", &submissionTrace,
                                                sizeof(submissionTrace)) &&
        submissionTrace == 1;
    RLOG("rgpusubmit=%u: bounded 24G830 pre-submission tracing %s",
         submissionTraceEnabled, submissionTraceEnabled ? "enabled" : "disabled");
    uint32_t cps = 0;
    if (PE_parse_boot_argn("rgpucp", &cps, sizeof(cps)) && cps == 1) {
        cpSurgeryEnabled = true;
        RLOG("rgpucp=1: command-processor workarounds enabled (aperture move, MEC microcode "
             "reload, GART rewrite, MEC halt) -- only correct on a CP locked by the PSP");
    } else {
        RLOG("rgpucp not set: leaving the command processor alone (correct for a device the "
             "firmware still owns)");
    }
    uint32_t mqdm = 0;
    if (PE_parse_boot_argn("rgpumqd", &mqdm, sizeof(mqdm)) && mqdm <= 2) {
        mqdFixMode = mqdm;
        RLOG("rgpumqd=%u: %s", mqdm, mqdm == 2
             ? "validate KIQ before start; genuine dequeue and native MEC halt writes preserved"
             : mqdm == 1 ? "legacy post-timeout MQD/EOP repair" : "reporting only");
    }
    uint32_t ptbm = 0;
    if (PE_parse_boot_argn("rgpuptb", &ptbm, sizeof(ptbm)) && ptbm <= 2) {
        ptbFixMode = ptbm;
        RLOG("rgpuptb=%u: %s", ptbm, ptbm == 2
             ? "validated native physical framebuffer getter; no manual PTB writes"
             : ptbm == 1 ? "legacy post-invalidation PTB experiment" : "reporting only");
    }
    uint32_t vmroot = 0;
    vmRootFixEnabled = PE_parse_boot_argn("rgpuvmroot", &vmroot, sizeof(vmroot)) &&
        vmroot == 1;
    RLOG("rgpuvmroot=%u: VMID2 GFXHUB root MC-to-physical repair %s; child PDEs remain "
         "diagnostic-only until the bounded BAR0 walk proves their address form",
         vmRootFixEnabled, vmRootFixEnabled ? "ARMED" : "off");
    uint32_t mem = 0;
    if (PE_parse_boot_argn("rgpumem", &mem, sizeof(mem)) && mem <= 2) {
        memProbeMode = mem;
        RLOG("rgpumem=%u: %s AMDHWMemory's pool pointers at +0x68/+0x70, which are what "
             "enableAllocations gates on and which have never been logged", mem,
             mem >= 2 ? "report and act on" : "report");
    }
    uint32_t vmp = 0;
    if (PE_parse_boot_argn("rgpuvmm", &vmp, sizeof(vmp)) && vmp <= 3) {
        vmmProbeMode = vmp;
        if (vmp == 1)
            RLOG("rgpuvmm=1: observing AMDHWVMM::init and setMemoryAllocationsEnabled, to "
                 "see why the DMA paging channel at m_0x28 is never built");
        else if (vmp == 2)
            RLOG("rgpuvmm=2: as 1, and m_0x20 is cleared so the idempotency guard falls "
                 "through -- UNNECESSARY, m_0x20 was measured as 0 after init, the guard is "
                 "already open and the real problem is that nobody passes true");
        else if (vmp == 3)
            RLOG("rgpuvmm=3: as 1, and setMemoryAllocationsEnabled(true) is driven from "
                 "setVirtualSpaceReady(true) so the DMA paging channel gets built");
    }
    uint32_t rlp = 0;
    if (PE_parse_boot_argn("rgpurlc", &rlp, sizeof(rlp)) && (rlp == 1 || rlp == 2)) {
        rlcProbeEnabled = true;
        rlcProbeEnabled2 = (rlp == 2);
        if (rlp == 2)
            RLOG("rgpurlc=2: the RLC_ENABLE cycle is ARMED, and it is known to stop a "
                 "working RLC without restarting it");
        RLOG("rgpurlc=1: the RLC will be dumped, probed for writability, and asked to "
             "acknowledge safe mode; if RLC_CNTL is writable the F32 is restarted");
    }
    uint32_t icp = 0;
    if (PE_parse_boot_argn("rgpuic", &icp, sizeof(icp)) && icp == 1) {
        icachePrimeEnabled = true;
        RLOG("rgpuic=1: after TTL the CP instruction cache is asked to prime, with controls "
             "for whether writes land and whether the invalidate command executes at all");
    }
    uint32_t fbm = 0;
    if (PE_parse_boot_argn("rgpufb", &fbm, sizeof(fbm)) && fbm <= 2) {
        fbApertureMode = fbm;
        if (fbm == 1)
            RLOG("rgpufb=1: FB_LOCATION_BASE will be set equal to FB_OFFSET, so MC == "
                 "physical across the carveout -- the configuration the host itself runs, "
                 "and the one in which the PSP's own autoloaded microcode is reachable");
        else if (fbm == 2)
            RLOG("rgpufb=2: FB_LOCATION_BASE -> 0x850000000, bringing the locked IC base "
                 "inside BAR0 so the plugin can write microcode there (needs rgpucp=1)");
    }
    if (PE_parse_boot_argn("rgpureset", &rst, sizeof(rst)) && rst == 1) {
        pspResetRequested = true;
        RLOG("rgpureset=1: a PSP MODE1 reset will be issued before the PSP ring is created");
    }
    if (mqdFixMode == 2 && (cpSurgeryEnabled || pspResetRequested || icachePrimeEnabled ||
                            rlcProbeEnabled || fbApertureMode != 0)) {
        RLOG("XQ2: disabling conflicting experiments: rgpucp=%u rgpureset=%u rgpuic=%u "
             "rgpurlc=%u rgpufb=%u; mode 2 performs queue preparation only",
             cpSurgeryEnabled, pspResetRequested, icachePrimeEnabled, rlp, fbApertureMode);
        cpSurgeryEnabled = false;
        pspResetRequested = false;
        icachePrimeEnabled = false;
        rlcProbeEnabled = false;
        rlcProbeEnabled2 = false;
        fbApertureMode = 0;
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
    if (kernel_thread_start(vmObservationThread, nullptr, &th) == KERN_SUCCESS)
        thread_deallocate(th);
    else
        RLOG("could not start the VM observation thread");
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
