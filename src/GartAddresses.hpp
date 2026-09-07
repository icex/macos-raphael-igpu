#ifndef RAPHAEL_GART_ADDRESSES_HPP
#define RAPHAEL_GART_ADDRESSES_HPP
#include <stdint.h>

// GC10.3 uses logical MC addresses for queue storage, but physical framebuffer
// addresses for non-SYSTEM page-table roots. Keep BAR offsets distinct from both.
namespace RaphaelGart {
constexpr uint64_t MaxAddress = 0x0000ffffffffffffULL;
enum class MemoryForm { LegacyRelocation, NativePhysical };
struct Aperture {
    uint64_t swBase, field58, mcBase, mcTop, physicalBase, visibleBytes, delta60;
    MemoryForm form;
};
struct Range { uint64_t firstPage, lastPage; };
struct Table { uint64_t offset, bytes; };

inline bool extent(uint64_t base, uint64_t bytes) {
    return bytes != 0 && base <= MaxAddress && bytes - 1 <= MaxAddress - base;
}

// AMDHWMemory::initVRAMInfo copies physical FB base to +0x58 and computes
// +0x60 = base(+0x50) - physical(+0x58), x6 0x52804..0x52823. The legacy
// experiment instead assumed +0x58 was a BAR-to-MC relocation. Select that old
// assumption explicitly; a corrected native object must satisfy its own form.
inline bool validAperture(const Aperture &ap) {
    if (!ap.swBase || !ap.mcBase || !ap.physicalBase || ap.swBase < ap.field58 ||
        ((ap.swBase | ap.field58 | ap.mcBase | ap.physicalBase) & 0xfff) ||
        !extent(ap.swBase, ap.visibleBytes) || !extent(ap.physicalBase, ap.visibleBytes) ||
        ap.delta60 != ap.swBase - ap.field58 || ap.mcTop < ap.mcBase ||
        ap.mcTop > MaxAddress || ap.visibleBytes - 1 > ap.mcTop - ap.mcBase)
        return false;
    switch (ap.form) {
        case MemoryForm::NativePhysical:
            return ap.swBase == ap.mcBase && ap.field58 == ap.physicalBase;
        case MemoryForm::LegacyRelocation:
            return ap.delta60 == ap.mcBase;
    }
    return false;
}

// The native getter is void and stores vm+0x210. Correct only a zero
// result (or accept the already-correct value), without changing any UMA flags.
inline bool physicalFbField(uint32_t rawBase, uint32_t rawTop, uint32_t rawOffset,
                            uint64_t logicalBase, uint64_t logicalBytes,
                            uint64_t nativePhysical, uint64_t &physical) {
    if (rawBase == 0 || rawOffset == 0 || ((rawBase | rawTop | rawOffset) & 0xff000000u) ||
        rawTop < rawBase) return false;
    const uint64_t mc = static_cast<uint64_t>(rawBase) << 24;
    const uint64_t bytes = (static_cast<uint64_t>(rawTop) - rawBase + 1) << 24;
    const uint64_t pa = static_cast<uint64_t>(rawOffset) << 24;
    if (logicalBase != mc || logicalBytes > bytes || (logicalBytes & 0xfff) ||
        !extent(mc, logicalBytes) || !extent(pa, bytes) ||
        (nativePhysical != 0 && nativePhysical != pa)) return false;
    physical = pa;
    return true;
}

inline bool validRange(Range range) {
    return range.firstPage <= range.lastPage && range.lastPage <= (MaxAddress >> 12);
}

inline bool rangeFromRegisters(uint32_t startLo, uint32_t startHi,
                               uint32_t endLo, uint32_t endHi, Range &range) {
    if ((startHi | endHi) & ~0xfu) return false;
    const Range candidate { (static_cast<uint64_t>(startHi) << 32) | startLo,
                            (static_cast<uint64_t>(endHi) << 32) | endLo };
    if (!validRange(candidate)) return false;
    range = candidate;
    return true;
}

// Only flat, enabled CTX0 with a 4KiB-aligned non-SYSTEM root is understood.
// VALID and optional CACHE are the only supported low bits. Validate the entire
// inclusive table before permitting even one BAR0 read through it.
inline bool physicalTable(const Aperture &ap, Range range, uint32_t control,
                          uint64_t root, Table &table) {
    const uint64_t flags = root & 0xfff;
    if ((control & 7u) != 1u || (flags != 1 && flags != 5) || root > MaxAddress ||
        !validRange(range) || !validAperture(ap)) return false;
    const uint64_t address = root & ~0xfffULL;
    const uint64_t bytes = (range.lastPage - range.firstPage + 1) * 8;
    if (address < ap.physicalBase || bytes > ap.visibleBytes) return false;
    const uint64_t offset = address - ap.physicalBase;
    if (offset > ap.visibleBytes - bytes) return false;
    table = {offset, bytes};
    return true;
}

inline bool pteOffset(const Aperture &ap, Range range, uint32_t control, uint64_t root,
                       uint64_t va, uint64_t &offset, uint64_t &index) {
    Table table {};
    if (va > MaxAddress || !physicalTable(ap, range, control, root, table)) return false;
    const uint64_t page = va >> 12;
    if (page < range.firstPage || page > range.lastPage) return false;
    const uint64_t entry = page - range.firstPage;
    // validRange limits entry to 36 bits; physicalTable bounds its whole array.
    index = entry;
    offset = table.offset + entry * 8;
    return true;
}
}
#endif
