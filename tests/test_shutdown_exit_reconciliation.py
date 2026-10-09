"""Read-only reporting regression for the candidate392 capture/guest-exit race."""
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

spec = importlib.util.spec_from_file_location('guest_shutdown_reconcile',
    Path(__file__).resolve().parents[1]/'tools/guest-shutdown.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ExitReconciliationTests(unittest.TestCase):
    def run_case(self, outcomes=(), code=0, wrong=False, malformed=False, unavailable=False):
        with tempfile.TemporaryDirectory() as directory:
            vm = Path(directory); (vm/'run').mkdir()
            state = dict(cid='d'*64, started_at='2026-10-09T19:22:59.529333826Z',
                         libvirt_run_id='e068279ba75991d9c288c0d141103dda')
            files = []
            for index, outcome in enumerate(outcomes):
                receipt = dict(cid=state['cid'], started_at=state['started_at'],
                    run_id='wrong' if wrong else state['libvirt_run_id'], outcome=outcome,
                    channel=('critical', 'console')[index % 2], deferred=False,
                    proof_refusal=dict(code='original-pid-present', state='R', pid=113))
                path = vm/'run'/f"capture-exit-{state['cid']}-{index}.json"
                path.write_text('bad' if malformed else json.dumps(receipt)); files.append(path)
            originals = [p.read_bytes() for p in files]
            calls = []
            def inspect(argv, timeout):
                calls.append((argv, timeout))
                if unavailable: raise RuntimeError('missing container')
                return json.dumps(dict(Id=state['cid'], StartedAt=state['started_at'],
                                       Running=False, ExitCode=code))
            supervisor = SimpleNamespace(run=inspect, binary=lambda name:name)
            original = dict(cid=state['cid'], outcome='exited-after-guest-request',
                            request_id='1567e0bb2dab43838975c06e913d6dae')
            result = module.reconcile_exit(vm, state, original, supervisor)
            self.assertEqual(original['outcome'], 'exited-after-guest-request')
            self.assertEqual([p.read_bytes() for p in files], originals)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][0][1], 'inspect')
            self.assertEqual(calls[0][1], 2)
            return result

    def test_392_two_capture_refusals_exit137_is_not_guest_clean_exit(self):
        result = self.run_case(('immediate-stop', 'immediate-stop'), 137)
        self.assertEqual(result['outcome'], 'capture-abort-after-request')
        self.assertEqual(result['observed_outcome'], 'exited-after-guest-request')
        evidence = result['exit_reconciliation']
        self.assertEqual(len(evidence['capture_receipts']), 2)
        self.assertEqual(evidence['container_exit_code'], 137)
        self.assertFalse(evidence['private_terminal_verified'])

    def test_receipt_not_yet_written_nonzero_still_not_clean(self):
        self.assertEqual(self.run_case(code=137)['outcome'], 'abnormal-exit-after-request')

    def test_wrong_run_or_malformed_receipt_never_attributes_capture_force(self):
        for kwargs in ({'wrong':True}, {'malformed':True}):
            self.assertEqual(self.run_case(('immediate-stop',), **kwargs)['outcome'],
                             'exit-unverified-after-request')

    def test_missing_inspection_is_unverified(self):
        self.assertEqual(self.run_case(unavailable=True)['outcome'], 'exit-unverified-after-request')

    def test_zero_exit_and_natural_receipts_preserves_only_temporal_observation(self):
        result = self.run_case(('natural-container-exit',)*2)
        self.assertEqual(result['outcome'], 'exited-after-guest-request')
        self.assertFalse(result['exit_reconciliation']['private_terminal_verified'])

    def test_removed_container_requires_complete_bound_private_and_natural_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            vm = Path(directory); run = vm/'run'; run.mkdir()
            rid = '3d0e4869c7f1c49af50497f440996a5b'
            state = dict(cid='2'*64, started_at='2026-10-09T19:01:02.174626476Z',
                         libvirt_run_id=rid, libvirt_plan_sha256='1'*64, critical_enabled=True)
            private = run/('libvirt-'+rid); private.mkdir()
            binding = dict(cid=state['cid'], started_at=state['started_at'], run_id=rid)
            identity = dict(name='rgpu-'+rid, run_id=rid, pid=113, start_ticks=36728665,
                            uuid='00000000-0000-0000-0000-000000000000')
            scope = dict(kind='pid-namespace', device=5, inode=4026533264, init_start_ticks=36728580)
            running = dict(binding, identity=identity, scope=scope, plan_sha256='1'*64)
            terminal = dict(binding, identity=identity, scope=scope,
                            reason='guest-shutdown', process_exited=True)
            (private/'running.json').write_text(json.dumps(running))
            for i, channel in enumerate(('console','critical')):
                (run/f"capture-exit-{state['cid']}-{i}.json").write_text(json.dumps(
                    dict(binding, channel=channel, outcome='natural-container-exit')))
            def absent(*args, **kwargs): raise RuntimeError('container destroyed')
            supervisor = SimpleNamespace(run=absent, binary=lambda name:name)
            original = dict(cid=state['cid'], outcome='exited-after-guest-request')
            for mutation, expected in (({}, True), ({'process_exited':False}, False),
                    ({'scope':dict(scope, inode=1)}, False), ({'cid':'3'*64}, False)):
                (private/'terminal.json').write_text(json.dumps(dict(terminal, **mutation)))
                result = module.reconcile_exit(vm, state, original, supervisor)
                self.assertEqual(result['exit_reconciliation']['private_terminal_verified'], expected)
                self.assertEqual(result['outcome'], 'exited-after-guest-request' if expected
                                 else 'exit-unverified-after-request')
                self.assertNotIn('container_exit_code', result['exit_reconciliation'])
            (private/'terminal.json').write_text(json.dumps(terminal))
            (run/f"capture-exit-{state['cid']}-1.json").unlink()
            self.assertEqual(module.reconcile_exit(vm, state, original, supervisor)['outcome'],
                             'exit-unverified-after-request')

    def test_other_outcomes_unmodified(self):
        original = dict(outcome='STOP_UNCONFIRMED')
        self.assertIs(module.reconcile_exit(Path('/unused'), {}, original), original)
