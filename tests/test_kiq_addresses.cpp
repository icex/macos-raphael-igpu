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
    using RaphaelGart::Aperture;
    using RaphaelGart::MemoryForm;
    // Historical capture supported the old relocation heuristic. This is an
    // explicit compatibility fixture, not the meaning of native field+0x58.
    Aperture legacy {bar, reserved, mc, top, mc, visible, mc, MemoryForm::LegacyRelocation};
    Aperture native {bar, mc, bar, 0xf41fffffffULL, mc, visible, bar - mc, MemoryForm::NativePhysical};
    RaphaelKiq::Addresses result {};
    auto plan = [&](uint64_t mqd, uint64_t eop) {
        return RaphaelKiq::planAddresses(legacy, mqd, eop, result);
    };

    // Run156: the propagated physical base does not relocate canonical MC inputs.
    require(RaphaelKiq::planAddresses(native, 0xf40b706000ULL, 0xf40b706800ULL, result),
            "run156 native physical field must not block canonical MC queue");
    require(result.mqdMc == 0xf40b706000ULL && result.eopMc == 0xf40b706800ULL &&
            result.imageOffset == 0xb706000, "run156 queue addresses unchanged");
    require(RaphaelKiq::planAddresses(native, result.mqdMc, result.eopMc, result),
            "run156 canonical MC preparation is idempotent");
    require(!RaphaelKiq::planAddresses(native, 0x84b706000ULL, 0x84b706800ULL, result),
            "physical framebuffer addresses are not native queue MC addresses");
    auto badNative = native; badNative.field58 += 0x1000; badNative.delta60 -= 0x1000;
    require(!RaphaelKiq::planAddresses(badNative, bar + 0xb706000, bar + 0xb706800, result),
            "native physical field must equal GC FB_OFFSET");
    badNative = native; badNative.delta60 += 0x1000;
    require(!RaphaelKiq::planAddresses(badNative, bar + 0xb706000, bar + 0xb706800, result),
            "native initialized delta must agree");
    badNative = native; badNative.field58 = 0; badNative.delta60 = bar;
    require(!RaphaelKiq::planAddresses(badNative, bar + 0xb706000, bar + 0xb706800, result),
            "native mode rejects the old zero field despite legacy predicate matching");
    badNative = native; badNative.swBase += 0x1000; badNative.delta60 += 0x1000;
    require(!RaphaelKiq::planAddresses(badNative, bar + 0xb706000, bar + 0xb706800, result),
            "native software base must equal logical MC base");

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
    auto bad = legacy; bad.field58 += 1;
    require(!RaphaelKiq::planAddresses(bad, bar + 0xb706000, bar + 0xb706800, result),
            "cross-check legacy relocation against hardware base");
    bad = legacy; bad.mcTop = mc - 1;
    require(!RaphaelKiq::planAddresses(bad, bar + 0xb706000, bar + 0xb706800, result),
            "reject inverted hardware aperture");
    bad = legacy; bad.visibleBytes = 0;
    require(!RaphaelKiq::planAddresses(bad, bar + 0xb706000, bar + 0xb706800, result),
            "reject absent BAR mapping");
    bad = legacy; bad.field58 = bar + 1;
    require(!RaphaelKiq::planAddresses(bad, bar + 0xb706000, bar + 0xb706800, result),
            "reject subtraction underflow");
    bad = legacy; bad.mcTop = UINT64_MAX;
    require(!RaphaelKiq::planAddresses(bad, bar + 0xb706000, bar + 0xb706800, result),
            "reject framebuffer outside 48-bit MC space");
    std::puts("KIQ address fixtures passed");
}
