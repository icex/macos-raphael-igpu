#pragma once

#include <stddef.h>
#include <stdint.h>

namespace rgpu {

// Append-only storage for small trivially-copyable observations captured from
// driver callbacks. Producers perform no allocation, formatting, MMIO or
// waiting. A release-published slot is consumed later by a kernel thread.
template <typename T, size_t Capacity> class ObservationBuffer {
    static_assert(Capacity > 0, "nonempty observation buffer required");
    struct Slot { unsigned ready; T value; } slots_[Capacity] {};
    uint64_t reserved_ {};
    uint64_t dropped_ {};
public:
    void append(const T &value) {
        const uint64_t sequence = __atomic_fetch_add(&reserved_, 1, __ATOMIC_RELAXED);
        if (sequence >= Capacity) {
            __atomic_fetch_add(&dropped_, 1, __ATOMIC_RELAXED);
            return;
        }
        auto source = reinterpret_cast<const uint8_t *>(&value);
        auto target = reinterpret_cast<uint8_t *>(&slots_[sequence].value);
        for (size_t i = 0; i < sizeof(T); ++i) target[i] = source[i];
        __atomic_store_n(&slots_[sequence].ready, 1u, __ATOMIC_RELEASE);
    }
    size_t size() const {
        const uint64_t count = __atomic_load_n(&reserved_, __ATOMIC_RELAXED);
        return count < Capacity ? static_cast<size_t>(count) : Capacity;
    }
    bool read(size_t sequence, T &value) const {
        if (sequence >= Capacity ||
            !__atomic_load_n(&slots_[sequence].ready, __ATOMIC_ACQUIRE)) return false;
        auto source = reinterpret_cast<const uint8_t *>(&slots_[sequence].value);
        auto target = reinterpret_cast<uint8_t *>(&value);
        for (size_t i = 0; i < sizeof(T); ++i) target[i] = source[i];
        return true;
    }
    uint64_t dropped() const {
        return __atomic_load_n(&dropped_, __ATOMIC_RELAXED);
    }
};

} // namespace rgpu
