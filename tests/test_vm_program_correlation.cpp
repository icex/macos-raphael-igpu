#include <cstdio>
#include <cstdlib>

#include "../src/VmProgramCorrelation.hpp"

static void require(bool condition, const char *message) {
    if (!condition) {
        std::fprintf(stderr, "FAIL: %s\n", message);
        std::exit(1);
    }
}

static RaphaelVm::PreparedRequest program(uint32_t sequence, uintptr_t thread,
                                           uint64_t start, uint64_t end) {
    RaphaelVm::PreparedRequest p {};
    p.valid = true;
    p.sequence = sequence;
    p.threadToken = thread;
    p.request = {true, 0, 2, start, end, 0x840000000ULL, 0, true};
    return p;
}

static RaphaelSdma::SubmitInfoObservation submit(uint32_t hint, uint32_t order,
                                                  uintptr_t thread, uint64_t address) {
    return {true, hint, order, thread, 0, 2, 1, {address, 0, 0, 0}};
}

int main() {
    using namespace RaphaelVm;
    PreparedRequest programs[] = {
        program(1, 0xaaa, 0x400000000ULL, 0x4000fffffULL),
        program(3, 0xaaa, 0x500000000ULL, 0x5000fffffULL),
        program(4, 0xbbb, 0x400000000ULL, 0x4000fffffULL),
    };

    auto exact = correlateSubmit(submit(1, 2, 0xaaa, 0x400020000ULL), programs, 3);
    require(exact.reason == CorrelationReason::Matched && exact.matchedIndex == 0 &&
                exact.sameThread == 2 && exact.earlier == 1 && exact.inRange == 1,
            "the exact hinted same-thread predecessor is selected");

    auto fallback = correlateSubmit(submit(99, 8, 0xaaa, 0x500020000ULL), programs, 3);
    require(fallback.reason == CorrelationReason::Matched && fallback.matchedIndex == 1,
            "the newest qualifying same-thread predecessor repairs a stale hint");

    auto crossThread = correlateSubmit(submit(4, 8, 0xccc, 0x400020000ULL), programs, 3);
    require(crossThread.reason == CorrelationReason::NoSameThread &&
                crossThread.matchedIndex == kNoProgramMatch,
            "a matching range and hint on another thread is never paired");

    auto future = correlateSubmit(submit(3, 3, 0xaaa, 0x500020000ULL), programs, 3);
    require(future.reason == CorrelationReason::NoInRange && future.sameThread == 2 &&
                future.earlier == 1 && future.inRange == 0,
            "a program at the submit event order is not an earlier producer");
    auto onlyFuture = correlateSubmit(submit(3, 3, 0xaaa, 0x500020000ULL),
                                      programs + 1, 1);
    require(onlyFuture.reason == CorrelationReason::NoEarlier &&
                onlyFuture.sameThread == 1 && onlyFuture.earlier == 0,
            "an exact hint at the same event order is refused as not earlier");

    auto range = correlateSubmit(submit(1, 8, 0xaaa, 0x600020000ULL), programs, 3);
    require(range.reason == CorrelationReason::NoInRange && range.earlier == 2 &&
                range.inRange == 0,
            "a same-thread predecessor outside the submitted range is refused");

    auto invalid = submit(1, 2, 0xaaa, 0x400020000ULL);
    invalid.layoutValid = false;
    require(correlateSubmit(invalid, programs, 3).reason ==
                CorrelationReason::InvalidSubmit,
            "invalid native submission layouts never correlate");
    require(correlateSubmit(submit(1, 2, 0xaaa, 0x400020000ULL), programs, 0).reason ==
                CorrelationReason::NoProgram,
            "an empty retained-program set reports the missing predicate");

    auto twoAddresses = submit(1, 2, 0xaaa, 0x400020000ULL);
    twoAddresses.entries = 2;
    twoAddresses.addresses[1] = 0x600000000ULL;
    require(correlateSubmit(twoAddresses, programs, 3).reason ==
                CorrelationReason::NoInRange,
            "every nonzero native packet address must fit one program range");

    std::puts("VM program-correlation fixtures passed");
}
