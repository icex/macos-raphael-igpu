#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <map>
#include <stdexcept>
#include <string>
#include <thread>

#include "../src/RecoveryLifetime.hpp"

static void require(bool condition, const char *message) {
    if (!condition) {
        std::fprintf(stderr, "FAIL: %s\n", message);
        std::exit(1);
    }
}

static std::map<std::string, std::string> loadGolden() {
    std::ifstream input("tests/fixtures/recovery-lifetime-v3-golden.txt");
    std::map<std::string, std::string> values;
    std::string line;
    while (std::getline(input, line)) {
        if (line.empty() || line[0] == '#') continue;
        auto split = line.find('=');
        if (split != std::string::npos)
            values[line.substr(0, split)] = line.substr(split + 1);
    }
    return values;
}

template <typename T> static std::string wireHex(const T &value) {
    static const char digits[] = "0123456789abcdef";
    const auto bytes = reinterpret_cast<const unsigned char *>(&value);
    std::string out;
    out.reserve(sizeof(value) * 2);
    for (size_t i = 0; i < sizeof(value); ++i) {
        out.push_back(digits[bytes[i] >> 4]);
        out.push_back(digits[bytes[i] & 0xf]);
    }
    return out;
}

struct Interrupted {};

int main() {
    using namespace RaphaelRecoveryV2;
    using namespace RaphaelRecoveryV3;
    constexpr uint64_t nonceLo = 0x0123456789abcdefULL;
    constexpr uint64_t nonceHi = 0xfedcba9876543210ULL;
    const auto owned = makeOwnership(0x0a000000, nonceLo, nonceHi);
    const auto pool = makePoolStatus(owned, PoolActive,
        0x0e000000, 0x0dfeb000, 0x0c000000, 0x0bfeb000, ReasonNone);
    const auto valid = makeValidLifetime(owned, pool);
    const auto golden = loadGolden();

    require(sizeof(LifetimeStatus) == 88 && LifetimeOffset == 0x200 &&
            LifetimeOffset + sizeof(LifetimeStatus) <= ScratchRelative,
            "schema-3 lifetime marker fits the free metadata span");
    require(wireHex(valid) == golden.at("valid"),
            "C++ VALID bytes match the shared host fixture");
    const auto abort = makeAbortLifetime(valid, LifetimeReasonDuplicatePool);
    require(wireHex(abort) == golden.at("abort_duplicate_pool"),
            "C++ ABORT bytes match the shared host fixture");
    require(validLifetime(valid, owned, pool, true) &&
            validLifetime(abort, owned, pool, false) &&
            !validLifetime(abort, owned, pool, true),
            "only exact VALID lifetime state authorizes recovery");

    constexpr size_t words = sizeof(LifetimeStatus) / sizeof(uint32_t);
    {
        uint32_t memory[words];
        __builtin_memcpy(memory, &abort, sizeof(abort));
        unsigned writes = 0;
        require(!publishValidLifetime(
                    valid,
                    [&](uint32_t i, uint32_t value) {
                        memory[i] = value;
                        ++writes;
                    },
                    [&](uint32_t i) { return memory[i]; }, [] {}) &&
                    writes == 0,
                "VALID publication cannot overwrite an existing terminal marker");
    }

    for (size_t stop = 0; stop < words + 1; ++stop) {
        uint32_t memory[words] {};
        size_t operations = 0;
        try {
            publishValidLifetime(valid,
                [&](uint32_t i, uint32_t value) {
                    if (operations++ == stop) throw Interrupted {};
                    memory[i] = value;
                },
                [&](uint32_t i) { return memory[i]; }, [] {});
            require(false, "partial VALID publication must be interrupted");
        } catch (const Interrupted &) {}
        LifetimeStatus observed {};
        __builtin_memcpy(&observed, memory, sizeof(observed));
        require(!validLifetime(observed, owned, pool, true),
                "every partial VALID write prefix is non-authorizing");
    }

    for (size_t stop = 1; stop < words + 1; ++stop) {
        uint32_t memory[words];
        __builtin_memcpy(memory, &valid, sizeof(valid));
        size_t operations = 0;
        const auto requested = makeAbortLifetime(valid, LifetimeReasonPoolOwner);
        try {
            publishAbortLifetime(requested,
                [&](uint32_t i, uint32_t value) {
                    if (operations++ == stop) throw Interrupted {};
                    memory[i] = value;
                },
                [&](uint32_t i) { return memory[i]; }, [] {});
            require(false, "partial ABORT publication must be interrupted");
        } catch (const Interrupted &) {}
        LifetimeStatus observed {};
        __builtin_memcpy(&observed, memory, sizeof(observed));
        require(!validLifetime(observed, owned, pool, true),
                "every ABORT prefix after poison is non-authorizing");
    }

    {
        uint32_t memory[words];
        __builtin_memcpy(memory, &valid, sizeof(valid));
        unsigned writes = 0;
        require(publishAbortLifetime(abort,
                    [&](uint32_t i, uint32_t value) { memory[i] = value; ++writes; },
                    [&](uint32_t i) { return memory[i]; }, [] {}) && writes > 0,
                "first durable abort publication succeeds");
        writes = 0;
        require(!publishAbortLifetime(
                    makeAbortLifetime(valid, LifetimeReasonPoolOwner),
                    [&](uint32_t i, uint32_t value) { memory[i] = value; ++writes; },
                    [&](uint32_t i) { return memory[i]; }, [] {}) && writes == 0,
                "an existing ABORT cannot be overwritten by a later reason");
    }

    for (unsigned iteration = 0; iteration < 2000; ++iteration) {
        LifetimeGate gate {};
        require(gate.beginValidPublication(), "one VALID publisher owns the gate");
        std::atomic<unsigned> ready {0};
        ValidCompletion completion {};
        AbortRequest request {};
        std::thread publisher([&] {
            ++ready;
            while (ready.load() != 2) std::this_thread::yield();
            completion = gate.finishValidPublication(true);
        });
        std::thread aborter([&] {
            ++ready;
            while (ready.load() != 2) std::this_thread::yield();
            request = gate.requestAbort(LifetimeReasonDuplicateReady);
        });
        publisher.join();
        aborter.join();
        require(!gate.clientsAllowed(),
                "an abort racing ACTIVE publication always blocks admission");
        const bool publisherOwns = completion == ValidCompletion::AbortOwner;
        const bool aborterOwns = request == AbortRequest::Owner;
        require(publisherOwns != aborterOwns &&
                gate.abortReason() == LifetimeReasonDuplicateReady,
                "exactly one racing caller owns the first abort publication");
        gate.finishAbortPublication(true);
        require(gate.phase() == GatePhase::Aborted && !gate.clientsAllowed(),
                "completed ABORT is terminal");
    }

    LifetimeGate poisoned {};
    require(poisoned.beginValidPublication(), "poison fixture begins publication");
    require(poisoned.requestAbort(LifetimeReasonVmmRange) == AbortRequest::Deferred,
            "abort during VALID publication is deferred to its owner");
    require(poisoned.finishValidPublication(false) == ValidCompletion::Poisoned &&
            poisoned.phase() == GatePhase::Poisoned && !poisoned.clientsAllowed(),
            "failed readback with a pending abort can never admit clients");
    require(poisoned.requestAbort(LifetimeReasonPoolOwner) == AbortRequest::AlreadyBlocked &&
            poisoned.abortReason() == LifetimeReasonVmmRange,
            "the first abort reason survives later invalidation attempts");

    return 0;
}
