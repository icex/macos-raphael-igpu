#include <cstdio>
#include <cstdlib>
#include "../src/KiqAddresses.hpp"

static void require(bool condition, const char *message) {
    if (!condition) {
        std::fprintf(stderr, "FAIL: %s\n", message);
        std::exit(1);
    }
}

int main() {
    constexpr uint64_t bar = 0xf400000000ULL;
    constexpr uint64_t reserved = 0xebc0000000ULL;
    constexpr uint64_t mc = 0x840000000ULL;
    constexpr uint64_t top = 0x85fffffffULL;
    constexpr uint64_t visible = 0x10000000ULL;
    RaphaelKiq::Addresses result {};
    auto plan = [&](uint64_t mqd, uint64_t eop) {
        return RaphaelKiq::planAddresses(bar, reserved, mc, top, visible, mqd, eop, result);
    };

    // Measured BAR-relative descriptor and EOP, independently calculated MC fixture.
    require(plan(0xf40b706000ULL, 0xf40b706800ULL), "accept measured BAR addresses");
    require(result.mqdMc == 0x84b706000ULL, "MQD uses MC aperture");
    require(result.eopMc == 0x84b706800ULL, "EOP uses MC aperture");
    require(result.imageOffset == 0x0b706000ULL, "image uses BAR offset");
    require(plan(0x84b706000ULL, 0x84b706800ULL), "already-MC addresses are idempotent");
    require(result.mqdMc == 0x84b706000ULL && result.eopMc == 0x84b706800ULL,
            "do not subtract relocation twice");
    require(plan(bar + visible - 0x1000, bar + visible - 0x800),
            "last complete allocation in mapped aperture");
    require(!plan(bar + visible, bar + visible + 0x800), "reject non-visible VRAM");
    require(!plan(0xffbfea0000ULL, 0xffbfea0800ULL), "GART VA is not a framebuffer pointer");
    require(!plan(reserved + 0xb706000, reserved + 0xb706800), "reject reserved-relative input");
    require(!plan(0, 0x800), "reject null descriptor");
    require(!plan(bar + 0xb706004, bar + 0xb706804), "reject unaligned descriptor");
    require(!plan(bar + 0xb706000, bar + 0xb706900), "EOP must follow the 2048-byte MQD");
    require(!plan(bar + 0xb706000, bar + 0xb707000), "reject unrelated EOP allocation");
    require(!plan(UINT64_MAX - 0x7ff, 0), "reject wrapping input");
    require(!RaphaelKiq::planAddresses(bar, reserved + 1, mc, top, visible,
                                     bar + 0xb706000, bar + 0xb706800, result),
            "cross-check software relocation against hardware base");
    require(!RaphaelKiq::planAddresses(bar, reserved, mc, mc - 1, visible,
                                     bar + 0xb706000, bar + 0xb706800, result),
            "reject inverted hardware aperture");
    require(!RaphaelKiq::planAddresses(bar, reserved, mc, top, 0,
                                     bar + 0xb706000, bar + 0xb706800, result),
            "reject absent BAR mapping");
    require(!RaphaelKiq::planAddresses(bar, bar + 1, mc, top, visible,
                                     bar + 0xb706000, bar + 0xb706800, result),
            "reject relocation underflow");
    require(!RaphaelKiq::planAddresses(bar, reserved, mc, UINT64_MAX, visible,
                                     bar + 0xb706000, bar + 0xb706800, result),
            "reject framebuffer outside 48-bit MC space");
    std::puts("KIQ address fixtures passed");
}
