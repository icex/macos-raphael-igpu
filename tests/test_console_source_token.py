import ctypes
import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
s=importlib.util.spec_from_file_location('fixtures',ROOT/'tests/test_console_token.py');fixtures=importlib.util.module_from_spec(s);s.loader.exec_module(fixtures)

class SourceTokenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which('cc'):raise unittest.SkipTest('C compiler unavailable')
        cls.tmp=tempfile.TemporaryDirectory();p=Path(cls.tmp.name)
        (p/'test.c').write_text('''#include "console-source-token.h"
#include <assert.h>
int decode(const unsigned char *p,size_t w,size_t h,size_t stride,const char *nonce,unsigned scale,unsigned *seq){uint8_t n[8];if(!rg_token_nonce(nonce,n))return -1;return rg_token_decode(p,w,h,stride,n,scale,seq);}
int lifecycle(void){RGTokenWindow s={0};s.enabled=s.armed=1;s.armedAt=10;
rg_token_observe(&s,20,RG_T_CRC,0,0);assert(s.waiting==1&&!s.started);
rg_token_observe(&s,69,RG_T_VALID,5,2);assert(s.started&&s.start==69&&s.processed==1);
rg_token_observe(&s,70,RG_T_VALID,5,2);rg_token_observe(&s,71,RG_T_CRC,0,2);
rg_token_observe(&s,72,RG_T_UNAVAILABLE,0,0);rg_token_observe(&s,73,RG_T_VALID,8,2);
rg_token_observe(&s,74,RG_T_VALID,7,2);assert(s.processed==6&&s.valid==3&&s.invalid==3&&s.unique==2&&s.duplicates==1&&s.skipped==2);
rg_token_observe(&s,99,RG_T_VALID,9,2);assert(s.done&&s.processed==6);
RGTokenWindow never={0};never.enabled=never.armed=1;never.armedAt=10;rg_token_poll(&never,70);assert(never.done&&!never.started);
RGTokenWindow off={0};rg_token_observe(&off,100,RG_T_VALID,2,1);assert(!off.started&&!off.processed);
return 1;}
''')
        subprocess.run(['cc','-shared','-fPIC','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-I',str(ROOT/'tools'),str(p/'test.c'),'-o',str(p/'test.so')],check=True)
        cls.lib=ctypes.CDLL(str(p/'test.so'));cls.lib.decode.argtypes=[ctypes.c_void_p,ctypes.c_size_t,ctypes.c_size_t,ctypes.c_size_t,ctypes.c_char_p,ctypes.c_uint,ctypes.POINTER(ctypes.c_uint)]
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def decode(self,image,nonce=fixtures.NONCE,scale=1):
        rgb,w,h,stride,c=image;bgra=bytearray(w*h*4)
        for y in range(h):
            for x in range(w):
                q=rgb[y*stride+x*c:y*stride+x*c+3];off=(y*w+x)*4;bgra[off:off+4]=bytes((q[2],q[1],q[0],255))
        data=(ctypes.c_ubyte*len(bgra)).from_buffer(bgra);seq=ctypes.c_uint()
        result=self.lib.decode(data,w,h,w*4,nonce.encode(),scale,ctypes.byref(seq));return result,seq.value
    def test_native_hidpi_match_existing_python(self):
        for scale in (1,2):
            frame=fixtures.image(scale=scale);self.assertEqual(self.decode(frame,scale=scale),(0,fixtures.mod.decode(*frame,fixtures.NONCE,scale)))
    def test_nonce_crc_duplicate_border_and_cell_failures(self):
        frame=fixtures.image();self.assertEqual(self.decode(frame,'1123456789abcdef')[0],5)
        self.assertEqual(self.decode(fixtures.image(second=8))[0],7)
        data,w,h,stride,c=frame
        data[68*stride+20*3:68*stride+20*3+3]=b'\x00'*3
        self.assertEqual(self.decode(frame)[0],2)
        for mode in ('crc','torn','ambiguous'):
            frame=fixtures.image();data,w,h,stride,c=frame
            if mode=='crc':
                for y in range(136,144):
                    for x in range(24,32):
                        off=y*stride+x*3;data[off:off+3]=bytes(255-v for v in data[off:off+3])
            else:
                off=74*stride+26*3;data[off:off+3]=bytes((128,128,128) if mode=='ambiguous' else (255,255,255))
            self.assertEqual(self.decode(frame)[0],{'crc':6,'torn':4,'ambiguous':3}[mode])
    def test_bad_configuration_and_geometry(self):
        for nonce in ('','0'*15,'0'*17,'g'*16,' 123456789abcdef'):
            self.assertEqual(self.decode(fixtures.image(),nonce)[0],-1)
        seq=ctypes.c_uint();self.assertEqual(self.lib.decode(None,0,0,0,fixtures.NONCE.encode(),1,ctypes.byref(seq)),1)
    def test_wait_window_duplicates_invalid_and_deadline(self):self.assertEqual(self.lib.lifecycle(),1)
