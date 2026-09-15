import pathlib
import subprocess
import tempfile
import unittest

class VcnSoftwareSramTests(unittest.TestCase):
    def test_production_allocation_success_failure_and_refusal(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        text = (root/'src/RaphaelGPU.cpp').read_text()
        start = text.index('static uint32_t wrapVcnHwInit(')
        end = text.index('// gvm_sw_init', start)
        body = text[start:end].replace('>(hwlibsBase + 0x8673a);', '>(reinterpret_cast<uintptr_t>(fakeAllocate));')
        program = r'''
#include <cstdint>
#include <cassert>
#include <cstring>
static bool vcnApuEnabled=false, vcnSharedSizeReady=true, vcnDpgEnabled=true, raphaelTargetConfirmed=true;
static uint8_t image[0x95000];
static uintptr_t hwlibsBase=reinterpret_cast<uintptr_t>(image);
static uint32_t nativeInit(void *,void *,void *) { return 0; }
static auto orgVcnHwInit=nativeInit;
static unsigned allocations; static bool fail;
static uint8_t sram[512];
static void *fakeAllocate(void *, uint64_t size, uint32_t align, uint32_t type,
                          uint64_t *gpu, uint64_t *handle, uint32_t cpu) {
    assert(size==512 && align==256 && type==2 && cpu==1); ++allocations;
    if(fail) return nullptr;
    *gpu=0x100000; *handle=0x1234; return sram;
}
#define RLOG(...) ((void)0)
#define FunctionCast(fn, org) org
''' + body + r'''
int main() {
    const uint8_t guard[]={0x55,0x48,0x89,0xe5,0x41,0x57,0x41,0x56,0x53,0x48,0x83,0xec,0x48,0x4c,0x89,0xcb};
    memcpy(image+0x8673a,guard,sizeof(guard));
    for(unsigned scenario=0; scenario<3; ++scenario) {
        alignas(8) uint8_t ctx[0x500]={}; uint32_t firmware=0x49c5;
        uintptr_t engine[]={0,0,reinterpret_cast<uintptr_t>(ctx)};
        *reinterpret_cast<uint32_t *>(ctx+0x268)=0x30001;
        *reinterpret_cast<uint32_t *>(ctx+0x2e0)=1;
        *reinterpret_cast<uint64_t *>(ctx+0x3f8)=hwlibsBase+0x93ec1;
        *reinterpret_cast<uint64_t *>(ctx+0x320)=scenario==2 ? 256 : 512;
        *reinterpret_cast<uint32_t *>(ctx+0x328)=256;
        *reinterpret_cast<uint32_t *>(ctx+0x338)=2;
        *reinterpret_cast<uint64_t *>(ctx+0x2c0)=0x200000;
        *reinterpret_cast<void **>(ctx+0x2d0)=&firmware;
        allocations=0; fail=scenario==1;
        auto r=wrapVcnHwInit(engine,nullptr,nullptr);
        assert(r==(scenario==0 ? 0u : 1u));
        assert(allocations==(scenario==2 ? 0u : 1u));
        assert(*reinterpret_cast<uint64_t *>(ctx+0x3f8)==hwlibsBase+(scenario==0 ? 0x943cf : 0x93ec1));
        assert(*reinterpret_cast<void **>(ctx+0x340)==(scenario==0 ? sram : nullptr));
        if(scenario==0) assert(*reinterpret_cast<uint64_t *>(ctx+0x330)==0x100000 &&
                              *reinterpret_cast<uint64_t *>(ctx+0x348)==0x1234);
    }
}
'''
        with tempfile.TemporaryDirectory() as directory:
            cpp=pathlib.Path(directory)/'sram.cpp'; binary=pathlib.Path(directory)/'sram'
            cpp.write_text(program)
            subprocess.run(['g++','-std=c++14',str(cpp),'-o',str(binary)],check=True)
            subprocess.run([str(binary)],check=True)
