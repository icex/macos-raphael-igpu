import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SleepInhibitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('experiment_sleep_test',
                                                       ROOT / 'tools/experiment.py')
        cls.tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.tool)

    def busctl(self, payload, returncode=0):
        return patch.object(
            self.tool.subprocess, 'run',
            return_value=SimpleNamespace(returncode=returncode,
                                          stdout=json.dumps(payload)))

    @staticmethod
    def payload(rows, signature='a(ssssuu)'):
        return {'type': signature, 'data': [rows]}

    def test_accepts_root_system_inhibitor_covering_sleep_and_idle(self):
        payload = self.payload([
            ['sleep:idle', 'sleep infinity', 'GPU debugging', 'block', 0, 4837],
        ])
        with self.busctl(payload) as run:
            self.assertTrue(self.tool.sleep_inhibited())
        self.assertEqual(run.call_args.args[0][:4],
                         ['busctl', '--system', '--json=short', 'call'])
        self.assertNotIn('--user', run.call_args.args[0])

    def test_rejects_delay_only_or_partial_scope(self):
        rows = [
            ['sleep', 'a', 'delay', 'delay', 0, 1],
            ['sleep', 'b', 'partial', 'block', 0, 2],
        ]
        with self.busctl(self.payload(rows)):
            self.assertFalse(self.tool.sleep_inhibited())

    def test_accepts_user_level_idle_only_block(self):
        # AGENTS.md: the normal test path runs an external user-level
        # `systemd-inhibit --what=idle`, so an idle-only block inhibitor satisfies
        # the gate.
        rows = [['idle', 'b', 'external idle inhibitor', 'block', 0, 2]]
        with self.busctl(self.payload(rows)):
            self.assertTrue(self.tool.sleep_inhibited())

    def test_rejects_malformed_or_failed_logind_call(self):
        malformed = [
            ({'type': 'a(ssssuu)', 'data': []}, 0),
            ({'type': 'a(ssssuu)', 'data': [[['sleep:idle', 'who']]]}, 0),
            ({'type': 'a(ssssuu)', 'data': [[['sleep:idle', 'who', 'why', 'block', 0, 'pid']]]}, 0),
            ({'type': 's', 'data': 'sleep:idle'}, 0),
        ]
        for payload, returncode in malformed:
            with self.subTest(payload=payload), self.busctl(payload, returncode):
                self.assertFalse(self.tool.sleep_inhibited())

        with patch.object(self.tool.subprocess, 'run', side_effect=OSError('no bus')):
            self.assertFalse(self.tool.sleep_inhibited())
        with patch.object(self.tool.subprocess, 'run', side_effect=TimeoutError('slow bus')):
            self.assertFalse(self.tool.sleep_inhibited())
        trailing_bad = self.payload([
            ['sleep:idle', 'who', 'why', 'block', 0, 1],
            ['sleep', 'who'],
        ])
        with self.busctl(trailing_bad):
            self.assertFalse(self.tool.sleep_inhibited())

    def test_rejects_nonzero_logind_call(self):
        payload = self.payload([
            ['sleep:idle', 'who', 'why', 'block', 0, 1],
        ])
        with self.busctl(payload, returncode=1):
            self.assertFalse(self.tool.sleep_inhibited())

    def test_host_snapshot_uses_logind_result(self):
        with patch.object(self.tool, 'sleep_inhibited', return_value=True), \
                patch.object(self.tool, 'command', return_value=''), \
                patch.object(self.tool.subprocess, 'run',
                             return_value=SimpleNamespace(returncode=0, stdout='')):
            snapshot = self.tool.host_snapshot()
        self.assertIs(snapshot['sleep_inhibited'], True)


if __name__ == '__main__':
    unittest.main()
