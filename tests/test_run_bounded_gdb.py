import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from unittest.mock import patch

SPEC=importlib.util.spec_from_file_location('runner',Path(__file__).parents[1]/'tools/run-bounded-gdb.py')
tool=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(tool)

class RunnerTests(unittest.TestCase):
    BUILD = 'a' * 32
    CID = 'c' * 64
    SERIAL = ('Kernel text 0xffffff801c8e8000-0xffffff801d2e8000 '
              'to be write-protected\nBUILD: identity=' + BUILD + '\n')

    def fixture(self, gdb_body):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__('shutil').rmtree(root))
        (root / 'supervision.json').write_text(json.dumps({
            'cid': self.CID, 'deadline_epoch': __import__('time').time() + 60,
            'serial_ready': str(root / ('serial-' + self.CID + '.ready'))}))
        (root / 'serial.log').write_text(self.SERIAL)
        (root / ('serial-' + self.CID + '.ready')).write_text(self.CID)
        generator = root / 'generator.py'
        generator.write_text("#!/usr/bin/env python3\nimport pathlib, sys\n"
                             "pathlib.Path(sys.argv[sys.argv.index('--output') + 1]).write_text('set confirm off\\n')\n")
        os.chmod(generator, 0o755)
        gdb = root / 'gdb.py'
        gdb.write_text('#!/usr/bin/env python3\n' + gdb_body)
        os.chmod(gdb, 0o755)
        return root, generator, gdb

    def run_main(self, root, generator, gdb):
        output = root / 'output'
        argv = ['runner', '--supervision', str(root / 'supervision.json'),
                '--output', str(output),
                '--build-id', self.BUILD, '--gdb', str(gdb),
                '--generator', str(generator), '--kernel-symbols', '/tmp/kernel',
                '--raphael-binary', '/tmp/raphael', '--raphael-dsym', '/tmp/dsym',
                '--scenario', 'vmid1-root']
        with patch.object(tool, 'verify_port'), patch.object(sys, 'argv', argv):
            tool.main()
        return output

    def test_live_serial_is_derived_from_exact_supervised_cid(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__('shutil').rmtree(root))
        ready = root / ('serial-' + self.CID + '.ready')
        ready.write_text(self.CID + ' console')
        state = {'cid': self.CID, 'critical_enabled': True,
                 'serial_ready': str(ready)}
        self.assertEqual(tool.live_serial_path(state), root / 'serial.log')
        state['serial_ready'] = str(root / ('serial-' + ('d' * 64) + '.ready'))
        with self.assertRaisesRegex(ValueError, 'serial readiness identity'):
            tool.live_serial_path(state)
        state['serial_ready'] = str(ready)
        ready.write_text(self.CID + ' wrong')
        with self.assertRaisesRegex(ValueError, 'serial readiness content'):
            tool.live_serial_path(state)
        ready.write_text(self.CID + ' console')
        (root / 'serial.log').write_text('live')
        (root / 'real-serial.log').write_text('foreign')
        (root / 'serial.log').unlink()
        (root / 'serial.log').symlink_to(root / 'real-serial.log')
        with self.assertRaisesRegex(ValueError, 'live serial path.*symlink'):
            tool.live_serial_path(state)

    def test_requires_mapping_and_exact_build(self):
        line='Kernel text 0xffffff801c8e8000-0xffffff801d2e8000 to be write-protected\n'
        self.assertIsNone(tool.readiness(line,'a'*32))
        self.assertEqual(tool.readiness(line+'BUILD: identity='+('a'*32), 'a'*32),
                         0xffffff801c8e8000)
        self.assertIsNone(tool.readiness(line+'BUILD: identity='+('b'*32), 'a'*32))

    def test_rejects_wrong_kernel_span(self):
        with self.assertRaisesRegex(ValueError,'kernel text'):
            tool.readiness('Kernel text 0x1000000-0x1001000 to be write-protected\n'
                           +'BUILD: identity='+('a'*32), 'a'*32)

    def test_detach_reports_failure_instead_of_claiming_resume(self):
        completed=mock.Mock(returncode=1,stdout='',stderr='not connected')
        with mock.patch.object(tool.subprocess,'run',return_value=completed):
            result=tool.detach('/gdb')
        self.assertFalse(result['detached'])
        self.assertIn('not connected',result['output'])

    def test_port_must_belong_to_running_exact_cid(self):
        good='true {"1234/tcp":[{"HostIp":"127.0.0.1","HostPort":"1234"}]}'
        with mock.patch.object(tool.subprocess,'check_output',return_value=good):
            tool.verify_port('a'*64)
        with mock.patch.object(tool.subprocess,'check_output',return_value='false {}'):
            with self.assertRaisesRegex(ValueError,'not running'):
                tool.verify_port('a'*64)

    def test_process_error_runs_detach_and_reports_failure(self):
        root, generator, gdb = self.fixture("import sys\nsys.exit(7)\n")
        with self.assertRaisesRegex(RuntimeError, 'status 7'):
            with patch.object(tool, 'detach', return_value={
                    'returncode': 0, 'detached': True, 'output': ''}) as detach:
                self.run_main(root, generator, gdb)
        detach.assert_called_once_with(str(gdb))

    def test_vmid1_root_capture_requires_root_specific_markers(self):
        markers = ("VMID1_WRAPPER_ENTRY_HIT\nVMID1_NATIVE_CALL_BOUNDARY\n"
                   "VMID1_PREPARED_CPU_OUTPUT\nWRAPPER_CPU_RETURN_HIT")
        root, generator, gdb = self.fixture("print(" + repr(markers) + ")\n")
        output = self.run_main(root, generator, gdb)
        result = json.loads((output / "result.json").read_text())
        self.assertEqual(result["scenario"], "vmid1-root")
        self.assertFalse((output / "serial.txt").exists())
        self.assertIsNone(result["target_gpu_address"])
        self.assertFalse(result["gpu_completion_established"])

    def test_missing_markers_is_rejected(self):
        root, generator, gdb = self.fixture("print('not a qualified capture')\n")
        with self.assertRaisesRegex(RuntimeError, 'lacks complete bounded capture'):
            self.run_main(root, generator, gdb)

    def test_timeout_terminates_and_reports_bounded_failure(self):
        root, generator, gdb = self.fixture("print('unused')\n")
        process = unittest.mock.Mock(returncode=None)
        process.wait.side_effect = [subprocess.TimeoutExpired('gdb', 1), None]
        real_popen = tool.subprocess.Popen
        def fake_popen(args, *popen_args, **popen_kwargs):
            if args[0] == str(gdb):
                return process
            return real_popen(args, *popen_args, **popen_kwargs)
        with patch.object(tool.subprocess, 'Popen', side_effect=fake_popen), \
                patch.object(tool, 'detach', return_value={
                    'returncode': 0, 'detached': True, 'output': ''}), \
                self.assertRaisesRegex(TimeoutError, 'timed out'):
            self.run_main(root, generator, gdb)
        process.terminate.assert_called_once_with()

    def test_mismatched_cid_port_is_rejected(self):
        value = 'true {"1234/tcp":[{"HostIp":"0.0.0.0","HostPort":"1234"}]}'
        with patch.object(tool.subprocess, 'check_output', return_value=value):
            with self.assertRaisesRegex(ValueError, 'loopback GDB mapping'):
                tool.verify_port(self.CID)

    def test_detach_invocation_is_bounded_even_when_gdb_returns_error(self):
        result = unittest.mock.Mock(returncode=9, stdout='', stderr='detach failed')
        with patch.object(tool.subprocess, 'run',
                          return_value=result) as run:
            self.assertEqual(tool.detach('/tmp/fake-gdb'), {
                'returncode': 9, 'detached': False, 'output': 'detach failed'})
        self.assertEqual(run.call_args.kwargs['timeout'], 3)
        self.assertFalse(run.call_args.kwargs['check'])

if __name__ == '__main__': unittest.main()
