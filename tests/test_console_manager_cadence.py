import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

ROOT=Path(__file__).resolve().parents[1]
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
wrapper=load('manager_cadence',ROOT/'tools/console-manager-cadence.py')
token=load('manager_token',ROOT/'tools/console-token.py')
producer=load('manager_producer',ROOT/'tools/spice-refresh-smoke.py')
NONCE='0344034403440344'

def snapshot(sequence,scale=1):
    width,height=640*scale,480*scale;raw=bytearray(width*height*4)
    data=producer.band(token,NONCE,sequence,width=width,scale=scale)
    offset=64*scale*width*4;raw[offset:offset+len(data)]=data
    return dict(pixels=bytes(raw),width=width,height=height,stride=width*4,channels=4,
                surface_width=width,surface_height=height)

class ManagerObserverSelectionTests(unittest.TestCase):
    def test_default_uses_one_full_snapshot_and_original_scale_fallback(self):
        data=snapshot(23,2);pix=Mock()
        for method,key in [('get_pixels','pixels'),('get_width','width'),('get_height','height'),('get_rowstride','stride'),('get_n_channels','channels')]:
            getattr(pix,method).return_value=data[key]
        display=Mock();display.get_pixbuf.return_value=pix
        self.assertEqual(wrapper.sample_display(display,token,NONCE),dict(sequence=23,scale=2,width=1280,height=960))
        display.get_pixbuf.assert_called_once_with()
    def test_roi_reacquires_each_callback_without_full_snapshot(self):
        display=Mock();display.get_pixbuf.side_effect=AssertionError('full screenshot forbidden in ROI mode')
        roi=Mock();roi.snapshot.side_effect=[snapshot(1),snapshot(2)]
        self.assertEqual(wrapper.sample_display(display,token,NONCE,roi)['sequence'],1)
        self.assertEqual(wrapper.sample_display(display,token,NONCE,roi)['sequence'],2)
        self.assertEqual(roi.snapshot.call_args_list,[((display,1),),((display,1),)])
        display.get_pixbuf.assert_not_called()
    def test_roi_returns_surface_geometry_and_attempts_both_scales(self):
        display=Mock();roi=Mock();data=snapshot(42,2);data.update(surface_width=3840,surface_height=2160)
        roi.snapshot.return_value=data
        self.assertEqual(wrapper.sample_display(display,token,NONCE,roi),dict(sequence=42,scale=2,width=3840,height=2160))
        self.assertEqual([call.args[1] for call in roi.snapshot.call_args_list],[1,2])
        display.get_pixbuf.assert_not_called()
    def test_roi_guard_failure_never_silently_falls_back(self):
        display=Mock();roi=Mock();roi.snapshot.side_effect=ValueError('unsupported primary format or geometry')
        with self.assertRaisesRegex(ValueError,'unsupported primary'):wrapper.sample_display(display,token,NONCE,roi)
        display.get_pixbuf.assert_not_called()
    def test_wrong_nonce_is_rejected_in_roi_mode(self):
        display=Mock();roi=Mock();roi.snapshot.return_value=snapshot(5)
        with self.assertRaisesRegex(ValueError,'wrong token identity'):wrapper.sample_display(display,token,'0000000000000000',roi)
        display.get_pixbuf.assert_not_called()
    def test_extension_loader_rejects_python_file_without_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'observer.py';path.write_text('raise AssertionError("must not run")')
            with self.assertRaisesRegex(ValueError,'native extension file'):wrapper.load_roi_extension(path)

if __name__=='__main__':unittest.main()
