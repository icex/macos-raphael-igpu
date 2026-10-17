import importlib.util, socket, tempfile, time, unittest
from pathlib import Path
from PIL import Image

class QemuFrameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path=Path(__file__).parents[1]/'tools/qemu-frame-capture.py'
        spec=importlib.util.spec_from_file_location('qemu_capture',path)
        cls.tool=importlib.util.module_from_spec(spec); spec.loader.exec_module(cls.tool)
    def test_dominant_center_requires_geometry_and_large_roi(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'frame.ppm'; Image.new('RGB',(1280,720),(0,0,0)).save(path)
            image=Image.open(path); pixels=image.load()
            for y in range(180,540):
                for x in range(320,760): pixels[x,y]=(250,5,4)
            image.save(path)
            self.assertFalse(self.tool.dominant(path,(255,0,0),(1280,720)))
            for y in range(180,540):
                for x in range(320,960): pixels[x,y]=(250,5,4)
            image.save(path)
            self.assertTrue(self.tool.dominant(path,(255,0,0),(1280,720)))
            self.assertFalse(self.tool.dominant(path,(255,0,0),(1024,768)))
    def test_static_both_colors_does_not_form_ordered_dominance(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'frame.ppm'; image=Image.new('RGB',(1280,720),(0,0,0)); p=image.load()
            for y in range(180,540):
                for x in range(320,640): p[x,y]=(255,0,0)
                for x in range(640,960): p[x,y]=(0,255,255)
            image.save(path)
            self.assertFalse(self.tool.dominant(path,(255,0,0),(1280,720)))
            self.assertFalse(self.tool.dominant(path,(0,255,255),(1280,720)))
    def test_receive_rejects_eof_and_absolute_deadline(self):
        left,right=socket.socketpair()
        right.close()
        with self.assertRaisesRegex(RuntimeError,'disconnected'):
            self.tool.receive_until(left,b'(qemu)',time.time()+1)
        left.close()
        left,right=socket.socketpair()
        try:
            with self.assertRaises(TimeoutError):
                self.tool.receive_until(left,b'(qemu)',time.time()-1)
        finally: left.close(); right.close()
if __name__=='__main__': unittest.main()
