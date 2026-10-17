import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    item=importlib.util.module_from_spec(spec);spec.loader.exec_module(item);return item

smoke=module('refresh',ROOT/'tools/spice-refresh-smoke.py')
token=module('refresh_token',ROOT/'tools/console-token.py')

class SoftwareProducerTests(unittest.TestCase):
    nonce='0344034403440344'
    def pixels(self,sequence,second=None):
        image=bytearray(640*480*4)
        image[64*640*4:160*640*4]=smoke.band(token,self.nonce,sequence,second)
        # Producer uses only grayscale/magenta, so BGRA=RGBA for token pixels.
        return image
    def test_complete_transaction_decodes(self):
        for seq in (0,1,255,256,0xffffffff):
            self.assertEqual(token.decode(self.pixels(seq),640,480,2560,4,self.nonce),seq)
    def test_deliberately_split_generation_is_not_valid(self):
        with self.assertRaisesRegex(ValueError,'torn duplicate tokens'):
            token.decode(self.pixels(42,41),640,480,2560,4,self.nonce)
    def test_wrong_nonce_is_not_a_delivery(self):
        with self.assertRaisesRegex(ValueError,'wrong token identity'):
            token.decode(self.pixels(42),640,480,2560,4,'0000000000000000')

if __name__=='__main__':unittest.main()
