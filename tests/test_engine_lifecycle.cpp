#include <cstdio>
#include <cstdlib>
#include <vector>
#include "../src/EngineLifecycle.hpp"

static void require(bool condition, const char *message) {
    if (!condition) {
        std::fprintf(stderr, "FAIL: %s\n", message);
        std::exit(1);
    }
}

int main() {
    int first = 1, third = 3;
    require(!RaphaelLifecycle::customPowerUpReady(true, &first, false),
            "custom power-up requires its cleanup route");
    require(!RaphaelLifecycle::customPowerUpReady(false, &first, true),
            "disabled tracing uses the native power-up path");
    require(!RaphaelLifecycle::customPowerUpReady(true, nullptr, true),
            "null hardware uses the native power-up path");
    require(RaphaelLifecycle::customPowerUpReady(true, &first, true),
            "custom power-up is admitted only with hardware and cleanup");
    void *engines[] {&first, nullptr, &third};
    std::vector<unsigned> visited;
    unsigned cleanupCount = 0;
    size_t failed = 99;

    bool ok = RaphaelLifecycle::powerUpAll(
        engines, 3,
        [&](void *, size_t index) {
            visited.push_back(static_cast<unsigned>(index));
            return index != 2;
        },
        [&] { cleanupCount++; }, failed);
    require(!ok, "failed engine must fail the sequence");
    require((visited == std::vector<unsigned>{0, 2}), "null engines are skipped in order");
    require(failed == 2, "failed engine index is preserved");
    require(cleanupCount == 1, "partial power-up is cleaned exactly once");

    visited.clear(); cleanupCount = 0; failed = 99;
    ok = RaphaelLifecycle::powerUpAll(
        engines, 3,
        [&](void *, size_t index) { visited.push_back(static_cast<unsigned>(index)); return true; },
        [&] { cleanupCount++; }, failed);
    require(ok, "all successful engines complete the sequence");
    require((visited == std::vector<unsigned>{0, 2}), "successful sequence visits every engine");
    require(failed == 3, "successful sequence has no failed engine");
    require(cleanupCount == 0, "successful power-up is not torn down");
    std::puts("engine lifecycle fixtures passed");
}
