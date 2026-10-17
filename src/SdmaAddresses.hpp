#pragma once

#include <stddef.h>
#include <stdint.h>

namespace RaphaelSdma {

struct SubmitInfoObservation {
    bool layoutValid;
    uint32_t vmProgramSequence;
    uint32_t eventOrder;
    uintptr_t threadToken;
    uint32_t flags;
    uint32_t vmid;
    uint32_t entries;
    uint64_t addresses[4];
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

// Exact Sequoia 24G830 AMD_SUBMIT_COMMAND_BUFFER_INFO layout used by
// AMDGFX10SDMAChannel::commitIndirectCommandBuffer. The addresses belong to
// the VMID at +4 and must remain GPU virtual addresses. This helper therefore
// observes the packet inputs without modifying any driver-owned memory.
inline SubmitInfoObservation observeSubmitInfo(
    const uint8_t *submitInfo, size_t submitInfoBytes) {
    constexpr size_t flagsOffset = 0;
    constexpr size_t vmidOffset = 4;
    constexpr size_t countOffset = 0x14;
    constexpr size_t firstAddress = 0x58;
    constexpr size_t entryStride = 0x28;
    constexpr uint32_t maxEntries = 4;
    SubmitInfoObservation result {false, 0, 0, 0, 0, 0, 0, {0, 0, 0, 0}};
    if (submitInfo == nullptr || submitInfoBytes < countOffset + sizeof(uint32_t))
        return result;

    result.flags = readU32(submitInfo + flagsOffset);
    result.vmid = readU32(submitInfo + vmidOffset);
    result.entries = readU32(submitInfo + countOffset);
    if (result.entries == 0 || result.entries > maxEntries ||
        firstAddress + static_cast<size_t>(result.entries - 1) * entryStride +
            sizeof(uint64_t) > submitInfoBytes)
        return result;

    result.layoutValid = true;
    for (uint32_t i = 0; i < result.entries; ++i)
        result.addresses[i] = readU64(
            submitInfo + firstAddress + static_cast<size_t>(i) * entryStride);
    return result;
}

} // namespace RaphaelSdma
