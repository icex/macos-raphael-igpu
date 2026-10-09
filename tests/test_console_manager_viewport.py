import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('viewport',Path(__file__).resolve().parents[1]/'tools/console-manager-cadence.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class Clock:
    now=0.
    def __call__(self):return self.now
class Window:
    def __init__(self):self.requests=[]
    def get_size(self):return (1300,800)
    def resize(self,*size):self.requests.append(size)
class Display:
    def __init__(self):
        self.window=Window();self.width=1000;self.height=600;self.scale=2;self.request=None
        self.properties={'scaling':True,'resize-guest':False,'monitor-id':0}
    def get_toplevel(self):return self.window
    def set_size_request(self,*size):self.request=size
    def get_allocated_width(self):return self.width
    def get_allocated_height(self):return self.height
    def get_scale_factor(self):return self.scale
    def get_property(self,key):return self.properties[key]

class ViewportTests(unittest.TestCase):
    def test_delta_resize_and_stable_exact_logical_allocation(self):
        clock=Clock();d=Display();v=m.ViewportControl(d,(1280,720),clock)
        self.assertEqual(d.request,(1280,720));self.assertFalse(v.check())
        self.assertEqual(d.window.requests,[(1580,920)])
        d.width=1280;d.height=720;clock.now=.1
        self.assertFalse(v.check());clock.now=.36;self.assertTrue(v.check())
        self.assertEqual(v.metadata['gdk_scale'],2)
        self.assertFalse(v.metadata['resize_guest'])
    def test_refuses_ignored_window_resize_bounded(self):
        clock=Clock();d=Display();v=m.ViewportControl(d,(1280,720),clock)
        for i in range(10):clock.now=i*.5;self.assertFalse(v.check())
        self.assertEqual(len(d.window.requests),4)
        clock.now=5
        with self.assertRaisesRegex(RuntimeError,'5 seconds'):v.check()
    def test_geometry_or_scale_change_after_settle_refused(self):
        for field,value in [('width',1279),('scale',1)]:
            with self.subTest(field=field):
                clock=Clock();d=Display();d.width=1280;d.height=720
                v=m.ViewportControl(d,(1280,720),clock);v.check();clock.now=.3;v.check()
                setattr(d,field,value)
                with self.assertRaisesRegex(RuntimeError,'changed'):v.check()
    def test_unstable_match_does_not_accumulate_settle_time(self):
        clock=Clock();d=Display();d.width=1280;d.height=720
        v=m.ViewportControl(d,(1280,720),clock);v.check()
        clock.now=.2;d.width=1279;v.check()
        clock.now=.3;d.width=1280;self.assertFalse(v.check())
        clock.now=.51;self.assertFalse(v.check())
        clock.now=.56;self.assertTrue(v.check())
    def test_draw_duration_and_unfinished_accounting(self):
        clock=Clock();t=m.DrawTiming(clock)
        self.assertFalse(t.begin());clock.now=.05;self.assertFalse(t.end())
        self.assertEqual(t.summary()['completed'],1);self.assertEqual(t.summary()['total_seconds'],.05)
        t.begin();self.assertTrue(t.summary()['in_progress'])
        self.assertEqual(t.summary()['completed'],1)

if __name__=='__main__':unittest.main()
