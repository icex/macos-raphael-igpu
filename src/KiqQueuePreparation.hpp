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

// GFX10 encodes CP_HQD_EOP_BASE_ADDR as a 256-byte address and uses control=8
// for the 2048-byte EOP buffer allocated immediately after the MQD.  This is
// deliberately a write/readback transaction with no doorbell or MEC changes.
template <typename Read, typename Write>
bool programEopForNativeStart(Read read, Write write, uint64_t eopAddr,
                              uint32_t control = 8) {
    if (eopAddr == 0 || (eopAddr & 0xffU) != 0 || control != 8) return false;
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
