import pathlib
import subprocess
import tempfile
import unittest


class WritebackDisplayTests(unittest.TestCase):
    def test_control_page_aperture_and_publication(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            binary = pathlib.Path(directory) / 'writeback-display-test'
            subprocess.run(['g++', '-std=c++14', '-Wall', '-Wextra', '-Werror',
                            str(root / 'tests/test_writeback_display.cpp'), '-o', str(binary)],
                           check=True)
            subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    unittest.main()
