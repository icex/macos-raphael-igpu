#pragma once
#include <stddef.h>
#include <stdint.h>

// EDID for the plug-free virtual display, built at runtime so its preferred mode can
// follow the QEMU window (any size) at 60 or 120 Hz. Timings are VESA CVT reduced
// blanking v2 (fixed 80-pixel horizontal blank, >= 460 us vertical blank). Modes whose
// pixel clock fits an EDID detailed timing (<= 655.35 MHz) go in the base block; the
// rest (3840x2160@120 needs ~1.08 GHz) go in a DisplayID 1.3 type I timing block in
// the extension, which carries a 24-bit clock in 10 kHz units.
namespace RaphaelEdid {
struct Timing {
    uint32_t pixelKhz = 0;
    uint16_t hActive = 0, hBlank = 0, hFront = 0, hSync = 0;
    uint16_t vActive = 0, vBlank = 0, vFront = 0, vSync = 0;
    uint16_t refresh = 0;
};

inline Timing cvtRb2(uint16_t width, uint16_t height, uint16_t refresh) {
    Timing t;
    if (width < 320 || height < 200 || width > 8192 || height > 8192 || refresh < 24 || refresh > 240)
        return t;
    const uint64_t frameNs = 1000000000ull / refresh;
    const uint64_t minVblankNs = 460000;
    if (frameNs <= minVblankNs) return t;
    // Line period from the active part of the frame, then enough lines for 460 us.
    const uint64_t lineNs1000 = (frameNs - minVblankNs) * 1000 / height;   // ns * 1000
    uint32_t vbi = uint32_t((minVblankNs * 1000 + lineNs1000 - 1) / lineNs1000);
    const uint32_t vSync = 8, vBackMin = 6;
    if (vbi < vSync + vBackMin + 1) vbi = vSync + vBackMin + 1;
    t.hActive = width; t.hBlank = 80; t.hFront = 8; t.hSync = 32;
    t.vActive = height; t.vBlank = uint16_t(vbi); t.vSync = uint16_t(vSync);
    t.vFront = uint16_t(vbi - vSync - vBackMin);
    t.refresh = refresh;
    t.pixelKhz = uint32_t(uint64_t(width + 80) * (height + vbi) * refresh / 1000);
    return t;
}

// One product ID per panel size: WindowServer caches display overrides per vendor/product,
// so a size it has never seen reads the override the guest helper wrote for it.
inline uint16_t productFor(uint16_t width, uint16_t height, uint16_t refresh) {
    uint32_t h = 2166136261u;
    const uint16_t v[3] = {width, height, refresh};
    for (uint16_t x : v) { h = (h ^ (x & 0xff)) * 16777619u; h = (h ^ (x >> 8)) * 16777619u; }
    return uint16_t(0x8000u | (h & 0x7fffu));
}

inline bool fitsDtd(const Timing &t) {
    return t.pixelKhz && t.pixelKhz <= 655350 && t.hActive < 4096 && t.vActive < 4096 &&
           t.hBlank < 4096 && t.vBlank < 4096 && t.hFront < 1024 && t.hSync < 1024 &&
           t.vFront < 64 && t.vSync < 64;
}

// 18-byte EDID detailed timing descriptor (digital separate sync, +h +v).
inline void writeDtd(uint8_t *d, const Timing &t, uint16_t widthMm, uint16_t heightMm) {
    const uint32_t clk = t.pixelKhz / 10;
    d[0] = uint8_t(clk); d[1] = uint8_t(clk >> 8);
    d[2] = uint8_t(t.hActive); d[3] = uint8_t(t.hBlank);
    d[4] = uint8_t(((t.hActive >> 8) << 4) | (t.hBlank >> 8));
    d[5] = uint8_t(t.vActive); d[6] = uint8_t(t.vBlank);
    d[7] = uint8_t(((t.vActive >> 8) << 4) | (t.vBlank >> 8));
    d[8] = uint8_t(t.hFront); d[9] = uint8_t(t.hSync);
    d[10] = uint8_t(((t.vFront & 15) << 4) | (t.vSync & 15));
    d[11] = uint8_t(((t.hFront >> 8) << 6) | ((t.hSync >> 8) << 4) | ((t.vFront >> 4) << 2) | (t.vSync >> 4));
    d[12] = uint8_t(widthMm); d[13] = uint8_t(heightMm);
    d[14] = uint8_t(((widthMm >> 8) << 4) | (heightMm >> 8));
    d[15] = 0; d[16] = 0; d[17] = 0x1a;       // digital separate sync, +H -V (CVT-RB)
}

// 20-byte DisplayID type I detailed timing.
inline void writeDisplayIdTiming(uint8_t *d, const Timing &t, bool preferred) {
    const uint32_t clk = t.pixelKhz / 10 - 1;
    d[0] = uint8_t(clk); d[1] = uint8_t(clk >> 8); d[2] = uint8_t(clk >> 16);
    // Nominal aspect code (DisplayID 1.3): 4:3, 16:9, 16:10, 64:27, else undefined (8).
    const uint32_t w = t.hActive, h = t.vActive;
    const uint8_t aspect = w * 3 == h * 4 ? 2 : w * 9 == h * 16 ? 4 : w * 10 == h * 16 ? 5 :
                           w * 27 == h * 64 ? 6 : 8;
    d[3] = uint8_t((preferred ? 0x80 : 0) | aspect);   // progressive
    auto put = [&](int at, uint16_t v) { d[at] = uint8_t(v); d[at + 1] = uint8_t(v >> 8); };
    put(4, uint16_t(t.hActive - 1)); put(6, uint16_t(t.hBlank - 1));
    put(8, uint16_t((t.hFront - 1) | 0x8000)); put(10, uint16_t(t.hSync - 1));
    put(12, uint16_t(t.vActive - 1)); put(14, uint16_t(t.vBlank - 1));
    put(16, uint16_t(t.vFront - 1)); put(18, uint16_t(t.vSync - 1)); // -V
}

inline void checksum(uint8_t *block) {
    uint8_t sum = 0;
    for (int i = 0; i < 127; i++) sum += block[i];
    block[127] = uint8_t(0x100 - sum);
}

struct Mode { uint16_t width, height, refresh; };

// Physical size at the 448 EDID's density (3840 px = 600 mm, ~163 dpi): macOS offered the
// 2x HiDPI modes and chose 1920x1080 HiDPI for it. A 218-dpi size with range-limits-only
// descriptors (450) got no HiDPI modes and a 0 Hz mode list.
inline void physicalMm(uint16_t width, uint16_t height, uint16_t &wMm, uint16_t &hMm) {
    wMm = uint16_t((uint32_t(width) * 5 + 16) / 32);
    hMm = uint16_t((uint32_t(height) * 5 + 16) / 32);
}

constexpr size_t kMaxModes = 16, kMaxExtBlocks = 3, kMaxBytes = 128 * (1 + kMaxExtBlocks);
constexpr size_t kTimingsPerBlock = 5;        // 20-byte DisplayID timings per extension block

// Writes up to kMaxBytes (base + DisplayID extension blocks; out[126] is their count).
// modes[0] is preferred; returns false if a mode has no valid timing or they do not fit.
inline bool build(uint8_t *out, const Mode *modes, size_t count, uint32_t serial,
                  uint16_t product = 0x0447) {
    for (size_t i = 0; i < kMaxBytes; i++) out[i] = 0;
    if (!count || count > kMaxModes) return false;
    Timing timings[kMaxModes];
    for (size_t i = 0; i < count; i++) {
        timings[i] = cvtRb2(modes[i].width, modes[i].height, modes[i].refresh);
        if (!timings[i].pixelKhz) return false;
    }
    uint16_t wMm, hMm;
    physicalMm(modes[0].width, modes[0].height, wMm, hMm);
    static const uint8_t header[8] = {0, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0};
    for (int i = 0; i < 8; i++) out[i] = header[i];
    out[8] = 0x48; out[9] = 0xf0;            // manufacturer "RPH"
    out[10] = uint8_t(product); out[11] = uint8_t(product >> 8);
    out[12] = uint8_t(serial); out[13] = uint8_t(serial >> 8);
    out[14] = uint8_t(serial >> 16); out[15] = uint8_t(serial >> 24);
    out[16] = 41; out[17] = 36;              // week 41, 2026
    out[18] = 1; out[19] = 4;                // EDID 1.4
    out[20] = 0xa5;                          // digital, 10 bpc, DisplayPort
    out[21] = uint8_t((wMm + 5) / 10); out[22] = uint8_t((hMm + 5) / 10);
    out[23] = 0x78;                          // gamma 2.2
    out[24] = 0x06;                          // RGB 4:4:4, preferred timing is native
    static const uint8_t chroma[10] = {0xee, 0x91, 0xa3, 0x54, 0x4c, 0x99, 0x26, 0x0f, 0x50, 0x54};
    for (int i = 0; i < 10; i++) out[25 + i] = chroma[i];
    for (int i = 38; i < 54; i++) out[i] = 1;
    out[38] = 0xd1; out[39] = 0xc0;            // standard timing 1920x1080@60, as in 448
    // Base block: up to two DTDs, then range limits and name.
    int slot = 54, dtds = 0;
    bool inBase[kMaxModes] = {};
    // EDID 1.4 needs a native preferred DTD first. When the preferred mode is beyond a
    // DTD (4K120) the first DTD is the next mode that fits and DisplayID marks the real
    // preferred mode.
    for (size_t i = 0; i < count && dtds < 2; i++) {
        if (!fitsDtd(timings[i])) continue;
        writeDtd(out + slot, timings[i], wMm, hMm);
        inBase[i] = true; slot += 18; dtds++;
    }
    if (!dtds) return false;
    // A preferred mode beyond any DTD (wider than 4095) lives only in DisplayID. The base
    // block must not then claim its first DTD is native: macOS would size the panel (and
    // decide Retina) from that smaller fallback. Leave "preferred timing is native" clear.
    bool nativeInBase = false;
    for (size_t i = 0; i < count; i++)
        if (inBase[i] && modes[i].width == modes[0].width && modes[i].height == modes[0].height)
            nativeInBase = true;
    if (!nativeInBase) out[24] = 0x04;
    while (slot < 90) {                       // dummy descriptors keep the layout fixed
        out[slot + 3] = 0x10; slot += 18;
    }
    uint16_t maxRefresh = 0, minRefresh = 255;
    uint32_t maxKhz = 0, maxHKhz = 0, minHKhz = UINT32_MAX;
    for (size_t i = 0; i < count; i++) {
        const Timing &t = timings[i];
        if (t.refresh > maxRefresh) maxRefresh = t.refresh;
        if (t.refresh < minRefresh) minRefresh = t.refresh;
        if (t.pixelKhz > maxKhz) maxKhz = t.pixelKhz;
        const uint32_t h = t.pixelKhz / (t.hActive + t.hBlank);
        if (h + 1 > maxHKhz) maxHKhz = h + 1;
        if (h < minHKhz) minHKhz = h;
    }
    // Wide GTF-default range limits like the 448 EDID (24-120 Hz, 30-160 kHz, 600 MHz),
    // widened only when a listed mode needs more.
    uint8_t *r = out + 90;
    (void)minRefresh; (void)minHKhz;
    r[3] = 0xfd; r[4] = 0;
    r[5] = 24; r[6] = uint8_t(maxRefresh > 120 ? maxRefresh : 120);
    r[7] = 30;
    if (maxHKhz > 255) { r[4] |= 0x08; r[8] = uint8_t(maxHKhz - 255 > 255 ? 255 : maxHKhz - 255); }
    else r[8] = uint8_t(maxHKhz > 160 ? maxHKhz : 160);
    const uint32_t tenMhz = (maxKhz + 9999) / 10000;
    r[9] = uint8_t(tenMhz > 255 ? 255 : (tenMhz > 60 ? tenMhz : 60));
    r[10] = 0x00; r[11] = 0x0a;
    for (int i = 12; i < 18; i++) r[i] = 0x20;
    uint8_t *n = out + 108;                   // product name
    n[3] = 0xfc;
    static const char name[] = "Raphael VD\n ";
    for (int i = 0; i < 13; i++) n[5 + i] = uint8_t(name[i] ? name[i] : ' ');
    // Extensions: DisplayID 1.3 sections with every mode not in the base block, five
    // timings per block; the first section also carries the display parameters.
    size_t ext = 0;
    for (size_t i = 0; i < count; i++) if (!inBase[i]) ext++;
    const size_t blocks = (ext + kTimingsPerBlock - 1) / kTimingsPerBlock;
    if (blocks > kMaxExtBlocks) return false;
    out[126] = uint8_t(blocks);
    checksum(out);
    size_t next = 0;                          // next mode index to place
    bool marked = false;
    for (size_t blk = 0; blk < blocks; blk++) {
        uint8_t *e = out + 128 * (1 + blk);
        size_t here = 0;
        size_t idx[kTimingsPerBlock];
        while (next < count && here < kTimingsPerBlock) {
            if (!inBase[next]) idx[here++] = next;
            next++;
        }
        const bool params = blk == 0;
        const uint8_t payload = uint8_t((params ? 15 : 0) + 3 + 20 * here);
        e[0] = 0x70;
        e[1] = 0x13;                          // DisplayID 1.3
        e[2] = payload;                       // section bytes after the 5-byte header
        e[3] = 0x03; e[4] = 0;                // standalone display
        uint8_t *b = e + 5;
        if (params) {
            // Display parameters: image size (0.1 mm), native pixels, 10 bpc, gamma 2.2.
            b[0] = 0x01; b[1] = 0; b[2] = 12;
            b[3] = uint8_t(wMm * 10); b[4] = uint8_t((wMm * 10) >> 8);
            b[5] = uint8_t(hMm * 10); b[6] = uint8_t((hMm * 10) >> 8);
            b[7] = uint8_t(modes[0].width); b[8] = uint8_t(modes[0].width >> 8);
            b[9] = uint8_t(modes[0].height); b[10] = uint8_t(modes[0].height >> 8);
            b[11] = 0x00;                     // features
            b[12] = 120;                      // gamma 2.2
            b[13] = uint8_t(modes[0].width * 100u / modes[0].height - 100u);
            b[14] = 0x99;                     // 10 bpc dynamic and native
            b += 15;
        }
        b[0] = 0x03; b[1] = 0; b[2] = uint8_t(20 * here);
        uint8_t *d = b + 3;
        // DisplayID needs one preferred timing: the real preferred mode when it lives
        // here, else the first DisplayID entry.
        for (size_t k = 0; k < here; k++) {
            const size_t i = idx[k];
            writeDisplayIdTiming(d, timings[i], i == 0 || (inBase[0] && !marked));
            marked = true;
            d += 20;
        }
        uint8_t sum = 0;
        for (int i = 1; i < 5 + payload; i++) sum += e[i];
        e[5 + payload] = uint8_t(0x100 - sum);    // DisplayID section checksum
        checksum(e);
    }
    return true;
}
}
