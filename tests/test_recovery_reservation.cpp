#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include "../src/RecoveryReservation.hpp"

static void require(bool condition, const char *message) {
    if (!condition) {
        std::fprintf(stderr, "FAIL: %s\n", message);
        std::exit(1);
    }
}

int main() {
    using namespace RaphaelRecovery;
    struct OwnerLayout { void *words[3]; };
    OwnerLayout memory {}, hardware {};
    uint32_t pciToken = 0, barToken = 0;
    void *cachedMapping = nullptr;
    unsigned mapCalls = 0;
    bool mappingAvailable = false;
    auto mapper = [&](void *pci) -> void * {
        ++mapCalls;
        require(pci == &pciToken, "the memory owner supplies the expected PCI object");
        return mappingAvailable ? &barToken : nullptr;
    };
    auto unavailable = establishBarMapping(
        cachedMapping, nullptr, nullptr, mapper);
    require(unavailable.status == BarMappingStatus::OwnerUnavailable &&
                unavailable.address == nullptr && mapCalls == 0,
            "an unavailable early owner does not attempt or cache a BAR mapping");
    memory.words[2] = &hardware;
    hardware.words[2] = &pciToken;
    auto failed = establishBarMapping(cachedMapping, nullptr, &memory, mapper);
    require(failed.status == BarMappingStatus::MappingFailed &&
                failed.address == nullptr && cachedMapping == nullptr && mapCalls == 1,
            "a failed map attempt returns cleanly without poisoning the cache");
    mappingAvailable = true;
    auto early = establishBarMapping(cachedMapping, nullptr, &memory, mapper);
    require(early.status == BarMappingStatus::Mapped && early.address == &barToken &&
                cachedMapping == &barToken && mapCalls == 2,
            "AMDHWMemory's owner establishes BAR0 before later hardware publication");
    auto retained = establishBarMapping(cachedMapping, nullptr, nullptr, mapper);
    require(retained.status == BarMappingStatus::Cached &&
                retained.address == &barToken && mapCalls == 2,
            "a successful early mapping is retained without another map attempt");

    constexpr uint64_t nonceLo = 0xaaaaaaaaaaaaaaaaULL;
    constexpr uint64_t nonceHi = 0xaaaaaaaaaaaaaaaaULL;
    auto descriptor = pending(nonceLo, nonceHi);
    require(valid(descriptor, Pending, nonceLo, nonceHi), "pending challenge validates");

    uint64_t pool0 = 0x20000000, pool1 = 0x10000000;
    bool nativeAllocatorConstructed = false;
    require(activate(descriptor, pool0, pool1), "guest activates a pending challenge");
    require(pool0 == HeapLimit && pool1 == HeapLimit,
            "both allocator pools end below the recovery reservation");
    auto constructNativeAllocator = [&] {
        require(pool0 == HeapLimit && pool1 == HeapLimit &&
                    valid(descriptor, Active, nonceLo, nonceHi),
                "native allocation sees the active reservation and capped pools");
        nativeAllocatorConstructed = true;
    };
    require(!nativeAllocatorConstructed, "native allocation has not run during activation");
    constructNativeAllocator();
    require(barVisibleBytes(pool0, pool1) == ReservationEnd,
            "reserved heap limits retain the complete BAR0 mapping for diagnostics");
    require(valid(descriptor, Active, nonceLo, nonceHi),
            "active descriptor preserves the launch nonce");

    uint64_t stale0 = 0x20000000, stale1 = 0x10000000;
    require(!activate(descriptor, stale0, stale1),
            "an already-active stale descriptor cannot activate again");
    require(stale0 == 0x20000000 && stale1 == 0x10000000,
            "failed activation cannot alter allocator limits");

    auto corrupt = pending(nonceLo, nonceHi);
    corrupt.checksum ^= 1;
    require(!activate(corrupt, stale0, stale1), "corrupt challenge is rejected");

    auto small = pending(nonceLo, nonceHi);
    uint64_t small0 = 0x10000000, small1 = 0x08000000;
    require(!activate(small, small0, small1),
            "reservation requires the complete BAR-visible range");
    require(barVisibleBytes(0x08000000, 0x10000000) == 0x08000000,
            "unreserved allocator limits remain conservative");
    std::puts("Recovery reservation fixtures passed");
}
