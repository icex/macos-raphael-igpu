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

static constexpr size_t kPreparedRequestDwords = 0x54 / sizeof(uint32_t);
static constexpr size_t kInvalidateInfoDwords = 0x28 / sizeof(uint32_t);

struct PreparedRequest {
    bool valid;
    uint32_t sequence;
    uintptr_t threadToken;
    InvalidateRequest request;
    bool alternate;
    bool rootRepaired;
    bool preparedRootMatches;
    uint64_t nativeRoot;
    uint32_t repairReason;
    uint32_t infoWords[kInvalidateInfoDwords];
    uint32_t words[kPreparedRequestDwords];
};

enum class RootRepairReason : uint32_t {
    InvalidInput,
    Disabled,
    TargetUnmarked,
    WrongHub,
    WrongVmid,
    NotReprogrammed,
    InvalidAperture,
    SystemRoot,
    UnsupportedFlags,
    AlreadyPhysical,
    OutsideFramebuffer,
    Overflow,
    Repaired,
};

struct LocalInvalidateInfo {
    bool valid;
    bool eligible;
    bool repaired;
    uint64_t originalRoot;
    uint64_t nativeRoot;
    RootRepairReason reason;
    alignas(uint64_t) uint8_t bytes[0x28];
};

struct FramebufferAperture {
    uint64_t mcBase;
    uint64_t mcTop;
    uint64_t physicalBase;
    uint64_t visibleBytes;
};

struct PageTableEntry {
    bool valid;
    bool system;
    bool snooped;
    bool executable;
    bool readable;
    bool writeable;
    bool pdeAsPte;
    bool translateFurther;
    bool childConverted;
    uint32_t level;
    uint64_t index;
    uint64_t tablePhysical;
    uint64_t raw;
    uint64_t address;
};

