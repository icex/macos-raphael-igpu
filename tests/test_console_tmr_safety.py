import pathlib
import subprocess
import tempfile
import unittest

class ConsoleTmrSafetyTests(unittest.TestCase):
    def test_missing_ownership_running_firmware_and_read_faults_never_call_psp(self):
        source=pathlib.Path(__file__).with_suffix('.cpp')
        with tempfile.TemporaryDirectory() as tmp:
            binary=pathlib.Path(tmp)/'test'
            subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror',str(source),'-o',str(binary)],check=True)
            subprocess.run([str(binary)],check=True)
