#pragma once

#include <stddef.h>
#include <stdint.h>

#include "ObservationBuffer.hpp"

namespace RaphaelBacking {

// Live scalar snapshots around AMDAccelVidMemory::allocPhysical. These are
// observations at the wrapper boundaries, not a claim about final object state.
struct Snapshot {
    uint64_t length;
    uintptr_t owner;
    uint64_t element;
    uint64_t raw120;
    uint32_t flags;
    bool available;
    uint64_t freeBytes = 0;
};

inline Snapshot captureSnapshot(const void *backing) {
    if (backing == nullptr) return Snapshot {};
    auto bytes = static_cast<const uint8_t *>(backing);
    return Snapshot {
        __atomic_load_n(reinterpret_cast<const uint64_t *>(bytes + 0x40),
                        __ATOMIC_RELAXED),
        __atomic_load_n(reinterpret_cast<const uintptr_t *>(bytes + 0x110),
                        __ATOMIC_RELAXED),
        __atomic_load_n(reinterpret_cast<const uint64_t *>(bytes + 0x118),
                        __ATOMIC_RELAXED),
        __atomic_load_n(reinterpret_cast<const uint64_t *>(bytes + 0x120),
                        __ATOMIC_RELAXED),
        __atomic_load_n(reinterpret_cast<const uint32_t *>(bytes + 0x128),
                        __ATOMIC_RELAXED),
        true
    };
}

struct Observation {
    uintptr_t backing;
    uintptr_t threadToken;
    bool result;
    Snapshot before;
    Snapshot after;
    uint32_t sequence;
    uint64_t successfulBefore = 0;
    uint64_t failedBefore = 0;
    uint64_t successfulAfter = 0;
    uint64_t failedAfter = 0;
};

inline uint32_t poolIndex(const Snapshot &snapshot) {
    return (snapshot.flags >> 19) & 1u;
}

template <size_t FailureSamples> class Store {
    rgpu::ObservationBuffer<Observation, FailureSamples> failures_ {};
    volatile uint64_t successful_ {};
    volatile uint64_t failed_ {};
public:
    void append(const Observation &observation) {
        if (observation.result) {
            __atomic_fetch_add(&successful_, 1u, __ATOMIC_RELAXED);
        } else {
            __atomic_fetch_add(&failed_, 1u, __ATOMIC_RELAXED);
            failures_.append(observation);
        }
    }

    uint64_t successful() const {
        return __atomic_load_n(&successful_, __ATOMIC_RELAXED);
    }
    uint64_t failed() const {
        return __atomic_load_n(&failed_, __ATOMIC_RELAXED);
    }
    uint64_t completed() const {
        return successful() + failed();
    }
    const rgpu::ObservationBuffer<Observation, FailureSamples> &failures() const {
        return failures_;
    }
};

template <typename Native, typename Capture, size_t FailureSamples>
bool observe(bool active, void *backing, uintptr_t threadToken, uint32_t sequence,
             Store<FailureSamples> &store, Native native, Capture capture) {
    if (!active) return native(backing);
    const auto before = capture(backing);
    const auto successfulBefore = store.successful();
    const auto failedBefore = store.failed();
    const bool result = native(backing);
    const auto after = capture(backing);
    store.append(Observation {
        reinterpret_cast<uintptr_t>(backing), threadToken, result,
        before, after, sequence, successfulBefore, failedBefore,
        store.successful() + (result ? 1u : 0u),
        store.failed() + (result ? 0u : 1u)
    });
    return result;
}

} // namespace RaphaelBacking
