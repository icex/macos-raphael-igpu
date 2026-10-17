"""Compile the exact SPICE patch policy and check its opt-in boundary."""
import ctypes
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

PATCH=Path(__file__).resolve().parents[1]/'findings/research/patches/spice-0.16.0-unix-lossless-opt-in.patch'

class UnixLosslessPolicy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc=shutil.which('c++')
        if not cc or not Path('/usr/include/spice-1/spice/enums.h').exists():
            raise unittest.SkipTest('C++ compiler and protocol headers required')
        text=PATCH.read_text().split('+++ b/server/rgpu-unix-lossless.h\n',1)[1]
        header='\n'.join(line[1:] for line in text.splitlines() if line.startswith('+'))+'\n'
        cls.temp=tempfile.TemporaryDirectory();p=Path(cls.temp.name)
        (p/'rgpu-unix-lossless.h').write_text(header)
        (p/'test.cpp').write_text('''#include "rgpu-unix-lossless.h"
extern "C" int policy(int family,int codec,const char *opt) {
 return rgpu_unix_compression_allowed(family,static_cast<SpiceImageCompression>(codec),opt);
}
extern "C" int unix_family() { return AF_UNIX; }
extern "C" int tcp_family() { return AF_INET; }
extern "C" int lz4_codec() { return SPICE_IMAGE_COMPRESSION_LZ4; }
''')
        subprocess.run([cc,'-std=c++11','-O2','-Wall','-Wextra','-Werror','-I/usr/include/spice-1','-shared','-fPIC',str(p/'test.cpp'),'-o',str(p/'test.so')],check=True,capture_output=True)
        cls.lib=ctypes.CDLL(str(p/'test.so'));cls.fn=cls.lib.policy
        cls.fn.argtypes=[ctypes.c_int,ctypes.c_int,ctypes.c_char_p];cls.fn.restype=ctypes.c_int

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_existing_unix_default_and_other_codecs_preserved(self):
        family=self.lib.unix_family();lz4=self.lib.lz4_codec()
        for codec in range(9):
            for opt in (None,b'',b'0',b'yes',b'01',b'10',b'1 ',b'true'):
                self.assertEqual(self.fn(family,codec,opt),0)
            self.assertEqual(self.fn(family,codec,b'1'),int(codec==lz4))

    def test_tcp_behavior_unchanged(self):
        for codec in range(9):
            for opt in (None,b'',b'0',b'1',b'yes'):
                self.assertEqual(self.fn(self.lib.tcp_family(),codec,opt),1)

if __name__=='__main__':unittest.main()
