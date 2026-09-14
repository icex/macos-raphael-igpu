import pathlib
import subprocess
import tempfile
import unittest


class VcnPowerNativeTests(unittest.TestCase):
    def test_allowlisted_power_protocol_and_failure_paths(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            binary = pathlib.Path(directory) / 'vcn-power-test'
            subprocess.run(['g++', '-std=c++14', '-Wall', '-Wextra', '-Werror',
                            str(root / 'tests/test_vcn_platform_power.cpp'), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)
