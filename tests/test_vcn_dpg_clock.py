import pathlib
import subprocess
import tempfile
import unittest


class VcnDpgClockTests(unittest.TestCase):
    def test_native_secure_clock_sequence_and_scope(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        program = r'''
#include "VcnDpgClock.hpp"
#include <cassert>
using RaphaelVcnDpg::clockGateValue;
int main() {
    // Native +94026/+9403e call sites pass the SAME value to CTRL/GATE.
    // The expected sequence follows native unsecure +93d8e and Linux VCN3.
    for (unsigned control : {0x104u, 0x105u}) {
        assert(clockGateValue(true, false, 0x30001, 1, 0x8a, control) == control);
        assert(clockGateValue(true, true, 0x30001, 1, 0x88, control) == 0);
        assert(clockGateValue(true, false, 0x30001, 1, 0x8c, 1) == 1);
        assert(clockGateValue(true, false, 0x30001, 1, 0x8e, 0) == 0);
        assert(clockGateValue(false, true, 0x30001, 1, 0x88, control) == control);
        assert(clockGateValue(true, false, 0x30001, 1, 0x88, control) == control);
        assert(clockGateValue(true, true, 0x30000, 1, 0x88, control) == control);
        assert(clockGateValue(true, true, 0x30001, 0, 0x88, control) == control);
    }
    for (unsigned value : {0u, 1u, 0xffffffffu, 0x1ff00200u, 0xff00200u}) {
        assert(clockGateValue(true, true, 0x30001, 1, 0x88, value) == value);
        assert(clockGateValue(true, true, 0x30001, 1, 0x156, value) == value);
    }
}
'''
        with tempfile.TemporaryDirectory() as directory:
            source = pathlib.Path(directory) / 'clock.cpp'
            source.write_text('#include <initializer_list>\n' + program)
            binary = pathlib.Path(directory) / 'clock'
            subprocess.run(['g++', '-std=c++14', '-Wall', '-Wextra', '-Werror',
                            '-I', str(root / 'src'), str(source), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)
