"""Execute the production aggregation policy with bounded and overflow cases."""
import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]

class ConsoleTimingTests(unittest.TestCase):
    def test_production_policy(self):
        compiler = shutil.which('c++')
        if not compiler:
            self.skipTest('C++ compiler unavailable')
        source = r'''
#include "ConsoleTiming.hpp"
#include <cassert>
#include <cstdio>
int main() {
    char row[512];
    const unsigned long long max = UINT64_MAX;
    int length = snprintf(row, sizeof(row), CONSOLE_TIMING_LINE1,
                          128u, max, 3840u, 2160u, max, 1u,
                          max, max, max, max, max, max);
    assert(length > 0 && length <= 239);
    length = snprintf(row, sizeof(row), CONSOLE_TIMING_LINE2,
                      128u, max, 3840u, 2160u, max, 1u,
                      max, max, max, max, max);
    assert(length > 0 && length <= 239);
    ConsoleTiming t;
    const uint64_t a[5] = {1, 2, 3, 4, 5};
    assert(!t.record(0, 1440, 900, a));
    assert(!t.record(1, 1440, 900, a));
    assert(t.buckets[0].count == 2 && t.buckets[0].total[4] == 10);
    assert(t.buckets[0].maximum[4] == 5);
    assert(!t.record(2, 3840, 2160, a));
    assert(t.buckets[1].count == 1);
    for (unsigned i = 2; i < 8; ++i) assert(!t.record(3, 640+i, 480, a));
    assert(!t.record(4, 999, 777, a));
    assert(t.dropped == 1);
    assert(!t.record(ConsoleTiming::period-1, 1440, 900, a));
    assert(t.record(ConsoleTiming::period, 1440, 900, a));
    t.clearWindow(ConsoleTiming::period);
    assert(t.reports == 1 && t.dropped == 0 && !t.buckets[0].count);
    assert(!t.record(ConsoleTiming::period+1, 999, 777, a));
    assert(t.buckets[0].width == 999);
    t.buckets[0].count = UINT64_MAX;
    t.buckets[0].total[4] = UINT64_MAX-2;
    assert(!t.record(ConsoleTiming::period+2, 999, 777, a));
    assert(t.saturated && t.buckets[0].count == UINT64_MAX);
    assert(t.buckets[0].total[4] == UINT64_MAX);
    t.clearWindow(2*ConsoleTiming::period);
    assert(!t.saturated);
    // Lifetime cap: no more collection/logging after exactly 128 reports.
    while (t.reports < ConsoleTiming::reportLimit) {
        const auto next = t.started + ConsoleTiming::period;
        assert(t.record(next, 640, 480, a));
        t.clearWindow(next);
    }
    assert(!t.record(UINT64_MAX, 640, 480, a));
    assert(!t.buckets[0].count && t.reports == 128);
    // Out-of-order timestamps do not prematurely open a reporting window.
    ConsoleTiming backwards;
    assert(!backwards.record(100, 640, 480, a));
    assert(!backwards.record(99, 640, 480, a));
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp)
            (path/'test.cpp').write_text(source)
            subprocess.run([compiler, '-std=c++11', '-Wall', '-Wextra', '-Werror',
                            '-I', str(ROOT/'src'), str(path/'test.cpp'), '-o', str(path/'test')], check=True)
            subprocess.run([str(path/'test')], check=True, timeout=5)
