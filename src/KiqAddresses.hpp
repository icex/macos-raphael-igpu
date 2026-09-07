#ifndef RAPHAEL_KIQ_ADDRESSES_HPP
#define RAPHAEL_KIQ_ADDRESSES_HPP

#include <stdint.h>

namespace RaphaelKiq {
struct Addresses {
    uint64_t mqdMc;
    uint64_t eopMc;
    uint64_t imageOffset;
};

// Pure validation for Apple's one-page allocation: 2 KiB MQD followed by 2 KiB EOP.
// Accept canonical MC addresses as well, so a second preparation cannot relocate twice.
inline bool planAddresses(uint64_t swBase, uint64_t reserved, uint64_t fbBase,
                          uint64_t fbTop, uint64_t visibleBytes, uint64_t mqd,
                          uint64_t eop, Addresses &out) {
    constexpr uint64_t maxMc = 0x0000ffffffffffffULL;
    if (!swBase || !fbBase || swBase < reserved || swBase - reserved != fbBase ||
        fbTop < fbBase || fbTop > maxMc || swBase > maxMc ||
        (swBase & 0xfff) || (fbBase & 0xfff) || visibleBytes < 0x1000)
        return false;

    auto offset = [=](uint64_t address, uint64_t &value) {
        if (address >= fbBase && address <= fbTop)
            value = address - fbBase;
        else if (address >= swBase && address - swBase < visibleBytes)
            value = address - swBase;
        else
            return false;
        return value < visibleBytes && value <= fbTop - fbBase;
    };
    uint64_t mqdOffset, eopOffset;
    if (!offset(mqd, mqdOffset) || !offset(eop, eopOffset) ||
        (mqdOffset & 0xfff) || mqdOffset > visibleBytes - 0x1000 ||
        fbTop - fbBase < 0xfff || mqdOffset > fbTop - fbBase - 0xfff ||
        eopOffset != mqdOffset + 0x800)
        return false;

    out = {fbBase + mqdOffset, fbBase + eopOffset, mqdOffset};
    return true;
}
}

#endif
