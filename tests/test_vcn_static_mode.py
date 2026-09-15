import pathlib
import subprocess
import tempfile
import unittest

class VcnStaticModeTests(unittest.TestCase):
    def test_production_transition_preserves_other_bits_and_refuses_bad_reads(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        source = (root / 'src/RaphaelGPU.cpp').read_text()
        begin = source.index('    if (vcnStaticEnabled && !vcnDpgEnabled) {')
        # Extract this production block, not the unrelated code that follows it.
        depth = 0
        for end in range(source.index('{', begin), len(source)):
            depth += (source[end] == '{') - (source[end] == '}')
            if depth == 0:
                end += 1
                break
        else:
            self.fail('unterminated static-mode block')
        body = source[begin:end].replace('reinterpret_cast<uint32_t (*)(void *, uint32_t, uint32_t)>(hwlibsBase + 0x86834)', 'fakeRead')
        program = r'''
#include <cstdint>
#include <cstring>
#include <cassert>
#define RLOG(...) ((void)0)
#define FunctionCast(a,b) fakeWrite
bool vcnStaticEnabled=true, vcnDpgEnabled=false, raphaelTargetConfirmed=true;
bool orgVcnWriteRegister=true, orgVcnConfig=true;
uintptr_t hwlibsBase=0x100000;
uint32_t power=0x804, writes=0, last=0; bool sticks=true;
uint32_t fakeRead(void*,uint32_t bank,uint32_t reg) { assert(bank==1 && reg==4); return power; }
void fakeWrite(void*,uint32_t bank,uint32_t reg,uint32_t value) { assert(bank==1 && reg==4); last=value; ++writes; if(sticks)power=value; }
int transition(const uint8_t* ctx) {void* engine=nullptr;
''' + body + r'''
return 0;}
int main() {
 alignas(8) uint8_t ctx[0x440]={};
 *reinterpret_cast<uint32_t*>(ctx+0x268)=0x30001;
 *reinterpret_cast<uint64_t*>(ctx+0x3f8)=hwlibsBase+0x930f8;
 assert(transition(ctx)==0 && power==0x800 && writes==1 && last==0x800);
 writes=0; assert(transition(ctx)==0 && writes==0);
 for(auto invalid : {0xffffffffu,0xdeadbeefu,0x80000804u}) {
  power=invalid; assert(transition(ctx)==1 && writes==0);
 }
 power=0x804; sticks=false; assert(transition(ctx)==1 && writes==1);
 writes=0; raphaelTargetConfirmed=false; assert(transition(ctx)==1 && writes==0);
 raphaelTargetConfirmed=true; *reinterpret_cast<uint32_t*>(ctx)=2;
 assert(transition(ctx)==1 && writes==0);
 return 0;
}
'''
        program = '#include <initializer_list>\n' + program
        with tempfile.TemporaryDirectory() as directory:
            cpp=pathlib.Path(directory)/'test.cpp'; binary=pathlib.Path(directory)/'test'
            cpp.write_text(program)
            subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror',str(cpp),'-o',str(binary)],check=True)
            subprocess.run([str(binary)],check=True)
