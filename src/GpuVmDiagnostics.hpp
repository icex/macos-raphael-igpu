#pragma once

#include <stddef.h>
#include <stdint.h>

namespace RaphaelVm {

struct InvalidateRequest {
    bool valid;
    uint32_t hub;
    uint32_t vmid;
    uint64_t start;
    uint64_t end;
    uint64_t root;
    uint32_t flags;
    bool reprogram;
};

struct ContextRegisters {
    bool valid;
    uint32_t control;
    uint32_t ptbLo;
    uint32_t ptbHi;
    uint32_t startLo;
    uint32_t startHi;
    uint32_t endLo;
    uint32_t endHi;
};

inline uint32_t readU32(const uint8_t *bytes) {
    uint32_t value = 0;
    for (size_t i = 0; i < sizeof(value); ++i)
        value |= static_cast<uint32_t>(bytes[i]) << (i * 8);
    return value;
}

inline uint64_t readU64(const uint8_t *bytes) {
    uint64_t value = 0;
    for (size_t i = 0; i < sizeof(value); ++i)
        value |= static_cast<uint64_t>(bytes[i]) << (i * 8);
    return value;
}

// prepareVMInvalidateRequest consumes exactly 0x28 bytes with this layout in
// AMDRadeonX6000 24G830. Keep it read-only: the native method remains the sole
// owner of VM programming.
inline InvalidateRequest observeInvalidateRequest(const uint8_t *bytes, size_t size) {
    InvalidateRequest result {false, 0, 0, 0, 0, 0, 0, false};
    if (bytes == nullptr || size < 0x28) return result;
    result.valid = true;
    result.hub = readU32(bytes);
    result.vmid = readU32(bytes + 4);
    result.start = readU64(bytes + 8);
    result.end = readU64(bytes + 0x10);
    result.root = readU64(bytes + 0x18);
    result.flags = readU32(bytes + 0x20);
    result.reprogram = bytes[0x24] != 0;
    return result;
}

// GC 10.3 exposes 16 contexts. Control registers have stride one; each root,
// start and end value occupies a low/high pair and therefore has stride two.
constexpr ContextRegisters contextRegisters(uint32_t vmid) {
    return vmid < 16
        ? ContextRegisters {true, 0x15fc + vmid, 0x1667 + vmid * 2,
                            0x1668 + vmid * 2, 0x1687 + vmid * 2,
                            0x1688 + vmid * 2, 0x16a7 + vmid * 2,
                            0x16a8 + vmid * 2}
        : ContextRegisters {false, 0, 0, 0, 0, 0, 0, 0};
}

constexpr uint64_t join(uint32_t lo, uint32_t hi) {
    return (static_cast<uint64_t>(hi) << 32) | lo;
}

} // namespace RaphaelVm
