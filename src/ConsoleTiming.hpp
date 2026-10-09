// Bounded diagnostic aggregation only. Caller serializes access; units are ns.
#pragma once
#include <stdint.h>
struct ConsoleTiming {
    static constexpr unsigned slots = 8, stages = 5, reportLimit = 128;
    static constexpr uint64_t period = 5000000000ULL;
    struct Bucket {
        uint32_t width = 0, height = 0;
        uint64_t count = 0, total[stages] = {}, maximum[stages] = {};
    } buckets[slots];
    uint64_t started = 0, dropped = 0;
    unsigned reports = 0;
    bool saturated = false, begun = false;
    void add(uint64_t &target, uint64_t value) {
        if (UINT64_MAX - target < value) { target = UINT64_MAX; saturated = true; }
        else target += value;
    }
    // Returns true when caller must report this window then clearWindow(now).
    bool record(uint64_t now, uint32_t w, uint32_t h, const uint64_t (&ns)[stages]) {
        if (reports >= reportLimit) return false;
        if (!begun) { started = now; begun = true; }
        Bucket *bucket = nullptr;
        for (auto &b : buckets) {
            if (!b.count || (b.width == w && b.height == h)) { bucket = &b; break; }
        }
        if (!bucket) add(dropped, 1);
        else {
            bucket->width = w; bucket->height = h; add(bucket->count, 1);
            for (unsigned i = 0; i < stages; ++i) {
                add(bucket->total[i], ns[i]);
                if (ns[i] > bucket->maximum[i]) bucket->maximum[i] = ns[i];
            }
        }
        return now >= started && now - started >= period;
    }
    void clearWindow(uint64_t now) {
        for (auto &b : buckets) b = Bucket{};
        dropped = 0; saturated = false; started = now; begun = true;
        if (reports < reportLimit) ++reports;
    }
};
