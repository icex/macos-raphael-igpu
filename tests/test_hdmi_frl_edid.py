import pathlib
import subprocess
import tempfile
import unittest


class HdmiFrlEdidTests(unittest.TestCase):
    def test_advertised_rate_and_malformed_edids(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            binary = pathlib.Path(directory) / 'hdmi-frl-test'
            subprocess.run(['g++', '-std=c++14', '-Wall', '-Wextra', '-Werror',
                            str(root / 'tests/test_hdmi_frl_edid.cpp'), '-o', str(binary)],
                           check=True)
            subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    unittest.main()
