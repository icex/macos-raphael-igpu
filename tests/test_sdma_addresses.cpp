#include <cstdio>
#include <cstdlib>
#include <initializer_list>
#include "../src/SdmaAddresses.hpp"

static void require(bool condition, const char *message) {
    if (!condition) {
        std::fprintf(stderr, "FAIL: %s\n", message);
        std::exit(1);
    }
}

int main() {
    using RaphaelSdma::AddressRepair;
    using RaphaelSdma::repairTruncatedFramebufferAddress;

    constexpr uint64_t swBase = 0xf400000000ULL;
    constexpr uint64_t physicalBase = 0x840000000ULL;
    constexpr uint64_t bytes = 0x10000000ULL;

    auto first = repairTruncatedFramebufferAddress(
        0x400100000ULL, swBase, physicalBase, bytes);
    require(first.valid && first.changed && first.address == 0x840100000ULL,
            "the measured SDMA paging IB is translated into the physical FB aperture");

    auto last = repairTruncatedFramebufferAddress(
        0x40fffffffULL, swBase, physicalBase, bytes);
    require(last.valid && last.changed && last.address == 0x84fffffffULL,
            "the final byte of the framebuffer range is translated");

    auto physical = repairTruncatedFramebufferAddress(
        0x840100000ULL, swBase, physicalBase, bytes);
    require(physical.valid && !physical.changed && physical.address == 0x840100000ULL,
            "an already physical address remains unchanged");

    for (uint64_t outside : {0x3ffffffffULL, 0x410000000ULL, 0xffbff40000ULL}) {
        AddressRepair repair = repairTruncatedFramebufferAddress(
            outside, swBase, physicalBase, bytes);
        require(!repair.valid && !repair.changed && repair.address == outside,
                "an address outside the exact truncated framebuffer window is rejected");
    }

    auto noTruncation = repairTruncatedFramebufferAddress(
        0x400100000ULL, 0x400000000ULL, physicalBase, bytes);
    require(!noTruncation.valid && !noTruncation.changed,
            "a software aperture already representable in 36 bits is not reinterpreted");

    for (uint64_t invalidBytes : {0ULL, 0x1000000001ULL}) {
        auto invalid = repairTruncatedFramebufferAddress(
            0x400100000ULL, swBase, physicalBase, invalidBytes);
        require(!invalid.valid && !invalid.changed,
                "unsupported framebuffer extents cannot enable repair");
    }

    std::puts("SDMA address fixtures passed");
}
