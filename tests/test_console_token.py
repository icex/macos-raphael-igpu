import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('token',Path(__file__).resolve().parents[1]/'tools/console-token.py')
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
NONCE='0123456789abcdef'


def image(sequence=7,second=None,scale=1):
    width=640*scale;height=200*scale;stride=width*3+8
    data=bytearray(stride*height)
    def rect(x,y,w,h,rgb):
        for row in range(y,y+h):
            for col in range(x,x+w):data[row*stride+col*3:row*stride+col*3+3]=bytes(rgb)
    cell=8*scale
    for left,seq in ((16*scale,sequence),(176*scale,sequence if second is None else second)):
        top=64*scale;rect(left,top,18*cell,12*cell,(255,0,255))
        packet=mod.packet(NONCE,seq)
        for bit in range(160):
            value=255 if packet[bit//8]&(1<<(7-bit%8)) else 0
            rect(left+(1+bit%16)*cell,top+(1+bit//16)*cell,cell,cell,(value,)*3)
    return data,width,height,stride,3


class TokenTests(unittest.TestCase):
    def test_valid_native_and_hidpi_with_padded_stride(self):
        for scale in (1,2):self.assertEqual(mod.decode(*image(scale=scale),NONCE,scale),7)
    def test_wrong_nonce_rejected(self):
        with self.assertRaisesRegex(ValueError,'identity'):mod.decode(*image(),'1123456789abcdef')
    def test_two_valid_but_different_tokens_rejected(self):
        with self.assertRaisesRegex(ValueError,'duplicate'):mod.decode(*image(second=8),NONCE)
    def test_torn_cell_rejected(self):
        data,w,h,stride,c=image();off=74*stride+26*3;data[off:off+3]=bytes((255,255,255))
        with self.assertRaisesRegex(ValueError,'torn'):mod.decode(data,w,h,stride,c,NONCE)
    def test_checksum_corruption_rejected(self):
        data,w,h,stride,c=image()
        # Flip one entire sequence bit in first token, preserving cell uniformity.
        x=16+8;y=64+9*8
        for row in range(y,y+8):
            for col in range(x,x+8):
                off=row*stride+col*3;data[off:off+3]=bytes(255-v for v in data[off:off+3])
        with self.assertRaisesRegex(ValueError,'checksum'):mod.decode(data,w,h,stride,c,NONCE)
    def test_tracker_counts_duplicates_gaps_and_rejects_backwards(self):
        tracker=mod.SequenceTracker()
        self.assertEqual(tracker.observe(2),dict(unique=True,skipped=0))
        self.assertEqual(tracker.observe(2),dict(unique=False,skipped=0))
        self.assertEqual(tracker.observe(5),dict(unique=True,skipped=2))
        with self.assertRaisesRegex(ValueError,'out-of-order'):tracker.observe(4)
        self.assertEqual(tracker.last,5)
