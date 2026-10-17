// Publication before copy, slot reuse, or silent truncation must fail these tests.
#include "../src/DiagnosticRecords.hpp"
#include <cassert>
#include <atomic>
#include <cstdio>
#include <cstring>
#include <thread>
#include <vector>

int main() {
    rgpu::SuccessRecordBudget budget {};
    unsigned successfulRecords = 0;
    for (unsigned i = 0; i < 100; ++i)
        successfulRecords += budget.take(true, 4) ? 1 : 0;
    assert(successfulRecords == 4);
    for (unsigned i = 0; i < 100; ++i)
        assert(budget.take(false, 4));

    // Sustained process creation must leave critical space for failures/recovery.
    // The two COW families each keep four successes; later errors stay visible.
    static rgpu::DiagnosticRecords<rgpu::kCriticalRecordCapacity, 32> lifetime;
    rgpu::SuccessRecordBudget metalCow, videoCow;
    for (unsigned i=0;i<400;i++) lifetime.append("startup-and-required-evidence");
    for (unsigned i=0;i<1000;i++) {
        if (metalCow.take(true,4)) lifetime.append("metal-cow-ok");
        if (videoCow.take(true,4)) lifetime.append("video-cow-ok");
    }
    assert(metalCow.take(false,4) && videoCow.take(false,4));
    lifetime.append("metal-cow-failed"); lifetime.append("video-cow-failed");
    lifetime.append("shutdown"); lifetime.append("owned"); lifetime.append("valid-lifetime");
    assert(lifetime.size()==413 && lifetime.dropped()==0 && lifetime.truncated()==0);
    char last[32]; assert(lifetime.read(412,last));
    assert(std::strcmp(last,"valid-lifetime")==0);

    // A repaired VMID can progress through more than 128 clean KIQ submissions.
    // Retain a bounded clean prefix without ever suppressing the later fault.
    rgpu::SuccessRecordBudget preClearFaultBudget {};
    unsigned cleanPreClearRecords = 0;
    for (unsigned i = 0; i < 160; ++i) {
        const uint32_t status = 0;
        cleanPreClearRecords += preClearFaultBudget.take(
            status == 0, rgpu::kRoutinePreClearRecordLimit) ? 1 : 0;
    }
    const uint32_t faultStatus = 0xdead;
    assert(cleanPreClearRecords == 8 &&
           preClearFaultBudget.take(
               faultStatus == 0, rgpu::kRoutinePreClearRecordLimit));

    // The finite first-fault estimate is 199 records; the production capacity
    // leaves room for all of them rather than dropping everything after 128.
    static rgpu::DiagnosticRecords<rgpu::kCriticalRecordCapacity, 8>
        boundedCriticalBurst {};
    for (unsigned i = 0; i < 199; ++i) boundedCriticalBurst.append("record");
    assert(boundedCriticalBurst.size() == 199 && boundedCriticalBurst.dropped() == 0);

    rgpu::DiagnosticRecords<2, 8> small {};
    char out[8];
    assert(!small.read(0, out));
    small.append("abcdefghijk");
    small.append("two");
    small.append("overflow");
    assert(small.read(0, out) && std::strcmp(out, "abcdefg") == 0);
    assert(small.read(1, out) && std::strcmp(out, "two") == 0);
    assert(!small.read(2, out));
    assert(small.dropped() == 1 && small.truncated() == 1);

    static rgpu::DiagnosticRecords<4000, 64> records {};
    std::atomic<unsigned> done {0};
    std::vector<std::thread> producers;
    for (unsigned p = 0; p < 4; ++p) producers.emplace_back([&, p] {
        for (unsigned i = 0; i < 1100; ++i) {
            char msg[64];
            std::snprintf(msg, sizeof(msg), "%u:%u:0123456789abcdef:END", p, i);
            records.append(msg);
        }
        ++done;
    });
    unsigned cursor = 0;
    bool seen[4][1100] {};
    while (done != 4 || cursor < records.size()) {
        char msg[64];
        if (!records.read(cursor, msg)) { std::this_thread::yield(); continue; }
        unsigned p, i; char tail[40];
        assert(std::sscanf(msg, "%u:%u:%39s", &p, &i, tail) == 3);
        assert(p < 4 && i < 1100 && !seen[p][i]);
        assert(std::strcmp(tail, "0123456789abcdef:END") == 0);
        seen[p][i] = true;
        // A reader cannot destroy records, even while other producers append.
        char again[64];
        assert(records.read(cursor, again) && std::strcmp(msg, again) == 0);
        ++cursor;
        if (cursor % 31 == 0) std::this_thread::yield();
    }
    for (auto &p : producers) p.join();
    assert(cursor == 4000 && records.dropped() == 400 && records.truncated() == 0);
}
