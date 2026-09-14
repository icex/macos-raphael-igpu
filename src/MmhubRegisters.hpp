#pragma once
#include <stddef.h>
#include <stdint.h>

namespace RaphaelMmhub {
// X6000 24G830: AMDGFX10VMM::fillVMRegisters places hub1 at +0xef8.
// AMDMMHub_2_0_0::fillVMRegisters builds 12 globals, 16*7 context registers,
// then 18*5 invalidation-engine registers (0x358 bytes). They are register
// indices, not register contents. MMHUB2.4.1 uses Linux's mmhub2.3 layout.
constexpr size_t kWords = 0x358 / 4;
constexpr size_t kHub1Offset = 0xef8;
constexpr uint32_t kNativeBase = 0x13200; // discovery segment0
constexpr uint32_t kRaphaelBase = 0x1a000; // discovery segment1

inline uint32_t registerAt(size_t word, bool corrected) {
    if (word >= kWords) return 0;
    constexpr uint32_t oldGlobals[12] = {
        0x873,0x680,0x681,0x682,0x698,0x688,0x689,0x68a,0x68b,0x68c,0x68d,0x68e};
    constexpr uint32_t newGlobals[12] = {
        0x8f3,0x700,0x701,0x702,0x718,0x708,0x709,0x70a,0x70b,0x70c,0x70d,0x70e};
    const uint32_t base = corrected ? kRaphaelBase : kNativeBase;
    if (word < 12) return base + (corrected ? newGlobals[word] : oldGlobals[word]);
    if (word < 124) {
        const uint32_t vmid = (word-12)/7, field = (word-12)%7;
        constexpr uint32_t oldContext[7] = {0x72b,0x72c,0x74b,0x74c,0x76b,0x76c,0x6c0};
        constexpr uint32_t newContext[7] = {0x940,0x941,0x942,0x943,0x944,0x945,0x740};
        return base + (corrected ? newContext[field] : oldContext[field]) +
            vmid*(field==6 ? 1 : corrected ? 8 : 2);
    }
    const uint32_t engine = (word-124)/5, field = (word-124)%5;
    constexpr uint32_t oldEngine[5] = {0x707,0x708,0x6e3,0x6f5,0x6d1};
    constexpr uint32_t newEngine[5] = {0xa03,0xa04,0xa01,0xa02,0xa00};
    return base + (corrected ? newEngine[field] : oldEngine[field]) +
        engine*(corrected ? 8 : field<2 ? 2 : 1);
}

enum class Result : uint32_t { Disabled, Invalid, Mismatch, AlreadyCorrect, Repaired };
// Validate all fields before the first write. Never partly repair an unknown ABI.
inline Result repair(uint32_t *table, size_t bytes, bool enabled, bool target) {
    if (!enabled || !target) return Result::Disabled;
    if (!table || bytes != kWords*4) return Result::Invalid;
    bool oldMatch=true, newMatch=true;
    for(size_t i=0;i<kWords;i++) {
        oldMatch &= table[i]==registerAt(i,false);
        newMatch &= table[i]==registerAt(i,true);
    }
    if (newMatch) return Result::AlreadyCorrect;
    if (!oldMatch) return Result::Mismatch;
    for(size_t i=0;i<kWords;i++) table[i]=registerAt(i,true);
    return Result::Repaired;
}
}
