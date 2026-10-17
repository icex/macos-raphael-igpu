"""Compile the actual client-request gate, independent of image environment."""
import ctypes
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

PATCH=Path(__file__).resolve().parents[1]/'findings/research/patches/spice-0.16.0-unix-lossless-client-opt-in.patch'

class ClientLosslessPolicy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc=shutil.which('c++')
        if not cc or not Path('/usr/include/spice-1/spice/enums.h').exists():
            raise unittest.SkipTest('C++ and protocol headers required')
        text=PATCH.read_text().split('+++ b/server/rgpu-unix-lossless-client.h\n',1)[1]
        header='\n'.join(line[1:] for line in text.splitlines() if line.startswith('+'))+'\n'
        cls.temp=tempfile.TemporaryDirectory();p=Path(cls.temp.name)
        (p/'rgpu-unix-lossless-client.h').write_text(header)
        (p/'test.cpp').write_text('''#include "rgpu-unix-lossless-client.h"
extern "C" int policy(int family,int codec) {
 return rgpu_unix_client_compression_allowed(family,static_cast<SpiceImageCompression>(codec));
}
extern "C" int unix_family() { return AF_UNIX; }
extern "C" int tcp_family() { return AF_INET; }
extern "C" int lz4_codec() { return SPICE_IMAGE_COMPRESSION_LZ4; }
''')
        subprocess.run([cc,'-std=c++11','-O2','-Wall','-Wextra','-Werror','-I/usr/include/spice-1','-shared','-fPIC',str(p/'test.cpp'),'-o',str(p/'test.so')],check=True,capture_output=True)
        cls.lib=ctypes.CDLL(str(p/'test.so'));cls.fn=cls.lib.policy
        cls.fn.argtypes=[ctypes.c_int,ctypes.c_int];cls.fn.restype=ctypes.c_int

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_unix_only_explicit_lz4(self):
        for codec in range(9):
            self.assertEqual(self.fn(self.lib.unix_family(),codec),int(codec==self.lib.lz4_codec()))

    def test_other_families_unchanged(self):
        for family in (self.lib.tcp_family(),10):
            for codec in range(9):self.assertEqual(self.fn(family,codec),1)

if __name__=='__main__':unittest.main()
