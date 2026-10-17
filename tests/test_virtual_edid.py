import pathlib
import subprocess
import tempfile
import unittest


class VirtualEdidTests(unittest.TestCase):
    def test_cvt_rb2_dtd_and_displayid_blocks(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            binary = pathlib.Path(directory) / 'virtual-edid-test'
            subprocess.run(['g++', '-std=c++14', '-Wall', '-Wextra', '-Werror',
                            str(root / 'tests/test_virtual_edid.cpp'), '-o', str(binary)],
                           check=True)
            subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    unittest.main()
