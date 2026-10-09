import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('entry_console',ROOT/'tools/libvirt-console-entry.py')
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)


class DaemonEnvironmentTests(unittest.TestCase):
    def test_child_discovery_cannot_select_inherited_launcher_shim(self):
        # Exercise child PATH lookup without executing an emulator or libvirtd.
        with tempfile.TemporaryDirectory() as tmp:
            shim=Path(tmp)/'qemu-system-x86_64'
            shim.write_text('#!/bin/sh\nexit 99\n');shim.chmod(0o755)
            inherited=dict(os.environ,PATH=tmp+':/usr/bin',
                           XDG_RUNTIME_DIR='/run/vm/private/runtime',
                           RGPU_LIBVIRT_RUN_ID='test-run')
            real_run=subprocess.run
            code='import shutil,os,json;print(json.dumps(dict(binary=shutil.which("qemu-system-x86_64"),runtime=os.environ["XDG_RUNTIME_DIR"],run=os.environ["RGPU_LIBVIRT_RUN_ID"])))'
            control=real_run([sys.executable,'-c',code],env=inherited,
                             capture_output=True,text=True,check=True)
            self.assertEqual(json.loads(control.stdout)['binary'],str(shim))
            observed=[]
            def fake_daemon(argv,**kw):
                self.assertEqual(argv,['libvirtd','--daemon'])
                self.assertTrue(kw['check']);self.assertEqual(kw['timeout'],7)
                result=real_run([sys.executable,'-c',code],env=kw['env'],
                                capture_output=True,text=True,check=True)
                observed.append(json.loads(result.stdout))
                return result
            with patch.dict(os.environ,inherited,clear=True), \
                 patch.object(mod.time,'monotonic',return_value=100), \
                 patch.object(mod.subprocess,'run',side_effect=fake_daemon):
                mod.start_daemon(107)
                self.assertEqual(os.environ['PATH'],inherited['PATH'])
            self.assertNotEqual(observed[0]['binary'],str(shim))
            self.assertEqual(observed[0]['runtime'],inherited['XDG_RUNTIME_DIR'])
            self.assertEqual(observed[0]['run'],'test-run')

    def test_daemon_failure_is_not_swallowed(self):
        with patch.object(mod.subprocess,'run',side_effect=subprocess.CalledProcessError(1,['libvirtd'])):
            with self.assertRaises(subprocess.CalledProcessError):mod.start_daemon(0)

    def test_daemon_wait_retains_ten_second_cap(self):
        with patch.object(mod.time,'monotonic',return_value=100), \
             patch.object(mod.subprocess,'run') as run:
            mod.start_daemon(500)
            self.assertEqual(run.call_args.kwargs['timeout'],10)
