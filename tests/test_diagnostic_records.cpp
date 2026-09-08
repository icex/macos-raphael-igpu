// Publication before copy, slot reuse, or silent truncation must fail these tests.
#include "../src/DiagnosticRecords.hpp"
#include <cassert>
#include <atomic>
#include <cstdio>
#include <cstring>
#include <thread>
#include <vector>

int main() {
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
