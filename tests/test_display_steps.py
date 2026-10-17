import pathlib
import subprocess
import tempfile
import unittest


class DisplayStepsTests(unittest.TestCase):
    def test_aspect_classes_and_steps(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            binary = pathlib.Path(directory) / 'display-steps-test'
            subprocess.run(['g++', '-std=c++14', '-Wall', '-Wextra', '-Werror',
                            str(root / 'tests/test_display_steps.cpp'), '-o', str(binary)],
                           check=True)
            subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    unittest.main()
