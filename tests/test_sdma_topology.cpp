#include <cstdio>
#include <cstdlib>
#include <initializer_list>
#include "../src/SdmaTopology.hpp"

static void require(bool condition, const char *message) {
    if (!condition) {
        std::fprintf(stderr, "FAIL: %s\n", message);
        std::exit(1);
    }
}

struct Engine {
    bool result;
    unsigned calls;
};

static bool startEngine(void *raw) {
    auto engine = static_cast<Engine *>(raw);
    engine->calls++;
    return engine->result;
}

int main() {
    using RaphaelSdma::Topology;

    // Hybrid-002 captured one discovered instance while X6000 allocated two objects.
    auto one = RaphaelSdma::plan(1);
    require(one.valid && one.startCount == 1, "one discovered instance produces one start");
    Engine first {true, 0}, nonexistent {true, 0};
    void *captured[2] {&first, &nonexistent};
    void *detached = RaphaelSdma::detachExtra(captured, 2, one);
    require(detached == &nonexistent, "the false second SDMA object is detached");
    require(captured[0] == &first && captured[1] == nullptr,
            "detaching the second object preserves the real first object");
    int owner = 0, otherOwner = 0;
    require(RaphaelSdma::ownsRepairedSlots(&owner, &owner, captured, 2, one),
            "the exact repaired hardware object owns the replacement start");
    require(!RaphaelSdma::ownsRepairedSlots(&owner, &otherOwner, captured, 2, one),
            "another hardware object cannot inherit replacement-start state");
    require(!RaphaelSdma::ownsRepairedSlots(nullptr, nullptr, captured, 2, one),
            "null objects cannot own replacement-start state");
    require(RaphaelSdma::start(captured, 2, one, startEngine),
            "the surviving native SDMA engine result is returned");
    require(first.calls == 1 && nonexistent.calls == 0,
            "the absent second instance is never started");

    // A real two-instance Navi23 topology remains unchanged.
    auto two = RaphaelSdma::plan(2);
    Engine second {true, 0};
    void *native[2] {&first, &second};
    require(!RaphaelSdma::ownsRepairedSlots(&owner, &owner, native, 2, one),
            "a recreated object with a live second slot must be repaired again");
    require(RaphaelSdma::detachExtra(native, 2, two) == nullptr,
            "two-instance topology does not detach an engine");
    require(native[0] == &first && native[1] == &second,
            "two-instance slots remain intact");
    first.calls = 0;
    require(RaphaelSdma::start(native, 2, two, startEngine),
            "two valid engines both start");
    require(first.calls == 1 && second.calls == 1, "native two-engine order is preserved");

    // Native error semantics survive the topology correction.
    first = {false, 0};
    nonexistent = {true, 0};
    void *failure[2] {&first, &nonexistent};
    RaphaelSdma::detachExtra(failure, 2, one);
    require(!RaphaelSdma::start(failure, 2, one, startEngine),
            "a real first-engine failure is not forced to success");
    require(first.calls == 1 && nonexistent.calls == 0,
            "failure does not touch the detached engine");

    first = {true, 0};
    second = {false, 0};
    void *secondFailure[2] {&first, &second};
    require(!RaphaelSdma::start(secondFailure, 2, two, startEngine),
            "a real second-engine failure remains visible on a two-instance GPU");
    require(first.calls == 1 && second.calls == 1,
            "two-instance startup preserves native order through the failing child");

    // Invalid discovery data must not mutate or start anything.
    for (unsigned count : {0U, 3U, 0xffffffffU}) {
        Topology invalid = RaphaelSdma::plan(count);
        void *slots[2] {&first, &second};
        require(!invalid.valid, "unsupported instance count is rejected");
        require(RaphaelSdma::detachExtra(slots, 2, invalid) == nullptr,
                "invalid topology does not detach objects");
        require(slots[0] == &first && slots[1] == &second,
                "invalid topology leaves allocation untouched");
        require(!RaphaelSdma::start(slots, 2, invalid, startEngine),
                "invalid topology cannot report startup success");
    }

    void *missing[2] {nullptr, &second};
    require(!RaphaelSdma::start(missing, 2, one, startEngine),
            "missing required engine preserves native failure");

    for (size_t allocated : {0U, 1U, 3U}) {
        void *wrongExtent[2] {&first, &second};
        require(RaphaelSdma::detachExtra(wrongExtent, allocated, one) == nullptr,
                "unexpected owner-array extent is rejected");
        require(wrongExtent[0] == &first && wrongExtent[1] == &second,
                "extent rejection cannot mutate the owner array");
        require(!RaphaelSdma::start(wrongExtent, allocated, one, startEngine),
                "unexpected owner-array extent cannot report startup success");
        require(!RaphaelSdma::ownsRepairedSlots(&owner, &owner, wrongExtent,
                                                allocated, one),
                "unexpected owner-array extent cannot own replacement-start state");
    }
    std::puts("SDMA topology fixtures passed");
}
