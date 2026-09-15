import pathlib
import subprocess
import tempfile
import unittest

class VcnReleaseSequenceTests(unittest.TestCase):
    def test_actual_sram_hook_order_and_scope(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        source = (root / 'src/RaphaelGPU.cpp').read_text()
        start = source.index('static uint32_t *wrapAddToDpgSram(')
        end = source.index('static uint32_t wrapVcnConfig(', start)
        body = source[start:end].replace('reinterpret_cast<mach_vm_address_t>(__builtin_return_address(0))', 'testCaller')
        program = r'''
#include <cstdint>
#include <cassert>
#include <cstring>
#include "VcnDpgClock.hpp"
using mach_vm_address_t = uintptr_t;
static uintptr_t hwlibsBase=0x100000, testCaller;
static bool vcnDpgEnabled=true, raphaelTargetConfirmed=true;
static uint32_t *append(void *, uint32_t *p, uint32_t bank, uint32_t reg, uint32_t value) {
    assert(bank==1); p[0]=reg; p[1]=value; return p+2;
}
static auto orgAddToDpgSram=append;
#define FunctionCast(fn, org) org
#define RLOG(...) ((void)0)
''' + body + r'''
int main() {
    alignas(8) uint8_t ctx[0x400] = {};
    uintptr_t engine[3] = {0,0,reinterpret_cast<uintptr_t>(ctx)};
    *reinterpret_cast<uint32_t *>(ctx+0x268)=0x30001;
    uint32_t words[16] = {};
    testCaller=hwlibsBase+0x94351;
    auto end=wrapAddToDpgSram(engine,words,1,0x156,0x0ff00200);
    const uint32_t expected[]={0x26c,0x10,0x26b,3,0x4a6,0,0xc6,0,0x156,0x0ff00200};
    assert(end==words+10 && !memcmp(words,expected,sizeof(expected)));
    testCaller=hwlibsBase+0x9436c;
    end=wrapAddToDpgSram(engine,words,1,0x4a6,0x3e0000);
    assert(end==words+2 && words[1]==0);
    testCaller=hwlibsBase+0x94351; raphaelTargetConfirmed=false;
    end=wrapAddToDpgSram(engine,words,1,0x156,0x0ff00200);
    assert(end==words+2 && words[0]==0x156 && words[1]==0x0ff00200);
    raphaelTargetConfirmed=true; testCaller=hwlibsBase+0x9408c;
    end=wrapAddToDpgSram(engine,words,1,0x156,0x1ff00200);
    assert(end==words+2 && words[1]==0x1ff00200);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            cpp = pathlib.Path(directory) / 'release.cpp'
            binary = pathlib.Path(directory) / 'release'
            cpp.write_text(program)
            subprocess.run(['g++', '-std=c++14', '-I', str(root/'src'), str(cpp), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)
