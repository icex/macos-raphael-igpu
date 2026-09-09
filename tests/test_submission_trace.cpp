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

    std::puts("submission trace fixtures passed");
}
