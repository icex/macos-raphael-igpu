#include <cassert>
#include <cstring>
#include <cstdint>
#include <limits>

#include "../src/AllocationLogBudget.hpp"

static uint64_t targetFor(uint64_t site, const uint8_t (&call)[5]) {
    uint32_t encoded = 0;
    for (unsigned i = 0; i < 4; ++i)
        encoded |= static_cast<uint32_t>(call[i + 1]) << (i * 8);
    int32_t displacement = 0;
    std::memcpy(&displacement, &encoded, sizeof(displacement));
    return static_cast<uint64_t>(static_cast<int64_t>(site + 5) + displacement);
}

int main() {
    uint8_t call[5] {};
    constexpr uint64_t site = 0x100000000ULL;
    assert(RaphaelAllocationLog::makeCall(site, site + 5 + 0x7fffffffULL, call));
    assert(targetFor(site, call) == site + 5 + 0x7fffffffULL);
    assert(!RaphaelAllocationLog::makeCall(site, site + 5 + 0x80000000ULL, call));
    assert(RaphaelAllocationLog::makeCall(site, site + 5 - 0x80000000ULL, call));
    assert(targetFor(site, call) == site + 5 - 0x80000000ULL);
    assert(!RaphaelAllocationLog::makeCall(site, site + 5 - 0x80000001ULL, call));
    assert(!RaphaelAllocationLog::makeCall(std::numeric_limits<uint64_t>::max() - 4,
                                           0, call));

    assert(!RaphaelAllocationLog::emit(0));
    for (uint64_t count = 1; count <= 8; ++count)
        assert(RaphaelAllocationLog::emit(count));
    assert(!RaphaelAllocationLog::emit(9));
    assert(RaphaelAllocationLog::emit(1024));
    assert(!RaphaelAllocationLog::emit(1025));
    assert(RaphaelAllocationLog::emit(2048));
}
