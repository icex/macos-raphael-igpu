import pathlib
import subprocess
import tempfile
import unittest

class VcnSramReadbackTests(unittest.TestCase):
    def test_read_only_controls_last_writer_and_full_prevalidation(self):
        root=pathlib.Path(__file__).resolve().parents[1]
        program=r'''
#include "VcnDpgReadback.hpp"
#include <cassert>
using RaphaelVcnDpg::readback;
int main() {
    unsigned controls=0, reads=0, reports=0; uint32_t selected=0;
    auto write=[&](uint32_t value){ assert((value&0xffff)==0); selected=value; ++controls; };
    auto read=[&](){++reads; return selected==0x00d60000 ? 0x0ff00200u : 0xdeadbeefu;};
    auto report=[&](uint32_t reg,uint32_t expected,uint32_t observed){
        ++reports;
        if(reg==0xd6) assert(expected==0x0ff00200 && observed==expected);
        else assert(reg==0xc004 && expected==0x105 && observed==0xdeadbeef);
    };
    uint32_t image[]={0xd6,0x1ff00200,0xc004,0x105,0xd6,0x0ff00200};
    assert(readback(image,sizeof(image),write,read,report));
    assert(controls==3 && reads==2 && reports==2 && selected==0);
    controls=reads=reports=0;
    image[4]=0x10000;
    assert(!readback(image,sizeof(image),write,read,report));
    assert(!readback(image,7,write,read,report));
    assert(!readback(image,520,write,read,report));
    assert(!readback(nullptr,8,write,read,report));
    assert(controls==0 && reads==0 && reports==0);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            cpp=pathlib.Path(directory)/'readback.cpp'; binary=pathlib.Path(directory)/'readback'
            cpp.write_text(program)
            subprocess.run(['g++','-std=c++14','-Wall','-Wextra','-Werror','-I',str(root/'src'),str(cpp),'-o',str(binary)],check=True)
            subprocess.run([str(binary)],check=True)
