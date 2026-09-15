import pathlib
import subprocess
import tempfile
import unittest

class VcnPspSramTests(unittest.TestCase):
    def test_native_ownership_guards_preserve_context(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        text = (root/'src/RaphaelGPU.cpp').read_text()
        start = text.index('static uint32_t wrapVcnHwInit(')
        end = text.index('// gvm_sw_init', start)
        body = text[start:end].replace('>(hwlibsBase + 0x8673a);', '>(reinterpret_cast<uintptr_t>(fakeAllocate));')
        program = r'''
#include <cstdint>
#include <cassert>
#include <cstring>
static bool vcnApuEnabled=false, vcnSharedSizeReady=true, vcnDpgEnabled=true, raphaelTargetConfirmed=false;
static bool raphaelGcSeen=true, marker=true;
static bool hasUniqueRaphaelPciMarker() { return marker; }
static uint8_t image[0x95000];
static uintptr_t hwlibsBase=reinterpret_cast<uintptr_t>(image);
static uint32_t nativeInit(void *,void *,void *) { return 0; }
static auto orgVcnHwInit=nativeInit;
static uint8_t sram[512];
#define RLOG(...) ((void)0)
#define FunctionCast(fn, org) org
''' + body + r'''
int main() {
    for(unsigned scenario=0; scenario<9; ++scenario) {
        alignas(8) uint8_t ctx[0x500]={}; uint32_t firmware=0x49c5;
        uintptr_t engine[]={0,0,reinterpret_cast<uintptr_t>(ctx)};
        *reinterpret_cast<uint32_t *>(ctx+0x268)=scenario==8 ? 0x30000 : 0x30001;
        *reinterpret_cast<uint32_t *>(ctx+0x2e0)=scenario==4 ? 1 : 0;
        *reinterpret_cast<uint64_t *>(ctx+0x3f8)=hwlibsBase+(scenario==5 ? 0x93ec1 : 0x943cf);
        *reinterpret_cast<uint64_t *>(ctx+0x320)=scenario==2 ? 256 : 512;
        *reinterpret_cast<uint32_t *>(ctx+0x328)=256;
        *reinterpret_cast<uint32_t *>(ctx+0x338)=2;
        *reinterpret_cast<uint64_t *>(ctx+0x330)=0x100000;
        *reinterpret_cast<void **>(ctx+0x340)=scenario==1 ? nullptr : sram;
        *reinterpret_cast<uint64_t *>(ctx+0x348)=0x1234;
        if(scenario==6) *reinterpret_cast<uint32_t *>(ctx)=0x20;
        if(scenario==7) *reinterpret_cast<void **>(ctx+0x2d0)=&firmware;
        marker=scenario!=3;
        uint8_t before[sizeof(ctx)]; memcpy(before,ctx,sizeof(ctx));
        auto r=wrapVcnHwInit(engine,nullptr,nullptr);
        assert(r==(scenario==0 ? 0u : 1u));
        // Wrapper must neither allocate nor corrupt native release metadata,
        // including on all refused ownership/identity branches.
        assert(memcmp(ctx,before,sizeof(ctx))==0);
    }
}
'''
        with tempfile.TemporaryDirectory() as directory:
            cpp=pathlib.Path(directory)/'sram.cpp'; binary=pathlib.Path(directory)/'sram'
            cpp.write_text(program)
            subprocess.run(['g++','-std=c++14',str(cpp),'-o',str(binary)],check=True)
            subprocess.run([str(binary)],check=True)
