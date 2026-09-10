#ifndef RAPHAEL_RECOVERY_LIFETIME_HPP
#define RAPHAEL_RECOVERY_LIFETIME_HPP

#include <stdint.h>

#include "RecoveryLease.hpp"

// Schema 3 adds a persistent lifetime state to the immutable schema-2 OWNED and
// POOL records. The integration callbacks must provide ordered, aligned 32-bit
// BAR stores plus a fence and readback. These helpers do not assume that a log
// replay or a guest shutdown is a lifecycle proof.
namespace RaphaelRecoveryV3 {

constexpr uint64_t LifetimeOffset = 0x200;
constexpr uint64_t LifetimeMagic = 0x334d4c4b55504752ULL; // "RGPUKLM3"
constexpr uint32_t LifetimeVersion = 3;
constexpr uint32_t LifetimeValid = 0x444c4156U;            // "VALD"
constexpr uint32_t LifetimeAborting = 0x47544241U;         // "ABTG"
constexpr uint32_t LifetimeAbort = 0x54524241U;            // "ABRT"
constexpr uint64_t LifetimeChecksumDomain = 0x6a09e667f3bcc909ULL;

enum LifetimeReason : uint32_t {
    LifetimeReasonNone = 0,
    LifetimeReasonDuplicateReady = 1,
    LifetimeReasonVmmRange = 2,
    LifetimeReasonPoolOwner = 3,
    LifetimeReasonDuplicatePool = 4,
};

inline bool validLifetimeReason(uint64_t reason) {
    return reason >= LifetimeReasonDuplicateReady &&
           reason <= LifetimeReasonDuplicatePool;
}

struct LifetimeStatus {
    uint64_t magic;
    uint32_t version;
    uint32_t state;
    uint64_t leaseOffset;
    uint64_t leaseEnd;
    uint64_t nonceLo;
    uint64_t nonceHi;
    uint64_t generation;
    uint64_t ownershipChecksum;
    uint64_t poolChecksum;
    uint64_t reason;
    uint64_t checksum;
};

static_assert(sizeof(LifetimeStatus) == 88,
              "host and guest lifetime layouts differ");
static_assert(LifetimeOffset >= RaphaelRecoveryV2::PoolStatusOffset +
                  sizeof(RaphaelRecoveryV2::PoolStatus) &&
              LifetimeOffset + sizeof(LifetimeStatus) <=
                  RaphaelRecoveryV2::ScratchRelative,
              "lifetime marker must stay in the free lease metadata span");

inline uint64_t checksum(const LifetimeStatus &v) {
    return LifetimeChecksumDomain ^ v.magic ^ static_cast<uint64_t>(v.version) ^
           static_cast<uint64_t>(v.state) ^ v.leaseOffset ^ v.leaseEnd ^
           v.nonceLo ^ v.nonceHi ^ v.generation ^ v.ownershipChecksum ^
           v.poolChecksum ^ v.reason;
}

inline bool validLifetimeEncoding(const LifetimeStatus &v) {
    if (v.magic != LifetimeMagic || v.version != LifetimeVersion ||
        v.checksum != checksum(v)) return false;
    if (v.state == LifetimeValid) return v.reason == LifetimeReasonNone;
    return v.state == LifetimeAbort && validLifetimeReason(v.reason);
}

inline LifetimeStatus makeValidLifetime(
    const RaphaelRecoveryV2::OwnershipDescriptor &owned,
    const RaphaelRecoveryV2::PoolStatus &pool) {
    LifetimeStatus value {
        LifetimeMagic, LifetimeVersion, LifetimeValid,
        owned.leaseOffset, owned.leaseEnd, owned.nonceLo, owned.nonceHi,
        owned.generation, owned.checksum, pool.checksum,
        LifetimeReasonNone, 0,
    };
    value.checksum = checksum(value);
    return value;
}

inline LifetimeStatus makeAbortLifetime(const LifetimeStatus &valid,
                                        LifetimeReason reason) {
    LifetimeStatus value = valid;
    value.state = LifetimeAbort;
    value.reason = reason;
    value.checksum = checksum(value);
    return value;
}

inline bool validLifetime(
    const LifetimeStatus &value,
    const RaphaelRecoveryV2::OwnershipDescriptor &owned,
    const RaphaelRecoveryV2::PoolStatus &pool, bool requireValid) {
    return RaphaelRecoveryV2::validOwnership(
               owned, owned.nonceLo, owned.nonceHi, owned.leaseEnd) &&
           RaphaelRecoveryV2::validPoolStatus(pool, owned) &&
           pool.state == RaphaelRecoveryV2::PoolActive &&
           validLifetimeEncoding(value) &&
           value.leaseOffset == owned.leaseOffset &&
           value.leaseEnd == owned.leaseEnd &&
           value.nonceLo == owned.nonceLo && value.nonceHi == owned.nonceHi &&
           value.generation == owned.generation &&
           value.ownershipChecksum == owned.checksum &&
           value.poolChecksum == pool.checksum &&
           (!requireValid || value.state == LifetimeValid);
}

// A partial initial publication has state zero. A complete final state store may
// be accepted only after the consumer independently validates full BAR readback.
template <typename Write, typename Read, typename Fence>
inline bool publishValidLifetime(const LifetimeStatus &value, Write write,
                                 Read read, Fence fence) {
    if (!validLifetimeEncoding(value) || value.state != LifetimeValid) return false;
    constexpr uint32_t count = sizeof(LifetimeStatus) / sizeof(uint32_t);
    constexpr uint32_t stateWord = 3;
    if (read(stateWord) != 0) return false;
    uint32_t words[count];
    __builtin_memcpy(words, &value, sizeof(value));
    write(stateWord, 0);
    fence();
    if (read(stateWord) != 0) return false;
    for (uint32_t i = 0; i < count; ++i)
        if (i != stateWord) write(i, words[i]);
    fence();
    write(stateWord, words[stateWord]);
    fence();
    for (uint32_t i = 0; i < count; ++i)
        if (read(i) != words[i]) return false;
    return true;
}

// The ABORTING state is stored and read back before any mutable body field. A
// stopped guest therefore exposes VALID only if the abort transition had not
// begun; every later prefix is non-authorizing. An existing ABORT is immutable.
template <typename Write, typename Read, typename Fence>
inline bool publishAbortLifetime(const LifetimeStatus &value, Write write,
                                 Read read, Fence fence) {
    if (!validLifetimeEncoding(value) || value.state != LifetimeAbort) return false;
    constexpr uint32_t count = sizeof(LifetimeStatus) / sizeof(uint32_t);
    constexpr uint32_t stateWord = 3;
    uint32_t currentWords[count];
    for (uint32_t i = 0; i < count; ++i) currentWords[i] = read(i);
    LifetimeStatus current {};
    __builtin_memcpy(&current, currentWords, sizeof(current));
    if (!validLifetimeEncoding(current) || current.state != LifetimeValid ||
        current.leaseOffset != value.leaseOffset ||
        current.leaseEnd != value.leaseEnd || current.nonceLo != value.nonceLo ||
        current.nonceHi != value.nonceHi ||
        current.generation != value.generation ||
        current.ownershipChecksum != value.ownershipChecksum ||
        current.poolChecksum != value.poolChecksum)
        return false;
    uint32_t words[count];
    __builtin_memcpy(words, &value, sizeof(value));
    write(stateWord, LifetimeAborting);
    fence();
    if (read(stateWord) != LifetimeAborting) return false;
    for (uint32_t i = 0; i < count; ++i)
        if (i != stateWord) write(i, words[i]);
    fence();
    write(stateWord, words[stateWord]);
    fence();
    for (uint32_t i = 0; i < count; ++i)
        if (read(i) != words[i]) return false;
    return true;
}

enum class GatePhase : uint32_t {
    Initial,
    PublishingValid,
    ValidAbortRequested,
    Active,
    PublishingAbort,
    Aborted,
    Poisoned,
};

enum class ValidCompletion : uint32_t { Active, AbortOwner, Poisoned };
enum class AbortRequest : uint32_t { Owner, Deferred, AlreadyBlocked };

// Phase and first abort reason share one atomic word. Competing VALID completion
// and abort requests therefore have a single winner; no late VALID transition
// can overwrite an accepted abort request.
class LifetimeGate {
public:
    bool beginValidPublication() {
        uint64_t expected = pack(GatePhase::Initial, LifetimeReasonNone);
        return __atomic_compare_exchange_n(
            &control_, &expected,
            pack(GatePhase::PublishingValid, LifetimeReasonNone), false,
            __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE);
    }

