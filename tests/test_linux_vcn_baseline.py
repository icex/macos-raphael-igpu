import importlib.util
from pathlib import Path
import tempfile
import unittest

class LinuxVcnBaselineTests(unittest.TestCase):
    def test_output_content_and_frame_count(self):
        spec=importlib.util.spec_from_file_location('baseline',Path(__file__).resolve().parents[1]/'tools/linux_vcn_baseline.py')
        m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'output.nv12'
            data=b''.join(y.tobytes()+bytes([128])*(1280*720//2) for y in m.pattern())
            p.write_bytes(data);self.assertTrue(m.validate(p)['passed'])
            p.write_bytes(data[:-1]);self.assertFalse(m.validate(p)['passed'])
            bad=bytearray(data);bad[100*1280+100]=255
            p.write_bytes(bad);self.assertFalse(m.validate(p)['passed'])
