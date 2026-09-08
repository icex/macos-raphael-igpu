#pragma once

#include <stdint.h>

namespace RaphaelSdma {

struct AddressRepair {
    bool valid;
    bool changed;
    uint64_t address;
};

// X6000's GFX10 SDMA path retains only 36 address bits for framebuffer-backed
// indirect buffers. That is harmless on supported Navi boards, whose logical
// framebuffer aperture fits below 64 GiB. QEMU placed this Raphael BAR at
// 0xf400000000, while the GPU reaches the same bytes through the physical MC
// aperture at 0x840000000. Recognize only an address in the exact low-36-bit
// image of the software framebuffer aperture and translate its byte offset.
constexpr AddressRepair repairTruncatedFramebufferAddress(
    uint64_t address, uint64_t softwareBase, uint64_t physicalBase,
    uint64_t bytes) {
    constexpr uint64_t addressMask = (1ULL << 36) - 1;
    if (bytes == 0 || bytes > addressMask + 1 || softwareBase <= addressMask ||
        physicalBase > UINT64_MAX - bytes)
        return {false, false, address};

    if (address >= physicalBase && address - physicalBase < bytes)
        return {true, false, address};

    const uint64_t truncatedBase = softwareBase & addressMask;
    if (truncatedBase > addressMask - (bytes - 1) || address < truncatedBase ||
        address - truncatedBase >= bytes)
        return {false, false, address};

    return {true, true, physicalBase + (address - truncatedBase)};
}

} // namespace RaphaelSdma