struct PageTableWalk {
    bool valid;
    bool complete;
    uint32_t count;
    PageTableEntry entries[4];
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

enum class InvalidateRegisterKind : uint32_t { Unknown, Semaphore, Request, Acknowledge };
struct InvalidateRegister {
    bool valid;
    InvalidateRegisterKind kind;
    uint32_t engine;
};

struct InvalidateRegisterSample {
    InvalidateRegister decoded;
    uint32_t mmioRegister;
    uint32_t value;
    bool read;
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

inline void writeU64(uint8_t *bytes, uint64_t value) {
    for (size_t i = 0; i < sizeof(value); ++i)
        bytes[i] = static_cast<uint8_t>(value >> (i * 8));
}

inline InvalidateRequest observeInvalidateRequest(const uint8_t *bytes, size_t size);

inline bool validAperture(const FramebufferAperture &aperture) {
    return aperture.mcBase != 0 && aperture.physicalBase != 0 &&
        aperture.mcTop >= aperture.mcBase && aperture.visibleBytes >= 8 &&
        (aperture.mcBase & 0xfff) == 0 && (aperture.physicalBase & 0xfff) == 0 &&
        aperture.mcBase <= 0x0000ffffffffffffULL &&
        aperture.physicalBase <= 0x0000ffffffffffffULL &&
        aperture.visibleBytes - 1 <= aperture.mcTop - aperture.mcBase &&
        aperture.visibleBytes - 1 <= 0x0000ffffffffffffULL - aperture.physicalBase;
}

// X6000's getPDEValue retains bits 47:6 of an allocation address and adds
// VALID. Some captured roots also carry CACHE (bit 2), while candidate 179's
// native VMID2 request carried no low attributes and X6000 copied that raw
// root into its PTB register words. Preserve those observed forms and reject
// every other one, especially SYSTEM. The caller's 0x28-byte object is copied
// before any edit.
inline LocalInvalidateInfo prepareInvalidateInfo(
    const uint8_t *source, size_t size, bool enabled, bool markedRaphael,
    uint32_t rawFbBase, uint32_t rawFbTop, uint32_t rawFbOffset) {
    LocalInvalidateInfo result {};
    result.reason = RootRepairReason::InvalidInput;
    if (source == nullptr || size < sizeof(result.bytes)) return result;
    for (size_t i = 0; i < sizeof(result.bytes); ++i) result.bytes[i] = source[i];
    result.valid = true;
    const auto request = observeInvalidateRequest(source, size);
    result.originalRoot = request.root;
    result.nativeRoot = request.root;
    if (!enabled) { result.reason = RootRepairReason::Disabled; return result; }
    if (!markedRaphael) {
        result.reason = RootRepairReason::TargetUnmarked; return result;
    }
    if (!request.valid) return result;
    if (request.hub != 0) { result.reason = RootRepairReason::WrongHub; return result; }
    if (request.vmid != 2) { result.reason = RootRepairReason::WrongVmid; return result; }
    if (!request.reprogram) {
        result.reason = RootRepairReason::NotReprogrammed; return result;
    }
    if (rawFbBase == 0 || rawFbOffset == 0 || rawFbTop < rawFbBase ||
        ((rawFbBase | rawFbTop | rawFbOffset) & 0xff000000u)) {
        result.reason = RootRepairReason::InvalidAperture; return result;
    }

    constexpr uint64_t pdeAddressMask = 0x0000ffffffffffc0ULL;
    const uint64_t attributes = request.root & ~pdeAddressMask;
    if ((attributes & (1ULL << 1)) != 0) {
        result.reason = RootRepairReason::SystemRoot; return result;
    }
    if (attributes != 0 && attributes != 1 && attributes != 5) {
        result.reason = RootRepairReason::UnsupportedFlags; return result;
    }
    const uint64_t address = request.root & pdeAddressMask;
    const uint64_t mcBase = static_cast<uint64_t>(rawFbBase) << 24;
    const uint64_t mcTop = (static_cast<uint64_t>(rawFbTop) << 24) | 0xffffffULL;
    const uint64_t physicalBase = static_cast<uint64_t>(rawFbOffset) << 24;
    if (address >= physicalBase && address <=
        physicalBase + (mcTop - mcBase)) {
        result.reason = RootRepairReason::AlreadyPhysical; return result;
    }
    if (address < mcBase || address > mcTop) {
        result.reason = RootRepairReason::OutsideFramebuffer; return result;
    }
    if (address - mcBase > 0x0000ffffffffffffULL - physicalBase) {
        result.reason = RootRepairReason::Overflow; return result;
    }

    const uint64_t physical = physicalBase + (address - mcBase);
    if (physical > pdeAddressMask) {
        result.reason = RootRepairReason::Overflow; return result;
    }
    result.eligible = true;
    result.repaired = true;
    result.nativeRoot = physical | attributes;
    result.reason = RootRepairReason::Repaired;
    writeU64(result.bytes + 0x18, result.nativeRoot);
    return result;
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

// AMDGFX10VMM::prepareVMInvalidateRequest fills this 0x54-byte request before
// the SDMA channel patches its VM-program packet. Copy both the immutable input
// and the native output so the observation remains useful after the callback.
inline PreparedRequest observePreparedRequest(const uint8_t *info, size_t infoSize,
                                              const uint8_t *nativeInfo,
                                              size_t nativeInfoSize,
                                              const uint8_t *prepared,
                                              size_t preparedSize, bool alternate,
                                              bool rootRepaired,
                                              RootRepairReason repairReason) {
    PreparedRequest result {};
    result.request = observeInvalidateRequest(info, infoSize);
    result.alternate = alternate;
    const auto nativeRequest = observeInvalidateRequest(nativeInfo, nativeInfoSize);
    if (!result.request.valid || !nativeRequest.valid || prepared == nullptr ||
        preparedSize < 0x54)
        return result;
    result.rootRepaired = rootRepaired;
    result.nativeRoot = nativeRequest.root;
    result.repairReason = static_cast<uint32_t>(repairReason);
    for (size_t i = 0; i < kInvalidateInfoDwords; ++i)
        result.infoWords[i] = readU32(info + i * sizeof(uint32_t));
    for (size_t i = 0; i < kPreparedRequestDwords; ++i)
        result.words[i] = readU32(prepared + i * sizeof(uint32_t));
    result.preparedRootMatches =
        ((static_cast<uint64_t>(result.words[3]) << 32) | result.words[1]) ==
            result.nativeRoot;
    result.valid = true;
    return result;
}

inline uint64_t physicalTableAddress(uint64_t address,
                                     const FramebufferAperture &aperture) {
    if (!validAperture(aperture) || (address & 0x3f) != 0) return 0;
    if (address >= aperture.physicalBase &&
        address - aperture.physicalBase <= aperture.visibleBytes - 8)
        return address;
    if (address >= aperture.mcBase && address <= aperture.mcTop &&
        address - aperture.mcBase <= aperture.visibleBytes - 8)
        return aperture.physicalBase + (address - aperture.mcBase);
    return 0;
}

inline PageTableEntry decodePageTableEntry(uint64_t tablePhysical, uint32_t level,
                                           uint64_t index, uint64_t raw) {
    const bool pdeAsPte = (raw & (1ULL << 54)) != 0;
    const bool leaf = level == 0 || pdeAsPte;
    return PageTableEntry {
        (raw & (1ULL << 0)) != 0,
        (raw & (1ULL << 1)) != 0,
        (raw & (1ULL << 2)) != 0,
        (raw & (1ULL << 4)) != 0,
        (raw & (1ULL << 5)) != 0,
        (raw & (1ULL << 6)) != 0,
        pdeAsPte,
        (raw & (1ULL << 56)) != 0,
        false, level, index, tablePhysical, raw,
        raw & (leaf ? 0x0000fffffffff000ULL : 0x0000ffffffffffc0ULL)
    };
}

// PAGE_TABLE_DEPTH is the number of PDE levels above the leaf PTB. Hardware
// encodes the leaf width as PAGE_TABLE_BLOCK_SIZE + 9; intermediate directories
// consume 9 bits, while the root consumes all remaining high PFN bits. The root
// and each child table must be CPU-visible through BAR0 before one qword is read.
// Data-page leaf addresses and the submitted VA are diagnostic values only and
// are never translated by this helper.
template <typename Read64>
inline PageTableWalk walkPageTables(uint64_t root, uint32_t control, uint64_t va,
                                    const FramebufferAperture &aperture,
                                    Read64 read64) {
    PageTableWalk result {};
    const uint32_t depth = (control >> 1) & 3u;
    const uint32_t encodedBlockSize = (control >> 3) & 0xfu;
    constexpr uint64_t pdeAddressMask = 0x0000ffffffffffc0ULL;
    const uint64_t rootFlags = root & ~pdeAddressMask;
    if ((control & 1u) == 0 || va > 0x0000ffffffffffffULL ||
        (rootFlags != 1 && rootFlags != 5) || !validAperture(aperture))
        return result;
    uint64_t table = physicalTableAddress(root & pdeAddressMask, aperture);
    if (table == 0) return result;
    result.valid = true;
    const uint32_t leafWidth = depth == 0 ? 36u : encodedBlockSize + 9u;
    const uint64_t leafMask = (1ULL << leafWidth) - 1;
    for (int level = static_cast<int>(depth); level >= 0; --level) {
        const uint32_t unsignedLevel = static_cast<uint32_t>(level);
        const uint32_t shift = level == 0
            ? 12u
            : 12u + leafWidth + (unsignedLevel - 1u) * 9u;
        if (shift >= 48) { result.valid = false; return result; }
        const uint64_t index = level == 0
            ? (va >> shift) & leafMask
            : unsignedLevel == depth
                ? va >> shift
                : (va >> shift) & 0x1ffu;
        if (index > (aperture.visibleBytes - 8) / 8 ||
            table < aperture.physicalBase ||
            table - aperture.physicalBase > aperture.visibleBytes - 8 -
                static_cast<uint64_t>(index) * 8) {
            result.valid = false;
            return result;
        }
        uint64_t raw = 0;
        if (!read64(table + static_cast<uint64_t>(index) * 8, raw)) {
            result.valid = false;
            return result;
        }
        auto &entry = result.entries[result.count++];
        entry = decodePageTableEntry(table, static_cast<uint32_t>(level), index, raw);
        if (!entry.valid) return result;
        if (entry.translateFurther) return result;
        if (level == 0 || entry.pdeAsPte) {
            result.complete = true;
            return result;
        }
        if (entry.system) return result;
        const uint64_t child = physicalTableAddress(entry.address, aperture);
        if (child == 0) return result;
        entry.childConverted = child != entry.address;
        table = child;
    }
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

constexpr InvalidateRegister decodeInvalidateRegister(
    uint32_t reg, uint32_t semaphore0, uint32_t request0, uint32_t acknowledge0,
    uint32_t engines = 18) {
    return reg >= semaphore0 && reg - semaphore0 < engines
        ? InvalidateRegister {true, InvalidateRegisterKind::Semaphore, reg - semaphore0}
        : reg >= request0 && reg - request0 < engines
            ? InvalidateRegister {true, InvalidateRegisterKind::Request, reg - request0}
            : reg >= acknowledge0 && reg - acknowledge0 < engines
                ? InvalidateRegister {true, InvalidateRegisterKind::Acknowledge,
                                      reg - acknowledge0}
                : InvalidateRegister {false, InvalidateRegisterKind::Unknown, 0};
}

// Invalidate semaphore reads can acquire ownership; do not sample them
// diagnostically. Unknown register roles are also refused.
template <typename Reader>
inline InvalidateRegisterSample sampleInvalidateRegister(
    uint32_t mmioRegister, InvalidateRegister decoded, Reader reader) {
    InvalidateRegisterSample result {decoded, mmioRegister, 0, false};
    if (!decoded.valid || decoded.kind == InvalidateRegisterKind::Semaphore)
        return result;
    result.value = reader(mmioRegister);
    result.read = true;
    return result;
}

// AMDGFX10VMM::getPDEValue and getPTEValue keep the address bits they receive and
// only add attribute bits. Apple's video-memory objects carry framebuffer MC
// addresses, while the GFXHUB walker consumes physical table and page addresses:
// Linux applies amdgpu_gmc_vram_mc2pa to every non-SYSTEM PDE and VRAM PTE, and
// candidate 180 proved the same rule for the VMID2 root (prepared 0x84b6f3000
// matched the live register; the walker then faulted one level below). Convert
// only an address inside the MC aperture. Physical, system, unrelated and
// invalid-aperture inputs pass through unchanged.
enum class EntryDomain : uint32_t {
    Converted = 0,
    AlreadyPhysical = 1,
    Outside = 2,
    System = 3,
    InvalidAperture = 4,
};
static constexpr size_t kEntryDomainCount = 5;

enum class EntryKind : uint32_t { Pde = 0, Pte = 1 };

struct EntryConversionSample {
    EntryKind kind;
    uint32_t level;
    uint32_t flags;
    uint64_t original;
    uint64_t result;
};

inline EntryDomain convertEntryAddress(uint64_t address, bool system,
                                       uint32_t rawFbBase, uint32_t rawFbTop,
                                       uint32_t rawFbOffset, uint64_t &result) {
    result = address;
    if (system) return EntryDomain::System;
    if (rawFbBase == 0 || rawFbOffset == 0 || rawFbTop < rawFbBase ||
        ((rawFbBase | rawFbTop | rawFbOffset) & 0xff000000u))
        return EntryDomain::InvalidAperture;
    const uint64_t mcBase = static_cast<uint64_t>(rawFbBase) << 24;
    const uint64_t mcTop = (static_cast<uint64_t>(rawFbTop) << 24) | 0xffffffULL;
    const uint64_t physicalBase = static_cast<uint64_t>(rawFbOffset) << 24;
    if (address >= physicalBase && address <= physicalBase + (mcTop - mcBase))
        return EntryDomain::AlreadyPhysical;
    if (address < mcBase || address > mcTop) return EntryDomain::Outside;
    const uint64_t offset = address - mcBase;
    if (offset > 0x0000ffffffffffffULL - physicalBase) return EntryDomain::InvalidAperture;
    result = physicalBase + offset;
    return EntryDomain::Converted;
}

inline const char *entryDomainName(EntryDomain domain) {
    switch (domain) {
        case EntryDomain::Converted: return "converted";
        case EntryDomain::AlreadyPhysical: return "physical";
        case EntryDomain::Outside: return "outside";
        case EntryDomain::System: return "system";
        case EntryDomain::InvalidAperture: return "invalid-aperture";
    }
    return "unknown";
}

constexpr uint64_t join(uint32_t lo, uint32_t hi) {
    return (static_cast<uint64_t>(hi) << 32) | lo;
}

constexpr uint64_t decodeFaultAddress(uint32_t logicalPageLo, uint32_t logicalPageHi) {
    return join(logicalPageLo, logicalPageHi & 0xfu) << 12;
}

} // namespace RaphaelVm
