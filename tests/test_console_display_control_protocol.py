"""Execute the holder's portable wire parser, without a display or socket."""
import ctypes
import pathlib
import shutil
import struct
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]

class Protocol(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('cc')
        if not compiler:
            raise unittest.SkipTest('C compiler unavailable')
        cls.tmp = tempfile.TemporaryDirectory()
        source = pathlib.Path(cls.tmp.name) / 'probe.c'
        source.write_text('#include "console-display-control.h"\n'
                          'unsigned check(const unsigned char*p,size_t n){return rg_validate(p,n);}\n'
                          'void encode(unsigned char*p,unsigned v){rg_write32(p,v);}\n')
        library = pathlib.Path(cls.tmp.name) / 'probe.so'
        subprocess.run([compiler, '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror',
                        '-I', str(ROOT / 'tools'), str(source), '-o', str(library)], check=True)
        cls.lib = ctypes.CDLL(str(library))
        cls.lib.check.argtypes = [ctypes.c_char_p, ctypes.c_size_t]
        cls.lib.check.restype = ctypes.c_uint
        cls.lib.encode.argtypes = [ctypes.c_void_p, ctypes.c_uint]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def request(self, w=2468, h=1484, magic=0x52475044, version=1, sequence=1):
        return struct.pack('<IIIII', magic, version, sequence, w, h)

    def check(self, data):
        return self.lib.check(data, len(data))

    def test_dynamic_and_boundary_geometry(self):
        for w, h in [(2468, 1484), (640, 480), (3840, 2160), (2560, 1440)]:
            self.assertEqual(self.check(self.request(w, h)), 0)

    def test_reject_odd_outside_and_unsigned_extremes(self):
        for w, h in [(2469, 1484), (2468, 1485), (638, 480), (640, 478),
                     (3842, 2160), (3840, 2162), (0xffffffff, 480), (0, 0)]:
            self.assertEqual(self.check(self.request(w, h)), 2)

    def test_exact_length_and_header(self):
        data = self.request()
        for size in range(20):
            self.assertEqual(self.check(data[:size]), 1)
        self.assertEqual(self.check(data + b'x'), 1)
        for kw in [{'magic': 0}, {'version': 2}, {'sequence': 0}]:
            self.assertEqual(self.check(self.request(**kw)), 1)

    def test_reply_integer_encoding(self):
        for value in [0, 1, 0x52475044, 0x80000001, 0xffffffff]:
            buffer = ctypes.create_string_buffer(4)
            self.lib.encode(buffer, value)
            self.assertEqual(buffer.raw, struct.pack('<I', value))
