import pathlib
import subprocess
import tempfile
import unittest


class HostMemoryReservationTests(unittest.TestCase):
    def test_host_window_bounds_and_native_reservation(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            binary = pathlib.Path(directory) / 'host-memory-test'
            subprocess.run(['g++', '-std=c++14', '-Wall', '-Wextra', '-Werror',
                            str(root / 'tests/test_host_memory_reservation.cpp'), '-o', str(binary)],
                           check=True)
            subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    unittest.main()