    ValidCompletion finishValidPublication(bool published) {
        for (;;) {
            uint64_t current = __atomic_load_n(&control_, __ATOMIC_ACQUIRE);
            const auto currentPhase = unpackPhase(current);
            const auto reason = unpackReason(current);
            GatePhase next;
            ValidCompletion result;
            if (currentPhase == GatePhase::PublishingValid) {
                next = published ? GatePhase::Active : GatePhase::Poisoned;
                result = published ? ValidCompletion::Active : ValidCompletion::Poisoned;
            } else if (currentPhase == GatePhase::ValidAbortRequested) {
                next = published ? GatePhase::PublishingAbort : GatePhase::Poisoned;
                result = published ? ValidCompletion::AbortOwner :
                                     ValidCompletion::Poisoned;
            } else {
                return ValidCompletion::Poisoned;
            }
            const uint64_t desired = pack(next, reason);
            if (__atomic_compare_exchange_n(&control_, &current, desired, false,
                                            __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE))
                return result;
        }
    }

    AbortRequest requestAbort(LifetimeReason reason) {
        if (!validLifetimeReason(reason)) {
            poison();
            return AbortRequest::AlreadyBlocked;
        }
        for (;;) {
            uint64_t current = __atomic_load_n(&control_, __ATOMIC_ACQUIRE);
            const auto currentPhase = unpackPhase(current);
            GatePhase next;
            AbortRequest result;
            if (currentPhase == GatePhase::PublishingValid) {
                next = GatePhase::ValidAbortRequested;
                result = AbortRequest::Deferred;
            } else if (currentPhase == GatePhase::Active) {
                next = GatePhase::PublishingAbort;
                result = AbortRequest::Owner;
            } else if (currentPhase == GatePhase::Initial) {
                next = GatePhase::Poisoned;
                result = AbortRequest::AlreadyBlocked;
            } else {
                return AbortRequest::AlreadyBlocked;
            }
            const uint64_t desired = pack(next, reason);
            if (__atomic_compare_exchange_n(&control_, &current, desired, false,
                                            __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE))
                return result;
        }
    }

