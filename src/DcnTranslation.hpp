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

// Match HDMI packing to the PHY pixel-clock resynchronizer. Linux
// dce112_program_pixel_clk_resync uses ratios0/1/2/3 for8/10/12/16bpc.
inline uint32_t hdmiPixelResync(uint32_t phy, uint32_t hdmi) {
    const uint32_t ratio = (hdmi & (1u << 24)) ? ((hdmi >> 28) & 3u) : 0u;
    return (phy & ~0x30u) | (ratio << 4);
}

// DCN31 VPG SRAM wake: disable light sleep, clear forced light sleep.
inline uint32_t wakeVpgMemory(uint32_t value) { return (value & ~0x10u) | 1u; }

// Reserve three of sixteen CRB segments only if the requested/current COMPBUF
// size agrees and leaves room. Reject inaccessible reads, configuration errors,
// or any other pipe allocation; do not resize a live allocation.
inline bool canAllocateDet0(uint32_t comp, uint32_t d0, uint32_t d1,
                            uint32_t d2, uint32_t d3) {
    return !(comp & 0x80000000u) && (comp & 31u) == ((comp >> 8) & 31u) &&
           (comp & 31u) <= 13u && d0 == 0 && d1 == 0 && d2 == 0 && d3 == 0;
}

// ---- DMCUB stays untouched ----
// The DMCUB microcontroller boots through PSP-owned code/data windows and reaches memory
// through its own secure memory unit. Starting it from the guest froze the host
// (findings/research/dcn315-dmcub-host-crash-20260917.md), so the DAL must see DMCUB as
// absent and may never write a DMCUB register.
static constexpr uint32_t kDcDmcubEnable = 1u << 16;   // CC_DC_PIPE_DIS.DC_DMCUB_ENABLE

inline bool isDmcubRegister(const uint32_t *table, size_t count, uint32_t index) {
    size_t lo = 0, hi = count;
    while (lo < hi) {
        const size_t mid = lo + (hi - lo) / 2;
        if (table[mid] < index) lo = mid + 1;
        else hi = mid;
    }
    return lo < count && table[lo] == index;
}

inline bool isDmcubRegister(uint32_t index) {
    return isDmcubRegister(kDcn302DmcubRegisters,
                           sizeof(kDcn302DmcubRegisters) / sizeof(kDcn302DmcubRegisters[0]), index);
}

// What the DAL reads from the DMCUB strap: the pipe fuses unchanged, DMCUB reported absent,
// so dmub_srv_has_hw_support() fails and no DMUB hardware initialization is attempted.
inline uint32_t maskDmcubStrap(uint32_t value) { return value & ~kDcDmcubEnable; }

// DIO memory power (dcn_3_1_5_offset.h / sh_mask.h, identical in 3.0.2). The host's DCN 3.1
// driver leaves the I2C engine memory in forced light sleep after its last transaction and
// Apple's DCN 3.0 code never wakes it, so every DDC read returns 0xff.
static constexpr uint32_t k315DioMemPwrStatus = 0x539d;      // DIO_MEM_PWR_STATUS
static constexpr uint32_t k315DioMemPwrCtrl = 0x539e;        // DIO_MEM_PWR_CTRL
static constexpr uint32_t kDioI2cLightSleepForce = 1u << 0;  // DIO_MEM_PWR_CTRL.I2C_LIGHT_SLEEP_FORCE
static constexpr uint32_t kDioI2cLightSleepDis = 1u << 1;    // DIO_MEM_PWR_CTRL.I2C_LIGHT_SLEEP_DIS
static constexpr uint32_t kDioI2cMemPwrState = 1u << 0;      // DIO_MEM_PWR_STATUS.I2C_MEM_PWR_STATE
inline uint32_t wakeDioI2c(uint32_t ctrl) { return (ctrl & ~kDioI2cLightSleepForce) | kDioI2cLightSleepDis; }

// I2C engine speed. The host's DCN 3.1 driver leaves DC_I2C_DDC1_SPEED at prescale 0x96 with
// the slow start/stop timing; Apple's DCN 3.0 code reprograms 0x78 / fast timing (it assumes a
// 12 MHz engine clock) and the EDID address is NACKed. Replaying the host value tests whether
// the bus timing is the difference. MICROSECOND_TIME_BASE_DIV tells the real engine clock.
static constexpr uint32_t k315DcI2cDdc1Speed = 0x5362;          // DC_I2C_DDC1_SPEED (same in 3.0.2)
static constexpr uint32_t k315MicrosecondTimeBaseDiv = 0x13b;   // MICROSECOND_TIME_BASE_DIV
static constexpr uint32_t kHostDdc1Speed = 0x9600102;           // prescale 150, threshold 2, timing 1

// DCHUBBUB_ARB_DRAM_STATE_CNTL (3.1.5 index). On this APU the power-management firmware
// changes DRAM clock / enters self-refresh only when the display hub allows it; with pipes
// enabled but no timing generator running it never does, and the firmware stalls. Forcing
// both allow bits keeps it moving (worst case: display underflow, not a hang).
static constexpr uint32_t k315DchubbubArbDramStateCntl = 0x39bc;
static constexpr uint32_t kDramStateForceAllow = 0x33;   // SR force value+enable, P-state force value+enable
inline uint32_t forceDramAllow(uint32_t value) { return value | kDramStateForceAllow; }
// Linux hubbub1_allow_self_refresh_control(false): SR force-enable=1, value=0.
// Retain the P-state safeguard, but active scanout must not force SR permission.
inline uint32_t scanoutDramAllow(uint32_t value, bool active) {
    const uint32_t guarded = forceDramAllow(value);
    return active ? guarded & ~1u : guarded;
}


// Verbose trace window (DCN 3.0.2 indices): the DC_I2C engine block and the DIO/GPIO pad
// registers (DDC, HPD, AUX pad control). Every access here is logged, not just the first two.
inline bool isDdcTraceWindow(uint32_t index302) {
    return (index302 >= 0x5358 && index302 <= 0x5377) || (index302 >= 0x539d && index302 <= 0x53a4) ||
           (index302 >= 0x5d89 && index302 <= 0x5ddd);
}

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
