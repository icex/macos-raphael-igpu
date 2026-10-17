"""Execute the real SDMA correction body with injected register read failures."""
import pathlib
import subprocess
import tempfile
import unittest


class SdmaConfigReadbackTests(unittest.TestCase):
    def test_inaccessible_registers_never_generate_configuration_writes(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        source = (root / 'src/RaphaelGPU.cpp').read_text()
        start = source.index('static void applySdmaAddrConfig(const char *when, bool quiet) {')
        end = source.index('\nstatic uint64_t hwInfoField(', start)
        program = r'''
#include <cstdint>
#include <cassert>
#include <initializer_list>
static uint32_t sdmaAddrConfigMode = 2;
static void *asicInfo = reinterpret_cast<void *>(1);
static constexpr unsigned kGcGbAddrConfig=0, kSdmaGbAddrConfig=1, kSdmaGbAddrConfigRead=2;
static constexpr uint32_t kGbAddrConfigFields=0x0c1807ff;
static uint32_t regs[3];
static unsigned writes;
static uint32_t fbRead(void *, unsigned index) { return regs[index]; }
static void fbWrite(void *, unsigned index, uint32_t value) { ++writes; regs[index]=value; }
#define RLOG(...) ((void)0)
'''
        program += source[start:end]
        program += r'''
int main() {
    for (unsigned index=0; index<3; ++index) {
        for (uint32_t missing : {0xffffffffu, 0xdeadbeefu}) {
            regs[0]=0x42; regs[1]=regs[2]=0x444; regs[index]=missing; writes=0;
            applySdmaAddrConfig("fault", true);
            assert(writes == 0);
        }
    }
    regs[0]=0; regs[1]=regs[2]=0x444; writes=0;
    applySdmaAddrConfig("zero source", true); assert(writes == 0);
    regs[0]=0x42; regs[1]=regs[2]=0x80000444; writes=0;
    applySdmaAddrConfig("valid", true);
    assert(writes == 2 && regs[1] == 0x80000042 && regs[2] == 0x80000042);
    writes=0; applySdmaAddrConfig("repeat", true); assert(writes == 0);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            cpp = pathlib.Path(directory) / 'sdma.cpp'
            cpp.write_text(program)
            binary = pathlib.Path(directory) / 'sdma'
            subprocess.run(['g++', '-std=c++14', str(cpp), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)
