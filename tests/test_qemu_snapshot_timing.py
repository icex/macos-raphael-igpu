"""Compile the actual header added by the diagnostic extension patch."""
import pathlib
import shutil
import subprocess
import tempfile
import unittest
ROOT = pathlib.Path(__file__).resolve().parents[1]

class SnapshotTimingTests(unittest.TestCase):
    def test_aggregate_policy(self):
        compiler = shutil.which('cc')
        if not compiler:
            self.skipTest('C compiler unavailable')
        patch = (ROOT/'findings/research/patches/qemu-10.1.2-bochs-snapshot-timing.patch').read_text()
        added = patch.split('+++ b/hw/display/bochs-snapshot-timing.h\n', 1)[1]
        header = '\n'.join(line[1:] for line in added.splitlines() if line.startswith('+'))+'\n'
        source = r'''
#include "bochs-snapshot-timing.h"
#include <assert.h>
int main(void) {
    BochsSnapshotTiming s = {0};
    const uint64_t us[3] = {11, 23, 7};
    assert(!bst_record(&s, 0, 3840, 2160, false, us));
    assert(!bst_record(&s, 1, 3840, 2160, true, us));
    assert(s.buckets[0].count == 2 && s.buckets[0].pending_present == 1);
    assert(s.buckets[0].total[1] == 46 && s.buckets[0].maximum[1] == 23);
    for (unsigned i=1;i<BST_SLOTS;i++) assert(!bst_record(&s, 2, 640+i, 480, false, us));
    assert(!bst_record(&s, 3, 999, 777, true, us));
    assert(s.dropped == 1);
    assert(!bst_record(&s, BST_PERIOD_US-1, 3840, 2160, false, us));
    assert(bst_record(&s, BST_PERIOD_US, 3840, 2160, false, us));
    bst_clear(&s, BST_PERIOD_US);
    assert(s.windows == 1 && !s.dropped && !s.buckets[0].count);
    assert(!bst_record(&s, BST_PERIOD_US+1, 999, 777, true, us));
    s.buckets[0].count=UINT64_MAX;
    s.buckets[0].pending_present=UINT64_MAX;
    s.buckets[0].total[0]=UINT64_MAX-1;
    assert(!bst_record(&s, BST_PERIOD_US+2, 999, 777, true, us));
    assert(s.saturated && s.buckets[0].count==UINT64_MAX);
    assert(s.buckets[0].total[0]==UINT64_MAX);
    bst_clear(&s, 2*BST_PERIOD_US);
    while(s.windows<BST_WINDOWS) {
        uint64_t next=s.started+BST_PERIOD_US;
        assert(bst_record(&s, next, 640, 480, false, us));
        bst_clear(&s, next);
    }
    assert(!bst_record(&s, UINT64_MAX, 640, 480, false, us));
    assert(s.windows==128 && !s.buckets[0].count);
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as temp:
            d = pathlib.Path(temp)
            (d/'bochs-snapshot-timing.h').write_text(header)
            (d/'test.c').write_text(source)
            subprocess.run([compiler, '-std=c11', '-Wall', '-Wextra', '-Werror', str(d/'test.c'), '-o', str(d/'test')], check=True)
            subprocess.run([str(d/'test')], check=True, timeout=5)
