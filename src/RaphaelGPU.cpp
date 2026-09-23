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
#include <IOKit/IOMemoryDescriptor.h>
#include <kern/clock.h>
#include <kern/thread.h>
#include <kern/task.h>
#include <mach/task_info.h>
#include <mach/mach_vm.h>
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
#include "MmhubRegisters.hpp"
#include "VcnPlatformPower.hpp"
#include "GfxHangDump.hpp"
#include "VmEntryUpdate.hpp"
#include "VmProgramCorrelation.hpp"
#include "ObservationBuffer.hpp"
#include "SubmissionTrace.hpp"
#include "BackingTrace.hpp"
#include "EngineLifecycle.hpp"
#include "TextureDiagParser.hpp"
#include "RecoveryReservation.hpp"
#include "RecoveryLease.hpp"
#include "RecoveryLifetime.hpp"
#include "CriticalReplay.hpp"
#include "CriticalUart.hpp"
#include "AllocationLogBudget.hpp"
#include "DcnTranslation.hpp"
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
// Candidate submission tracing can add at most 211 records: 64 ordinary, 32
// notable, 32 original summaries, 8 phase samples, 32 phase summaries, four
// backing-allocation samples, 32 backing summaries and seven route/readiness
// records. Mode 4 adds at most 69 exponential/safety summaries, 24 returned-call
// samples, eight submit-correlation records and one route record. 512 retains
// that bounded set alongside the existing VM/SDMA evidence budget.
static rgpu::DiagnosticRecords<rgpu::kCriticalRecordCapacity, 512> criticalRecords {};
static bool criticalUartEnabled = false;
static bool criticalUartQuiesceEnabled = false;
static rgpu::SuccessRecordBudget waitStampRecordBudget {};
static rgpu::SuccessRecordBudget kiqSubmitRecordBudget {};
static rgpu::SuccessRecordBudget preClearFaultRecordBudget {};
static rgpu::SuccessRecordBudget feedbackCowRecordBudget {};
static rgpu::SuccessRecordBudget vcnCowRecordBudget {};
static rgpu::SuccessRecordBudget vcnPresetCowRecordBudget {};
static rgpu::ObservationBuffer<RaphaelVm::PreparedRequest, 8> vmid2Programs {};
static rgpu::ObservationBuffer<RaphaelSdma::SubmitInfoObservation, 8> vmid2Submits {};
static RaphaelSubmit::Store<64, 32> submissionTrace {};
static RaphaelSubmit::MapPhaseStore<RaphaelSubmit::MapSamplesPerPhase>
    submissionMapPhases {};
static RaphaelSubmit::CommitStore<32> submissionCommits {};
static RaphaelBacking::Store<4> submissionBackingAllocations {};
static volatile uint32_t nextSubmissionTraceSequence = 0;
static bool submissionTraceEnabled = false;
static volatile bool submissionTraceRoutesReady = false;
static bool vmRootFixEnabled = false;
static bool vmFaultDiagEnabled = false;
// rgpuvmroot: enabled modes repair hub-0 client roots (VMIDs 1..15) while leaving
// VMID0's legacy GART alone; 2/3 retain the historical template hooks; 4 converts
// the separately supplied real entry source at the SDMA update boundary verified
// in X6000 24G830. Mode 5 retains mode 4 and additionally repairs the independent
// MES MAP_PROCESS page-table-base field after native packet construction.
static uint32_t vmRootFixMode = 0;
static bool mmhubFixEnabled = false;
static bool vcnFirmwareEnabled = false;
static bool vcnApuEnabled = false;
static bool vcnStaticEnabled = false;
static bool vcnSmuEnabled = false;
static uint32_t vcnClockMHz = 0; // rgpuvcnclk=<MHz>: opt-in SetHardMinVcn/SetSoftMaxVcn after PowerUpVcn
static bool smuQueryEnabled = false; // rgpusmuquery=1: read-only GetGfxclkFrequency/GetEnabledSmuFeatures
static uint32_t gfxClockMHz = 0; // rgpugfxclk=<MHz>: opt-in SetHardMinGfxClk after PowerUpVcn
static uint32_t dcnClockMHz = 0; // rgpudclk=<MHz>: opt-in DCLK SetHardMinVcn/SetSoftMaxVcn
static bool vcnResetEnabled = false;
static bool vcnDpgEnabled = false;
static bool vcnDecodeFirstEnabled = false;
static bool vcnNoDpmEnabled = false;
static bool vcnWptrEnabled = false;
// rgpuvcnpreset=1: force RENCODE_IB_OP_SET_BALANCE_ENCODING_MODE in
// AMDRadeonVADriver2 via the same current-task COW path as kVcnDpmTarget.
// Effective only when the existing vcnNoDpmEnabled/ppCompatibilityBypassed
// gate also holds, so it runs in the same video process at the same moment.
static bool vcnPresetEnabled = false;
static mach_vm_address_t orgVcnDecodeSubmit = 0;
static uint32_t vcnDecodeSubmitCalls = 0;
static bool ppCompatibilityBypassed = false;
static mach_vm_address_t orgVcnWriteRegister = 0;
static mach_vm_address_t orgAddToDpgSram = 0;
static IOLock *vcnSmuLock = nullptr;
static mach_vm_address_t orgVcnConfig = 0;
static mach_vm_address_t orgVcnInitialize = 0;
static mach_vm_address_t orgVcnQueryFw = 0;
static bool vcnSharedSizeReady = false;
#include "VcnFirmware.hpp"
#include "VcnDpgClock.hpp"
#include "VcnDpgReadback.hpp"
static mach_vm_address_t orgVcnReadFw = 0;
static mach_vm_address_t orgVcnHwInit = 0;
static volatile bool mmhubTableCorrect = false;
static rgpu::ObservationBuffer<RaphaelVm::PreparedRequest, 8> mmhubPrograms {};
static mach_vm_address_t orgVmmGetPde {};
static mach_vm_address_t orgVmmGetPte {};
static mach_vm_address_t orgVmmUpdateEntries {};
static mach_vm_address_t orgFillMapProcess {};
// Page-table entry conversions: lifetime counters per kind and domain, plus a
// bounded first-sample buffer per kind. Producers never log, allocate or wait.
static volatile uint64_t vmEntryCounts[2][RaphaelVm::kEntryDomainCount] {};
// Calls that arrived before the aperture snapshot and Raphael marker were
// both published pass through unconverted; count them so a silent early
// producer cannot hide behind the active-phase counters.
static volatile uint64_t vmEntryInactive[2] {};
static rgpu::ObservationBuffer<RaphaelVm::EntryConversionSample, 8> vmEntrySamples[2] {};
static rgpu::ObservationBuffer<RaphaelVm::MapProcessObservation, 8> vmMapProcessSamples {};
static volatile uint64_t vmUpdateCounts[RaphaelVm::kUpdateDomainCount] {};
static rgpu::ObservationBuffer<RaphaelVm::EntryUpdateDecision, 8> vmUpdateChildSamples {};
static rgpu::ObservationBuffer<RaphaelVm::EntryUpdateDecision, 8> vmUpdateEligibleSamples {};
static rgpu::ObservationBuffer<RaphaelVm::EntryUpdateDecision, 8> vmUpdateControlSamples {};
static volatile bool raphaelTargetConfirmed = false;
// Published once by the early framebuffer callback and read later by the VM
// callback. Keeping this snapshot avoids MMIO under X6000's unknown VM locks.
static volatile uint32_t cachedFbBase = 0;
static volatile uint32_t cachedFbTop = 0;
static volatile uint32_t cachedFbOffset = 0;
static volatile bool cachedFbPublished = false;
static volatile uint32_t nextVmObservationSequence = 0;
static volatile uint32_t latestVmid2ProgramSequence = 0;
static RaphaelVm::FaultObservationStore<2> clientFaults {};

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

// Every sample still reaches ordinary serial; only successful critical samples
// are bounded. Failures retain their existing capture-fatal behavior.
#define SAMPLED_CRLOG(budget, success, fmt, ...) do { \
    diagAppend((budget).take((success), 4), fmt, ## __VA_ARGS__); \
    SYSLOG("rgpu", fmt, ## __VA_ARGS__); \
} while (0)

// One exact 24G830 allocation-failure call site, not a global kprintf hook.
// Native allocation attempts, false returns and per-pool counters remain untouched.
static bool allocationLogBudgetEnabled = false;
static bool allocationLogInstalled = false;
static mach_vm_address_t originalAllocationLogger = 0;
static volatile uint64_t allocationLogFailures = 0;
static void budgetAllocationFailure(const char *format, const char *name,
                                   uint64_t requested, uint64_t freeBytes,
                                   uint64_t fixedFreeBytes) {
    const uint64_t count = __sync_add_and_fetch(&allocationLogFailures, 1);
    if (!RaphaelAllocationLog::emit(count)) return;
    using Logger = void (*)(const char *, ...);
    auto logger = reinterpret_cast<Logger>(originalAllocationLogger);
    // Preserve the first eight original diagnostics exactly. Subsequent samples
    // explicitly expose the cumulative failure count; this is not allocation success.
    if (count <= 8) logger(format, name, requested, freeBytes, fixedFreeBytes);
    else logger("%s: AMD allocation failures=%llu (sampled after first 8); "
                "latest size=%llu free=%llu fixed-free=%llu\n",
                name, count, requested, freeBytes, fixedFreeBytes);
}

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

// rgpumem reports AMDHWMemory's pool state. The old mode-2 early enable graft was
// removed: Apple's one native enable is now the only pool initialization epoch.
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
static bool recoveryLeaseConfigured = false;
static uint64_t discoveredVramTotal = 0;
static uint64_t discoveredBarVisible = 0;
static uint64_t nativeProviderTotal = 0;
static uint64_t nativeProviderVisible = 0;
static bool discoveredCapacityValid = false;
static uint64_t recoveryNonceLo = 0;
static uint64_t recoveryNonceHi = 0;
static RaphaelRecoveryV2::LeaseState recoveryLeaseState {};
static void *recoveryLeaseElement = nullptr;
static bool recoveryPoolStatusPublished = false;
static RaphaelRecoveryV2::PoolStatus recoveryActivePoolStatus {};
static volatile bool recoveryActivePoolStatusReady = false;
static RaphaelRecoveryV3::LifetimeStatus recoveryLifetimeStatus {};
static RaphaelRecoveryV3::LifetimeGate recoveryLifetimeGate {};
static void *recoveryLeaseMemoryOwner = nullptr;
static void *recoveryLeaseHardwareOwner = nullptr;

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
// Explicit experiment: allow Apple's native timeout restore/reprogram path only
// after an exact-address, owned-lease, ingress-suppressed timeout proof.
static uint32_t mqdNativeRestoreMode = 0;
static volatile uint32_t nativeMecProbeArmed = 0;
static void *hwMemObject = nullptr;
static volatile uint32_t *fbAperture();
static bool wrapHwMemEnable(void *self);
static bool isRaphaelHardware(void *self);
static bool hasUniqueRaphaelPciMarker();

static void reportCpState(const char *when);
static void primeIcacheOnly();
static void probeRlc();
static void repairMqdPointers();
static bool prepareKiq(uint64_t &mqdAddr, uint64_t &eopAddr, const void *spec,
                       bool &nativeRestoreAttempted,
                       RaphaelKiq::HaltedNativeTransaction *haltedTx);
static void reportKiqPreparation(const char *stage);
static mach_vm_address_t orgVmmInit = 0;
static mach_vm_address_t orgVmmSetAlloc = 0;
static mach_vm_address_t orgVmmSetVSReady = 0;
static mach_vm_address_t orgVmmFillRegs = 0;
static mach_vm_address_t orgVmmPrepare = 0;
static mach_vm_address_t orgVmmProgInv = 0;
static mach_vm_address_t orgProcessCommandBuffer = 0;
static mach_vm_address_t orgBatchPrepareMappings = 0;
static mach_vm_address_t orgBatchPrepare = 0;
static mach_vm_address_t orgBatchMemoryMapPrepare = 0;
static mach_vm_address_t orgSubmitBuffer = 0;
static mach_vm_address_t orgBackingAllocPhysical = 0;
static mach_vm_address_t orgCommitIntoGPUPageTable = 0;
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
    // Historical cards keep their byte-identical COM1 replay path. COM2 cards use
    // the independent worker below, so they cannot queue behind this SYSLOG burst.
    if (!criticalUartEnabled) {
        for (unsigned replay = 0; replay < 18; ++replay) {
            const size_t count = criticalRecords.size();
            const uint64_t dropped = criticalRecords.dropped();
            const uint64_t truncated = criticalRecords.truncated();
            const bool complete = rgpu::CriticalReplayV2::emitSnapshot(
                RGPU_BUILD_ID, replay, count, dropped, truncated,
                [](size_t sequence,
                   char (&record)[rgpu::CriticalReplayV2::kRecordStorageBytes]) {
                    return criticalRecords.read(sequence, record);
                },
                [](const char *line) { SYSLOG("rgpu", "%s", line); });
            if (!complete)
                SYSLOG("rgpu", "critical replay snapshot %u deferred", replay);
            IOSleep(10000);
        }
    }
    thread_terminate(current_thread());
}

struct CriticalPortIo {
    uint8_t read(uint16_t port) const {
        uint8_t value;
        asm volatile("inb %1, %0" : "=a"(value) : "Nd"(port));
        return value;
    }
    void write(uint16_t port, uint8_t value) const {
        asm volatile("outb %0, %1" : : "a"(value), "Nd"(port));
    }
    uint64_t micros() const {
        uint64_t absolute = 0;
        uint64_t nanoseconds = 0;
        clock_get_uptime(&absolute);
        absolutetime_to_nanoseconds(absolute, &nanoseconds);
        return nanoseconds / 1000;
    }
    void delay(unsigned us) const { IODelay(us); }
};

static void criticalDumpThread(void *, wait_result_t) {
    static constexpr uint64_t kWorkerTimeoutUs = UINT64_C(180000000);
    CriticalPortIo io;
    const uint64_t workerStarted = io.micros();
    const rgpu::CriticalWorkerBudget budget(workerStarted, kWorkerTimeoutUs);
    const unsigned initialSleepMs = budget.cappedSleepMs(io.micros(), diagDumpDelayMs);
    if (initialSleepMs != 0) IOSleep(initialSleepMs);
    if (budget.remainingUs(io.micros()) == 0) {
        SYSLOG("rgpu", "critical COM2 worker deadline exhausted before readiness");
        thread_terminate(current_thread());
        return;
    }
    rgpu::CriticalUart<CriticalPortIo> uart(io);
    const bool initialized = uart.initialize();
    const uint64_t readyTimeoutUs = budget.cappedOperationUs(
        io.micros(), decltype(uart)::kByteTimeoutUs * 80);
    if (!initialized || readyTimeoutUs == 0 ||
        !uart.writeReady(RGPU_BUILD_ID, readyTimeoutUs)) {
        SYSLOG("rgpu", "critical COM2 producer readiness failed");
        thread_terminate(current_thread());
        return;
    }

    // Keep the complete worker within the existing 180-second observation window.
    // A blocked attempt consumes only the remaining window, and never emits END.
    bool quiesceRequested = false;
    for (unsigned replay = 0; replay < 18; ++replay) {
        const uint64_t remaining = budget.remainingUs(io.micros());
        if (remaining == 0) break;
        // Keep a healthy UART configured so FCR reset cannot discard queued tail
        // bytes. Only a failed prior attempt reinitializes before its retry.
        if (uart.failed() && !uart.initialize()) {
            SYSLOG("rgpu", "critical COM2 snapshot %u initialization failed", replay);
        } else {
            if (criticalUartQuiesceEnabled && uart.pollQuiesceRequest())
                quiesceRequested = true;
            const uint64_t snapshotRemaining = budget.remainingUs(io.micros());
            if (snapshotRemaining == 0) break;
            // A quiesce request observed before this attempt makes it a fresh
            // post-request sample.  A request received during an ordinary
            // attempt always gets another snapshot, even if that attempt happened
            // to finish after the request reached the UART.
            const bool finalAttempt = quiesceRequested;
            const size_t count = criticalRecords.size();
            const uint64_t dropped = criticalRecords.dropped();
            const uint64_t truncated = criticalRecords.truncated();
            uart.beginSnapshot(snapshotRemaining < decltype(uart)::kSnapshotTimeoutUs ?
                               snapshotRemaining : decltype(uart)::kSnapshotTimeoutUs);
            const bool complete = rgpu::CriticalReplayV2::emitSnapshot(
                RGPU_BUILD_ID, replay, count, dropped, truncated,
                [](size_t sequence,
                   char (&record)[rgpu::CriticalReplayV2::kRecordStorageBytes]) {
                    return criticalRecords.read(sequence, record);
                },
                [&](const char *line) { uart(line); });
            if (!complete)
                SYSLOG("rgpu", "critical replay snapshot %u deferred", replay);
            else if (uart.failed())
                SYSLOG("rgpu", "critical COM2 snapshot %u transmission failed", replay);
            if (criticalUartQuiesceEnabled && uart.pollQuiesceRequest())
                quiesceRequested = true;
            if (rgpu::criticalSnapshotCaughtUp(
                    finalAttempt, complete, uart.failed(), count, dropped, truncated,
                    criticalRecords.size(), criticalRecords.dropped(),
                    criticalRecords.truncated()) &&
                    uart.writeQuiesced(RGPU_BUILD_ID, replay,
                                       static_cast<uint16_t>(count))) {
                thread_terminate(current_thread());
                return;
            }
        }
        const uint64_t remainingUs = budget.remainingUs(io.micros());
        if (remainingUs == 0) break;
        if (criticalUartQuiesceEnabled && quiesceRequested)
            continue;
        if (criticalUartQuiesceEnabled) {
            // Preserve the ten-second cadence while making the control path
            // responsive.  RX polling has a fixed byte budget and never logs.
            const uint64_t sleepUs = remainingUs < UINT64_C(10000000) ?
                remainingUs : UINT64_C(10000000);
            const uint64_t sleepEnd = io.micros() + sleepUs;
            while (io.micros() < sleepEnd) {
                if (uart.pollQuiesceRequest()) {
                    quiesceRequested = true;
                    break;
                }
                const uint64_t left = sleepEnd - io.micros();
                if (left >= UINT64_C(10000)) IOSleep(10);
                else if (left >= 1000) IOSleep(static_cast<unsigned>(left / 1000));
                else IODelay(static_cast<unsigned>(left));
            }
        } else if (remainingUs >= UINT64_C(10000000))
            IOSleep(10000);
        else if (remainingUs >= 1000)
            IOSleep(static_cast<unsigned>(remainingUs / 1000));
        else
            IODelay(static_cast<unsigned>(remainingUs));
    }
    if (criticalUartQuiesceEnabled) {
        // Candidate 217: the harness requested quiesce after the probe, 22 minutes after
        // this worker's 180-second replay window had closed, so no ACK ever came and the
        // run idled until a manual stop. Keep only the RX control path alive (no replay
        // traffic, 10 ms polls) for the longest authorized run, then answer the request
        // with one fresh caught-up snapshot and the ACK.
        static constexpr uint64_t kLateQuiesceUs = UINT64_C(6000000000);
        const rgpu::CriticalWorkerBudget late(io.micros(), kLateQuiesceUs);
        unsigned lateReplay = 18;
        while (late.remainingUs(io.micros()) != 0 && lateReplay < 64) {
            if (!quiesceRequested) {
                if (!uart.pollQuiesceRequest()) {
                    IOSleep(10);
                    continue;
                }
                quiesceRequested = true;
            }
            if (uart.failed() && !uart.initialize()) {
                IOSleep(1000);
                continue;
            }
            const size_t count = criticalRecords.size();
            const uint64_t dropped = criticalRecords.dropped();
            const uint64_t truncated = criticalRecords.truncated();
            uart.beginSnapshot(decltype(uart)::kSnapshotTimeoutUs);
            const unsigned replay = lateReplay++;
            const bool complete = rgpu::CriticalReplayV2::emitSnapshot(
                RGPU_BUILD_ID, replay, count, dropped, truncated,
                [](size_t sequence,
                   char (&record)[rgpu::CriticalReplayV2::kRecordStorageBytes]) {
                    return criticalRecords.read(sequence, record);
                },
                [&](const char *line) { uart(line); });
            if (rgpu::criticalSnapshotCaughtUp(
                    true, complete, uart.failed(), count, dropped, truncated,
                    criticalRecords.size(), criticalRecords.dropped(),
                    criticalRecords.truncated()) &&
                    uart.writeQuiesced(RGPU_BUILD_ID, replay, static_cast<uint16_t>(count)))
                break;
            IOSleep(100);
        }
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
static constexpr size_t kOffVcnConfig = 0x86bae; // HWLibs _internal_read_config_setting
static constexpr size_t kOffVcnInitialize = 0x87c74; // HWLibs _engine_initialize
static constexpr size_t kOffVcnSharedSize = 0x878f5; // HWLibs _engine_hw_init shared allocation sequence
static constexpr size_t kOffVcnReadFw = 0x86648; // HWLibs _internal_cos_read_fw
static constexpr size_t kOffVcnHwInit = 0x862ea; // HWLibs _vcn_hw_init
static constexpr size_t kOffAddToDpgSram = 0x93f5d; // HWLibs _engine_3_0_add_to_dpg_sram
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
static constexpr size_t kOffNbio72SetDbRange = 0x2413da; // _nbio7_2_set_doorbell_aperture_range
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
static constexpr size_t kOffHwMemReserve = 0x5343c;   // AMDHWMemory::reserve [x6] (called only)
static constexpr size_t kOffVmmInit     = 0x56d3a;    // AMDHWVMM::init [x6]
static constexpr size_t kOffVmmSetAlloc = 0x5791e;    // AMDHWVMM::setMemoryAllocationsEnabled [x6]
static constexpr size_t kOffVmmSetVSReady = 0x578ce;  // AMDHWVMM::setVirtualSpaceReady [x6]
static constexpr size_t kOffHwAppendReserved = 0x72afe; // AMDHardware::appendToReservedVRAMOffset [x6] (called only)
static constexpr size_t kOffVmmFillRegs = 0x62400;    // AMDGFX10VMM::fillVMRegisters [x6]
static constexpr size_t kOffVmmPrepare  = 0x6249c;    // __ZN26AMDRadeonX6000_AMDGFX10VMM26prepareVMInvalidateRequestEP25AMD_VM_INVALIDATE_REQUESTPK22AMD_VM_INVALIDATE_INFOb [x6]
static constexpr size_t kOffVmmProgInv  = 0x6278a;    // AMDGFX10VMM::programAndInvalidateVM [x6]
static constexpr size_t kOffVmmGetPde   = 0x629c6;    // __ZN26AMDRadeonX6000_AMDGFX10VMM11getPDEValueE15eAMD_VMPT_LEVELy [x6]
static constexpr size_t kOffVmmGetPte   = 0x62a14;    // __ZN26AMDRadeonX6000_AMDGFX10VMM11getPTEValueE15eAMD_VMPT_LEVELyN24AMDRadeonX6000_IAMDHWVMM10VmMapFlagsEj [x6]
static constexpr size_t kOffVmmUpdateEntries = 0x55cda; // __ZN29AMDRadeonX6000_AMDHWVMContext36updateContiguousPTEsWithDMAUsingAddrEyyyyy [x6]
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
static constexpr size_t kOffFillMapProcess = 0x8edce; // AMDGFX10HIQHWChannel::fillMapProcessPacket [x6]
static constexpr size_t kOffKiqSubmit    = 0x5c716;  // AMDKIQHWChannel::submitKIQFrame [x6]
static constexpr size_t kOffWaitStamp    = 0x4c520;  // AMDHWChannel::waitForHwStamp [x6]
// Observation-only submission boundaries in the exact 24G830 X6000 image. Keep
// the full symbols here because BatchPrepare is a substring of BatchPrepareMappings.
static constexpr size_t kOffProcessCommandBuffer = 0x9ca6; // __ZN35AMDRadeonX6000_AMDAccelCommandQueue20processCommandBufferEjj [x6]
static constexpr size_t kOffBatchPrepareMappings = 0x18256; // __ZN31AMDRadeonX6000_AMDAccelResource20BatchPrepareMappingsEP37AMDRadeonX6000_AMDGraphicsAcceleratorPKPS_j [x6]
static constexpr size_t kOffBatchPrepare = 0x184d8; // __ZN31AMDRadeonX6000_AMDAccelResource12BatchPrepareEP37AMDRadeonX6000_AMDGraphicsAcceleratorPKPS_j [x6]
static constexpr size_t kOffBatchMemoryMapPrepare = 0x6550; // __ZN37AMDRadeonX6000_AMDGraphicsAccelerator21batchMemoryMapPrepareEP16IOAccelMemoryMap [x6]
static constexpr size_t kOffSubmitBuffer = 0xb83e; // __ZN30AMDRadeonX6000_AMDAccelChannel12submitBufferEP24IOAccelCommandDescriptor [x6]
static constexpr size_t kOffBackingAllocPhysical = 0x3aa76; // __ZN32AMDRadeonX6000_AMDAccelVidMemory13allocPhysicalEv [x6]
static constexpr size_t kOffCommitIntoGPUPageTable = 0x3b4d2; // __ZN32AMDRadeonX6000_AMDAccelMemoryMap22commitIntoGPUPageTableEv [x6]
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
static mach_vm_address_t orgNbio72SetDbRange {};
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
// GC 10.3.6 golden registers (Linux golden_settings_gc_10_3_6[]) that the Navi23
// path never programs: read-only diagnostics so a run records what the graphics
// pipe is actually configured with before the first desktop draw.
static constexpr uint32_t kGcGbAddrConfig  = kGcSeg0 + 0x13de;   // GB_ADDR_CONFIG   (golden 0x42, mask 0x0c1807ff)
static constexpr uint32_t kGcUtcl1Ctrl     = kGcSeg0 + 0x1588;   // UTCL1_CTRL       (golden 0x00100000)
static constexpr uint32_t kGcSqgConfig     = kGcSeg0 + 0x10ba;   // SQG_CONFIG       (golden 0x1000, mask 0x17ff)
static constexpr uint32_t kGcGcrGeneralCntl = kGcSeg0 + 0x1580;  // GCR_GENERAL_CNTL (golden 0x500)
static constexpr uint32_t kGcChPipeSteer   = kGcSeg1 + 0x2d90;   // CH_PIPE_STEER    (golden 0x44)
static constexpr uint32_t kGcGl1PipeSteer  = kGcSeg1 + 0x2d10;   // GL1_PIPE_STEER   (golden 0x44)
static constexpr uint32_t kGcGl2PipeSteer0 = kGcSeg1 + 0x2e25;   // GL2_PIPE_STEER_0 (golden 0x32103210)
static constexpr uint32_t kGcGl2PipeSteer1 = kGcSeg1 + 0x2e26;   // GL2_PIPE_STEER_1 (golden 0x32103210)
static constexpr uint32_t kGcRlcCpSchedulers = kGcSeg1 + 0x4ca1; // RLC_CP_SCHEDULERS (Linux KIQ me2/pipe1/q0 -> 0xc8)

static void reportGoldenState(const char *when) {
    if (asicInfo == nullptr) return;
    RLOG("XG: %s: GB_ADDR_CONFIG=%#x CH_PIPE_STEER=%#x GL1_PIPE_STEER=%#x "
         "GL2_PIPE_STEER=%#x/%#x UTCL1_CTRL=%#x SQG_CONFIG=%#x GCR_GENERAL_CNTL=%#x "
         "(Linux 10.3.6 golden 0x42 0x44 0x44 0x32103210/0x32103210 0x100000 0x1000 0x500)",
         when, fbRead(asicInfo, kGcGbAddrConfig), fbRead(asicInfo, kGcChPipeSteer),
         fbRead(asicInfo, kGcGl1PipeSteer), fbRead(asicInfo, kGcGl2PipeSteer0),
         fbRead(asicInfo, kGcGl2PipeSteer1), fbRead(asicInfo, kGcUtcl1Ctrl),
         fbRead(asicInfo, kGcSqgConfig), fbRead(asicInfo, kGcGcrGeneralCntl));
    RLOG("XG: %s: RLC_CP_SCHEDULERS=%#x RLC_PG_CNTL=%#x RLC_GPM_STAT=%#x RLC_SRM_CNTL=%#x",
         when, fbRead(asicInfo, kGcRlcCpSchedulers), fbRead(asicInfo, kGcRlcPgCntl),
         fbRead(asicInfo, kGcRlcGpmStat), fbRead(asicInfo, kGcRlcSrmCntl));
}

// rgpugolden=1: program Linux's golden_settings_gc_10_3_6[] once before the RLC
// starts. Apple ships the Navi23 (10.3.4) table, which has no GB_ADDR_CONFIG or
// pipe-steer entries at all, so on this part the tiling and pipe configuration
// stays at whatever the SoC reset left. Masks and values are transcribed from
// gfx_v10_0.c (v6.12) with the gc_10_1_0 offsets that file includes; the
// GCR_GENERAL_CNTL entry uses the file-local Vangogh offset 0x1580.
static uint32_t goldenMode = 0;
struct GoldenRegister { uint32_t reg; uint32_t mask; uint32_t value; const char *name; };
static constexpr GoldenRegister kGolden1036[] = {
    {kGcSeg1 + 0x507c, 0xff7f0fff, 0x78000100, "CGTT_SPI_CS_CLK_CTRL"},
    {kGcSeg1 + 0x2d90, 0x000000ff, 0x00000044, "CH_PIPE_STEER"},
    {kGcSeg0 + 0x1f53, 0x0007ffff, 0x0000c200, "CPF_GCR_CNTL"},
    {kGcSeg0 + 0x13ae, 0xffffffff, 0x00000280, "DB_DEBUG3"},
    {kGcSeg0 + 0x13af, 0xffffffff, 0x00800000, "DB_DEBUG4"},
    {kGcSeg0 + 0x13de, 0x0c1807ff, 0x00000042, "GB_ADDR_CONFIG"},
    {kGcSeg0 + 0x1580, 0x1ff1ffff, 0x00000500, "GCR_GENERAL_CNTL"},
    {kGcSeg1 + 0x2d10, 0x000000ff, 0x00000044, "GL1_PIPE_STEER"},
    {kGcSeg1 + 0x2e25, 0x77777777, 0x32103210, "GL2_PIPE_STEER_0"},
    {kGcSeg1 + 0x2e26, 0x77777777, 0x32103210, "GL2_PIPE_STEER_1"},
    {kGcSeg1 + 0x2e21, 0xffffffff, 0xfffffff3, "GL2A_ADDR_MATCH_MASK"},
    {kGcSeg1 + 0x2e03, 0xffffffff, 0xfffffff3, "GL2C_ADDR_MATCH_MASK"},
    {kGcSeg1 + 0x2e08, 0xff8fff0f, 0x580f1008, "GL2C_CM_CTRL1"},
    {kGcSeg1 + 0x2e0c, 0xf7ffffff, 0x00f80988, "GL2C_CTRL3"},
    {kGcSeg0 + 0x10a2, 0x000001ff, 0x00000020, "LDS_CONFIG"},
    {kGcSeg0 + 0x1025, 0xf17fffff, 0x01200007, "PA_CL_ENHANCE"},
    {kGcSeg0 + 0x1070, 0xffffffff, 0x00000800, "PA_SC_BINNER_TIMEOUT_COUNTER"},
    {kGcSeg0 + 0x107c, 0xffffffbf, 0x00000820, "PA_SC_ENHANCE_2"},
    {kGcSeg0 + 0x10ba, 0x000017ff, 0x00001000, "SQG_CONFIG"},
    {kGcSeg0 + 0x11b8, 0xffffff7f, 0x00010020, "SX_DEBUG_1"},
    {kGcSeg0 + 0x12e2, 0xfff7ffff, 0x01030000, "TA_CNTL_AUX"},
    {kGcSeg0 + 0x1588, 0xffffffff, 0x00100000, "UTCL1_CTRL"},
};

static void applyGoldenRegisters(const char *when) {
    if (goldenMode != 1 || asicInfo == nullptr) return;
    static bool applied = false;
    if (applied) return;
    applied = true;
    unsigned changed = 0, mismatched = 0;
    for (const auto &g : kGolden1036) {
        const uint32_t before = fbRead(asicInfo, g.reg);
        if (before == 0xdeadbeef || before == 0xffffffffU) {
            RLOG("XG: golden %s at %s: unreadable (%#x); skipped", g.name, when, before);
            continue;
        }
        const uint32_t target = (before & ~g.mask) | (g.value & g.mask);
        if (target == before) continue;
        fbWrite(asicInfo, g.reg, target);
        const uint32_t after = fbRead(asicInfo, g.reg);
        changed++;
        if (after != target) mismatched++;
        RLOG("XG: golden %s at %s: %#x -> %#x (readback %#x)%s", g.name, when, before,
             target, after, after == target ? "" : " MISMATCH");
    }
    RLOG("XG: golden 10.3.6 applied at %s: %u written, %u readback mismatches", when,
         changed, mismatched);
}
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
static bool programMode2Eop(uint64_t eopAddr);
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

// rgpucpfw=1 (candidate 215). Apple's restart report shows the gfx CP running Apple's
// Navi 23 microcode (ME 0x40, PFP 0x58, CE 0x24) under this chip's RLC (0x1f). Candidates
// 212-214 put the hang in the ME/3D-pipeline end-of-packet handshake
// (QU_STALLED_ON_EOP_DONE_PULSE) on the first large draw. GC 10.3.6 has its own CP
// microcode family (ME 0x0e, PFP 0x12, CE 0x03), signed with the same key and the same
// payload sizes. Swap the three descriptors, matched by the fw type each signed payload
// carries at +0x58, before psp_np_fw_init copies the array. MEC stays Apple's.
static uint32_t cpFwMode = 0;
#ifdef RGPU_HAVE_CP_FW
struct CpPayload { uint32_t fwType; const uint8_t *data; uint32_t size; const char *name; };
static const CpPayload kCpPayloads[] {
    {0x81012001u, kCpMeFw, kCpMeFwSize, "CP_ME"},
    {0x81012002u, kCpPfpFw, kCpPfpFwSize, "CP_PFP"},
    {0x81012003u, kCpCeFw, kCpCeFwSize, "CP_CE"},
};

static void substituteCpFirmware(uint8_t *arr, uint32_t count) {
    for (const auto &p : kCpPayloads) {
        if (p.size < 0x5c || *reinterpret_cast<const uint32_t *>(p.data + 0x58) != p.fwType ||
            p.data[0x10] != '$' || p.data[0x11] != 'P' || p.data[0x12] != 'S' ||
            p.data[0x13] != '1') {
            RLOG("X9C: embedded %s is not a $PS1 payload of type %#x -- not substituting",
                 p.name, p.fwType);
            return;
        }
    }
    unsigned replaced = 0;
    for (uint32_t i = 0; i < count; i++) {
        auto e = arr + static_cast<size_t>(i) * 40;
        const auto data = *reinterpret_cast<const uint8_t *const *>(e + 0x10);
        const uint32_t len = *reinterpret_cast<const uint32_t *>(e + 0x18);
        if (data == nullptr || len < 0x5c) continue;
        const uint32_t fwType = *reinterpret_cast<const uint32_t *>(data + 0x58);
        const bool signedPayload = data[0x10] == '$' && data[0x11] == 'P' &&
                                   data[0x12] == 'S' && data[0x13] == '1';
        // Candidate 215 matched nothing on the full 0x81012001 form: Apple's embedded blobs
        // use a shorter fw_type the way its TOC does (0x200e vs this chip's 0x0101200e).
        // Log every descriptor of a CP payload size and match the low 16 bits.
        if (len == 0x40400 || len == 0x40380 || len == 0x414b0)
            RLOG("X9C: descriptor %u type %#x len %#x magic=%u fw_type=%#x", i,
                 *reinterpret_cast<const uint32_t *>(e + 0x04), len, signedPayload, fwType);
        if (!signedPayload) continue;
        for (const auto &p : kCpPayloads) {
            if ((p.fwType & 0xffffu) != (fwType & 0xffffu)) continue;
            if (len != p.size) {
                RLOG("X9C: %s descriptor %u length %#x != gc_10_3_6 %#x -- left alone",
                     p.name, i, len, p.size);
                break;
            }
            *reinterpret_cast<const uint8_t **>(e + 0x10) = p.data;
            RLOG("X9C: descriptor %u type %#x %s Apple %p/%#x fw_type %#x -> gc_10_3_6 %p/%#x "
                 "fw_type %#x", i, *reinterpret_cast<const uint32_t *>(e + 0x04), p.name, data,
                 len, fwType, p.data, p.size, p.fwType);
            replaced++;
            break;
        }
    }
    RLOG("X9C: %u of 3 graphics CP microcode descriptors replaced", replaced);
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
#ifdef RGPU_HAVE_CP_FW
    if (cpFwMode == 1 && arr != nullptr)
        substituteCpFirmware(static_cast<uint8_t *>(arr), count);
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
// Observe the doorbell ranges Apple programs through the NBIO 7.2 family. Linux
// nbio_v7_2_vcn_doorbell_range writes GDC0_BIF_VCN0_DOORBELL_RANGE (RSMU byte
// address 0x1403bcc) with OFFSET=0x1f0<<2 and SIZE=8 -> 0x807c0. The request is
// {type(5=VCN,0=SDMA,4=IH), offset0, size0(64-bit), offset1, size1(64-bit)}.
static uint32_t wrapNbio72SetDbRange(void *ctx, const int32_t *req) {
    const uint32_t r = FunctionCast(wrapNbio72SetDbRange, orgNbio72SetDbRange)(ctx, req);
    if (req) {
        const int64_t size0 = *reinterpret_cast<const int64_t *>(req + 4);
        const int64_t size1 = *reinterpret_cast<const int64_t *>(req + 8);
        RLOG("XK: nbio7_2_set_doorbell_aperture_range type=%d offset0=%#x size0=%lld offset1=%#x size1=%lld -> %u",
             req[0], req[2], size0, req[6], size1, r);
    }
    return r;
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
    const bool preserveMecHalt = RaphaelKiq::preserveNativeMecHalt(
        mqdNativeRestoreMode, mqdFixMode,
        __atomic_load_n(&nativeMecProbeArmed, __ATOMIC_ACQUIRE) != 0,
        caller, reg, client, flag, gcCtx != nullptr, gcCtx == ctx);
    if (preserveMecHalt && reg == kGcCpMecCntl) {
        const uint32_t requested = val;
        val |= RaphaelKiq::kMecHaltMask;
        CRLOG("XQ4: native MEC halt guard caller=+%#llx requested=%#x effective=%#x client=%#x flag=%#x",
             caller, requested, val, client, flag);
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

// HWLibs 24G830 _internal_cos_read_fw receives a preallocated CPU buffer,
// capacity at +8 and filename at +16. Return is bytes copied, zero on failure.
// The native consumer keeps the AMD signature header, extracts version at +0x60,
// and owns all subsequent firmware allocation, authentication and initialization.
// Native configuration table indices0/1/7 are EnableVCNDPG,
// PP_EnableVCNPG and EnableVCNSecureLoad. Mode3 (EnableSwVCNFWLoading)
// is forced to0 for the PSP-loading comparison. Clearing7
// chooses the native static initializer instead of the secure DPG SRAM path.
// Assert VCPU reset while the native static initializer enables its clock,
// before native cache programming. The same native initializer releases reset.
// Match Linux's observed M/U/LMI-on PGFSM state instead of the native
// all-off write after SMU PowerUp. Restricted to initial secure DPG startup.
static bool vcnCorePowerWaitSucceeded = false;
static bool vcnCorePowerSelected(void *engine) {
    if (!vcnDpgEnabled || !engine ||
        !__atomic_load_n(&raphaelTargetConfirmed, __ATOMIC_ACQUIRE)) return false;
    const auto ctx = *reinterpret_cast<const uint8_t **>(static_cast<uint8_t *>(engine) + 0x10);
    const auto manager = *reinterpret_cast<const uint32_t **>(static_cast<uint8_t *>(engine) + 0x18);
    return ctx && manager && manager[0] == 0 &&
        !(*reinterpret_cast<const uint32_t *>(ctx) & 1) &&
        *reinterpret_cast<const uint32_t *>(ctx + 0x268) == 0x30001 &&
        *reinterpret_cast<const uint32_t *>(ctx + 0x2e0) == 0 &&
        *reinterpret_cast<const uint64_t *>(ctx + 0x3f8) == hwlibsBase + 0x943cf;
}
static void wrapVcnWriteRegister(void *engine, uint32_t segment, uint32_t reg, uint32_t value) {
    const auto caller = reinterpret_cast<mach_vm_address_t>(__builtin_return_address(0));
    auto ctx = engine ? *reinterpret_cast<const uint8_t **>(static_cast<uint8_t *>(engine) + 16) : nullptr;
    const bool reset = vcnResetEnabled && vcnStaticEnabled && ctx &&
        __atomic_load_n(&raphaelTargetConfirmed, __ATOMIC_ACQUIRE) &&
        caller == hwlibsBase + 0x931ba && segment == 1 && reg == 0x156 &&
        *reinterpret_cast<const uint32_t *>(ctx + 0x268) == 0x30001 &&
        *reinterpret_cast<const uint32_t *>(ctx + 0x2e0) == 0 && (value & 0x200);
    if (caller == hwlibsBase + 0x93a1e && segment == 1 && reg == 0 &&
        value == 0x2a2aaaaa && vcnCorePowerSelected(engine)) {
        // Exact native disable_power_gating (+93599) M/U/LMI-on config.
        // The corresponding wait below uses its masked on-state, not a fake success.
        RLOG("VCNCORE: PGFSM config %08x -> 2a2a9aa5", value);
        value = 0x2a2a9aa5;
    }
    const uint32_t requested = value;
    if (reset) value |= 0x10000000;
    FunctionCast(wrapVcnWriteRegister, orgVcnWriteRegister)(engine, segment, reg, value);
    if (reset) {
        auto read = reinterpret_cast<uint32_t (*)(void *, uint32_t, uint32_t)>(hwlibsBase + 0x86834);
        const uint32_t beforeDelay = read(engine, segment, reg);
        IOSleep(10); // Linux VCN boot-failure retry reset hold time
        RLOG("VCNR: native clock/reset requested=%x written=%x readback=%x after10ms=%x",
             requested, value, beforeDelay, read(engine, segment, reg));
    }
    // Do not read protected/power-gated cache/reset registers merely to log
    // writes. Native initialization and its required waits own MMIO ordering.

}

static mach_vm_address_t orgMmhub21 = 0, nativeMmhub23 = 0;
static void wrapMmhub21(void *vm) {
    const auto caller = reinterpret_cast<mach_vm_address_t>(__builtin_return_address(0));
    const bool select = vm && caller == hwlibsBase + 0x33eca && nativeMmhub23 &&
                        raphaelGcSeen && hasUniqueRaphaelPciMarker();
    RLOG("MHG: native table select=%u gc=%u caller=+%llx", select,
         raphaelGcSeen, caller - hwlibsBase);
    if (select) reinterpret_cast<void (*)(void *)>(nativeMmhub23)(vm);
    else FunctionCast(wrapMmhub21, orgMmhub21)(vm);
    if (select) {
        auto table = *reinterpret_cast<const uint8_t **>(static_cast<uint8_t *>(vm) + 0x510);
        if (table) RLOG("MHG: native table ctx0=%x root0=%x start0=%x end0=%x fbbase=%x",
            *reinterpret_cast<const uint32_t *>(table + 0x380),
            *reinterpret_cast<const uint32_t *>(table + 0x388),
            *reinterpret_cast<const uint32_t *>(table + 0x398),
            *reinterpret_cast<const uint32_t *>(table + 0x3a8),
            *reinterpret_cast<const uint32_t *>(table + 0x7a0));
    }
}

// Trace the native decoder queue submission (HWLibs _queue_decode_3_0_submit_frame).
// Native ownership, copy, pointer advancement and commit are unchanged. Capture
// only the first four complete kernel-owned queue slots and their immediate MMIO
// readbacks; no waits or command submission are added by this wrapper.
static uint32_t wrapVcnDecodeSubmit(void *queue, const void *frame) {
    const uint32_t n = __atomic_add_fetch(&vcnDecodeSubmitCalls, 1u, __ATOMIC_RELAXED);
    auto q = static_cast<const uint8_t *>(queue);
    auto engine = q ? *reinterpret_cast<void *const *>(q + 8) : nullptr;
    auto ctx = engine ? *reinterpret_cast<const uint8_t *const *>(
        static_cast<const uint8_t *>(engine) + 0x10) : nullptr;
    const uint32_t slotBytes = q ? *reinterpret_cast<const uint32_t *>(q + 0x58) : 0;
    const uint32_t slots = q ? *reinterpret_cast<const uint32_t *>(q + 0x54) : 0;
    const uint32_t slot = q ? *reinterpret_cast<const uint32_t *>(q + 0x50) : 0;
    const bool selected = n <= 4 && vcnWptrEnabled && q && ctx && frame &&
        __atomic_load_n(&raphaelTargetConfirmed, __ATOMIC_ACQUIRE) &&
        *reinterpret_cast<const uint32_t *>(ctx + 0x268) == 0x30001 &&
        *reinterpret_cast<const uint32_t *>(q + 0x10) == 1 &&
        slotBytes >= 32 && slotBytes <= 0x1000 && !(slotBytes & 3) &&
        slots && slots <= 0x1000 && slot < slots;
    if (n <= 4 && q && ctx)
        CRLOG("VCNQ: submit n=%u selected=%u flags=%x ctxflags=%x slot=%u slots=%u bytes=%u gpu=%#llx",
              n, selected, *reinterpret_cast<const uint32_t *>(q),
              *reinterpret_cast<const uint32_t *>(ctx), slot, slots, slotBytes,
              *reinterpret_cast<const uint64_t *>(q + 0x28));
    if (selected) {
        auto words = static_cast<const uint32_t *>(frame);
        const unsigned count = slotBytes / 4 < 64 ? slotBytes / 4 : 64;
        for (unsigned i = 0; i + 7 < count; i += 8)
            RLOG("VCNQ: packet n=%u dword=%u %08x %08x %08x %08x %08x %08x %08x %08x",
                  n, i, words[i], words[i+1], words[i+2], words[i+3],
                  words[i+4], words[i+5], words[i+6], words[i+7]);
    }
    const uint32_t result = FunctionCast(wrapVcnDecodeSubmit, orgVcnDecodeSubmit)(queue, frame);
    if (selected) {
        auto read = reinterpret_cast<uint32_t (*)(void *, uint32_t, uint32_t)>(hwlibsBase + 0x86834);
        auto shared = *reinterpret_cast<const uint8_t *const *>(ctx + 0x388);
        CRLOG("VCNQ: committed n=%u result=%u index=%u rptr=%x wptr=%x scratch2=%x shared-rptr=%x shared-wptr=%x",
              n, result, *reinterpret_cast<const uint32_t *>(q + 0x50),
              read(engine,1,0x2e0), read(engine,1,0x2e1), read(engine,1,0x16),
              shared ? *reinterpret_cast<const uint32_t *>(shared + 0x30) : 0xffffffff,
              shared ? *reinterpret_cast<const uint32_t *>(shared + 0x34) : 0xffffffff);
        // AON/RBC registers only (all read without incident in 272's VCNDF);
        // no LMI-domain or DPG-gated register reads here.
        CRLOG("VCNQ: state n=%u power=%x pause=%x rb-cntl=%x doorbell-page-offset=%x", n,
              read(engine,1,4), read(engine,1,0x14), read(engine,1,0x2de),
              static_cast<unsigned>(*reinterpret_cast<const uint64_t *>(q + 0x60) & 0xfff));
    }
    return result;
}

// Candidate 252: the secure DPG path (decode_sram_secure_initialize) builds the DPG SRAM with
// the VCPU cache BAR written as add_to_dpg_sram(,1,0x43c,0)/(,1,0x43d,0) -- zero -- relying on an
// firmware handling not established by these zeros alone. Inject the firmware TMR address from
// ctx+0x2c0 (populated by engine_initialize's firmware-loaded wait) into just those two entries,
// as a firmware-window experiment; this has not demonstrated VCPU execution. Other entries pass
// through unchanged. Guarded to the Raphael VCN3.1 context; no-op when the value is already set.
static uint32_t *wrapAddToDpgSram(void *engine, uint32_t *sram, uint32_t bank,
                                  uint32_t reg, uint32_t value) {
    auto clockCtx = engine ? *reinterpret_cast<const uint8_t **>(
        static_cast<uint8_t *>(engine) + 16) : nullptr;
    const auto caller = reinterpret_cast<mach_vm_address_t>(__builtin_return_address(0));
    const uint32_t corrected = RaphaelVcnDpg::clockGateValue(
        vcnDpgEnabled && clockCtx &&
            __atomic_load_n(&raphaelTargetConfirmed, __ATOMIC_ACQUIRE),
        caller == hwlibsBase + 0x94043,
        clockCtx ? *reinterpret_cast<const uint32_t *>(clockCtx + 0x268) : 0,
        bank, reg, value);
    if (corrected != value) {
        RLOG("VCNDPG: secure CGC_GATE %08x -> %08x", value, corrected);
        value = corrected;
    }
    if (vcnDpgEnabled && clockCtx &&
        __atomic_load_n(&raphaelTargetConfirmed, __ATOMIC_ACQUIRE) &&
        *reinterpret_cast<const uint32_t *>(clockCtx + 0x268) == 0x30001 && bank == 1) {
        if (caller == hwlibsBase + 0x94351 && reg == 0x156 && value == 0x0ff00200) {
            // Linux vcn_v3_0_start_dpg_mode: access masks, unstall memory,
            // unblock VCPU register access, THEN release reset. Four extra
            // pairs preserve the PSP's 16-byte SRAM size alignment (256 -> 288).
            const uint32_t regs[] = {0x26c, 0x26b, 0x4a6, 0xc6};
            const uint32_t values[] = {0x10, 3, 0, 0};
            for (unsigned i = 0; i < 4; ++i)
                sram = FunctionCast(wrapAddToDpgSram, orgAddToDpgSram)(
                    engine, sram, 1, regs[i], values[i]);
            RLOG("VCNREL: added XX masks, LMI_CTRL2=0 and RB_ARB_CTRL=0 before reset release");
        }
        if (caller == hwlibsBase + 0x9436c && reg == 0x4a6 && value == 0x3e0000)
            value = 0; // retain the Linux memory-interface value after release
    }
    // Candidate 253: decode_sram_secure_initialize zeros the whole VCPU cache window and relies
    // on native secure handling. Mirror what decode_sram_initialize (unsecure) programs
    // from ctx: firmware cache BAR (0x43c/0x43d <- ctx+0x2c0), cache SIZE0 (0x141 <- ctx+0x2b0),
    // and the stack/cache1 BAR (0x468/0x469 <- ctx+0x2f8). Only rewrites entries the secure path
    // left 0; anything already nonzero passes through.
    if (vcnDpgEnabled && engine && bank == 1 && value == 0 &&
        (reg == 0x43c || reg == 0x43d || reg == 0x141 || reg == 0x468 || reg == 0x469)) {
        auto ctx = *reinterpret_cast<const uint8_t **>(static_cast<uint8_t *>(engine) + 16);
        if (ctx && __atomic_load_n(&raphaelTargetConfirmed, __ATOMIC_ACQUIRE) &&
            *reinterpret_cast<const uint32_t *>(ctx + 0x268) == 0x30001 &&
            *reinterpret_cast<const uint32_t *>(ctx + 0x2e0) == 1) {
            const uint64_t tmr   = *reinterpret_cast<const uint64_t *>(ctx + 0x2c0); // firmware
            const uint64_t stack = *reinterpret_cast<const uint64_t *>(ctx + 0x2f8); // cache1/stack
            const uint32_t size0 = *reinterpret_cast<const uint32_t *>(ctx + 0x2b0); // cache size0
            uint32_t inject = 0;
            switch (reg) {
                case 0x43c: inject = static_cast<uint32_t>(tmr); break;
                case 0x43d: inject = static_cast<uint32_t>(tmr >> 32); break;
                case 0x141: inject = size0; break;
                case 0x468: inject = static_cast<uint32_t>(stack); break;
                case 0x469: inject = static_cast<uint32_t>(stack >> 32); break;
            }
            if (inject != 0) {
                RLOG("VCNDPG: inject sram reg=%x 0 -> %08x", reg, inject);
                value = inject;
            }
        }
    }
    return FunctionCast(wrapAddToDpgSram, orgAddToDpgSram)(engine, sram, bank, reg, value);
}
static uint32_t wrapVcnConfig(void *engine, uint32_t index) {
    uint32_t value = FunctionCast(wrapVcnConfig, orgVcnConfig)(engine, index);
    auto ctx = engine ? *reinterpret_cast<const uint8_t **>(
        static_cast<uint8_t *>(engine) + 16) : nullptr;
    if (vcnDpgEnabled && orgAddToDpgSram && ctx && (index == 0 || index == 3 || index == 7) &&
        *reinterpret_cast<const uint32_t *>(ctx + 0x268) == 0x30001) {
        const uint32_t selected = index == 3 ? 0 : 1;
        RLOG("VCNDPG: native config%u %u -> %u (PSP firmware, native SRAM)", index, value, selected);
        return selected;
    }
    if (vcnStaticEnabled && ctx && (index == 0 || index == 1 || index == 7) &&
        *reinterpret_cast<const uint32_t *>(ctx + 0x268) == 0x30001) {
        RLOG("VCNS: native config%u %u -> 0", index, value);
        return 0;
    }
    return value;
}
// Native CGS interface query: (interface, firmware ID, 16-byte output).
// Observe only the two VCN firmware IDs, preserving native return/output. No
// extra firmware query or MMIO read; failed queries do not expose output bytes.
static uint32_t wrapVcnQueryFw(void *cgs, uint32_t id, void *output) {
    const uint32_t result = FunctionCast(wrapVcnQueryFw, orgVcnQueryFw)(cgs, id, output);
    static unsigned reports = 0;
    if ((id == 0x14 || id == 0x15) && output &&
        __sync_fetch_and_add(&reports, 1u) < 8) {
        auto out = static_cast<const uint8_t *>(output);
        RLOG("VCNP: query id=%x result=%u loaded=%u valid=%u address=%llx", id, result,
             result == 0 ? out[0] : 0, result == 0 ? out[1] : 0,
             result == 0 ? *reinterpret_cast<const uint64_t *>(out + 8) : 0ULL);
    }
    return result;
}
// 24G830 native wait ABI: EDI engine, ESI bank, EDX reg, ECX expected,
// R8D mask, optional R9D timeout. Native caller tests EAX (zero = success).
static mach_vm_address_t orgVcnWait = 0, orgVcnWaitMs = 0;
static unsigned vcnWaitReports = 0;
static uint32_t wrapVcnWait(void *engine, uint32_t bank, uint32_t reg,
                            uint32_t expected, uint32_t bits) {
    const auto caller = reinterpret_cast<uintptr_t>(__builtin_return_address(0)) - hwlibsBase;
    if (caller == 0x93a3b && bank == 1 && reg == 1 &&
        expected == 0x2a2aaaaa && bits == 0x3f3fffff && vcnCorePowerSelected(engine)) {
        RLOG("VCNCORE: native PGFSM wait %08x -> 2a2a8aa0 mask=%08x", expected, bits);
        expected = 0x2a2a8aa0;
    }
    const auto n = __sync_fetch_and_add(&vcnWaitReports, 1u);
    if (n < 64) RLOG("VCNW: begin n=%u caller=+%llx bank=%x reg=%x expected=%x mask=%x ms=5000",
        n, static_cast<uint64_t>(caller), bank, reg, expected, bits);
    const uint32_t result = FunctionCast(wrapVcnWait, orgVcnWait)(engine, bank, reg, expected, bits);
    if (caller == 0x93a3b && bank == 1 && reg == 1 &&
        expected == 0x2a2a8aa0 && bits == 0x3f3fffff && vcnCorePowerSelected(engine))
        vcnCorePowerWaitSucceeded = result == 0;
    if (n < 64) RLOG("VCNW: end n=%u result=%u", n, result);
    return result;
}
static uint32_t wrapVcnWaitMs(void *engine, uint32_t bank, uint32_t reg,
                              uint32_t expected, uint32_t bits, uint32_t ms) {
    const auto caller = reinterpret_cast<uintptr_t>(__builtin_return_address(0)) - hwlibsBase;
    const auto n = __sync_fetch_and_add(&vcnWaitReports, 1u);
    if (n < 64) RLOG("VCNW: begin n=%u caller=+%llx bank=%x reg=%x expected=%x mask=%x ms=%u",
        n, static_cast<uint64_t>(caller), bank, reg, expected, bits, ms);
    const uint32_t result = FunctionCast(wrapVcnWaitMs, orgVcnWaitMs)(engine, bank, reg, expected, bits, ms);
    if (n < 64) RLOG("VCNW: end n=%u result=%u", n, result);
    return result;
}
static uint32_t wrapVcnInitialize(void *engine) {
    if (vcnDpgEnabled && (!orgVcnConfig || !orgAddToDpgSram || !orgVcnWriteRegister || !orgVcnWait)) {
        RLOG("VCNDPG: required route missing; native initialization refused");
        return 1;
    }
    if (vcnResetEnabled && !orgVcnWriteRegister) {
        RLOG("VCNR: route missing; native initialization refused");
        return 1;
    }
    auto ctx = engine ? *reinterpret_cast<const uint8_t **>(
        static_cast<uint8_t *>(engine) + 16) : nullptr;
    if (vcnDpgEnabled && (!ctx ||
        *reinterpret_cast<const uint32_t *>(ctx + 0x268) != 0x30001 ||
        *reinterpret_cast<const uint64_t *>(ctx + 0x320) < 288 ||
        !*reinterpret_cast<void *const *>(ctx + 0x340))) {
        RLOG("VCNREL: SRAM capacity/context guard failed; initialization refused");
        return 1;
    }
    if (ctx) RLOG("VCNS: initialize flags=%x mode=%u initializer=+%llx",
        *reinterpret_cast<const uint32_t *>(ctx),
        *reinterpret_cast<const uint32_t *>(ctx + 0x2e0),
        *reinterpret_cast<const uint64_t *>(ctx + 0x3f8) - hwlibsBase);
    if (vcnSmuEnabled) {
        auto cgs = engine ? *reinterpret_cast<const uint8_t **>(engine) : nullptr;
        if (!vcnSmuLock || !(vcnStaticEnabled || vcnDpgEnabled) || !ctx || !cgs ||
            !__atomic_load_n(&raphaelTargetConfirmed, __ATOMIC_ACQUIRE) ||
            *reinterpret_cast<const uint32_t *>(ctx + 0x268) != 0x30001 ||
            *reinterpret_cast<const uint32_t *>(ctx + 0x298) != 0x04121015 ||
            *reinterpret_cast<const uint64_t *>(cgs + 0xc0) != hwlibsBase + 0x9e5f1 ||
            *reinterpret_cast<const uint64_t *>(cgs + 0xb8) != hwlibsBase + 0x9e619) {
            RLOG("VCNM: identity/transport guard failed; native initialization refused");
            return 1;
        }
        auto handle = *reinterpret_cast<void *const *>(cgs + 8);
        if (!handle) return 1;
        // Audited CGS wrappers take byte SMN addresses via native BGM. Their
        // register accesses use the existing BGM transport. The dummy
        // SMU backend sends no competing firmware commands; serialize our calls.
        auto read = reinterpret_cast<uint32_t (*)(void *, uint32_t)>(hwlibsBase + 0x9e5f1);
        auto write = reinterpret_cast<void (*)(void *, uint32_t, uint32_t)>(hwlibsBase + 0x9e619);
        auto queues = *reinterpret_cast<const uint32_t *const *>(
            static_cast<const uint8_t *>(engine) + 0x18);
        // Only cycle an unstarted engine with no active queues. Keep ordinary
        // PowerUp behavior for any subsequent initialization/resume.
        const bool cycleVcn = vcnStaticEnabled && !vcnDpgEnabled && queues &&
            !(*reinterpret_cast<const uint32_t *>(ctx) & 1) && queues[0] == 0;
        IOLockLock(vcnSmuLock);
        auto power = RaphaelVcnPower::enable(
            [&](uint32_t address) { return read(handle, address); },
            [&](uint32_t address, uint32_t value) { write(handle, address, value); },
            []() { IOSleep(1); }, cycleVcn, vcnClockMHz, smuQueryEnabled, gfxClockMHz, dcnClockMHz);
        IOLockUnlock(vcnSmuLock);
        RLOG("VCNCYCLE: selected=%u down-response=%x active-queues=%u",
             cycleVcn, power.downResponse, queues ? queues[0] : 0xffffffffu);
        RLOG("VCNM: pre=%x version=%x power-response=%x error=%u",
             power.pre, power.version, power.response, power.error);
        if (smuQueryEnabled)
            RLOG("SMUQ: gfxclk-response=%x gfxclk-mhz=%u features-response=%x features=%08x%08x",
                 power.gfxclkResponse, power.gfxclkMHz, power.featuresResponse,
                 power.featuresHigh, power.featuresLow);
        if (vcnClockMHz)
            RLOG("VCNCLK: requested=%u hardmin-response=%x softmax-response=%x applied=%u",
                 vcnClockMHz, power.clockMinResponse, power.clockMaxResponse,
                 power.clockMinResponse == 1 && power.clockMaxResponse == 1);
        if (dcnClockMHz)
            RLOG("DCLK: requested=%u hardmin-response=%x softmax-response=%x applied=%u",
                 dcnClockMHz, power.dclkMinResponse, power.dclkMaxResponse,
                 power.dclkMinResponse == 1 && power.dclkMaxResponse == 1);
        if (gfxClockMHz)
            RLOG("GFXCLK: requested=%u hardmin-response=%x applied=%u", gfxClockMHz,
                 power.gfxMinResponse, power.gfxMinResponse == 1);
        if (power.error) return 1;
    }
    if (vcnStaticEnabled && !vcnDpgEnabled) {
        if (!ctx || !orgVcnWriteRegister || !orgVcnConfig ||
            !__atomic_load_n(&raphaelTargetConfirmed, __ATOMIC_ACQUIRE) ||
            *reinterpret_cast<const uint32_t *>(ctx + 0x268) != 0x30001 ||
            *reinterpret_cast<const uint64_t *>(ctx + 0x3f8) != hwlibsBase + 0x930f8 ||
            (*reinterpret_cast<const uint32_t *>(ctx) & 2)) return 1;
        auto read = reinterpret_cast<uint32_t (*)(void *, uint32_t, uint32_t)>(hwlibsBase + 0x86834);
        const uint32_t before = read(engine, 1, 4);
        if (before == 0xffffffff || before == 0xdeadbeef || (before & 0x80000000)) {
            RLOG("VCNMODE: inaccessible/stalled power status=%x; initialization refused", before);
            return 1;
        }
        // Linux stop_dpg_mode clears PG_MODE. Native static initialization only
        // clears 0x103 and otherwise inherits this dynamic-mode bit across reset.
        if (before & 4)
            FunctionCast(wrapVcnWriteRegister, orgVcnWriteRegister)(engine, 1, 4, before & ~4u);
        const uint32_t after = read(engine, 1, 4);
        RLOG("VCNMODE: static power before=%08x after=%08x", before, after);
        if (after == 0xffffffff || after == 0xdeadbeef || (after & 4)) return 1;
    }
    if (vcnDpgEnabled && vcnDecodeFirstEnabled && ctx &&
        __atomic_load_n(&raphaelTargetConfirmed, __ATOMIC_ACQUIRE) &&
        *reinterpret_cast<const uint32_t *>(ctx + 0x268) == 0x30001 &&
        !(*reinterpret_cast<const uint32_t *>(ctx) & 1) &&
        *reinterpret_cast<const uint32_t *>(ctx + 0x35c) == 0 &&
        reinterpret_cast<mach_vm_address_t>(__builtin_return_address(0)) == hwlibsBase + 0x88451) {
        auto manager = *reinterpret_cast<const uint32_t *const *>(
            static_cast<const uint8_t *>(engine) + 0x18);
        if (manager && manager[0] == 0) {
            // MODE2 can leave NJ_PAUSE_DPG_REQ asserted after a failed guest.
            // Match the native/Linux unpause write before fresh DPG startup,
            // only with no active queues and software pause state UNPAUSE.
            auto read = reinterpret_cast<uint32_t (*)(void *, uint32_t, uint32_t)>(hwlibsBase + 0x86834);
            auto write = reinterpret_cast<void (*)(void *, uint32_t, uint32_t, uint32_t)>(hwlibsBase + 0x8680f);
            const uint32_t before = read(engine, 1, 0x14);
            const bool selected = before != 0xffffffff && before != 0xdeadbeef && (before & 0xc);
            if (selected) write(engine, 1, 0x14, before & ~0xcu);
            RLOG("VCNUP: selected=%u before=%x after=%x software-pause=0 active=0",
                selected, before, read(engine, 1, 0x14));
        }
    }
    const bool corePowerTest = vcnCorePowerSelected(engine);
    if (corePowerTest) vcnCorePowerWaitSucceeded = false;
    const uint32_t result = FunctionCast(wrapVcnInitialize, orgVcnInitialize)(engine);
    if (corePowerTest) {
        auto read = reinterpret_cast<uint32_t (*)(void *, uint32_t, uint32_t)>(hwlibsBase + 0x86834);
        const uint32_t fsm = read(engine, 1, 1);
        RLOG("VCNCORE: initialized result=%u PGFSM=%08x power=%08x pause=%08x",
            result, fsm, read(engine, 1, 4), read(engine, 1, 0x14));
        // DPG may change the state after SRAM submission; require the actual
        // preceding on-state wait to have succeeded, not a permanently-on core.
        if (!vcnCorePowerWaitSucceeded) return 1;
    }
    RLOG("VCNS: native initialize returned%u", result);
    if (!result && vcnDecodeFirstEnabled && vcnDpgEnabled && ctx &&
        __atomic_load_n(&raphaelTargetConfirmed, __ATOMIC_ACQUIRE) &&
        *reinterpret_cast<const uint32_t *>(ctx + 0x268) == 0x30001 &&
        reinterpret_cast<mach_vm_address_t>(__builtin_return_address(0)) == hwlibsBase + 0x88451) {
        // Linux initializes the hardware RBC ring before its first NJ pause.
        // Use only an existing native-owned inactive decoder queue. Do not start
        // a queue or change the native queue-manager active count here.
        auto manager = *reinterpret_cast<const uint8_t *const *>(
            static_cast<const uint8_t *>(engine) + 0x18);
        auto queue = manager ? *reinterpret_cast<uint8_t *const *>(manager + 0x20) : nullptr;
        auto shared = *reinterpret_cast<const uint8_t *const *>(ctx + 0x388);
        const uint32_t flags = queue ? *reinterpret_cast<const uint32_t *>(queue) : 0xffffffff;
        const uint32_t type = queue ? *reinterpret_cast<const uint32_t *>(queue + 0x10) : 0;
        const uint32_t width = queue ? *reinterpret_cast<const uint32_t *>(queue + 0x54) : 0;
        const uint32_t count = queue ? *reinterpret_cast<const uint32_t *>(queue + 0x58) : 0;
        const uint64_t bytes = static_cast<uint64_t>(width) * count;
        const uint64_t gpu = queue ? *reinterpret_cast<const uint64_t *>(queue + 0x28) : 0;
        const uint64_t callback = queue ? *reinterpret_cast<const uint64_t *>(queue + 0x78) : 0;
        const uint8_t guard[] = {0x55,0x48,0x89,0xe5,0x41,0x57,0x41,0x56,
            0x41,0x54,0x53,0x48,0x8b,0x47,0x08,0x31,0xdb,0x80,0x78,0x2c,0x00};
        const bool selected = manager && queue && shared && type == 1 && !(flags & 1) &&
            !(*reinterpret_cast<const uint32_t *>(ctx) & 1) &&
            *reinterpret_cast<const uint32_t *>(manager) == 0 &&
            *reinterpret_cast<void *const *>(queue + 8) == engine &&
            *reinterpret_cast<void *const *>(queue + 0x38) && gpu &&
            bytes >= 256 && bytes <= 0x100000 && !(bytes & (bytes - 1)) &&
            static_cast<const uint8_t *>(engine)[0x2c] == 0 &&
            callback == hwlibsBase + 0x94fa3 &&
            !memcmp(reinterpret_cast<const void *>(callback), guard, sizeof(guard));
        RLOG("VCNDF: selected=%u queue=%p type=%u flags=%x active=%u bytes=%llu gpu=%llx callback=+%llx",
            selected, queue, type, flags, manager ? *reinterpret_cast<const uint32_t *>(manager) : 0xffffffff,
            bytes, gpu, callback ? callback - hwlibsBase : 0);
        if (selected) {
            auto read = reinterpret_cast<uint32_t (*)(void *, uint32_t, uint32_t)>(hwlibsBase + 0x86834);
            RLOG("VCNDF: before RBC=%x BAR=%x_%x RPTR=%x WPTR=%x pause=%x power=%x shared39=%x",
                read(engine,1,0x2de), read(engine,1,0x433), read(engine,1,0x432),
                read(engine,1,0x2e0), read(engine,1,0x2e1), read(engine,1,0x14), read(engine,1,4), shared[0x39]);
            const uint32_t initialized = reinterpret_cast<uint32_t (*)(void *)>(callback)(queue);
            RLOG("VCNDF: after result=%u RBC=%x BAR=%x_%x RPTR=%x WPTR=%x pause=%x power=%x shared39=%x",
                initialized, read(engine,1,0x2de), read(engine,1,0x433), read(engine,1,0x432),
                read(engine,1,0x2e0), read(engine,1,0x2e1), read(engine,1,0x14), read(engine,1,4), shared[0x39]);
        }
    }
    // Source/placement metadata is ordinary memory. Do not probe live DPG SRAM,
    // cache BARs, soft-reset state, guessed segment bases or adjacent registers.
    // Working Linux already established sentinel readbacks are inconclusive;
    // candidate273 lost host capture across this former diagnostic boundary.
    if (ctx) RLOG("VCNP: context fwID=%x placement=%llx bytes=%x regbase1=%x shared=%llx",
        *reinterpret_cast<const uint32_t *>(ctx + 0x2a0),
        *reinterpret_cast<const uint64_t *>(ctx + 0x2c0),
        *reinterpret_cast<const uint32_t *>(ctx + 0x2b0),
        *reinterpret_cast<const uint32_t *>(ctx + 0x38),
        *reinterpret_cast<const uint64_t *>(ctx + 0x378));
    return result;
}

static uint32_t wrapVcnReadFw(void *engine, void *input) {
    if (vcnFirmwareEnabled && engine && input) {
        auto in = static_cast<uint8_t *>(input);
        auto name = *reinterpret_cast<const char **>(in + 16);
        auto dst = *reinterpret_cast<void **>(in);
        auto capacity = *reinterpret_cast<const uint32_t *>(in + 8);
        auto ctx = *reinterpret_cast<const uint8_t **>(static_cast<uint8_t *>(engine) + 16);
        if (name && !strcmp(name, "ativvaxy_vcn3_1.dat") && ctx &&
            *reinterpret_cast<const uint32_t *>(ctx + 0x268) == 0x30001) {
            if (!dst || capacity < sizeof(raphaelVcnFirmware)) {
                RLOG("VCNF: refused buffer capacity=%u", capacity);
                return 0;
            }
            memcpy(dst, raphaelVcnFirmware, sizeof(raphaelVcnFirmware));
            RLOG("VCNF: supplied Raphael3.1.2 signed payload bytes=%lu version=0x04121015",
                 sizeof(raphaelVcnFirmware));
            return sizeof(raphaelVcnFirmware);
        }
    }
    return FunctionCast(wrapVcnReadFw, orgVcnReadFw)(engine, input);
}

static uint32_t wrapVcnHwInit(void *engine, void *input, void *output) {
    if (vcnApuEnabled && !vcnSharedSizeReady) {
        RLOG("VCNA: allocation guard failed; refusing native VCN HW initialization");
        return 1;
    }
    auto ctx = engine ? *reinterpret_cast<const uint8_t **>(
        static_cast<uint8_t *>(engine) + 16) : nullptr;
    if (ctx) RLOG("VCNF: HW init ip=%x flags=%x mode=%u fwPresent=%u fwBytes=%u fwVersion=%x",
        *reinterpret_cast<const uint32_t *>(ctx + 0x268),
        *reinterpret_cast<const uint32_t *>(ctx),
        *reinterpret_cast<const uint32_t *>(ctx + 0x2e0), ctx[0x278],
        *reinterpret_cast<const uint32_t *>(ctx + 0x288),
        *reinterpret_cast<const uint32_t *>(ctx + 0x298));
    auto result = FunctionCast(wrapVcnHwInit, orgVcnHwInit)(engine, input, output);
    if (!result && vcnApuEnabled && ctx) {
        auto shared = *reinterpret_cast<uint8_t * const *>(ctx + 0x388);
        auto size = *reinterpret_cast<const uint64_t *>(ctx + 0x368);
        if (size != 0x1000 || !shared ||
            *reinterpret_cast<const uint32_t *>(ctx + 0x380) != 0 ||
            *reinterpret_cast<const uint32_t *>(ctx + 0x268) != 0x30001 ||
            *reinterpret_cast<const uint32_t *>(ctx + 0x298) != 0x04121015) {
            RLOG("VCNA: shared state mismatch; refusing initialization completion");
            return 1;
        }
        // Linux VCN3.1.2: bit11 advertises SMU interface type at byte0x58.
        // The enlarged allocation is still owned and released by the native driver.
        shared[0x58] = 2;
        *reinterpret_cast<uint32_t *>(shared) |= 1u << 11;
        // Linux's matching 3.1.2 firmware advertises RB, MULTI_QUEUE, SW_RING
        // and SMU_INTERFACE (0xb40). Native Apple adds legacy bits0..2 and
        // FW_LOGGING even when the corresponding logging byte is disabled.
        const uint32_t appleFlags = *reinterpret_cast<const uint32_t *>(shared);
        if (appleFlags != 0xf47) {
            RLOG("VCNABI: unexpected shared flags=%x; comparison refused", appleFlags);
            return 1;
        }
        *reinterpret_cast<uint32_t *>(shared) = 0xb40;
        RLOG("VCNABI: flags %x -> %x cgc-mode=%u sw-ring=%u logging=%u",
            appleFlags, *reinterpret_cast<const uint32_t *>(shared),
            *reinterpret_cast<const uint32_t *>(shared + 0x0c), shared[0x41], shared[0x48]);
        RLOG("VCNA: shared bytes=%llu flags=%x SMU-interface=%u domain=%u gpu=%llx",
             size, *reinterpret_cast<const uint32_t *>(shared), shared[0x58],
             *reinterpret_cast<const uint32_t *>(ctx + 0x380),
             *reinterpret_cast<const uint64_t *>(ctx + 0x378));
        for (unsigned offset = 0; offset < 0x60; offset += 0x10) {
            const auto words = reinterpret_cast<const uint32_t *>(shared + offset);
            RLOG("VCNABI: offset=%x words=%08x %08x %08x %08x",
                offset, words[0], words[1], words[2], words[3]);
        }
    }
    if (!result && vcnDpgEnabled && ctx) {
        // Mode0 allocates SRAM natively only after a successful PSP load-status
        // query. Reject fallback/software ownership; initialize later obtains
        // the actual trusted firmware address through the native loaded wait.
        const bool nativePsp = raphaelGcSeen && hasUniqueRaphaelPciMarker() &&
            *reinterpret_cast<const uint32_t *>(ctx + 0x268) == 0x30001 &&
            *reinterpret_cast<const uint32_t *>(ctx + 0x2e0) == 0 &&
            (*reinterpret_cast<const uint32_t *>(ctx) & 0x20) == 0 &&
            *reinterpret_cast<const uint64_t *>(ctx + 0x3f8) == hwlibsBase + 0x943cf &&
            *reinterpret_cast<const uint64_t *>(ctx + 0x320) == 0x200 &&
            *reinterpret_cast<const uint32_t *>(ctx + 0x328) == 0x100 &&
            *reinterpret_cast<const uint32_t *>(ctx + 0x338) == 2 &&
            *reinterpret_cast<const uint64_t *>(ctx + 0x330) &&
            *reinterpret_cast<void *const *>(ctx + 0x340) &&
            !*reinterpret_cast<void *const *>(ctx + 0x2d0);
        RLOG("VCNPSP: native=%u mode=%u flags=%x initializer=+%llx SRAM=%llx cpu=%p bytes=%llx placeholders=preserved",
            nativePsp, *reinterpret_cast<const uint32_t *>(ctx + 0x2e0),
            *reinterpret_cast<const uint32_t *>(ctx),
            *reinterpret_cast<const uint64_t *>(ctx + 0x3f8) - hwlibsBase,
            *reinterpret_cast<const uint64_t *>(ctx + 0x330),
            *reinterpret_cast<void *const *>(ctx + 0x340),
            *reinterpret_cast<const uint64_t *>(ctx + 0x320));
        if (!nativePsp) return 1;
    }

    RLOG("VCNF: native HW init returned %u", result);
    return result;
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
        {kOffNbio72SetDbRange, &orgNbio72SetDbRange, reinterpret_cast<void *>(wrapNbio72SetDbRange),
         "nbio7_2_set_doorbell_aperture_range"},
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
    if (vcnWptrEnabled) {
        const uint8_t entry[] = {0x55,0x48,0x89,0xe5,0x41,0x57,0x41,0x56,
                                0x53,0x50,0x48,0x89,0xfb,0x4c,0x8b,0x7f,0x08};
        // MOV ECX,R14D; OR ECX,80000000; shared.wptr=ECX; SCRATCH2=ECX.
        // Match Linux vcn_v3_0_dec_ring_set_wptr's raw DWORD pointer in both
        // destinations. OR0 retains the native footprint and control flow.
        const uint8_t before[] = {0x44,0x89,0xf1,0x81,0xc9,0x00,0x00,0x00,0x80,0x89,0x48,0x34};
        const uint8_t after[]  = {0x44,0x89,0xf1,0x81,0xc9,0x00,0x00,0x00,0x00,0x89,0x48,0x34};
        const bool guard = !memcmp(reinterpret_cast<const void *>(base + 0x95650), entry, sizeof(entry)) &&
            !memcmp(reinterpret_cast<const void *>(base + 0x956b4), before, sizeof(before));
        bool patched = false;
        if (guard) {
            KernelPatcher::LookupPatch lp {&kexts[KextHWLibs], before, after, sizeof(before), 1};
            patcher.applyLookupPatch(&lp, reinterpret_cast<uint8_t *>(base + 0x956b4), sizeof(before) + 1);
            patched = patcher.getError() == KernelPatcher::Error::NoError &&
                !memcmp(reinterpret_cast<const void *>(base + 0x956b4), after, sizeof(after));
            patcher.clearError();
            if (patched) orgVcnDecodeSubmit = patcher.routeFunction(base + 0x95650,
                reinterpret_cast<mach_vm_address_t>(wrapVcnDecodeSubmit), true);
            patcher.clearError();
        }
        CRLOG("VCNQ: raw-wptr guard=%u patched=%u submit-route=%u", guard, patched,
              orgVcnDecodeSubmit != 0);
    }
    if (mmhubFixEnabled) {
        const uint8_t guard[] = {0x55,0x48,0x89,0xe5,0x41,0x57,0x41,0x56,
                                 0x41,0x55,0x41,0x54,0x53,0x50};
        if (!memcmp(reinterpret_cast<const void *>(base + 0x3675b), guard, sizeof(guard)) &&
            !memcmp(reinterpret_cast<const void *>(base + 0x36223), guard, sizeof(guard))) {
            orgMmhub21 = patcher.routeFunction(base + 0x3675b,
                reinterpret_cast<mach_vm_address_t>(wrapMmhub21), true);
            patcher.clearError();
            if (orgMmhub21) nativeMmhub23 = base + 0x36223;
        }
        RLOG("MHG: guarded runtime route=%u", orgMmhub21 != 0);
    }
    if (vcnResetEnabled || vcnDpgEnabled) {
        const uint8_t guard[] = {0x55,0x48,0x89,0xe5,0x48,0x8b,0x07,0x48,
                                 0x8b,0x7f,0x10,0x89,0xf6,0x03,0x54,0xb7,0x34};
        if (!memcmp(reinterpret_cast<const void *>(base + 0x8680f), guard, sizeof(guard))) {
            orgVcnWriteRegister = patcher.routeFunction(base + 0x8680f,
                reinterpret_cast<mach_vm_address_t>(wrapVcnWriteRegister), true);
            patcher.clearError();
        }
        RLOG("VCNR: guarded native write=%u", orgVcnWriteRegister != 0);
    }
    if (vcnStaticEnabled || vcnDpgEnabled) {
        // Complete instructions from audited HWLibs24G830+868d4, before any route.
        const uint8_t queryGuard[] = {0x55,0x48,0x89,0xe5,0x41,0x56,0x53,0x48,0x83,0xec,0x10,0x31,0xc9};
        if (!memcmp(reinterpret_cast<const void *>(base + 0x868d4), queryGuard, sizeof(queryGuard))) {
            orgVcnQueryFw = patcher.routeFunction(base + 0x868d4,
                reinterpret_cast<mach_vm_address_t>(wrapVcnQueryFw), true);
            patcher.clearError();
        }
        RLOG("VCNP: guarded query=%u", orgVcnQueryFw != 0);
        const uint8_t configGuard[] = {0x55,0x48,0x89,0xe5,0x41,0x57,0x41,0x56,0x53,0x48,0x83,0xec,0x28,0x48,0x8d,0x5d,0xe4};
        const uint8_t initializeGuard[] = {0x55,0x48,0x89,0xe5,0x41,0x56,0x53,0x48,0x83,0xec,0x20,0x48,0x89,0xfb};
        if (!memcmp(reinterpret_cast<const void *>(base + kOffVcnConfig), configGuard, sizeof(configGuard)) &&
            !memcmp(reinterpret_cast<const void *>(base + kOffVcnInitialize), initializeGuard, sizeof(initializeGuard))) {
            orgVcnInitialize = patcher.routeFunction(base + kOffVcnInitialize,
                reinterpret_cast<mach_vm_address_t>(wrapVcnInitialize), true);
            patcher.clearError();
            if (orgVcnInitialize) orgVcnConfig = patcher.routeFunction(base + kOffVcnConfig,
                reinterpret_cast<mach_vm_address_t>(wrapVcnConfig), true);
            patcher.clearError();
            RLOG("VCNS: guarded config=%u initialize=%u", orgVcnConfig != 0, orgVcnInitialize != 0);
        } else RLOG("VCNS: prologue mismatch; native config retained");
        // Candidate 252: route add_to_dpg_sram to inject the VCPU cache BAR into the secure DPG SRAM.
        const uint8_t dpgSramGuard[] = {0x55,0x48,0x89,0xe5,0x48,0x89,0xf0,0x48,0x8b,0x77,0x10,0x89,0xd2};
        if (!memcmp(reinterpret_cast<const void *>(base + kOffAddToDpgSram), dpgSramGuard, sizeof(dpgSramGuard))) {
            orgAddToDpgSram = patcher.routeFunction(base + kOffAddToDpgSram,
                reinterpret_cast<mach_vm_address_t>(wrapAddToDpgSram), true);
            patcher.clearError();
        }
        RLOG("VCNDPG: add_to_dpg_sram route=%u", orgAddToDpgSram != 0);
        // First 15 bytes are complete position-independent instructions in both
        // wait routines. The later RIP-relative callback LEA is not displaced.
        const uint8_t waitGuard[] = {0x55,0x48,0x89,0xe5,0x48,0x83,0xec,0x20,
                                    0x48,0x8d,0x45,0xe8,0x48,0x89,0x38};
        if (!memcmp(reinterpret_cast<const void *>(base + 0x86a3d), waitGuard, sizeof(waitGuard)) &&
            !memcmp(reinterpret_cast<const void *>(base + 0x86a9e), waitGuard, sizeof(waitGuard))) {
            orgVcnWait = patcher.routeFunction(base + 0x86a3d,
                reinterpret_cast<mach_vm_address_t>(wrapVcnWait), true);
            patcher.clearError();
            orgVcnWaitMs = patcher.routeFunction(base + 0x86a9e,
                reinterpret_cast<mach_vm_address_t>(wrapVcnWaitMs), true);
            patcher.clearError();
        }
        RLOG("VCNW: guarded wait=%u wait-ms=%u", orgVcnWait != 0, orgVcnWaitMs != 0);
    }
    if (vcnFirmwareEnabled) {
        const uint8_t readGuard[] = {0x55,0x48,0x89,0xe5,0x48,0x83,0xec,0x20};
        const uint8_t initGuard[] = {0x55,0x48,0x89,0xe5,0x41,0x57,0x41,0x56};
        if (!memcmp(reinterpret_cast<const void *>(base + kOffVcnReadFw), readGuard, sizeof(readGuard)) &&
            !memcmp(reinterpret_cast<const void *>(base + kOffVcnHwInit), initGuard, sizeof(initGuard))) {
            orgVcnHwInit = patcher.routeFunction(base + kOffVcnHwInit,
                reinterpret_cast<mach_vm_address_t>(wrapVcnHwInit), true);
            patcher.clearError();
            if (orgVcnHwInit) orgVcnReadFw = patcher.routeFunction(base + kOffVcnReadFw,
                reinterpret_cast<mach_vm_address_t>(wrapVcnReadFw), true);
            patcher.clearError();
            RLOG("VCNF: guarded routes read=%u init=%u", orgVcnReadFw != 0, orgVcnHwInit != 0);
            if (vcnApuEnabled && orgVcnReadFw && orgVcnHwInit) {
                const uint8_t before[] = {0x49,0xc7,0x81,0x68,0x03,0x00,0x00,0x58,0x00,0x00,0x00,0x41,0xc7,0x81,0x80,0x03,0x00,0x00,0x02,0x00,0x00,0x00,0x49,0x8b,0x3e,0x4d,0x8d,0x81,0x78,0x03,0x00,0x00,0x49,0x81,0xc1,0x90,0x03,0x00,0x00,0xc7,0x04,0x24,0x00,0x00,0x00,0x00,0xbe,0x58,0x00,0x00,0x00,0xba,0x00,0x01,0x00,0x00,0xb9,0x02,0x00,0x00,0x00,0xe8,0x03,0xee,0xff,0xff,0x49,0x89,0xc7,0x49,0x8b,0x4e,0x10,0x48,0x89,0x81,0x88,0x03,0x00,0x00};
                const uint8_t after[] = {0x49,0xc7,0x81,0x68,0x03,0x00,0x00,0x00,0x10,0x00,0x00,0x41,0xc7,0x81,0x80,0x03,0x00,0x00,0x00,0x00,0x00,0x00,0x49,0x8b,0x3e,0x4d,0x8d,0x81,0x78,0x03,0x00,0x00,0x49,0x81,0xc1,0x90,0x03,0x00,0x00,0xc7,0x04,0x24,0x00,0x00,0x00,0x00,0xbe,0x00,0x10,0x00,0x00,0xba,0x00,0x01,0x00,0x00,0xb9,0x00,0x00,0x00,0x00,0xe8,0x03,0xee,0xff,0xff,0x49,0x89,0xc7,0x49,0x8b,0x4e,0x10,0x48,0x89,0x81,0x88,0x03,0x00,0x00};
                // Guard both size arguments and both domain fields (allocation/release),
                // plus the native allocation call and CPU-pointer store. The wrapper
                // above refuses execution unless the complete replacement reads back.
                if (!memcmp(reinterpret_cast<const void *>(base + kOffVcnSharedSize), before, sizeof(before))) {
                    KernelPatcher::LookupPatch lp {&kexts[KextHWLibs], before, after, sizeof(before), 1};
                    patcher.applyLookupPatch(&lp, reinterpret_cast<uint8_t *>(base + kOffVcnSharedSize), sizeof(before) + 1);
                    RLOG("VCNA: allocation patch error=%u", static_cast<unsigned>(patcher.getError()));
                    vcnSharedSizeReady = !memcmp(reinterpret_cast<const void *>(base + kOffVcnSharedSize), after, sizeof(after));
                    patcher.clearError();
                }
                RLOG("VCNA: guarded shared allocation extension=%u", vcnSharedSizeReady);
            }
        } else RLOG("VCNF: prologue mismatch; firmware intervention refused");
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

// Keep the first functional lease experiment inside the CPU-visible BAR.
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
// Capacity discovery retains Apple's provider pool fields and separately records
// the logical framebuffer and CPU-visible BAR bounds for recovery diagnostics.
static bool discoverVramCapacities(RaphaelRecoveryV2::DiscoveredPoolCapacities &out);

static uint32_t wrapHwMemVram(void *self) {
    auto r = FunctionCast(wrapHwMemVram, orgHwMemVram)(self);
    if (self == nullptr) return r;
    discoveredCapacityValid = false;
    discoveredVramTotal = 0;
    discoveredBarVisible = 0;
    nativeProviderTotal = 0;
    nativeProviderVisible = 0;
    if ((r & 0xffU) == 0) return 0;
    auto f = reinterpret_cast<uint8_t *>(self);
    auto q = [f](size_t o) -> uint64_t & { return *reinterpret_cast<uint64_t *>(f + o); };
    hwMemObject = self;
    RaphaelRecoveryV2::DiscoveredPoolCapacities discoveredPools {};
    discoveredCapacityValid = discoverVramCapacities(discoveredPools);
    if (!discoveredCapacityValid) {
        RLOG("XH: native VRAM rejected: runtime GFXHUB/BAR capacity discovery failed");
        return 0;
    }
    discoveredVramTotal = discoveredPools.totalCapacity;
    discoveredBarVisible = discoveredPools.visibleCapacity;
    nativeProviderTotal = discoveredPools.pools.total;
    nativeProviderVisible = discoveredPools.pools.visible;
    if (discoveredPools.pools.total != q(0x40) || discoveredPools.pools.visible != q(0x48)) {
        RLOG("XH: native VRAM rejected: provider sizes total=%#llx visible=%#llx "
             "capacity total=%#llx BAR=%#llx", q(0x40), q(0x48),
             discoveredVramTotal, discoveredBarVisible);
        discoveredCapacityValid = false;
        return 0;
    }
    RLOG("XH: initVRAMInfo -> %u  base(+50)=%#llx fbPhysical(+58)=%#llx delta(+60)=%#llx "
         "size0=%#llx size1=%#llx | rawTotal=%#llx barVisible=%#llx "
         "providerTotal=%#llx providerVisible=%#llx poolA(0x68)=%#llx poolB(0x70)=%#llx",
         r, q(0x50), q(0x58), q(0x60), q(0x40), q(0x48), discoveredVramTotal,
         discoveredBarVisible, nativeProviderTotal, nativeProviderVisible, q(0x68), q(0x70));
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
// the startup decision point. Runtime video PM also reads this flag; AMDVA must
// not claim support for the disabled PowerPlay backend.
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
    if (recoveryLeaseConfigured && !recoveryLeaseState.kiqAllowed()) {
        RLOG("XH: startKIQ refused before native call: no valid OWNED lease");
        return 0xe00002bc;
    }
    bool nativeRestoreAttempted = false;
    RaphaelKiq::HaltedNativeTransaction haltedTx {};
    if (mqdFixMode == 2 && !prepareKiq(a, b, spec, nativeRestoreAttempted, &haltedTx)) {
        RLOG("XQ2: startKIQ refused: preflight or genuine dequeue failed");
        return 0xe00002bc; // same failure used by Apple's startKIQ queue-spec check
    }
    if (mqdNativeRestoreMode == 3 && !haltedTx.held) {
        CRLOG("XQ2: halted native probe refused: no exact probe admission");
        return 0xe00002bc;
    }
    if (nativeRestoreAttempted)
        CRLOG("XQ2: native restore entered after %s admission; non-authorizing",
              mqdNativeRestoreMode == 3 ? "validated contained-probe" :
              "unresolved dequeue timeout");
    bool thisProbeArmed = false;
    // The armed flag serialises the halted MEC + GRBM-selector critical section.
    // It must stay armed until every post-call readback and recontain write on the
    // paths below has finished, so release it at scope exit rather than right
    // after the native call returns.
    struct ProbeDisarm {
        bool armed = false;
        ~ProbeDisarm() {
            if (armed) __atomic_store_n(&nativeMecProbeArmed, 0, __ATOMIC_RELEASE);
        }
    } probeDisarm;
    if (mqdNativeRestoreMode == 3 && mqdFixMode == 2 && nativeRestoreAttempted && haltedTx.held) {
        uint32_t expected = 0;
        thisProbeArmed = __atomic_compare_exchange_n(
            &nativeMecProbeArmed, &expected, 1, false, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE);
        probeDisarm.armed = thisProbeArmed;
        if (!thisProbeArmed) {
            CRLOG("XQ4: native MEC probe refused: another scoped native call is armed");
            fbWrite(asicInfo, kGcCpMecCntl, haltedTx.savedMecControl | RaphaelKiq::kMecHaltMask);
            fbWrite(asicInfo, kGcGrbmGfxCntl, 0);
            return 0xe00002bc;
        }
    }
    auto r = FunctionCast(wrapKiqStart, orgKiqStart)(self, a, b, spec, out);
    RLOG("XJ:   PM4 startKIQ(%#llx, %#llx) -> %#x (0 is success)", a, b, r);
    if (mqdFixMode == 2) {
        fbWrite(asicInfo, kGcGrbmGfxCntl, kKiqSelector);
        reportKiqPreparation("after native startKIQ");
        if (haltedTx.held) {
            const uint32_t active = fbRead(asicInfo, kGcHqdActive);
            const uint32_t dequeue = fbRead(asicInfo, kGcHqdDequeue);
            const uint32_t eopCtl = fbRead(asicInfo, kGcHqdEopControl);
            const uint32_t eopLo = fbRead(asicInfo, kGcHqdEopBase);
            const uint32_t eopHi = fbRead(asicInfo, kGcHqdEopBaseHi);
            const uint32_t mqdLo = fbRead(asicInfo, kGcMqdBase);
            const uint32_t mqdHi = fbRead(asicInfo, kGcMqdBaseHi);
            const uint32_t pqLo = fbRead(asicInfo, kGcHqdPqBase);
            const uint32_t pqHi = fbRead(asicInfo, kGcHqdPqBaseHi);
            const uint32_t rptr = fbRead(asicInfo, kGcHqdPqRptr);
            const uint32_t wptrHi = fbRead(asicInfo, kGcHqdPqWptrHi);
            const uint32_t wptrLo = fbRead(asicInfo, kGcHqdPqWptrLo);
            const uint32_t mec = fbRead(asicInfo, kGcCpMecCntl);
            const bool verified = RaphaelKiq::haltedNativeResultVerified(
                r == 0, mec, active, dequeue, mqdLo, mqdHi, pqLo, pqHi, eopLo, eopHi,
                eopCtl, rptr, wptrHi, wptrLo, a, haltedTx.expectedPq, b,
                haltedTx.initialWptrLo, mqdNativeRestoreMode == 3);
            if (mqdNativeRestoreMode == 3) {
                CRLOG("XQ2: halted native probe result=%#x verified=%u MEC=%#x ACTIVE=%#x "
                      "DEQUEUE=%#x MQD=%#x_%08x PQ=%#x_%08x EOP=%#x_%08x ctl=%#x "
                      "RPTR=%#x WPTR=%#x_%08x; keeping MEC halted", r, verified, mec, active,
                      dequeue, mqdHi, mqdLo, pqHi, pqLo, eopHi, eopLo, eopCtl, rptr, wptrHi, wptrLo);
                fbWrite(asicInfo, kGcCpPqWptrPoll, 0);
                fbWrite(asicInfo, kGcHqdPqDbCtl, 0);
                fbWrite(asicInfo, kGcCpMecCntl, haltedTx.savedMecControl | RaphaelKiq::kMecHaltMask);
                IODelay(50);
                CRLOG("XQ2: halted native probe recontain MEC=%#x", fbRead(asicInfo, kGcCpMecCntl));
                fbWrite(asicInfo, kGcGrbmGfxCntl, 0);
                return 0xe00002bc;
            }
            const bool readable = mec != 0xffffffffU && active != 0xffffffffU &&
                dequeue != 0xffffffffU && eopCtl != 0xffffffffU;
            if (!verified)
                CRLOG("XQ2: halted native verify fields result=%#x readable=%u ACTIVE=%#x "
                      "DEQUEUE=%#x MEC=%#x MQD=%#x_%08x PQ=%#x_%08x EOP=%#x_%08x ctl=%#x "
                      "RPTR=%#x WPTR=%#x_%08x expectedPQ=%#llx", r, readable, active, dequeue,
                      mec, mqdHi, mqdLo, pqHi, pqLo, eopHi, eopLo, eopCtl, rptr, wptrHi,
                      wptrLo, haltedTx.expectedPq);
            auto read = [](RaphaelKiq::HaltedRegister reg) -> uint32_t {
                switch (reg) {
                    case RaphaelKiq::HaltedRegister::MecControl: return fbRead(asicInfo, kGcCpMecCntl);
                    case RaphaelKiq::HaltedRegister::Active: return fbRead(asicInfo, kGcHqdActive);
                    case RaphaelKiq::HaltedRegister::Dequeue: return fbRead(asicInfo, kGcHqdDequeue);
                    case RaphaelKiq::HaltedRegister::Rptr: return fbRead(asicInfo, kGcHqdPqRptr);
                    case RaphaelKiq::HaltedRegister::WptrHi: return fbRead(asicInfo, kGcHqdPqWptrHi);
                    case RaphaelKiq::HaltedRegister::WptrLo: return fbRead(asicInfo, kGcHqdPqWptrLo);
                    case RaphaelKiq::HaltedRegister::Poll: return fbRead(asicInfo, kGcCpPqWptrPoll);
                    case RaphaelKiq::HaltedRegister::Doorbell: return fbRead(asicInfo, kGcHqdPqDbCtl);
                }
                return 0xffffffffU;
            };
            auto write = [](RaphaelKiq::HaltedRegister reg, uint32_t value) {
                if (reg == RaphaelKiq::HaltedRegister::MecControl) fbWrite(asicInfo, kGcCpMecCntl, value);
            };
            const bool released = RaphaelKiq::releaseHaltedNative(
                haltedTx, read, write, [](unsigned us) { IODelay(us); }, r == 0, verified);
            if (!released) {
                const uint32_t mecAfterFailure = fbRead(asicInfo, kGcCpMecCntl);
                CRLOG("XQ2: dequeue refused: halted native verification failed; savedMEC=%#x currentMEC=%#x recontain_attempted=1",
                      haltedTx.savedMecControl, mecAfterFailure);
                fbWrite(asicInfo, kGcCpPqWptrPoll, 0);
                fbWrite(asicInfo, kGcHqdPqDbCtl, 0);
                fbWrite(asicInfo, kGcGrbmGfxCntl, 0);
                return 0xe00002bc;
            }
            CRLOG("XQ2: halted native release verified=1 savedMEC=%#x currentMEC=%#x released=1",
                  haltedTx.savedMecControl, fbRead(asicInfo, kGcCpMecCntl));
        }
        if (r == 0 && cpSurgeryEnabled && !nativeRestoreAttempted && !programMode2Eop(b)) {
            CRLOG("XQ2: mode-2 EOP programming/readback failed; KIQ submission blocked");
            fbWrite(asicInfo, kGcGrbmGfxCntl, 0);
            return 0xe00002bc;
        }
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
    reportGoldenState(when);
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
    // The golden registers are static; three samples (before/after RLC start
    // and the first KIQ submit) bound the serial volume.
    static unsigned goldenDumps = 0;
    if (goldenDumps < 3) { goldenDumps++; reportGoldenState(when); }
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

// Fill the EOP registers after native startKIQ. Mode 2 deliberately keeps this
// transaction separate from the exploratory doorbell-message surgery below.
static bool programMode2Eop(uint64_t eopAddr) {
    if (asicInfo == nullptr) return false;
    auto read = [](RaphaelKiq::EopRegister reg) -> uint32_t {
        switch (reg) {
            case RaphaelKiq::EopRegister::BaseLo: return fbRead(asicInfo, kGcHqdEopBase);
            case RaphaelKiq::EopRegister::BaseHi: return fbRead(asicInfo, kGcHqdEopBaseHi);
            case RaphaelKiq::EopRegister::Control: return fbRead(asicInfo, kGcHqdEopControl);
        }
        return 0xffffffffU;
    };
    auto write = [](RaphaelKiq::EopRegister reg, uint32_t value) {
        switch (reg) {
            case RaphaelKiq::EopRegister::BaseLo: fbWrite(asicInfo, kGcHqdEopBase, value); break;
            case RaphaelKiq::EopRegister::BaseHi: fbWrite(asicInfo, kGcHqdEopBaseHi, value); break;
            case RaphaelKiq::EopRegister::Control: fbWrite(asicInfo, kGcHqdEopControl, value); break;
        }
    };
    const bool ok = RaphaelKiq::programEopForNativeStart(read, write, eopAddr);
    RLOG("XQ2: mode-2 EOP %#llx_%08x ctl=%#x readback=%s", eopAddr >> 32,
         static_cast<uint32_t>(eopAddr), read(RaphaelKiq::EopRegister::Control),
         ok ? "ok" : "failed");
    return ok;
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
static uint64_t cachedBarMapLength = 0;
static void *cachedBarHardware = nullptr;
static void *cachedBarPci = nullptr;
static volatile uint32_t *fbAperture() {
    static void *cached {};
    void *hardware = hwMemObject != nullptr
        ? *reinterpret_cast<void **>(reinterpret_cast<uint8_t *>(hwMemObject) + 0x10)
        : nullptr;
    if (hardware == nullptr) hardware = hwObj;
    void *pci = hardware != nullptr
        ? *reinterpret_cast<void **>(reinterpret_cast<uint8_t *>(hardware) + 0x10) : nullptr;
    if (cached != nullptr && (hardware != cachedBarHardware || pci != cachedBarPci)) return nullptr;
    auto result = RaphaelRecovery::establishBarMapping(
        cached, hardware, hwMemObject, [](void *pci) -> void * {
            if (pci == nullptr) return nullptr;
            auto vt = *reinterpret_cast<uint64_t **>(pci);
            if (vt == nullptr || vt[0x908 / 8] == 0) return nullptr;
            auto mapFn = reinterpret_cast<void *(*)(void *, uint32_t, uint32_t)>(
                vt[0x908 / 8]);
            auto map = mapFn(pci, 0x10, 0);
            if (map == nullptr) return nullptr;
            auto mvt = *reinterpret_cast<uint64_t **>(map);
            if (mvt == nullptr || mvt[0x128 / 8] == 0 || mvt[0x118 / 8] == 0) return nullptr;
            auto getLength = reinterpret_cast<uint64_t (*)(void *)>(mvt[0x128 / 8]);
            const uint64_t length = getLength(map);
            if (length == 0) return nullptr;
            auto getVA = reinterpret_cast<uint64_t (*)(void *)>(mvt[0x118 / 8]);
            void *address = reinterpret_cast<void *>(getVA(map));
            if (address == nullptr) return nullptr;
            cachedBarMapLength = length;
            return address;
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
            cachedBarHardware = hardware;
            cachedBarPci = pci;
            RLOG("XN: BAR0 mapped at %p", result.address);
            break;
        case RaphaelRecovery::BarMappingStatus::Cached:
            break;
    }
    return reinterpret_cast<volatile uint32_t *>(result.address);
}

static bool discoverVramCapacities(RaphaelRecoveryV2::DiscoveredPoolCapacities &out) {
    if (asicInfo == nullptr || hwMemObject == nullptr || fbAperture() == nullptr) return false;
    if (*reinterpret_cast<void **>(reinterpret_cast<uint8_t *>(hwMemObject) + 0x10) == nullptr)
        return false;
    if (!RaphaelRecoveryV2::discoverPoolCapacities(
            fbRead(asicInfo, kGcFbBase), fbRead(asicInfo, kGcFbTop),
            cachedBarMapLength,
            *reinterpret_cast<uint64_t *>(reinterpret_cast<uint8_t *>(hwMemObject) + 0x40),
            *reinterpret_cast<uint64_t *>(reinterpret_cast<uint8_t *>(hwMemObject) + 0x48),
            out)) return false;
    return true;
}

static bool fitsDiscoveredBar(uint64_t offset, uint64_t length) {
    uint64_t end = 0;
    return discoveredCapacityValid && discoveredBarVisible != 0 &&
           RaphaelRecoveryV2::checkedAdd(offset, length, end) && end <= discoveredBarVisible;
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
    uint64_t visible = discoveredBarVisible;
    if (!discoveredCapacityValid || visible == 0) return false;
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
    if (!fitsDiscoveredBar(off, 0x800)) {
        RLOG("XN: mqd offset %#llx is outside the discovered BAR0 aperture", off); return;
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
    if (!fitsDiscoveredBar(pteOff, 8)) return;

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

// rgpuhangdump=1 (candidate 212). Candidates 210 and 211 stalled the graphics ring on
// channel 35 stamp 8 (RPTR 0x1e31, WPTR 0x2000, CP_STALLED_STAT2 QU_STALLED_ON_EOP_DONE_PULSE)
// with VM_FAULT_STATUS 0 while compute completed. At the first KIQ observation whose
// ring read pointer stays put for 50 ms with data pending, record what PFP, ME and CE
// last parsed and which indirect buffers they are inside. This path only reads
// registers; the ring and IB pages are read later by hangDumpThread, outside the KIQ
// submit call. Offsets: gc_10_3_0_offset.h (CP_IB1_OFFSET from gc_10_1_0, same block).
static uint32_t hangDumpMode = 0;
static constexpr uint32_t kGcCpMeHeaderDump  = kGcSeg0 + 0x0f41;
static constexpr uint32_t kGcCpPfpHeaderDump = kGcSeg0 + 0x0f42;
static constexpr uint32_t kGcCpCeHeaderDump  = kGcSeg0 + 0x0f44;
static constexpr uint32_t kGcCeInstrPntr     = kGcSeg0 + 0x0f47;
static constexpr uint32_t kGcRb0WptrHi       = kGcSeg0 + 0x1df5;
static constexpr uint32_t kGcGrbmStatusSe0   = kGcSeg0 + 0x0da5;
static constexpr uint32_t kGcGrbmStatus3     = kGcSeg0 + 0x0da7;
static constexpr uint32_t kGcPaScFifoSize    = kGcSeg0 + 0x1093;
static constexpr unsigned kHangDumpLimit = 3;
enum : unsigned { kHangIb1, kHangIb2, kHangCeIb1, kHangCeIb2, kHangIbCount };
enum : unsigned { kHangBaseLo, kHangBaseHi, kHangBufsz, kHangOffset };
static constexpr const char *const kHangIbNames[kHangIbCount] {"IB1", "IB2", "CE_IB1", "CE_IB2"};
static constexpr uint32_t kHangIbRegisters[kHangIbCount][4] {
    {kGcSeg1 + 0x20cc, kGcSeg1 + 0x20cd, kGcSeg1 + 0x20ce, kGcSeg1 + 0x2092},
    {kGcSeg1 + 0x20cf, kGcSeg1 + 0x20d0, kGcSeg1 + 0x20d1, kGcSeg1 + 0x2093},
    {kGcSeg1 + 0x20c6, kGcSeg1 + 0x20c7, kGcSeg1 + 0x20c8, kGcSeg1 + 0x2098},
    {kGcSeg1 + 0x20c9, kGcSeg1 + 0x20ca, kGcSeg1 + 0x20cb, kGcSeg1 + 0x2099},
};
struct GfxHangSnapshot {
    uint32_t rptr, wptr, baseLo, baseHi, cntl;
    uint32_t ib[kHangIbCount][4];
};
static GfxHangSnapshot hangSnapshots[kHangDumpLimit] {};
static volatile uint32_t hangSnapshotCount = 0;
static volatile uint32_t hangSnapshotBusy = 0;

static void logHeaderDump(const char *name, uint32_t reg) {
    uint32_t v[8];
    for (auto &value : v) value = fbRead(asicInfo, reg);
    RLOG("XD: %s x8: %08x %08x %08x %08x %08x %08x %08x %08x", name,
         v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7]);
}

static void observeGfxRingHang(const char *when) {
    if (hangDumpMode != 1 || asicInfo == nullptr) return;
    if (__atomic_load_n(&hangSnapshotCount, __ATOMIC_ACQUIRE) >= kHangDumpLimit) return;
    const uint32_t rptr = fbRead(asicInfo, kGcRb0Rptr);
    const uint32_t wptr = fbRead(asicInfo, kGcRb0Wptr);
    if (rptr == wptr || rptr == 0xdeadbeef) return;
    uint32_t after = rptr;
    for (unsigned i = 0; i < 5 && after == rptr; ++i) {
        IODelay(10000);
        after = fbRead(asicInfo, kGcRb0Rptr);
    }
    if (!RaphaelHang::ringStalled(rptr, wptr, after)) return;
    uint32_t expected = 0;
    if (!__atomic_compare_exchange_n(&hangSnapshotBusy, &expected, 1u, false,
                                     __ATOMIC_ACQUIRE, __ATOMIC_RELAXED)) return;
    const uint32_t index = __atomic_load_n(&hangSnapshotCount, __ATOMIC_ACQUIRE);
    static uint32_t lastDumpedRptr = UINT32_MAX;
    if (index >= kHangDumpLimit || rptr == lastDumpedRptr) {
        __atomic_store_n(&hangSnapshotBusy, 0u, __ATOMIC_RELEASE);
        return;
    }
    lastDumpedRptr = rptr;
    auto &snap = hangSnapshots[index];
    snap.rptr = rptr;
    snap.wptr = wptr;
    snap.baseLo = fbRead(asicInfo, kGcRb0Base);
    snap.baseHi = fbRead(asicInfo, kGcRb0BaseHi);
    snap.cntl = fbRead(asicInfo, kGcRb0Cntl);
    const auto ring = RaphaelHang::ringGeometry(snap.baseLo, snap.baseHi, snap.cntl);
    RLOG("XD: gfx hang dump %u at %s: RB0 RPTR=%#x static 50 ms, WPTR=%#x_%08x "
         "BASE=%#x_%08x (ring va %#llx, %#x dwords, valid=%u) CNTL=%#x VMID=%#x GRBM_GFX_CNTL=%#x",
         index, when, rptr, fbRead(asicInfo, kGcRb0WptrHi), wptr, snap.baseHi, snap.baseLo,
         ring.va, ring.dwords, ring.valid, snap.cntl, fbRead(asicInfo, kGcRbVmid),
         fbRead(asicInfo, kGcGrbmGfxCntl));
    logHeaderDump("CP_PFP_HEADER_DUMP", kGcCpPfpHeaderDump);
    logHeaderDump("CP_ME_HEADER_DUMP", kGcCpMeHeaderDump);
    logHeaderDump("CP_CE_HEADER_DUMP", kGcCpCeHeaderDump);
    for (unsigned n = 0; n < kHangIbCount; ++n) {
        for (unsigned r = 0; r < 4; ++r) snap.ib[n][r] = fbRead(asicInfo, kHangIbRegisters[n][r]);
        RLOG("XD: CP_%s BASE=%#x_%08x BUFSZ=%#x OFFSET=%#x", kHangIbNames[n],
             snap.ib[n][kHangBaseHi], snap.ib[n][kHangBaseLo], snap.ib[n][kHangBufsz],
             snap.ib[n][kHangOffset]);
    }
    RLOG("XD: GRBM_STATUS=%#x STATUS2=%#x STATUS3=%#x STATUS_SE0=%#x CP_STAT=%#x "
         "STALLED_STAT1=%#x 2=%#x 3=%#x BUSY_STAT=%#x",
         fbRead(asicInfo, kGcGrbmStatus), fbRead(asicInfo, kGcGrbmStatus2),
         fbRead(asicInfo, kGcGrbmStatus3), fbRead(asicInfo, kGcGrbmStatusSe0),
         fbRead(asicInfo, kGcCpStat), fbRead(asicInfo, kGcCpStalled1),
         fbRead(asicInfo, kGcCpStalled2), fbRead(asicInfo, kGcCpStalled3),
         fbRead(asicInfo, kGcCpBusyStat));
    const uint32_t pfp = fbRead(asicInfo, kGcPfpInstrPntr), me = fbRead(asicInfo, kGcMeInstrPntr);
    const uint32_t ce = fbRead(asicInfo, kGcCeInstrPntr);
    IODelay(20);
    RLOG("XD: PA_SC_FIFO_SIZE=%#x SPI_DEBUG_BUSY=unavailable (no GC 10.3 offset) "
         "instr PFP %#x->%#x ME %#x->%#x CE %#x->%#x fault=%#x addr=%#x_%08x",
         fbRead(asicInfo, kGcPaScFifoSize), pfp, fbRead(asicInfo, kGcPfpInstrPntr), me,
         fbRead(asicInfo, kGcMeInstrPntr), ce, fbRead(asicInfo, kGcCeInstrPntr),
         fbRead(asicInfo, kGcVmFaultSts), fbRead(asicInfo, kGcVmFaultHi),
         fbRead(asicInfo, kGcVmFaultLo));
    // Every ring frame waits on CP_COHER_STATUS bit 31 with CP_WAIT_REG_MEM_TIMEOUT 0.
    RLOG("XD: CP_COHER CNTL=%#x START_DELAY=%#x STATUS=%#x BASE=%#x_%08x SIZE=%#x | "
         "CP_ME_COHER CNTL=%#x STATUS=%#x | CP_WAIT_REG_MEM_TIMEOUT=%#x PFP_COMPLETION=%#x",
         fbRead(asicInfo, kGcSeg1 + 0x207c), fbRead(asicInfo, kGcSeg1 + 0x207b),
         fbRead(asicInfo, kGcSeg1 + 0x207f), fbRead(asicInfo, kGcSeg1 + 0x2079),
         fbRead(asicInfo, kGcSeg1 + 0x207e), fbRead(asicInfo, kGcSeg1 + 0x207d),
         fbRead(asicInfo, kGcSeg1 + 0x20fe), fbRead(asicInfo, kGcSeg1 + 0x2103),
         fbRead(asicInfo, kGcSeg1 + 0x2074), fbRead(asicInfo, kGcSeg1 + 0x20ec));
    RLOG("XD: PA_SC_ENHANCE=%#x ENHANCE_1=%#x ENHANCE_2=%#x ENHANCE_3=%#x "
         "PA_PH_INTERFACE_FIFO_SIZE=%#x PA_PH_ENHANCE=%#x BINNER_TIMEOUT=%#x",
         fbRead(asicInfo, kGcSeg0 + 0x109c), fbRead(asicInfo, kGcSeg0 + 0x109d),
         fbRead(asicInfo, kGcSeg0 + 0x107c), fbRead(asicInfo, kGcSeg0 + 0x1085),
         fbRead(asicInfo, kGcSeg0 + 0x1080), fbRead(asicInfo, kGcSeg0 + 0x1081),
         fbRead(asicInfo, kGcSeg0 + 0x1070));
    __atomic_store_n(&hangSnapshotCount, index + 1, __ATOMIC_RELEASE);
    __atomic_store_n(&hangSnapshotBusy, 0u, __ATOMIC_RELEASE);
}

// rgpuhangdump=1, candidate 213. Candidate 212 showed the ME parked in a WAIT_REG_MEM
// past dword 0x100 of WallpaperSequoia's draw IB, which Apple's restart report prints
// only up to 0x100 and which the BAR cannot reach (VMID 3 page tables sit above the
// 256 MiB aperture). The report itself maps each pending command buffer with
// IAMDHWChannel::mapCmdBuffers (IOAccelSysMemory::lockForCPUAccess), so wrap it: copy
// the whole buffer, sample every register WAIT_REG_MEM target while the ME is still
// parked, and leave formatting to hangDumpThread.
// rgpuaddrcfg: Apple's GFX10 address library (AMDHWAlignManager2::init builds its
// ADDR_CREATE_INPUT from the shared hardware-info block) chooses swizzle patterns and
// the pipe-bank xor from regValue.gbAddrConfig = hwinfo[0xa0]. The same block is copied
// to user space by AMDAccelDevice::getHardwareInfo. If it carries Navi23's pipe count
// while Raphael's GB_ADDR_CONFIG is 0x42 (4 pipes), GPU-only paths stay consistent but
// every CPU-visible texture layout is a tile permutation. Mode 1 reports the block;
// mode 2 also replaces hwinfo gbAddrConfig with the live register before the library is
// created.
static constexpr size_t kOffAlignManager2Init = 0x6032a;
    // __ZN33AMDRadeonX6000_AMDHWAlignManager24initEP30AMDRadeonX6000_IAMDHWInterface [x6]
static constexpr size_t kHwInfoGetterSlot = 0x1c0;    // IAMDHWInterface vtable: hwinfo block
static constexpr size_t kHwInfoGbAddrConfig = 0xa0;   // ADDR_CREATE_INPUT +0x30 gbAddrConfig
static constexpr size_t kHwInfoBackendDisables = 0xa8;
static constexpr size_t kHwInfoNoOfBanks = 0xb0;
static constexpr size_t kHwInfoNoOfRanks = 0xb8;
// rgpuhwcapclr=<mask>: clear bits of the 32-bit hardware-info field at 0xcc before the
// address library is created (the Metal driver reads capability bits there, for
// example 0x1000 before allowing variable-size swizzle modes).
static constexpr size_t kHwInfoCapabilities = 0xcc;
static uint32_t hwCapClearMask = 0;
static uint32_t addrConfigMode = 0;
static mach_vm_address_t orgAlignManager2Init = 0;

// rgpusdmacfg: the SDMA copy engine has its own GB_ADDR_CONFIG pair (GC seg0 0x1e/0x1f).
// Probe v7 fixed Shared-buffer copies by disabling Apple's blit DMA and synchronized
// textures by avoiding pipe-bank xor layouts: both are SDMA/DMA paths, and the tile
// permutation matches a 16-pipe/16-packer decoder. NootedRed programs both registers for
// APUs. Mode 1 logs them; mode 2 copies GB_ADDR_CONFIG's fields into both.
static constexpr uint32_t kSdmaGbAddrConfig     = kGcSeg0 + 0x001e;
static constexpr uint32_t kSdmaGbAddrConfigRead = kGcSeg0 + 0x001f;
static constexpr uint32_t kGbAddrConfigFields   = 0x0c1807ff;
static uint32_t sdmaAddrConfigMode = 0;

// rgputilelog=1: read-only sweep of every tiling-configuration register, to confirm none
// still holds a Navi23 value (like SDMA0_GB_ADDR_CONFIG's 0x444 did) once the copy path
// mishandles a texture. The remaining defect is texture-to-texture copies into a Managed
// texture: a per-surface pipe-bank-xor difference the copy does not apply. If every
// register below reads Raphael's value at probe time, the mismatch is driver-internal.
static constexpr uint32_t kGcGbBackendMap        = kGcSeg0 + 0x13df;  // GB_BACKEND_MAP
static constexpr uint32_t kGcCcRbBackendDisable  = kGcSeg0 + 0x13dd;  // CC_RB_BACKEND_DISABLE
static constexpr uint32_t kGcGbGpuId             = kGcSeg0 + 0x13e0;  // GB_GPU_ID
static constexpr uint32_t kGcGbEdcMode           = kGcSeg0 + 0x1e1e;  // GB_EDC_MODE
static constexpr uint32_t kGcRmiXbarConfig       = kGcSeg0 + 0x1527;  // RMI_XBAR_CONFIG
static constexpr uint32_t kGcRmiUtcUnitConfig    = kGcSeg0 + 0x152d;  // RMI_UTC_UNIT_CONFIG
static constexpr uint32_t kGcSpiConfigCntl       = kGcSeg0 + 0x11ec;  // SPI_CONFIG_CNTL
static constexpr uint32_t kGcPaScTileSteering    = kGcSeg1 + 0x00d7;  // PA_SC_TILE_STEERING_OVERRIDE
static uint32_t tileLogMode = 0;
static uint32_t tileLogCount = 0;

static void logTilingRegisters(const char *when) {
    if (tileLogMode == 0 || asicInfo == nullptr) return;
    if (__atomic_fetch_add(&tileLogCount, 1u, __ATOMIC_RELAXED) >= 40) return;
    RLOG("XT: tiling at %s: GB_ADDR_CONFIG=%#x READ=%#x BACKEND_MAP=%#x RB_BACKEND_DISABLE=%#x "
         "GB_GPU_ID=%#x EDC_MODE=%#x SDMA0=%#x/%#x RMI_XBAR=%#x RMI_UTC=%#x SPI_CFG=%#x "
         "TILE_STEER=%#x", when, fbRead(asicInfo, kGcGbAddrConfig),
         fbRead(asicInfo, kGcSeg0 + 0x13e2), fbRead(asicInfo, kGcGbBackendMap),
         fbRead(asicInfo, kGcCcRbBackendDisable), fbRead(asicInfo, kGcGbGpuId),
         fbRead(asicInfo, kGcGbEdcMode), fbRead(asicInfo, kSdmaGbAddrConfig),
         fbRead(asicInfo, kSdmaGbAddrConfigRead), fbRead(asicInfo, kGcRmiXbarConfig),
         fbRead(asicInfo, kGcRmiUtcUnitConfig), fbRead(asicInfo, kGcSpiConfigCntl),
         fbRead(asicInfo, kGcPaScTileSteering));
}

static void applySdmaAddrConfig(const char *when, bool quiet) {
    if (sdmaAddrConfigMode == 0 || asicInfo == nullptr) return;
    const uint32_t config = fbRead(asicInfo, kGcGbAddrConfig);
    const uint32_t sdma = fbRead(asicInfo, kSdmaGbAddrConfig);
    const uint32_t sdmaRead = fbRead(asicInfo, kSdmaGbAddrConfigRead);
    // Never merge layout bits with an inaccessible source OR destination.
    // In particular, preserving reserved bits from 0xffffffff would manufacture
    // a register write from a failed read during power transitions.
    if (config == 0 || config == 0xdeadbeef || config == 0xffffffffu ||
        sdma == 0xdeadbeef || sdma == 0xffffffffu ||
        sdmaRead == 0xdeadbeef || sdmaRead == 0xffffffffu) return;
    const uint32_t want = (sdma & ~kGbAddrConfigFields) | (config & kGbAddrConfigFields);
    const uint32_t wantRead = (sdmaRead & ~kGbAddrConfigFields) | (config & kGbAddrConfigFields);
    const bool change = sdmaAddrConfigMode == 2 && sdma != 0xdeadbeef && sdmaRead != 0xdeadbeef &&
                        (sdma != want || sdmaRead != wantRead);
    if (change) {
        fbWrite(asicInfo, kSdmaGbAddrConfig, want);
        fbWrite(asicInfo, kSdmaGbAddrConfigRead, wantRead);
    }
    if (!quiet || change)
        RLOG("XG: rgpusdmacfg=%u at %s: GB_ADDR_CONFIG=%#x SDMA0_GB_ADDR_CONFIG %#x -> %#x "
             "SDMA0_GB_ADDR_CONFIG_READ %#x -> %#x", sdmaAddrConfigMode, when, config, sdma,
             fbRead(asicInfo, kSdmaGbAddrConfig), sdmaRead, fbRead(asicInfo, kSdmaGbAddrConfigRead));
}

static uint64_t hwInfoField(const uint8_t *info, size_t offset) {
    uint64_t value = 0;
    memcpy(&value, info + offset, sizeof(value));
    return value;
}

static int wrapAlignManager2Init(void *that, void *hwInterface) {
    uint8_t *info = nullptr;
    if (hwInterface != nullptr) {
        void **vtable = *static_cast<void ***>(hwInterface);
        if (vtable != nullptr && vtable[kHwInfoGetterSlot / sizeof(void *)] != nullptr) {
            auto getter = reinterpret_cast<uint8_t *(*)(void *)>(vtable[kHwInfoGetterSlot / sizeof(void *)]);
            info = getter(hwInterface);
        }
    }
    const uint32_t live = asicInfo != nullptr ? fbRead(asicInfo, kGcGbAddrConfig) : 0xdeadbeef;
    if (info != nullptr) {
        RLOG("XA: hwinfo=%p numRasterPipe=%#llx numShaderPipes=%#llx gbAddrConfig=%#llx "
             "backendDisables=%#llx noOfBanks=%#llx noOfRanks=%#llx live GB_ADDR_CONFIG=%#x",
             info, hwInfoField(info, 0x18), hwInfoField(info, 0x20),
             hwInfoField(info, kHwInfoGbAddrConfig), hwInfoField(info, kHwInfoBackendDisables),
             hwInfoField(info, kHwInfoNoOfBanks), hwInfoField(info, kHwInfoNoOfRanks), live);
        uint32_t caps[6] = {};
        memcpy(caps, info + 0xc0, sizeof(caps));
        RLOG("XA: hwinfo[0xc0..0xd4]=%#x %#x %#x %#x %#x %#x", caps[0], caps[1], caps[2], caps[3],
             caps[4], caps[5]);
        if (hwCapClearMask != 0) {
            uint32_t capabilities = 0;
            memcpy(&capabilities, info + kHwInfoCapabilities, sizeof(capabilities));
            const uint32_t cleared = capabilities & ~hwCapClearMask;
            memcpy(info + kHwInfoCapabilities, &cleared, sizeof(cleared));
            RLOG("XA: rgpuhwcapclr=%#x hwinfo[0xcc] %#x -> %#x", hwCapClearMask, capabilities, cleared);
        }
        const uint64_t reported = hwInfoField(info, kHwInfoGbAddrConfig);
        // Mode 3: the Metal driver creates its own address library with gbAddrConfig
        // read as a 32-bit value at hwinfo[0xa4], the upper half of the kernel's 64-bit
        // field, which is 0 ("use the chip default": Navi's 16 pipes / 16 packers).
        if (addrConfigMode == 3 && live != 0xdeadbeef && live != 0) {
            uint32_t upper = 0;
            memcpy(&upper, info + kHwInfoGbAddrConfig + 4, sizeof(upper));
            memcpy(info + kHwInfoGbAddrConfig + 4, &live, sizeof(live));
            uint32_t check = 0;
            memcpy(&check, info + kHwInfoGbAddrConfig + 4, sizeof(check));
            RLOG("XA: rgpuaddrcfg=3 hwinfo[0xa4] %#x -> %#x (hwinfo[0xa0] qword now %#llx)", upper,
                 check, hwInfoField(info, kHwInfoGbAddrConfig));
        }
        if (addrConfigMode == 2 && live != 0xdeadbeef && live != 0 && reported != live) {
            const uint64_t replacement = live;
            memcpy(info + kHwInfoGbAddrConfig, &replacement, sizeof(replacement));
            RLOG("XA: rgpuaddrcfg=2 hwinfo gbAddrConfig %#llx -> %#llx", reported,
                 hwInfoField(info, kHwInfoGbAddrConfig));
        }
    } else {
        RLOG("XA: hwinfo getter unavailable (interface=%p)", hwInterface);
    }
    applySdmaAddrConfig("AMDHWAlignManager2::init", false);
    auto org = reinterpret_cast<int (*)(void *, void *)>(orgAlignManager2Init);
    const int result = org(that, hwInterface);
    RLOG("XA: AMDHWAlignManager2::init -> %#x", result);
    return result;
}

// rgpuswlog: AMDHWAlignManager2::getPreferredSwizzleMode2 (x6+0x60566) returns the
// swizzle mode the address library prefers for a surface. Mode 1 logs the first calls
// (input swizzle mode, resource type, format, size, flags and the returned mode);
// mode 2 also returns ADDR_SW_LINEAR (0) so kernel-chosen layouts are linear.
static constexpr size_t kOffPreferredSwizzleMode2 = 0x60566;
    // __ZN33AMDRadeonX6000_AMDHWAlignManager224getPreferredSwizzleMode2EP33_ADDR2_COMPUTE_SURFACE_INFO_INPUT [x6]
static uint32_t swizzleLogMode = 0;
static mach_vm_address_t orgPreferredSwizzleMode2 = 0;
static uint32_t swizzleLogCount = 0;

static uint32_t wrapPreferredSwizzleMode2(void *that, const uint8_t *input) {
    auto org = reinterpret_cast<uint32_t (*)(void *, const uint8_t *)>(orgPreferredSwizzleMode2);
    const uint32_t preferred = org(that, input);
    const uint32_t result = swizzleLogMode == 2 ? 0u : preferred;
    const uint32_t count = __atomic_fetch_add(&swizzleLogCount, 1u, __ATOMIC_RELAXED);
    if (count < 48 && input != nullptr) {
        uint32_t field[11] = {};
        memcpy(field, input, sizeof(field));
        RLOG("XS: preferred swizzle #%u flags=%#x mode=%u type=%u format=%u %ux%u slices=%u "
             "mips=%u -> %u%s", count, field[1], field[2], field[3], field[4], field[5], field[6],
             field[7], field[8], preferred, swizzleLogMode == 2 ? " (returned linear)" : "");
    }
    return result;
}


// rgpuvgpr: sampler-side swizzle enables before RLC start. 1 sets
// LDS_CONFIG.VGPR_SWIZZLE_EN (bit 1), 2 sets SQ_CONFIG.VGPR_SWIZZLE_EN (bit 12),
// 3 only logs both registers.
static constexpr uint32_t kGcSqConfig  = kGcSeg0 + 0x10a0;
static constexpr uint32_t kGcLdsConfig = kGcSeg0 + 0x10a2;
static uint32_t vgprMode = 0;

static void applyVgprSwizzle(const char *when) {
    if (vgprMode == 0 || asicInfo == nullptr) return;
    const uint32_t sq = fbRead(asicInfo, kGcSqConfig), lds = fbRead(asicInfo, kGcLdsConfig);
    if (vgprMode == 1 && lds != 0xdeadbeef) fbWrite(asicInfo, kGcLdsConfig, lds | 0x2u);
    if (vgprMode == 2 && sq != 0xdeadbeef) fbWrite(asicInfo, kGcSqConfig, sq | 0x1000u);
    RLOG("XV: rgpuvgpr=%u at %s: SQ_CONFIG %#x -> %#x, LDS_CONFIG %#x -> %#x", vgprMode, when,
         sq, fbRead(asicInfo, kGcSqConfig), lds, fbRead(asicInfo, kGcLdsConfig));
}

// rgpugbread: GB_ADDR_CONFIG_READ (seg0 0x13e2) mirrors GB_ADDR_CONFIG for software
// that derives texture swizzle layouts. Probe v7 reproduced every tile permutation as
// hardware writing with the 0x42 (4 pipe) layout and Apple's readers decoding with a
// 16-pipe/16-packer layout. NootedRed programs both registers with the same value.
// Mode 1 logs both registers; mode 2 also copies GB_ADDR_CONFIG into the READ mirror.
static constexpr uint32_t kGcGbAddrConfigRead = kGcSeg0 + 0x13e2;
static uint32_t gbReadMode = 0;

static void applyGbAddrConfigRead(const char *when) {
    if (gbReadMode == 0 || asicInfo == nullptr) return;
    const uint32_t config = fbRead(asicInfo, kGcGbAddrConfig);
    const uint32_t mirror = fbRead(asicInfo, kGcGbAddrConfigRead);
    if (gbReadMode == 2 && config != 0xdeadbeef && config != 0 && mirror != config)
        fbWrite(asicInfo, kGcGbAddrConfigRead, config);
    RLOG("XG: rgpugbread=%u at %s: GB_ADDR_CONFIG=%#x GB_ADDR_CONFIG_READ %#x -> %#x", gbReadMode,
         when, config, mirror, fbRead(asicInfo, kGcGbAddrConfigRead));
}

static constexpr size_t kOffPendingCommandReport = 0xd950;
    // __ZN30AMDRadeonX6000_AMDAccelChannel38writePendingCommandInfoDiagnosisReportERPcRjP18AMD_COMMAND_BUFFERP11IOAccelTask [x6]
static constexpr size_t kOffMapCmdBuffers = 0x4d58e;
    // __ZN28AMDRadeonX6000_IAMDHWChannel13mapCmdBuffersEP18AMD_COMMAND_BUFFERjP13AMD_MAPPED_CB [x6]
static constexpr size_t kOffUnmapCmdBuffers = 0x4d608;
    // __ZN28AMDRadeonX6000_IAMDHWChannel15unmapCmdBuffersEP18AMD_COMMAND_BUFFERjP13AMD_MAPPED_CB [x6]
static mach_vm_address_t orgPendingCommandReport = 0;
static mach_vm_address_t hangMapCmdBuffers = 0;
static mach_vm_address_t hangUnmapCmdBuffers = 0;
static constexpr unsigned kHangCbLimit = 2;
static constexpr uint32_t kHangCbMaxDwords = 0x4000;
static constexpr unsigned kHangWaitLimit = 16;
static constexpr unsigned kHangWaitSamples = 3;
struct HangWaitSample {
    uint32_t at;
    RaphaelHang::WaitRegMem wait;
    bool sampled;
    uint32_t values[kHangWaitSamples];
};
struct HangCommandBuffer {
    uint64_t va;
    uint32_t size;
    uint32_t copied;
    uint32_t waits;
    HangWaitSample wait[kHangWaitLimit];
    uint32_t words[kHangCbMaxDwords];
};
static HangCommandBuffer hangCbs[kHangCbLimit] {};
static volatile uint32_t hangCbCount = 0;
static volatile uint32_t hangCbBusy = 0;

static void capturePendingCommandBuffer(void *cb) {
    if (hangDumpMode != 1 || cb == nullptr || hangMapCmdBuffers == 0 ||
        hangUnmapCmdBuffers == 0)
        return;
    uint32_t expected = 0;
    if (!__atomic_compare_exchange_n(&hangCbBusy, &expected, 1u, false,
                                     __ATOMIC_ACQUIRE, __ATOMIC_RELAXED)) return;
    const uint32_t index = __atomic_load_n(&hangCbCount, __ATOMIC_ACQUIRE);
    const auto fields = reinterpret_cast<const uint8_t *>(cb);
    const uint32_t size = RaphaelVm::readU32(fields + 4);
    const uint64_t va = RaphaelVm::readU64(fields + 0x10);
    bool duplicate = false;
    for (uint32_t i = 0; i < index && i < kHangCbLimit; ++i) duplicate |= hangCbs[i].va == va;
    if (index >= kHangCbLimit || duplicate || size == 0) {
        __atomic_store_n(&hangCbBusy, 0u, __ATOMIC_RELEASE);
        return;
    }
    using CmdBufferMap = void (*)(void *, uint32_t, uint64_t *);
    uint64_t mapped = 0;
    reinterpret_cast<CmdBufferMap>(hangMapCmdBuffers)(cb, 1, &mapped);
    if (mapped == 0) {
        RLOG("XB: pending CB va=%#llx size=%#x not mappable", va, size);
        __atomic_store_n(&hangCbBusy, 0u, __ATOMIC_RELEASE);
        return;
    }
    auto &out = hangCbs[index];
    out.va = va;
    out.size = size;
    out.copied = size < kHangCbMaxDwords ? size : kHangCbMaxDwords;
    const auto source = reinterpret_cast<const uint32_t *>(mapped);
    for (uint32_t i = 0; i < out.copied; ++i) out.words[i] = source[i];
    reinterpret_cast<CmdBufferMap>(hangUnmapCmdBuffers)(cb, 1, &mapped);
    out.waits = 0;
    for (uint32_t at = 0; at < out.copied && out.waits < kHangWaitLimit;) {
        const uint32_t dwords = RaphaelHang::packetDwords(out.words[at]);
        if (dwords == 0) { ++at; continue; }
        const auto wait = RaphaelHang::parseWaitRegMem(out.words, out.copied, at);
        if (wait.valid) {
            auto &sample = out.wait[out.waits++];
            sample.at = at;
            sample.wait = wait;
            // Register targets only; an MMIO index past BAR5 is not read.
            sample.sampled = wait.memSpace == 0 && wait.address < 0x20000 && asicInfo != nullptr;
            for (unsigned k = 0; k < kHangWaitSamples; ++k) {
                sample.values[k] = sample.sampled
                    ? fbRead(asicInfo, static_cast<uint32_t>(wait.address)) : 0;
                if (sample.sampled && k + 1 < kHangWaitSamples) IODelay(1000);
            }
        }
        at += dwords;
    }
    __atomic_store_n(&hangCbCount, index + 1, __ATOMIC_RELEASE);
    __atomic_store_n(&hangCbBusy, 0u, __ATOMIC_RELEASE);
    RLOG("XB: pending CB %u va=%#llx size=%#x copied=%#x waits=%u", index, va, size, out.copied,
         out.waits);
    // Candidate 213 lost the worker's wait lines to console drops; the short capture-time
    // lines survived. Log each wait here as well.
    for (uint32_t n = 0; n < out.waits; ++n) {
        const auto &sample = out.wait[n];
        const auto &w = sample.wait;
        RLOG("XB: pending CB %u wait %u at=%#x fn=%u mem=%u oper=%u eng=%u addr=%#llx "
             "second=%#x ref=%#x mask=%#x interval=%#x sampled=%u values=%#x,%#x,%#x", index, n,
             sample.at, w.function, w.memSpace, w.operation, w.engine, w.address, w.second,
             w.reference, w.mask, w.interval, sample.sampled, sample.values[0], sample.values[1],
             sample.values[2]);
        // The packets that led the ME here: 24 dwords before the wait and its own seven.
        const uint32_t from = sample.at > 24 ? sample.at - 24 : 0;
        const uint32_t to = sample.at + 7 < out.copied ? sample.at + 7 : out.copied;
        char line[160];
        for (uint32_t first = from; first < to; first += 8) {
            int used = 0;
            for (uint32_t i = first; i < first + 8 && i < to; ++i)
                used += snprintf(line + used, sizeof(line) - used, " %08x", out.words[i]);
            RLOG("XB: pending CB %u wait %u ctx [0x%04x]%s", index, n, first, line);
        }
    }
}

static void wrapPendingCommandReport(void *channel, char **cursor, uint32_t *remaining,
                                     void *cb, void *task) {
    FunctionCast(wrapPendingCommandReport, orgPendingCommandReport)(channel, cursor, remaining,
                                                                    cb, task);
    capturePendingCommandBuffer(cb);
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
    observeGfxRingHang("KIQ observation");
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
    if (!fitsDiscoveredBar(kMecFwFbOffset, kMecFwSize)) {
        RLOG("XP: MEC ucode does not fit under the discovered BAR0 aperture"); return;
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
        if (vmRootFixEnabled || vmFaultDiagEnabled) {
            const uint32_t sequence = __atomic_load_n(
                &latestVmid2ProgramSequence, __ATOMIC_ACQUIRE);
            if (vmFaultDiagEnabled || (vmRootFixEnabled && sequence != 0)) {
                const uint32_t status = fbRead(asicInfo, kGcVmFaultSts);
                const uint64_t address = RaphaelVm::decodeFaultAddress(
                    fbRead(asicInfo, kGcVmFaultLo), fbRead(asicInfo, kGcVmFaultHi));
                if (vmFaultDiagEnabled && status != 0)
                    clientFaults.capture(status, address);
                if (vmRootFixEnabled && sequence != 0 &&
                    preClearFaultRecordBudget.take(
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
    // Candidate 181 found VMID2's first page-table block carrying an unconverted
    // MC address although every counted producer call was classified outside
    // the aperture: the earliest entries are written before any later gate can
    // open. Confirm the exact Raphael marker here, before the VMM can allocate,
    // so the entry-conversion gate is decided by the aperture snapshot alone.
    const bool markedAtInit = hwIface != nullptr && isRaphaelHardware(hwIface);
    auto r = FunctionCast(wrapVmmInit, orgVmmInit)(self, hwIface, flags);
    if (vmRootFixMode >= 2)
        CRLOG("VM: entry-gate init marked=%u aperture=%u mode=%u", markedAtInit,
              __atomic_load_n(&cachedFbPublished, __ATOMIC_ACQUIRE), vmRootFixMode);
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
static bool prepareKiq(uint64_t &mqdAddr, uint64_t &eopAddr, const void *spec,
                       bool &nativeRestoreAttempted,
                       RaphaelKiq::HaltedNativeTransaction *haltedTx) {
    nativeRestoreAttempted = false;
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
        if (prepared.status == Status::DequeueTimeout ||
            (mqdNativeRestoreMode == 3 && prepared.status == Status::PointerResetFailed)) {
            RaphaelKiq::QueueState fresh {
                fbRead(asicInfo, kGcHqdActive), fbRead(asicInfo, kGcHqdDequeue),
                fbRead(asicInfo, kGcHqdPqRptr), fbRead(asicInfo, kGcHqdPqWptrHi),
                fbRead(asicInfo, kGcHqdPqWptrLo), fbRead(asicInfo, kGcCpPqWptrPoll),
                fbRead(asicInfo, kGcHqdPqDbCtl)};
            auto memory = reinterpret_cast<uint8_t *>(hwMemObject);
            void *hardware = memory == nullptr ? nullptr :
                *reinterpret_cast<void **>(memory + 0x10);
            const bool leaseValid = recoveryLeaseConfigured &&
                recoveryLeaseState.kiqAllowed() &&
                RaphaelRecoveryV2::validOwnership(
                    recoveryLeaseState.ownership(), recoveryNonceLo, recoveryNonceHi,
                    memory == nullptr ? 0 :
                    RaphaelRecoveryV2::compatibilityPoolSize(
                        RaphaelRecoveryV2::nativePoolSizes(
                            *reinterpret_cast<uint64_t *>(memory + 0x40),
                            *reinterpret_cast<uint64_t *>(memory + 0x48))));
            const bool ownersMatch =
                __atomic_load_n(&recoveryLeaseMemoryOwner, __ATOMIC_ACQUIRE) == hwMemObject &&
                __atomic_load_n(&recoveryLeaseHardwareOwner, __ATOMIC_ACQUIRE) == hardware &&
                hardware != nullptr;
            const uint64_t freshImageMqd =
                (static_cast<uint64_t>(get(0x204)) << 32) | get(0x200);
            const uint64_t freshImageEop =
                (static_cast<uint64_t>(get(0x298)) << 32) | get(0x294);
            const bool imageStillExact = get(0) == 0xc0310800 && get(0x20c) == 0 &&
                freshImageMqd == planned.mqdMc &&
                freshImageEop == (planned.eopMc >> 8);
            nativeRestoreAttempted = prepared.status == Status::DequeueTimeout
                ? RaphaelKiq::timeoutNativeRestoreEligible(
                    mqdNativeRestoreMode != 0, mqdAddr, eopAddr, planned.mqdMc, planned.eopMc,
                    fresh, leaseValid, ownersMatch, imageStillExact)
                : RaphaelKiq::inactiveRetainedProbeEligible(
                    mqdNativeRestoreMode == 3, mqdAddr, eopAddr, planned.mqdMc, planned.eopMc,
                    fresh, leaseValid, ownersMatch, imageStillExact);
            CRLOG("XQ2: dequeue %s after %u us; descriptor unchanged; "
                  "native-restore=%u lease=%u owners=%u active=%#x dequeue=%#x "
                  "poll=%#x doorbell=%#x image-exact=%u",
                  prepared.status == Status::DequeueTimeout ? "TIMEOUT" : "INACTIVE-RETAINED",
                  prepared.elapsedUs,
                  nativeRestoreAttempted,
                  leaseValid, ownersMatch, fresh.active, fresh.dequeue, fresh.poll,
                  fresh.doorbell, imageStillExact);
            if (nativeRestoreAttempted) {
                if (mqdNativeRestoreMode >= 2 && haltedTx != nullptr) {
                    const uint64_t expectedPqBefore =
                        (static_cast<uint64_t>(get(0x224)) << 32) | get(0x220);
                    if (expectedPqBefore == 0) {
                        CRLOG("XQ2: dequeue refused: halted native setup has empty MQD PQ image");
                        fbWrite(asicInfo, kGcGrbmGfxCntl, 0);
                        return false;
                    }
                    fbWrite(asicInfo, kGcGrbmGfxCntl, kKiqSelector);
                    auto read = [](RaphaelKiq::HaltedRegister reg) -> uint32_t {
                        switch (reg) {
                            case RaphaelKiq::HaltedRegister::MecControl: return fbRead(asicInfo, kGcCpMecCntl);
                            case RaphaelKiq::HaltedRegister::Active: return fbRead(asicInfo, kGcHqdActive);
                            case RaphaelKiq::HaltedRegister::Dequeue: return fbRead(asicInfo, kGcHqdDequeue);
                            case RaphaelKiq::HaltedRegister::Rptr: return fbRead(asicInfo, kGcHqdPqRptr);
                            case RaphaelKiq::HaltedRegister::WptrHi: return fbRead(asicInfo, kGcHqdPqWptrHi);
                            case RaphaelKiq::HaltedRegister::WptrLo: return fbRead(asicInfo, kGcHqdPqWptrLo);
                            case RaphaelKiq::HaltedRegister::Poll: return fbRead(asicInfo, kGcCpPqWptrPoll);
                            case RaphaelKiq::HaltedRegister::Doorbell: return fbRead(asicInfo, kGcHqdPqDbCtl);
                        }
                        return 0xffffffffU;
                    };
                    auto write = [](RaphaelKiq::HaltedRegister reg, uint32_t value) {
                        switch (reg) {
                            case RaphaelKiq::HaltedRegister::MecControl: fbWrite(asicInfo, kGcCpMecCntl, value); break;
                            case RaphaelKiq::HaltedRegister::Active: fbWrite(asicInfo, kGcHqdActive, value); break;
                            case RaphaelKiq::HaltedRegister::Dequeue: fbWrite(asicInfo, kGcHqdDequeue, value); break;
                            case RaphaelKiq::HaltedRegister::Rptr: fbWrite(asicInfo, kGcHqdPqRptr, value); break;
                            case RaphaelKiq::HaltedRegister::WptrHi: fbWrite(asicInfo, kGcHqdPqWptrHi, value); break;
                            case RaphaelKiq::HaltedRegister::WptrLo: fbWrite(asicInfo, kGcHqdPqWptrLo, value); break;
                            default: break;
                        }
                    };
                    if (!RaphaelKiq::beginHaltedNative(*haltedTx, read, write,
                                                       [](unsigned us) { IODelay(us); },
                                                       mqdNativeRestoreMode == 3)) {
                        CRLOG("XQ2: dequeue refused: halted native setup failed savedMEC=%#x currentMEC=%#x held=%u",
                              haltedTx->savedMecControl, read(RaphaelKiq::HaltedRegister::MecControl),
                              haltedTx->held);
                        reportKiqPreparation("halted setup refused");
                        fbWrite(asicInfo, kGcGrbmGfxCntl, 0);
                        return false;
                    }
                    haltedTx->expectedPq = expectedPqBefore;
                    const uint64_t expectedPqAgain =
                        (static_cast<uint64_t>(get(0x224)) << 32) | get(0x220);
                    if (haltedTx->expectedPq == 0 || haltedTx->expectedPq != expectedPqAgain) {
                        CRLOG("XQ2: dequeue refused: halted native setup has unstable MQD PQ image "
                              "first=%#llx second=%#llx", haltedTx->expectedPq, expectedPqAgain);
                        fbWrite(asicInfo, kGcGrbmGfxCntl, 0);
                        return false;
                    }
                    RLOG("XQ2: halted-native setup complete; native owns HQD programming");
                    return true;
                }
                fbWrite(asicInfo, kGcGrbmGfxCntl, 0);
                RLOG("XQ2: native restore admission restores selector zero; Apple owns timeout/reprogram sequence");
                return true;
            }
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
    if (imgOff == ~0ULL || !fitsDiscoveredBar(imgOff, 0x800)) {
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

// Native +6246c tests AL and +6248f tail-calls the Boolean hub method.
static bool wrapVmmFillRegs(void *self) {
    auto r = FunctionCast(wrapVmmFillRegs, orgVmmFillRegs)(self);
    if (mmhubFixEnabled && self != nullptr && r != 0) {
        auto table = reinterpret_cast<uint32_t *>(static_cast<uint8_t *>(self) +
                                                   RaphaelMmhub::kHub1Offset);
        const auto result = RaphaelMmhub::repair(table, RaphaelMmhub::kWords * 4,
            true, __atomic_load_n(&raphaelTargetConfirmed, __ATOMIC_ACQUIRE));
        const bool corrected = result == RaphaelMmhub::Result::Repaired ||
                               result == RaphaelMmhub::Result::AlreadyCorrect;
        __atomic_store_n(&mmhubTableCorrect, corrected, __ATOMIC_RELEASE);
        RLOG("MH: hub1 table result=%u corrected=%u root2=%#x req6=%#x ack6=%#x",
             static_cast<uint32_t>(result), corrected, table[12+2*7],
             table[124+6*5+2], table[124+6*5+3]);
        // Abort VMM initialization if the requested ABI correction was refused.
        if (!corrected) return 0;
    }
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
        fbOffsetSnapshot, mmhubFixEnabled &&
            __atomic_load_n(&mmhubTableCorrect, __ATOMIC_ACQUIRE));
    const void *nativeInfo = local.valid ? static_cast<const void *>(local.bytes) : info;
    FunctionCast(wrapVmmPrepare, orgVmmPrepare)(self, prepared, nativeInfo, alternate);
    auto observation = RaphaelVm::observePreparedRequest(
        reinterpret_cast<const uint8_t *>(info), info != nullptr ? 0x28 : 0,
        reinterpret_cast<const uint8_t *>(nativeInfo), nativeInfo != nullptr ? 0x28 : 0,
        reinterpret_cast<const uint8_t *>(prepared), prepared != nullptr ? 0x54 : 0,
        alternate, local.repaired, local.reason);
    if (mmhubFixEnabled && observation.valid && observation.request.hub == 1)
        mmhubPrograms.append(observation);
    if (observation.valid && observation.request.hub == 0 &&
            observation.request.vmid == 2) {
        observation.sequence = __sync_add_and_fetch(&nextVmObservationSequence, 1u);
        observation.threadToken = reinterpret_cast<uintptr_t>(current_thread());
        vmid2Programs.append(observation);
        __atomic_store_n(&latestVmid2ProgramSequence, observation.sequence, __ATOMIC_RELEASE);
    }
}

static uint32_t *wrapFillMapProcess(void *self, uint32_t *packet, uint64_t root,
                                    uint64_t trapBase, uint32_t queueCount,
                                    uint32_t pasid, uint32_t flags) {
    auto end = FunctionCast(wrapFillMapProcess, orgFillMapProcess)(
        self, packet, root, trapBase, queueCount, pasid, flags);
    const bool returnValid = packet != nullptr && end == packet + 0x10;
    uint32_t header = 0;
    uint64_t nativeRoot = 0;
    RaphaelVm::MapProcessRepair repair {};
    if (returnValid) {
        __builtin_memcpy(&header, packet, sizeof(header));
        __builtin_memcpy(&nativeRoot, reinterpret_cast<uint8_t *>(packet) + 8,
                         sizeof(nativeRoot));
        const bool marked = __atomic_load_n(&raphaelTargetConfirmed, __ATOMIC_ACQUIRE);
        const bool published = __atomic_load_n(&cachedFbPublished, __ATOMIC_ACQUIRE);
        repair = RaphaelVm::repairMapProcessPacket(
            reinterpret_cast<uint8_t *>(packet), 0x40, vmRootFixMode == 5,
            marked && published,
            __atomic_load_n(&cachedFbBase, __ATOMIC_RELAXED),
            __atomic_load_n(&cachedFbTop, __ATOMIC_RELAXED),
            __atomic_load_n(&cachedFbOffset, __ATOMIC_RELAXED));
    }
    uint64_t finalRoot = nativeRoot;
    if (returnValid)
        __builtin_memcpy(&finalRoot, reinterpret_cast<uint8_t *>(packet) + 8,
                         sizeof(finalRoot));
    vmMapProcessSamples.append(RaphaelVm::MapProcessObservation {
        root, nativeRoot, finalRoot, pasid, header,
        static_cast<uint32_t>(repair.reason), returnValid, repair.repaired});
    return end;
}

// AMDGFX10VMM::getPDEValue(level, tableAddress) and getPTEValue(level, pageAddress,
// flags, fragment) keep the address bits they receive and add attributes only.
// Apple's video-memory objects carry framebuffer MC addresses, while GFXHUB
// consumes physical table and page addresses. Candidate 180 proved that rule for
// the VMID2 root: the prepared root 0x84b6f3000 matched the live register and the
// walker then faulted one level below with MAPPING_ERROR. These wrappers apply
// the identical aperture arithmetic to the entries below the root. They run under
// X6000 locks: cached snapshots, pure arithmetic, atomic counters, lock-free
// samples; no MMIO, log, allocation or wait.
static uint64_t convertVmEntryAddress(RaphaelVm::EntryKind kind, uint32_t level,
                                      uint32_t flags, bool system, uint64_t address) {
    const uint32_t fbBase = __atomic_load_n(&cachedFbBase, __ATOMIC_RELAXED);
    const uint32_t fbTop = __atomic_load_n(&cachedFbTop, __ATOMIC_RELAXED);
    const uint32_t fbOffset = __atomic_load_n(&cachedFbOffset, __ATOMIC_RELAXED);
    uint64_t result = address;
    const auto domain = RaphaelVm::convertEntryAddress(address, system, fbBase, fbTop,
                                                       fbOffset, result);
    const size_t k = kind == RaphaelVm::EntryKind::Pde ? 0 : 1;
    __atomic_fetch_add(&vmEntryCounts[k][static_cast<size_t>(domain)], 1u,
                       __ATOMIC_RELAXED);
    vmEntrySamples[k].append(RaphaelVm::EntryConversionSample {
        kind, level, flags, address, result, domain});
    return result;
}

static bool vmEntryConversionActive(uint32_t minimumMode) {
    return vmRootFixMode >= minimumMode && vmRootFixMode <= 3 &&
        __atomic_load_n(&raphaelTargetConfirmed, __ATOMIC_ACQUIRE) &&
        __atomic_load_n(&cachedFbPublished, __ATOMIC_ACQUIRE);
}

static uint64_t wrapVmmGetPde(void *self, uint32_t level, uint64_t address) {
    if (vmEntryConversionActive(2))
        address = convertVmEntryAddress(RaphaelVm::EntryKind::Pde, level, 0, false,
                                        address);
    else
        __atomic_fetch_add(&vmEntryInactive[0], 1u, __ATOMIC_RELAXED);
    return FunctionCast(wrapVmmGetPde, orgVmmGetPde)(self, level, address);
}

// VmMapFlags bit 3 becomes PTE SYSTEM (24G830 0x62a18..0x62a2b): a system page keeps
// its guest physical address; only video-memory pages live in the MC aperture.
static uint64_t wrapVmmGetPte(void *self, uint32_t level, uint64_t address,
                              uint32_t flags, uint32_t fragment) {
    if (vmEntryConversionActive(3))
        address = convertVmEntryAddress(RaphaelVm::EntryKind::Pte, level, flags,
                                        (flags & 0x8u) != 0, address);
    else
        __atomic_fetch_add(&vmEntryInactive[1], 1u, __ATOMIC_RELAXED);
    return FunctionCast(wrapVmmGetPte, orgVmmGetPte)(self, level, address, flags,
                                                     fragment);
}

// X6000 24G830 builds an attribute-only PDE/PTE template, then passes the real
// address separately in the third numeric argument here. Candidate 182's
// getPDEValue/getPTEValue hooks therefore never saw that address. Convert only
// this source operand; destination, count, template and increment remain native.
// This callback can run under X6000 VM locks, so it uses only cached state, pure
// arithmetic, atomics and bounded append-only observations.
static void wrapVmmUpdateEntries(void *self, uint64_t destination, uint64_t count,
                                 uint64_t source, uint64_t templateValue,
                                 uint64_t increment) {
    const uint64_t returnAddress =
        reinterpret_cast<uint64_t>(__builtin_return_address(0));
    const uint64_t callerOffset = x6Base != 0 && returnAddress >= x6Base
        ? returnAddress - x6Base : UINT64_MAX;
    const bool active = vmRootFixMode >= 4 &&
        __atomic_load_n(&raphaelTargetConfirmed, __ATOMIC_ACQUIRE) &&
        __atomic_load_n(&cachedFbPublished, __ATOMIC_ACQUIRE);
    const auto decision = RaphaelVm::prepareEntryUpdate(
        active,
        __atomic_load_n(&cachedFbBase, __ATOMIC_RELAXED),
        __atomic_load_n(&cachedFbTop, __ATOMIC_RELAXED),
        __atomic_load_n(&cachedFbOffset, __ATOMIC_RELAXED),
        callerOffset, destination, count, source, templateValue, increment);
    auto native = FunctionCast(wrapVmmUpdateEntries, orgVmmUpdateEntries);
    RaphaelVm::forwardEntryUpdate(native, self, decision);

    if (decision.domain == RaphaelVm::UpdateDomain::Converted) {
        if (decision.producer == RaphaelVm::UpdateProducer::Child)
            vmUpdateChildSamples.append(decision);
        else
            vmUpdateEligibleSamples.append(decision);
    } else {
        vmUpdateControlSamples.append(decision);
    }
    // Publish the cumulative returned-call count after the corresponding
    // sample is either ready or deliberately omitted by the bounded buffer.
    __atomic_fetch_add(&vmUpdateCounts[static_cast<size_t>(decision.domain)], 1u,
                       __ATOMIC_RELEASE);
}

static bool recoveryLeaseDisjointFromLiveGart(
        const RaphaelRecoveryV2::OwnershipDescriptor &descriptor) {
    if (asicInfo == nullptr) return false;
    RaphaelGart::Aperture aperture {};
    RaphaelGart::Range range {};
    RaphaelGart::Table table {};
    const uint64_t root =
        (static_cast<uint64_t>(fbRead(asicInfo, kGcVmCtx0PtbHi)) << 32) |
        fbRead(asicInfo, kGcVmCtx0PtbLo);
    const uint32_t control = fbRead(asicInfo, kGcVmCtx0Cntl);
    const bool decoded = gartApertureInfo(aperture) && gartRange(range) &&
        RaphaelGart::physicalTable(aperture, range, control, root, table);
    const bool disjoint = decoded && RaphaelRecoveryV2::disjointFromRange(
        descriptor, table.offset, table.bytes, aperture.visibleBytes);
    RLOG("XH: v2 live GART validation decoded=%u table=%#llx-%#llx "
         "lease=%#llx-%#llx disjoint=%u", decoded, table.offset,
         table.offset + table.bytes, descriptor.leaseOffset,
         descriptor.leaseEnd, disjoint);
    return disjoint;
}

static bool writeRecoveryLifetime(
        const RaphaelRecoveryV3::LifetimeStatus &status, bool aborting) {
    auto fb = fbAperture();
    if (fb == nullptr) return false;
    const uint64_t base = status.leaseOffset + RaphaelRecoveryV3::LifetimeOffset;
    auto write = [=](uint32_t i, uint32_t value) {
        fb[base / sizeof(uint32_t) + i] = value;
    };
    auto read = [=](uint32_t i) {
        return fb[base / sizeof(uint32_t) + i];
    };
    auto fence = [] { OSSynchronizeIO(); };
    return aborting
        ? RaphaelRecoveryV3::publishAbortLifetime(status, write, read, fence)
        : RaphaelRecoveryV3::publishValidLifetime(status, write, read, fence);
}

static void abortRecoveryLifetime(RaphaelRecoveryV3::LifetimeReason reason) {
    const auto request = recoveryLifetimeGate.requestAbort(reason);
    recoveryLeaseState.invalidate();
    if (request == RaphaelRecoveryV3::AbortRequest::Owner) {
        const auto aborted = RaphaelRecoveryV3::makeAbortLifetime(
            recoveryLifetimeStatus, reason);
        const bool published = writeRecoveryLifetime(aborted, true);
        if (published) recoveryLifetimeStatus = aborted;
        recoveryLifetimeGate.finishAbortPublication(published);
        CRLOG("XH3 LIFETIME state=ABORT reason=%u nonce=%016llx_%016llx "
              "durable=%u", static_cast<uint32_t>(reason), recoveryNonceLo,
              recoveryNonceHi, published);
    }
}

static bool authorizeRecoveryClients(
        const RaphaelRecoveryV2::PoolStatus &status) {
    if (!__atomic_load_n(&recoveryActivePoolStatusReady, __ATOMIC_ACQUIRE) ||
        __builtin_memcmp(&status, &recoveryActivePoolStatus, sizeof(status)) != 0 ||
        recoveryLeaseState.phase() != RaphaelRecoveryV2::Phase::PoolVerified ||
        recoveryLeaseState.clientsAllowed() ||
        !RaphaelRecoveryV2::validPoolStatus(
            recoveryActivePoolStatus, recoveryLeaseState.ownership()) ||
        !recoveryLifetimeGate.beginValidPublication())
        return false;

    const auto valid = RaphaelRecoveryV3::makeValidLifetime(
        recoveryLeaseState.ownership(), recoveryActivePoolStatus);
    recoveryLifetimeStatus = valid;
    const bool published = writeRecoveryLifetime(valid, false);
    const auto completion = recoveryLifetimeGate.finishValidPublication(published);
    if (completion == RaphaelRecoveryV3::ValidCompletion::Active) {
        if (!published || !recoveryLifetimeGate.clientsAllowed()) return false;
        CRLOG("XH3 LIFETIME state=VALID nonce=%016llx_%016llx checksum=%#llx",
              recoveryNonceLo, recoveryNonceHi, valid.checksum);
        return true;
    }
    if (completion == RaphaelRecoveryV3::ValidCompletion::AbortOwner) {
        const auto reason = static_cast<RaphaelRecoveryV3::LifetimeReason>(
            recoveryLifetimeGate.abortReason());
        const auto aborted = RaphaelRecoveryV3::makeAbortLifetime(valid, reason);
        const bool abortPublished = writeRecoveryLifetime(aborted, true);
        if (abortPublished) recoveryLifetimeStatus = aborted;
        recoveryLifetimeGate.finishAbortPublication(abortPublished);
        CRLOG("XH3 LIFETIME state=ABORT reason=%u nonce=%016llx_%016llx "
              "durable=%u", static_cast<uint32_t>(reason), recoveryNonceLo,
              recoveryNonceHi, abortPublished);
    }
    return false;
}

static void wrapVmmSetVSReady(void *self, uint32_t ready) {
    auto native = [&] { FunctionCast(wrapVmmSetVSReady, orgVmmSetVSReady)(self, ready); };
    if (self == nullptr) { native(); return; }
    vmmObject = self;
    auto f = reinterpret_cast<uint8_t *>(self);
    auto q = [f](size_t o) { return *reinterpret_cast<void **>(f + o); };
    bool owned = true;
    if (ready != 0 && recoveryLeaseConfigured) {
        const auto memory = reinterpret_cast<uint8_t *>(hwMemObject);
        const uint64_t visible = discoveredBarVisible;
        const uint64_t logical = discoveredVramTotal;
        void *hardware = q(0x10);
        using AppendReserved = uint64_t (*)(void *, uint32_t, uint64_t, uint32_t);
        AppendReserved appendReserved = nullptr;
        const bool acquisitionExpected = recoveryLeaseState.canAcquire();
        uint64_t predictedOffset = 0, predictedNext = 0;
        bool predictedValid = false;
        owned = RaphaelRecoveryV2::establishBeforeVmm(
            recoveryLeaseState, recoveryNonceLo, recoveryNonceHi, visible,
            [&]() {
                if (hardware == nullptr || memory == nullptr ||
                    *reinterpret_cast<void **>(memory + 0x10) != hardware ||
                    !isRaphaelHardware(hardware))
                    return false;
                auto vt = *reinterpret_cast<uint64_t **>(hardware);
                if (vt == nullptr || vt[0x180 / 8] != x6Base + kOffHwAppendReserved)
                    return false;
                appendReserved = reinterpret_cast<AppendReserved>(vt[0x180 / 8]);
                return true;
            },
            [&]() -> uint64_t {
                return appendReserved(hardware, 0, RaphaelRecoveryV2::LeaseSize, 0x1000);
            },
            [&](const RaphaelRecoveryV2::OwnershipDescriptor &descriptor) {
                if (memory == nullptr || hardware == nullptr) return false;
                auto hardwareBytes = reinterpret_cast<uint8_t *>(hardware);
                const uint64_t primary = *reinterpret_cast<uint64_t *>(hardwareBytes + 0x340);
                const uint64_t secondary = *reinterpret_cast<uint64_t *>(hardwareBytes + 0x350);
                predictedValid = RaphaelRecoveryV2::predictNativeVmmRange(
                    primary, secondary, 0x04400000, 0x1000, visible, logical,
                    nativeProviderTotal, nativeProviderVisible,
                    predictedOffset, predictedNext);
                return recoveryLeaseDisjointFromLiveGart(descriptor) &&
                    predictedValid &&
                    RaphaelRecoveryV2::logicalDisjointFromRange(
                        descriptor, predictedOffset, 0x04400000, logical, visible);
            },
            [&](const RaphaelRecoveryV2::OwnershipDescriptor &descriptor) {
                auto fb = fbAperture();
                if (fb == nullptr) return false;
                auto write = [fb](uint64_t base, uint32_t word, uint32_t value) {
                    fb[base / 4 + word] = value;
                };
                auto read = [fb](uint64_t base, uint32_t word) {
                    return fb[base / 4 + word];
                };
                auto fence = [] { OSSynchronizeIO(); };
                const uint64_t statusBase = descriptor.leaseOffset +
                                            RaphaelRecoveryV2::PoolStatusOffset;
                if (!RaphaelRecoveryV2::clearRecord<RaphaelRecoveryV2::PoolStatus>(
                        [&](uint32_t i, uint32_t v) { write(statusBase, i, v); },
                        [&](uint32_t i) { return read(statusBase, i); }, fence))
                    return false;
                const uint64_t lifetimeBase = descriptor.leaseOffset +
                                              RaphaelRecoveryV3::LifetimeOffset;
                if (!RaphaelRecoveryV2::clearRecord<
                        RaphaelRecoveryV3::LifetimeStatus>(
                        [&](uint32_t i, uint32_t v) { write(lifetimeBase, i, v); },
                        [&](uint32_t i) { return read(lifetimeBase, i); }, fence))
                    return false;
                if (!RaphaelRecoveryV2::publishRecord(
                        descriptor,
                        [&](uint32_t i, uint32_t v) {
                            write(descriptor.leaseOffset +
                                  RaphaelRecoveryV2::OwnershipOffset, i, v);
                        },
                        [&](uint32_t i) {
                            return read(descriptor.leaseOffset +
                                        RaphaelRecoveryV2::OwnershipOffset, i);
                        }, fence))
                    return false;
                const auto nonce = RaphaelRecoveryV2::logNonce(descriptor);
                CRLOG("XH2 OWNED nonce=%016llx_%016llx gen=1 lease=%#llx-%#llx "
                      "scratch=%#llx-%#llx checksum=%#llx", nonce.first,
                      nonce.second, descriptor.leaseOffset, descriptor.leaseEnd,
                      descriptor.scratchOffset, descriptor.scratchEnd,
                      descriptor.checksum);
                return true;
            }, native);
        if (!owned && !acquisitionExpected) {
            abortRecoveryLifetime(
                RaphaelRecoveryV3::LifetimeReasonDuplicateReady);
            CRLOG("XH2 ABORT reason=duplicate-ready nonce=%016llx_%016llx",
                  recoveryNonceLo, recoveryNonceHi);
        }
        if (owned) {
            const uint64_t memoryBase = *reinterpret_cast<uint64_t *>(memory + 0x50);
            const uint64_t vmmBase = *reinterpret_cast<uint64_t *>(f + 0x50);
            const bool baseOk = vmmBase >= memoryBase;
            const uint64_t vmmOffset = baseOk ? vmmBase - memoryBase : UINT64_MAX;
            const bool vmmOwned = baseOk && RaphaelRecoveryV2::logicalDisjointFromRange(
                recoveryLeaseState.ownership(), vmmOffset, 0x04400000, logical, visible) &&
                (!predictedValid || vmmOffset == predictedOffset);
            if (!vmmOwned) {
                abortRecoveryLifetime(RaphaelRecoveryV3::LifetimeReasonVmmRange);
                owned = false;
                CRLOG("XH2 ABORT reason=vmm-range nonce=%016llx_%016llx",
                      recoveryNonceLo, recoveryNonceHi);
                RLOG("XH: v2 native VMM reservation rejected base=%#llx offset=%#llx "
                     "bytes=%#x logical=%#llx visible=%#llx predicted=%#llx", vmmBase,
                     vmmOffset, 0x04400000, logical, visible, predictedOffset);
            }
            if (vmmOwned)
                RLOG("XH: native VMM post primary=%#llx/%#llx secondary=%#llx/%#llx "
                     "actual=%#llx-%#llx match=%u",
                     *reinterpret_cast<uint64_t *>(reinterpret_cast<uint8_t *>(hardware) + 0x340),
                     *reinterpret_cast<uint64_t *>(reinterpret_cast<uint8_t *>(hardware) + 0x348),
                     *reinterpret_cast<uint64_t *>(reinterpret_cast<uint8_t *>(hardware) + 0x350),
                     *reinterpret_cast<uint64_t *>(reinterpret_cast<uint8_t *>(hardware) + 0x358), vmmOffset,
                     vmmOffset + 0x04400000, !predictedValid || vmmOffset == predictedOffset);
        }
        if (owned) {
            __atomic_store_n(&recoveryLeaseHardwareOwner, hardware, __ATOMIC_RELEASE);
            __atomic_store_n(&recoveryLeaseMemoryOwner, memory, __ATOMIC_RELEASE);
        }
    } else {
        native();
    }
    const uint64_t vmmBase = *reinterpret_cast<uint64_t *>(f + 0x50);
    RLOG("XV: setVirtualSpaceReady(%u) | m_0x20=%p m_0x28=%p vmmBase(+50)=%#llx "
         "lease-owned=%u [caller x6+%#llx]",
         ready, q(0x20), q(0x28), vmmBase, owned,
         reinterpret_cast<uint64_t>(__builtin_return_address(0)) - x6Base);
    if (owned && ready != 0 && vmmProbeMode >= 3 && q(0x28) == nullptr &&
        orgVmmSetAlloc != 0) {
        RLOG("XV: driving setMemoryAllocationsEnabled(true) from here, because nothing else "
             "does and m_0x28 is the DMA paging channel endVMPTUpdate dereferences");
        reinterpret_cast<void (*)(void *, uint32_t)>(orgVmmSetAlloc)(self, 1);
        CRLOG("XV2 VMM phase=early enable=1 base=%#llx arena=%p pool0=%p pool1=%p",
              *reinterpret_cast<uint64_t *>(f + 0x50), q(0x58), q(0x78), q(0x80));
        RLOG("XV: after forced enable: m_0x20=%p m_0x28=%p m_0x30=%p -> %s",
             q(0x20), q(0x28), *reinterpret_cast<void **>(f + 0x30),
             q(0x28) != nullptr ? "DMA PAGING CHANNEL PRESENT"
                                : "still NULL, endVMPTUpdate will panic");
    }
}

static void wrapVmmSetAlloc(void *self, uint32_t enable) {
    if (self == nullptr) {
        FunctionCast(wrapVmmSetAlloc, orgVmmSetAlloc)(self, enable);
        return;
    }
    auto f = reinterpret_cast<uint8_t *>(self);
    auto slot = [f](size_t o) -> void *& { return *reinterpret_cast<void **>(f + o); };
    vmmObject = self;
    CRLOG("XV: setMemoryAllocationsEnabled(%u) entry: m_0x20=%p m_0x28=%p m_0x30=%p "
          "nest(0x3c)=%u  [caller x6+%#llx]", enable, slot(0x20), slot(0x28),
          slot(0x30), *reinterpret_cast<uint32_t *>(f + 0x3c),
          reinterpret_cast<uint64_t>(__builtin_return_address(0)) - x6Base);
    if (enable != 0 && vmmProbeMode >= 2 && slot(0x20) != nullptr && slot(0x28) == nullptr) {
        RLOG("XV: clearing m_0x20 so the guard at 0x5793d falls through and the channel is "
             "built; setMemoryAllocationsEnabled reassigns m_0x20 itself at 0x5795c");
        slot(0x20) = nullptr;
    }
    FunctionCast(wrapVmmSetAlloc, orgVmmSetAlloc)(self, enable);
    if (enable != 0) {
        CRLOG("XV2 VMM phase=native enable=%u base=%#llx arena=%p pool0=%p pool1=%p",
              enable, *reinterpret_cast<uint64_t *>(f + 0x50), slot(0x58),
              slot(0x78), slot(0x80));
    }
    RLOG("XV: setMemoryAllocationsEnabled(%u) exit:  m_0x20=%p m_0x28=%p m_0x30=%p -> %s",
         enable, slot(0x20), slot(0x28), slot(0x30),
         slot(0x28) != nullptr ? "DMA PAGING CHANNEL PRESENT"
                               : "still NULL, endVMPTUpdate will panic");
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

// rgpunobin=1: PA_SC_ENHANCE_1.DISABLE_SC_BINNING (bit 3) turns deferred pixel binning
// off globally, whatever PA_SC_BINNER_CNTL_0 a command buffer programs. The stuck draw
// enables DPBB (PA_SC_BINNER_CNTL_0=0x19ffe00c) after a depth clear with binning off.
static uint32_t noBinMode = 0;
static constexpr uint32_t kGcPaScEnhance1 = kGcSeg0 + 0x109d;

static void applyNoBinning(const char *when) {
    if (noBinMode != 1 || asicInfo == nullptr) return;
    const uint32_t before = fbRead(asicInfo, kGcPaScEnhance1);
    if (before == 0xdeadbeef) return;
    fbWrite(asicInfo, kGcPaScEnhance1, before | 0x8u);
    RLOG("XD: rgpunobin at %s: PA_SC_ENHANCE_1 %#x -> %#x (readback %#x)", when, before,
         before | 0x8u, fbRead(asicInfo, kGcPaScEnhance1));
}

static void startRlc() {
    if (asicInfo == nullptr) { RLOG("XK: no register accessor yet"); return; }
    dumpGfxState("before RLC start");
    applyGoldenRegisters("before RLC start");
    applyNoBinning("before RLC start");
    applyVgprSwizzle("before RLC start");
    applyGbAddrConfigRead("before RLC start");
    applySdmaAddrConfig("before RLC start", false);
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
static bool isRaphaelPciMarker(IOService *pci) {
    if (!pci) return false;
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
    return matches;
}

// Called at native VM initialization, after IP discovery but before VMM init.
// Do not publish the later framebuffer/target barrier from this early check.
static bool hasUniqueRaphaelPciMarker() {
    auto matching = IOService::serviceMatching("IOPCIDevice");
    if (!matching) return false;
    auto iterator = IOService::getMatchingServices(matching);
    matching->release();
    if (!iterator) return false;
    unsigned matches = 0;
    while (auto object = iterator->getNextObject())
        if (isRaphaelPciMarker(OSDynamicCast(IOService, object))) ++matches;
    iterator->release();
    return matches == 1;
}

static bool isRaphaelHardware(void *self) {
    if (!raphaelGcSeen || !self) return false;
    auto rawPci = *reinterpret_cast<void **>(static_cast<uint8_t *>(self) + 0x10);
    const bool matches = isRaphaelPciMarker(OSDynamicCast(IOService,
                                           reinterpret_cast<OSObject *>(rawPci)));
    if (matches) {
        // The framebuffer snapshot is published earlier in startup. Make the
        // exact marker match the release barrier for later VM callbacks.
        __atomic_store_n(&raphaelTargetConfirmed, true, __ATOMIC_RELEASE);
    }
    return matches;
}

static uint32_t wrapHwEngInit(void *self) {
    if (sdmaTopologyEnabled && sdmaTopologyRoutesReady && isRaphaelHardware(self)) {
        // AppleGVA 24G830's HEVC capability enumeration only descends from
        // GFX0/IGPU/IOPP/display nodes. QEMU exposes our marked PCI device as
        // S30, so the accelerator's valid properties are otherwise invisible
        // to that search. Change only this known name in the IOService plane;
        // retain ACPI identity, registry ID, parents, children and properties.
        auto pci = OSDynamicCast(IOService, reinterpret_cast<OSObject *>(
            *reinterpret_cast<void **>(static_cast<uint8_t *>(self) + 0x10)));
        const char *name = pci ? pci->getName(gIOServicePlane) : nullptr;
        if (name && !strcmp(name, "S30")) {
            pci->setName("GFX0", gIOServicePlane);
            const bool renamed = !strcmp(pci->getName(gIOServicePlane), "GFX0");
            RLOG("HEVCNAME: marked Raphael IOService S30 -> GFX0 result=%u actual=%s",
                 renamed, pci->getName(gIOServicePlane));
        }
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
    // Apple's SDMA bring-up programs SDMA0_GB_ADDR_CONFIG{,_READ} with Navi23's 0x444;
    // make every SDMA submission decode textures with Raphael's layout (rgpusdmacfg=2).
    applySdmaAddrConfig("SDMA commit", true);
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
    (void)size0;
    (void)size1;
    uint64_t visible = discoveredBarVisible;
    if (!discoveredCapacityValid || visible == 0) return false;
    aperture = {static_cast<uint64_t>(base) << 24,
                (static_cast<uint64_t>(top) << 24) | 0xffffffULL,
                static_cast<uint64_t>(offset) << 24, visible};
    return RaphaelVm::validAperture(aperture);
}

static void reportVmid2Walk(uint32_t sequence, const RaphaelVm::PreparedRequest &program,
                            const RaphaelSdma::SubmitInfoObservation &submit,
                            uint64_t contextStart) {
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
            // Candidate 181's frozen root has its only entry at index zero for
            // VAs beginning at the live nonzero context start. Treating the VA
            // as context-relative is a diagnostic reconstruction of that
            // observed layout; hardware success remains the deciding evidence.
            contextStart, va, aperture, reader);
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

static void publishClientFaultWalks() {
    if (!vmFaultDiagEnabled || asicInfo == nullptr) return;
    static size_t cursor = 0;
    RaphaelVm::FaultObservation fault {};
    while (cursor < 2 && clientFaults.read(cursor, fault)) {
        ++cursor;
        const auto decoded = RaphaelVm::decodeFaultStatus(fault.status);
        auto rd = [](uint32_t relative) { return fbRead(asicInfo, kGcSeg0 + relative); };
        const auto beforeSnapshot = RaphaelVm::captureContextSnapshot(decoded.vmid, rd);
        if (!beforeSnapshot.valid) continue;
        const auto &before = beforeSnapshot.words;
        const uint64_t root = RaphaelVm::join(before[1], before[2]);
        const uint64_t start = RaphaelVm::join(before[3], before[4]) << 12;
        const uint64_t end = (RaphaelVm::join(before[5], before[6]) << 12) | 0xfffULL;
        RaphaelVm::FramebufferAperture aperture {};
        auto fb = fbAperture();
        const bool apertureValid = fb != nullptr && vmid2Aperture(aperture);
        auto reader = [&](uint64_t physical, uint64_t &value) {
            if (!apertureValid || physical < aperture.physicalBase ||
                physical - aperture.physicalBase > aperture.visibleBytes - 8)
                return false;
            const uint64_t dword = (physical - aperture.physicalBase) / 4;
            value = RaphaelVm::join(fb[dword], fb[dword + 1]);
            return true;
        };
        const auto relative = RaphaelVm::walkPageTables(
            root, before[0], start, fault.address, aperture, reader);
        const auto absolute = RaphaelVm::walkPageTables(
            root, before[0], fault.address, aperture, reader);
        const auto afterSnapshot = RaphaelVm::captureContextSnapshot(decoded.vmid, rd);
        const bool contextStable = RaphaelVm::contextSnapshotStable(
            beforeSnapshot, afterSnapshot);
        const bool addressInContext = fault.address >= start && fault.address <= end;
        CRLOG("VM: fault-walk vmid=%u status=%#x fault-va=%#llx cid=%u walker=%u "
              "permission=%#x mapping=%u rw=%u atomic=%u ctl=%#x root=%#llx "
              "start=%#llx end=%#llx aperture=%u context-stable=%u "
              "address-in-context=%u timing=worker-after-latch tables-non-atomic=1",
              decoded.vmid, fault.status, fault.address, decoded.cid,
              decoded.walkerError, decoded.permissionFaults, decoded.mappingError,
              decoded.write, decoded.atomic, before[0], root, start, end,
              apertureValid, contextStable, addressInContext);
        const RaphaelVm::PageTableWalk *walks[] {&relative, &absolute};
        const char *views[] {"relative", "absolute"};
        for (size_t view = 0; view < 2; ++view) {
            const auto &walk = *walks[view];
            CRLOG("VM: fault-walk-view status=%#x fault-va=%#llx view=%s valid=%u "
                  "complete=%u count=%u",
                  fault.status, fault.address, views[view], walk.valid,
                  walk.complete, walk.count);
            for (uint32_t n = 0; n < walk.count; ++n) {
                const auto &e = walk.entries[n];
                CRLOG("VM: fault-walk-entry status=%#x fault-va=%#llx view=%s n=%u "
                      "level=%u index=%llu "
                      "table=%#llx raw=%#llx entry-addr=%#llx V=%u S=%u X=%u R=%u W=%u "
                      "P=%u TF=%u mc2pa-eligible=%u child-mc2pa=%u",
                      fault.status, fault.address, views[view], n, e.level, e.index,
                      e.tablePhysical, e.raw,
                      e.address, e.valid, e.system, e.executable, e.readable,
                      e.writeable, e.pdeAsPte, e.translateFurther,
                      !e.system && !e.pdeAsPte, e.childConverted);
            }
        }
    }
    static RaphaelVm::FaultRejectionSchedule rejectionSchedule {};
    const uint64_t rejected = clientFaults.nonClientVmid() + clientFaults.duplicates() +
        clientFaults.contention() + clientFaults.full();
    if (rejectionSchedule.shouldPublish(rejected)) {
        CRLOG("VM: fault-capture rejected non-client-vmid=%llu duplicate=%llu "
              "contention=%llu capacity=%llu",
              clientFaults.nonClientVmid(), clientFaults.duplicates(),
              clientFaults.contention(), clientFaults.full());
    }
}

// rgpuhangdump=1 memory half. GART (VMID 0) and client pages are resolved the way
// walkGart and publishClientFaultWalks do; SYSTEM pages are guest RAM and are mapped
// read-only as a physical IOMemoryDescriptor range, VRAM pages are read through
// the BAR0 aperture. Runs only on hangDumpThread.
struct HangPageSource {
    bool ok;
    bool system;
    uint64_t address;
    uint64_t fbOffset;
    uint64_t raw;
    const char *view;
};

static HangPageSource hangGartPage(uint64_t va) {
    HangPageSource result {false, false, 0, 0, 0, "gart"};
    if (asicInfo == nullptr) return result;
    const uint64_t root = (static_cast<uint64_t>(fbRead(asicInfo, kGcVmCtx0PtbHi)) << 32) |
                           fbRead(asicInfo, kGcVmCtx0PtbLo);
    RaphaelGart::Aperture aperture {};
    RaphaelGart::Range range {};
    uint64_t off = 0, idx = 0;
    auto fb = fbAperture();
    if (fb == nullptr || !gartApertureInfo(aperture) || !gartRange(range) ||
        !RaphaelGart::pteOffset(aperture, range, fbRead(asicInfo, kGcVmCtx0Cntl), root, va,
                                off, idx) || !fitsDiscoveredBar(off, 8))
        return result;
    result.raw = (static_cast<uint64_t>(fb[off / 4 + 1]) << 32) | fb[off / 4];
    if ((result.raw & 1) == 0) return result;
    result.address = result.raw & 0x0000fffffffff000ULL;
    result.system = (result.raw & 2) != 0;
    result.ok = result.system || RaphaelHang::framebufferOffset(
        result.address, aperture.mcBase, aperture.physicalBase, aperture.visibleBytes,
        result.fbOffset);
    return result;
}

static HangPageSource hangClientPage(uint32_t vmid, uint64_t va, bool quiet = false) {
    HangPageSource result {false, false, 0, 0, 0, "client"};
    if (asicInfo == nullptr) return result;
    auto rd = [](uint32_t relative) { return fbRead(asicInfo, kGcSeg0 + relative); };
    const auto context = RaphaelVm::captureContextSnapshot(vmid, rd);
    RaphaelVm::FramebufferAperture aperture {};
    auto fb = fbAperture();
    if (vmid == 0 || !context.valid || fb == nullptr || !vmid2Aperture(aperture)) return result;
    const uint32_t control = context.words[0];
    const uint64_t root = RaphaelVm::join(context.words[1], context.words[2]);
    const uint64_t start = RaphaelVm::join(context.words[3], context.words[4]) << 12;
    auto reader = [&](uint64_t physical, uint64_t &value) {
        if (physical < aperture.physicalBase ||
            physical - aperture.physicalBase > aperture.visibleBytes - 8)
            return false;
        const uint64_t dword = (physical - aperture.physicalBase) / 4;
        value = RaphaelVm::join(fb[dword], fb[dword + 1]);
        return true;
    };
    const uint64_t starts[2] {start, 0};
    const char *const views[2] {"client-relative", "client-absolute"};
    for (unsigned v = 0; v < 2; ++v) {
        if (v == 1 && start == 0) break;
        if (va < starts[v]) continue;
        const auto walk = RaphaelVm::walkPageTables(root, control, starts[v], va, aperture,
                                                    reader);
        if (walk.count != 0) result.raw = walk.entries[walk.count - 1].raw;
        if (!walk.valid || !walk.complete || walk.count == 0) continue;
        const auto &leaf = walk.entries[walk.count - 1];
        uint64_t page = 0;
        if (!RaphaelHang::leafPage(leaf.address, control, leaf.level, va - starts[v], page))
            continue;
        result.address = page;
        result.system = leaf.system;
        result.view = views[v];
        result.ok = result.system || RaphaelHang::framebufferOffset(
            page, aperture.mcBase, aperture.physicalBase, aperture.visibleBytes,
            result.fbOffset);
        if (result.ok) return result;
    }
    if (!quiet)
        RLOG("XD: vmid %u va %#llx unresolved: ctl=%#x root=%#llx start=%#llx last-entry=%#llx",
             vmid, va, control, root, start, result.raw);
    return result;
}

static bool readHangPage(const HangPageSource &source, uint32_t *words) {
    if (!source.ok) return false;
    if (!source.system) {
        auto fb = fbAperture();
        if (fb == nullptr || !fitsDiscoveredBar(source.fbOffset, 0x1000)) return false;
        for (unsigned i = 0; i < 1024; ++i) words[i] = fb[source.fbOffset / 4 + i];
        return true;
    }
    // withPhysicalAddress is withAddressRange(address, length, direction, TASK_NULL) in
    // xnu. This build does not define KERNEL, so the SDK declares IOPhysicalAddress and
    // IOByteCount as 32-bit and the direct call would bind a symbol the kernel does not
    // export (and truncate guest addresses above 4 GiB). mach_vm_address_t is 64-bit.
    IOMemoryDescriptor *descriptor = IOMemoryDescriptor::withAddressRange(
        source.address, 0x1000, kIODirectionIn, nullptr);
    if (descriptor == nullptr) return false;
    IOMemoryMap *map = descriptor->map(kIOMapReadOnly);
    bool ok = false;
    if (map != nullptr && map->getVirtualAddress() != 0) {
        auto bytes = reinterpret_cast<const uint32_t *>(map->getVirtualAddress());
        for (unsigned i = 0; i < 1024; ++i) words[i] = bytes[i];
        ok = true;
    }
    if (map != nullptr) map->release();
    descriptor->release();
    return ok;
}

// Read `count` dwords at GPU VA base + 4 * (first + i) (ring positions wrap) in the
// given address space, log them eight per line, and keep a copy for packet scanning.
static constexpr uint32_t kHangMaxDwords = 128;
static uint32_t hangPageWords[1024];
static void dumpHangDwords(const char *label, uint32_t vmid, uint64_t base, uint32_t first,
                           uint32_t count, uint32_t wrapDwords, uint32_t *copy, bool *valid) {
    if (count > kHangMaxDwords) count = kHangMaxDwords;
    uint64_t cachedPage = UINT64_MAX;
    bool cachedOk = false;
    char line[160];
    int used = 0;
    uint32_t lineFirst = first;
    for (uint32_t i = 0; i < count; ++i) {
        const uint32_t position = wrapDwords != 0
            ? RaphaelHang::ringIndex(first, i, wrapDwords) : first + i;
        const uint64_t va = base + static_cast<uint64_t>(position) * 4;
        const uint64_t page = va & ~0xfffULL;
        if (page != cachedPage) {
            cachedPage = page;
            const auto source = vmid == 0 ? hangGartPage(page) : hangClientPage(vmid, page);
            cachedOk = readHangPage(source, hangPageWords);
            RLOG("XD: %s page va=%#llx via %s -> %s %#llx (entry %#llx) read=%u", label, page,
                 source.view, source.system ? "system" : "vram",
                 source.system ? source.address : source.fbOffset, source.raw, cachedOk);
        }
        const bool ok = cachedOk;
        const uint32_t word = ok ? hangPageWords[(va & 0xfff) / 4] : 0;
        if (copy != nullptr) copy[i] = word;
        if (valid != nullptr) valid[i] = ok;
        if (i % 8 == 0) { lineFirst = position; used = 0; }
        used += snprintf(line + used, sizeof(line) - used, ok ? " %08x" : " --------", word);
        if (i % 8 == 7 || i + 1 == count)
            RLOG("XD: %s vmid=%u [%#x]%s", label, vmid, lineFirst, line);
    }
}

// Apple may leave the VMID field of the IB control word clear. Then use the
// address space that maps the buffer's first page: GART first, then each client.
static uint32_t hangIbVmid(const char *label, uint32_t vmid, uint64_t address) {
    if (vmid != 0) return vmid;
    const uint64_t page = address & ~0xfffULL;
    if (hangGartPage(page).ok) return 0;
    uint32_t chosen = 0;
    for (uint32_t candidate = 1; candidate < 16; ++candidate) {
        const auto source = hangClientPage(candidate, page, true);
        if (!source.ok) continue;
        RLOG("XD: %s va=%#llx with control VMID 0 resolves in vmid %u via %s -> %#llx", label,
             address, candidate, source.view, source.system ? source.address : source.fbOffset);
        if (chosen == 0) chosen = candidate;
    }
    return chosen;
}

static void dumpHangIb(const char *label, uint32_t packetVmid, uint64_t address,
                       uint32_t length, uint32_t offsetRegister, uint32_t bufszRegister) {
    const uint32_t vmid = hangIbVmid(label, packetVmid, address);
    const auto cursor = RaphaelHang::ibCursor(offsetRegister, bufszRegister, length);
    RLOG("XD: %s vmid=%u va=%#llx length=%#x OFFSET=%#x BUFSZ=%#x cursor offset=%u:%#x "
         "remaining=%u:%#x", label, vmid, address, length, offsetRegister, bufszRegister,
         cursor.offsetValid, cursor.offset, cursor.remainingValid, cursor.remaining);
    uint32_t firstWindowStart = UINT32_MAX;
    for (unsigned reading = 0; reading < 2; ++reading) {
        const bool usable = reading == 0 ? cursor.offsetValid : cursor.remainingValid;
        const uint32_t at = reading == 0 ? cursor.offset : cursor.remaining;
        if (!usable) continue;
        const auto window = RaphaelHang::windowAround(at, 48, 16, length);
        if (!window.valid || window.first == firstWindowStart) continue;
        if (firstWindowStart != UINT32_MAX && window.first + 48 > firstWindowStart &&
            firstWindowStart + 48 > window.first) continue;
        firstWindowStart = window.first;
        dumpHangDwords(label, vmid, address, window.first, window.count, 0, nullptr, nullptr);
    }
}

static void dumpGfxHangMemory(uint32_t index, const GfxHangSnapshot &snap) {
    if (asicInfo == nullptr) return;
    const auto ring = RaphaelHang::ringGeometry(snap.baseLo, snap.baseHi, snap.cntl);
    if (!ring.valid) {
        RLOG("XD: gfx hang dump %u memory: ring geometry invalid", index);
        return;
    }
    static constexpr uint32_t kBefore = 64, kAfter = 32;
    uint32_t words[kBefore + kAfter] {};
    bool valid[kBefore + kAfter] {};
    const uint32_t first = RaphaelHang::ringIndex(snap.rptr, -static_cast<int64_t>(kBefore),
                                                  ring.dwords);
    RLOG("XD: gfx hang dump %u memory: ring va=%#llx RPTR=%#x WPTR=%#x window [%#x..RPTR+%u)",
         index, ring.va, snap.rptr, snap.wptr, first, kAfter);
    dumpHangDwords("ring", 0, ring.va, first, kBefore + kAfter, ring.dwords, words, valid);
    RaphaelHang::IbPacket gfxIb {}, ceIb {}, lastGfxIb {};
    for (uint32_t i = 0; i + 3 < kBefore + kAfter; ++i) {
        if (!valid[i] || !valid[i + 1] || !valid[i + 2] || !valid[i + 3]) continue;
        const auto packet = RaphaelHang::parseIndirectBuffer(words, kBefore + kAfter, i);
        if (!packet.valid) continue;
        const bool gfx = packet.opcode == RaphaelHang::kPacket3IndirectBuffer;
        const auto &regs = snap.ib[gfx ? kHangIb1 : kHangCeIb1];
        const bool covers = RaphaelHang::packetCoversBase(packet, regs[kHangBaseLo],
                                                          regs[kHangBaseHi]);
        RLOG("XD: ring[%#x] %s va=%#llx length=%#x vmid=%u control=%#x %s RPTR covers-%s=%u",
             RaphaelHang::ringIndex(first, i, ring.dwords),
             gfx ? "INDIRECT_BUFFER" : "INDIRECT_BUFFER_CONST", packet.address,
             packet.lengthDwords, packet.vmid, packet.control, i < kBefore ? "before" : "at/after",
             gfx ? "IB1" : "CE_IB1", covers);
        if (gfx && i < kBefore) lastGfxIb = packet;
        if (covers && gfx) gfxIb = packet;
        if (covers && !gfx) ceIb = packet;
    }
    const auto &ib1 = snap.ib[kHangIb1];
    if (!gfxIb.valid && lastGfxIb.valid && (ib1[kHangBaseLo] | ib1[kHangBaseHi]) != 0) {
        RLOG("XD: no ring IB covers CP_IB1_BASE; using the last IB before RPTR");
        gfxIb = lastGfxIb;
    }
    if (gfxIb.valid) {
        const uint64_t ib1Base = RaphaelVm::join(ib1[kHangBaseLo], ib1[kHangBaseHi]) & ~3ULL;
        dumpHangIb("IB1", gfxIb.vmid, gfxIb.address, gfxIb.lengthDwords, ib1[kHangOffset],
                   ib1[kHangBufsz]);
        if (ib1Base != gfxIb.address && ib1Base > gfxIb.address &&
            ib1Base - gfxIb.address < static_cast<uint64_t>(gfxIb.lengthDwords) * 4) {
            const uint32_t at = static_cast<uint32_t>((ib1Base - gfxIb.address) / 4);
            const auto window = RaphaelHang::windowAround(at, 48, 16, gfxIb.lengthDwords);
            if (window.valid)
                dumpHangDwords("IB1@BASE", hangIbVmid("IB1@BASE", gfxIb.vmid, gfxIb.address),
                               gfxIb.address, window.first, window.count, 0, nullptr, nullptr);
        }
        const auto &ib2 = snap.ib[kHangIb2];
        const uint64_t ib2Base = RaphaelVm::join(ib2[kHangBaseLo], ib2[kHangBaseHi]) & ~3ULL;
        if (ib2Base != 0)
            dumpHangIb("IB2", gfxIb.vmid, ib2Base, 0, ib2[kHangOffset], ib2[kHangBufsz]);
    } else {
        RLOG("XD: no INDIRECT_BUFFER packet in the ring window; IB contents not read");
    }
    if (ceIb.valid) {
        const auto &ce = snap.ib[kHangCeIb1];
        dumpHangIb("CE_IB1", ceIb.vmid, ceIb.address, ceIb.lengthDwords, ce[kHangOffset],
                   ce[kHangBufsz]);
    }
    RLOG("XD: gfx hang dump %u memory complete", index);
}

// Candidate 213 printed 419 lines in one burst while Apple's report and HWLibs TTL
// asserts were logging: most lines were dropped and some interleaved. Wait for the
// report to finish, pace the output below the 115200-baud console rate, tag every
// line with a checksum, and print the buffer twice.
static void printHangWaits(uint32_t index, const HangCommandBuffer &cb) {
    for (uint32_t n = 0; n < cb.waits; ++n) {
        const auto &sample = cb.wait[n];
        const auto &w = sample.wait;
        RLOG("XB: cb%u WAIT_REG_MEM[0x%04x] op=%#x fn=%u mem=%u oper=%u eng=%u addr=%#llx "
             "second=%#x ref=%#x mask=%#x interval=%#x", index, sample.at, w.opcode, w.function,
             w.memSpace, w.operation, w.engine, w.address, w.second, w.reference, w.mask,
             w.interval);
        IOSleep(20);
        if (sample.sampled) {
            RLOG("XB: cb%u WAIT_REG_MEM[0x%04x] register %#llx at capture = %#x %#x %#x "
                 "satisfied=%u", index, sample.at, w.address, sample.values[0], sample.values[1],
                 sample.values[2], RaphaelHang::waitSatisfied(w.function, sample.values[2],
                                                               w.reference, w.mask));
        } else if (w.memSpace == 1) {
            const auto source = hangGartPage(w.address & ~0xfffULL);
            const bool read = readHangPage(source, hangPageWords);
            const uint32_t value = read ? hangPageWords[(w.address & 0xfff) / 4] : 0;
            RLOG("XB: cb%u WAIT_REG_MEM[0x%04x] memory %#llx via gart ok=%u read=%u value=%#x "
                 "satisfied=%u (read after capture)", index, sample.at, w.address, source.ok,
                 read, value, read && RaphaelHang::waitSatisfied(w.function, value, w.reference,
                                                                 w.mask));
        }
        IOSleep(20);
    }
}

static void printHangCommandBuffer(uint32_t index, const HangCommandBuffer &cb) {
    // Candidate 213's guest shut down about 30 s after the report: 3 s settle, 20 ms per
    // line (about 5 KB/s against the 11.5 KB/s console), 2 s between passes.
    IOSleep(3000);
    for (uint32_t pass = 1; pass <= 2; ++pass) {
        RLOG("XB: cb%u pass %u va=%#llx size=%#x copied=%#x waits=%u", index, pass, cb.va,
             cb.size, cb.copied, cb.waits);
        printHangWaits(index, cb);
        char line[160];
        for (uint32_t first = 0; first < cb.copied; first += 8) {
            const uint32_t count = cb.copied - first < 8 ? cb.copied - first : 8;
            int used = 0;
            for (uint32_t i = first; i < first + count; ++i)
                used += snprintf(line + used, sizeof(line) - used, " %08x", cb.words[i]);
            RLOG("XB: cb%u p%u [0x%04x]%s x=%08x", index, pass, first, line,
                 RaphaelHang::lineChecksum(first, cb.words + first, count));
            IOSleep(20);
        }
        RLOG("XB: cb%u pass %u complete", index, pass);
        if (pass == 1) IOSleep(2000);
    }
}

// Candidate 217: with binning disabled the desktop no longer stalls, so record positive
// evidence as well: every 5 s, sample the gfx ring pointers and CP/GRBM state. A ring
// whose WPTR keeps advancing and whose RPTR catches up is WindowServer/WallpaperSequoia
// work completing on this device.
static void sampleGfxProgress(uint32_t sample, uint32_t &lastWptr, uint32_t &advances,
                              uint32_t &drained) {
    if (asicInfo == nullptr) return;
    const uint32_t rptr = fbRead(asicInfo, kGcRb0Rptr), wptr = fbRead(asicInfo, kGcRb0Wptr);
    const bool moved = sample != 0 && wptr != lastWptr;
    advances += moved;
    drained += rptr == wptr;
    RLOG("XR: gfx progress %u: RPTR=%#x WPTR=%#x %s wptr-moved=%u CP_STAT=%#x GRBM_STATUS=%#x "
         "STALLED_STAT2=%#x advances=%u drained=%u", sample, rptr, wptr,
         rptr == wptr ? "drained" : "pending", moved, fbRead(asicInfo, kGcCpStat),
         fbRead(asicInfo, kGcGrbmStatus), fbRead(asicInfo, kGcCpStalled2), advances, drained);
    lastWptr = wptr;
    applySdmaAddrConfig("gfx progress", sample != 0);
    logTilingRegisters("gfx progress");
}

// rgpusdmacfg=2 watchdog: something after accelerator power-up rewrites the SDMA pair to
// Navi23's 0x444. Poll every 50 ms for the first 600 s, then once a second, restore
// Raphael's layout immediately and record when it happened and the power state around it.
static void sdmaWatchdogThread(void *, wait_result_t) {
    uint64_t polls = 0;
    uint32_t corrections = 0;
    while (asicInfo == nullptr) { IOSleep(50); ++polls; }
    for (;;) {
        const uint32_t config = fbRead(asicInfo, kGcGbAddrConfig);
        const uint32_t sdma = fbRead(asicInfo, kSdmaGbAddrConfig);
        const uint32_t sdmaRead = fbRead(asicInfo, kSdmaGbAddrConfigRead);
        if (config != 0 && config != 0xdeadbeef && config != 0xffffffffu &&
            sdma != 0xdeadbeef && sdma != 0xffffffffu &&
            sdmaRead != 0xdeadbeef && sdmaRead != 0xffffffffu &&
            (((sdma ^ config) & kGbAddrConfigFields) != 0 || ((sdmaRead ^ config) & kGbAddrConfigFields) != 0)) {
            ++corrections;
            if (corrections <= 16)
                RLOG("XG: SDMA watchdog #%u at ~%llu ms: SDMA0_GB_ADDR_CONFIG=%#x READ=%#x (want %#x) "
                     "RLC_CNTL=%#x RLC_PG_CNTL=%#x CP_STAT=%#x GRBM_STATUS=%#x SDMA0_STATUS=%#x",
                     corrections, polls * 50, sdma, sdmaRead, config, fbRead(asicInfo, kGcRlcCntl),
                     fbRead(asicInfo, kGcRlcPgCntl), fbRead(asicInfo, kGcCpStat),
                     fbRead(asicInfo, kGcGrbmStatus), fbRead(asicInfo, kSdmaStatus0));
            applySdmaAddrConfig("SDMA watchdog", corrections > 16);
            logTilingRegisters("SDMA watchdog");
        }
        if (polls < 12000) { IOSleep(50); ++polls; }
        else { IOSleep(1000); polls += 20; }
    }
}

static void hangDumpThread(void *, wait_result_t) {
    uint32_t served = 0, cbServed = 0;
    uint32_t samples = 0, lastWptr = 0, advances = 0, drained = 0;
    static constexpr uint32_t kProgressSamples = 40;
    // 120000 polls of 50 ms cover the longest authorized 6000-second run.
    for (unsigned poll = 0; poll < 120000 &&
         (served < kHangDumpLimit || cbServed < kHangCbLimit || samples < kProgressSamples);
         ++poll) {
        const uint32_t published = __atomic_load_n(&hangSnapshotCount, __ATOMIC_ACQUIRE);
        while (served < published && served < kHangDumpLimit) {
            dumpGfxHangMemory(served, hangSnapshots[served]);
            ++served;
        }
        const uint32_t cbs = __atomic_load_n(&hangCbCount, __ATOMIC_ACQUIRE);
        while (cbServed < cbs && cbServed < kHangCbLimit) {
            printHangCommandBuffer(cbServed, hangCbs[cbServed]);
            ++cbServed;
        }
        // Start sampling 30 s after plugin start, once the accelerator is up.
        if (poll >= 600 && poll % 100 == 0 && samples < kProgressSamples)
            sampleGfxProgress(samples++, lastWptr, advances, drained);
        IOSleep(50);
    }
    thread_terminate(current_thread());
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
    if (walk && submit != nullptr)
        reportVmid2Walk(sequence, program, *submit, start);
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

static bool wrapCommitIntoGPUPageTable(void *memoryMap) {
    if (!submissionTraceCaptureActive())
        return FunctionCast(wrapCommitIntoGPUPageTable,
                            orgCommitIntoGPUPageTable)(memoryMap);
    const bool result = FunctionCast(wrapCommitIntoGPUPageTable,
                                     orgCommitIntoGPUPageTable)(memoryMap);
    const uint32_t sequence = __sync_add_and_fetch(&nextSubmissionTraceSequence, 1u);
    const uintptr_t threadToken = reinterpret_cast<uintptr_t>(current_thread());
    submissionCommits.append({reinterpret_cast<uintptr_t>(memoryMap), threadToken,
                              result, sequence});
    return result;
}

static bool wrapBackingAllocPhysical(void *backing) {
    if (!submissionTraceCaptureActive())
        return FunctionCast(wrapBackingAllocPhysical, orgBackingAllocPhysical)(backing);
    return RaphaelBacking::observe(
        true, backing, reinterpret_cast<uintptr_t>(current_thread()),
        __sync_add_and_fetch(&nextSubmissionTraceSequence, 1u),
        submissionBackingAllocations,
        [](void *object) {
            return FunctionCast(wrapBackingAllocPhysical, orgBackingAllocPhysical)(object);
        },
        [](const void *object) { return RaphaelBacking::captureSnapshot(object); });
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
    static size_t backingCursor = 0;
    static uint64_t lastBackingCompleted = 0;
    static unsigned backingDirtyPolls = 0;
    static unsigned backingSummaryRecords = 0;
    static bool backingDirty = false;
    static size_t commitCursor = 0;
    static uint64_t lastCommitCalls = 0;
    static unsigned commitSummaryRecords = 0;
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
    RaphaelSubmit::CommitObservation commitObservation {};
    while (commitCursor < submissionCommits.samples().size() &&
           submissionCommits.samples().read(commitCursor, commitObservation)) {
        ++commitCursor;
        CRLOG("SUB: commit seq=%u map=%#llx thread=%#llx result=%u",
              commitObservation.sequence,
              static_cast<uint64_t>(commitObservation.memoryMap),
              static_cast<uint64_t>(commitObservation.threadToken),
              commitObservation.result);
    }
    const uint64_t commitCalls = submissionCommits.calls();
    if (commitCalls != lastCommitCalls && commitSummaryRecords < 32) {
        CRLOG("SUB: commit-summary calls=%llu failures=%llu dropped=%llu state=live",
              commitCalls, submissionCommits.failures(),
              submissionCommits.samples().dropped());
        lastCommitCalls = commitCalls;
        ++commitSummaryRecords;
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

    RaphaelBacking::Observation backingObservation {};
    while (backingCursor < submissionBackingAllocations.failures().size() &&
           submissionBackingAllocations.failures().read(backingCursor,
                                                         backingObservation)) {
        ++backingCursor;
        const auto &before = backingObservation.before;
        const auto &after = backingObservation.after;
        CRLOG("SUB: backing seq=%u object=%#llx thread=%#llx pool=%u result=%u "
              "pre=%u/%#llx/%#llx/%#llx/%#llx/%#x "
              "post=%u/%#llx/%#llx/%#llx/%#llx/%#x counters=%llu/%llu->%llu/%llu state=live",
              backingObservation.sequence,
              static_cast<uint64_t>(backingObservation.backing),
              static_cast<uint64_t>(backingObservation.threadToken),
              RaphaelBacking::poolIndex(before),
              backingObservation.result,
              before.available, before.length, static_cast<uint64_t>(before.owner),
              before.element, before.raw120, before.flags,
              after.available, after.length, static_cast<uint64_t>(after.owner),
              after.element, after.raw120, after.flags,
              backingObservation.successfulBefore, backingObservation.failedBefore,
              backingObservation.successfulAfter, backingObservation.failedAfter);
    }
    // Load each result counter once. The sum describes this live snapshot; sample
    // publication and drops may legitimately lag while another callback is active.
    const uint64_t backingTrue = submissionBackingAllocations.successful();
    const uint64_t backingFalse = submissionBackingAllocations.failed();
    const uint64_t backingCompleted = backingTrue + backingFalse;
    if (backingCompleted != lastBackingCompleted) {
        backingDirty = true;
    }
    // Six-second cadence keeps the initial record plus continuous dirty updates
    // within 31 records over the bounded 180-second observation lifetime.
    if (backingDirty && backingDirtyPolls < 600) ++backingDirtyPolls;
    const bool initialBacking = backingSummaryRecords == 0 &&
        __atomic_load_n(&submissionTraceRoutesReady, __ATOMIC_ACQUIRE);
    const bool periodicBacking = backingDirty && backingDirtyPolls >= 600;
    if (backingSummaryRecords < 32 &&
        (initialBacking || periodicBacking)) {
        CRLOG("SUB: backing-summary completed=%llu true=%llu false=%llu "
              "dropped=%llu state=live", backingCompleted, backingTrue,
              backingFalse, submissionBackingAllocations.failures().dropped());
        ++backingSummaryRecords;
        backingDirty = false;
        backingDirtyPolls = 0;
    }
    lastBackingCompleted = backingCompleted;
}

// Bounded summary of the child PDE / VRAM PTE conversions: at most 24 changed
// summaries plus the first four converted samples of each kind.
static void publishPendingVmEntryConversions() {
    if (vmRootFixMode < 2 || vmRootFixMode > 3) return;
    static uint64_t lastTotal = 0;
    static unsigned summaries = 0;
    static size_t sampleCursor[2] {};
    uint64_t c[2][RaphaelVm::kEntryDomainCount];
    uint64_t total = __atomic_load_n(&vmEntryInactive[0], __ATOMIC_RELAXED) +
        __atomic_load_n(&vmEntryInactive[1], __ATOMIC_RELAXED);
    for (size_t k = 0; k < 2; ++k)
        for (size_t d = 0; d < RaphaelVm::kEntryDomainCount; ++d) {
            c[k][d] = __atomic_load_n(&vmEntryCounts[k][d], __ATOMIC_RELAXED);
            total += c[k][d];
        }
    if (total != lastTotal && summaries < 24) {
        lastTotal = total;
        ++summaries;
        CRLOG("VM: entry-conv mode=%u routes=%u/%u pde=%llu/%llu/%llu/%llu/%llu "
              "pte=%llu/%llu/%llu/%llu/%llu inactive=%llu/%llu dropped=%llu/%llu",
              vmRootFixMode, orgVmmGetPde != 0, orgVmmGetPte != 0,
              c[0][0], c[0][1], c[0][2], c[0][3], c[0][4],
              c[1][0], c[1][1], c[1][2], c[1][3], c[1][4],
              __atomic_load_n(&vmEntryInactive[0], __ATOMIC_RELAXED),
              __atomic_load_n(&vmEntryInactive[1], __ATOMIC_RELAXED),
              vmEntrySamples[0].dropped(), vmEntrySamples[1].dropped());
    }
    for (size_t k = 0; k < 2; ++k) {
        RaphaelVm::EntryConversionSample sample {};
        while (sampleCursor[k] < vmEntrySamples[k].size() &&
               vmEntrySamples[k].read(sampleCursor[k], sample)) {
            ++sampleCursor[k];
            CRLOG("VM: entry-sample kind=%s level=%u flags=%#x original=%#llx result=%#llx "
                  "domain=%s",
                  sample.kind == RaphaelVm::EntryKind::Pde ? "pde" : "pte",
                  sample.level, sample.flags, sample.original, sample.result,
                  RaphaelVm::entryDomainName(sample.domain));
        }
    }
}

static void publishVmUpdateSample(const char *bucket,
                                  const RaphaelVm::EntryUpdateDecision &sample) {
    CRLOG("VM: entry-update-sample bucket=%s caller=x6+0x%llx producer=%s domain=%s "
          "destination=0x%llx count=%llu source=0x%llx result=0x%llx template=0x%llx "
          "increment=0x%llx constructed=0x%llx state=returned",
          bucket, sample.callerOffset, RaphaelVm::updateProducerName(sample.producer),
          RaphaelVm::updateDomainName(sample.domain), sample.destination, sample.count,
          sample.source, sample.result, sample.templateValue, sample.increment,
          sample.constructed);
}

// Cumulative snapshots use exponential activity thresholds plus immediate first
// conversion/safety-domain signals. They remain bounded without requiring a
// continuously active callback stream to become quiet.
static void publishPendingVmEntryUpdates() {
    if (vmRootFixMode < 4) return;
    static RaphaelVm::UpdateSummarySchedule summarySchedule {};
    static size_t childCursor = 0;
    static size_t eligibleCursor = 0;
    static size_t controlCursor = 0;
    uint64_t counts[RaphaelVm::kUpdateDomainCount] {};
    for (size_t n = 0; n < RaphaelVm::kUpdateDomainCount; ++n)
        counts[n] = __atomic_load_n(&vmUpdateCounts[n], __ATOMIC_ACQUIRE);
    if (summarySchedule.shouldPublish(counts)) {
        using D = RaphaelVm::UpdateDomain;
        CRLOG(RGPU_VM_ENTRY_UPDATE_SUMMARY_FORMAT, vmRootFixMode,
              orgVmmUpdateEntries != 0,
              counts[static_cast<size_t>(D::Inactive)],
              counts[static_cast<size_t>(D::Converted)],
              counts[static_cast<size_t>(D::AlreadyPhysical)],
              counts[static_cast<size_t>(D::Outside)],
              counts[static_cast<size_t>(D::System)],
              counts[static_cast<size_t>(D::InvalidTemplate)],
              counts[static_cast<size_t>(D::InvalidAperture)],
              counts[static_cast<size_t>(D::Empty)],
              counts[static_cast<size_t>(D::Overflow)],
              counts[static_cast<size_t>(D::SpanOutside)],
              counts[static_cast<size_t>(D::ZeroSource)],
              vmUpdateChildSamples.dropped(), vmUpdateEligibleSamples.dropped(),
              vmUpdateControlSamples.dropped());
    }
    RaphaelVm::EntryUpdateDecision sample {};
    while (childCursor < vmUpdateChildSamples.size() &&
           vmUpdateChildSamples.read(childCursor, sample)) {
        ++childCursor;
        publishVmUpdateSample("child", sample);
    }
    while (eligibleCursor < vmUpdateEligibleSamples.size() &&
           vmUpdateEligibleSamples.read(eligibleCursor, sample)) {
        ++eligibleCursor;
        publishVmUpdateSample("eligible", sample);
    }
    while (controlCursor < vmUpdateControlSamples.size() &&
           vmUpdateControlSamples.read(controlCursor, sample)) {
        ++controlCursor;
        publishVmUpdateSample("control", sample);
    }
}

static void publishPendingVmObservations() {
    publishClientFaultWalks();
    static size_t mapProcessCursor = 0;
    RaphaelVm::MapProcessObservation mapProcess {};
    while (mapProcessCursor < vmMapProcessSamples.size() &&
           vmMapProcessSamples.read(mapProcessCursor, mapProcess)) {
        ++mapProcessCursor;
        CRLOG("VM: map-process-root input=%#llx native=%#llx final=%#llx pasid=%u "
              "header=%#08x return-valid=%u repaired=%u reason=%u",
              mapProcess.inputRoot, mapProcess.nativeRoot, mapProcess.finalRoot,
              mapProcess.pasid, mapProcess.header, mapProcess.returnValid,
              mapProcess.repaired, mapProcess.reason);
    }
    static uint64_t lastMapProcessDropped = 0;
    static unsigned mapProcessDropReports = 0;
    const uint64_t mapProcessDropped = vmMapProcessSamples.dropped();
    if (mapProcessDropped != lastMapProcessDropped && mapProcessDropReports < 8) {
        lastMapProcessDropped = mapProcessDropped;
        ++mapProcessDropReports;
        CRLOG("VM: map-process-summary retained=%llu dropped=%llu",
              static_cast<uint64_t>(vmMapProcessSamples.size()), mapProcessDropped);
    }
    static size_t mmhubCursor = 0;
    RaphaelVm::PreparedRequest mmhubProgram {};
    while (mmhubCursor < mmhubPrograms.size() && mmhubPrograms.read(mmhubCursor, mmhubProgram)) {
        ++mmhubCursor;
        const auto *w = mmhubProgram.words;
        CRLOG("MH: prepared hub=%u vmid=%u reprogram=%u root=%#llx native=%#llx "
              "repaired=%u root-reg=%#x/%#x req=%#x ack=%#x mask=%#x",
              mmhubProgram.request.hub, mmhubProgram.request.vmid,
              mmhubProgram.request.reprogram, mmhubProgram.request.root,
              mmhubProgram.nativeRoot, mmhubProgram.rootRepaired,
              w[0], w[2], w[16], w[18], w[20]);
    }
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
        // This is the earliest worker-side register sample. Page-table walking
        // waits for a correlated submit so an unmapped hard-coded VA cannot be
        // mistaken for a conversion failure.
        if (programCount == 1)
            reportVmid2Runtime("prepared", program.sequence, program, nullptr, false);
    }
    RaphaelSdma::SubmitInfoObservation submit {};
    while (submitCursor < vmid2Submits.size() && vmid2Submits.read(submitCursor, submit)) {
        ++submitCursor;
        const uint32_t hint = submit.vmProgramSequence;
        const auto correlation = RaphaelVm::correlateSubmit(
            submit, programCache, programCount);
        const RaphaelVm::PreparedRequest *matched =
            correlation.matchedIndex != RaphaelVm::kNoProgramMatch
                ? &programCache[correlation.matchedIndex] : nullptr;
        submit.vmProgramSequence = matched != nullptr ? matched->sequence : 0;
        CRLOG("SD: submit vmid=%u flags=%#x entries=%u valid=%u IB0=%#llx IB1=%#llx seq=%u",
              submit.vmid, submit.flags, submit.entries, submit.layoutValid,
              submit.addresses[0], submit.addresses[1], submit.vmProgramSequence);
        CRLOG("VM: correlate-submit order=%u thread=0x%llx hint=%u result=%u reason=%s "
              "retained=%llu same-thread=%llu earlier=%llu in-range=%llu",
              submit.eventOrder, static_cast<uint64_t>(submit.threadToken), hint,
              submit.vmProgramSequence,
              RaphaelVm::correlationReasonName(correlation.reason),
              static_cast<uint64_t>(correlation.retained),
              static_cast<uint64_t>(correlation.sameThread),
              static_cast<uint64_t>(correlation.earlier),
              static_cast<uint64_t>(correlation.inRange));
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
    publishPendingVmEntryConversions();
    publishPendingVmEntryUpdates();
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
    applySdmaAddrConfig("startHWEngines", false);
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

// Candidate270: observe the real decoder context boundary. No return-value or
// input changes; counts are per operation and bounded. Pinned 24G830 ABIs.
static mach_vm_address_t orgVcnCreateContext = 0, orgVcnRequestCap = 0;
static mach_vm_address_t orgVcnStartEngine = 0, orgVcnSendPM = 0;
static mach_vm_address_t orgVcnNewContext = 0;
static uint32_t vcnNewContextCalls = 0;
static uint32_t vcnContextCalls[4] = {};
static uint32_t vcnContextSequence(unsigned operation) {
    return __atomic_add_fetch(&vcnContextCalls[operation], 1u, __ATOMIC_RELAXED);
}
static uint32_t wrapVcnCreateContext(void *self, const uint32_t *info, uint32_t *output) {
    const uint32_t n = vcnContextSequence(0);
    if (n <= 16) RLOG("VCNCTX: create begin n=%u self=%p info=%p output=%p codec=%u channel=%u width=%u height=%u instance=%u",
        n, self, info, output, info ? info[1] : 0, info ? info[2] : 0,
        info ? info[3] : 0, info ? info[4] : 0, info ? info[12] : 0);
    const uint32_t result = FunctionCast(wrapVcnCreateContext, orgVcnCreateContext)(self, info, output);
    if (n <= 16) RLOG("VCNCTX: create end n=%u result=%08x id=%u", n, result,
        !result && output ? *output : 0xffffffffu);
    return result;
}
static uint32_t wrapVcnNewContext(void *self, const uint32_t *info, uint32_t *output,
                                  uint64_t inputSize, uint64_t *outputSize) {
    const uint32_t n = __atomic_add_fetch(&vcnNewContextCalls, 1u, __ATOMIC_RELAXED);
    if (n <= 16) CRLOG("VCNCTX: video new begin n=%u codec=%u channel=%u width=%u height=%u scheduler=%u client=%u pm=%#llx",
        n, info ? info[1] : 0, info ? info[2] : 0, info ? info[3] : 0,
        info ? info[4] : 0, info ? info[6] : 0, info ? info[7] : 0,
        info ? (uint64_t(info[9]) << 32 | info[8]) : 0);
    const uint32_t result = FunctionCast(wrapVcnNewContext, orgVcnNewContext)(
        self, info, output, inputSize, outputSize);
    if (n <= 16) CRLOG("VCNCTX: video new end n=%u result=%08x id=%u", n, result,
                      !result && output ? *output : 0xffffffffu);
    return result;
}
static bool wrapVcnRequestCap(void *self, const void *cap, uint32_t *output, uint32_t flags, bool encode) {
    const uint32_t n = vcnContextSequence(1);
    auto bytes = static_cast<const uint8_t *>(self);
    if (n <= 16) RLOG("VCNCTX: capability begin n=%u engine=%p flags=%x encode=%u active=%u maximum=%u",
        n, self, flags, encode, *reinterpret_cast<const uint32_t *>(bytes + 0x2ac),
        *reinterpret_cast<const uint32_t *>(bytes + 0x2b4));
    const bool result = FunctionCast(wrapVcnRequestCap, orgVcnRequestCap)(self, cap, output, flags, encode);
    if (n <= 16) RLOG("VCNCTX: capability end n=%u result=%u", n, result);
    return result;
}
static uint32_t wrapVcnStartEngine(void *self, const uint32_t *info, uint64_t size) {
    const uint32_t n = vcnContextSequence(2);
    if (n <= 16) RLOG("VCNCTX: start begin n=%u size=%llu id=%u instance=%u channel=%u",
        n, size, info && size == 12 ? info[0] : 0, info && size == 12 ? info[1] : 0,
        info && size == 12 ? info[2] : 0);
    const uint32_t result = FunctionCast(wrapVcnStartEngine, orgVcnStartEngine)(self, info, size);
    if (n <= 16) RLOG("VCNCTX: start end n=%u result=%08x", n, result);
    return result;
}
static uint32_t wrapVcnSendPM(void *self, const void *request) {
    const auto caller = reinterpret_cast<mach_vm_address_t>(__builtin_return_address(0));
    const bool selected = (caller >= x6Base + 0x21ba0 && caller < x6Base + 0x21f18) ||
        (caller >= x6Base + 0x21404 && caller < x6Base + 0x214d3) ||
        (caller >= x6Base + 0x28c4e && caller < x6Base + 0x28e70) ||
        (caller >= x6Base + 0x48758 && caller < x6Base + 0x48946);
    const uint32_t n = selected ? vcnContextSequence(3) : 0;
    if (selected && n <= 32) {
        // Native callers pass four kernel-owned words: input, input bytes,
        // output, output-size pointer. Decode only their bounded input header.
        auto words = static_cast<const uint64_t *>(request);
        const uint64_t length = words ? words[1] : 0;
        const auto input = words ? reinterpret_cast<const uint32_t *>(words[0]) : nullptr;
        const bool header = input && length >= 8 && length <= 0x1000;
        auto accelerator = static_cast<const uint8_t *>(self);
        RLOG("VCNCTX: PM begin n=%u caller=+%llx request=%p bytes=%llu header=%u/%08x accel-flags=%x display-machine=%p",
            n, caller-x6Base, request, length, header ? input[0] : 0,
            header ? input[1] : 0, accelerator[0xc78],
            *reinterpret_cast<void *const *>(accelerator + 0x378));
    }
    const uint32_t result = FunctionCast(wrapVcnSendPM, orgVcnSendPM)(self, request);
    if (selected && n <= 32) RLOG("VCNCTX: PM end n=%u caller=+%llx result=%08x", n, caller-x6Base, result);
    return result;
}

static uint32_t wrapAccPowerUpHW(void *self) {
    CRLOG("XJ: AMDGraphicsAccelerator::powerUpHW entry");
    auto r = FunctionCast(wrapAccPowerUpHW, orgAccPowerUpHW)(self);
    CRLOG("XJ: AMDGraphicsAccelerator::powerUpHW -> %u", r & 0xff);
    applySdmaAddrConfig("powerUpHW", false);
    return r;
}

static bool publishRecoveryPoolStatus(const RaphaelRecoveryV2::PoolStatus &status) {
    if (recoveryPoolStatusPublished) return false;
    if (!RaphaelRecoveryV2::validOwnership(
            recoveryLeaseState.ownership(), recoveryNonceLo, recoveryNonceHi,
            hwMemObject != nullptr
                ? RaphaelRecoveryV2::compatibilityPoolSize(
                      RaphaelRecoveryV2::nativePoolSizes(
                          *reinterpret_cast<uint64_t *>(
                              reinterpret_cast<uint8_t *>(hwMemObject) + 0x40),
                          *reinterpret_cast<uint64_t *>(
                              reinterpret_cast<uint8_t *>(hwMemObject) + 0x48)))
                : 0) ||
        !RaphaelRecoveryV2::validPoolStatus(status, recoveryLeaseState.ownership()))
        return false;
    auto fb = fbAperture();
    if (fb == nullptr) return false;
    const uint64_t base = status.leaseOffset + RaphaelRecoveryV2::PoolStatusOffset;
    auto fence = [] { OSSynchronizeIO(); };
    bool written = RaphaelRecoveryV2::publishRecord(
        status,
        [=](uint32_t i, uint32_t value) { fb[base / 4 + i] = value; },
        [=](uint32_t i) { return fb[base / 4 + i]; }, fence);
    if (!written) return false;
    recoveryPoolStatusPublished = true;
    if (status.state == RaphaelRecoveryV2::PoolActive) {
        recoveryActivePoolStatus = status;
        __atomic_store_n(&recoveryActivePoolStatusReady, true, __ATOMIC_RELEASE);
    }
    const auto nonce = RaphaelRecoveryV2::logNonce(status);
    CRLOG("XH2 POOL state=%s nonce=%016llx_%016llx gen=1 lease=%#llx-%#llx "
          "pool0=%#llx->%#llx pool1=%#llx->%#llx reason=%llu checksum=%#llx",
          status.state == RaphaelRecoveryV2::PoolActive ? "ACTIVE" : "INVALID",
          nonce.first, nonce.second, status.leaseOffset, status.leaseEnd,
          status.pool0Before, status.pool0After, status.pool1Before, status.pool1After,
          status.reason, status.checksum);
    return true;
}

static bool wrapHwMemEnable(void *self) {
    if (self == nullptr)
        return FunctionCast(wrapHwMemEnable, orgHwMemEnable)(self);
    auto f = reinterpret_cast<uint8_t *>(self);
    auto q = [f](size_t o) -> uint64_t & {
        return *reinterpret_cast<uint64_t *>(f + o);
    };
    if (!discoveredCapacityValid || self != hwMemObject) {
        RLOG("XH: enableAllocations rejected: VRAM capacity discovery invalid");
        return false;
    }
    if (recoveryLeaseConfigured) {
        void *expectedMemory = __atomic_load_n(
            &recoveryLeaseMemoryOwner, __ATOMIC_ACQUIRE);
        void *expectedHardware = __atomic_load_n(
            &recoveryLeaseHardwareOwner, __ATOMIC_ACQUIRE);
        void *actualHardware = *reinterpret_cast<void **>(f + 0x10);
        auto vt = *reinterpret_cast<uint64_t **>(self);
        if (self != expectedMemory || actualHardware != expectedHardware ||
            expectedHardware == nullptr || vt == nullptr ||
            vt[0x198 / 8] != x6Base + kOffHwMemReserve) {
            abortRecoveryLifetime(RaphaelRecoveryV3::LifetimeReasonPoolOwner);
            CRLOG("XH2 ABORT reason=pool-owner nonce=%016llx_%016llx",
                  recoveryNonceLo, recoveryNonceHi);
            RLOG("XH: v2 pool owner rejected memory=%p/%p hardware=%p/%p reserve=%#llx",
                 self, expectedMemory, actualHardware, expectedHardware,
                 vt != nullptr ? vt[0x198 / 8] : 0);
            return false;
        }
    }
    hwMemObject = self;
    RLOG("XH: enableAllocations entry: pool0=%p pool1=%p size0=%#llx size1=%#llx "
         "base=%#llx", reinterpret_cast<void *>(q(0x68)),
         reinterpret_cast<void *>(q(0x70)), q(0x40), q(0x48), q(0x50));
    if (!recoveryLeaseConfigured) {
        auto r = FunctionCast(wrapHwMemEnable, orgHwMemEnable)(self);
        RLOG("XH: enableAllocations -> %u (v2 lease disabled)", r);
        return r;
    }
    recoveryLeaseElement = nullptr;
    auto result = RaphaelRecoveryV2::establishPools(
        recoveryLeaseState, q(0x50),
        [&] { return FunctionCast(wrapHwMemEnable, orgHwMemEnable)(self); },
        [&]() -> RaphaelRecoveryV2::PoolFreeSnapshot {
            auto pool0 = reinterpret_cast<uint8_t *>(q(0x68));
            auto pool1 = reinterpret_cast<uint8_t *>(q(0x70));
            if (pool0 == nullptr || pool1 == nullptr) return {false, 0, 0};
            return {true, *reinterpret_cast<uint64_t *>(pool0 + 0x50),
                          *reinterpret_cast<uint64_t *>(pool1 + 0x50)};
        },
        [&](uint64_t address, uint64_t length) {
            RaphaelRecoveryV2::NativeReserveEvidence evidence {};
            auto vt = *reinterpret_cast<uint64_t **>(self);
            if (!__atomic_load_n(&raphaelTargetConfirmed, __ATOMIC_ACQUIRE) ||
                vt == nullptr || vt[0x198 / 8] != x6Base + kOffHwMemReserve)
                return evidence;
            auto reserve = reinterpret_cast<bool (*)(void *, void **, uint64_t,
                                                      uint64_t, bool, uint32_t)>(
                vt[0x198 / 8]);
            evidence.returned = reserve(self, &recoveryLeaseElement, address,
                                        length, true, 0x22);
            evidence.element = recoveryLeaseElement;
            if (recoveryLeaseElement != nullptr) {
                auto element = reinterpret_cast<uint8_t *>(recoveryLeaseElement);
                evidence.pool0Start = *reinterpret_cast<uint64_t *>(element + 0x20);
                evidence.pool1Start = *reinterpret_cast<uint64_t *>(element + 0x50);
            }
            return evidence;
        },
        [&](const RaphaelRecoveryV2::PoolStatus &status) {
            return publishRecoveryPoolStatus(status);
        },
        [&](const RaphaelRecoveryV2::PoolStatus &status) {
            return authorizeRecoveryClients(status);
        });
    if (!result.active) {
        if (result.reason == RaphaelRecoveryV2::ReasonDuplicateEpoch) {
            abortRecoveryLifetime(
                RaphaelRecoveryV3::LifetimeReasonDuplicatePool);
            CRLOG("XH2 ABORT reason=duplicate-pool nonce=%016llx_%016llx",
                  recoveryNonceLo, recoveryNonceHi);
        }
        RLOG("XH: v2 pool exclusion failed reason=%llu native=%u reserve=%u "
             "element=%p starts=%#llx/%#llx expected=%#llx "
             "pool0=%#llx->%#llx pool1=%#llx->%#llx",
             result.reason, result.nativeResult, result.reserve.returned,
             result.reserve.element, result.reserve.pool0Start,
             result.reserve.pool1Start, result.fullAddress,
             result.before.pool0, result.after.pool0,
             result.before.pool1, result.after.pool1);
        return 0;
    }
    RLOG("XH: enableAllocations -> %u; v2 lease ACTIVE element=%p full=%#llx",
         result.nativeResult, result.reserve.element, result.fullAddress);
    return result.nativeResult;
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
    __atomic_store_n(&ppCompatibilityBypassed, true, __ATOMIC_RELEASE);
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

static bool entryMatches(mach_vm_address_t base, size_t imageSize, size_t offset,
                         const uint8_t *expected, size_t expectedSize);

// ---- Physical display: Apple's DCN 3.02 display core on Raphael's DCN 3.1.5 ----
//
// AMDRadeonX6000Framebuffer embeds AMD's display core (DC 3.2.145) with DCN 2.0, 2.1, 3.0
// and 3.02 resource pools. resource_parse_asic_id (0xb3084) maps family 0x8f by
// hw_internal_rev: [60,70) -> DCN 3.02 (Navi 23), [40,70) -> DCN 3.0, else DCN 2.0. The
// unreadable strap makes Raphael report rev 75, so today the DAL builds a Navi 10 pool.
// DCN 3.0.2 is the closest register map to Raphael's 3.1.5 (same base segments, 94% of
// shared registers at the same index), so rgpudcn steers the DAL there and rewrites the
// rest of the register indices where every DAL register access goes: the cgs_device's
// read/write slots. dm_read_reg/dm_write_reg (0x6dcb8/0x6dca6) and the DMUB register
// callbacks (0x888a4/0x888b8) all jump through [cgs+0x40]/[cgs+0x48](cgs->ctx, ...).
//
//   0xfea5e  dc_create(init_data): +0x00 hw_asic_id (+4 family, +0xc rev), +0x30 cgs_device
//   0xff053  dc_hardware_init(dc): calls hwss.init_hw; dc+0x308 ctx, ctx+0x88 dc_dmub_srv
//   0x110bd7 generic_reg_wait(ctx, index, shift, mask, expected, delay_us, tries, func, line)
//
// The guest never programs DMCUB. Registering Raphael's DMCUB firmware for PSP from the
// guest (the withdrawn rgpudcn bit 8) froze the host within a second of the PSP firmware
// load on 2026-09-17 (findings/research/dcn315-dmcub-host-crash-20260917.md): DMCUB boots
// from PSP-owned windows and reaches memory through its own secure unit. While translating,
// the DAL reads CC_DC_PIPE_DIS with DC_DMCUB_ENABLE cleared, so dmub_srv_has_hw_support()
// fails, and every DMCUB_* register write is dropped.
//
// rgpudcn=<mask>: 1 trace, 2 translate (needs 4), 4 DCN 3.02 pool (rev 75 -> 60),
// 16 inert dc_dmub_srv if DMUB never attached (dcn30 init_hw dereferences ctx->dmub_srv
// unconditionally). Bit 8 is refused. rgpudcntrace=<lines> bounds the access trace
// (default 1500).
static constexpr size_t kOffDcnRegWait     = 0x110bd7;
static constexpr size_t kOffDcCreate       = 0xfea5e;
static constexpr size_t kOffDcHardwareInit = 0xff053;
static constexpr size_t kOffDcDmubQueue = 0x1b06de;    // dc_dmub_srv_cmd_queue
static constexpr size_t kOffDcDmubExecute = 0x1b0756;  // dc_dmub_srv_cmd_execute
static constexpr size_t kOffDcDmubWait = 0x1b0797;     // dc_dmub_srv_wait_idle
enum : uint32_t {
    kDcnTrace = 1, kDcnTranslate = 2, kDcnPool302 = 4, kDcnWithdrawnDmcubFirmware = 8,
    kDcnDmubGuard = 16, kDcnDioWake = 32, kDcnHostI2cSpeed = 64, kDcnDmcubSurvey = 128,
    kDcnDmubHook = 256, kDcnDmubDeliver = 512,
    kDcnAllowed = kDcnTrace | kDcnTranslate | kDcnPool302 | kDcnDmubGuard | kDcnDioWake |
                  kDcnHostI2cSpeed | kDcnDmcubSurvey | kDcnDmubHook | kDcnDmubDeliver,
};
static uint32_t dcnMode = 0;
static uint32_t dcnTraceBudget = 1500;
static mach_vm_address_t orgDcnRegWait = 0, orgDcCreate = 0, orgDcHardwareInit = 0;
using DcnRegRead = uint32_t (*)(void *, uint32_t);
using DcnRegWrite = void (*)(void *, uint32_t, uint32_t);
static DcnRegRead dcnNativeRead = nullptr;
static DcnRegWrite dcnNativeWrite = nullptr;
static void *dcnRegContext = nullptr;
static RaphaelDcn::AccessCounter<4096> dcnAccesses;
static RaphaelDcn::DalMailbox dcnDalMailbox;
static volatile uint32_t dcnTraceLines = 0;
static volatile uint32_t dcnDropped = 0;

static bool dcnTranslating() {
    return (dcnMode & (kDcnTranslate | kDcnPool302)) == (kDcnTranslate | kDcnPool302);
}

// Return addresses one and two frames above the register accessor's caller. Every native
// frame here keeps RBP (push rbp; mov rbp,rsp), and so does this kext.
static void dcnCallers(void *frame, uint64_t *first, uint64_t *second) {
    *first = *second = 0;
    auto valid = [](uint64_t p) { return p >= 0xffffff8000000000ULL && (p & 7) == 0; };
    const uint64_t callerFrame = frame ? *reinterpret_cast<uint64_t *>(frame) : 0;
    if (!valid(callerFrame)) return;
    *first = reinterpret_cast<uint64_t *>(callerFrame)[1];
    const uint64_t upper = *reinterpret_cast<uint64_t *>(callerFrame);
    if (valid(upper)) *second = reinterpret_cast<uint64_t *>(upper)[1];
}

static uint64_t dcnRel(uint64_t address) {
    return fbBase && address >= fbBase && address < fbBase + 0x400000 ? address - fbBase : address;
}

static void dcnTraceAccess(char op, uint32_t from, const RaphaelDcn::Mapping &m, uint32_t value,
                           uint64_t ret, void *frame, const char *note = "") {
    if (!(dcnMode & kDcnTrace)) return;
    const uint32_t seen = dcnAccesses.note(RaphaelDcn::accessKey(from, op == 'W'));
    const bool dropped = m.action == RaphaelDcn::Action::Drop;
    if (!(seen == 1 || seen == 2 || (dropped && seen <= 3) || *note ||
          RaphaelDcn::isDdcTraceWindow(from))) return;
    if (__sync_add_and_fetch(&dcnTraceLines, 1) > dcnTraceBudget) return;
    uint64_t up1 = 0, up2 = 0;
    dcnCallers(frame, &up1, &up2);
    RLOG("DCN: %c %#x%s%#x v=%#x n=%u @%#llx<%#llx<%#llx%s", op, from,
         dropped ? " DROP " : m.action == RaphaelDcn::Action::Move ? " -> " : " = ",
         m.index, value, seen, dcnRel(ret), dcnRel(up1), dcnRel(up2), note);
}

__attribute__((noinline))
static uint32_t wrapDcnRegRead(void *context, uint32_t index) {
    using namespace RaphaelDcn;
    Mapping m {Action::Pass, index};
    const char *note = "";
    uint32_t value = 0;
    if (!dcnTranslating()) {
        value = dcnNativeRead(context, index);
    } else if (DalMailbox::owns(index)) {
        m = {Action::Drop, index};
        value = dcnDalMailbox.read(index);
        note = " (DALSMC emulated)";
    } else {
        m = translate(index);
        if (m.action == Action::Drop) {
            __sync_add_and_fetch(&dcnDropped, 1);
        } else if (index == k302CcDcPipeDis) {
            value = maskDmcubStrap(dcnNativeRead(context, m.index));
            note = " (DMCUB reported absent)";
        } else {
            value = dcnNativeRead(context, m.index);
            if (const FieldRemap *remap = fieldRemap(index)) value = remapRead(*remap, value);
        }
    }
    dcnTraceAccess('R', index, m, value, reinterpret_cast<uint64_t>(__builtin_return_address(0)),
                   __builtin_frame_address(0), note);
    return value;
}

__attribute__((noinline))
static void wrapDcnRegWrite(void *context, uint32_t index, uint32_t value) {
    using namespace RaphaelDcn;
    Mapping m {Action::Pass, index};
    const char *note = "";
    if (!dcnTranslating()) {
        dcnNativeWrite(context, index, value);
    } else if (DalMailbox::owns(index)) {
        m = {Action::Drop, index};
        note = " (DALSMC emulated)";
        if (dcnDalMailbox.write(index, value))
            CRLOG("DCN: DALSMC message %#x argument %#x answered failed (Raphael has no DAL "
                  "mailbox)", dcnDalMailbox.message(), dcnDalMailbox.argument());
    } else {
        m = translate(index);
        if (isDmcubRegister(index)) {
            m = {Action::Drop, index};
            note = " (DMCUB write blocked)";
            CRLOG("DCN: blocked DMCUB register write %#x = %#x", index, value);
        } else if (m.action == Action::Drop) {
            __sync_add_and_fetch(&dcnDropped, 1);
        } else if (const FieldRemap *remap = fieldRemap(index)) {
            dcnNativeWrite(context, m.index,
                           remapWrite(*remap, value, dcnNativeRead(context, m.index)));
            note = " (fields remapped)";
        } else if ((dcnMode & kDcnHostI2cSpeed) && m.index == k315DcI2cDdc1Speed &&
                   value != kHostDdc1Speed) {
            dcnNativeWrite(context, m.index, kHostDdc1Speed);
            note = " (DDC1 speed replayed from the host: 0x9600102)";
        } else {
            dcnNativeWrite(context, m.index, value);
        }
    }
    dcnTraceAccess('W', index, m, value, reinterpret_cast<uint64_t>(__builtin_return_address(0)),
                   __builtin_frame_address(0), note);
}

// Every exhausted wait prints "generic_reg_wait:513" with no register; name each one.
static void wrapDcnRegWait(void *ctx, uint32_t index, uint32_t shift, uint32_t fieldMask,
                           uint32_t expected, uint32_t delayUs, uint32_t tries,
                           const char *func, int line) {
    static volatile uint32_t waits = 0;
    const uint32_t n = __sync_add_and_fetch(&waits, 1);
    const RaphaelDcn::Mapping m = dcnTranslating() ? RaphaelDcn::translate(index)
                                                   : RaphaelDcn::Mapping{RaphaelDcn::Action::Pass, index};
    FunctionCast(wrapDcnRegWait, orgDcnRegWait)(ctx, index, shift, fieldMask, expected, delayUs,
                                               tries, func, line);
    if (n <= 64)
        RLOG("DCN: wait#%u %s:%d reg %#x%s%#x field(<<%u & %#x) == %#x delay=%uus tries=%u",
             n, func ? func : "?", line, index,
             m.action == RaphaelDcn::Action::Drop ? " DROP " : " -> ", m.index, shift, fieldMask,
             expected, delayUs, tries);
}

// Steer only the display core: the asic id reaches no other client through this struct.
// The DCN 3.02 pool brings Apple's DMUB service with it, so the pool is only selected once
// the register interposition that fences DMCUB off is in place.
static void *wrapDcCreate(void *init) {
    if (init != nullptr && (dcnMode & (kDcnTrace | kDcnTranslate)) && dcnNativeRead == nullptr) {
        const auto cgs = *reinterpret_cast<uint64_t **>(reinterpret_cast<uint8_t *>(init) + 0x30);
        // Kext text lives in the auxiliary collection at 0xffffff7f8... as well as in the
        // boot collection at 0xffffff80...; HWLibs' cgs register functions are the former.
        const auto kernelText = [](uint64_t p) { return p >= 0xffffff7f80000000ULL; };
        if (cgs != nullptr) {
            CRLOG("DCN: cgs %p slots ctx=%#llx read=%#llx write=%#llx getProperty=%#llx", cgs,
                  cgs[5], cgs[8], cgs[9], cgs[10]);
        }
        if (cgs != nullptr && kernelText(cgs[8]) && kernelText(cgs[9])) {
            dcnRegContext = reinterpret_cast<void *>(cgs[5]);
            dcnNativeRead = reinterpret_cast<DcnRegRead>(cgs[8]);
            dcnNativeWrite = reinterpret_cast<DcnRegWrite>(cgs[9]);
            cgs[9] = reinterpret_cast<uint64_t>(wrapDcnRegWrite);
            cgs[8] = reinterpret_cast<uint64_t>(wrapDcnRegRead);
        }
        CRLOG("DCN: cgs %p read=%#llx write=%#llx -> %s", cgs,
              dcnRel(reinterpret_cast<uint64_t>(dcnNativeRead)),
              dcnRel(reinterpret_cast<uint64_t>(dcnNativeWrite)),
              dcnNativeRead ? "interposed" : "NOT interposed");
    }
    if (dcnNativeRead == nullptr) dcnMode &= ~(kDcnTrace | kDcnTranslate | kDcnPool302);
    if (init != nullptr && dcnTranslating()) {
        auto asic = reinterpret_cast<uint32_t *>(init);
        const uint32_t family = asic[1], rev = asic[3];
        if (family == 0x8f && (rev < 60 || rev >= 70)) asic[3] = 60;
        CRLOG("DCN: dc_create chip=%#x family=%#x pci_rev=%#x hw_internal_rev %u -> %u "
              "(DCN 3.02 pool)", asic[0], family, asic[2], rev, asic[3]);
    }
    void *dc = FunctionCast(wrapDcCreate, orgDcCreate)(init);
    if (dc != nullptr && dalLogMask != 0) {
        const auto kernelPtr = [](uint64_t p) { return p >= 0xffffff8000000000ULL; };
        const auto ctx = *reinterpret_cast<uint64_t *>(reinterpret_cast<uint8_t *>(dc) + 0x308);
        const auto logger = kernelPtr(ctx) ? *reinterpret_cast<uint64_t *>(ctx + 0x10) : 0;
        if (kernelPtr(logger)) {
            auto mask = reinterpret_cast<uint64_t *>(logger + 0x20);
            CRLOG("DCN: DAL logger %#llx mask %#llx -> %#llx", logger, *mask, dalLogMask);
            *mask = dalLogMask;
        } else {
            CRLOG("DCN: DAL logger not found (ctx %#llx logger %#llx)", ctx, logger);
        }
    }
    CRLOG("DCN: dc_create -> %p (translate=%u trace-lines=%u dropped=%u unique=%zu)", dc,
          dcnTranslating(), dcnTraceLines, dcnDropped, dcnAccesses.used());
    return dc;
}


// Inbox1 ring of the running DMCUB, found by the survey (BAR0 offset and size; 0 = unknown).
static uint64_t dcnRingBar = 0;
// rgpudallog=<mask>: dc_context->logger (+0x10) type mask (+0x20), dc_log_type bits (v5.14).
static uint64_t dalLogMask = 0;
static uint32_t dcnRingSize = 0;

// Read-only survey of the DMCUB the host driver left running (rgpudcn bit 128). Nothing here
// writes a register or VRAM: it logs every non-zero DMCUB register, whether the firmware timer
// advances, where each memory window lives in VRAM, and the last commands in the inbox ring.
static void dcnSurveyDmcub(const char *when) {
    if (!(dcnMode & kDcnDmcubSurvey) || dcnNativeRead == nullptr) return;
    auto rd = [](uint32_t index) { return dcnNativeRead(dcnRegContext, index); };
    char line[240];
    size_t len = 0;
    unsigned printed = 0;
    auto emit = [&](uint32_t index, uint32_t value) {
        len += snprintf(line + len, sizeof(line) - len, " %x=%x", index, value);
        if (++printed % 8 == 0) { CRLOG("DCN: DMCUB %s regs%s", when, line); len = 0; line[0] = 0; }
    };
    line[0] = 0;
    if (const uint32_t v = rd(0x363a)) emit(0x363a, v);                  // DMCUB_RBBMIF_SEC_CNTL
    for (uint32_t index = 0x364e; index <= 0x36c0; index++)
        if (const uint32_t v = rd(index)) emit(index, v);
    if (len) CRLOG("DCN: DMCUB %s regs%s", when, line);

    const uint32_t t0 = rd(0x36bd);                                      // DMCUB_TIMER_CURRENT
    IODelay(1000);
    const uint32_t t1 = rd(0x36bd);
    CRLOG("DCN: DMCUB %s timer %#x -> %#x in 1 ms (%s), CNTL=%#x SCRATCH0=%#x", when, t0, t1,
          t1 != t0 ? "running" : "STOPPED", rd(0x36b6), rd(0x36a3));

    // Memory windows: REGION3_CWn maps [BASE, TOP) of the DMCUB address space to the MC
    // address in CWn_OFFSET. On this APU the MC address is inside the framebuffer aperture.
    const uint64_t fbMc = asicInfo != nullptr
        ? static_cast<uint64_t>(fbRead(asicInfo, kGcFbBase) & 0xffffff) << 24 : 0;
    auto volatile *fb = fbAperture();
    auto visible = [](uint64_t off, uint64_t size) {
        uint64_t end = 0;
        return discoveredCapacityValid ? fitsDiscoveredBar(off, size)
                                       : (RaphaelRecoveryV2::checkedAdd(off, size, end) &&
                                          end <= cachedBarMapLength);
    };
    uint32_t cwBase[8] {}, cwTop[8] {};
    uint64_t cwMc[8] {};
    for (unsigned cw = 0; cw < 8; cw++) {
        cwBase[cw] = rd(0x3665 + cw);
        cwTop[cw] = rd(0x366d + cw) & 0x1fffffff;
        cwMc[cw] = rd(0x3675 + 2 * cw) | (static_cast<uint64_t>(rd(0x3676 + 2 * cw)) << 32);
        if (cwBase[cw] == 0 && cwMc[cw] == 0) continue;
        const bool inFb = fbMc != 0 && cwMc[cw] >= fbMc;
        const uint64_t bar = inFb ? cwMc[cw] - fbMc : 0;
        CRLOG("DCN: DMCUB %s CW%u dmcub [%#x,%#x) -> MC %#llx fb+%#llx %s", when, cw,
              cwBase[cw], cwTop[cw], cwMc[cw], bar,
              !inFb ? "outside FB" : visible(bar, 0x1000) ? "BAR-visible" : "not BAR-visible");
    }

    // Inbox1 ring: 64-byte commands. Dump the last four the host driver wrote.
    const uint32_t inBase = rd(0x3694), inSize = rd(0x3695), inW = rd(0x3696), inR = rd(0x3697);
    CRLOG("DCN: DMCUB %s inbox1 base=%#x size=%#x wptr=%#x rptr=%#x | outbox1 base=%#x size=%#x "
          "wptr=%#x rptr=%#x | fbMc=%#llx bar=%p", when, inBase, inSize, inW, inR, rd(0x369c),
          rd(0x369d), rd(0x369e), rd(0x369f), fbMc, fb);
    if (fb == nullptr || fbMc == 0 || inSize == 0 || inSize > 0x100000) return;
    // CWn_BASE/TOP hold the window without the 0x60000000 DMCUB prefix the inbox base carries.
    const uint32_t inOff = inBase & 0x1fffffff;
    for (unsigned cw = 0; cw < 8; cw++) {
        if (inOff < cwBase[cw] || inOff >= cwTop[cw] || cwMc[cw] < fbMc) continue;
        const uint64_t ringBar = cwMc[cw] - fbMc + (inOff - cwBase[cw]);
        dcnRingBar = ringBar;
        dcnRingSize = inSize;
        if (!visible(ringBar, inSize)) { CRLOG("DCN: DMCUB inbox ring fb+%#llx not visible", ringBar); return; }
        for (unsigned k = 4; k >= 1; k--) {
            const uint32_t at = (inW + inSize - 64 * k) % inSize;
            len = 0; line[0] = 0;
            for (unsigned d = 0; d < 16; d++)
                len += snprintf(line + len, sizeof(line) - len, " %08x", fb[(ringBar + at + 4 * d) / 4]);
            CRLOG("DCN: DMCUB %s inbox[%#x]%s", when, at, line);
        }
        return;
    }
    CRLOG("DCN: DMCUB inbox base %#x is in no mapped window", inBase);
}

static void dcnLogDmcubState(const char *when) {
    if (dcnNativeRead == nullptr) return;
    // Reads only: DMCUB_CNTL and the boot status never change what the microcontroller does.
    const uint32_t cntl = dcnNativeRead(dcnRegContext, RaphaelDcn::k302DmcubCntl);
    const uint32_t status = dcnNativeRead(dcnRegContext, RaphaelDcn::k315DmcubScratch0);
    CRLOG("DCN: DMCUB %s CNTL=%#x SCRATCH0=%#x (untouched by the guest)", when, cntl, status);
}

static void wrapDcHardwareInit(void *dc) {
    if (dc != nullptr) {
        const auto ctx = *reinterpret_cast<uint8_t **>(reinterpret_cast<uint8_t *>(dc) + 0x308);
        const auto slot = ctx ? reinterpret_cast<void **>(ctx + 0x88) : nullptr;
        dcnLogDmcubState("before init_hw");
        dcnSurveyDmcub("before");
        CRLOG("DCN: dc_hardware_init dc=%p ctx=%p dmub_srv=%p", dc, ctx, slot ? *slot : nullptr);
        if ((dcnMode & kDcnDmubGuard) && slot != nullptr && *slot == nullptr) {
            // dc_dmub_srv is 0x68 bytes: +0x00 struct dmub_srv *, +0x58 dc_context *. A zeroed
            // dmub_srv has hw_init == false, so every DMUB call returns an error instead.
            static uint8_t inertDmub[0x1000] {};
            static uint64_t inertDcDmub[13] {};
            inertDcDmub[0] = reinterpret_cast<uint64_t>(inertDmub);
            inertDcDmub[11] = reinterpret_cast<uint64_t>(ctx);
            *slot = inertDcDmub;
            CRLOG("DCN: DMUB service never attached; installed an inert dc_dmub_srv so "
                  "dcn30_init_hw cannot dereference NULL");
        }
    }
    FunctionCast(wrapDcHardwareInit, orgDcHardwareInit)(dc);
    dcnLogDmcubState("after init_hw");
    dcnSurveyDmcub("after");
    if ((dcnMode & kDcnDioWake) && dcnNativeRead != nullptr && dcnNativeWrite != nullptr) {
        // Wake the DIO I2C engine memory the host driver left in forced light sleep, and keep
        // it awake; poll the power state like dce_i2c_hw does before a transaction.
        const uint32_t ctrl = dcnNativeRead(dcnRegContext, RaphaelDcn::k315DioMemPwrCtrl);
        const uint32_t before = dcnNativeRead(dcnRegContext, RaphaelDcn::k315DioMemPwrStatus);
        dcnNativeWrite(dcnRegContext, RaphaelDcn::k315DioMemPwrCtrl, RaphaelDcn::wakeDioI2c(ctrl));
        uint32_t status = before, tries = 0;
        while ((status & RaphaelDcn::kDioI2cMemPwrState) != 0 && tries++ < 50) {
            IODelay(10);
            status = dcnNativeRead(dcnRegContext, RaphaelDcn::k315DioMemPwrStatus);
        }
        CRLOG("DCN: DIO I2C memory: CTRL %#x -> %#x, STATUS %#x -> %#x after %u polls",
              ctrl, RaphaelDcn::wakeDioI2c(ctrl), before, status, tries);
    }
    if (dcnNativeRead != nullptr) {
        CRLOG("DCN: I2C clock: MICROSECOND_TIME_BASE_DIV=%#x DC_I2C_DDC1_SPEED=%#x (host-i2c-speed=%u)",
              dcnNativeRead(dcnRegContext, RaphaelDcn::k315MicrosecondTimeBaseDiv),
              dcnNativeRead(dcnRegContext, RaphaelDcn::k315DcI2cDdc1Speed),
              (dcnMode & kDcnHostI2cSpeed) != 0);
    }
    CRLOG("DCN: dc_hardware_init done (trace-lines=%u dropped=%u unique=%zu)", dcnTraceLines,
          dcnDropped, dcnAccesses.used());
}

// DMUB command path (rgpudcn 256/512). Apple's dc_dmub_srv_cmd_queue/execute/wait_idle
// (0x1b06de/0x1b0756/0x1b0797) are replaced. With 256 alone every command is logged and
// reported successful; nothing is written. With 512 as well, VBIOS commands (type 128) are
// copied into the running firmware's inbox1 ring and INBOX1_WPTR is advanced; everything else
// is still only logged. The first timeout turns delivery off for the rest of the boot.
static mach_vm_address_t orgDcDmubQueue {}, orgDcDmubExecute {}, orgDcDmubWait {};
static uint32_t dmubWptr = 0, dmubCommands = 0, dmubDelivered = 0;
static bool dmubPending = false, dmubDeliverDead = false;

static bool dmubDeliverReady() {
    return (dcnMode & kDcnDmubDeliver) && !dmubDeliverDead && dcnNativeRead != nullptr &&
           dcnNativeWrite != nullptr && dcnRingBar != 0 && dcnRingSize >= 0x400 &&
           dcnRingSize <= 0x100000 && fbAperture() != nullptr;
}

static void wrapDcDmubQueue(void *dcDmub, const uint32_t *cmd) {
    (void)dcDmub;
    if (cmd == nullptr) return;
    const uint32_t header = cmd[0];
    const uint32_t type = header & 0xff, sub = (header >> 8) & 0xff, bytes = (header >> 24) & 0x3f;
    dmubCommands++;
    char line[200];
    size_t len = 0;
    line[0] = 0;
    for (unsigned d = 0; d < 16; d++) len += snprintf(line + len, sizeof(line) - len, " %08x", cmd[d]);
    // Raphael has four display pipes; DCN 3.02 code also gates a fifth.
    const bool deliver = type == 128 && !(sub == 3 && (cmd[1] & 0xff) >= 4) && dmubDeliverReady();
    CRLOG("DCN: DMUB cmd#%u type=%u sub=%u bytes=%u %s:%s", dmubCommands, type, sub, bytes,
          deliver ? "deliver" : "log-only", line);
    if (!deliver) return;
    auto volatile *fb = fbAperture();
    const uint32_t rptr = dcnNativeRead(dcnRegContext, 0x3697);         // DMCUB_INBOX1_RPTR
    if (!dmubPending) dmubWptr = dcnNativeRead(dcnRegContext, 0x3696);  // DMCUB_INBOX1_WPTR
    if ((dmubWptr + 64) % dcnRingSize == rptr) {
        CRLOG("DCN: DMUB ring full (wptr %#x rptr %#x); delivery disabled", dmubWptr, rptr);
        dmubDeliverDead = true;
        return;
    }
    for (unsigned d = 0; d < 16; d++) fb[(dcnRingBar + dmubWptr + 4 * d) / 4] = cmd[d];
    __sync_synchronize();
    dmubWptr = (dmubWptr + 64) % dcnRingSize;
    dmubPending = true;
}

static void wrapDcDmubExecute(void *dcDmub) {
    (void)dcDmub;
    if (!dmubPending || !dmubDeliverReady()) return;
    dcnNativeWrite(dcnRegContext, 0x3696, dmubWptr);                     // DMCUB_INBOX1_WPTR
}

static void wrapDcDmubWait(void *dcDmub) {
    (void)dcDmub;
    if (!dmubPending) return;
    dmubPending = false;
    if (!dmubDeliverReady()) return;
    uint32_t rptr = 0, waited = 0;
    for (; waited < 100000; waited += 10) {
        rptr = dcnNativeRead(dcnRegContext, 0x3697);
        if (rptr == dmubWptr) break;
        IODelay(10);
    }
    if (rptr == dmubWptr) {
        dmubDelivered++;
        CRLOG("DCN: DMUB delivered #%u, firmware consumed to %#x in %u us", dmubDelivered, rptr, waited);
        return;
    }
    dmubDeliverDead = true;
    CRLOG("DCN: DMUB TIMEOUT wptr %#x rptr %#x after %u us, CNTL=%#x SCRATCH0=%#x; delivery disabled",
          dmubWptr, rptr, waited, dcnNativeRead(dcnRegContext, 0x36b6),
          dcnNativeRead(dcnRegContext, 0x36a3));
}

static void installDcnRoutes(KernelPatcher &patcher, mach_vm_address_t addr, size_t size) {
    if (dcnMode == 0) return;
    struct Target {
        size_t offset; const uint8_t *prologue; size_t length; mach_vm_address_t wrapper;
        mach_vm_address_t *org; const char *name; bool wanted;
    };
    static const uint8_t regWait[]  = {0x55,0x48,0x89,0xe5,0x41,0x57,0x41,0x56,0x41,0x55,0x41,
                                       0x54,0x53,0x48,0x83,0xec,0x38,0x45,0x89,0xcd};
    static const uint8_t dcCreate[] = {0x55,0x48,0x89,0xe5,0x41,0x57,0x41,0x56,0x53,0x48,0x83,
                                       0xec,0x18,0x49,0x89,0xfe,0xbf,0x48,0xea,0x00};
    static const uint8_t hwInit[]   = {0x55,0x48,0x89,0xe5,0x41,0x57,0x41,0x56,0x41,0x55,0x41,
                                       0x54,0x53,0x48,0x83,0xec,0x28,0x48,0x89,0xfb};
    static const uint8_t dmubQueue[] = {0x55,0x48,0x89,0xe5,0x41,0x57,0x41,0x56,0x41,0x54,0x53,
                                        0x49,0x89,0xf6};
    static const uint8_t dmubExec[]  = {0x55,0x48,0x89,0xe5,0x41,0x56,0x53,0x48,0x89,0xfb,0x48,
                                        0x8b,0x3f,0x4c,0x8b,0x73,0x58};
    const Target targets[] = {
        {kOffDcnRegWait, regWait, sizeof(regWait),
         reinterpret_cast<mach_vm_address_t>(wrapDcnRegWait), &orgDcnRegWait, "generic_reg_wait",
         (dcnMode & kDcnTrace) != 0},
        {kOffDcCreate, dcCreate, sizeof(dcCreate),
         reinterpret_cast<mach_vm_address_t>(wrapDcCreate), &orgDcCreate, "dc_create", true},
        {kOffDcHardwareInit, hwInit, sizeof(hwInit),
         reinterpret_cast<mach_vm_address_t>(wrapDcHardwareInit), &orgDcHardwareInit,
         "dc_hardware_init", true},
        {kOffDcDmubQueue, dmubQueue, sizeof(dmubQueue),
         reinterpret_cast<mach_vm_address_t>(wrapDcDmubQueue), &orgDcDmubQueue,
         "dc_dmub_srv_cmd_queue", (dcnMode & kDcnDmubHook) != 0},
        {kOffDcDmubExecute, dmubExec, sizeof(dmubExec),
         reinterpret_cast<mach_vm_address_t>(wrapDcDmubExecute), &orgDcDmubExecute,
         "dc_dmub_srv_cmd_execute", (dcnMode & kDcnDmubHook) != 0},
        {kOffDcDmubWait, dmubExec, sizeof(dmubExec),
         reinterpret_cast<mach_vm_address_t>(wrapDcDmubWait), &orgDcDmubWait,
         "dc_dmub_srv_wait_idle", (dcnMode & kDcnDmubHook) != 0},
    };
    for (const auto &t : targets) {
        if (!t.wanted) continue;
        const bool matches = entryMatches(addr, size, t.offset, t.prologue, t.length);
        if (matches) *t.org = patcher.routeFunction(addr + t.offset, t.wrapper, true);
        CRLOG("DCN: route %s -> %s (prologue=%u org=%#llx)", t.name, *t.org ? "ok" : "FAILED",
              matches, *t.org);
        patcher.clearError();
    }
    if (!orgDcCreate && (dcnMode & (kDcnPool302 | kDcnTranslate | kDcnTrace))) {
        // No interposition, so no DMCUB fence: never select the DCN 3.02 pool.
        dcnMode &= ~(kDcnPool302 | kDcnTranslate | kDcnTrace);
        CRLOG("DCN: dc_create route missing; pool, translation and trace disabled");
    }
    if (!orgDcHardwareInit) dcnMode &= ~kDcnDmubGuard;
    if (!orgDcDmubQueue || !orgDcDmubExecute || !orgDcDmubWait) dcnMode &= ~(kDcnDmubHook | kDcnDmubDeliver);
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

// Read-only Metal image diagnostic state is declared before the kext callback
// because the route is installed from processKext; its implementation lives
// beside the existing texture-patch constants below.
static uint32_t texDiagEnabled = 0;
static IOLock *textureDiagCowLock = nullptr;
static mach_vm_address_t orgGetHardwareInfo = 0;
static mach_vm_address_t orgVideoGetHWInfo = 0;
using TextureDiagTaskInfo = kern_return_t (*)(task_t, task_flavor_t, task_info_t,
                                               mach_msg_type_number_t *);
using TextureDiagCurrentTask = task_t (*)();
using TextureDiagGetTaskMap = vm_map_t (*)(task_t);
using TextureDiagReadUser = kern_return_t (*)(vm_map_t, vm_map_address_t,
                                               void *, vm_map_size_t);
using TextureDiagSelfPid = int (*)();
using TextureDiagRegionRecurse = kern_return_t (*)(vm_map_t, mach_vm_address_t *,
                                                   mach_vm_size_t *, natural_t *,
                                                   vm_region_recurse_info_t,
                                                   mach_msg_type_number_t *);
using TextureDiagProtect = kern_return_t (*)(vm_map_t, mach_vm_address_t,
                                             mach_vm_size_t, boolean_t, vm_prot_t);
using TextureDiagWriteUser = kern_return_t (*)(vm_map_t, const void *,
                                                vm_map_address_t, vm_map_size_t);
struct TextureDiagReadContext { vm_map_t map; };
static TextureDiagTaskInfo textureDiagTaskInfo = nullptr;
static TextureDiagCurrentTask textureDiagCurrentTask = nullptr;
static TextureDiagGetTaskMap textureDiagGetTaskMap = nullptr;
static TextureDiagReadUser textureDiagReadUser = nullptr;
static TextureDiagSelfPid textureDiagSelfPid = nullptr;
// rgpuvd120=1: patch CoreDisplay's virtual-display refresh integer, WindowServer only.
static bool vd120Enabled = false;
using TextureDiagSelfName = void (*)(char *, int);
static TextureDiagSelfName textureDiagSelfName = nullptr;
static bool currentProcessIsWindowServer() {
    if (textureDiagSelfName == nullptr) return false;
    char name[32] {};
    textureDiagSelfName(name, sizeof(name));
    return strcmp(name, "WindowServer") == 0;
}
static TextureDiagRegionRecurse textureDiagRegionRecurse = nullptr;
static TextureDiagProtect textureDiagProtect = nullptr;
static TextureDiagWriteUser textureDiagWriteUser = nullptr;
static volatile uint32_t textureDiagLogCount = 0;
static constexpr size_t kOffGetHardwareInfo = 0xeca4; // AMDAccelDevice::getHardwareInfo [x6]
static constexpr uint8_t kGetHardwareInfoEntry[] = {
    0x55, 0x48, 0x89, 0xe5, 0x41, 0x57, 0x41, 0x56,
    0x41, 0x54, 0x53, 0x48, 0x85, 0xf6
};
static int wrapGetHardwareInfo(void *self, void *values);
static int wrapVideoGetHWInfo(void *self, void *values);

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
        installDcnRoutes(patcher, addr, sz);
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
        if (texDiagEnabled != 0 || vcnNoDpmEnabled || vd120Enabled) {
            textureDiagSelfName = reinterpret_cast<TextureDiagSelfName>(
                patcher.solveSymbol(KernelPatcher::KernelID, "_proc_selfname"));
            textureDiagTaskInfo = reinterpret_cast<TextureDiagTaskInfo>(
                patcher.solveSymbol(KernelPatcher::KernelID, "_task_info"));
            textureDiagCurrentTask = reinterpret_cast<TextureDiagCurrentTask>(
                patcher.solveSymbol(KernelPatcher::KernelID, "_current_task"));
            textureDiagGetTaskMap = reinterpret_cast<TextureDiagGetTaskMap>(
                patcher.solveSymbol(KernelPatcher::KernelID, "_get_task_map"));
            textureDiagReadUser = reinterpret_cast<TextureDiagReadUser>(
                patcher.solveSymbol(KernelPatcher::KernelID, "_vm_map_read_user"));
            textureDiagSelfPid = reinterpret_cast<TextureDiagSelfPid>(
                patcher.solveSymbol(KernelPatcher::KernelID, "_proc_selfpid"));
            textureDiagRegionRecurse = reinterpret_cast<TextureDiagRegionRecurse>(
                patcher.solveSymbol(KernelPatcher::KernelID, "_mach_vm_region_recurse"));
            textureDiagProtect = reinterpret_cast<TextureDiagProtect>(
                patcher.solveSymbol(KernelPatcher::KernelID, "_mach_vm_protect"));
            textureDiagWriteUser = reinterpret_cast<TextureDiagWriteUser>(
                patcher.solveSymbol(KernelPatcher::KernelID, "_vm_map_write_user"));
            const bool symbols = textureDiagTaskInfo && textureDiagCurrentTask &&
                                 textureDiagGetTaskMap && textureDiagReadUser;
            const bool entry = entryMatches(addr, sz, kOffGetHardwareInfo,
                                            kGetHardwareInfoEntry,
                                            sizeof(kGetHardwareInfoEntry));
            if (symbols && entry)
                orgGetHardwareInfo = patcher.routeFunction(
                    addr + kOffGetHardwareInfo,
                    reinterpret_cast<mach_vm_address_t>(wrapGetHardwareInfo), true);
            RLOG("XTDIAG: route=%s symbols=%u entry=%u taskinfo=%p current=%p map=%p read=%p pid=%p region=%p protect=%p write=%p",
                 orgGetHardwareInfo ? "ok" : "OFF", symbols, entry,
                 textureDiagTaskInfo, textureDiagCurrentTask,
                 textureDiagGetTaskMap, textureDiagReadUser, textureDiagSelfPid,
                 textureDiagRegionRecurse, textureDiagProtect, textureDiagWriteUser);
            patcher.clearError();
            if (vcnNoDpmEnabled) {
                // Preserve TEST RSI / JZ null-output refusal. Route only the
                // non-null entry at28935, before any stack modification. All
                // 16 displaced bytes are whole non-PC-relative instructions.
                static const uint8_t videoEntry[] = {
                    0x48,0x85,0xf6,0x0f,0x84,0xbb,0x01,0x00,0x00,
                    0x55,0x48,0x89,0xe5,0x41,0x57,0x41,0x56,0x53,0x50,
                    0x48,0x89,0xf3,0x49,0x89,0xfe
                };
                const bool videoGuard = entryMatches(addr, sz, 0x2892c,
                    videoEntry, sizeof(videoEntry));
                if (symbols && videoGuard)
                    orgVideoGetHWInfo = patcher.routeFunction(addr + 0x28935,
                        reinterpret_cast<mach_vm_address_t>(wrapVideoGetHWInfo), true);
                CRLOG("VCNDPM: video HWInfo route entry=%u routed=%u", videoGuard,
                      orgVideoGetHWInfo != 0);
                patcher.clearError();
            }
        }
        if (mask & XJ) {
            // 24G830's AMDGraphicsAccelerator::start failure cleanup branches
            // from 0x1eca to 0x1f50, where the uninitialised +0x1ea0 trace
            // object is dereferenced. Redirect that branch to the common
            // return path (0x1fd2) so power-up failure is reported cleanly.
            static const uint8_t find[] = {0x0f, 0x84, 0x80, 0x00, 0x00, 0x00};
            static const uint8_t replace[] = {0x0f, 0x84, 0x02, 0x01, 0x00, 0x00};
            KernelPatcher::LookupPatch lp {&kexts[KextX6000], find, replace,
                                           sizeof(find), 1};
            // The six-byte pattern occurs at a dozen sites in this X6000 build;
            // Lilu searches strictly before (start + maxSize - patchSize).
            // N+1 permits only the exact starting address; N permits no match.
            patcher.applyLookupPatch(&lp, reinterpret_cast<uint8_t *>(addr + 0x1eca),
                                     sizeof(find) + 1);
            RLOG("XJ: AMDGraphicsAccelerator::start failure cleanup patch -> %s",
                 patcher.getError() == KernelPatcher::Error::NoError ? "ok" : "FAILED");
            patcher.clearError();
        }
        if ((mask & XH) || recoveryLeaseConfigured) {
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
        if (allocationLogBudgetEnabled && !allocationLogInstalled) {
            // RIP-relative format + argument moves and native counter/false-return
            // tail are exact build guards. The CALL displacement is loader-relocated.
            static const uint8_t prefix[] = {
                0x48,0x8b,0x73,0x18,0x48,0x8b,0x8b,0xf0,0x00,0x00,0x00,
                0x48,0x83,0xc6,0x04,0x48,0x8d,0x3d,0x63,0x6e,0x0b,0x00,
                0x45,0x31,0xff,0x4c,0x89,0xf2,0x49,0x89,0xc0,0x31,0xc0};
            static const uint8_t tail[] = {
                0x48,0xff,0x83,0xd0,0x00,0x00,0x00,
                0x4c,0x89,0xbb,0xd8,0x00,0x00,0x00,
                0x4c,0x89,0xbb,0xe0,0x00,0x00,0x00,0x44,0x89,0xf8};
            const bool guard = entryMatches(addr, sz, 0x5334f, prefix, sizeof(prefix)) &&
                entryMatches(addr, sz, 0x53375, tail, sizeof(tail));
            uint8_t before[5] {}, after[5] {};
            bool installed = false;
            mach_vm_address_t target = 0, resolvedLogger = 0;
            bool reachable = false;
            const mach_vm_address_t expectedLogger = patcher.solveSymbol(
                KernelPatcher::KernelID, "_kprintf");
            patcher.clearError();
            if (guard && expectedLogger) {
                memcpy(before, reinterpret_cast<const void *>(addr + 0x53370), sizeof(before));
                int32_t originalDisplacement = 0;
                memcpy(&originalDisplacement, before + 1, sizeof(originalDisplacement));
                target = static_cast<mach_vm_address_t>(
                    static_cast<int64_t>(addr + 0x53375) + originalDisplacement);
                resolvedLogger = target;
                // The kernel collection binds this native CALL to an import island,
                // not directly to kprintf. Validate the single FF25 RIP-relative
                // jump and its pointer; never accept an arbitrary imported target.
                // The exact native CALL/prefix/tail identify this loader-owned stub.
                if (before[0] == 0xe8 && target != expectedLogger &&
                    target >= 0xffffff0000000000ULL && target <= UINT64_MAX - 6) {
                    uint8_t stub[6] {};
                    memcpy(stub, reinterpret_cast<const void *>(target), sizeof(stub));
                    if (stub[0] == 0xff && stub[1] == 0x25) {
                        int32_t displacement = 0;
                        memcpy(&displacement, stub + 2, sizeof(displacement));
                        const auto slot = static_cast<mach_vm_address_t>(
                            static_cast<int64_t>(target + 6) + displacement);
                        if (slot >= 0xffffff0000000000ULL && slot <= UINT64_MAX - 8)
                            memcpy(&resolvedLogger, reinterpret_cast<const void *>(slot), sizeof(resolvedLogger));
                    }
                }
                reachable = RaphaelAllocationLog::makeCall(addr + 0x53370,
                    reinterpret_cast<mach_vm_address_t>(budgetAllocationFailure), after);
                if (before[0] == 0xe8 && resolvedLogger == expectedLogger && reachable) {
                    originalAllocationLogger = target;
                    KernelPatcher::LookupPatch lp {&kexts[KextX6000], before, after, sizeof(before), 1};
                    patcher.applyLookupPatch(&lp, reinterpret_cast<uint8_t *>(addr + 0x53370), sizeof(before) + 1);
                    installed = patcher.getError() == KernelPatcher::Error::NoError &&
                        entryMatches(addr, sz, 0x53370, after, sizeof(after));
                }
            }
            allocationLogInstalled = installed;
            CRLOG("ALLOCLOG: guarded=%u installed=%u first=8 every=1024 original=%#llx "
                  "target=%#llx resolved=%#llx expected=%#llx reachable=%u",
                  guard, installed, originalAllocationLogger, target, resolvedLogger,
                  expectedLogger, reachable);
            patcher.clearError();
        }
        if (vcnDpgEnabled) {
            if (vcnNoDpmEnabled) {
                static const uint8_t newContextEntry[] = {
                    0x55,0x48,0x89,0xe5,0x41,0x57,0x41,0x56,0x41,0x55,0x41,0x54,0x53,0x50
                };
                const bool newGuard = entryMatches(addr, sz, 0x49292,
                    newContextEntry, sizeof(newContextEntry));
                if (newGuard) orgVcnNewContext = patcher.routeFunction(addr + 0x49292,
                    reinterpret_cast<mach_vm_address_t>(wrapVcnNewContext), true);
                CRLOG("VCNCTX: route VideoNewContext entry=%u routed=%u", newGuard,
                      orgVcnNewContext != 0);
                patcher.clearError();
            }
            // Every footprint ends at an instruction boundary and contains no
            // branch, call, or RIP-relative instruction. Preserve native ABI.
            static const uint8_t guardCreateContext[] = {0x55,0x48,0x89,0xe5,0x41,0x57,0x41,0x56,0x41,0x55,0x41,0x54,0x53,0x50};
            const bool matchCreateContext = entryMatches(addr, sz, 0x21ba0, guardCreateContext, sizeof(guardCreateContext));
            if (matchCreateContext) orgVcnCreateContext = patcher.routeFunction(addr + 0x21ba0,
                reinterpret_cast<mach_vm_address_t>(wrapVcnCreateContext), true);
            CRLOG("VCNCTX: route CreateContext entry=%u routed=%u", matchCreateContext, orgVcnCreateContext != 0);
            patcher.clearError();
            static const uint8_t guardRequestCap[] = {0x55,0x48,0x89,0xe5,0x41,0x57,0x41,0x56,0x41,0x54,0x53,0x45,0x89,0xc7};
            const bool matchRequestCap = entryMatches(addr, sz, 0x89508, guardRequestCap, sizeof(guardRequestCap));
            if (matchRequestCap) orgVcnRequestCap = patcher.routeFunction(addr + 0x89508,
                reinterpret_cast<mach_vm_address_t>(wrapVcnRequestCap), true);
            CRLOG("VCNCTX: route RequestCap entry=%u routed=%u", matchRequestCap, orgVcnRequestCap != 0);
            patcher.clearError();
            static const uint8_t guardStartEngine[] = {0x55,0x48,0x89,0xe5,0x41,0x57,0x41,0x56,0x41,0x54,0x53,0x48,0x85,0xf6};
            const bool matchStartEngine = entryMatches(addr, sz, 0x49632, guardStartEngine, sizeof(guardStartEngine));
            if (matchStartEngine) orgVcnStartEngine = patcher.routeFunction(addr + 0x49632,
                reinterpret_cast<mach_vm_address_t>(wrapVcnStartEngine), true);
            CRLOG("VCNCTX: route StartEngine entry=%u routed=%u", matchStartEngine, orgVcnStartEngine != 0);
            patcher.clearError();
            static const uint8_t guardSendPM[] = {0x55,0x48,0x89,0xe5,0x41,0x57,0x41,0x56,0x53,0x50,0x41,0xbe,0xd7,0x02,0x00,0xe0};
            const bool matchSendPM = entryMatches(addr, sz, 0x7056, guardSendPM, sizeof(guardSendPM));
            if (matchSendPM) orgVcnSendPM = patcher.routeFunction(addr + 0x7056,
                reinterpret_cast<mach_vm_address_t>(wrapVcnSendPM), true);
            CRLOG("VCNCTX: route SendPM entry=%u routed=%u", matchSendPM, orgVcnSendPM != 0);
            patcher.clearError();
        }

        if (vmmProbeMode != 0 || memProbeMode != 0 || ptbFixMode != 0 ||
            vmRootFixEnabled || recoveryLeaseConfigured) {
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
            if (vmRootFixMode >= 2 && vmRootFixMode <= 3) {
                // Complete displaced spans of 14 and 15 bytes with no branch or
                // RIP-relative operand; getPDEValue's first jne begins at +14.
                static const uint8_t pdeEntry[] = {0x55, 0x48, 0x89, 0xe5, 0xff, 0xc6,
                    0x8b, 0x87, 0x34, 0x0b, 0x00, 0x00, 0x39, 0xc6};
                static const uint8_t pteEntry[] = {0x55, 0x48, 0x89, 0xe5, 0x89, 0xc8,
                    0xc1, 0xe8, 0x02, 0x83, 0xe0, 0x02, 0x41, 0x89, 0xc9};
                const bool pdeMatches = entryMatches(addr, sz, kOffVmmGetPde, pdeEntry,
                                                     sizeof(pdeEntry));
                if (pdeMatches)
                    orgVmmGetPde = patcher.routeFunction(addr + kOffVmmGetPde,
                        reinterpret_cast<mach_vm_address_t>(wrapVmmGetPde), true);
                CRLOG("VM: route AMDGFX10VMM::getPDEValue -> %s (entry=%u org=0x%llx)",
                      orgVmmGetPde ? "ok" : "FAILED", pdeMatches, orgVmmGetPde);
                patcher.clearError();
                if (vmRootFixMode == 3) {
                    const bool pteMatches = entryMatches(addr, sz, kOffVmmGetPte,
                                                         pteEntry, sizeof(pteEntry));
                    if (pteMatches)
                        orgVmmGetPte = patcher.routeFunction(addr + kOffVmmGetPte,
                            reinterpret_cast<mach_vm_address_t>(wrapVmmGetPte), true);
                    CRLOG("VM: route AMDGFX10VMM::getPTEValue -> %s (entry=%u org=0x%llx)",
                          orgVmmGetPte ? "ok" : "FAILED", pteMatches, orgVmmGetPte);
                    patcher.clearError();
                }
            }
            if (vmRootFixMode >= 4) {
                // Complete first 17 bytes: frame setup, callee-saved pushes and
                // stack allocation. No branch or RIP-relative operand occurs in
                // this guarded span in the pinned 24G830 X6000 image.
                static const uint8_t updateEntry[] = {
                    0x55, 0x48, 0x89, 0xe5, 0x41, 0x57, 0x41, 0x56, 0x41,
                    0x55, 0x41, 0x54, 0x53, 0x48, 0x83, 0xec, 0x48};
                const bool updateMatches = entryMatches(
                    addr, sz, kOffVmmUpdateEntries, updateEntry,
                    sizeof(updateEntry));
                if (updateMatches)
                    orgVmmUpdateEntries = patcher.routeFunction(
                        addr + kOffVmmUpdateEntries,
                        reinterpret_cast<mach_vm_address_t>(wrapVmmUpdateEntries), true);
                CRLOG("VM: route AMDHWVMContext::updateContiguousPTEsWithDMAUsingAddr "
                      "-> %s (entry=%u org=0x%llx)",
                      orgVmmUpdateEntries ? "ok" : "FAILED", updateMatches,
                      orgVmmUpdateEntries);
                patcher.clearError();
            }
            if (vmRootFixMode == 5) {
                static const uint8_t mapProcessEntry[] = {
                    0x55, 0x48, 0x89, 0xe5, 0x41, 0x57, 0x41, 0x56,
                    0x41, 0x54, 0x53, 0x49, 0x89, 0xcf, 0x49, 0x89, 0xd4};
                const bool mapProcessMatches = entryMatches(
                    addr, sz, kOffFillMapProcess, mapProcessEntry,
                    sizeof(mapProcessEntry));
                if (mapProcessMatches)
                    orgFillMapProcess = patcher.routeFunction(
                        addr + kOffFillMapProcess,
                        reinterpret_cast<mach_vm_address_t>(wrapFillMapProcess), true);
                CRLOG("VM: route AMDGFX10HIQHWChannel::fillMapProcessPacket -> %s "
                      "(entry=%u org=0x%llx)",
                      orgFillMapProcess ? "ok" : "FAILED", mapProcessMatches,
                      orgFillMapProcess);
                patcher.clearError();
            }
            if (ptbFixMode != 2) {
                orgVmmProgInv = patcher.routeFunction(addr + kOffVmmProgInv,
                                reinterpret_cast<mach_vm_address_t>(wrapVmmProgInv), true);
                RLOG("route AMDGFX10VMM::programAndInvalidateVM -> %s (org=0x%llx)",
                     orgVmmProgInv ? "ok" : "FAILED", orgVmmProgInv);
                patcher.clearError();
            }
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
            static const uint8_t backingAllocEntry[] = {0x55, 0x48, 0x89, 0xe5, 0x41, 0x57, 0x41, 0x56, 0x41, 0x55, 0x41, 0x54, 0x53, 0x48, 0x83, 0xec, 0x18};
            static const uint8_t commitEntry[] = {0x55, 0x48, 0x89, 0xe5, 0x41,
                0x57, 0x41, 0x56, 0x41, 0x55, 0x41, 0x54, 0x53, 0x50, 0x48,
                0x89, 0xfb};
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
                             submitEntry, sizeof(submitEntry)) &&
                entryMatches(addr, sz, kOffBackingAllocPhysical,
                             backingAllocEntry, sizeof(backingAllocEntry)) &&
                entryMatches(addr, sz, kOffCommitIntoGPUPageTable,
                             commitEntry, sizeof(commitEntry));
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
                    {kOffBackingAllocPhysical, &orgBackingAllocPhysical,
                     reinterpret_cast<void *>(wrapBackingAllocPhysical),
                     "AMDAccelVidMemory::allocPhysical"},
                    {kOffCommitIntoGPUPageTable, &orgCommitIntoGPUPageTable,
                     reinterpret_cast<void *>(wrapCommitIntoGPUPageTable),
                     "AMDAccelMemoryMap::commitIntoGPUPageTable"},
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
                orgSubmitBuffer && orgBackingAllocPhysical && orgCommitIntoGPUPageTable;
            __atomic_store_n(&submissionTraceRoutesReady, ready, __ATOMIC_RELEASE);
            CRLOG("SUB: routes=%s count=7 entries-match=%u capture=%s",
                  ready ? "ok" : "FAILED", entriesMatch, ready ? "armed" : "disabled");
        }
        if (hangDumpMode == 1) {
            // Complete instructions: the report prologue through sub rsp,0x38, and the
            // map/unmap entries through mov rbx,rdx (called, not routed).
            static const uint8_t reportEntry[] = {0x55, 0x48, 0x89, 0xe5, 0x41, 0x57,
                0x41, 0x56, 0x41, 0x55, 0x41, 0x54, 0x53, 0x48, 0x83, 0xec, 0x38};
            static const uint8_t mapCbEntry[] = {0x85, 0xf6, 0x74, 0x74, 0x55, 0x48, 0x89,
                0xe5, 0x41, 0x57, 0x41, 0x56, 0x41, 0x55, 0x41, 0x54, 0x53, 0x50, 0x48, 0x89,
                0xd3};
            static const uint8_t unmapCbEntry[] = {0x85, 0xf6, 0x74, 0x64, 0x55, 0x48, 0x89,
                0xe5, 0x41, 0x57, 0x41, 0x56, 0x41, 0x55, 0x41, 0x54, 0x53, 0x50, 0x48, 0x89,
                0xd3};
            const bool reportMatches =
                entryMatches(addr, sz, kOffPendingCommandReport, reportEntry,
                             sizeof(reportEntry)) &&
                entryMatches(addr, sz, kOffMapCmdBuffers, mapCbEntry, sizeof(mapCbEntry)) &&
                entryMatches(addr, sz, kOffUnmapCmdBuffers, unmapCbEntry,
                             sizeof(unmapCbEntry));
            if (reportMatches) {
                hangMapCmdBuffers = addr + kOffMapCmdBuffers;
                hangUnmapCmdBuffers = addr + kOffUnmapCmdBuffers;
                orgPendingCommandReport = patcher.routeFunction(
                    addr + kOffPendingCommandReport,
                    reinterpret_cast<mach_vm_address_t>(wrapPendingCommandReport), true);
                patcher.clearError();
            }
            RLOG("XB: pending command report route entries-match=%u route=%s (org=%#llx)",
                 reportMatches, orgPendingCommandReport ? "ok" : "FAILED",
                 orgPendingCommandReport);
        }
        if (addrConfigMode != 0 || hwCapClearMask != 0 || sdmaAddrConfigMode != 0) {
            // push rbp; mov rbp,rsp; push r15; push r14; push r12; push rbx; sub rsp,0x90
            static const uint8_t alignInitEntry[] = {0x55, 0x48, 0x89, 0xe5, 0x41, 0x57,
                0x41, 0x56, 0x41, 0x54, 0x53, 0x48, 0x81, 0xec, 0x90, 0x00, 0x00, 0x00};
            const bool alignMatches = entryMatches(addr, sz, kOffAlignManager2Init,
                                                   alignInitEntry, sizeof(alignInitEntry));
            if (alignMatches) {
                orgAlignManager2Init = patcher.routeFunction(
                    addr + kOffAlignManager2Init,
                    reinterpret_cast<mach_vm_address_t>(wrapAlignManager2Init), true);
                patcher.clearError();
            }
            RLOG("XA: AMDHWAlignManager2::init route entries-match=%u route=%s (org=%#llx)",
                 alignMatches, orgAlignManager2Init ? "ok" : "FAILED", orgAlignManager2Init);
        }
        if (swizzleLogMode != 0) {
            // push rbp; mov rbp,rsp; push r14; push rbx; sub rsp,0x70; mov r14,rdi; xor ebx,ebx
            static const uint8_t preferredEntry[] = {0x55, 0x48, 0x89, 0xe5, 0x41, 0x56, 0x53,
                0x48, 0x83, 0xec, 0x70, 0x49, 0x89, 0xfe, 0x31, 0xdb};
            const bool preferredMatches = entryMatches(addr, sz, kOffPreferredSwizzleMode2,
                                                       preferredEntry, sizeof(preferredEntry));
            if (preferredMatches) {
                orgPreferredSwizzleMode2 = patcher.routeFunction(
                    addr + kOffPreferredSwizzleMode2,
                    reinterpret_cast<mach_vm_address_t>(wrapPreferredSwizzleMode2), true);
                patcher.clearError();
            }
            RLOG("XS: getPreferredSwizzleMode2 route entries-match=%u route=%s (org=%#llx)",
                 preferredMatches, orgPreferredSwizzleMode2 ? "ok" : "FAILED",
                 orgPreferredSwizzleMode2);
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

// rgpunotexxor: clear enableTexturePipeBankXor (AMD_DeviceSettings bit 27) in Apple's
// AMDRadeonX6000MTLDriver so Metal computes pipeBankXor = 0 for textures across the render,
// sample and blit paths. This fixes MTLStorageModeManaged tiled<->linear texture copies on
// Raphael (4 pipes / config 0x42): the userspace tiled blit and the userspace synchronize
// (metadataRetile) otherwise disagree by one pipe-bank-xor bit at 64-pixel granularity.
// Both agents and probe v7 confirmed this is a userspace-only lever with no kernel input.
// The driver ships only inside the dyld shared cache on Sequoia, so we patch it in every
// Legacy Lilu fileless delivery is inactive on Sequoia; the opt-in current-task COW
// diagnostic below is the experimental delivery path and revalidates live bytes.
static uint32_t texPipeBankXorDisable = 0;

static bool textureDiagRead(void *opaque, uint64_t address, void *out, size_t size) {
    auto *context = static_cast<TextureDiagReadContext *>(opaque);
    if (context == nullptr || context->map == nullptr || textureDiagReadUser == nullptr ||
        out == nullptr || size == 0 || address == 0 || address > 0x800000000000ULL ||
        size > 0x800000000000ULL - address)
        return false;
    return textureDiagReadUser(context->map, address, out, size) == KERN_SUCCESS;
}

// Every exact userspace target this kext patches through the current-task COW
// path advertises different behavior once patched: kMetal/kFeedback are gated
// by rgputexdiag=2, kVcnDpm and kVcnPreset by the vcnNoDpm capability-alignment
// gate (kVcnPreset additionally requires rgpuvcnpreset=1). The kind selects both
// the gate and the log line; the underlying guard/COW mechanics are identical.
enum class DiagTargetKind { kMetal, kFeedback, kVcnDpm, kVcnPreset, kVirtualDisplay120 };


static bool diagTargetGateOpen(DiagTargetKind kind) {
    switch (kind) {
    case DiagTargetKind::kVcnDpm:
        return vcnNoDpmEnabled && __atomic_load_n(&ppCompatibilityBypassed, __ATOMIC_ACQUIRE);
    case DiagTargetKind::kVcnPreset:
        return vcnPresetEnabled && vcnNoDpmEnabled &&
               __atomic_load_n(&ppCompatibilityBypassed, __ATOMIC_ACQUIRE);
    case DiagTargetKind::kVirtualDisplay120:
        return vd120Enabled && currentProcessIsWindowServer();
    case DiagTargetKind::kMetal:
    case DiagTargetKind::kFeedback:
    default:
        return texDiagEnabled == 2;
    }
}

// Retain the complete instruction guard for every exact userspace target,
// task-private copy-on-write mapping, post-write verification and RX restoration.
// The VCN targets advertise unavailable Apple DPM; native setupPowerState owns its
// no-DPM cleanup, while wrapVcnInitialize retains actual Raphael SMU power-up.
static void textureDiagCow(TextureDiagReadContext *context, int pid,
                           const RaphaelTextureDiag::Result &result,
                           mach_vm_address_t regionStart, mach_vm_size_t regionSize,
                           vm_prot_t regionProt, vm_prot_t regionMax, bool emit,
                           const RaphaelTextureDiag::Target &target, DiagTargetKind kind,
                           const char *label) {
    if (!diagTargetGateOpen(kind) || context == nullptr || context->map == nullptr ||
        textureDiagCowLock == nullptr || textureDiagProtect == nullptr ||
        textureDiagWriteUser == nullptr || pid <= 0 || !result.found || result.alreadyPatched ||
        result.status != RaphaelTextureDiag::Ok || !result.instructionMatch ||
        !result.uuidMatch || !result.pathTerminated)
        return;
    const mach_vm_address_t page = result.instructionAddress & ~mach_vm_address_t(0xfff);
    if (regionStart > page || regionSize < 0x1000 ||
        page - regionStart > regionSize - 0x1000 ||
        (regionProt & (VM_PROT_READ | VM_PROT_EXECUTE)) !=
            (VM_PROT_READ | VM_PROT_EXECUTE) || (regionProt & VM_PROT_WRITE) != 0 ||
        (regionMax & (VM_PROT_READ | VM_PROT_EXECUTE)) !=
            (VM_PROT_READ | VM_PROT_EXECUTE))
        return;
    if (target.instructionSize < 6 ||
        target.instructionSize > RaphaelTextureDiag::kMaxInstructionSize ||
        (result.instructionAddress & 0xfff) > 0x1000 - target.instructionSize) return;
    uint8_t before[RaphaelTextureDiag::kMaxInstructionSize] {};
    kern_return_t readBefore = textureDiagRead(context, result.instructionAddress,
                                                before, target.instructionSize) ? KERN_SUCCESS : KERN_FAILURE;
    if (readBefore != KERN_SUCCESS || memcmp(before, target.instruction, target.instructionSize) != 0) {
        return;
    }
    size_t patchOffset = 0, patchSize = 0;
    if (!RaphaelTextureDiag::patchSpan(target, patchOffset, patchSize)) return;
    kern_return_t protectRc = textureDiagProtect(context->map, page, 0x1000, FALSE,
                                                   VM_PROT_READ | VM_PROT_WRITE | VM_PROT_COPY);
    kern_return_t writeRc = KERN_FAILURE;
    kern_return_t restoreRc = KERN_FAILURE;
    kern_return_t verifyRc = KERN_FAILURE;
    if (protectRc == KERN_SUCCESS) {
        uint8_t afterProtect[sizeof(before)] {};
        const bool stillOriginal = textureDiagRead(context, result.instructionAddress,
                                                    afterProtect, target.instructionSize) &&
            memcmp(afterProtect, target.instruction, target.instructionSize) == 0;
        if (stillOriginal)
            writeRc = textureDiagWriteUser(context->map, target.patchedInstruction + patchOffset,
                                           result.instructionAddress + patchOffset, patchSize);
    }
    // The protection API can fail after partial map work: always restore.
    restoreRc = textureDiagProtect(context->map, page, 0x1000, FALSE, regionProt);
    {
        uint8_t after[sizeof(before)] {};
        const bool readAfter = textureDiagRead(context, result.instructionAddress,
                                                after, target.instructionSize);
        verifyRc = (readAfter &&
                    memcmp(after, target.patchedInstruction, target.instructionSize) == 0) ?
            KERN_SUCCESS : KERN_FAILURE;
    }
    const bool cowSucceeded = protectRc == KERN_SUCCESS && writeRc == KERN_SUCCESS &&
                              restoreRc == KERN_SUCCESS && verifyRc == KERN_SUCCESS;
    if (kind == DiagTargetKind::kFeedback)
        SAMPLED_CRLOG(feedbackCowRecordBudget, cowSucceeded, "FBEXPAND: COW pid=%d addr=%#llx p=%d w=%d r=%d v=%d", pid,
              result.instructionAddress, protectRc, writeRc, restoreRc, verifyRc);
    if (kind == DiagTargetKind::kVcnDpm)
        SAMPLED_CRLOG(vcnCowRecordBudget, cowSucceeded, "VCNDPM: COW pid=%d addr=%#llx p=%d w=%d r=%d v=%d", pid,
              result.instructionAddress, protectRc, writeRc, restoreRc, verifyRc);
    if (kind == DiagTargetKind::kVirtualDisplay120)
        CRLOG("VD120: COW pid=%d addr=%#llx p=%d w=%d r=%d v=%d", pid,
              result.instructionAddress, protectRc, writeRc, restoreRc, verifyRc);
    if (kind == DiagTargetKind::kVcnPreset)
        SAMPLED_CRLOG(vcnPresetCowRecordBudget, cowSucceeded,
              "VCNPRESET: COW target=%s pid=%d addr=%#llx p=%d w=%d r=%d v=%d", label, pid,
              result.instructionAddress, protectRc, writeRc, restoreRc, verifyRc);
    if (restoreRc != KERN_SUCCESS)
        CRLOG("XTCOW pid=%d p=%d w=%d r=%d v=%d unsafe", pid, protectRc, writeRc,
              restoreRc, verifyRc);
    else if (emit || protectRc != KERN_SUCCESS || writeRc != KERN_SUCCESS || verifyRc != KERN_SUCCESS)
        RLOG("XTCOW pid=%d p=%d w=%d r=%d v=%d", pid, protectRc, writeRc,
             restoreRc, verifyRc);
}

namespace {
struct DiagTargetEntry {
    const RaphaelTextureDiag::Target *target;
    DiagTargetKind kind;
    const char *label; // only used for the VCNPRESET image/COW log lines
};
// Table order matches the historical targetIndex 0/1/2 exactly for the first
// three entries (Metal texture, VCN DPM, texture feedback); the three VCN
// preset sites are appended, sharing kVcnDpmTarget's image identity.
const DiagTargetEntry kDiagTargets[] = {
    {&RaphaelTextureDiag::kTextureTarget, DiagTargetKind::kMetal, nullptr},
    {&RaphaelTextureDiag::kVcnDpmTarget, DiagTargetKind::kVcnDpm, nullptr},
    {&RaphaelTextureDiag::kFeedbackTarget, DiagTargetKind::kFeedback, nullptr},
    {&RaphaelTextureDiag::kVcnPresetValueTarget, DiagTargetKind::kVcnPreset, "preset-value"},
    {&RaphaelTextureDiag::kVcnPresetHevcGateTarget, DiagTargetKind::kVcnPreset, "hevc-gate"},
    {&RaphaelTextureDiag::kVcnPresetAvcGateTarget, DiagTargetKind::kVcnPreset, "avc-gate"},
    {&RaphaelTextureDiag::kVirtualDisplayRefreshTarget, DiagTargetKind::kVirtualDisplay120, "coredisplay-refresh"},
};
} // namespace

static void applyCurrentTaskImagePatches(bool includeMetal) {
    if (texDiagEnabled != 0 || vcnNoDpmEnabled || vd120Enabled) {
        const bool emit = __atomic_fetch_add(&textureDiagLogCount, 1u,
                                             __ATOMIC_RELAXED) < 64;
        const bool cowLocked = (texDiagEnabled == 2 || vcnNoDpmEnabled || vcnPresetEnabled ||
                                vd120Enabled) &&
                               textureDiagCowLock != nullptr;
        if (cowLocked) IOLockLock(textureDiagCowLock);
        task_t task = textureDiagCurrentTask ? textureDiagCurrentTask() : nullptr;
        const int pid = textureDiagSelfPid ? textureDiagSelfPid() : -1;
        vm_map_t map = (task && textureDiagGetTaskMap) ? textureDiagGetTaskMap(task) : nullptr;
        TextureDiagReadContext readContext {map};
        task_dyld_info_data_t dyld {};
        mach_msg_type_number_t count = TASK_DYLD_INFO_COUNT;
        kern_return_t taskRc = (task && textureDiagTaskInfo) ?
            textureDiagTaskInfo(task, TASK_DYLD_INFO,
                                reinterpret_cast<task_info_t>(&dyld), &count) : KERN_FAILURE;
        for (const auto &entry : kDiagTargets) {
            const bool vcnLike = entry.kind == DiagTargetKind::kVcnDpm ||
                                 entry.kind == DiagTargetKind::kVcnPreset ||
                                 entry.kind == DiagTargetKind::kVirtualDisplay120;
            if (vcnLike ? !diagTargetGateOpen(entry.kind) : (!includeMetal || texDiagEnabled == 0))
                continue;
            const auto &target = *entry.target;
            RaphaelTextureDiag::Result result {};
            if (taskRc == KERN_SUCCESS && count >= TASK_DYLD_INFO_COUNT &&
                dyld.all_image_info_size >= 16 && map != nullptr)
                result = RaphaelTextureDiag::inspect(textureDiagRead, &readContext,
                                                      dyld.all_image_info_addr,
                                                      dyld.all_image_info_format, target);
            kern_return_t regionRc = KERN_FAILURE;
            mach_vm_address_t regionStart = result.instructionAddress;
            mach_vm_size_t regionSize = 0;
            vm_prot_t regionProt = VM_PROT_NONE, regionMax = VM_PROT_NONE;
            boolean_t regionSubmap = FALSE;
            if (result.instructionAddress != 0 && map != nullptr && textureDiagRegionRecurse) {
                natural_t depth = 0;
                for (unsigned level = 0; level <= 8; ++level) {
                    vm_region_submap_info_data_64_t info {};
                    mach_msg_type_number_t infoCount = VM_REGION_SUBMAP_INFO_COUNT_64;
                    regionStart = result.instructionAddress;
                    regionSize = 0;
                    regionRc = textureDiagRegionRecurse(
                        map, &regionStart, &regionSize, &depth,
                        reinterpret_cast<vm_region_recurse_info_t>(&info), &infoCount);
                    if (regionRc == KERN_SUCCESS && infoCount < VM_REGION_SUBMAP_INFO_COUNT_64)
                        regionRc = KERN_FAILURE;
                    regionProt = info.protection;
                    regionMax = info.max_protection;
                    regionSubmap = info.is_submap;
                    if (regionRc != KERN_SUCCESS || !info.is_submap) break;
                    ++depth;
                }
            }
            if (entry.kind == DiagTargetKind::kVcnDpm && (emit || result.found)) {
                // Absent images and already-patched processes are routine queries,
                // not lifecycle evidence. A found but invalid target remains critical.
                const bool invalidTarget = result.found && result.status != RaphaelTextureDiag::Ok;
                diagAppend(invalidTarget,
                           "VCNDPM: image pid=%d st=%u uuid=%u bytes=%u patched=%u addr=%#llx",
                           pid, result.status, result.uuidMatch, result.instructionMatch,
                           result.alreadyPatched, result.instructionAddress);
                SYSLOG("rgpu", "VCNDPM: image pid=%d st=%u uuid=%u bytes=%u patched=%u addr=%#llx",
                       pid, result.status, result.uuidMatch, result.instructionMatch,
                       result.alreadyPatched, result.instructionAddress);
            }
            static volatile uint32_t vd120ImageLogs = 0;
            if (entry.kind == DiagTargetKind::kVirtualDisplay120 &&
                __atomic_fetch_add(&vd120ImageLogs, 1u, __ATOMIC_RELAXED) < 6)
                CRLOG("VD120: image pid=%d st=%u uuid=%u bytes=%u patched=%u addr=%#llx",
                      pid, result.status, result.uuidMatch, result.instructionMatch,
                      result.alreadyPatched, result.instructionAddress);
            if (entry.kind == DiagTargetKind::kVcnPreset && (emit || result.found)) {
                const bool invalidTarget = result.found && result.status != RaphaelTextureDiag::Ok;
                diagAppend(invalidTarget,
                           "VCNPRESET: image target=%s pid=%d st=%u uuid=%u bytes=%u patched=%u addr=%#llx",
                           entry.label, pid, result.status, result.uuidMatch, result.instructionMatch,
                           result.alreadyPatched, result.instructionAddress);
                SYSLOG("rgpu", "VCNPRESET: image target=%s pid=%d st=%u uuid=%u bytes=%u patched=%u addr=%#llx",
                       entry.label, pid, result.status, result.uuidMatch, result.instructionMatch,
                       result.alreadyPatched, result.instructionAddress);
            }
            if (!vcnLike && emit) RLOG("XTDIAG pid=%d task=%p ti=%d fmt=%d images=%u n=%u st=%u uuid=%u path=%u "
                 "text=%#llx instr=%#llx bytes=%u patched=%u",
                 pid, task, taskRc, dyld.all_image_info_format, result.imageCount, result.inspected,
                 result.status, result.uuidMatch, result.pathTerminated,
                 result.textBase, result.instructionAddress, result.instructionMatch, result.alreadyPatched);
            if (emit) RLOG("XTREG pid=%d rc=%d start=%#llx size=%#llx prot=%#x max=%#x sub=%u",
                           pid, regionRc, regionStart, regionSize, regionProt, regionMax,
                           regionSubmap);
            if (regionRc == KERN_SUCCESS && !regionSubmap && result.status == RaphaelTextureDiag::Ok &&
                result.instructionMatch && result.uuidMatch && result.pathTerminated)
                textureDiagCow(&readContext, pid, result, regionStart, regionSize,
                               regionProt, regionMax, emit, target, entry.kind, entry.label);
        }
        if (cowLocked) IOLockUnlock(textureDiagCowLock);
    }
}

static int wrapVideoGetHWInfo(void *self, void *values) {
    applyCurrentTaskImagePatches(false);
    using GetHWInfo = int (*)(void *, void *);
    return orgVideoGetHWInfo ? reinterpret_cast<GetHWInfo>(orgVideoGetHWInfo)(self, values)
                            : KERN_FAILURE;
}

static int wrapGetHardwareInfo(void *self, void *values) {
    applyCurrentTaskImagePatches(true);
    using GetHardwareInfo = int (*)(void *, void *);
    return orgGetHardwareInfo ? reinterpret_cast<GetHardwareInfo>(orgGetHardwareInfo)(self, values)
                               : KERN_FAILURE;
}

static const char kMtlDriverPath[] =
    "/System/Library/Extensions/AMDRadeonX6000MTLDriver.bundle/Contents/MacOS/AMDRadeonX6000MTLDriver";
// movabs rax, 0x1ff700000  ->  movabs rax, 0x1f7700000  (clears bit 27); site is unique.
static const uint8_t kMtlTexXorFind[10]    = { 0x48, 0xb8, 0x00, 0x00, 0x70, 0xff, 0x01, 0x00, 0x00, 0x00 };
static const uint8_t kMtlTexXorReplace[10] = { 0x48, 0xb8, 0x00, 0x00, 0x70, 0xf7, 0x01, 0x00, 0x00, 0x00 };
static const vm_address_t kMtlTexXorSegOff[1] = { 0x13a7e1 }; // offset within the driver __TEXT segment
// Unslid __TEXT base/size of AMDRadeonX6000MTLDriver in the KDK 24G830 shared cache. Supplying
// these lets Lilu patch the shared cache without the dyld .map (absent/split on Sequoia); the
// per-process patcher re-verifies the live bytes against the find pattern, so a stale base is
// a safe no-op.
static const vm_address_t kMtlTexXorTextBase = 0x7ffb08bf3000ULL;
static const vm_address_t kMtlTexXorTextSize = 0x5029aeULL;
static UserPatcher::BinaryModPatch mtlTexXorPatch {
    CPU_TYPE_X86_64,
    0,                                        // flags
    kMtlTexXorFind,
    kMtlTexXorReplace,
    sizeof(kMtlTexXorFind),
    0,                                        // skip
    1,                                        // count (unique site)
    UserPatcher::FileSegment::SegmentTextText,
    1                                         // section: non-zero enables the patch
};
static UserPatcher::BinaryModInfo mtlTexXorMod {
    kMtlDriverPath, &mtlTexXorPatch, 1, 0, 0, 0, 0, kMtlTexXorSegOff,
    kMtlTexXorTextBase, kMtlTexXorTextSize
};

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
    uint32_t vmFaultDiag = 0;
    uint32_t mmhubFix = 0;
    uint32_t allocationLogBudget = 0;
    allocationLogBudgetEnabled = PE_parse_boot_argn("rgpualloclog", &allocationLogBudget,
        sizeof(allocationLogBudget)) && allocationLogBudget == 1;
    uint32_t vcnReset = 0;
    vcnResetEnabled = PE_parse_boot_argn("rgpuvcnreset", &vcnReset, sizeof(vcnReset)) && vcnReset == 1;
    uint32_t vcnDpg = 0;
    vcnDpgEnabled = PE_parse_boot_argn("rgpuvcndpg", &vcnDpg, sizeof(vcnDpg)) && vcnDpg == 1;
    uint32_t vcnDecodeFirst = 0;
    vcnDecodeFirstEnabled = PE_parse_boot_argn("rgpuvcndecfirst", &vcnDecodeFirst, sizeof(vcnDecodeFirst)) && vcnDecodeFirst == 1;
    uint32_t vcnSmu = 0;
    vcnSmuEnabled = PE_parse_boot_argn("rgpuvcnsmu", &vcnSmu, sizeof(vcnSmu)) && vcnSmu == 1;
    if (vcnSmuEnabled) vcnSmuLock = IOLockAlloc();
    uint32_t vcnClock = 0;
    if (PE_parse_boot_argn("rgpuvcnclk", &vcnClock, sizeof(vcnClock)) && vcnClock >= 200 && vcnClock <= 3000)
        vcnClockMHz = vcnClock;
    uint32_t smuQuery = 0;
    smuQueryEnabled = PE_parse_boot_argn("rgpusmuquery", &smuQuery, sizeof(smuQuery)) && smuQuery == 1;
    uint32_t gfxClock = 0;
    if (PE_parse_boot_argn("rgpugfxclk", &gfxClock, sizeof(gfxClock)) && gfxClock >= 200 && gfxClock <= 3000)
        gfxClockMHz = gfxClock;
    uint32_t dcnClock = 0;
    if (PE_parse_boot_argn("rgpudclk", &dcnClock, sizeof(dcnClock)) && dcnClock >= 200 && dcnClock <= 3000)
        dcnClockMHz = dcnClock;
    RLOG("VCNCLK: rgpuvcnclk=%u rgpudclk=%u rgpugfxclk=%u rgpusmuquery=%u (effective only with rgpuvcnsmu=1)",
         vcnClockMHz, dcnClockMHz, gfxClockMHz, smuQueryEnabled);
    uint32_t vcnStatic = 0;
    vcnStaticEnabled = PE_parse_boot_argn("rgpuvcnstatic", &vcnStatic, sizeof(vcnStatic)) && vcnStatic == 1;
    uint32_t vcnApu = 0;
    vcnApuEnabled = PE_parse_boot_argn("rgpuvcnapu", &vcnApu, sizeof(vcnApu)) && vcnApu == 1;
    uint32_t vcnFw = 0;
    vcnFirmwareEnabled = PE_parse_boot_argn("rgpuvcnfw", &vcnFw, sizeof(vcnFw)) && vcnFw == 1;
    mmhubFixEnabled = PE_parse_boot_argn("rgpummhub", &mmhubFix, sizeof(mmhubFix)) && mmhubFix == 1;
    RLOG("MH: rgpummhub=%u: guarded MMHUB2.4 register table and client-root correction",
         mmhubFixEnabled);
    vmFaultDiagEnabled = PE_parse_boot_argn("rgpuvmdiag", &vmFaultDiag,
                                           sizeof(vmFaultDiag)) && vmFaultDiag == 1;
    RLOG("rgpuvmdiag=%u: bounded client-VMID fault-selected page-table diagnostics %s",
         vmFaultDiagEnabled, vmFaultDiagEnabled ? "enabled" : "disabled");
    uint32_t criticalUart = 0;
    criticalUartEnabled = PE_parse_boot_argn("rgpucr2uart", &criticalUart,
                                             sizeof(criticalUart)) && criticalUart == 2;
    RLOG("rgpucr2uart=%u: dedicated polling-only COM2 critical replay %s",
         criticalUartEnabled ? 2 : 0, criticalUartEnabled ? "enabled" : "disabled");
    uint32_t criticalQuiesce = 0;
    criticalUartQuiesceEnabled = criticalUartEnabled &&
        PE_parse_boot_argn("rgpucr2quiesce", &criticalQuiesce,
                           sizeof(criticalQuiesce)) && criticalQuiesce == 1;
    RLOG("rgpucr2quiesce=%u: bounded COM2 producer quiesce %s",
         criticalUartQuiesceEnabled ? 1 : 0,
         criticalUartQuiesceEnabled ? "enabled" : "disabled");
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
    uint32_t mqdr = 0;
    mqdNativeRestoreMode = PE_parse_boot_argn("rgpumqdrestore", &mqdr,
                                               sizeof(mqdr)) && mqdr <= 3 ? mqdr : 0;
    uint32_t golden = 0;
    goldenMode = PE_parse_boot_argn("rgpugolden", &golden, sizeof(golden)) && golden <= 1
        ? golden : 0;
    RLOG("XG: rgpugolden=%u (%s)", goldenMode,
         goldenMode == 1 ? "program Linux GC 10.3.6 golden registers before RLC start" : "off");
    uint32_t cpFw = 0, noBin = 0;
    cpFwMode = PE_parse_boot_argn("rgpucpfw", &cpFw, sizeof(cpFw)) && cpFw <= 1 ? cpFw : 0;
    noBinMode = PE_parse_boot_argn("rgpunobin", &noBin, sizeof(noBin)) && noBin <= 1 ? noBin : 0;
#ifdef RGPU_HAVE_CP_FW
    RLOG("X9C: rgpucpfw=%u (%s)", cpFwMode, cpFwMode == 1
         ? "load gc_10_3_6 CP ME/PFP/CE microcode instead of Apple's Navi 23 blobs" : "off");
#else
    RLOG("X9C: rgpucpfw=%u but no embedded CP microcode; off", cpFwMode);
    cpFwMode = 0;
#endif
    RLOG("XD: rgpunobin=%u (%s)", noBinMode,
         noBinMode == 1 ? "PA_SC_ENHANCE_1.DISABLE_SC_BINNING before RLC start" : "off");
    uint32_t hangDump = 0;
    uint32_t swLog = 0;
    swizzleLogMode = PE_parse_boot_argn("rgpuswlog", &swLog, sizeof(swLog)) && swLog <= 2 ? swLog : 0;
    RLOG("XS: rgpuswlog=%u (%s)", swizzleLogMode,
         swizzleLogMode == 2 ? "log preferred swizzle modes and return linear"
         : swizzleLogMode == 1 ? "log preferred swizzle modes" : "off");
    uint32_t texDiag = 0;
    texDiagEnabled = PE_parse_boot_argn("rgputexdiag", &texDiag, sizeof(texDiag)) &&
                     texDiag <= 2 ? texDiag : 0;
    uint32_t vcnNoDpm = 0;
    vcnNoDpmEnabled = PE_parse_boot_argn("rgpuvcnnodpm", &vcnNoDpm, sizeof(vcnNoDpm)) &&
        vcnNoDpm == 1 && (mask & XI) && vcnSmuEnabled && vcnDpgEnabled;
    uint32_t vcnWptr = 0;
    vcnWptrEnabled = PE_parse_boot_argn("rgpuvcnwptr", &vcnWptr, sizeof(vcnWptr)) &&
        vcnWptr == 1 && vcnNoDpmEnabled && vcnFirmwareEnabled && vcnApuEnabled;
    uint32_t vcnPreset = 0;
    vcnPresetEnabled = PE_parse_boot_argn("rgpuvcnpreset", &vcnPreset, sizeof(vcnPreset)) &&
        vcnPreset == 1;
    RLOG("VCNPRESET: rgpuvcnpreset=%u", vcnPresetEnabled);
    uint32_t dcn = 0, dcnTrace = 0;
    // The DCN 3.02 pool and translation are only meaningful, and only safe, together.
    if (PE_parse_boot_argn("rgpudcn", &dcn, sizeof(dcn)) && (dcn & ~kDcnAllowed) == 0 &&
        ((dcn & kDcnPool302) != 0) == ((dcn & kDcnTranslate) != 0)) dcnMode = dcn;
    else if (dcn != 0) CRLOG("DCN: rgpudcn=%#x refused (bit 8 froze the host; bits 2 and 4 must be "
                             "set together)", dcn);
    PE_parse_boot_argn("rgpudallog", &dalLogMask, sizeof(dalLogMask));
    if (PE_parse_boot_argn("rgpudcntrace", &dcnTrace, sizeof(dcnTrace)) && dcnTrace <= 20000)
        dcnTraceBudget = dcnTrace;
    CRLOG("DCN: rgpudcn=%#x (trace=%u translate=%u pool302=%u dmub-guard=%u) trace-lines=%u",
          dcnMode, (dcnMode & kDcnTrace) != 0, (dcnMode & kDcnTranslate) != 0,
          (dcnMode & kDcnPool302) != 0, (dcnMode & kDcnDmubGuard) != 0, dcnTraceBudget);
    if (dcnMode & kDcnDioWake) CRLOG("DCN: dio-wake=1 (I2C memory light sleep cleared after init_hw)");
    uint32_t vd120 = 0;
    vd120Enabled = PE_parse_boot_argn("rgpuvd120", &vd120, sizeof(vd120)) && vd120 == 1;
    CRLOG("VD120: rgpuvd120=%u", vd120Enabled);
    if (texDiagEnabled == 2 || vcnNoDpmEnabled || vcnPresetEnabled || vd120Enabled)
        textureDiagCowLock = IOLockAlloc();
    CRLOG("VCNDPM: capability alignment enabled=%u lock=%u", vcnNoDpmEnabled,
          textureDiagCowLock != nullptr);
    RLOG("rgputexdiag=%u: current-task Metal image diagnostic %s",
         texDiagEnabled, texDiagEnabled == 2 ? "COW enabled" :
         texDiagEnabled == 1 ? "read-only enabled" : "disabled");
    uint32_t texXor = 0;
    texPipeBankXorDisable = PE_parse_boot_argn("rgpunotexxor", &texXor, sizeof(texXor)) && texXor <= 1
        ? texXor : 0;
    RLOG("XX: rgpunotexxor=%u (%s)", texPipeBankXorDisable, texPipeBankXorDisable == 1
         ? "clear enableTexturePipeBankXor(bit27) in AMDRadeonX6000MTLDriver" : "off");
    uint32_t capClear = 0;
    hwCapClearMask = PE_parse_boot_argn("rgpuhwcapclr", &capClear, sizeof(capClear)) ? capClear : 0;
    RLOG("XA: rgpuhwcapclr=%#x", hwCapClearMask);
    uint32_t sdmaCfg = 0;
    sdmaAddrConfigMode = PE_parse_boot_argn("rgpusdmacfg", &sdmaCfg, sizeof(sdmaCfg)) && sdmaCfg <= 2
        ? sdmaCfg : 0;
    RLOG("XG: rgpusdmacfg=%u", sdmaAddrConfigMode);
    uint32_t tileLog = 0;
    tileLogMode = PE_parse_boot_argn("rgputilelog", &tileLog, sizeof(tileLog)) && tileLog <= 1 ? tileLog : 0;
    RLOG("XT: rgputilelog=%u", tileLogMode);
    uint32_t gbRead = 0;
    gbReadMode = PE_parse_boot_argn("rgpugbread", &gbRead, sizeof(gbRead)) && gbRead <= 2 ? gbRead : 0;
    RLOG("XG: rgpugbread=%u", gbReadMode);
    uint32_t vgpr = 0;
    vgprMode = PE_parse_boot_argn("rgpuvgpr", &vgpr, sizeof(vgpr)) && vgpr <= 3 ? vgpr : 0;
    RLOG("XV: rgpuvgpr=%u", vgprMode);
    uint32_t addrCfg = 0;
    addrConfigMode = PE_parse_boot_argn("rgpuaddrcfg", &addrCfg, sizeof(addrCfg)) && addrCfg <= 3
        ? addrCfg : 0;
    RLOG("XA: rgpuaddrcfg=%u (%s)", addrConfigMode,
         addrConfigMode == 3 ? "report hwinfo and give user space GB_ADDR_CONFIG at hwinfo[0xa4]"
         : addrConfigMode == 2 ? "report hwinfo gbAddrConfig and replace it with live GB_ADDR_CONFIG"
         : addrConfigMode == 1 ? "report hwinfo gbAddrConfig" : "off");
    hangDumpMode = PE_parse_boot_argn("rgpuhangdump", &hangDump, sizeof(hangDump)) &&
        hangDump <= 1 ? hangDump : 0;
    RLOG("XD: rgpuhangdump=%u (%s)", hangDumpMode, hangDumpMode == 1
         ? "dump CP header/IB state, ring and IB memory at the first stalled gfx ring observation"
         : "off");
    if (mqdNativeRestoreMode != 0 && mqdFixMode != 2) {
        RLOG("XQ2: rgpumqdrestore=%u requires rgpumqd=2; native restore disabled",
             mqdNativeRestoreMode);
        mqdNativeRestoreMode = 0;
    }
    RLOG("rgpumqdrestore=%u: native timeout restore experiment %s",
         mqdNativeRestoreMode,
         mqdNativeRestoreMode == 3 ? "armed halted native probe (always contained)" :
         mqdNativeRestoreMode == 2 ? "armed with halted MEC transaction" :
         mqdNativeRestoreMode == 1 ? "armed only for exact owned timeout" : "off");
    uint32_t ptbm = 0;
    if (PE_parse_boot_argn("rgpuptb", &ptbm, sizeof(ptbm)) && ptbm <= 2) {
        ptbFixMode = ptbm;
        RLOG("rgpuptb=%u: %s", ptbm, ptbm == 2
             ? "validated native physical framebuffer getter; no manual PTB writes"
             : ptbm == 1 ? "legacy post-invalidation PTB experiment" : "reporting only");
    }
    uint32_t vmroot = 0;
    if (PE_parse_boot_argn("rgpuvmroot", &vmroot, sizeof(vmroot)) && vmroot <= 5)
        vmRootFixMode = vmroot;
    vmRootFixEnabled = vmRootFixMode >= 1;
    RLOG("rgpuvmroot=%u: client GFXHUB root MC-to-physical repair %s; child PDE "
         "template conversion %s; video-memory PTE template conversion %s; real entry "
         "source conversion %s; MAP_PROCESS root conversion %s",
         vmRootFixMode, vmRootFixEnabled ? "ARMED" : "off",
         vmRootFixMode == 2 || vmRootFixMode == 3 ? "ARMED" : "off",
         vmRootFixMode == 3 ? "ARMED" : "off", vmRootFixMode >= 4 ? "ARMED" : "off",
         vmRootFixMode == 5 ? "ARMED" : "off");
    uint32_t mem = 0;
    if (PE_parse_boot_argn("rgpumem", &mem, sizeof(mem)) && mem <= 1) {
        memProbeMode = mem;
        RLOG("rgpumem=%u: report AMDHWMemory pool pointers and native one-init state", mem);
    }
    bool nonceLoPresent = PE_parse_boot_argn("rgpurnlo", &recoveryNonceLo,
                                             sizeof(recoveryNonceLo));
    bool nonceHiPresent = PE_parse_boot_argn("rgpurnhi", &recoveryNonceHi,
                                             sizeof(recoveryNonceHi));
    recoveryLeaseConfigured = nonceLoPresent && nonceHiPresent;
    RLOG("XH: dynamic recovery lease %s nonce=%016llx_%016llx",
          recoveryLeaseConfigured ? "configured" : "disabled",
          recoveryNonceLo, recoveryNonceHi);
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
            RLOG("rgpuvmm=3: VMM channel diagnostics enabled; native channel follows owned VS-ready state");
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
    if (criticalUartEnabled) {
        if (kernel_thread_start(criticalDumpThread, nullptr, &th) == KERN_SUCCESS)
            thread_deallocate(th);
        else
            RLOG("could not start the critical COM2 thread");
    }
    if (kernel_thread_start(vmObservationThread, nullptr, &th) == KERN_SUCCESS)
        thread_deallocate(th);
    else
        RLOG("could not start the VM observation thread");
    if (sdmaAddrConfigMode == 2) {
        if (kernel_thread_start(sdmaWatchdogThread, nullptr, &th) == KERN_SUCCESS)
            thread_deallocate(th);
        else
            RLOG("could not start the SDMA address-config watchdog");
    }
    if (hangDumpMode == 1) {
        if (kernel_thread_start(hangDumpThread, nullptr, &th) == KERN_SUCCESS)
            thread_deallocate(th);
        else
            RLOG("XD: could not start the hang dump thread");
    }
    lilu.onPatcherLoadForce(onPatcher);
    lilu.onKextLoadForce(kexts, arrsize(kexts), processKext, nullptr);
    RLOG("registered %lu kexts (Loaded flag set)", arrsize(kexts));
    if (texPipeBankXorDisable == 1) {
        auto err = lilu.onProcLoad(nullptr, 0, nullptr, nullptr, &mtlTexXorMod, 1);
        RLOG("XX: rgpunotexxor onProcLoad -> %d (%s)", static_cast<int>(err),
             err == LiluAPI::Error::NoError ? "registered MTL driver texture-pipe-bank-xor patch" : "FAILED");
    }
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
