#pragma once

#include <stddef.h>
#include <stdint.h>

// rgpuhangdump=1 (candidate 212): address and packet arithmetic for the graphics
// ring hang dump. The kext only reads registers and memory; nothing here writes.
namespace RaphaelHang {

static constexpr uint64_t kMaxGpuAddress = 0x0000ffffffffffffULL;

struct RingGeometry {
    bool valid;
    uint64_t va;
    uint32_t dwords;
};

// gfx_v10_0_cp_gfx_resume writes gpu_addr >> 8 into CP_RB0_BASE/BASE_HI and
// RB_BUFSZ = order_base_2(ring_size / 8), so the ring holds 2 << RB_BUFSZ dwords.
inline RingGeometry ringGeometry(uint32_t baseLo, uint32_t baseHi, uint32_t cntl) {
    RingGeometry result {false, 0, 0};
    const uint32_t bufsz = cntl & 0x3fu;
    const uint64_t encoded = (static_cast<uint64_t>(baseHi) << 32) | baseLo;
    if (bufsz == 0 || bufsz > 22 || encoded == 0 || (encoded >> 40) != 0) return result;
    const uint64_t va = encoded << 8;
    const uint32_t dwords = 2u << bufsz;
    if (va > kMaxGpuAddress - (static_cast<uint64_t>(dwords) * 4 - 1)) return result;
    return {true, va, dwords};
}

// Ring positions wrap at the (power of two) ring size.
inline uint32_t ringIndex(uint32_t position, int64_t delta, uint32_t dwords) {
    if (dwords == 0 || (dwords & (dwords - 1)) != 0) return 0;
    const uint64_t mask = dwords - 1;
    return static_cast<uint32_t>((static_cast<uint64_t>(position) +
                                  static_cast<uint64_t>(delta)) & mask);
}

// Pending ring data whose read pointer does not move across the sample window.
constexpr bool ringStalled(uint32_t rptrBefore, uint32_t wptr, uint32_t rptrAfter) {
    return rptrBefore != wptr && rptrAfter == rptrBefore;
}

enum : uint32_t {
    kPacket3IndirectBuffer = 0x3f,
    kPacket3IndirectBufferConst = 0x33,
};

struct IbPacket {
    bool valid;
    uint32_t opcode;
    uint64_t address;
    uint32_t lengthDwords;
    uint32_t vmid;
    uint32_t control;
};

// PACKET3(INDIRECT_BUFFER[_CONST], 2): address low (bit 1:0 swap), address high,
// control = length_dw | vmid << 24 (gfx_v10_0_ring_emit_ib_gfx).
inline IbPacket parseIndirectBuffer(const uint32_t *words, size_t count, size_t at) {
    IbPacket result {false, 0, 0, 0, 0, 0};
    if (words == nullptr || at >= count || count - at < 4) return result;
    const uint32_t header = words[at];
    const uint32_t opcode = (header >> 8) & 0xffu;
    if ((header >> 30) != 3u || ((header >> 16) & 0x3fffu) != 2u || (header & 0xffu) != 0 ||
        (opcode != kPacket3IndirectBuffer && opcode != kPacket3IndirectBufferConst))
        return result;
    const uint64_t address = ((static_cast<uint64_t>(words[at + 2]) << 32) | words[at + 1]) &
                             ~3ULL;
    const uint32_t control = words[at + 3];
    const uint32_t length = control & 0xfffffu;
    if (address == 0 || address > kMaxGpuAddress || length == 0) return result;
    return {true, opcode, address, length, (control >> 24) & 0xfu, control};
}

// CP_IB1_BASE may name the buffer start or the current fetch position; accept both.
inline bool packetCoversBase(const IbPacket &packet, uint32_t baseLo, uint32_t baseHi) {
    if (!packet.valid) return false;
    const uint64_t base = ((static_cast<uint64_t>(baseHi) << 32) | baseLo) & ~3ULL;
    const uint64_t bytes = static_cast<uint64_t>(packet.lengthDwords) * 4;
    return base >= packet.address && base - packet.address <= bytes;
}

struct DumpWindow {
    bool valid;
    uint32_t first;
    uint32_t count;
};

// A window [cursor - before, cursor + after) clipped to [0, length). A zero
// length means the buffer size is unknown and only the lower bound applies.
inline DumpWindow windowAround(uint64_t cursor, uint32_t before, uint32_t after,
                               uint32_t length) {
    DumpWindow result {false, 0, 0};
    if (length != 0 && cursor > length) return result;
    const uint64_t first = cursor > before ? cursor - before : 0;
    uint64_t end = cursor + after;
    if (length != 0 && end > length) end = length;
    if (end <= first || first > UINT32_MAX || end - first > UINT32_MAX) return result;
    return {true, static_cast<uint32_t>(first), static_cast<uint32_t>(end - first)};
}

// Two readings of the PFP position inside an IB: CP_IBn_OFFSET as dwords from the
// start, and length minus CP_IBn_BUFSZ if BUFSZ counts the remaining dwords.
struct IbCursor {
    bool offsetValid;
    uint32_t offset;
    bool remainingValid;
    uint32_t remaining;
};

inline IbCursor ibCursor(uint32_t offsetRegister, uint32_t bufszRegister, uint32_t length) {
    IbCursor result {false, 0, false, 0};
    if (length == 0 || offsetRegister <= length) {
        result.offsetValid = true;
        result.offset = offsetRegister;
    }
    if (length != 0 && bufszRegister <= length) {
        result.remainingValid = true;
        result.remaining = length - bufszRegister;
    }
    return result;
}

// Size of the span one entry maps. Mirrors RaphaelVm::walkPageTables: the leaf
// level indexes 4 KiB pages; a level-L directory entry spans 2^shift(L) bytes.
inline uint32_t entryShift(uint32_t control, uint32_t level) {
    const uint32_t depth = (control >> 1) & 3u;
    const uint32_t leafWidth = depth == 0 ? 36u : ((control >> 3) & 0xfu) + 9u;
    return level == 0 ? 12u : 12u + leafWidth + (level - 1u) * 9u;
}

// Physical address of the 4 KiB page that holds relativeVa, for a leaf or a
// PDE-as-PTE entry whose address field is `address`.
inline bool leafPage(uint64_t address, uint32_t control, uint32_t level, uint64_t relativeVa,
                     uint64_t &page) {
    const uint32_t shift = entryShift(control, level);
    if (shift >= 48) return false;
    const uint64_t span = 1ULL << shift;
    const uint64_t inside = relativeVa & (span - 1) & ~0xfffULL;
    const uint64_t base = address & ~(span - 1);
    if (base > kMaxGpuAddress - inside) return false;
    page = base + inside;
    return true;
}

// A non-SYSTEM page address is either physical FB (after mc2pa) or logical MC.
inline bool framebufferOffset(uint64_t address, uint64_t mcBase, uint64_t physicalBase,
                              uint64_t visibleBytes, uint64_t &offset) {
    if (visibleBytes < 0x1000 || (address & 0xfff) != 0) return false;
    const uint64_t last = visibleBytes - 0x1000;
    if (physicalBase != 0 && address >= physicalBase && address - physicalBase <= last) {
        offset = address - physicalBase;
        return true;
    }
    if (mcBase != 0 && address >= mcBase && address - mcBase <= last) {
        offset = address - mcBase;
        return true;
    }
    return false;
}

// Dwords one packet occupies, header included; 0 for anything that is not a
// PACKET2 filler or a type-3 header. PACKET3(NOP, 0x3fff) is a one-dword filler.
inline uint32_t packetDwords(uint32_t header) {
    if (header == 0x80000000u) return 1;
    if ((header >> 30) != 3u) return 0;
    const uint32_t count = (header >> 16) & 0x3fffu;
    if (count == 0x3fffu && ((header >> 8) & 0xffu) == 0x10u) return 1;
    return count + 2;
}

enum : uint32_t { kPacket3WaitRegMem = 0x3c, kPacket3WaitRegMem64 = 0x93 };

struct WaitRegMem {
    bool valid;
    uint32_t opcode;
    uint32_t function;   // 0 always, 1 <, 2 <=, 3 ==, 4 !=, 5 >=, 6 >
    uint32_t memSpace;   // 0 register, 1 memory
    uint32_t operation;  // 0 wait, 1 write then wait
    uint32_t engine;
    uint64_t address;    // register index, or GPU address for memory
    uint32_t second;     // address high or second register
    uint32_t reference;
    uint32_t mask;
    uint32_t interval;
};

// PACKET3(WAIT_REG_MEM, 5): control, addr0, addr1, reference, mask, interval
// (gfx_v10_0_wait_reg_mem). Memory addresses are 4-byte aligned; addr1 is high.
// WAIT_REG_MEM64 has nine words and 64-bit reference/mask. Leave it to the raw
// packet dump; this parser and its consumers only evaluate 32-bit waits.
inline WaitRegMem parseWaitRegMem(const uint32_t *words, size_t count, size_t at) {
    WaitRegMem result {false, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0};
    if (words == nullptr || at >= count || count - at < 7) return result;
    const uint32_t header = words[at];
    const uint32_t opcode = (header >> 8) & 0xffu;
    if ((header >> 30) != 3u || ((header >> 16) & 0x3fffu) != 5u ||
        opcode != kPacket3WaitRegMem)
        return result;
    const uint32_t control = words[at + 1];
    result.opcode = opcode;
    result.function = control & 7u;
    result.memSpace = (control >> 4) & 3u;
    result.operation = (control >> 6) & 3u;
    result.engine = (control >> 8) & 3u;
    result.second = words[at + 3];
    result.address = result.memSpace == 1
        ? (((static_cast<uint64_t>(words[at + 3]) << 32) | words[at + 2]) & ~3ULL)
        : words[at + 2];
    result.reference = words[at + 4];
    result.mask = words[at + 5];
    result.interval = words[at + 6];
    result.valid = true;
    return result;
}

inline bool waitSatisfied(uint32_t function, uint32_t value, uint32_t reference, uint32_t mask) {
    const uint32_t v = value & mask;
    switch (function) {
        case 0: return true;
        case 1: return v < reference;
        case 2: return v <= reference;
        case 3: return v == reference;
        case 4: return v != reference;
        case 5: return v >= reference;
        case 6: return v > reference;
    }
    return false;
}

// Per-line tag for printed command-buffer dwords (tools/decode-hang-dump.py).
inline uint32_t lineChecksum(uint32_t first, const uint32_t *words, uint32_t count) {
    uint32_t sum = 0x52475055u ^ first;
    for (uint32_t i = 0; i < count; ++i) sum = (sum << 5 | sum >> 27) ^ words[i];
    return sum;
}

} // namespace RaphaelHang
