from pathlib import Path
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
class RelativeBranchTests(unittest.TestCase):
    def test_current_addresses_condition_and_signed_range(self):
        with tempfile.TemporaryDirectory() as directory:
            binary=Path(directory)/'branch'
            subprocess.run(['c++','-std=c++14','-Wall','-Wextra','-Werror','-I',str(ROOT/'src'),str(ROOT/'tests/relative_branch.cpp'),'-o',str(binary)],check=True)
            subprocess.run([str(binary)],check=True)
