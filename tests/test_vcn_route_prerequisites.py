"""Run the actual initialization preflight with injected missing routes."""
import pathlib
import subprocess
import tempfile
import unittest

class VcnRoutePrerequisiteTests(unittest.TestCase):
    def test_missing_sram_or_config_route_refuses_before_native_execution(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        source = (root / 'src/RaphaelGPU.cpp').read_text()
        start = source.index('static uint32_t wrapVcnInitialize(void *engine) {')
        end = source.index('    auto ctx =', start)
        program = r'''
#include <cstdint>
#include <cassert>
static bool vcnDpgEnabled, vcnResetEnabled;
static uintptr_t orgVcnConfig, orgAddToDpgSram, orgVcnWriteRegister;
static unsigned nativeCalls;
#define RLOG(...) ((void)0)
''' + source[start:end] + '++nativeCalls; return 0; }\n'
        program += r'''
int main() {
    vcnDpgEnabled=true;
    for (unsigned routes=0; routes<4; ++routes) {
        orgVcnConfig=routes&1; orgAddToDpgSram=routes&2; nativeCalls=0;
        assert(wrapVcnInitialize(nullptr) == (routes==3 ? 0u : 1u));
        assert(nativeCalls == (routes==3 ? 1u : 0u));
    }
    vcnResetEnabled=true; orgVcnWriteRegister=0; nativeCalls=0;
    assert(wrapVcnInitialize(nullptr)==1 && nativeCalls==0);
    vcnResetEnabled=false; vcnDpgEnabled=false;
    orgVcnConfig=orgAddToDpgSram=0;
    assert(wrapVcnInitialize(nullptr)==0 && nativeCalls==1);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            cpp = pathlib.Path(directory) / 'routes.cpp'
            binary = pathlib.Path(directory) / 'routes'
            cpp.write_text(program)
            subprocess.run(['g++', '-std=c++14', str(cpp), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)
