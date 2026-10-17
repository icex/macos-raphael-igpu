#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <thread>
#include <vector>

#include "../src/BackingTrace.hpp"

static void require(bool condition, const char *message) {
    if (!condition) {
        std::fprintf(stderr, "FAIL: %s\n", message);
        std::exit(1);
    }
}

template <typename T>
static void put(unsigned char *object, size_t offset, T value) {
    std::memcpy(object + offset, &value, sizeof(value));
}

int main() {
    using RaphaelBacking::Observation;
    using RaphaelBacking::Snapshot;

    const auto unavailable = RaphaelBacking::captureSnapshot(nullptr);
    require(!unavailable.available,
            "a null backing object produces an explicitly unavailable snapshot");

    alignas(8) unsigned char backing[0x150] {};
    put<uint64_t>(backing, 0x40, 0x200000ull);
    put<uintptr_t>(backing, 0x110, 0x1122334455667788ull);
    put<uint64_t>(backing, 0x118, 0xaabbccdd00112233ull);
    put<uint64_t>(backing, 0x120, 0x4000ull);
    put<uint32_t>(backing, 0x128, 0x81u);
    const auto captured = RaphaelBacking::captureSnapshot(backing);
    require(captured.available && captured.length == 0x200000ull &&
                captured.owner == 0x1122334455667788ull &&
                captured.element == 0xaabbccdd00112233ull &&
                captured.raw120 == 0x4000ull && captured.flags == 0x81u,
            "the exact proven backing fields are copied without reinterpretation");

    RaphaelBacking::Store<4> inactiveStore;
    unsigned nativeCalls = 0;
    unsigned snapshotCalls = 0;
    const bool inactiveResult = RaphaelBacking::observe(
        false, backing, 0x7777, 1, inactiveStore,
        [&](void *) {
            ++nativeCalls;
            return false;
        },
        [&](const void *) {
            ++snapshotCalls;
            return Snapshot {};
        });
    require(!inactiveResult && nativeCalls == 1 && snapshotCalls == 0 &&
                inactiveStore.successful() == 0 && inactiveStore.failed() == 0,
            "inactive observation delegates exactly once without reading fields");

    RaphaelBacking::Store<4> activeStore;
    nativeCalls = 0;
    const bool activeResult = RaphaelBacking::observe(
        true, backing, 0x8888, 9, activeStore,
        [&](void *object) {
            ++nativeCalls;
            auto bytes = static_cast<unsigned char *>(object);
            put<uint64_t>(bytes, 0x118, 0x12345000ull);
            put<uint32_t>(bytes, 0x128, 0x91u);
            return false;
        },
        [](const void *object) { return RaphaelBacking::captureSnapshot(object); });
    require(!activeResult && nativeCalls == 1 && activeStore.successful() == 0 &&
                activeStore.failed() == 1 && activeStore.completed() == 1,
            "active observation preserves the native result and counts completion once");
    Observation retained {};
    require(activeStore.failures().read(0, retained) && retained.sequence == 9 &&
                retained.backing == reinterpret_cast<uintptr_t>(backing) &&
                retained.threadToken == 0x8888 && !retained.result &&
                retained.before.element == 0xaabbccdd00112233ull &&
                retained.after.element == 0x12345000ull &&
                retained.before.flags == 0x81u && retained.after.flags == 0x91u,
            "the first failure sample retains immutable live pre/post scalar snapshots");
    require(retained.successfulBefore == 0 && retained.failedBefore == 0 &&
                retained.successfulAfter == 0 && retained.failedAfter == 1 &&
                RaphaelBacking::poolIndex(retained.before) == 0,
            "failure sample retains bounded result counters and pool domain");
    retained.before.flags |= 1u << 19;
    require(RaphaelBacking::poolIndex(retained.before) == 1,
            "pool domain extraction follows the exact native selector bit");

    const bool successfulResult = RaphaelBacking::observe(
        true, backing, 0x9999, 10, activeStore,
        [&](void *) {
            ++nativeCalls;
            return true;
        },
        [](const void *object) { return RaphaelBacking::captureSnapshot(object); });
    require(successfulResult && nativeCalls == 2 && activeStore.successful() == 1 &&
                activeStore.failed() == 1 && activeStore.failures().size() == 1,
            "a true native result is preserved and counted without retaining a failure sample");

    RaphaelBacking::Store<4> nullStore;
    const bool nullResult = RaphaelBacking::observe(
        true, nullptr, 0xaaaa, 11, nullStore,
        [](void *) { return false; },
        [](const void *object) { return RaphaelBacking::captureSnapshot(object); });
    Observation nullSample {};
    require(!nullResult && nullStore.failures().read(0, nullSample) &&
                !nullSample.before.available && !nullSample.after.available,
            "an active null object remains a safe explicit unavailable failure sample");

    RaphaelBacking::Store<4> concurrentStore;
    constexpr unsigned ThreadCount = 8;
    constexpr unsigned CallsPerThread = 1000;
    std::atomic<bool> start {false};
    std::atomic<bool> readerSawPublishedSample {false};
    std::atomic<unsigned> activeProducers {ThreadCount};
    std::atomic<bool> coherentPublication {true};
    std::thread reader([&] {
        while (!start.load(std::memory_order_acquire)) std::this_thread::yield();
        while (activeProducers.load(std::memory_order_acquire) != 0) {
            for (size_t index = 0; index < concurrentStore.failures().size(); ++index) {
                Observation sample {};
                if (!concurrentStore.failures().read(index, sample)) continue;
                const uint64_t marker = sample.sequence;
                if (sample.result || !sample.before.available || !sample.after.available ||
                    sample.before.length != marker ||
                    sample.before.element != ~marker ||
                    sample.after.raw120 != marker + 1 ||
                    sample.threadToken != marker % ThreadCount)
                    coherentPublication.store(false, std::memory_order_relaxed);
                readerSawPublishedSample.store(true, std::memory_order_release);
            }
            std::this_thread::yield();
        }
    });
    std::vector<std::thread> threads;
    for (unsigned thread = 0; thread < ThreadCount; ++thread) {
        threads.emplace_back([thread, &concurrentStore, &start,
                              &readerSawPublishedSample, &activeProducers] {
            while (!start.load(std::memory_order_acquire)) std::this_thread::yield();
            const uint64_t firstMarker = thread;
            Snapshot firstBefore {firstMarker, 0, ~firstMarker, 0, 0, true};
            Snapshot firstAfter {0, 0, 0, firstMarker + 1, 0, true};
            concurrentStore.append(Observation {
                0x1000u + thread, thread, false, firstBefore, firstAfter,
                static_cast<uint32_t>(firstMarker)
            });
            while (!readerSawPublishedSample.load(std::memory_order_acquire))
                std::this_thread::yield();
            for (unsigned call = 0; call < CallsPerThread; ++call) {
                const bool result = ((thread + call) & 1u) == 0;
                const uint64_t marker = ThreadCount + thread * CallsPerThread + call;
                Snapshot before {marker, 0, ~marker, 0, 0, true};
                Snapshot after {0, 0, 0, marker + 1, 0, true};
                concurrentStore.append(Observation {
                    0x1000u + thread, marker % ThreadCount, result, before, after,
                    static_cast<uint32_t>(marker)
                });
            }
            activeProducers.fetch_sub(1, std::memory_order_release);
        });
    }
    start.store(true, std::memory_order_release);
    for (auto &thread : threads) thread.join();
    reader.join();
    const uint64_t expectedEach = ThreadCount * CallsPerThread / 2;
    require(concurrentStore.successful() == expectedEach &&
                concurrentStore.failed() == expectedEach + ThreadCount &&
                concurrentStore.completed() == 2 * expectedEach + ThreadCount,
            "independent result counters survive concurrent producers after sample saturation");
    require(concurrentStore.failures().size() == 4 &&
                concurrentStore.failures().dropped() == expectedEach + ThreadCount - 4,
            "failure samples have a hard four-record bound with explicit loss accounting");
    require(readerSawPublishedSample.load() && coherentPublication.load(),
            "a concurrent reader sees only self-consistent release-published samples");
    for (size_t index = 0; index < concurrentStore.failures().size(); ++index) {
        Observation sample {};
        require(concurrentStore.failures().read(index, sample) && !sample.result &&
                    sample.before.available && sample.after.available &&
                    sample.before.length == sample.sequence &&
                    sample.before.element == ~uint64_t(sample.sequence) &&
                    sample.after.raw120 == uint64_t(sample.sequence) + 1,
                "release publication exposes complete immutable samples");
    }

    std::puts("backing trace fixtures passed");
}
