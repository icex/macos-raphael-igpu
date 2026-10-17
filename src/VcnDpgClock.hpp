#pragma once
#include <stdint.h>

namespace RaphaelVcnDpg {
// HWLibs 24G830 secure SRAM caller +0x94043 reuses CGC_CTRL's timer
// value for CGC_GATE. Native unsecure DPG and Linux use CGC_GATE=0.
inline uint32_t clockGateValue(bool target, bool secureCaller, uint32_t version,
                               uint32_t bank, uint32_t reg, uint32_t value) {
    if (target && secureCaller && version == 0x30001 && bank == 1 && reg == 0x88 &&
        (value == 0x104 || value == 0x105)) return 0;
    return value;
}
}
