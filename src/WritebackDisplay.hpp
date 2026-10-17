#pragma once
#include <stddef.h>
#include <stdint.h>

// iGPU -> QEMU window (rgpuwbdisplay=1). DCN display writeback (DWB + MCIF_WB) writes
// each composited frame into a RAM region QEMU places at a fixed guest-physical address
// without describing it to the firmware (vfio-pci x-rgpu-display). QEMU presents the
// last completed buffer in its own console; no emulated display adapter exists.
// The control page ABI matches QEMU hw/vfio/rgpu-display.h (version 1).
namespace RaphaelWriteback {
constexpr uint32_t kMagic = 0x31445052u; // "RPD1"
constexpr uint32_t kVersion = 1;
constexpr uint64_t kDefaultGpa = 0x4000000000ull;
constexpr uint32_t kMaxBuffers = 4;

struct Ctl {
    uint32_t magic, version;
    uint64_t regionGpa, regionSize;
    uint32_t bufferOffset, bufferStride, maxBuffers, maxBytes;
    uint32_t hostSeq, reqWidth, reqHeight, reqRefreshMhz, viewerActive, hostFrames;
    uint64_t hostHeartbeatNs;
    uint32_t hostPolls, hostError;
    uint32_t sampleCrc, crcChanges, sampledFrames;
    uint8_t reserved0[0x100 - 0x5c];
    uint32_t guestMagic, guestSeq, active, width, height, pitch, drmFourcc, nbuf;
    uint32_t statusBar, statusOffset, statusShift, statusMask, statusLag;
    uint32_t ackHostSeq, guestFrames;
    uint32_t stopCount;
    struct Stop { uint32_t bar, offset, clearMask, pad; } stop[4];
    uint32_t statusBase;   // value of the index field for buffer 0 (MCIF_WB CUR_BUF is 1-based)
    uint32_t sdmaFence;    // SDMA copy: seq << 2 | buffer, written by the engine
    // Hardware cursor plane (the SDMA copy reads only the primary surface). The image is
    // linear ARGB8888 at region + kCursorOffset; cursorSeq changes after a new image landed,
    // cursorPosSeq after the fields below changed. Positions are surface pixels.
    uint32_t cursorSeq, cursorWidth, cursorHeight, cursorPitch;
    uint32_t cursorPosSeq, cursorX, cursorY, cursorHotX, cursorHotY, cursorEnabled;
    uint8_t reserved1[0x1000 - 0x1b0];
};
static_assert(sizeof(Ctl) == 0x1000, "control page");
static_assert(offsetof(Ctl, hostHeartbeatNs) == 0x40, "heartbeat");
static_assert(offsetof(Ctl, guestMagic) == 0x100, "guest half");
static_assert(offsetof(Ctl, guestFrames) == 0x138, "guest frames");
static_assert(offsetof(Ctl, stop) == 0x140, "stop list");
static_assert(offsetof(Ctl, statusBase) == 0x180, "status base");
static_assert(offsetof(Ctl, sdmaFence) == 0x184, "sdma fence");
static_assert(offsetof(Ctl, cursorSeq) == 0x188 && offsetof(Ctl, cursorEnabled) == 0x1ac, "cursor");
constexpr uint32_t kCursorOffset = 0x100000, kCursorMaxBytes = 256 * 256 * 4;

// QEMU's half must describe the region we were told to expect before we program the
// GPU to write into it: wrong addresses would be DMA into guest RAM or IOMMU faults.
inline bool hostValid(const Ctl &c, uint64_t gpa) {
    return c.magic == kMagic && c.version == kVersion && c.regionGpa == gpa &&
           c.maxBuffers >= 2 && c.maxBuffers <= kMaxBuffers &&
           c.bufferOffset >= 0x1000 && (c.bufferOffset & 0xfff) == 0 &&
           c.bufferStride >= c.maxBytes && (c.bufferStride & 0xfff) == 0 &&
           c.maxBytes >= 1920u * 1080u * 4u &&
           uint64_t(c.bufferOffset) + uint64_t(c.bufferStride) * c.maxBuffers <= c.regionSize &&
           c.regionSize <= (1ull << 32);
}

// DRM fourcc codes QEMU understands.
constexpr uint32_t kXrgb8888 = 0x34325258u, kArgb8888 = 0x34325241u;
constexpr uint32_t kXrgb2101010 = 0x30335258u;

// MMHUB/DCHUBBUB AGP aperture: MC [bot<<24, (top<<24)|0xffffff] -> system (IOVA)
// address mc - (bot<<24) + (base<<24). Place it directly above the frame buffer so the
// system aperture (256 KiB units) only grows upward and never overlaps the GART.
struct AgpPlan {
    bool ok = false;
    uint32_t bot = 0, top = 0, base = 0;   // 16 MiB units
    uint32_t sysHigh = 0;                  // 256 KiB units, inclusive
    uint64_t mcRegion = 0;                 // MC address of region offset 0
};
inline AgpPlan planAgp(uint64_t fbTopInclusive, uint64_t gartStart, uint64_t gpa,
                       uint64_t regionSize, uint32_t sysHighNow) {
    AgpPlan p;
    const uint64_t unit = 1ull << 24;
    if (!regionSize || (gpa & (unit - 1)) || fbTopInclusive == UINT64_MAX) return p;
    const uint64_t mc = (fbTopInclusive + 1 + unit - 1) & ~(unit - 1);
    const uint64_t end = mc + ((regionSize + unit - 1) & ~(unit - 1)) - 1;
    if (end >= gartStart || end >= (1ull << 48)) return p;
    p.bot = uint32_t(mc >> 24);
    p.top = uint32_t(end >> 24);
    p.base = uint32_t(gpa >> 24);
    p.sysHigh = uint32_t(end >> 18) > sysHighNow ? uint32_t(end >> 18) : sysHighNow;
    p.mcRegion = mc;
    p.ok = true;
    return p;
}

struct Geometry {
    uint32_t width, height, pitch, fourcc, nbuf;
    uint32_t statusBar, statusOffset, statusShift, statusMask, statusLag;
    uint32_t statusBase;
};
inline bool geometryFits(const Ctl &c, const Geometry &g) {
    return g.width && g.height && g.pitch >= g.width * 4 && !(g.pitch & 63) &&
           uint64_t(g.pitch) * g.height <= c.maxBytes &&
           g.nbuf >= 1 && g.nbuf <= c.maxBuffers && g.nbuf <= kMaxBuffers &&
           !(g.statusOffset & 3) && g.statusShift < 32 && g.statusMask && g.statusLag <= 1 &&
           g.statusBase <= 1;
}

// Publish the guest half; guestSeq is written last so QEMU never sees a torn update.
template <class Fence>
inline void publish(volatile Ctl &c, const Geometry &g, bool active, Fence fence) {
    c.guestMagic = kMagic;
    c.active = active ? 1 : 0;
    c.width = g.width; c.height = g.height; c.pitch = g.pitch;
    c.drmFourcc = g.fourcc; c.nbuf = g.nbuf;
    c.statusBar = g.statusBar; c.statusOffset = g.statusOffset;
    c.statusShift = g.statusShift; c.statusMask = g.statusMask; c.statusLag = g.statusLag;
    c.statusBase = g.statusBase;
    fence();
    c.guestSeq = c.guestSeq + 1;
    fence();
}

inline uint64_t bufferMc(const AgpPlan &p, const Ctl &c, uint32_t index) {
    return p.mcRegion + c.bufferOffset + uint64_t(c.bufferStride) * index;
}

// A viewer is attached when QEMU refreshed the console within the last two seconds of
// its own realtime clock; we compare QEMU's successive heartbeats, never guest time.
struct ViewerTracker {
    uint64_t lastBeat = 0;
    uint32_t staleTicks = 0;
    bool attached(uint64_t beat, uint32_t ticksPerTwoSeconds) {
        if (beat != lastBeat) { lastBeat = beat; staleTicks = 0; return true; }
        if (staleTicks < ticksPerTwoSeconds) { staleTicks++; return beat != 0; }
        return false;
    }
};

// DCN 3.1.5 absolute dword indices (seg2 0x34c0, seg3 0x9000). Every DWB/MCIF_WB index
// is identical in 3.0.2, so Apple's own tables would land on the same registers.
namespace Reg {
constexpr uint32_t kOtgStride = 0x80, kOdmStride = 0x10;
constexpr uint32_t OtgHBlank = 0x34c0 + 0x1b2b, OtgHTotal = 0x34c0 + 0x1b2a;
constexpr uint32_t OtgVTotal = 0x34c0 + 0x1b2f, OtgVBlank = 0x34c0 + 0x1b36;
constexpr uint32_t OtgControl = 0x34c0 + 0x1b41, OtgFrameCount = 0x34c0 + 0x1b4c;
constexpr uint32_t OdmSource = 0x34c0 + 0x1acb;      // OPTC_SEG0_SRC_SEL [19:16] = OPP
constexpr uint32_t MpcOutMux = 0x9000 + 0x580;       // per OPP, stride 4: top MPCC [3:0]
constexpr uint32_t MpcDwbMux = 0x955c;               // MUX [3:0], STATUS [7:4]
constexpr uint32_t DwbEnableClk = 0x66e8, DwbMemPwr = 0x66e9, FcModeCtrl = 0x66ea;
constexpr uint32_t FcFlowCtrl = 0x66eb, FcSourceSize = 0x66ee, DwbOutCtrl = 0x66f5;
constexpr uint32_t DwbOverflow = 0x66f9, DwbHdrMult = 0x6754, DwbGamutMode = 0x6755;
constexpr uint32_t DwbOgamControl = 0x6763;
constexpr uint32_t McifSwControl = 0x3732, McifStatus = 0x3734, McifPitch = 0x3735;
constexpr uint32_t McifBufStatus = 0x3736;           // + 2*(n): STATUS, +1 STATUS2
constexpr uint32_t McifArb = 0x373e, McifAddrY = 0x3742, McifAddrC = 0x3744; // + 4*n
constexpr uint32_t McifVce = 0x3752, McifQos = 0x3757, McifLumaSize = 0x3759;
constexpr uint32_t McifChromaSize = 0x375a, McifAddrYHigh = 0x375b; // + 2*n
constexpr uint32_t McifAddrCHigh = 0x375c, McifResolution = 0x3763; // + n
constexpr uint32_t McifPstateWm = 0x376a, McifWatermark = 0x376b;
constexpr uint32_t MmhubbubMemPwr = 0x3800;          // 3.1.5 (3.0.2: 0x37ff)
constexpr uint32_t DcnAgpBot = 0x3938, DcnAgpTop = 0x3939, DcnAgpBase = 0x393a;
// MMHUB 2.3 layout, discovery base 0x1a000.
constexpr uint32_t MmAgpTop = 0x1a8ee, MmAgpBot = 0x1a8ef, MmAgpBase = 0x1a8f0;
constexpr uint32_t MmSysLow = 0x1a8f1, MmSysHigh = 0x1a8f2;
constexpr uint32_t MmFbBase = 0x1a8ec, MmFbTop = 0x1a8ed;
}

// Timing of the one active output, read from the OTG.
struct Timing {
    bool active = false;
    uint32_t otg = 0, opp = 0, mpcc = 0;
    uint32_t width = 0, height = 0, hTotal = 0, vTotal = 0;
    uint32_t odmSegments = 1;   // ODM combine: DWB taps one MPC tree, i.e. one segment
};
template <class Read>
inline Timing activeTiming(Read read) {
    Timing t;
    for (uint32_t i = 0; i < 4; i++) {
        const uint32_t control = read(Reg::OtgControl + i * Reg::kOtgStride);
        if (control == 0xffffffffu || !(control & 1)) continue;
        const uint32_t h = read(Reg::OtgHBlank + i * Reg::kOtgStride);
        const uint32_t v = read(Reg::OtgVBlank + i * Reg::kOtgStride);
        const uint32_t hStart = h & 0x7fff, hEnd = (h >> 16) & 0x7fff;
        const uint32_t vStart = v & 0x7fff, vEnd = (v >> 16) & 0x7fff;
        if (hStart <= hEnd || vStart <= vEnd) continue;
        t.otg = i;
        t.width = hStart - hEnd;
        t.height = vStart - vEnd;
        t.hTotal = (read(Reg::OtgHTotal + i * Reg::kOtgStride) & 0x7fff) + 1;
        t.vTotal = (read(Reg::OtgVTotal + i * Reg::kOtgStride) & 0x7fff) + 1;
        const uint32_t source = read(Reg::OdmSource + i * Reg::kOdmStride);
        t.opp = (source >> 16) & 0xf;
        t.odmSegments = (source & 3) + 1;          // OPTC_NUM_OF_INPUT_SEGMENT
        t.width /= t.odmSegments;
        t.mpcc = read(Reg::MpcOutMux + 4 * t.opp) & 0xf;
        t.active = t.opp < 4 && t.mpcc < 4;
        return t;
    }
    return t;
}

struct WbSetup {
    uint32_t width, height, pitch, mpcc;
    uint32_t pixelClockKhz;
    uint64_t mc[kMaxBuffers];
};
inline uint32_t pitchFor(uint32_t width) { return (width * 4 + 255) & ~255u; }

// Linux dcn20_calc_max_scaled_time for packed 32 bpp.
inline uint32_t maxScaledTime(uint32_t timePerPixel, uint32_t urgentWatermarkNs) {
    uint32_t timePerByte = timePerPixel / 4;
    if (!timePerByte) timePerByte = 1;
    const uint32_t capability = 0x200u * timePerByte * 32 / 16;
    return capability > urgentWatermarkNs ? capability - urgentWatermarkNs : 0;
}

// Watermarks in ns, as DML's writeback urgent / DRAM clock change latencies would give
// for DCN 3.1.5 (writeback_latency_us 12, dram clock change 23 us); no DML here.
constexpr uint32_t kUrgentWatermarkNs = 12000, kPstateWatermarkNs = 23000;

// Stop sequence (also what QEMU replays on exit through the stop list).
template <class Read, class Write>
inline void stop(Read read, Write write) {
    write(Reg::FcModeCtrl, read(Reg::FcModeCtrl) & ~1u);
    write(Reg::McifSwControl, read(Reg::McifSwControl) & ~1u);
    write(Reg::DwbEnableClk, read(Reg::DwbEnableClk) & ~1u);
    write(Reg::MpcDwbMux, (read(Reg::MpcDwbMux) & ~0xfu) | 0xf);
}

// Linux mmhubbub3_config_mcif_buf + config_mcif_arb + enable, then dwb3_enable with
// bypass gamut/OGAM and A2R10G10B10 output, then dcn30 set_dwb_mux.
template <class Read, class Write>
inline bool start(Read read, Write write, const WbSetup &s, uint32_t nbuf) {
    if (!s.width || !s.height || s.width > 8192 || s.height > 8192 || s.mpcc > 3 ||
        s.pitch != pitchFor(s.width) || (s.pitch >> 8) > 0xff || !nbuf || nbuf > kMaxBuffers ||
        !s.pixelClockKhz)
        return false;
    for (uint32_t n = 0; n < nbuf; n++)
        if ((s.mc[n] & 0xff) || s.mc[n] >= (1ull << 48)) return false;
    stop(read, write);
    write(Reg::MmhubbubMemPwr, (read(Reg::MmhubbubMemPwr) & ~0xcu) | 0x10u);
    write(Reg::DwbMemPwr, (read(Reg::DwbMemPwr) & ~0x300u) | 0x400u);
    // A ring shorter than four repeats addresses so the hardware never writes elsewhere.
    for (uint32_t n = 0; n < kMaxBuffers; n++) {
        const uint64_t a = s.mc[n % nbuf];
        write(Reg::McifAddrY + 4 * n, uint32_t(a >> 8));
        write(Reg::McifAddrYHigh + 2 * n, uint32_t(a >> 40) & 0xff);
        write(Reg::McifAddrC + 4 * n, 0);
        write(Reg::McifAddrCHigh + 2 * n, 0);
        write(Reg::McifResolution + n, (s.width & 0x1fff) | ((s.height & 0x1fff) << 16));
    }
    write(Reg::McifLumaSize, ((s.pitch >> 8) * s.height) & 0xfffff);
    write(Reg::McifChromaSize, 0);
    write(Reg::McifPitch, ((s.pitch >> 8) & 0xff) << 8);
    write(Reg::McifSwControl, (read(Reg::McifSwControl) & ~0xf00u) | (1u << 24));
    const uint32_t tpp = 64000000u / s.pixelClockKhz;
    write(Reg::McifArb, (read(Reg::McifArb) & ~0xfff00003u) | ((tpp & 0xfff) << 20) | 2u);
    for (uint32_t k = 0; k < 4; k++) {
        write(Reg::McifWatermark, (k << 24) | kUrgentWatermarkNs);
        write(Reg::McifPstateWm, (k << 24) | kPstateWatermarkNs);
    }
    write(Reg::McifQos, maxScaledTime(tpp, kUrgentWatermarkNs) & 0x3fffff);
    write(Reg::McifVce, (read(Reg::McifVce) & ~0x1fff0000u) | (31u << 16));
    write(Reg::McifSwControl, read(Reg::McifSwControl) | 1u);

    write(Reg::DwbEnableClk, read(Reg::DwbEnableClk) | 1u | (1u << 4) | (1u << 8));
    write(Reg::FcSourceSize, (s.width & 0x7fff) | ((s.height & 0x7fff) << 16));
    write(Reg::FcModeCtrl, read(Reg::FcModeCtrl) & ~((1u << 8) | (3u << 4) | (3u << 12)));
    write(Reg::DwbHdrMult, 0x1f000);
    write(Reg::DwbGamutMode, 0);
    write(Reg::DwbOgamControl, read(Reg::DwbOgamControl) & ~3u);
    write(Reg::DwbOutCtrl, (2u << 4) | (0x3ffu << 8));
    write(Reg::MpcDwbMux, (read(Reg::MpcDwbMux) & ~0xfu) | s.mpcc);
    write(Reg::FcFlowCtrl, (read(Reg::FcFlowCtrl) & ~0xfffu) | 96u);
    write(Reg::FcModeCtrl, read(Reg::FcModeCtrl) | 1u);
    return true;
}

// Writeback is healthy when capture, buffer manager and mux are all still as we left them.
template <class Read>
inline bool running(Read read, uint32_t mpcc) {
    return (read(Reg::FcModeCtrl) & 1) && (read(Reg::McifSwControl) & 1) &&
           (read(Reg::DwbEnableClk) & 1) && (read(Reg::MpcDwbMux) & 0xf) == mpcc;
}
}
