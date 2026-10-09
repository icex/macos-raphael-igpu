import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('preferences',ROOT/'tools/console-preferences.py')
prefs=importlib.util.module_from_spec(spec);spec.loader.exec_module(prefs)

class PreferencesTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.directory=Path(self.tmp.name).resolve();self.path=self.directory/prefs.NAME
    def put(self,data):
        self.path.write_bytes(data);self.path.chmod(0o600)
    def test_missing_default_and_atomic_set_read(self):
        self.assertEqual(prefs.read(self.directory),dict(schema=1,guest_scale=2,source='legacy-default'))
        prefs.write(self.directory,1)
        self.assertEqual(prefs.read(self.directory)['guest_scale'],1)
        self.assertEqual(self.path.stat().st_mode&0o777,0o600)
        prefs.write(self.directory,2)
        self.assertEqual(prefs.read(self.directory)['guest_scale'],2)
        self.assertEqual(list(self.directory.glob('.console-preferences-*')),[])
    def test_malformed_and_oversized_are_not_overwritten(self):
        for data in [b'bad',b'[]',b'{"schema":1,"guest_scale":true}',
                     b'{"schema":1,"guest_scale":3}',b'{"schema":1,"guest_scale":1,"extra":0}',
                     b'{"schema":1,"guest_scale":1,"guest_scale":2}',b' '*4097]:
            self.put(data)
            with self.subTest(data=data[:80]),self.assertRaises(ValueError):prefs.read(self.directory)
            with self.assertRaises(ValueError):prefs.write(self.directory,1)
            self.assertEqual(self.path.read_bytes(),data)
    def test_symlink_hardlink_wrongmode_and_owner_refused(self):
        target=self.directory/'target';target.write_text('{}');target.chmod(0o600)
        self.path.symlink_to(target)
        with self.assertRaises(OSError):prefs.read(self.directory)
        self.path.unlink();os.link(target,self.path)
        with self.assertRaises(ValueError):prefs.read(self.directory)
        self.path.unlink();self.put(b'{"schema":1,"guest_scale":1}');self.path.chmod(0o644)
        with self.assertRaises(ValueError):prefs.read(self.directory)
        self.path.chmod(0o600)
        with patch.object(prefs.os,'geteuid',return_value=os.geteuid()+1),self.assertRaises(ValueError):prefs.read(self.directory)
    def test_failed_replace_preserves_old_and_removes_temporary(self):
        prefs.write(self.directory,2);old=self.path.read_bytes()
        with patch.object(prefs.os,'replace',side_effect=OSError('injected')),self.assertRaises(OSError):prefs.write(self.directory,1)
        self.assertEqual(self.path.read_bytes(),old)
        self.assertEqual(list(self.directory.glob('.console-preferences-*')),[])
    def test_invalid_scale_and_writable_directory(self):
        for value in (True,0,3,'1'):
            with self.assertRaises(ValueError):prefs.write(self.directory,value)
        self.directory.chmod(0o777)
        with self.assertRaises(ValueError):prefs.read(self.directory)
