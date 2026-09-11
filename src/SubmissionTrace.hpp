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
static constexpr uint32_t MaximumPreparedMapCount = 0x3ff;

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

enum class MapPhase : uint32_t {
    None = 0,
    Capacity = 1,
    VirtualAddress = 2,
    BackingPte = 3,
    Unknown = 4,
};

static constexpr size_t MapPhaseCount = 5;
static constexpr size_t MapSamplesPerPhase = 2;
static constexpr unsigned MapPhaseSummaryLimit = 32;

struct MapSnapshot {
    uint32_t batchCount;
    uint32_t prepareCount;
    uint32_t flags;
    uint64_t gpuVirtualAddress;
    bool available;

    constexpr MapSnapshot(uint32_t batch = 0, uint32_t prepare = 0,
                          uint32_t mapFlags = 0, uint64_t gpuva = 0,
                          bool fieldsAvailable = false) :
        batchCount(batch), prepareCount(prepare), flags(mapFlags),
        gpuVirtualAddress(gpuva), available(fieldsAvailable) {}
};

struct MapPrepareObservation {
    uintptr_t accelerator;
    uintptr_t memoryMap;
    uintptr_t threadToken;
    bool result;
    MapSnapshot before;
    MapSnapshot after;
    uint32_t sequence;
    // Commits are observed on the same worker and map object while the native
    // prepare call is active. A zero window means commit was not reached.
    uint32_t commitCalls = 0;
    uint32_t commitFailures = 0;
    uint32_t commitFirstSequence = 0;
    uint32_t commitLastSequence = 0;
};

struct CommitObservation {
    uintptr_t memoryMap;
    uintptr_t threadToken;
    bool result;
    uint32_t sequence;
};

inline bool commitMatches(const CommitObservation &observation,
                          uintptr_t memoryMap, uintptr_t threadToken) {
    return observation.memoryMap == memoryMap &&
        observation.threadToken == threadToken;
}

template <size_t SampleCapacity> class CommitStore {
    rgpu::ObservationBuffer<CommitObservation, SampleCapacity> samples_ {};
    volatile uint64_t calls_ {};
    volatile uint64_t failures_ {};
public:
    void append(const CommitObservation &observation) {
        __atomic_fetch_add(&calls_, 1u, __ATOMIC_RELAXED);
        if (!observation.result) __atomic_fetch_add(&failures_, 1u, __ATOMIC_RELAXED);
        samples_.append(observation);
    }
    uint64_t calls() const { return __atomic_load_n(&calls_, __ATOMIC_RELAXED); }
    uint64_t failures() const { return __atomic_load_n(&failures_, __ATOMIC_RELAXED); }
    const rgpu::ObservationBuffer<CommitObservation, SampleCapacity> &samples() const {
        return samples_;
    }
};

inline MapPhase classifyMapPrepare(const MapPrepareObservation &observation) {
    if (observation.result) return MapPhase::None;
    const auto &before = observation.before;
    const auto &after = observation.after;
    if (!before.available || !after.available || before.prepareCount != 0 ||
        after.prepareCount != 0 || before.batchCount != after.batchCount ||
        ((before.flags & 1u) && !(after.flags & 1u)))
        return MapPhase::Unknown;
    if (before.batchCount > MaximumPreparedMapCount) {
        // The capacity fast path returns without touching the target map.
        if (before.flags != after.flags ||
            before.gpuVirtualAddress != after.gpuVirtualAddress)
            return MapPhase::Unknown;
        return MapPhase::Capacity;
    }
    // Bit zero is authoritative. Flag 0x20 allows a valid assigned address of zero.
    return (after.flags & 1u) ? MapPhase::BackingPte : MapPhase::VirtualAddress;
}

constexpr size_t mapPhaseIndex(MapPhase phase) {
    return static_cast<size_t>(phase);
}

inline const char *mapPhaseName(MapPhase phase) {
    switch (phase) {
        case MapPhase::None: return "none";
        case MapPhase::Capacity: return "capacity";
        case MapPhase::VirtualAddress: return "va-allocation-reclaim";
        case MapPhase::BackingPte: return "backing-pte";
        case MapPhase::Unknown: return "unknown";
    }
    return "unknown";
}

template <size_t SamplesPerPhase> class MapPhaseStore {
    rgpu::ObservationBuffer<MapPrepareObservation, SamplesPerPhase>
        samples_[MapPhaseCount] {};
    volatile uint64_t counts_[MapPhaseCount] {};
public:
    void append(const MapPrepareObservation &observation) {
        const auto phase = classifyMapPrepare(observation);
        if (phase == MapPhase::None) return;
        const auto index = mapPhaseIndex(phase);
        __atomic_fetch_add(&counts_[index], 1u, __ATOMIC_RELAXED);
        samples_[index].append(observation);
    }

    uint64_t count(MapPhase phase) const {
        return __atomic_load_n(&counts_[mapPhaseIndex(phase)], __ATOMIC_RELAXED);
    }
    const rgpu::ObservationBuffer<MapPrepareObservation, SamplesPerPhase> &
    samples(MapPhase phase) const {
        return samples_[mapPhaseIndex(phase)];
    }
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
