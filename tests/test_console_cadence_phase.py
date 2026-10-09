"""Portable checks for mixed workload arguments, phase boundaries and ramp."""
import ctypes
import math
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
class Phase(ctypes.Structure):
    _fields_=[('index',ctypes.c_uint),('full',ctypes.c_int)]+[(n,ctypes.c_double) for n in ('start','end','low','high','angle')]

class MixedPhaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc=shutil.which('cc')
        if not cc:raise unittest.SkipTest('C compiler unavailable')
        cls.tmp=tempfile.TemporaryDirectory();root=Path(cls.tmp.name)
        (root/'phase.c').write_text('#include "console_cadence_phase.h"\nint mode(const char*s){return rgpu_source_mode(s);}\nint phase(double e,double d,RGPUMixedPhase*out){return rgpu_mixed_phase(e,d,out);}\n')
        subprocess.run([cc,'-std=c11','-Wall','-Wextra','-Werror','-shared','-fPIC','-I',str(ROOT/'tests'),str(root/'phase.c'),'-lm','-o',str(root/'phase.so')],check=True,capture_output=True)
        cls.lib=ctypes.CDLL(str(root/'phase.so'));cls.lib.phase.argtypes=[ctypes.c_double,ctypes.c_double,ctypes.POINTER(Phase)];cls.lib.phase.restype=ctypes.c_int
        cls.lib.mode.argtypes=[ctypes.c_char_p];cls.lib.mode.restype=ctypes.c_int
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def phase(self,elapsed,duration=110):
        value=Phase();self.assertEqual(self.lib.phase(elapsed,duration,ctypes.byref(value)),1);return value
    def test_only_explicit_supported_mode_names(self):
        for text,expected in [(b'baseline',1),(b'prerendered',2),(b'mixed',3),(b'',0),(b'MIXED',0),(b'mixed extra',0),(None,0)]:
            self.assertEqual(self.lib.mode(text),expected)
    def test_exact_twenty_second_boundaries_and_truncated_end(self):
        for elapsed,index,full in [(0,0,0),(19.999,0,0),(20,1,1),(39.999,1,1),(40,2,0),(60,3,1),(80,4,0),(100,5,1),(109.999,5,1)]:
            p=self.phase(elapsed);self.assertEqual((p.index,p.full,p.start,p.end),(index,full,index*20,min((index+1)*20,110)))
        self.assertEqual(self.phase(119.999,120).end,120)
    def test_low_contrast_smooth_endpoints(self):
        previous=None
        for step in range(2400):
            p=self.phase(step/20.0,120)
            self.assertGreaterEqual(p.low,.085-1e-12);self.assertLessEqual(p.high,.155+1e-12)
            self.assertGreaterEqual(p.angle,0);self.assertLess(p.angle,360)
            if not p.full:self.assertEqual((p.low,p.high,p.angle),(.12,.12,0))
            if previous:
                self.assertLess(abs(p.low-previous.low),.0003)
                self.assertLess(abs(p.high-previous.high),.0003)
            previous=p
        for time in (20,40,60,80,100):
            p=self.phase(time,120);self.assertAlmostEqual(p.low,.12);self.assertAlmostEqual(p.high,.12)
    def test_nonfinite_expired_and_out_of_range_refuse(self):
        value=Phase()
        for elapsed,duration in [(math.nan,110),(math.inf,110),(-1,110),(110,110),(120,120),(0,0),(0,121),(0,math.nan),(0,math.inf)]:
            self.assertEqual(self.lib.phase(elapsed,duration,ctypes.byref(value)),0)
        self.assertEqual(self.lib.phase(0,110,None),0)

if __name__=='__main__':unittest.main()
