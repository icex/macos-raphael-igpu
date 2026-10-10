"""Compile the exact new header embedded in the experimental QEMU patch."""
import ctypes
import pathlib
import random
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PATCH = ROOT/'findings/research/patches/qemu-10.1.2-spice-changed-single-bbox-research.patch'

class Rect(ctypes.Structure):
    _fields_ = [(key, ctypes.c_int) for key in ('left', 'top', 'right', 'bottom')]

class ChangedBBox(unittest.TestCase):
    EXTRA_PATCHES = ()
    @classmethod
    def setUpClass(cls):
        cc = shutil.which('cc')
        if not cc: raise unittest.SkipTest('C compiler unavailable')
        text = PATCH.read_text().split('+++ b/ui/spice-diff-bbox.h\n', 1)[1]
        header = '\n'.join(line[1:] for line in text.splitlines() if line.startswith('+'))+'\n'
        cls.temp = tempfile.TemporaryDirectory()
        root = pathlib.Path(cls.temp.name)
        (root/'ui').mkdir()
        (root/'ui'/'spice-diff-bbox.h').write_text(header)
        for extra in cls.EXTRA_PATCHES:
            subprocess.run(['patch', '-p1', '-i', str(extra)], cwd=root, check=True, capture_output=True)
        (root/'spice-diff-bbox.h').write_text((root/'ui'/'spice-diff-bbox.h').read_text())
        (root/'test.c').write_text('''#include "spice-diff-bbox.h"
int test_bbox(const uint8_t *s, size_t n, size_t stride,
 const uint8_t *m, size_t mn, size_t ms, int w, int h,
 RGPUDiffRect d, RGPUDiffRect *out) {
 return rgpu_diff_bbox(s,n,stride,m,mn,ms,w,h,d,out);
}
''')
        subprocess.run([cc,'-std=c11','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',str(root/'test.c'),'-o',str(root/'test.so')],check=True,capture_output=True)
        cls.lib=ctypes.CDLL(str(root/'test.so'));cls.fn=cls.lib.test_bbox
        cls.fn.argtypes=[ctypes.c_void_p,ctypes.c_size_t,ctypes.c_size_t,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_size_t,ctypes.c_int,ctypes.c_int,Rect,ctypes.POINTER(Rect)]
        cls.fn.restype=ctypes.c_int

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def call(self, source, mirror, w, h, stride=None, ms=None, dirty=None, n=None, mn=None):
        stride=w*4 if stride is None else stride;ms=stride if ms is None else ms
        s=(ctypes.c_ubyte*len(source)).from_buffer_copy(source)
        m=(ctypes.c_ubyte*len(mirror)).from_buffer_copy(mirror);out=Rect()
        result=self.fn(s,len(source) if n is None else n,stride,m,len(mirror) if mn is None else mn,ms,w,h,dirty or Rect(0,0,w,h),ctypes.byref(out))
        return result,(out.left,out.top,out.right,out.bottom)

    def test_same_pixels_ignore_padding_and_different_strides(self):
        w,h=7,5;s=bytearray((w*4+8)*h);m=bytearray((w*4+16)*h)
        for y in range(h):
            s[y*(w*4+8)+w*4:(y+1)*(w*4+8)]=b'\xaa'*8
            m[y*(w*4+16)+w*4:(y+1)*(w*4+16)]=b'\xbb'*16
        self.assertEqual(self.call(s,m,w,h,w*4+8,w*4+16)[0],0)

    def test_each_corner_channels_and_last_pixel(self):
        w,h=9,6;mirror=bytes(w*h*4)
        for x,y in [(0,0),(w-1,0),(0,h-1),(w-1,h-1),(4,3)]:
            for channel in range(4):
                source=bytearray(mirror);source[(y*w+x)*4+channel]=255
                self.assertEqual(self.call(source,mirror,w,h),(1,(x,y,x+1,y+1)))

    def test_far_regions_return_one_union(self):
        w,h=32,12;m=bytes(w*h*4);s=bytearray(m)
        for x,y in [(2,3),(29,9),(16,5)]:s[(y*w+x)*4]=7
        self.assertEqual(self.call(s,m,w,h),(1,(2,3,30,10)))

    def test_bounds_and_short_storage_reject_before_read(self):
        s=bytes(64);m=bytes(64)
        for kwargs in [dict(stride=15),dict(ms=15),dict(n=63),dict(mn=63),dict(stride=2**63),dict(dirty=Rect(-1,0,4,4)),dict(dirty=Rect(0,0,5,4)),dict(dirty=Rect(0,0,0,4))]:
            self.assertEqual(self.call(s,m,4,4,**kwargs)[0],-1)
        self.assertEqual(self.call(s,m,4096,2160)[0],-1)

    def test_known_dirty_region_and_random_reconstruction(self):
        w,h=37,19;stride=w*4+12;source=bytearray(stride*h);mirror=bytearray(stride*h)
        rng=random.Random(372)
        for frame in range(120):
            changed=[]
            for _ in range(rng.randrange(1,12)):
                x,y=rng.randrange(w),rng.randrange(h);changed.append((x,y))
                source[y*stride+x*4:y*stride+x*4+4]=bytes(rng.randrange(256) for _ in range(4))
            result,box=self.call(source,mirror,w,h,stride)
            self.assertEqual(result,1)
            l,t,r,b=box
            for y in range(t,b):mirror[y*stride+l*4:y*stride+r*4]=source[y*stride+l*4:y*stride+r*4]
            self.assertEqual(source,mirror)
            self.assertEqual(self.call(source,mirror,w,h,stride)[0],0)
        source[3*stride+7*4]=99
        self.assertEqual(self.call(source,mirror,w,h,stride,dirty=Rect(6,2,10,8)),(1,(7,3,8,4)))

if __name__=='__main__':unittest.main()
