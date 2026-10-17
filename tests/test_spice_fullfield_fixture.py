import base64
import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
def load(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
fixture=load('fullfield_fixture',ROOT/'tools/spice-refresh-smoke.py')
token=load('fullfield_token',ROOT/'tools/console-token.py')

class CompactFixtureTests(unittest.TestCase):
    def test_compact_rows_preserve_two_tokens_and_outside_background(self):
        nonce='0344034403440344';base=0xd0000000
        for width,height,scale in [(640,480,1),(3840,2160,2)]:
            with self.subTest(scale=scale):
                pixels=bytearray([31])*(width*height*4)
                raw=fixture.band(token,nonce,729,width=width,scale=scale)
                commands=fixture.compact_band_commands(raw,base,width,scale)
                for command in commands:
                    op,address,length,payload=command.split()
                    self.assertEqual(op,'b64write')
                    off=int(address,0)-base;data=base64.b64decode(payload,validate=True)
                    self.assertEqual(len(data),int(length,0))
                    self.assertGreaterEqual(off,0);self.assertLessEqual(off+len(data),len(pixels))
                    pixels[off:off+len(data)]=data
                self.assertEqual(token.decode(pixels,width,height,width*4,4,nonce,scale),729)
                self.assertEqual(pixels[:4],bytes([31])*4)
                self.assertEqual(pixels[-4:],bytes([31])*4)
                self.assertEqual(pixels[64*scale*width*4:64*scale*width*4+4],bytes([31])*4)
    def test_malformed_band_refused_before_transfer(self):
        with self.assertRaisesRegex(ValueError,'geometry'):
            fixture.compact_band_commands(b'bad',0xd0000000,640,1)
