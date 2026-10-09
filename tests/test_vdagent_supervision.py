"""Exercise the actual supervisor/systemd environment boundary without a VM."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class VdagentSupervisionTests(unittest.TestCase):
    def test_start_locked_forwards_explicit_agent_policy_and_clears_unset(self):
        spec = importlib.util.spec_from_file_location(
            'vdagent_supervision', ROOT / 'tools/vm-supervision.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for value in ('on', 'off', None):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as temporary:
                vm = Path(temporary)
                (vm / 'run/launch-pending').mkdir(parents=True)
                calls = []
                state = {'test': 'bounded-readiness'}

                def external_run(argv, **kwargs):
                    calls.append(argv)
                    if argv[0] == 'docker' and argv[1] == 'ps':
                        return ''
                    if argv[0] == 'systemd-run':
                        unit = next(arg.split('=', 1)[1] for arg in argv
                                    if arg.startswith('--unit='))
                        (vm / 'run' / (unit + '.json')).write_text(json.dumps(state))
                        return ''
                    raise AssertionError('unexpected external command: ' + argv[0])

                env = {'GENERIC_GRAPHICS': 'off', 'CONSOLE_SNAPSHOT': 'restart-timing',
                       'EXTRA': 'must-not-forward', 'GPU': 'must-not-forward'}
                if value is not None:
                    env['CONSOLE_VDAGENT'] = value
                with patch.dict(os.environ, env, clear=True), \
                        patch.object(module, 'binary', side_effect=lambda name: name), \
                        patch.object(module, 'run', side_effect=external_run), \
                        patch.object(module, 'logind_block_inhibited', return_value=True), \
                        patch.object(module, 'verify') as verified, \
                        patch.object(module, 'properties', return_value={
                            'LoadState': 'loaded', 'ActiveState': 'active', 'SubState': 'running'}):
                    self.assertEqual(module.start_locked(
                        vm, 180, ['--gpu', '0000:7b:00.0'], critical_enabled=True), state)
                verified.assert_called_once_with(state)
                commands = [argv for argv in calls if argv[0] == 'systemd-run']
                self.assertEqual(len(commands), 1)
                command = commands[0]
                self.assertEqual([arg for arg in command
                                  if arg.startswith('--setenv=CONSOLE_VDAGENT=')],
                                 ['--setenv=CONSOLE_VDAGENT=' + (value or '')])
                # Apply only the emitted assignments over a contrary manager
                # environment: inherited caller state cannot make this test pass.
                managed_env = {'CONSOLE_VDAGENT': 'on' if value != 'on' else 'off'}
                for arg in command:
                    if arg.startswith('--setenv='):
                        key, setting = arg[len('--setenv='):].split('=', 1)
                        managed_env[key] = setting
                self.assertEqual(managed_env['CONSOLE_VDAGENT'], value or '')
                self.assertIn('--setenv=CONSOLE_SNAPSHOT=restart-timing', command)
                for key in ('GPU', 'GPU_ID', 'GPU_ROM', 'GPU_SUB', 'EXTRA'):
                    self.assertIn('--setenv=' + key + '=', command)
                self.assertIn('--property=RuntimeMaxSec=180s', command)
                self.assertTrue(any(arg.startswith('--property=ExecStopPost=')
                                    and ' cleanup ' in arg for arg in command))
                self.assertIn('--critical-serial', command)
                self.assertEqual(command[-3:], ['--', '--gpu', '0000:7b:00.0'])
                self.assertEqual(list((vm / 'run/launch-pending').iterdir()), [])
                self.assertEqual(json.loads((vm / 'run/supervision.json').read_text()), state)


if __name__ == '__main__':
    unittest.main()
