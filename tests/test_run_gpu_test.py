import importlib.util
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("run_gpu_test", ROOT / "tools/run-gpu-test.py")
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

class RunGpuTestTests(unittest.TestCase):
    def test_command_has_external_idle_inhibitor(self):
        cmd = mod.build_command(Path('/vm'), Path('/m'), Path('/o'), Path('/wt'))
        self.assertEqual(cmd[:3], ['systemd-inhibit', '--what=idle', '--mode=block'])
        self.assertNotIn('--ack-risk', cmd)
        self.assertNotIn('--manual-reuse', cmd)
        self.assertNotIn('--what=sleep:idle', cmd)
        self.assertIn('/wt/tools/experiment.py', cmd)

    def test_stale_manual_reuse_attrs_are_never_forwarded(self):
        # Same-boot reuse is admitted automatically now; there is no flag to forward,
        # even if a caller still sets these now-meaningless attributes.
        with tempfile.TemporaryDirectory() as d:
            vm = Path(d); (vm/'manifest').write_text('{}')
            args = type('A', (), {'vm_dir':str(vm), 'manifest':str(vm/'manifest'),
                'output':str(vm/'out'), 'dry_run':True, 'worktree':str(ROOT),
                'manual_reuse':True, 'ack_risk':True})
            with patch('builtins.print') as output:
                self.assertEqual(mod.run(args), 0)
            command = json.loads(output.call_args.args[0])['command']
            self.assertNotIn('--manual-reuse', command)
            self.assertNotIn('--ack-risk', command)

    def test_status_append_is_compact(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'status.md'
            mod.append_status(p, {'verdict':'INVALID','earliest_failure':'launcher'}, Path('/out'))
            text = p.read_text()
            self.assertIn('One-command GPU test', text)
            self.assertIn('`INVALID`', text)
            self.assertIn('`launcher`', text)

    def test_dry_run_does_not_write_output_or_status(self):
        with tempfile.TemporaryDirectory() as d:
            vm = Path(d); (vm/'manifest').write_text('{}')
            args = type('A', (), {'vm_dir':str(vm), 'manifest':str(vm/'manifest'), 'output':str(vm/'out'), 'dry_run':True, 'ack_risk':False, 'worktree':str(ROOT)})
            self.assertEqual(mod.run(args), 0)
            self.assertFalse((vm/'out').exists())
            self.assertFalse((vm/'status.md').exists())

    def test_non_json_failure_is_durable_and_preserves_exit_code(self):
        with tempfile.TemporaryDirectory() as d:
            vm = Path(d); manifest = vm/'manifest'; manifest.write_text(json.dumps({'run_id':'abc123','spec':{'candidate_version':'1.0.202'}}))
            output = vm/'out'; status = vm/'status.md'
            completed = type('Completed', (), {'stdout':'partial\n', 'stderr':'boom\n', 'returncode':7})
            args = type('A', (), {'vm_dir':str(vm), 'manifest':str(manifest), 'output':str(output),
                                  'status_path':str(status), 'dry_run':False, 'worktree':str(ROOT)})
            with patch.object(mod.subprocess, 'run', return_value=completed):
                self.assertEqual(mod.run(args), 7)
            self.assertEqual((output/'wrapper-stdout.txt').read_text(), 'partial\n')
            self.assertEqual((output/'wrapper-stderr.txt').read_text(), 'boom\n')
            result = json.loads((output/'wrapper-result.json').read_text())
            self.assertEqual(result['returncode'], 7)
            self.assertEqual(result['stdout_bytes'], 8)
            self.assertEqual(result['verdict'], 'WRAPPER_FAILURE')
            self.assertEqual(result['earliest_failure'], 'launcher')
            self.assertEqual(result['candidate_version'], '1.0.202')
            self.assertEqual(result['run_id'], 'abc123')
            self.assertIn('One-command GPU test', status.read_text())

    def test_oserror_is_durable_and_classified(self):
        with tempfile.TemporaryDirectory() as d:
            vm = Path(d); manifest = vm/'manifest'; manifest.write_text('{}'); output = vm/'out'
            args = type('A', (), {'vm_dir':str(vm), 'manifest':str(manifest), 'output':str(output),
                                  'status_path':str(vm/'status.md'), 'dry_run':False, 'worktree':str(ROOT)})
            with patch.object(mod.subprocess, 'run', side_effect=OSError('no systemd-inhibit')):
                self.assertEqual(mod.run(args), 127)
            result = json.loads((output/'wrapper-result.json').read_text())
            self.assertEqual(result['verdict'], 'WRAPPER_FAILURE')
            self.assertEqual(result['returncode'], 127)
            self.assertIn('no systemd-inhibit', (output/'wrapper-stderr.txt').read_text())

    def test_status_path_defaults_to_repository_status(self):
        self.assertEqual(mod.default_status_path(), ROOT/'status.md')

    def test_existing_output_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            vm = Path(d); manifest = vm/'manifest'; manifest.write_text('{}'); output = vm/'out'; output.mkdir()
            args = type('A', (), {'vm_dir':str(vm), 'manifest':str(manifest), 'output':str(output),
                                  'status_path':str(vm/'status.md'), 'dry_run':False, 'worktree':str(ROOT)})
            with self.assertRaisesRegex(SystemExit, 'output already exists'):
                mod.run(args)

if __name__ == '__main__': unittest.main()
