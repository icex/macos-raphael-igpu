#pragma once
// Standard Retina steps for the iGPU display in QEMU's window.
//
// The window picks an aspect class; each class has standard "looks like" sizes that run
// as 2x panels (macOS 15.7 builds Retina modes for panels from 3840 wide up). All usable
// steps of the class go into the EDID, so Displays lists them and a resize within the class
// is a mode switch, not a hotplug. Between steps QEMU scales the picture proportionally.
#include <stdint.h>

namespace RaphaelSteps {

struct Step { uint16_t width, height; };
struct Class { uint16_t num, den; Step steps[2]; uint8_t count; };

constexpr Class kClasses[] = {
    {16, 9, {{1920, 1080}, {2560, 1440}}, 2},
    {16, 10, {{1920, 1200}, {2560, 1600}}, 2},
    {64, 27, {{2560, 1080}, {3440, 1440}}, 2},   // 21:9
    {32, 9, {{3840, 1080}, {0, 0}}, 1},
    {3, 2, {{1920, 1280}, {2160, 1440}}, 2},
    {4, 3, {{1920, 1440}, {2048, 1536}}, 2},
};
constexpr unsigned kClassCount = sizeof(kClasses) / sizeof(kClasses[0]);

// a/b vs c/d distance from 1, as the ratio max/min: true when a:b is closer to 1 than c:d.
inline bool closer(uint64_t a, uint64_t b, uint64_t c, uint64_t d) {
    const uint64_t hi1 = a > b ? a : b, lo1 = a > b ? b : a;
    const uint64_t hi2 = c > d ? c : d, lo2 = c > d ? d : c;
    return hi1 * lo2 < hi2 * lo1;
}

// The class whose aspect is nearest the window's (by ratio, so 2:1 and 1:2 errors weigh alike).
inline unsigned classFor(uint32_t width, uint32_t height) {
    unsigned best = 0;
    for (unsigned i = 1; i < kClassCount; i++) {
        const Class &c = kClasses[i], &b = kClasses[best];
        if (closer(uint64_t(width) * c.den, uint64_t(height) * c.num,
                   uint64_t(width) * b.den, uint64_t(height) * b.num))
            best = i;
    }
    return best;
}

// The usable step nearest (by ratio) to window width x 100 / retinaPercent points.
// Returns -1 when no step of the class is usable.
template <class Usable>
inline int stepFor(unsigned cls, uint32_t windowWidth, uint32_t retinaPercent, Usable usable) {
    if (cls >= kClassCount || !retinaPercent) return -1;
    const uint64_t target = uint64_t(windowWidth) * 100;      // in units of 1/retinaPercent
    int best = -1;
    for (unsigned i = 0; i < kClasses[cls].count; i++) {
        const Step &s = kClasses[cls].steps[i];
        if (!usable(s)) continue;
        if (best < 0 || closer(uint64_t(s.width) * retinaPercent, target,
                               uint64_t(kClasses[cls].steps[best].width) * retinaPercent, target))
            best = int(i);
    }
    return best;
}

}  // namespace RaphaelSteps
