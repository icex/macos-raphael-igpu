#pragma once
#include <stdint.h>
#include <stddef.h>

// Return only an explicitly advertised HDMI Forum FRL rate (1..6).
// Do not infer DSC, chroma support or a successful trained link from this value.
static inline uint8_t hdmiFrlEdidRate(const uint8_t *edid, size_t size) {
    static const uint8_t header[] = {0,255,255,255,255,255,255,0};
    if (!edid || size < 128 || size > 2048 || size % 128) return 0;
    for (size_t i = 0; i < sizeof(header); ++i)
        if (edid[i] != header[i]) return 0;
    if ((size_t(edid[126]) + 1) * 128 != size) return 0;
    uint8_t rate = 0;
    for (size_t block = 0; block < size; block += 128) {
        uint8_t sum = 0;
        for (size_t i = 0; i < 128; ++i) sum += edid[block + i];
        if (sum) return 0;
        if (!block || edid[block] != 2) continue;
        const uint8_t *cta = edid + block;
        if (cta[1] < 3 || cta[2] < 4 || cta[2] > 127) continue;
        for (size_t pos = 4; pos < cta[2];) {
            const size_t len = cta[pos] & 31;
            if (pos + 1 + len > cta[2]) return 0;
            const uint8_t *data = cta + pos + 1;
            if ((cta[pos] >> 5) == 3 && len >= 7 &&
                data[0] == 0xd8 && data[1] == 0x5d && data[2] == 0xc4 &&
                data[3] == 1 && (data[5] & 0x80)) {
                const uint8_t advertised = data[6] >> 4;
                if (advertised > 6 || (rate && advertised != rate)) return 0;
                rate = advertised;
            }
            pos += 1 + len;
        }
    }
    return rate;
}
