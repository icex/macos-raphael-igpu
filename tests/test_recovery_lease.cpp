#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <map>
#include <string>
#include <thread>

#include "../src/RecoveryLease.hpp"

static void require(bool condition, const char *message) {
    if (!condition) {
        std::fprintf(stderr, "FAIL: %s\n", message);
        std::exit(1);
    }
}

static std::map<std::string, std::string> loadGolden() {
    std::ifstream input("tests/fixtures/recovery-lease-v2-golden.txt");
    std::map<std::string, std::string> values;
    std::string line;
    while (std::getline(input, line)) {
        if (line.empty() || line[0] == '#') continue;
        auto split = line.find('=');
        if (split != std::string::npos)
            values[line.substr(0, split)] = line.substr(split + 1);
    }
    return values;
}

template <typename T>
static std::string wireHex(const T &value) {
    static const char digits[] = "0123456789abcdef";
    const auto bytes = reinterpret_cast<const unsigned char *>(&value);
    std::string out;
    out.reserve(sizeof(value) * 2);
    for (size_t i = 0; i < sizeof(value); ++i) {
        out.push_back(digits[bytes[i] >> 4]);
        out.push_back(digits[bytes[i] & 0xf]);
    }
    return out;
}

int main() {
    using namespace RaphaelRecoveryV2;

    require(sizeof(OwnershipDescriptor) == 80, "OWNED wire record stays 80 bytes");
    require(sizeof(PoolStatus) == 104, "POOL wire record stays 104 bytes");
    auto golden = loadGolden();
    require(!golden.empty(), "shared host/guest golden fixture is readable");
    auto goldenOwned = makeOwnership(0x0a000000, 0x0123456789abcdefULL,
                                     0xfedcba9876543210ULL);
    auto goldenActive = makePoolStatus(goldenOwned, PoolActive,
        0x0e000000, 0x0dfeb000, 0x0c000000, 0x0bfeb000, ReasonNone);
    auto goldenInvalid = makePoolStatus(goldenOwned, PoolInvalid,
        0x0e000000, 0x0dfeb000, 0x0c000000, 0x0c000000, ReasonPoolAddress);
    require(wireHex(goldenOwned) == golden["ownership"] &&
            wireHex(goldenActive) == golden["active"] &&
            wireHex(goldenInvalid) == golden["invalid"],
            "C++ final wire bytes match the shared Python/host fixture");

    // Native 24G830 clamps only visible > total. The proposed 256/512 swap
    // therefore collapses to 256/256; the measured 512/256 pair survives.
    auto measured = nativePoolSizes(0x20000000, 0x10000000);
    auto swapped = nativePoolSizes(0x10000000, 0x20000000);
    require(measured.total == 0x20000000 && measured.visible == 0x10000000,
            "native 512/256 sizes are ordered and retained");
    require(swapped.total == 0x10000000 && swapped.visible == 0x10000000,
            "native clamp turns 256/512 into 256/256");
    auto unequal = threeArgumentPoolInit(0xf400000000ULL, measured);
    require(unequal.totalEnd == 0xf420000000ULL &&
            unequal.reservedStart == 0xf410000000ULL && unequal.reservedLength == 0,
            "init_pool(Eyyy) receives total end, reserved start, and zero length");
    require(compatibilityPoolSize(measured) == 0x10000000,
            "first delta retains the complete 256 MiB BAR-visible pool");
    for (uint64_t capacity : {0x08000000ULL, 0x10000000ULL,
                              0x20000000ULL, 0x40000000ULL}) {
        DiscoveredPoolCapacities discovered {};
        require(discoverPoolCapacities(0x100, static_cast<uint32_t>(0x100 +
                    (capacity >> 24) - 1), capacity, capacity, capacity, discovered) &&
                    discovered.totalCapacity == capacity && discovered.visibleCapacity == capacity,
                "runtime capacity matrix accepts matching provider capacity");
        require(discoverPoolCapacities(0x100, static_cast<uint32_t>(0x100 +
                    (capacity >> 24) - 1), capacity * 2, capacity, capacity, discovered),
                "BAR capacity above total is harmlessly capped");
    }
    DiscoveredPoolCapacities discovered {};
    require(discoverPoolCapacities(0x100, 0x10f, 0x10000000, 0x10000000,
                                   0x08000000, discovered) &&
                discovered.pools.visible == 0x08000000,
            "provider reservation deduction preserves usable visible size");
    require(!discoverPoolCapacities(0x100, 0x10f, 0, 0x10000000, 0x10000000, discovered) &&
            !discoverPoolCapacities(0x200, 0x10f, 0x10000000, 0x10000000, 0x10000000, discovered) &&
            !discoverPoolCapacities(0x10000000, 0x10000001, 0x10000000, 0x10000000,
                                    0x10000000, discovered) &&
            !discoverPoolCapacities(0x100, 0x10f, 0x10000000, 0x08000000,
                                    0x10000000, discovered),
            "zero, reversed, invalid register, and total-below-visible capacities reject");

    constexpr uint64_t nonceLo = 0x0123456789abcdefULL;
    constexpr uint64_t nonceHi = 0xfedcba9876543210ULL;
    auto owned = makeOwnership(0x0b6f0000, nonceLo, nonceHi);
    require(validOwnership(owned, nonceLo, nonceHi, 0x10000000),
            "native lease produces a bounded OWNED descriptor");
    require(owned.leaseEnd == 0x0b705000 && owned.scratchOffset == 0x0b6f1000 &&
            owned.scratchEnd == 0x0b704004,
            "dynamic scratch geometry is rebased inside the 0x15000 lease");
    require(checksum(owned) == owned.checksum, "OWNED checksum covers every prior field");
    auto ownedNonce = logNonce(owned);
    require(ownedNonce.first == nonceLo && ownedNonce.second == nonceHi,
            "OWNED locator emits the manifest nonce in LOW_HIGH order");

    uint32_t ownedWords[sizeof(OwnershipDescriptor) / sizeof(uint32_t)] {};
    unsigned writes = 0, fences = 0;
    auto writeOwned = [&](uint32_t i, uint32_t value) {
        require(i == 3 || ownedWords[3] == 0,
                "OWNED state stays zero until its final commit store");
        ownedWords[i] = value;
        ++writes;
    };
    auto readOwned = [&](uint32_t i) { return ownedWords[i]; };
    auto fence = [&] { ++fences; };
    require(publishRecord(owned, writeOwned, readOwned, fence) && fences == 3 &&
            writes == sizeof(OwnershipDescriptor) / sizeof(uint32_t) + 1,
            "OWNED uses body-before-state publication and verifies full readback");
    auto corrupt = owned;
    corrupt.scratchEnd++;
    corrupt.checksum = checksum(corrupt);
    require(!validOwnership(corrupt, nonceLo, nonceHi, 0x10000000),
            "corrupt scratch geometry is rejected");
    corrupt = owned;
    corrupt.checksum ^= 1;
    require(!validOwnership(corrupt, nonceLo, nonceHi, 0x10000000),
            "independent checksum corruption is rejected");
    require(!validOwnership(owned, nonceLo ^ 1, nonceHi, 0x10000000),
            "stale launch nonce is rejected");
    require(!validOwnership(makeOwnership(0x0fff0000, nonceLo, nonceHi),
                            nonceLo, nonceHi, 0x10000000),
            "lease crossing the visible BAR end is rejected");
    require(!validOwnership(makeOwnership(0, nonceLo, nonceHi),
                            nonceLo, nonceHi, 0x10000000),
            "zero is not an acquired native lease offset");
    require(disjointFromRange(owned, 0x0b705000, 0x1000, 0x10000000) &&
            disjointFromRange(owned, 0x0b6ef000, 0x1000, 0x10000000),
            "GART ranges immediately adjacent to the lease are accepted");
    require(!disjointFromRange(owned, 0x0b704fff, 1, 0x10000000) &&
            !disjointFromRange(owned, 0x0b6f0000, 1, 0x10000000),
            "either one-byte GART overlap is rejected");
    require(!disjointFromRange(owned, UINT64_MAX - 0x1000, 0x2000,
                               0x10000000) &&
            !disjointFromRange(owned, 0x0ffff000, 0x2000, 0x10000000),
            "wrapped or BAR-escaping GART extents are rejected");

    require(logicalDisjointFromRange(owned, 0x10000000, 0x04400000,
                                     0x20000000, 0x10000000),
            "upper logical VMM range is accepted with visible lease");
    require(!logicalDisjointFromRange(owned, 0x0a000000, 0x04400000,
                                      0x20000000, 0x10000000),
            "logical VMM range overlapping lease is rejected");
    require(!logicalDisjointFromRange(owned, 0x1f000000, 0x02000000,
                                      0x20000000, 0x10000000) &&
            !logicalDisjointFromRange(owned, UINT64_MAX - 0x1000, 0x2000,
                                      0x20000000, 0x10000000),
            "logical VMM range escaping total or wrapping is rejected");

    uint64_t fullAddress = 0;
    require(fullPoolAddress(0xf400000000ULL, owned.leaseOffset, fullAddress) &&
            fullAddress == 0xf40b6f0000ULL,
            "software pools receive full base plus BAR lease offset");
    const auto goodFullAddress = fullAddress;
    require(!fullPoolAddress(UINT64_MAX - 0x1000, 0x2000, fullAddress) &&
            fullAddress == goodFullAddress,
            "full pool address addition rejects overflow");

    uint64_t leaseOffset = 0, cursorAfterLease = 0, vmmOffset = 0, cursorAfterVmm = 0;
    require(topDownReserve(0x0fb08000, LeaseSize, 0x1000,
                           leaseOffset, cursorAfterLease) &&
            leaseOffset == 0x0faf3000 && cursorAfterLease == leaseOffset,
            "native type-0 lease is allocated first from the top-down cursor");
    require(topDownReserve(cursorAfterLease, 0x04400000, 0x1000,
                           vmmOffset, cursorAfterVmm) &&
            vmmOffset == 0x0b6f3000 && cursorAfterVmm == vmmOffset &&
            vmmOffset + 0x04400000 == leaseOffset,
            "following 68 MiB VMM allocation is disjoint below the lease");
    uint64_t predicted = 0, predictedNext = 0;
    require(predictNativeVmmRange(0x1faf3000, 0x1faf3000, 0x04400000, 0x1000,
                                  0x10000000, 0x20000000, 0x20000000, 0x10000000,
                                  predicted, predictedNext) &&
            predicted == 0x1b6f3000 && predictedNext == predicted,
            "native secondary cursor predicts the 68 MiB VMM interval");
    for (uint64_t capacity : {0x08000000ULL, 0x10000000ULL}) {
        const uint64_t cursor = capacity - LeaseSize;
        require(predictNativeVmmRange(cursor, 0x1abcdef0, 0x04400000, 0x1000,
                                      capacity, capacity, capacity, capacity,
                                      predicted, predictedNext) &&
                predicted == ((cursor - 0x04400000) & ~0xfffULL) &&
                predicted + 0x04400000 <= capacity,
                "equal provider pools select a primary range inside visible capacity");
    }
    require(!predictNativeVmmRange(0x10000000, 0x1abcdef0, 0x04400000, 0x1000,
                                   0x10000000, 0x20000000, 0x08000000, 0x08000000,
                                   predicted, predictedNext),
            "primary cursor above provider capacity is rejected");
    require(!predictNativeVmmRange(0x04400000, 0x04400000, 0x04400000, 0x1000,
                                   0x10000000, 0x20000000, 0x20000000, 0x10000000,
                                   predicted, predictedNext) &&
            !predictNativeVmmRange(0x22000000, 0x22000000, 0x02000000, 0x1000,
                                   0x10000000, 0x20000000, 0x20000000, 0x10000000,
                                   predicted, predictedNext),
            "zero-width or total-escaping native cursor prediction is rejected");
    require(0x0b708000ULL + 0x04400000ULL == 0x0fb08000ULL &&
            0x0fb08000ULL > 0x0f000000ULL &&
            0x0fb08000ULL <= 0x10000000ULL,
            "preserved VMM arena escapes the old 240 MiB cap but fits 256 MiB");

    unsigned sequence = 0;
    LeaseState ordered {};
    bool ready = establishBeforeVmm(ordered, nonceLo, nonceHi, 0x10000000,
        [&] { require(sequence++ == 0, "owner and method preflight is first"); return true; },
        [&] { require(sequence++ == 1, "native append follows preflight"); return 0x0faf3000ULL; },
        [&](const OwnershipDescriptor &value) {
            require(sequence++ == 2 && value.leaseOffset == 0x0faf3000,
                    "live GART validation follows native append");
            return true;
        },
        [&](const OwnershipDescriptor &value) {
            require(sequence++ == 3 && value.leaseOffset == 0x0faf3000,
                    "OWNED write/readback precedes native VMM");
            return true;
        },
        [&] { require(sequence++ == 4 && ordered.kiqAllowed(),
                      "native VMM sees published ownership"); });
    require(ready && sequence == 5, "ready callback ordering is complete");
    unsigned duplicatePreflight = 0, duplicateAppend = 0, duplicateValidate = 0;
    unsigned duplicatePublish = 0, duplicateNative = 0;
    require(!establishBeforeVmm(ordered, nonceLo, nonceHi, 0x10000000,
                [&] { ++duplicatePreflight; return true; },
                [&] { ++duplicateAppend; return 0x0fad0000ULL; },
                [&](const OwnershipDescriptor &) { ++duplicateValidate; return true; },
                [&](const OwnershipDescriptor &) { ++duplicatePublish; return true; },
                [&] { ++duplicateNative; }) &&
            duplicatePreflight == 0 && duplicateAppend == 0 && duplicateValidate == 0 &&
            duplicatePublish == 0 && duplicateNative == 0 &&
            ordered.phase() == Phase::Invalid,
            "duplicate ready epoch performs no second native mutation");

    for (unsigned iteration = 0; iteration < 1000; ++iteration) {
        LeaseState concurrentReady {};
        std::atomic<unsigned> readyThreads {0};
        std::atomic<unsigned> appendCalls {0};
        std::atomic<unsigned> nativeCalls {0};
        auto attempt = [&] {
            ++readyThreads;
            while (readyThreads.load() != 2) std::this_thread::yield();
            establishBeforeVmm(
                concurrentReady, nonceLo, nonceHi, 0x10000000,
                [] { return true; },
                [&] { ++appendCalls; return 0x0faf3000ULL; },
                [](const OwnershipDescriptor &) { return true; },
                [](const OwnershipDescriptor &) { return true; },
                [&] { ++nativeCalls; });
        };
        std::thread first(attempt);
        std::thread second(attempt);
        first.join();
        second.join();
        require(appendCalls.load() == 1 && nativeCalls.load() <= 1 &&
                concurrentReady.phase() == Phase::Invalid,
                "concurrent ready calls permit at most one append/native epoch");
    }

    LeaseState wrongOwner {};
    unsigned ownerAppend = 0, ownerNative = 0;
    require(!establishBeforeVmm(wrongOwner, nonceLo, nonceHi, 0x10000000,
                [] { return false; },
                [&] { ++ownerAppend; return 0x0faf3000ULL; },
                [](const OwnershipDescriptor &) { return true; },
                [](const OwnershipDescriptor &) { return true; },
                [&] { ++ownerNative; }) && ownerAppend == 0 && ownerNative == 0 &&
            wrongOwner.phase() == Phase::Invalid,
            "wrong hardware owner or vtable target fails before native append");

    LeaseState gartConflict {};
    unsigned conflictPublish = 0, conflictNative = 0;
    require(!establishBeforeVmm(gartConflict, nonceLo, nonceHi, 0x10000000,
                [] { return true; },
                [] { return 0x0faf3000ULL; },
                [](const OwnershipDescriptor &) { return false; },
                [&](const OwnershipDescriptor &) { ++conflictPublish; return true; },
                [&] { ++conflictNative; }) && conflictPublish == 0 &&
            conflictNative == 0 && gartConflict.phase() == Phase::Invalid,
            "live GART overlap rejects publication and the native VMM append");

    auto active = makePoolStatus(owned, PoolActive,
        0x10000000, 0x0ffeb000, 0x10000000, 0x0ffeb000, ReasonNone);
    require(validPoolStatus(active, owned),
            "ACTIVE requires exact 0x15000 loss from both pools");
    auto activeNonce = logNonce(active);
    require(activeNonce.first == nonceLo && activeNonce.second == nonceHi,
            "POOL locator emits the manifest nonce in LOW_HIGH order");
    uint32_t poolWords[sizeof(PoolStatus) / sizeof(uint32_t)];
    for (auto &word : poolWords) word = 0xffffffffU;
    require(clearRecord<PoolStatus>(
                [&](uint32_t i, uint32_t v) { poolWords[i] = v; },
                [&](uint32_t i) { return poolWords[i]; }, fence),
            "POOL slot is cleared and read back before OWNED is published");
    require(publishRecord(active,
                [&](uint32_t i, uint32_t v) {
                    require(i == 3 || poolWords[3] == 0,
                            "POOL state stays zero until its final commit store");
                    poolWords[i] = v;
                },
                [&](uint32_t i) { return poolWords[i]; }, fence),
            "POOL uses body-before-state publication and verifies full readback");
    auto hiddenSecondFailure = active;
    hiddenSecondFailure.pool1After = hiddenSecondFailure.pool1Before;
    hiddenSecondFailure.checksum = checksum(hiddenSecondFailure);
    require(!validPoolStatus(hiddenSecondFailure, owned),
            "a native true result cannot hide second-pool reserve failure");
    auto invalid = makePoolStatus(owned, PoolInvalid,
        0x10000000, 0x0ffeb000, 0x10000000, 0x10000000, ReasonPoolDelta);
    require(validPoolStatus(invalid, owned), "INVALID records a nonzero terminal reason");
    require(!validPoolStatus(makePoolStatus(owned, PoolInvalid,
                1, 1, 1, 1, ReasonNone), owned),
            "INVALID without a reason is rejected");
    require(!validPoolStatus(makePoolStatus(owned, PoolInvalid,
                1, 1, 1, 1, 8), owned) &&
            !validPoolStatus(makePoolStatus(owned, PoolInvalid,
                1, 1, 1, 1, UINT64_MAX), owned),
            "INVALID accepts only the reviewed reason domain");

    LeaseState state {};
    require(!state.kiqAllowed() && !state.clientsAllowed(),
            "REQUESTED cannot start KIQ or ordinary clients");
    require(state.publishOwned(owned) && state.kiqAllowed() && !state.clientsAllowed(),
            "OWNED gates early KIQ while clients stay blocked");
    require(!state.publishOwned(owned), "a second native append is rejected");
    require(state.beginPoolInit() && !state.beginPoolInit(),
            "only one native pool initialization epoch is allowed");
    require(state.finishPoolInit(active, reinterpret_cast<void *>(0x1234),
                                 goodFullAddress, goodFullAddress, goodFullAddress),
            "both exact element starts and retained handle verify pool exclusion");
    require(state.phase() == Phase::PoolVerified && !state.clientsAllowed(),
            "verified exclusion does not admit clients before status publication");
    require(state.commitPoolPublication() && state.clientsAllowed(),
            "committed ACTIVE publication admits ordinary clients");
    require(!state.finishPoolInit(active, reinterpret_cast<void *>(0x1234),
                                  goodFullAddress, goodFullAddress, goodFullAddress),
            "ACTIVE cannot be republished or reuse a stale element");

    for (unsigned iteration = 0; iteration < 2000; ++iteration) {
        LeaseState raced {};
        require(raced.publishOwned(owned) && raced.beginPoolInit() &&
                raced.finishPoolInit(active, reinterpret_cast<void *>(0x1234),
                                     goodFullAddress, goodFullAddress,
                                     goodFullAddress),
                "commit/invalidate race fixture reaches POOL_VERIFIED");
        std::atomic<unsigned> ready {0};
        std::thread committer([&] {
            ++ready;
            while (ready.load() != 2) std::this_thread::yield();
            raced.commitPoolPublication();
        });
        std::thread invalidator([&] {
            ++ready;
            while (ready.load() != 2) std::this_thread::yield();
            raced.invalidate();
        });
        committer.join();
        invalidator.join();
        require(raced.phase() == Phase::Invalid && !raced.clientsAllowed(),
                "concurrent invalidation is terminal and cannot reopen ACTIVE");
    }

    LeaseState failed {};
    require(failed.publishOwned(owned) && failed.beginPoolInit(),
            "failure fixture reaches the pool exclusion phase");
    require(!failed.finishPoolInit(hiddenSecondFailure,
                                   reinterpret_cast<void *>(0x1234),
                                   goodFullAddress, goodFullAddress, goodFullAddress),
            "second-pool mismatch fails the wrapper contract");
    require(failed.phase() == Phase::Invalid && !failed.clientsAllowed() &&
            !failed.beginPoolInit(),
            "INVALID is terminal and prevents retry");

    LeaseState wrongAddress {};
    require(wrongAddress.publishOwned(owned) && wrongAddress.beginPoolInit(),
            "wrong-address fixture reaches pool exclusion");
    require(!wrongAddress.finishPoolInit(active, reinterpret_cast<void *>(0x1234),
                                         goodFullAddress, goodFullAddress + 0x1000,
                                         goodFullAddress + 0x1000),
            "equal pool element starts still reject when they miss the requested address");

    LeaseState nativeOrder {};
    require(nativeOrder.publishOwned(owned), "pool ordering fixture starts OWNED");
    unsigned poolSequence = 0, freeReads = 0;
    auto poolResult = establishPools(nativeOrder, 0xf400000000ULL,
        [&] { require(poolSequence++ == 0, "native enable runs first"); return 1u; },
        [&] {
            require(poolSequence == 1 || poolSequence == 3,
                    "pool free bytes are read around reserve");
            const bool before = freeReads++ == 0;
            ++poolSequence;
            return PoolFreeSnapshot {true,
                before ? 0x10000000ULL : 0x0ffeb000ULL,
                before ? 0x10000000ULL : 0x0ffeb000ULL};
        },
        [&](uint64_t address, uint64_t length) {
            require(poolSequence++ == 2 && address == 0xf40b6f0000ULL &&
                    length == LeaseSize,
                    "both-pool reserve follows native init at the full address");
            return NativeReserveEvidence {true, reinterpret_cast<void *>(0x1234),
                                          address, address};
        },
        [&](const PoolStatus &status) {
            require(poolSequence++ == 4 && status.state == PoolActive &&
                    nativeOrder.phase() == Phase::PoolVerified &&
                    !nativeOrder.clientsAllowed(),
                    "ACTIVE publishes after verified exclusion while clients stay blocked");
            return true;
        },
        [&](const PoolStatus &status) {
            require(poolSequence++ == 5 && status.state == PoolActive &&
                    nativeOrder.phase() == Phase::PoolVerified &&
                    !nativeOrder.clientsAllowed(),
                    "durable lifetime authorization precedes client admission");
            return true;
        });
    require(poolResult.active && nativeOrder.clientsAllowed() && poolSequence == 6,
            "native callback ordering admits clients only after both publications");

    LeaseState nativeHiddenFailure {};
    require(nativeHiddenFailure.publishOwned(owned),
            "hidden second-pool fixture starts OWNED");
    unsigned reads = 0;
    auto hidden = establishPools(nativeHiddenFailure, 0xf400000000ULL,
        [] { return 1u; },
        [&] {
            bool before = reads++ == 0;
            return PoolFreeSnapshot {true,
                before ? 0x10000000ULL : 0x0ffeb000ULL, 0x10000000ULL};
        },
        [&](uint64_t address, uint64_t) {
            return NativeReserveEvidence {true, reinterpret_cast<void *>(0x1234),
                                          address, address};
        },
        [](const PoolStatus &status) {
            require(status.state == PoolInvalid && status.reason == ReasonPoolDelta,
                    "hidden second-pool failure publishes terminal INVALID");
            return true;
        },
        [](const PoolStatus &) { return true; });
    require(!hidden.active && hidden.reason == ReasonPoolDelta &&
            nativeHiddenFailure.phase() == Phase::Invalid,
            "native true plus unchanged pool1 remains fail closed");

    LeaseState writebackFailure {};
    require(writebackFailure.publishOwned(owned),
            "writeback failure fixture starts OWNED");
    unsigned writebackPublications = 0;
    auto writeback = establishPools(writebackFailure, 0xf400000000ULL,
        [] { return 1u; },
        [read = 0u]() mutable {
            const bool before = read++ == 0;
            return PoolFreeSnapshot {true,
                before ? 0x10000000ULL : 0x0ffeb000ULL,
                before ? 0x10000000ULL : 0x0ffeb000ULL};
        },
        [](uint64_t address, uint64_t) {
            return NativeReserveEvidence {true, reinterpret_cast<void *>(0x1234),
                                          address, address};
        },
        [&](const PoolStatus &status) {
            ++writebackPublications;
            require(!writebackFailure.clientsAllowed(),
                    "failed ACTIVE publication never exposes ordinary clients");
            return status.state == PoolInvalid;
        },
        [](const PoolStatus &) { return true; });
    require(!writeback.active && writeback.reason == ReasonWriteback &&
            writebackPublications == 2 &&
            writebackFailure.phase() == Phase::Invalid &&
            !writebackFailure.clientsAllowed(),
            "ACTIVE writeback failure publishes terminal INVALID and fails closed");

    LeaseState lifetimeFailure {};
    require(lifetimeFailure.publishOwned(owned),
            "lifetime failure fixture starts OWNED");
    unsigned lifetimePublications = 0;
    auto lifetimeRejected = establishPools(lifetimeFailure, 0xf400000000ULL,
        [] { return 1u; },
        [read = 0u]() mutable {
            const bool before = read++ == 0;
            return PoolFreeSnapshot {true,
                before ? 0x10000000ULL : 0x0ffeb000ULL,
                before ? 0x10000000ULL : 0x0ffeb000ULL};
        },
        [](uint64_t address, uint64_t) {
            return NativeReserveEvidence {true, reinterpret_cast<void *>(0x1234),
                                          address, address};
        },
        [&](const PoolStatus &) { ++lifetimePublications; return true; },
        [&](const PoolStatus &status) {
            require(status.state == PoolActive &&
                    lifetimeFailure.phase() == Phase::PoolVerified &&
                    !lifetimeFailure.clientsAllowed(),
                    "failed lifetime readback is observed before client admission");
            return false;
        });
    require(!lifetimeRejected.active && lifetimeRejected.reason == ReasonWriteback &&
            lifetimePublications == 2 &&
            lifetimeFailure.phase() == Phase::Invalid &&
            !lifetimeFailure.clientsAllowed(),
            "lifetime publication failure leaves the pool epoch fail closed");

    unsigned duplicateNativeEnable = 0;
    auto duplicatePool = establishPools(nativeOrder, 0xf400000000ULL,
        [&] { ++duplicateNativeEnable; return 1u; },
        [] { return PoolFreeSnapshot {true, 1, 1}; },
        [](uint64_t, uint64_t) { return NativeReserveEvidence {}; },
        [](const PoolStatus &) { return true; },
        [](const PoolStatus &) { return true; });
    require(!duplicatePool.active && duplicatePool.reason == ReasonDuplicateEpoch &&
            duplicateNativeEnable == 0 && nativeOrder.phase() == Phase::Invalid,
            "duplicate pool epoch blocks before a second native initialization");

    LeaseState dirtyFalseState {};
    require(dirtyFalseState.publishOwned(owned), "dirty Boolean fixture starts OWNED");
    unsigned dirtyReserveCalls = 0;
    auto dirtyFalse = establishPools(dirtyFalseState, 0xf400000000ULL,
        [] { return 0xdeadbe00u; },
        [] { return PoolFreeSnapshot {true, 1, 1}; },
        [&](uint64_t, uint64_t) {
            ++dirtyReserveCalls;
            return NativeReserveEvidence {};
        },
        [](const PoolStatus &) { return true; },
        [](const PoolStatus &) { return true; });
    require(!dirtyFalse.active && dirtyFalse.reason == ReasonNativeEnable &&
            dirtyFalse.nativeResult == 0 && dirtyReserveCalls == 0,
            "dirty upper EAX bits cannot turn a false native AL into success");

    std::puts("Recovery lease v2 fixtures passed");
}
