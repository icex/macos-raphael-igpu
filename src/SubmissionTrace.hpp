#pragma once

#include <stddef.h>
#include <stdint.h>
#include "ObservationBuffer.hpp"

namespace RaphaelSubmit {

enum class Kind : uint32_t {
    ProcessCommandBuffer = 0,
    BatchPrepareMappings = 1,
    BatchPrepare = 2,
    MemoryMapPrepare = 3,
    SubmitBuffer = 4,
};

enum class Phase : uint32_t {
    Entry = 0,
    Exit = 1,
};

static constexpr size_t KindCount = 5;

struct Record {
    Kind kind;
    Phase phase;
    uintptr_t subject;
    uintptr_t object;
    uintptr_t threadToken;
    uint32_t requested;
    uint32_t result;
    uint32_t before;
    uint32_t sequence;
};

constexpr size_t kindIndex(Kind kind) {
    return static_cast<size_t>(kind);
}

inline const char *kindName(Kind kind) {
    switch (kind) {
        case Kind::ProcessCommandBuffer: return "process-command-buffer";
        case Kind::BatchPrepareMappings: return "mapping-batch";
        case Kind::BatchPrepare: return "resource-batch";
        case Kind::MemoryMapPrepare: return "memory-map";
        case Kind::SubmitBuffer: return "submit-buffer";
    }
    return "unknown";
}

inline const char *phaseName(Phase phase) {
    return phase == Phase::Entry ? "entry" : "exit";
}

// A mapping batch can make partial progress and then fall back to per-resource
// preparation, so it is notable evidence rather than a final submission error.
inline bool isNotable(const Record &record) {
    if (record.phase != Phase::Exit) return false;
    switch (record.kind) {
        case Kind::ProcessCommandBuffer:
            return record.result != 0;
        case Kind::BatchPrepareMappings:
            return record.requested != 0 && record.result < record.requested;
        case Kind::BatchPrepare:
        case Kind::MemoryMapPrepare:
            return record.result == 0;
        case Kind::SubmitBuffer:
            return false;
    }
    return false;
}

template <size_t RecordCapacity, size_t NotableCapacity> class Store {
    rgpu::ObservationBuffer<Record, RecordCapacity> records_ {};
    rgpu::ObservationBuffer<Record, NotableCapacity> notableRecords_ {};
    volatile uint64_t entries_[KindCount] {};
    volatile uint64_t exits_[KindCount] {};
    volatile uint64_t notable_[KindCount] {};
public:
    void append(const Record &record) {
        const auto index = kindIndex(record.kind);
        if (index >= KindCount) return;
        if (record.phase == Phase::Entry)
            __atomic_fetch_add(&entries_[index], 1u, __ATOMIC_RELAXED);
        else
            __atomic_fetch_add(&exits_[index], 1u, __ATOMIC_RELAXED);
        if (isNotable(record)) {
            __atomic_fetch_add(&notable_[index], 1u, __ATOMIC_RELAXED);
            notableRecords_.append(record);
        }
        records_.append(record);
    }

    uint64_t entries(Kind kind) const {
        return __atomic_load_n(&entries_[kindIndex(kind)], __ATOMIC_RELAXED);
    }
    uint64_t exits(Kind kind) const {
        return __atomic_load_n(&exits_[kindIndex(kind)], __ATOMIC_RELAXED);
    }
    uint64_t notable(Kind kind) const {
        return __atomic_load_n(&notable_[kindIndex(kind)], __ATOMIC_RELAXED);
    }
    const rgpu::ObservationBuffer<Record, RecordCapacity> &records() const {
        return records_;
    }
    const rgpu::ObservationBuffer<Record, NotableCapacity> &notableRecords() const {
        return notableRecords_;
    }
};

} // namespace RaphaelSubmit
