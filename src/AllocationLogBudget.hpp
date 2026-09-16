#pragma once
#include <stdint.h>
#include <stddef.h>

namespace RaphaelAllocationLog {
// Keep initial failure detail and periodic cumulative counts. No allocation or lock.
inline bool emit(uint64_t failures) {
    return failures != 0 && (failures <= 8 || failures % 1024 == 0);
}
// A CALL rel32 must remain a CALL: preserve the native return address and ABI.
inline bool makeCall(uint64_t site, uint64_t destination, uint8_t (&bytes)[5]) {
    if (site > UINT64_MAX - 5) return false;
    const uint64_t next = site + 5;
    int64_t delta;
    if (destination >= next) {
        if (destination - next > 0x7fffffffULL) return false;
        delta = static_cast<int64_t>(destination - next);
    } else {
        if (next - destination > 0x80000000ULL) return false;
        delta = -static_cast<int64_t>(next - destination);
    }
    const uint32_t displacement = static_cast<uint32_t>(delta);
    bytes[0] = 0xe8;
    for (unsigned i = 0; i < 4; ++i)
        bytes[i + 1] = static_cast<uint8_t>(displacement >> (i * 8));
    return true;
}
}