    void finishAbortPublication(bool published) {
        uint64_t current = __atomic_load_n(&control_, __ATOMIC_ACQUIRE);
        while (unpackPhase(current) == GatePhase::PublishingAbort) {
            const uint64_t desired = pack(
                published ? GatePhase::Aborted : GatePhase::Poisoned,
                unpackReason(current));
            if (__atomic_compare_exchange_n(&control_, &current, desired, false,
                                            __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE))
                return;
        }
    }

    bool clientsAllowed() const {
        return phase() == GatePhase::Active;
    }

    GatePhase phase() const {
        return unpackPhase(__atomic_load_n(&control_, __ATOMIC_ACQUIRE));
    }

    uint32_t abortReason() const {
        return unpackReason(__atomic_load_n(&control_, __ATOMIC_ACQUIRE));
    }

private:
    static uint64_t pack(GatePhase phase, uint32_t reason) {
        return static_cast<uint64_t>(static_cast<uint32_t>(phase)) |
               (static_cast<uint64_t>(reason) << 32);
    }
    static GatePhase unpackPhase(uint64_t value) {
        return static_cast<GatePhase>(static_cast<uint32_t>(value));
    }
    static uint32_t unpackReason(uint64_t value) {
        return static_cast<uint32_t>(value >> 32);
    }
    void poison() {
        for (;;) {
            uint64_t current = __atomic_load_n(&control_, __ATOMIC_ACQUIRE);
            const auto currentPhase = unpackPhase(current);
            if (currentPhase == GatePhase::Aborted ||
                currentPhase == GatePhase::Poisoned ||
                currentPhase == GatePhase::PublishingAbort ||
                currentPhase == GatePhase::ValidAbortRequested)
                return;
            const uint64_t desired = pack(GatePhase::Poisoned, unpackReason(current));
            if (__atomic_compare_exchange_n(&control_, &current, desired, false,
                                            __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE))
                return;
        }
    }

    uint64_t control_ {};
};

} // namespace RaphaelRecoveryV3

#endif
