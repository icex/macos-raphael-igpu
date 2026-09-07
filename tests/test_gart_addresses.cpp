#include <cstdio>
#include <cstdlib>
#include <initializer_list>
#include "../src/GartAddresses.hpp"

static void require(bool value, const char *message) {
    if (!value) { std::fprintf(stderr, "FAIL: %s\n", message); std::exit(1); }
}
int main() {
    using namespace RaphaelGart;
    constexpr uint64_t bar = 0xf400000000ULL, physical = 0x840000000ULL;
    uint64_t field = 0;
    require(physicalFbField(0xf400, 0xf41f, 0x840, bar, 0x20000000, 0, field) &&
            field == physical, "relocated framebuffer uses GC physical FB_OFFSET");
    require(physicalFbField(0x840, 0x85f, 0x840, physical, 0x20000000, 0, field) &&
            field == physical, "older identity framebuffer has same physical base");
    require(physicalFbField(0xf400, 0xf41f, 0x840, bar, 0x10000000, physical, field) &&
            field == physical, "already correct physical field is idempotent");
    require(!physicalFbField(0xf400, 0xf41f, 0x840, bar, 0x20000000, 1, field),
            "do not override unexplained native physical field");
    for (uint32_t raw : {0u, 0xffffffffu, 0x1000840u, 0xdeadbeefu})
        require(!physicalFbField(0xf400, 0xf41f, raw, bar, 0x20000000, 0, field),
                "reject absent or invalid offset register");
    require(!physicalFbField(0xf400, 0xf3ff, 0x840, bar, 0x20000000, 0, field), "inverted MC aperture");
    require(!physicalFbField(0x100f400, 0xf41f, 0x840, bar, 0x20000000, 0, field), "bad base register");
    require(!physicalFbField(0xf400, 0xffffffff, 0x840, bar, 0x20000000, 0, field), "bad top register");
    require(!physicalFbField(0xf400, 0xf41f, 0x840, physical, 0x20000000, 0, field), "native MC base mismatch");
    require(!physicalFbField(0xf400, 0xf41f, 0x840, bar, 0x20000001, 0, field), "native extent outside MC aperture");
    require(!physicalFbField(0xf400, 0xf41f, 0x840, bar, 0, 0, field), "empty native extent");
    require(!physicalFbField(0xf400, 0xf41f, 0xffffff, bar, 0x20000000, 0, field), "physical 48-bit extent overflow");

    Aperture relocated {bar, 0, bar, 0xf41fffffffULL, physical, 0x10000000, bar, MemoryForm::LegacyRelocation};
    Aperture identity {bar, 0xebc0000000ULL, physical, 0x85fffffffULL, physical, 0x10000000, physical, MemoryForm::LegacyRelocation};
    Range range {0xffbfa00, 0xffffe00};
    Table table {};
    Aperture run156 {bar, physical, bar, 0xf41fffffffULL, physical, 0x10000000, bar - physical, MemoryForm::NativePhysical};
    require(physicalTable(run156, range, 0x1555481, 0x84fdfc001ULL, table),
            "run156 physical field and physical GART root accepted");
    require(table.offset == 0xfdfc000 && table.bytes == 0x202008, "run156 complete table offset");
    auto inconsistent = run156; inconsistent.field58 += 0x1000; inconsistent.delta60 -= 0x1000;
    require(!physicalTable(inconsistent, range, 1, 0x84fdfc001ULL, table), "native physical field must match register");
    inconsistent = run156; inconsistent.delta60 = bar;
    require(!physicalTable(inconsistent, range, 1, 0x84fdfc001ULL, table), "native delta must match initialized object");
    inconsistent = run156; inconsistent.form = MemoryForm::LegacyRelocation;
    require(!physicalTable(inconsistent, range, 1, 0x84fdfc001ULL, table), "native state is not accepted as legacy relocation");
    inconsistent = relocated; inconsistent.form = MemoryForm::NativePhysical;
    require(!physicalTable(inconsistent, range, 1, 0x84fdfc001ULL, table), "native form does not fall back to legacy zero field");
    require(physicalTable(relocated, range, 0x1555401, 0x84fdfc001ULL, table), "zero reserved is valid");
    require(table.offset == 0xfdfc000 && table.bytes == 0x202008, "entire inclusive flat table validated");
    require(physicalTable(identity, range, 0x1555481, 0x84fdfc005ULL, table), "old physical root and cache flag valid");
    for (uint64_t flags : {0ULL, 2ULL, 3ULL, 8ULL, 0x40ULL, 0x100ULL})
        require(!physicalTable(relocated, range, 1, 0x84fdfc000ULL | flags, table), "unsupported root flags/alignment");
    require(!physicalTable(relocated, range, 3, 0x84fdfc001ULL, table), "reject non-flat context");
    require(!physicalTable(relocated, range, 0, 0x84fdfc001ULL, table), "reject disabled context");
    require(!physicalTable(relocated, range, UINT32_MAX, 0x84fdfc001ULL, table), "failed context register read");
    for (uint64_t root : {0xfdfc001ULL, 0xebcfdfc001ULL, 0xf40fdfc001ULL})
        require(!physicalTable(relocated, range, 1, root, table), "native-relative and logical MC roots are not physical");
    require(!physicalTable(relocated, {10, 9}, 1, physical + 1, table), "inverted page range");
    require(!physicalTable(relocated, {0, UINT64_MAX}, 1, physical + 1, table), "page-count overflow");
    auto bad = relocated; bad.field58 = 1;
    require(!physicalTable(bad, range, 1, 0x84fdfc001ULL, table), "software relocation cross-check");
    bad = relocated; bad.swBase += 1; bad.field58 = 1;
    require(!physicalTable(bad, range, 1, 0x84fdfc001ULL, table), "unaligned software allocation base");
    bad = relocated; bad.field58 = UINT64_MAX;
    require(!physicalTable(bad, range, 1, 0x84fdfc001ULL, table), "software subtraction underflow");
    bad = relocated; bad.visibleBytes = 0x1000;
    require(!physicalTable(bad, range, 1, physical + 1, table), "whole table must fit");
    require(physicalTable(relocated, {0, 511}, 1, physical + 0x0ffff001, table), "last 4KiB table fits exactly");
    require(!physicalTable(relocated, {0, 512}, 1, physical + 0x0ffff001, table), "one extra PTE beyond aperture");
    Range parsed {};
    require(rangeFromRegisters(0xffbfa00, 0, 0xffffe00, 0, parsed) && parsed.firstPage == range.firstPage &&
            parsed.lastPage == range.lastPage, "measured hardware range decodes");
    require(rangeFromRegisters(0, 1, 0, 1, parsed) && parsed.firstPage == 0x100000000ULL,
            "register high words contribute to full 48-bit VA");
    require(!rangeFromRegisters(0, 16, 0, 16, parsed), "unsupported high register bits");
    uint64_t offset = 0, index = 0;
    require(pteOffset(run156, range, 1, 0x84fdfc001ULL, 0xffbfea0000ULL, offset, index) &&
            offset == 0xfdfe500 && index == 0x4a0, "run156 ring PTE offset");
    require(pteOffset(run156, range, 1, 0x84fdfc001ULL, 0xffbfde0050ULL, offset, index) &&
            offset == 0xfdfdf00 && index == 0x3e0, "run156 poll PTE offset");
    require(pteOffset(relocated, range, 1, 0x84fdfc001ULL, 0xffbfea0000ULL, offset, index) &&
            offset == 0xfdfe500 && index == 0x4a0, "measured ring PTE offset");
    require(pteOffset(relocated, range, 1, 0x84fdfc001ULL, 0xffbfde0050ULL, offset, index) &&
            offset == 0xfdfdf00 && index == 0x3e0, "measured poll/report PTE offset");
    require(!pteOffset(relocated, range, 1, 0x84fdfc001ULL, 0xffbfa00000ULL - 1, offset, index), "VA below start");
    require(!pteOffset(relocated, range, 1, 0x84fdfc001ULL, 0xffffe01000ULL, offset, index), "VA above inclusive last page");
    require(!pteOffset(relocated, range, 1, 0x84fdfc001ULL, UINT64_MAX, offset, index), "VA overflow");
    require(pteOffset(relocated, {0x100000000ULL, 0x100000000ULL}, 1, physical + 1,
                      0x100000000fffULL, offset, index) && offset == 0 && index == 0, "high VA page final byte");
    std::puts("GART address fixtures passed");
}
