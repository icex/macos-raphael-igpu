"""Execute the holder's portable wire parser, without a display or socket."""
import ctypes
import pathlib
import shutil
import struct
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]

class Geometry(ctypes.Structure):
    _fields_ = [('w', ctypes.c_uint32), ('h', ctypes.c_uint32)]

class Modes(ctypes.Structure):
    _fields_ = [('items', Geometry * 8), ('count', ctypes.c_uint)]

class Protocol(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('cc')
        if not compiler:
            raise unittest.SkipTest('C compiler unavailable')
        cls.tmp = tempfile.TemporaryDirectory()
        source = pathlib.Path(cls.tmp.name) / 'probe.c'
        source.write_text('#include "console-display-control.h"\n'
                          'int settle(double*s,int identity,int ready,int expired,double now){return rg_settle(s,identity,ready,expired,now); }\n'
                          'unsigned check(const unsigned char*p,size_t n){return rg_validate(p,n);}\n'
                          'void encode(unsigned char*p,unsigned v){rg_write32(p,v);}\n'
                          'int insert(RGModes*m,unsigned w,unsigned h,unsigned cw,unsigned ch){return rg_insert(m,(RGGeometry){w,h},(RGGeometry){cw,ch});}\n'
                          'void touch(RGModes*m,unsigned w,unsigned h){rg_touch(m,(RGGeometry){w,h});}\n')
        library = pathlib.Path(cls.tmp.name) / 'probe.so'
        subprocess.run([compiler, '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror',
                        '-I', str(ROOT / 'tools'), str(source), '-o', str(library)], check=True)
        cls.lib = ctypes.CDLL(str(library))
        cls.lib.settle.argtypes = [ctypes.POINTER(ctypes.c_double), ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_double]
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

    def test_lru_keeps_current_across_many_resizes(self):
        modes = Modes()
        for i in range(40):
            self.assertEqual(self.lib.insert(ctypes.byref(modes), 1000 + 2*i, 800, 1000, 800), 1)
            self.assertLessEqual(modes.count, 8)
            entries = [(g.w, g.h) for g in modes.items[:modes.count]]
            self.assertIn((1000, 800), entries)
            self.assertEqual(entries[-1], (1000 + 2*i, 800))
        self.assertEqual([g.w for g in modes.items], [1000, 1066, 1068, 1070, 1072, 1074, 1076, 1078])

    def test_revisit_promotes_without_growth(self):
        modes = Modes()
        for i in range(8):
            self.lib.insert(ctypes.byref(modes), 1000 + 2*i, 800, 0, 0)
        self.lib.touch(ctypes.byref(modes), 1000, 800)
        self.lib.insert(ctypes.byref(modes), 1200, 800, 0, 0)
        self.assertEqual(modes.count, 8)
        self.assertNotIn(1002, [g.w for g in modes.items])
        self.assertIn(1000, [g.w for g in modes.items])
        self.lib.insert(ctypes.byref(modes), 1000, 800, 0, 0)
        self.assertEqual(modes.count, 8)
        self.assertEqual(modes.items[7].w, 1000)

    def test_candidate_does_not_change_committed_policy(self):
        modes = Modes()
        self.lib.insert(ctypes.byref(modes), 2468, 1484, 0, 0)
        original = bytes(modes)
        candidate = Modes.from_buffer_copy(original)
        self.lib.insert(ctypes.byref(candidate), 2500, 1500, 2468, 1484)
        self.assertEqual(bytes(modes), original)
        candidate.count = 9
        before = bytes(candidate)
        self.assertEqual(self.lib.insert(ctypes.byref(candidate), 2600, 1600, 0, 0), 0)
        self.assertEqual(bytes(candidate), before)

    def test_settle_transient_readiness_and_exact_deadline(self):
        since = ctypes.c_double(-1)
        def sample(now, ready=True, identity=True, expired=False):
            return self.lib.settle(ctypes.byref(since), identity, ready, expired, now)
        self.assertEqual(sample(0), 0)
        self.assertEqual(sample(.1), 0)
        self.assertEqual(sample(.15, ready=False), 0)
        self.assertEqual(sample(2.1), 0)
        self.assertEqual(sample(2.29), 0)
        self.assertEqual(sample(2.31), 1)
        self.assertEqual(sample(2.4, identity=False), -1)
        self.assertEqual(sample(2.5), 0)
        self.assertEqual(sample(2.8, expired=True), -1)

    def test_settle_never_accepts_persistent_foreign_placement(self):
        since = ctypes.c_double(-1)
        for index in range(450):
            self.assertEqual(self.lib.settle(ctypes.byref(since), 1, 0, 0, index / 100), 0)
        self.assertEqual(self.lib.settle(ctypes.byref(since), 1, 0, 1, 4.5), -1)

    def test_reply_integer_encoding(self):
        for value in [0, 1, 0x52475044, 0x80000001, 0xffffffff]:
            buffer = ctypes.create_string_buffer(4)
            self.lib.encode(buffer, value)
            self.assertEqual(buffer.raw, struct.pack('<I', value))
