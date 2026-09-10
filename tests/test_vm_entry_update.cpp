#include <cstdio>
#include <cstdlib>
#include <limits>

#include "../src/VmEntryUpdate.hpp"

static void require(bool condition, const char *message) {
    if (!condition) {
        std::fprintf(stderr, "FAIL: %s\n", message);
        std::exit(1);
    }
}

struct NativeCall {
    void *self {};
    uint64_t destination {};
    uint64_t count {};
    uint64_t source {};
    uint64_t attributes {};
    uint64_t increment {};
};

int main() {
    using namespace RaphaelVm;
    constexpr uint32_t fbBase = 0xf400;
    constexpr uint32_t fbTop = 0xf41f;
    constexpr uint32_t fbOffset = 0x840;
    constexpr uint64_t attributes = 0x2000000000000001ULL;

    auto child = prepareEntryUpdate(true, fbBase, fbTop, fbOffset, 0x55a72,
        0x84b6f2000ULL, 1, 0xf40b6f4000ULL, attributes, 0);
    require(child.domain == UpdateDomain::Converted &&
                child.producer == UpdateProducer::Child &&
                child.result == 0x84b6f4000ULL &&
                child.constructed == 0x200000084b6f4001ULL,
            "the captured child-PDE source is converted at the real consumer");

    auto leaf = prepareEntryUpdate(true, fbBase, fbTop, fbOffset, 0x559dc,
        0x84b700000ULL, 4, 0xf40b800000ULL, 1, 0x1000);
    require(leaf.domain == UpdateDomain::Converted &&
                leaf.producer == UpdateProducer::Leaf &&
                leaf.result == 0x84b800000ULL,
            "a multi-entry leaf source uses the separately supplied nonzero address");

    auto last = prepareEntryUpdate(true, fbBase, fbTop, fbOffset, 0x559dc,
        0, 1, 0xf41fffffffULL, 1, 0);
    require(last.domain == UpdateDomain::Converted && last.result == 0x85fffffffULL,
            "the final MC aperture byte remains eligible");

    auto oneIncrement = prepareEntryUpdate(true, fbBase, fbTop, fbOffset, 0x559dc,
        0, 2, 0xf41ffff000ULL, 1, 0xfff);
    require(oneIncrement.domain == UpdateDomain::Converted &&
                oneIncrement.spanEnd == 0xf41fffffffULL,
            "entry count applies count minus one increments in native entry units");

    auto span = prepareEntryUpdate(true, fbBase, fbTop, fbOffset, 0x559dc,
        0, 2, 0xf41ffff000ULL, 1, 0x1000);
    require(span.domain == UpdateDomain::SpanOutside &&
                span.result == span.source,
            "a batch crossing the MC aperture is refused atomically");

    auto multiplyOverflow = prepareEntryUpdate(true, fbBase, fbTop, fbOffset, 0x559dc,
        0, 3, 0xf40b6f4000ULL, 1,
        std::numeric_limits<uint64_t>::max() / 2 + 1);
    require(multiplyOverflow.domain == UpdateDomain::Overflow &&
                multiplyOverflow.result == multiplyOverflow.source,
            "the progression multiplication is checked before conversion");
    auto addOverflow = prepareEntryUpdate(true, fbBase, fbTop, fbOffset, 0x559dc,
        0, 2, std::numeric_limits<uint64_t>::max() - 2, 1, 4);
    require(addOverflow.domain == UpdateDomain::Overflow,
            "the progression addition is checked before conversion");

    require(prepareEntryUpdate(true, fbBase, fbTop, fbOffset, 0x561f6,
                0, 1, 0, 0, 0).domain == UpdateDomain::InvalidTemplate,
            "the native unmap form passes through unchanged");
    require(prepareEntryUpdate(true, fbBase, fbTop, fbOffset, 0x559dc,
                0, 1, 0xf40b6f4000ULL, 3, 0).domain == UpdateDomain::System,
            "SYSTEM template bit 1 forbids framebuffer conversion");
    require(prepareEntryUpdate(true, fbBase, fbTop, fbOffset, 0x559dc,
                0, 1, 0x84b6f4000ULL, 1, 0).domain == UpdateDomain::AlreadyPhysical,
            "an already physical source is never converted twice");
    require(prepareEntryUpdate(true, fbBase, fbTop, fbOffset, 0x559dc,
                0, 1, 0x400200000ULL, 1, 0).domain == UpdateDomain::Outside,
            "an unrelated guest physical source passes through");
    require(prepareEntryUpdate(true, 0, fbTop, fbOffset, 0x559dc,
                0, 1, 0xf40b6f4000ULL, 1, 0).domain == UpdateDomain::InvalidAperture,
            "an unpublished aperture refuses conversion");
    require(prepareEntryUpdate(true, 0, fbTop, fbOffset, 0x559dc,
                0, 1, 0, 1, 0).domain == UpdateDomain::InvalidAperture,
            "a zero source cannot conceal an invalid published aperture");
    require(prepareEntryUpdate(false, fbBase, fbTop, fbOffset, 0x55a72,
                0, 1, 0xf40b6f4000ULL, 1, 0).domain == UpdateDomain::Inactive,
            "an unmarked target refuses conversion");
    require(prepareEntryUpdate(true, fbBase, fbTop, fbOffset, 0x559dc,
                0, 0, 0xf40b6f4000ULL, 1, 0).domain == UpdateDomain::Empty,
            "an empty update is preserved");
    require(prepareEntryUpdate(true, fbBase, fbTop, fbOffset, 0x559dc,
                0, 1, 0, 1, 0).domain == UpdateDomain::ZeroSource,
            "a valid zero-address entry is observed without conversion");

    NativeCall captured {};
    int object = 0;
    auto native = [&](void *self, uint64_t destination, uint64_t count,
                      uint64_t source, uint64_t templateValue, uint64_t increment) {
        captured = {self, destination, count, source, templateValue, increment};
    };
    forwardEntryUpdate(native, &object, child);
    require(captured.self == &object && captured.destination == child.destination &&
                captured.count == child.count && captured.source == child.result &&
                captured.attributes == child.templateValue &&
                captured.increment == child.increment,
            "the forwarding helper changes only the real source operand");
    forwardEntryUpdate(native, &object, leaf);
    require(captured.destination == leaf.destination && captured.count == 4 &&
                captured.source == leaf.result && captured.attributes == 1 &&
                captured.increment == 0x1000,
            "a multi-entry leaf forwards native count/template/increment unchanged");
    auto system = prepareEntryUpdate(true, fbBase, fbTop, fbOffset, 0x559dc,
        0x400100000ULL, 2, 0xf40b6f4000ULL, 3, 0x1000);
    forwardEntryUpdate(native, &object, system);
    require(captured.source == system.source && captured.attributes == 3 &&
                captured.increment == 0x1000,
            "SYSTEM forwarding preserves the original source and native operands");
    auto unmap = prepareEntryUpdate(true, fbBase, fbTop, fbOffset, 0x561f6,
        0x84b6f2000ULL, 1, 0, 0, 0);
    forwardEntryUpdate(native, &object, unmap);
    require(captured.source == 0 && captured.attributes == 0 && captured.count == 1,
            "unmap forwarding preserves the native zero source and template");

    UpdateSummarySchedule schedule;
    uint64_t counts[kUpdateDomainCount] {};
    size_t publications = 0;
    for (uint64_t n = 1; n <= 1000000; ++n) {
        counts[static_cast<size_t>(UpdateDomain::Outside)] = n;
        if (schedule.shouldPublish(counts)) ++publications;
    }
    require(publications > 1 && publications < 32,
            "continuous callbacks produce bounded summaries without waiting for quiet");
    counts[static_cast<size_t>(UpdateDomain::Converted)] = 1;
    require(schedule.shouldPublish(counts),
            "the first late conversion publishes independently of the next threshold");
    counts[static_cast<size_t>(UpdateDomain::SpanOutside)] = 1;
    require(schedule.shouldPublish(counts),
            "the first late fatal span publishes after high legitimate volume");
    require(!schedule.shouldPublish(counts),
            "an unchanged non-threshold snapshot does not consume replay capacity");

    std::puts("VM entry-update fixtures passed");
}
