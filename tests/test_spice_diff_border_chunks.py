"""Compare the actual optimized QEMU helper with a pixel-by-pixel oracle."""
import ctypes
import random
import unittest
import test_spice_changed_bbox as baseline


class ChunkedBBox(baseline.ChangedBBox):
    EXTRA_PATCHES = (baseline.ROOT / 'findings/research/patches/qemu-10.1.2-spice-diff-border-chunks.patch',)

    def test_exact_oracle_unaligned_independent_strides_and_dirty_bounds(self):
        rng = random.Random(437)
        for trial in range(500):
            w, h = rng.randrange(1, 160), rng.randrange(1, 12)
            ss, ms = w * 4 + rng.randrange(17), w * 4 + rng.randrange(17)
            so, mo = rng.randrange(1, 8), rng.randrange(1, 8)
            source = bytearray([0xA5] * (so + ss * h + 64))
            mirror = bytearray([0x5A] * (mo + ms * h + 64))
            for y in range(h):
                pixels = rng.randbytes(w * 4)
                source[so+y*ss:so+y*ss+w*4] = pixels
                mirror[mo+y*ms:mo+y*ms+w*4] = pixels
            for _ in range(rng.randrange(25)):
                x, y, c = rng.randrange(w), rng.randrange(h), rng.randrange(4)
                source[so+y*ss+x*4+c] ^= 1
            l, t = rng.randrange(w), rng.randrange(h)
            r, b = rng.randrange(l+1, w+1), rng.randrange(t+1, h+1)
            changed = [(x, y) for y in range(t, b) for x in range(l, r)
                       if source[so+y*ss+x*4:so+y*ss+x*4+4] !=
                       mirror[mo+y*ms+x*4:mo+y*ms+x*4+4]]
            source_before, mirror_before = bytes(source), bytes(mirror)
            sa = (ctypes.c_ubyte * len(source)).from_buffer(source)
            ma = (ctypes.c_ubyte * len(mirror)).from_buffer(mirror)
            out = baseline.Rect()
            result = self.fn(ctypes.byref(sa, so), ss*h, ss,
                             ctypes.byref(ma, mo), ms*h, ms, w, h,
                             baseline.Rect(l, t, r, b), ctypes.byref(out))
            self.assertEqual(result, int(bool(changed)), trial)
            if changed:
                expected = (min(x for x,y in changed), min(y for x,y in changed),
                            max(x for x,y in changed)+1, max(y for x,y in changed)+1)
                self.assertEqual((out.left,out.top,out.right,out.bottom), expected, trial)
            self.assertEqual(bytes(source), source_before)
            self.assertEqual(bytes(mirror), mirror_before)

    def test_chunk_edges_and_full_width_last_byte(self):
        for w in (15,16,17,31,32,33,63,64,65,3840):
            mirror = bytes(w*4)
            for x in {0,w-1,w//2,max(0,w-16),min(16,w-1)}:
                source = bytearray(mirror)
                source[x*4+3] = 1
                self.assertEqual(self.call(source,mirror,w,1),(1,(x,0,x+1,1)))

if __name__ == '__main__':
    unittest.main()
