#pragma once
#include <stdint.h>
#include <stddef.h>

namespace RaphaelFB {
struct Mode { uint32_t width, height, hz; };
static constexpr Mode modes[] = {
    {640,480,60}, {1280,720,60}, {1920,1080,60}, {1920,1080,120},
    {2560,1440,60}, {2560,1440,120}, {3840,2160,60}, {3840,2160,120},
    {5120,2880,60}, {5120,2880,120}
};
static constexpr size_t count = sizeof(modes)/sizeof(modes[0]);
inline bool fits(const Mode &m, uint64_t aperture, uint64_t transport) {
    return (m.hz==60 || m.hz==120) && m.width>=320 && m.height>=200 &&
        m.width<=5120 && m.height<=2880 &&
        uint64_t(m.width)*m.height*4 <= aperture &&
        uint64_t(m.width)*m.height*4 <= transport;
}
// Absolute nanosecond deadlines preserve fractional periods and skip missed
// ticks. One delayed callback emits one VBL, never a catch-up burst.
struct Cadence {
    uint64_t origin=0, tick=0;
    uint32_t hz=0;
    void reset(uint64_t now,uint32_t rate) { origin=now;tick=0;hz=rate; }
    uint64_t next(uint64_t now) {
        if(!hz || now<origin)return 0;
        uint64_t elapsed=now-origin;
        if(elapsed>UINT64_MAX/hz)return 0;
        uint64_t due=elapsed*hz/1000000000ULL+1;
        if(due<=tick)due=tick+1;
        tick=due;
        if(tick>UINT64_MAX/1000000000ULL)return 0;
        uint64_t delta=tick*1000000000ULL/hz;
        return origin<=UINT64_MAX-delta ? origin+delta : 0;
    }
};
}
