#ifndef RAPHAEL_KIQ_QUEUE_PREPARATION_HPP
#define RAPHAEL_KIQ_QUEUE_PREPARATION_HPP

#include <stdint.h>

namespace RaphaelKiq {

enum class QueueRegister : uint8_t {
    Active,
    Dequeue,
    Rptr,
    WptrHi,
    WptrLo,
    Poll,
    Doorbell,
};

enum class HaltedRegister : uint8_t { MecControl, Active, Dequeue, Rptr, WptrHi, WptrLo, Poll, Doorbell };
constexpr uint32_t kMecHaltMask = (1U << 28) | (1U << 30);
constexpr uint64_t kNativeMecHaltCaller = 0x15073;
constexpr uint32_t kNativeMecControlRegister = 0x21b5;

inline bool preserveNativeMecHalt(uint32_t mode, bool armed, bool held,
                                  bool admission, uint64_t caller, uint32_t reg,
                                  uint32_t client, uint32_t flag, bool contextKnown,
                                  bool contextMatches) {
    return mode == 3 && armed && held && admission &&
        caller == kNativeMecHaltCaller && reg == kNativeMecControlRegister &&
        client == 0xb && flag == 1 && (!contextKnown || contextMatches);
}

struct HaltedNativeTransaction {
    uint32_t savedMecControl = 0;
    uint32_t initialWptrLo = 0;
    uint64_t expectedPq = 0;
    bool held = false;
};

inline bool haltedNativeResultVerified(bool nativeSuccess, uint32_t mec, uint32_t active,
                                       uint32_t dequeue, uint32_t mqdLo, uint32_t mqdHi,
                                       uint32_t pqLo, uint32_t pqHi, uint32_t eopLo,
                                       uint32_t eopHi, uint32_t eopControl, uint32_t rptr,
                                       uint32_t wptrHi, uint32_t wptrLo,
                                       uint64_t expectedMqd, uint64_t expectedPq,
                                       uint64_t expectedEop, uint32_t expectedWptrLo = 0,
                                       bool allowRetainedWptr = false) {
    const uint32_t values[] = {mec, active, dequeue, mqdLo, mqdHi, pqLo, pqHi, eopLo,
                               eopHi, eopControl, rptr, wptrHi, wptrLo};
    for (auto value : values)
        if (value == 0xffffffffU) return false;
    if (expectedMqd == 0 || expectedPq == 0 || expectedEop == 0) return false;
    return nativeSuccess && (mec & kMecHaltMask) == kMecHaltMask && (active & 1) &&
        dequeue == 0 && mqdLo == static_cast<uint32_t>(expectedMqd) &&
        mqdHi == static_cast<uint32_t>(expectedMqd >> 32) &&
        pqLo == static_cast<uint32_t>(expectedPq) && pqHi == static_cast<uint32_t>(expectedPq >> 32) &&
        eopLo == static_cast<uint32_t>(expectedEop >> 8) &&
        eopHi == static_cast<uint32_t>(expectedEop >> 40) && eopControl == 6 &&
        rptr == 0 && wptrHi == 0 &&
        ((allowRetainedWptr && wptrLo == expectedWptrLo) ||
         (!allowRetainedWptr && wptrLo == 0));
}

template <typename Read, typename Write, typename Delay>
bool beginHaltedNative(HaltedNativeTransaction &tx, Read read, Write write, Delay delay,
                       bool allowRetainedWptr = false) {
    tx = {};
    tx.savedMecControl = read(HaltedRegister::MecControl);
    if (tx.savedMecControl == 0xffffffffU) return false;
    write(HaltedRegister::MecControl, tx.savedMecControl | kMecHaltMask);
    delay(50);
    const uint32_t halted = read(HaltedRegister::MecControl);
    if (halted == 0xffffffffU || (halted & kMecHaltMask) != kMecHaltMask) return false;
    tx.held = true;
    if (allowRetainedWptr) {
        tx.initialWptrLo = read(HaltedRegister::WptrLo);
        if (tx.initialWptrLo == 0xffffffffU) return false;
    }
    write(HaltedRegister::Active, 0);
    write(HaltedRegister::Dequeue, 0);
    write(HaltedRegister::Rptr, 0);
    write(HaltedRegister::WptrHi, 0);
    if (!allowRetainedWptr) write(HaltedRegister::WptrLo, 0);
    const uint32_t active = read(HaltedRegister::Active);
    const uint32_t dequeue = read(HaltedRegister::Dequeue);
    const uint32_t rptr = read(HaltedRegister::Rptr);
    const uint32_t whi = read(HaltedRegister::WptrHi);
    const uint32_t wlo = read(HaltedRegister::WptrLo);
    const uint32_t poll = read(HaltedRegister::Poll);
    const uint32_t doorbell = read(HaltedRegister::Doorbell);
    if (active == 0xffffffffU || dequeue == 0xffffffffU || rptr == 0xffffffffU ||
        whi == 0xffffffffU || wlo == 0xffffffffU || poll == 0xffffffffU ||
        doorbell == 0xffffffffU || (active & 1) || dequeue || rptr || whi ||
        (poll & (1U << 31)) || (doorbell & (1U << 30)) ||
        (!allowRetainedWptr && wlo != 0) ||
        (allowRetainedWptr && wlo != tx.initialWptrLo)) return false;
    return true;
}

template <typename Read, typename Write, typename Delay>
bool releaseHaltedNative(HaltedNativeTransaction &tx, Read read, Write write,
                         Delay delay, bool nativeSuccess, bool hqdVerified) {
    if (!tx.held) return false;
    if (!nativeSuccess || !hqdVerified) {
        write(HaltedRegister::MecControl, tx.savedMecControl | kMecHaltMask);
        delay(50);
        return false;
    }
    write(HaltedRegister::MecControl, tx.savedMecControl);
    delay(50);
    if (read(HaltedRegister::MecControl) == tx.savedMecControl &&
        (read(HaltedRegister::MecControl) & kMecHaltMask) ==
            (tx.savedMecControl & kMecHaltMask)) {
        tx.held = false;
        return true;
    }
    write(HaltedRegister::MecControl, tx.savedMecControl | kMecHaltMask);
    delay(50);
    return false;
}

// Registers that must be populated after Apple's native startKIQ has created
// the HQD.  Keep this separate from QueueRegister so the mode-2 repair cannot
// accidentally enable a speculative doorbell path.
enum class EopRegister : uint8_t {
    BaseLo,
    BaseHi,
    Control,
};

struct QueueState {
    uint32_t active;
    uint32_t dequeue;
    uint32_t rptr;
    uint32_t wptrHi;
    uint32_t wptrLo;
    uint32_t poll;
    uint32_t doorbell;
};

enum class QueuePreparationStatus : uint8_t {
    Ready,
    Inaccessible,
    IngressNotDisabled,
    DequeueTimeout,
    QueueNotIdle,
    PointerResetFailed,
};

struct QueuePreparation {
    QueuePreparationStatus status;
    unsigned elapsedUs;
    QueueState state;

