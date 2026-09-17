from pathlib import Path
import importlib.util
import tempfile
import unittest


ROOT=Path(__file__).resolve().parents[1]


class VncCaptureTests(unittest.TestCase):
    def test_worker_uses_python_api_and_stdin_secret(self):
        source=(ROOT/'tools/vnc-frame-capture.py').read_text()
        self.assertIn("api.connect('127.0.0.1::5900', password.decode('utf-8'), timeout=5)",source)
        self.assertIn('sys.stdin.buffer.read',source)
        self.assertIn('client.captureScreen',source)
        self.assertIn("target.open('xb')",source)
        self.assertIn("image.size != (1280,720)",source)
        self.assertNotIn('vncdotool command',source)
        self.assertNotIn('password = sys.argv',source)

    def test_small_colored_icon_cannot_satisfy_dominant_stimulus(self):
        spec=importlib.util.spec_from_file_location('vnc_capture',ROOT/'tools/vnc-frame-capture.py')
        tool=importlib.util.module_from_spec(spec); spec.loader.exec_module(tool)
        from PIL import Image
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'frame.png'; image=Image.new('RGB',(1280,720),(0,0,0))
            for x in range(32):
                for y in range(32): image.putpixel((x,y),(255,0,0))
            image.save(path)
            self.assertFalse(tool._dominant(path,(255,0,0)))
            for color in ((255,0,0), (0,255,255)):
                with self.subTest(color=color):
                    image.paste(color, (320,180,960,540))
                    image.save(path)
                    self.assertTrue(tool._dominant(path,color))
                    self.assertFalse(tool._dominant(path,(0,255,0)))


if __name__ == '__main__': unittest.main()
