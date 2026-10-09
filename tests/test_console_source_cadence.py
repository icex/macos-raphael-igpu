import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
s=importlib.util.spec_from_file_location('token',ROOT/'tools/console-token.py');token=importlib.util.module_from_spec(s);s.loader.exec_module(token)

class SourceBandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which('cc'):raise unittest.SkipTest('C compiler unavailable')
        cls.tmp=tempfile.TemporaryDirectory();root=Path(cls.tmp.name)
        source=root/'encode.c';source.write_text('#include <stdio.h>\n#include "console_cadence_band.h"\nint main(void){uint8_t p[RGPU_BAND_BYTES],n[]={1,35,69,103,137,171,205,239};rgpu_band(p,n,12345);return fwrite(p,1,sizeof(p),stdout)!=sizeof(p);}\n')
        cls.binary=root/'encode'
        subprocess.run(['cc','-Wall','-Wextra','-Werror','-I',str(ROOT/'tests'),str(source),'-o',str(cls.binary)],check=True)
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def pixels(self,scale):
        band=subprocess.check_output([str(self.binary)]);self.assertEqual(len(band),38*12*4)
        w,h=640*scale,200*scale;image=bytearray(w*h*4)
        for y in range(96*scale):
            row=b''.join(band[(y//(8*scale)*38+x//(8*scale))*4:][:4] for x in range(304*scale))
            offset=((64*scale+y)*w+16*scale)*4;image[offset:offset+len(row)]=row
        return image,w,h,w*4,4
    def test_c_band_decodes_same_nonce_crc_geometry_native_hidpi(self):
        for scale in (1,2):self.assertEqual(token.decode(*self.pixels(scale),'0123456789abcdef',scale),12345)
    def test_wrong_nonce_and_corrupted_duplicate_refuse(self):
        args=self.pixels(1)
        with self.assertRaisesRegex(ValueError,'identity'):token.decode(*args,'1123456789abcdef')
        data,w,h,stride,c=args
        for y in range(72,80):
            for x in range(184,192):
                off=y*stride+x*4;data[off:off+3]=bytes(255-b for b in data[off:off+3])
        with self.assertRaises(ValueError):token.decode(data,w,h,stride,c,'0123456789abcdef')
