import importlib.util
import json
import os
from pathlib import Path
import tempfile
import subprocess
import sys
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
    def test_explicit_clipboard_migration_preserves_scale_and_independent_setters(self):
        prefs.write(self.directory,1)
        self.assertNotIn('clipboard_text',prefs.read(self.directory))
        value=prefs.write(self.directory,clipboard_text=True)
        self.assertEqual((value['schema'],value['guest_scale'],value['clipboard_text']),(2,1,True))
        self.assertTrue(prefs.write(self.directory,2)['clipboard_text'])
        self.assertFalse(prefs.write(self.directory,clipboard_text=False)['clipboard_text'])
        self.assertEqual(prefs.read(self.directory)['guest_scale'],2)
        for value in ('on',1,[]):
            with self.assertRaises(ValueError):prefs.write(self.directory,clipboard_text=value)
        for data in [b'{"schema":2,"guest_scale":1}',b'{"schema":2,"guest_scale":1,"clipboard_text":1}',
                     b'{"schema":1,"guest_scale":1,"clipboard_text":true}']:
            self.put(data)
            with self.assertRaises(ValueError):prefs.read(self.directory)

    def test_refresh_schema_migration_preserves_other_choices(self):
        self.assertEqual(prefs.read(self.directory).get('refresh_rate',60),60)
        prefs.write(self.directory,1,clipboard_text=True)
        value=prefs.write(self.directory,refresh_rate=120)
        self.assertEqual((value['schema'],value['guest_scale'],value['clipboard_text'],value['refresh_rate']),(3,1,True,120))
        self.assertEqual(prefs.write(self.directory,2)['refresh_rate'],120)
        self.assertEqual(prefs.write(self.directory,clipboard_text=False)['refresh_rate'],120)
        value=prefs.write(self.directory,refresh_rate=60)
        self.assertEqual((value['guest_scale'],value['clipboard_text'],value['refresh_rate']),(2,False,60))
        self.path.unlink()
        value=prefs.write(self.directory,refresh_rate=120)
        self.assertEqual((value['guest_scale'],value['clipboard_text'],value['refresh_rate']),(2,False,120))

    def test_refresh_cli_defaults_legacy_schemas_and_explicit_120(self):
        command=[sys.executable,'-B',str(ROOT/'tools/console-preferences.py'),'--support-dir',str(self.directory)]
        for value in [None,dict(schema=1,guest_scale=1),dict(schema=2,guest_scale=2,clipboard_text=True)]:
            if value is not None:self.put(json.dumps(value).encode())
            self.assertEqual(subprocess.check_output(command+['--read-refresh'],text=True).strip(),'60')
        subprocess.run(command+['--set-refresh','120'],check=True,capture_output=True)
        self.assertEqual(subprocess.check_output(command+['--read-refresh'],text=True).strip(),'120')
        self.assertTrue(prefs.read(self.directory)['clipboard_text'])
        for args in [['--read-refresh','--read-scale'],['--read-refresh','--set-clipboard','off'],['--set-refresh','90']]:
            self.assertNotEqual(subprocess.run(command+args,capture_output=True).returncode,0)

    def test_refresh_invalid_schema_fields_types_and_failed_migration(self):
        prefs.write(self.directory,1,clipboard_text=True);old=self.path.read_bytes()
        with patch.object(prefs.os,'replace',side_effect=OSError('injected')),self.assertRaises(OSError):
            prefs.write(self.directory,refresh_rate=120)
        self.assertEqual(self.path.read_bytes(),old)
        for value in (True,'120',60.0,0,90,121):
            with self.assertRaises(ValueError):prefs.write(self.directory,refresh_rate=value)
        for value in [dict(schema=3,guest_scale=1,clipboard_text=True),
                      dict(schema=2,guest_scale=1,clipboard_text=True,refresh_rate=60),
                      dict(schema=3,guest_scale=1,clipboard_text=True,refresh_rate=True),
                      dict(schema=3,guest_scale=1,clipboard_text=True,refresh_rate=90),
                      dict(schema=3,guest_scale=1,clipboard_text=True,refresh_rate=60.0)]:
            self.put(json.dumps(value).encode())
            with self.assertRaises(ValueError):prefs.read(self.directory)

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
