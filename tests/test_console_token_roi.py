"""Optional real-extension checks; live buffer equivalence has separate receipts."""
import os
from pathlib import Path
import sys
import threading
import unittest

EXTENSION=os.environ.get('RGPU_ROI_EXTENSION')

@unittest.skipUnless(EXTENSION,'optional local ROI observer extension not built')
class RoiGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0,str(Path(EXTENSION).resolve()))
        import console_token_roi
        cls.roi=console_token_roi
        import gi
        gi.require_version('Gtk','3.0');gi.require_version('SpiceClientGtk','3.0');gi.require_version('SpiceClientGLib','2.0')
        from gi.repository import Gtk,GLib,SpiceClientGtk,SpiceClientGLib
        cls.Gtk=Gtk;cls.GLib=GLib;cls.SpiceClientGtk=SpiceClientGtk;cls.SpiceClientGLib=SpiceClientGLib
        if not Gtk.init_check()[0]:raise unittest.SkipTest('GTK backend unavailable')
    def test_python_pointer_surrogate_is_rejected(self):
        for value in (0,123456,object(),None):
            with self.subTest(value=value),self.assertRaises(TypeError):self.roi.snapshot(value,1)
    def test_unbounded_scale_is_rejected(self):
        for scale in (-1,0,3,1000000):
            with self.subTest(scale=scale),self.assertRaises(ValueError):self.roi.snapshot(None,scale)
    def test_outside_main_loop_refuses_even_real_widget(self):
        session=self.SpiceClientGLib.Session();display=self.SpiceClientGtk.Display.new(session,0)
        try:
            with self.assertRaisesRegex(RuntimeError,'main-loop'):self.roi.snapshot(display,1)
        finally:display.destroy()
    def test_main_loop_with_no_channel_refuses_without_connection(self):
        session=self.SpiceClientGLib.Session();display=self.SpiceClientGtk.Display.new(session,0);observed=[]
        def check():
            try:self.roi.snapshot(display,1)
            except Exception as error:observed.append(error)
            finally:self.Gtk.main_quit()
            return False
        self.GLib.idle_add(check)
        try:self.Gtk.main()
        finally:display.destroy()
        self.assertEqual(len(observed),1);self.assertIsInstance(observed[0],ValueError)
        self.assertIn('matching display channel',str(observed[0]))

    def test_worker_cannot_borrow_surface_even_with_context(self):
        # A worker can own an idle GMainContext; GTK still belongs to main.
        session=self.SpiceClientGLib.Session();display=self.SpiceClientGtk.Display.new(session,0);observed=[]
        def worker():
            context=self.GLib.MainContext.default();owned=context.acquire()
            try:
                if not owned:raise RuntimeError('test failed to acquire idle context')
                try:self.roi.snapshot(display,1)
                except Exception as error:observed.append(error)
            finally:
                if owned:context.release()
        thread=threading.Thread(target=worker);thread.start();thread.join(timeout=3)
        display.destroy()
        self.assertFalse(thread.is_alive());self.assertEqual(len(observed),1)
        self.assertIsInstance(observed[0],RuntimeError)

if __name__=='__main__':unittest.main()
