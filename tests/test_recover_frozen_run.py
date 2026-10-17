import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from tests.test_critical_replay import BUILD, snapshot_lines


ROOT = Path(__file__).resolve().parents[1]


def load_tool():
    path = ROOT / 'tools/recover-frozen-run.py'
    spec = importlib.util.spec_from_file_location('recover_frozen_run', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RecoverFrozenRunTests(unittest.TestCase):
    def test_explicit_recovery_selector_cannot_be_overridden_by_cli_tolerance(self):
        tool = load_tool()
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            manifest = {
                'run_id':'0' * 32, 'boot_id':'boot', 'build_id':BUILD,
                'critical_replay_schema':2, 'recovery_lease_schema':3,
                'critical_replay_tolerance':'terminal-prefix',
                'recovery_critical_replay_tolerance':'terminal-prefix-open',
                'recovery_helpers_sha256':{'old':'0' * 64},
                'spec':{
                    'recovery_critical_replay_tolerance':'terminal-prefix-open'},
            }
            (run / 'manifest.json').write_text(json.dumps(manifest))
            terminal = ['BUILD: identity=' + BUILD,
                        'XH3 LIFETIME state=VALID exact']
            later = terminal + ['VM: fault status=0x201b3b']
            (run / 'serial.txt').write_text(''.join(
                snapshot_lines(terminal, snapshot=2) +
                snapshot_lines(later, snapshot=3)[:-1]))
            with self.assertRaisesRegex(
                    ValueError, 'does not match explicit recovery selector'):
                tool.build_proof(Path(temporary), run, 'terminal-prefix')
            _, _, proof = tool.build_proof(
                Path(temporary), run, 'terminal-prefix-open')
            self.assertEqual(proof['tolerance'], 'terminal-prefix-open')
            self.assertEqual(proof['open_attempt']['complete_records'],
                             ['VM: fault status=0x201b3b'])


if __name__ == '__main__':
    unittest.main()
