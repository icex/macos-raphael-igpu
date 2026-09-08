#pragma once

#include <stddef.h>
#include <stdint.h>

namespace RaphaelSdma {

// X6000 still asks AMDHardware for SDMA1 channels after its false second
// engine object has been removed. On a repaired one-instance owner those
// requests belong to the physical SDMA0 engine. Keep all other engine ids and
// every unrepaired/native topology untouched.
constexpr uint32_t engineForPhysicalTopology(uint32_t requestedEngine,
                                              bool oneInstanceRepaired) {
    return oneInstanceRepaired && requestedEngine == 2 ? 1 : requestedEngine;
}

// Apple's Navi23 allocator has exactly two SDMA object slots. Raphael discovery
// reports one physical instance; counts outside this domain are not safe to adapt.
struct Topology {
    bool valid;
    uint32_t startCount;
};

constexpr Topology plan(uint32_t discoveredInstances) {
    return discoveredInstances >= 1 && discoveredInstances <= 2
        ? Topology {true, discoveredInstances}
        : Topology {false, 0};
}

inline void *detachExtra(void **slots, size_t allocatedCount, Topology topology) {
    if (!topology.valid || slots == nullptr || allocatedCount != 2 ||
        topology.startCount >= allocatedCount)
        return nullptr;
    void *detached = slots[topology.startCount];
    slots[topology.startCount] = nullptr;
    return detached;
}

inline bool ownsRepairedSlots(void *owner, void *candidate, void **slots,
                              size_t allocatedCount, Topology topology) {
    return topology.valid && topology.startCount == 1 && owner != nullptr &&
           owner == candidate && slots != nullptr && allocatedCount == 2 &&
           slots[0] != nullptr && slots[1] == nullptr;
}

using StartFunction = bool (*)(void *engine);

inline bool start(void **slots, size_t allocatedCount, Topology topology,
                  StartFunction startFunction) {
    if (!topology.valid || slots == nullptr || startFunction == nullptr ||
        allocatedCount != 2 || topology.startCount == 0 ||
        topology.startCount > allocatedCount)
        return false;
    for (uint32_t i = 0; i < topology.startCount; i++) {
        if (slots[i] == nullptr || !startFunction(slots[i]))
            return false;
    }
    return true;
}

} // namespace RaphaelSdma
