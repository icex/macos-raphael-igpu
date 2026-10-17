import shutil
import importlib.util
import json
import hashlib
import subprocess
import tempfile
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
class FramebufferPolicyTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('c++'),'C++ compiler unavailable')
    def test_actual_mode_capacity_and_fractional_vbl_schedule(self):
        source=r'''
#include "ConsoleFramebufferPolicy.hpp"
#include <assert.h>
int main(){using namespace RaphaelFB;
assert(count==10);
for(size_t i=0;i<8;i++)assert(fits(modes[i],64ULL<<20,32ULL<<20));
for(size_t i=8;i<10;i++){assert(!fits(modes[i],64ULL<<20,32ULL<<20));assert(fits(modes[i],64ULL<<20,64ULL<<20));assert(!fits(modes[i],32ULL<<20,64ULL<<20));}
assert(!fits({3840,2160,144},64ULL<<20,64ULL<<20));
assert(!fits({UINT32_MAX,UINT32_MAX,120},UINT64_MAX,UINT64_MAX));
for(unsigned hz:{60U,120U}){Cadence c;c.reset(1000,hz);uint64_t now=1000;
for(unsigned i=1;i<=hz*3600;i++){uint64_t next=c.next(now);assert(next>now);assert(next==1000+uint64_t(i)*1000000000ULL/hz);now=next;}
assert(now==1000+3600ULL*1000000000ULL);
uint64_t late=now+123456789;c.next(late);assert(c.tick>hz*3600);uint64_t next=c.next(late);assert(next>late);}
Cadence invalid;assert(!invalid.next(1));invalid.reset(100,120);assert(!invalid.next(99));assert(!invalid.next(UINT64_MAX));
Cadence c;c.reset(0,120);assert(c.next(0)==8333333);assert(c.next(1000000000)==1008333333);assert(c.tick==121);
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'test.cpp').write_text('#include <initializer_list>\n'+source)
            subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-I',str(ROOT/'native-framebuffer'),str(p/'test.cpp'),'-o',str(p/'test')],check=True,capture_output=True)
            subprocess.run([str(p/'test')],check=True,timeout=5)

