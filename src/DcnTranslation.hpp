#ifndef RAPHAEL_DCN_TRANSLATION_HPP
#define RAPHAEL_DCN_TRANSLATION_HPP
// Apple's display core programs DCN 3.02 (Navi 23) register indices. Raphael is
// DCN 3.1.5 with the same base segments; most indices are unchanged, the rest moved
// or do not exist. translate() maps one 3.0.2 dword index onto the silicon.
#include <stddef.h>
#include <stdint.h>
#include "DcnTranslationTable.hpp"

namespace RaphaelDcn {

enum class Action : uint8_t { Pass, Move, Drop };

struct Mapping {
    Action action;
    uint32_t index;   // index to access; meaningless for Drop
};

inline Mapping translate(const XlatEntry *table, size_t count, uint32_t index) {
    size_t lo = 0, hi = count;
    while (lo < hi) {
        const size_t mid = lo + (hi - lo) / 2;
        if (table[mid].from < index) lo = mid + 1;
        else hi = mid;
    }
    if (lo < count && table[lo].from == index)
        return table[lo].kind == kXlatMove ? Mapping{Action::Move, table[lo].to}
                                           : Mapping{Action::Drop, index};
    return Mapping{Action::Pass, index};
}

inline Mapping translate(uint32_t index) {
    return translate(kDcn302To315, sizeof(kDcn302To315) / sizeof(kDcn302To315[0]), index);
}

// Bounded first-occurrence filter for access tracing: remembers up to `Slots` distinct
// keys and how often each was seen, so loops that rewrite one register (LUTs, polls)
// log a few samples instead of flooding the serial console.
template<size_t Slots>
class AccessCounter {
public:
    // Returns the occurrence number of `key` (1 for the first), or 0 when the table is full
    // and `key` is new.
    uint32_t note(uint32_t key) {
        const uint32_t stored = key + 1;   // 0 marks an empty slot
        size_t slot = (key * 2654435761u) % Slots;
        for (size_t probe = 0; probe < Slots; probe++, slot = (slot + 1) % Slots) {
            if (keys_[slot] == stored) return ++counts_[slot];
            if (keys_[slot] == 0) {
                if (used_ * 4 >= Slots * 3) return 0;
                keys_[slot] = stored;
                used_++;
                return counts_[slot] = 1;
            }
        }
        return 0;
    }
    size_t used() const { return used_; }

private:
    uint32_t keys_[Slots] {};
    uint32_t counts_[Slots] {};
    size_t used_ = 0;
};

inline uint32_t accessKey(uint32_t index, bool write) { return (index << 1) | (write ? 1u : 0u); }

// ---- registers whose fields moved ----

inline const FieldRemap *fieldRemap(const FieldRemap *table, size_t count, uint32_t index) {
    for (size_t i = 0; i < count; i++)
        if (table[i].from == index) return &table[i];
    return nullptr;
}

inline const FieldRemap *fieldRemap(uint32_t index) {
    return fieldRemap(kDcn302FieldRemaps, sizeof(kDcn302FieldRemaps) / sizeof(kDcn302FieldRemaps[0]),
                      index);
}

inline uint32_t fieldMask(uint8_t shift, uint8_t width) {
    return (width >= 32 ? 0xffffffffu : ((1u << width) - 1)) << shift;
}

// A 3.0.2-layout value written over the current 3.1.5 register: moved fields are placed
// at their new positions and 3.1.5 bits no 3.0.2 field covers keep their current value.
inline uint32_t remapWrite(const FieldRemap &remap, uint32_t value302, uint32_t current315) {
    uint32_t out = current315;
    for (uint8_t i = 0; i < remap.count; i++) {
        const FieldMove &f = remap.fields[i];
        out &= ~fieldMask(f.toShift, f.width);
        out |= ((value302 >> f.fromShift) & fieldMask(0, f.width)) << f.toShift;
    }
    return out;
}

inline uint32_t remapRead(const FieldRemap &remap, uint32_t value315) {
    uint32_t out = 0;
    for (uint8_t i = 0; i < remap.count; i++) {
        const FieldMove &f = remap.fields[i];
        out |= ((value315 >> f.toShift) & fieldMask(0, f.width)) << f.fromShift;
    }
    return out;
}

// DMCUB_SOFT_RESET is DMCUB_CNTL bit 17 on 3.0.2 and DMCUB_CNTL2 bit 0 on 3.1.5.
static constexpr uint32_t kDmcubCntlSoftReset302 = 1u << 17;
static constexpr uint32_t kDmcubCntl2SoftReset = 1u << 0;

// ---- Navi 2x DAL SMU mailbox ----
// Apple's dcn30 clock manager messages the dGPU DALSMC mailbox directly (message 0x1628a,
// argument 0x16273, response 0x16274). Raphael's PMFW has no such mailbox and the same
// message ids mean different things on its display mailbox, so these registers must never
// reach the silicon. The emulation answers every message as failed: GetSmuVersion failing
// makes the clock manager treat the SMU as absent.
class DalMailbox {
public:
    static constexpr uint32_t kMessage = 0x1628a, kArgument = 0x16273, kResponse = 0x16274;
    static constexpr uint32_t kResultOk = 1, kResultFailed = 0xff;

    static bool owns(uint32_t index) {
        return index == kMessage || index == kArgument || index == kResponse;
    }
    uint32_t read(uint32_t index) const {
        return index == kResponse ? response_ : index == kArgument ? argument_ : message_;
    }
    // Returns true when the write submitted a message (message() / argument() describe it).
    bool write(uint32_t index, uint32_t value) {
        if (index == kArgument) { argument_ = value; return false; }
        if (index == kResponse) { response_ = value; return false; }
        message_ = value;
        response_ = kResultFailed;
        return true;
    }
    uint32_t message() const { return message_; }
    uint32_t argument() const { return argument_; }

private:
    uint32_t message_ = 0, argument_ = 0, response_ = kResultOk;   // idle mailbox reads ready
};

}  // namespace RaphaelDcn
#endif