    bool ready() const { return status == QueuePreparationStatus::Ready; }
};

inline bool accessible(const QueueState &state) {
    return state.active != 0xffffffffU && state.dequeue != 0xffffffffU &&
        state.rptr != 0xffffffffU && state.wptrHi != 0xffffffffU &&
        state.wptrLo != 0xffffffffU && state.poll != 0xffffffffU &&
        state.doorbell != 0xffffffffU;
}

inline bool inactiveRetainedProbeEligible(bool enabled, uint64_t mqd, uint64_t eop,
                                          uint64_t plannedMqd, uint64_t plannedEop,
                                          const QueueState &state, bool leaseValid,
                                          bool ownersMatch, bool imageExact) {
    return enabled && leaseValid && ownersMatch && imageExact && accessible(state) &&
        state.active == 0 && state.dequeue == 0 && state.rptr == 0 && state.wptrHi == 0 &&
        state.wptrLo != 0 && state.wptrLo != 0xffffffffU && !(state.poll & (1U << 31)) &&
        !(state.doorbell & (1U << 30)) && mqd == plannedMqd && eop == plannedEop;
}

// A dequeue timeout may be handed to Apple's own restore/reprogram sequence only
// when every identity and ingress predicate is still true.  This predicate never
// changes queue state; callers must use a fresh post-timeout snapshot.
inline bool timeoutNativeRestoreEligible(bool enabled, uint64_t mqd,
                                         uint64_t eop, uint64_t plannedMqd,
                                         uint64_t plannedEop,
                                         const QueueState &state,
                                         bool leaseValid, bool ownersMatch,
                                         bool imageExact) {
    return enabled && leaseValid && ownersMatch && imageExact && accessible(state) &&
        (state.active & 1) && state.dequeue == 1 &&
        !(state.poll & (1U << 31)) && !(state.doorbell & (1U << 30)) &&
        mqd == plannedMqd && eop == plannedEop;
}

// GFX10 encodes CP_HQD_EOP_BASE_ADDR as a 256-byte address and uses the native
// control=6 value for the EOP buffer allocated immediately after the MQD. This is
// deliberately a write/readback transaction with no doorbell or MEC changes.
template <typename Read, typename Write>
bool programEopForNativeStart(Read read, Write write, uint64_t eopAddr,
                              uint32_t control = 6) {
    if (eopAddr == 0 || (eopAddr & 0xffU) != 0 || control != 6) return false;
    const uint64_t encoded = eopAddr >> 8;
    write(EopRegister::BaseLo, static_cast<uint32_t>(encoded));
    write(EopRegister::BaseHi, static_cast<uint32_t>(encoded >> 32));
    write(EopRegister::Control, control);
    return read(EopRegister::BaseLo) == static_cast<uint32_t>(encoded) &&
        read(EopRegister::BaseHi) == static_cast<uint32_t>(encoded >> 32) &&
        read(EopRegister::Control) == control;
}

// HWLibs 24G830 resets RPTR/WPTR only in its ACTIVE/dequeue branch. An already-inactive
// retained HQD skips those writes, then receives new MQD/PQ bases and ACTIVE=1. Normalize
// that missing branch while ingress is disabled, and fail before native activation if any
// write is inaccessible, ignored, or races with a queue-state change.
template <typename Read, typename Write, typename Delay>
QueuePreparation prepareQueueForNativeStart(Read read, Write write, Delay delay,
                                             unsigned timeoutUs = 50000,
                                             unsigned pollIntervalUs = 50) {
    auto snapshot = [&]() -> QueueState {
        return {
            read(QueueRegister::Active),
            read(QueueRegister::Dequeue),
            read(QueueRegister::Rptr),
            read(QueueRegister::WptrHi),
            read(QueueRegister::WptrLo),
            read(QueueRegister::Poll),
            read(QueueRegister::Doorbell),
        };
    };
    auto result = QueuePreparation {QueuePreparationStatus::Inaccessible, 0, snapshot()};
    if (!accessible(result.state)) return result;

    write(QueueRegister::Poll, result.state.poll & ~(1U << 31));
    write(QueueRegister::Doorbell, result.state.doorbell & ~(1U << 30));
    result.state = snapshot();
    if (!accessible(result.state)) return result;
    if ((result.state.poll & (1U << 31)) || (result.state.doorbell & (1U << 30))) {
        result.status = QueuePreparationStatus::IngressNotDisabled;
        return result;
    }

    if (result.state.active & 1) {
        write(QueueRegister::Dequeue, 1);
        while ((result.state.active & 1) && result.elapsedUs < timeoutUs) {
            const unsigned remaining = timeoutUs - result.elapsedUs;
            const unsigned interval = pollIntervalUs < remaining ? pollIntervalUs : remaining;
            if (interval == 0) break;
            delay(interval);
            result.elapsedUs += interval;
            result.state.active = read(QueueRegister::Active);
            if (result.state.active == 0xffffffffU) return result;
        }
        if (result.state.active & 1) {
            result.status = QueuePreparationStatus::DequeueTimeout;
            return result;
        }
    }

    write(QueueRegister::Dequeue, 0);
    result.state = snapshot();
    if (!accessible(result.state)) return result;
    if ((result.state.active & 1) || result.state.dequeue != 0 ||
        (result.state.poll & (1U << 31)) || (result.state.doorbell & (1U << 30))) {
        result.status = QueuePreparationStatus::QueueNotIdle;
        return result;
    }

    if (result.state.rptr != 0 || result.state.wptrHi != 0 || result.state.wptrLo != 0) {
        // This is the order used by Apple's active/dequeue branch in 24G830 HWLibs.
        write(QueueRegister::Rptr, 0);
        write(QueueRegister::WptrHi, 0);
        write(QueueRegister::WptrLo, 0);
        result.state = snapshot();
        if (!accessible(result.state)) return result;
        if ((result.state.active & 1) || result.state.dequeue != 0 ||
            (result.state.poll & (1U << 31)) || (result.state.doorbell & (1U << 30))) {
            result.status = QueuePreparationStatus::QueueNotIdle;
            return result;
        }
        if (result.state.rptr != 0 || result.state.wptrHi != 0 || result.state.wptrLo != 0) {
            result.status = QueuePreparationStatus::PointerResetFailed;
            return result;
        }
    }

    result.status = QueuePreparationStatus::Ready;
    return result;
}

}

#endif
