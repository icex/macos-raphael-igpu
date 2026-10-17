#pragma once
#include <stdint.h>

namespace RaphaelDmubRing {
struct Result { bool matched, restored; };
// Caller proves this 64-byte slot is unsubmitted, mapped, and reserved.
// Never updates the producer pointer. Restore even when readback fails.
template <typename Read, typename Write>
Result probe(uint64_t slot, Read read, Write write) {
    uint32_t saved[16];
    for (unsigned d = 0; d < 16; d++) saved[d] = read(slot + 4*d);
    Result result {true, true};
    for (unsigned pass = 0; pass < 2; pass++) {
        for (unsigned d = 0; d < 16; d++)
            write(slot + 4*d, (0x5a3cc300u ^ (0x01010101u*d)) ^ (pass ? 0xffffffffu : 0));
        __sync_synchronize();
        for (unsigned d = 0; d < 16; d++)
            if (read(slot + 4*d) != ((0x5a3cc300u ^ (0x01010101u*d)) ^ (pass ? 0xffffffffu : 0)))
                result.matched = false;
    }
    for (unsigned d = 0; d < 16; d++) write(slot + 4*d, saved[d]);
    __sync_synchronize();
    for (unsigned d = 0; d < 16; d++)
        if (read(slot + 4*d) != saved[d]) result.restored = false;
    return result;
}
}
