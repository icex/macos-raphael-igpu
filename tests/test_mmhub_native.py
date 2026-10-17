import pathlib
import subprocess
import tempfile
import unittest


class MmhubNativeTests(unittest.TestCase):
    def test_captured_addresses_and_transaction_guards(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            binary = pathlib.Path(directory) / 'mmhub-test'
            subprocess.run(['g++', '-std=c++14', '-Wall', '-Wextra', '-Werror',
                            str(root / 'tests/test_mmhub_registers.cpp'), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)
