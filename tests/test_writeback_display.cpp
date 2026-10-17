#include "../src/WritebackDisplay.hpp"
#include <cassert>
#include <cstring>
#include <map>
using namespace RaphaelWriteback;
static Ctl hostCtl() {
    Ctl c; memset(&c, 0, sizeof(c));
    c.magic = kMagic; c.version = kVersion; c.regionGpa = kDefaultGpa;
    c.regionSize = (2u << 20) + 4ull * (64u << 20);
    c.bufferOffset = 2u << 20; c.bufferStride = 64u << 20; c.maxBuffers = 4; c.maxBytes = 64u << 20;
    return c;
}
int main() {
    Ctl c = hostCtl();
    assert(hostValid(c, kDefaultGpa));
    assert(!hostValid(c, kDefaultGpa + 0x1000000));
    Ctl bad = c; bad.version = 2; assert(!hostValid(bad, kDefaultGpa));
    bad = c; bad.maxBuffers = 5; assert(!hostValid(bad, kDefaultGpa));
    bad = c; bad.regionSize = (2u << 20) + 3ull * (64u << 20); assert(!hostValid(bad, kDefaultGpa));
    bad = c; bad.magic = 0; assert(!hostValid(bad, kDefaultGpa));

    // 448 live values: FB 0xF4_0000_0000..0xF4_7FFF_FFFF, GART from 0xFF_BFA0_0000,
    // system aperture high 0x3d1fff (256 KiB units).
    const AgpPlan p = planAgp(0xF47FFFFFFFull, 0xFFBFA00000ull, kDefaultGpa, c.regionSize, 0x3d1fff);
    assert(p.ok);
    assert(p.bot == 0xF480 && p.top == 0xF490 && p.base == 0x4000);
    assert(p.mcRegion == 0xF480000000ull);
    assert(p.sysHigh == uint32_t(0xF490FFFFFFull >> 18));
    assert(bufferMc(p, c, 0) == 0xF480200000ull);
    assert(bufferMc(p, c, 3) == 0xF480200000ull + 3ull * (64u << 20));
    // MC address -> IOVA through the aperture lands inside QEMU's region.
    const uint64_t mc = bufferMc(p, c, 2);
    assert(mc - (uint64_t(p.bot) << 24) + (uint64_t(p.base) << 24) == kDefaultGpa + (2u << 20) + 2ull * (64u << 20));
    assert(!planAgp(0xF47FFFFFFFull, 0xF481000000ull, kDefaultGpa, c.regionSize, 0x3d1fff).ok);
    assert(!planAgp(0xF47FFFFFFFull, 0xFFBFA00000ull, kDefaultGpa + 0x1000, c.regionSize, 0x3d1fff).ok);

    Geometry g {3840, 2160, 3840 * 4, kXrgb8888, 4, 5, (0x34c0u + 0x274u) * 4, 4, 7, 1, 1};
    assert(geometryFits(c, g));
    Geometry gb = g; gb.pitch = 3840 * 4 + 4; assert(!geometryFits(c, gb));
    gb = g; gb.nbuf = 5; assert(!geometryFits(c, gb));
    gb = g; gb.width = 8192; gb.height = 4096; gb.pitch = 8192 * 4; assert(!geometryFits(c, gb));
    gb = g; gb.statusLag = 2; assert(!geometryFits(c, gb));
    gb = g; gb.statusBase = 2; assert(!geometryFits(c, gb));

    volatile Ctl &v = c;
    unsigned fences = 0;
    publish(v, g, true, [&] { fences++; });
    assert(fences == 2 && c.guestSeq == 1 && c.guestMagic == kMagic && c.active == 1);
    assert(c.width == 3840 && c.statusOffset == (0x34c0u + 0x274u) * 4 && c.statusLag == 1 && c.statusBase == 1);
    publish(v, g, false, [] {});
    assert(c.guestSeq == 2 && c.active == 0);

    ViewerTracker t;
    assert(!t.attached(0, 3));
    assert(t.attached(5, 3));
    assert(t.attached(5, 3) && t.attached(5, 3) && t.attached(5, 3));
    assert(!t.attached(5, 3));
    assert(t.attached(6, 3));
    
    // Timing discovery: OTG1 active 3840x2160 (htotal 4000, vtotal 2222), OPP 1, MPCC 2.
    std::map<uint32_t, uint32_t> regs;
    auto rd = [&](uint32_t r) { auto it = regs.find(r); return it == regs.end() ? 0u : it->second; };
    auto wr = [&](uint32_t r, uint32_t v) { regs[r] = v; };
    regs[Reg::OtgControl] = 0;
    regs[Reg::OtgControl + 0x80] = 1;
    regs[Reg::OtgHBlank + 0x80] = (80u << 16) | 3920u;
    regs[Reg::OtgVBlank + 0x80] = (40u << 16) | 2200u;
    regs[Reg::OtgHTotal + 0x80] = 3999;
    regs[Reg::OtgVTotal + 0x80] = 2221;
    regs[Reg::OdmSource + 0x10] = 1u << 16;
    regs[Reg::MpcOutMux + 4] = 2;
    Timing tm = activeTiming(rd);
    assert(tm.active && tm.otg == 1 && tm.opp == 1 && tm.mpcc == 2);
    assert(tm.width == 3840 && tm.height == 2160 && tm.hTotal == 4000 && tm.vTotal == 2222);
    regs[Reg::OdmSource + 0x10] = (1u << 16) | 1u;   // ODM 2:1
    tm = activeTiming(rd);
    assert(tm.odmSegments == 2 && tm.width == 1920 && tm.opp == 1);
    regs[Reg::OdmSource + 0x10] = 1u << 16;
    regs[Reg::OtgControl + 0x80] = 0;
    assert(!activeTiming(rd).active);

    assert(pitchFor(3840) == 15360 && pitchFor(1366) == 5632);
    assert(maxScaledTime(120, kUrgentWatermarkNs) == 0x200u * 30 * 2 - 12000);
    assert(maxScaledTime(4, 99999) == 0);

    WbSetup ws {3840, 2160, 15360, 2, 533250, {0xF480200000ull, 0xF484200000ull, 0, 0}};
    regs.clear();
    regs[Reg::MpcDwbMux] = 0xf;
    assert(start(rd, wr, ws, 2));
    assert(running(rd, 2) && !running(rd, 1));
    assert(regs[Reg::McifAddrY] == uint32_t(0xF480200000ull >> 8) && regs[Reg::McifAddrYHigh] == 0);
    assert(regs[Reg::McifAddrY + 4] == uint32_t(0xF484200000ull >> 8));
    assert(regs[Reg::McifAddrY + 8] == regs[Reg::McifAddrY]);      // ring of two repeats
    assert(regs[Reg::McifAddrY + 12] == regs[Reg::McifAddrY + 4]);
    assert(regs[Reg::McifLumaSize] == 60u * 2160u && regs[Reg::McifPitch] == (60u << 8));
    assert((regs[Reg::McifArb] >> 20) == 120 && (regs[Reg::McifArb] & 3) == 2);
    assert(regs[Reg::FcSourceSize] == (3840u | (2160u << 16)));
    assert(regs[Reg::DwbOutCtrl] == ((2u << 4) | (0x3ffu << 8)));
    assert(regs[Reg::McifResolution + 3] == (3840u | (2160u << 16)));
    assert((regs[Reg::McifSwControl] & ((1u << 24) | 1u)) == ((1u << 24) | 1u));
    stop(rd, wr);
    assert(!running(rd, 2) && (regs[Reg::MpcDwbMux] & 0xf) == 0xf);
    WbSetup bs = ws; bs.mc[1] |= 0x80; assert(!start(rd, wr, bs, 2));
    bs = ws; bs.pitch = 15364; assert(!start(rd, wr, bs, 2));
    bs = ws; bs.mpcc = 4; assert(!start(rd, wr, bs, 2));
    return 0;
}
