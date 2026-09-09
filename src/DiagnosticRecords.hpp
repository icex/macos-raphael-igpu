#pragma once
#include <stddef.h>
#include <stdint.h>

namespace rgpu {
static constexpr size_t kCriticalRecordCapacity = 256;
static constexpr uint64_t kRoutinePreClearRecordLimit = 8;

class SuccessRecordBudget {
    uint64_t successes_ {};
public:
    bool take(bool success, uint64_t maximumSuccessRecords) {
        if (!success) return true;
        return __atomic_fetch_add(&successes_, 1, __ATOMIC_RELAXED) <
            maximumSuccessRecords;
    }
};

// Append-only for one kext lifetime. No allocation, waiting on a producer, locks,
// MMIO, or formatting inside this class. Each reservation owns a distinct slot.
// Release publication follows the terminating NUL; acquire readers never inspect
// an unfinished slot. Slots are never reused, so a preempted reader stays safe.
// x86_64 atomics are inline (including in interrupt context); an interrupted
// producer cannot deadlock another producer. Sequence is the slot index.
template <size_t Capacity, size_t Width> class DiagnosticRecords {
    static_assert(Capacity > 0 && Width > 1, "nonempty records required");
    struct Slot { unsigned ready; char text[Width]; } slots_[Capacity] {};
    uint64_t reserved_ {};
    uint64_t dropped_ {};
    uint64_t truncated_ {};
public:
    void append(const char *text, bool alreadyTruncated = false) {
        uint64_t sequence = __atomic_fetch_add(&reserved_, 1, __ATOMIC_RELAXED);
        if (sequence >= Capacity) {
            __atomic_fetch_add(&dropped_, 1, __ATOMIC_RELAXED);
            return;
        }
        Slot &slot = slots_[sequence];
        size_t n = 0;
        while (n < Width - 1 && text[n]) { slot.text[n] = text[n]; ++n; }
        slot.text[n] = '\0';
        if (text[n] || alreadyTruncated)
            __atomic_fetch_add(&truncated_, 1, __ATOMIC_RELAXED);
        __atomic_store_n(&slot.ready, 1u, __ATOMIC_RELEASE);
    }
    size_t size() const {
        uint64_t n = __atomic_load_n(&reserved_, __ATOMIC_RELAXED);
        return n < Capacity ? static_cast<size_t>(n) : Capacity;
    }
    bool read(size_t sequence, char (&out)[Width]) const {
        if (sequence >= Capacity ||
            !__atomic_load_n(&slots_[sequence].ready, __ATOMIC_ACQUIRE)) return false;
        for (size_t i = 0; i < Width; ++i) {
            out[i] = slots_[sequence].text[i];
            if (!out[i]) break;
        }
        return true;
    }
    uint64_t dropped() const { return __atomic_load_n(&dropped_, __ATOMIC_RELAXED); }
    uint64_t truncated() const { return __atomic_load_n(&truncated_, __ATOMIC_RELAXED); }
};
}
