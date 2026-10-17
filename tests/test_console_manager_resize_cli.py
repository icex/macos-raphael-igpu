import contextlib
import importlib.util
import io
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('resize',Path(__file__).resolve().parents[1]/'tools/console-manager-resize.py')
resize=importlib.util.module_from_spec(spec)
spec.loader.exec_module(resize)

class ResizeCLI(unittest.TestCase):
    def parse(self,*args):
        return resize.parse_args(['--manager-prefix','/tmp/prefix','--output','/tmp/result',*args])

    def test_default_and_manager_arguments_preserved(self):
        a=self.parse('--','--connect','test:///default')
        self.assertEqual(a.viewport,[(1280,720),(1920,1080)])
        self.assertEqual(a.deadline_seconds,45)
        self.assertEqual(a.manager_args,['--','--connect','test:///default'])

    def test_ordered_arbitrary_sequence_and_single(self):
        a=self.parse('--viewport','1234','742','--viewport','1280','720','--viewport','1920','1080')
        self.assertEqual(a.viewport,[(1234,742),(1280,720),(1920,1080)])
        self.assertEqual(self.parse('--viewport','320','200').viewport,[(320,200)])

    def test_twelve_requests_have_bounded_deadline(self):
        args=[]
        for i in range(12):args+=['--viewport',str(1000+i*2),'700']
        a=self.parse(*args)
        self.assertEqual(len(a.viewport),12)
        self.assertLessEqual(a.deadline_seconds,180)
        self.assertGreater(a.deadline_seconds,120)
        with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
            self.parse(*args,'--viewport','1280','720')

    def test_invalid_geometry_and_incomplete_pair_refused(self):
        for args in [('319','720'),('1921','720'),('1280','199'),('1280','1081'),('x','720'),('1280',)]:
            with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
                self.parse('--viewport',*args)
