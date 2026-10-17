"""Compile the actual skipped-tick helper and compare with a replay-free oracle."""
import ctypes
from pathlib import Path
import random
import shutil
import subprocess
import tempfile
import unittest

PATCH=Path(__file__).resolve().parents[1]/'findings/research/patches/qemu-10.1.2-spice60-start-pacing.patch'

class StartPacing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc=shutil.which('cc')
        if not cc:raise unittest.SkipTest('C compiler required')
        text=PATCH.read_text().split('+++ b/ui/gui-start-pacing.h\n',1)[1]
        header='\n'.join(line[1:] for line in text.splitlines() if line.startswith('+'))+'\n'
        cls.temp=tempfile.TemporaryDirectory();p=Path(cls.temp.name)
        (p/'gui-start-pacing.h').write_text(header)
        (p/'test.c').write_text('#include "gui-start-pacing.h"\nint64_t tick(int64_t start,int64_t now,uint64_t period){return rgpu_gui_next_tick(start,now,period);}\n')
        subprocess.run([cc,'-std=c11','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',str(p/'test.c'),'-o',str(p/'test.so')],check=True,capture_output=True)
        cls.lib=ctypes.CDLL(str(p/'test.so'));cls.fn=cls.lib.tick
        cls.fn.argtypes=[ctypes.c_int64,ctypes.c_int64,ctypes.c_uint64];cls.fn.restype=ctypes.c_int64

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_short_work_exact_boundary_overrun_and_multiple_misses(self):
        for start,now,period,expected in [(100,103,17,117),(100,117,17,134),(100,135,17,151),(100,169,17,185),(100,110,5,115),(200,180,17,197)]:
            self.assertEqual(self.fn(start,now,period),expected)

    def test_random_next_future_phase_aligned_deadline(self):
        rng=random.Random(440)
        for _ in range(1000):
            start=rng.randrange(1000000);period=rng.randrange(1,1000);now=start+rng.randrange(5000)
            expected=start+period
            while expected<=now:expected+=period
            actual=self.fn(start,now,period)
            self.assertEqual(actual,expected)
            self.assertGreater(actual,now)
            self.assertLessEqual(actual-now,period)

    def test_invalid_period_and_overflow_saturate(self):
        maximum=2**63-1
        for start,now,period in [(1,2,0),(1,2,2**63),(maximum-3,maximum-2,17),(maximum-1,maximum,1),(0,-1,17)]:
            self.assertEqual(self.fn(start,now,period),maximum)

if __name__=='__main__':unittest.main()
