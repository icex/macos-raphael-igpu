#include "../src/VirtualEdid.hpp"
#include <cassert>
#include <cstdio>
using namespace RaphaelEdid;
static void sums(const uint8_t *e) {
    for (int b = 0; b < 2; b++) { uint8_t s = 0; for (int i = 0; i < 128; i++) s += e[b * 128 + i]; assert(s == 0); }
    const uint8_t *x = e + 128; uint8_t s = 0; for (int i = 1; i < 5 + x[2] + 1; i++) s += x[i]; assert(s == 0);
}
int main() {
    Timing t = cvtRb2(3840, 2160, 60);
    assert(t.vBlank == 62 && t.pixelKhz == 522614 && fitsDtd(t));
    t = cvtRb2(3840, 2160, 120);
    assert(t.vBlank == 127 && !fitsDtd(t) && t.pixelKhz > 1000000 && t.pixelKhz < 1100000);
    t = cvtRb2(1920, 1080, 120);
    assert(fitsDtd(t) && t.vFront == t.vBlank - 14);
    assert(!cvtRb2(100, 100, 60).pixelKhz && !cvtRb2(3840, 2160, 300).pixelKhz);
    uint8_t e[kMaxBytes];
    Mode m[] = {{3840, 2160, 120}, {3840, 2160, 60}, {1920, 1080, 120}};
    assert(build(e, m, 3, 1));
    sums(e);
    assert(e[126] == 1 && e[128] == 0x70 && e[133] == 0x01 && e[148] == 0x03);
    // The 120 Hz preferred mode lives in DisplayID with the preferred bit; the base DTDs are
    // left as dummies because the preferred mode does not fit a DTD.
    assert(e[148 + 3 + 3] & 0x80);
    assert(e[54] | e[55]);                                   // 4K60 DTD stands in as native
    Mode w[] = {{2560, 1600, 60}, {2560, 1600, 120}};
    assert(build(e, w, 2, 2));
    sums(e);
    assert(e[54] | e[55]);                                   // preferred DTD present
    assert((e[54 + 2] | ((e[54 + 4] >> 4) << 8)) == 2560);
    uint16_t wm, hm; physicalMm(3840, 2160, wm, hm); assert(wm == 600 && hm == 338);
    uint8_t e2[256];
    Mode q[] = {{3200, 2000, 60}, {1600, 1000, 60}};
    const uint16_t pid = productFor(3200, 2000, 60);
    assert(pid & 0x8000 && pid != productFor(3200, 2000, 120) && pid != productFor(3200, 1800, 60));
    assert(build(e2, q, 2, 9, pid));
    assert((e2[10] | (e2[11] << 8)) == pid);
    // Ten 120 Hz Retina panels (one per standard step) need two DisplayID blocks.
    Mode many[] = {{5120, 2880, 120}, {3840, 2160, 120}, {3840, 2400, 120}, {5120, 3200, 120},
                   {5120, 2160, 120}, {7680, 2160, 120}, {3840, 2560, 120}, {4320, 2880, 120},
                   {3840, 2880, 120}, {4096, 3072, 120}, {1920, 1080, 60}};
    assert(build(e, many, 11, 3));
    assert(e[126] == 2);
    for (int b = 0; b < 3; b++) { uint8_t s = 0; for (int i = 0; i < 128; i++) s += e[b * 128 + i]; assert(s == 0); }
    for (int b = 1; b < 3; b++) {
        const uint8_t *x = e + 128 * b; uint8_t s = 0;
        assert(x[0] == 0x70 && x[1] == 0x13);
        for (int i = 1; i < 5 + x[2] + 1; i++) s += x[i];
        assert(s == 0);
    }
    assert(e[24] == 0x04);                    // 5K preferred lives only in DisplayID
    assert((e[128 + 5 + 15 + 3 + 3] & 0x0f) == 4 && (e[128 + 5 + 15 + 3 + 3] & 0x80));  // 16:9, preferred
    return 0;
}
