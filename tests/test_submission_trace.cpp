#include <cstdio>
#include <cstdlib>
#include "../src/SubmissionTrace.hpp"

static void require(bool condition, const char *message) {
    if (!condition) {
        std::fprintf(stderr, "FAIL: %s\n", message);
        std::exit(1);
    }
}

int main() {
    using RaphaelSubmit::Kind;
    using RaphaelSubmit::MapPhase;
    using RaphaelSubmit::MapPrepareObservation;
    using RaphaelSubmit::MapSnapshot;
    using RaphaelSubmit::Phase;
    using RaphaelSubmit::Record;

    Record mapping {Kind::BatchPrepareMappings, Phase::Exit, 0, 0, 7, 5, 3, 0, 0};
    require(RaphaelSubmit::isNotable(mapping),
            "a partial mapping batch is retained even before final resource preparation");

    Record completeMapping {Kind::BatchPrepareMappings, Phase::Exit, 0, 0, 7, 5, 5, 0, 0};
    require(!RaphaelSubmit::isNotable(completeMapping),
            "a complete mapping batch is not reported as a failure");

    Record prepareFailure {Kind::BatchPrepare, Phase::Exit, 0, 0, 7, 5, 0, 0, 0};
    require(RaphaelSubmit::isNotable(prepareFailure),
            "the final false BatchPrepare result is retained");

    Record mapFailure {Kind::MemoryMapPrepare, Phase::Exit, 0x1111, 0x2222,
                       0x3333, 0, 0, 0, 77};
    require(RaphaelSubmit::isNotable(mapFailure),
            "a failed individual memory-map prepare is retained");

    Record queueError {Kind::ProcessCommandBuffer, Phase::Exit, 0, 0, 7, 0, 9, 0, 0};
    require(RaphaelSubmit::isNotable(queueError),
            "a nonzero post-command queue error is retained");

    Record submitExit {Kind::SubmitBuffer, Phase::Exit, 0, 0, 7, 0, 0, 0, 0};
    require(!RaphaelSubmit::isNotable(submitExit),
            "the void submitBuffer exit is evidence of return, not a result code");

    RaphaelSubmit::Store<2, 1> trace;
    Record submitEntry {Kind::SubmitBuffer, Phase::Entry, 0x1234, 0x5678,
                        0xabcdef, 0, 0, 0, 40};
    trace.append(submitEntry);
    trace.append(submitExit);
    trace.append(mapFailure);
    require(trace.entries(Kind::SubmitBuffer) == 1 &&
                trace.exits(Kind::SubmitBuffer) == 1 &&
                trace.notable(Kind::SubmitBuffer) == 0,
            "submitBuffer entry and return counts remain distinct");
    require(trace.exits(Kind::MemoryMapPrepare) == 1 &&
                trace.notable(Kind::MemoryMapPrepare) == 1,
            "failure counters continue after the ordinary record buffer fills");
    require(trace.records().size() == 2 && trace.records().dropped() == 1,
            "the ordinary trace has a hard capacity");
    Record retained {};
    require(trace.notableRecords().read(0, retained) &&
                retained.kind == Kind::MemoryMapPrepare &&
                retained.subject == mapFailure.subject &&
                retained.object == mapFailure.object &&
                retained.threadToken == mapFailure.threadToken &&
                retained.sequence == mapFailure.sequence,
            "a later failure retains its raw correlation evidence in a separate buffer");

    require(RaphaelSubmit::kindName(Kind::BatchPrepareMappings)[0] == 'm' &&
                RaphaelSubmit::phaseName(Phase::Exit)[0] == 'e',
            "records have stable human-readable kind and phase names");

    RaphaelSubmit::CommitStore<2> commits;
    commits.append({0x2222, 0x3333, true, 41});
    commits.append({0x2222, 0x3333, false, 42});
    commits.append({0x9999, 0x3333, false, 43});
    require(commits.calls() == 3 && commits.failures() == 2 &&
                commits.samples().size() == 2 && commits.samples().dropped() == 1,
            "commit diagnostics count results and retain a bounded sample set");
    require(RaphaelSubmit::commitMatches({0x2222, 0x3333, false, 42},
                                         0x2222, 0x3333),
            "commit correlation matches the exact map and worker");
    require(!RaphaelSubmit::commitMatches({0x9999, 0x3333, false, 43},
                                          0x2222, 0x3333),
            "commit correlation rejects a different map object");

    const MapSnapshot empty {0, 0, 0, 0, true};
    MapPrepareObservation capacity {0, 0, 0, false,
                                    {0x400, 0, 0, 0, true},
                                    {0x400, 0, 0, 0, true}, 0};
    require(RaphaelSubmit::classifyMapPrepare(capacity) == MapPhase::Capacity,
            "a count above the exact 0x3ff limit is a batch-capacity failure");
    capacity.before.batchCount = 0x3ff;
    capacity.after.batchCount = 0x3ff;
    require(RaphaelSubmit::classifyMapPrepare(capacity) == MapPhase::VirtualAddress,
            "the 0x3ff boundary itself is not a batch-capacity failure");
    capacity.before.batchCount = 0x400;
    capacity.after.batchCount = 0x3ff;
    require(RaphaelSubmit::classifyMapPrepare(capacity) == MapPhase::Unknown,
            "a capacity fast-path mutation is inconsistent");
    capacity.after.batchCount = 0x400;
    capacity.after.flags = 0x100;
    require(RaphaelSubmit::classifyMapPrepare(capacity) == MapPhase::Unknown,
            "full-width target flag mutation makes a capacity snapshot inconsistent");
    capacity.after.flags = 0;

    MapPrepareObservation unavailable {0, 0, 0, false, {}, empty, 0};
    require(RaphaelSubmit::classifyMapPrepare(unavailable) == MapPhase::Unknown,
            "a default unavailable snapshot cannot be called a VA failure");

    MapPrepareObservation virtualAddress {0, 0, 0, false, empty, empty, 0};
    require(RaphaelSubmit::classifyMapPrepare(virtualAddress) ==
                MapPhase::VirtualAddress,
            "a final unassigned map identifies the final VA allocation phase");
    virtualAddress.after.batchCount = 1;
    require(RaphaelSubmit::classifyMapPrepare(virtualAddress) == MapPhase::Unknown,
            "a false noncapacity path cannot change the prepared-map count");
    virtualAddress.after.batchCount = 0;

    MapPrepareObservation backing {0, 0, 0, false, empty,
                                   {0, 0, 0x21, 0, true}, 0};
    require(RaphaelSubmit::classifyMapPrepare(backing) == MapPhase::BackingPte,
            "assigned flag bit 0 is authoritative when flag 0x20 permits GPUVA zero");

    MapPrepareObservation impossiblePrepare {0, 0, 0, false,
                                             {0, 1, 0, 0, true}, empty, 0};
    require(RaphaelSubmit::classifyMapPrepare(impossiblePrepare) == MapPhase::Unknown,
            "a false result with a nonzero pre-prepare count is inconsistent");
    impossiblePrepare.before.prepareCount = 0;
    impossiblePrepare.after.prepareCount = 1;
    require(RaphaelSubmit::classifyMapPrepare(impossiblePrepare) == MapPhase::Unknown,
            "a false result with a nonzero post-prepare count is inconsistent");

    MapPrepareObservation clearedAssignment {0, 0, 0, false,
                                             {0, 0, 1, 0x1000, true}, empty, 0};
    require(RaphaelSubmit::classifyMapPrepare(clearedAssignment) == MapPhase::Unknown,
            "the outer fallback cannot clear the target map's assigned bit");

    MapPrepareObservation success {0, 0, 0, true, empty,
                                   {0, 0, 0x21, 0, true}, 0};
    require(RaphaelSubmit::classifyMapPrepare(success) == MapPhase::None,
            "successful preparation with a legal zero GPUVA is not a failure phase");

    MapPrepareObservation correlated {0, 0, 0, false, empty,
                                      {0, 0, 0x21, 0, true}, 0};
    correlated.commitCalls = 2;
    correlated.commitFailures = 1;
    correlated.commitFirstSequence = 41;
    correlated.commitLastSequence = 42;
    require(correlated.commitCalls == 2 && correlated.commitFailures == 1 &&
                correlated.commitFirstSequence < correlated.commitLastSequence,
            "map observations carry exact bounded commit window metadata");

    RaphaelSubmit::MapPhaseStore<1> phases;
    virtualAddress.sequence = 11;
    phases.append(virtualAddress);
    virtualAddress.sequence = 12;
    phases.append(virtualAddress);
    virtualAddress.sequence = 13;
    phases.append(virtualAddress);
    phases.append(backing);
    phases.append(success);
    require(phases.count(MapPhase::VirtualAddress) == 3 &&
                phases.samples(MapPhase::VirtualAddress).size() == 1 &&
                phases.samples(MapPhase::VirtualAddress).dropped() == 2,
            "phase counts continue after the bounded sample buffer fills");
    require(phases.count(MapPhase::BackingPte) == 1 &&
                phases.samples(MapPhase::BackingPte).size() == 1,
            "each failure phase retains its own first sample");
    require(phases.count(MapPhase::None) == 0 &&
                phases.samples(MapPhase::None).size() == 0,
            "the public phase API handles the non-failure phase without underflow");
    RaphaelSubmit::MapPrepareObservation retainedPhase {};
    require(phases.samples(MapPhase::VirtualAddress).read(0, retainedPhase) &&
                retainedPhase.sequence == 11,
            "the per-phase buffer retains the first failure sample");

    std::puts("submission trace fixtures passed");
}
