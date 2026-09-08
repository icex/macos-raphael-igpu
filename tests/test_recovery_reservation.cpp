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
    constexpr uint64_t nonceLo = 0xaaaaaaaaaaaaaaaaULL;
    constexpr uint64_t nonceHi = 0xaaaaaaaaaaaaaaaaULL;
    auto descriptor = pending(nonceLo, nonceHi);
    require(valid(descriptor, Pending, nonceLo, nonceHi), "pending challenge validates");

    uint64_t pool0 = 0x20000000, pool1 = 0x10000000;
    require(activate(descriptor, pool0, pool1), "guest activates a pending challenge");
    require(pool0 == HeapLimit && pool1 == HeapLimit,
            "both allocator pools end below the recovery reservation");
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
