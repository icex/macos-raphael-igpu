"""Direct-manager capture-exit receipts and guest-shutdown exit reconciliation."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT/'tools'/file)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


sup = load('direct_capture_supervision', 'vm-supervision.py')
gs = load('direct_capture_guest_shutdown', 'guest-shutdown.py')
CID = 'a'*64; RUN = 'b'*32; ADMIT = 'c'*64; START = '2026-10-12T09:54:20.835262854Z'


class DirectCaptureExitTests(unittest.TestCase):
    """The hook never execs into a direct container and never delays an unobserved stop."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.vm = Path(self.tmp.name); (self.vm/'run').mkdir()
        self.clock = 10.0
        self.live = [True, 'removed']
        self.calls = []

    def eof(self, channel='critical', **changes):
        value = dict(schema=1, cid=CID, started_at=START, run_id=RUN, admission_sha256=ADMIT,
                     channel=channel, eof_monotonic=9.9, eof_epoch=100+9.9-10,
                     published_monotonic=9.95)
        value.update(changes)
        (self.vm/'run'/f'capture-eof-{CID}-{channel}.json').write_text(json.dumps(value))

    def command(self, args, **kwargs):
        self.calls.append(args)
        if args[1] == 'inspect':
            value = self.live.pop(0) if len(self.live) > 1 else self.live[0]
            if value == 'removed':
                raise sup.CommandFailure('docker inspect failed (1)', 1)
            return json.dumps(dict(Id=CID, StartedAt=START, Running=value))
        if args[1] == 'ps':
            return ''
        raise AssertionError(args)

    def invoke(self, channel='critical'):
        def sleep(seconds): self.clock += seconds
        with patch.object(sup, 'run', side_effect=self.command), \
             patch.object(sup, 'binary', side_effect=lambda x: x), \
             patch.object(sup, 'stop_exact') as stop, \
             patch.object(sup.time, 'monotonic', side_effect=lambda: self.clock), \
             patch.object(sup.time, 'time', side_effect=lambda: 100+self.clock-10), \
             patch.object(sup.time, 'sleep', side_effect=sleep):
            result = sup.capture_exit(self.vm, CID, START, 200, RUN, ADMIT, channel,
                                      manager='direct')
        receipts = list((self.vm/'run').glob(f'capture-exit-{CID}-*.json'))
        self.assertEqual(len(receipts), 1)
        self.assertEqual(json.loads(receipts[0].read_text()), result)
        return result, stop

    def test_bound_eof_then_removed_container_is_natural_without_signal(self):
        self.eof()
        result, stop = self.invoke()
        stop.assert_not_called()
        self.assertEqual(result['outcome'], 'natural-container-exit')
        self.assertEqual((result['manager'], result['run_id'], result['admission_sha256']),
                         ('direct', RUN, ADMIT))
        self.assertEqual(result['transport_end_kind'], 'clean-eof')
        self.assertTrue(result['container_removed'])
        self.assertFalse(any(call[1] == 'exec' for call in self.calls))

    def test_already_removed_at_first_look_after_eof_is_natural(self):
        self.eof(); self.live = ['removed']
        result, stop = self.invoke()
        stop.assert_not_called()
        self.assertEqual(result['outcome'], 'natural-container-exit')

    def test_no_transport_observation_stops_live_container_immediately(self):
        self.live = [True]
        result, stop = self.invoke()
        stop.assert_called_once_with(CID)
        self.assertEqual(result['outcome'], 'immediate-stop')
        self.assertEqual(result['refusal_stage'], 'transport-observation')
        self.assertEqual(self.clock, 10.0)
        self.assertFalse(any(call[1] == 'exec' for call in self.calls))

    def test_no_transport_observation_and_stopped_is_never_natural(self):
        self.live = ['removed']
        result, stop = self.invoke()
        stop.assert_not_called()
        self.assertEqual(result['outcome'], 'already-stopped')

    def test_foreign_eof_identity_gets_no_grace(self):
        for field in ('run_id', 'admission_sha256', 'started_at', 'cid'):
            with self.subTest(field=field):
                for path in (self.vm/'run').glob('capture-*'): path.unlink()
                self.eof(**{field: 'wrong'}); self.live = [True]; self.clock = 10.0
                result, stop = self.invoke()
                stop.assert_called_once_with(CID)
                self.assertEqual(result['outcome'], 'immediate-stop')
                self.assertFalse(result['deferred'])
                self.assertEqual(self.clock, 10.0)

    def test_live_container_after_eof_gets_at_most_two_seconds(self):
        self.eof(); self.live = [True]
        result, stop = self.invoke()
        stop.assert_called_once_with(CID)
        self.assertEqual(result['outcome'], 'receipt-grace-expired')
        self.assertTrue(result['deferred'])
        self.assertLessEqual(self.clock, 9.9+2+0.001)

    def test_present_but_uninspectable_container_is_stopped(self):
        self.eof(); self.live = ['removed']
        original = self.command
        def command(args, **kwargs):
            if args[1] == 'ps':
                self.calls.append(args); return CID+'\n'
            return original(args, **kwargs)
        self.command = command
        result, stop = self.invoke()
        stop.assert_called_once_with(CID)
        self.assertEqual(result['outcome'], 'immediate-stop')

    def test_receipt_written_only_after_immediate_stop(self):
        self.live = [True]; order = []
        with patch.object(sup, 'run', side_effect=self.command), \
             patch.object(sup, 'binary', side_effect=lambda x: x), \
             patch.object(sup, 'stop_exact', side_effect=lambda cid: order.append('stop')), \
             patch.object(sup, '_durable_json', side_effect=lambda *a: order.append('receipt')), \
             patch.object(sup.time, 'monotonic', return_value=10.0), \
             patch.object(sup.time, 'time', return_value=100):
            sup.capture_exit(self.vm, CID, START, 200, RUN, ADMIT, 'console', manager='direct')
        self.assertEqual(order, ['stop', 'receipt'])

    def test_libvirt_default_still_requires_exec_witness(self):
        self.eof(); self.live = [True]
        with patch.object(sup, 'run', side_effect=self.command), \
             patch.object(sup, 'binary', side_effect=lambda x: x), \
             patch.object(sup, 'stop_exact') as stop, \
             patch.object(sup.time, 'monotonic', side_effect=lambda: self.clock), \
             patch.object(sup.time, 'time', side_effect=lambda: 100+self.clock-10):
            result = sup.capture_exit(self.vm, CID, START, 200, RUN, ADMIT, 'critical')
        # The fake has no exec support: libvirt refuses and stops immediately.
        stop.assert_called_once_with(CID)
        self.assertEqual((result['outcome'], result['refusal_stage']), ('immediate-stop', 'docker-exec'))
        self.assertNotIn('manager', result)


class DirectArmWiringTests(unittest.TestCase):
    def arm(self, env, critical=True):
        with tempfile.TemporaryDirectory() as tmp:
            vm = Path(tmp); (vm/'run').mkdir(); (vm/'sercat.py').write_text('')
            calls = []
            def command(argv, **kw):
                calls.append(argv)
                for arg in argv:
                    if arg.startswith('--setenv=VM_SERIAL_READY='):
                        Path(arg.split('=', 2)[2]).write_text('ready')
                return ''
            base = dict(VM_MANAGER='direct', GENERIC_GRAPHICS='on')
            clear = {k: v for k, v in os.environ.items() if not k.startswith('RGPU_')}
            with patch.dict(os.environ, dict(clear, **base, **env), clear=True), \
                 patch.object(sup, 'inspect', return_value=(START, 100)), \
                 patch.object(sup, 'binary', side_effect=lambda x: x), \
                 patch.object(sup, 'verify'), patch.object(sup, 'run', side_effect=command), \
                 patch.object(sup.time, 'time', return_value=101):
                state = sup.arm(vm, CID, 100, critical_enabled=critical)
            return state, calls

    def test_bound_direct_run_installs_capture_exit_on_every_channel(self):
        state, calls = self.arm(dict(RGPU_CAPTURE_RUN_ID=RUN, RGPU_CAPTURE_ADMISSION_SHA256=ADMIT))
        self.assertEqual(calls[0][-5:], ['docker', 'stop', '--time', '0', CID])
        services = [c for c in calls[1:] if any(a.startswith('--property=ExecStopPost=') for a in c)]
        self.assertEqual(len(services), 2)
        for service, channel in zip(services, ('console', 'critical')):
            stop = next(a for a in service if a.startswith('--property=ExecStopPost='))
            self.assertIn('capture-exit', stop)
            self.assertIn('--manager direct', stop)
            self.assertTrue(stop.endswith('--channel '+channel))
            self.assertIn(RUN, stop); self.assertIn(ADMIT, stop)
            self.assertIn(f'--setenv=VM_SERIAL_RUN_ID={RUN}', service)
            self.assertIn(f'--setenv=VM_SERIAL_ADMISSION_SHA256={ADMIT}', service)
            self.assertIn(f'--setenv=VM_SERIAL_CHANNEL={channel}', service)
        self.assertEqual((state['capture_manager'], state['capture_run_id'],
                          state['capture_admission_sha256']), ('direct', RUN, ADMIT))
        self.assertNotIn('libvirt_run_id', state)

    def test_unbound_or_console_only_direct_run_keeps_plain_stop(self):
        for env, critical in (({}, True),
                              (dict(RGPU_CAPTURE_RUN_ID=RUN, RGPU_CAPTURE_ADMISSION_SHA256=ADMIT), False)):
            with self.subTest(env=env, critical=critical):
                state, calls = self.arm(env, critical)
                stops = [a for c in calls[1:] for a in c if a.startswith('--property=ExecStopPost=')]
                self.assertTrue(stops)
                for stop in stops:
                    self.assertEqual(stop, '--property=ExecStopPost=docker stop --time 0 '+CID)
                self.assertNotIn('capture_run_id', state)

    def test_malformed_direct_identity_refuses(self):
        for env in (dict(RGPU_CAPTURE_RUN_ID='x'*32, RGPU_CAPTURE_ADMISSION_SHA256=ADMIT),
                    dict(RGPU_CAPTURE_RUN_ID=RUN)):
            with self.subTest(env=env), self.assertRaisesRegex(RuntimeError, 'direct capture identity'):
                self.arm(env)

    def test_launch_service_forwards_direct_identity(self):
        source = (ROOT/'tools/vm-supervision.py').read_text()
        self.assertIn('"RGPU_CAPTURE_RUN_ID", "RGPU_CAPTURE_ADMISSION_SHA256"', source)
        harness = (ROOT/'tools/experiment.py').read_text()
        self.assertIn('RGPU_CAPTURE_RUN_ID=manifest[\'run_id\']', harness)


class DirectReconciliationTests(unittest.TestCase):
    def run_case(self, receipts=None, events=None, inspect=None, state_changes=None):
        with tempfile.TemporaryDirectory() as directory:
            vm = Path(directory); (vm/'run').mkdir()
            state = dict(cid=CID, started_at=START, critical_enabled=True,
                         capture_manager='direct', capture_run_id=RUN,
                         capture_admission_sha256=ADMIT)
            state.update(state_changes or {})
            if receipts is None:
                receipts = [self.receipt('console'), self.receipt('critical')]
            for index, receipt in enumerate(receipts):
                (vm/'run'/f'capture-exit-{CID}-{index}.json').write_text(json.dumps(receipt))
            if events is None:
                events = [self.die(0)]
            calls = []
            def command(argv, timeout):
                calls.append(argv)
                self.assertEqual(timeout, 2)
                if argv[1] == 'inspect':
                    if inspect is None: raise RuntimeError('No such object')
                    return json.dumps(inspect)
                if argv[1] == 'events':
                    self.assertIn('container='+CID, argv)
                    self.assertEqual(argv[argv.index('--since')+1], START)
                    return ''.join(json.dumps(e)+'\n' for e in events)
                raise AssertionError(argv)
            supervisor = SimpleNamespace(run=command, binary=lambda name: name)
            original = dict(cid=CID, outcome='exited-after-guest-request')
            result = gs.reconcile_exit(vm, state, original, supervisor)
            self.assertEqual(original['outcome'], 'exited-after-guest-request')
            return result, calls

    @staticmethod
    def receipt(channel, **changes):
        value = dict(cid=CID, started_at=START, run_id=RUN, admission_sha256=ADMIT,
                     manager='direct', channel=channel, outcome='natural-container-exit',
                     deferred=True, transport_end_kind='clean-eof',
                     budget_origin='transport-observation', container_removed=True)
        value.update(changes)
        return value

    @staticmethod
    def die(code, **changes):
        value = dict(Type='container', Action='die',
                     Actor=dict(ID=CID, Attributes=dict(exitCode=str(code), name='rgpu-launch')))
        value.update(changes)
        return value

    def test_both_natural_receipts_and_zero_die_event_verify(self):
        result, calls = self.run_case()
        self.assertEqual(result['outcome'], 'exited-after-guest-request')
        evidence = result['exit_reconciliation']
        self.assertTrue(evidence['direct_natural_verified'])
        self.assertFalse(evidence['private_terminal_verified'])
        self.assertEqual((evidence['container_exit_code'], evidence['container_exit_source']),
                         (0, 'die-event'))
        self.assertEqual(evidence['errors'], [])
        self.assertEqual([c[1] for c in calls], ['inspect', 'events'])

    def test_retained_container_exit_zero_verifies_without_events(self):
        result, calls = self.run_case(inspect=dict(Id=CID, StartedAt=START, Running=False, ExitCode=0))
        self.assertEqual(result['outcome'], 'exited-after-guest-request')
        self.assertEqual([c[1] for c in calls], ['inspect'])

    def test_forced_receipt_is_capture_abort(self):
        for outcome in ('immediate-stop', 'receipt-grace-expired'):
            with self.subTest(outcome=outcome):
                result, _ = self.run_case([self.receipt('console'),
                                           self.receipt('critical', outcome=outcome)])
                self.assertEqual(result['outcome'], 'capture-abort-after-request')

    def test_missing_or_non_natural_channel_is_unverified(self):
        for receipts in ([self.receipt('console')], [],
                         [self.receipt('console'), self.receipt('console')],
                         [self.receipt('console'), self.receipt('critical', outcome='already-stopped')],
                         [self.receipt('console'), self.receipt('critical', transport_end_kind=None)]):
            with self.subTest(receipts=receipts):
                result, _ = self.run_case(receipts)
                self.assertEqual(result['outcome'], 'exit-unverified-after-request')
                self.assertFalse(result['exit_reconciliation']['direct_natural_verified'])

    def test_identity_mismatch_is_unverified(self):
        for changes in ({'run_id': 'f'*32}, {'admission_sha256': 'e'*64}, {'manager': None},
                        {'started_at': '2026-10-12T00:00:00Z'}):
            with self.subTest(changes=changes):
                result, _ = self.run_case([self.receipt('console'),
                                           self.receipt('critical', **changes)])
                self.assertEqual(result['outcome'], 'exit-unverified-after-request')
                self.assertTrue(any(e.startswith('invalid capture receipt')
                                    for e in result['exit_reconciliation']['errors']))
        for changes in ({'capture_run_id': 'f'*32}, {'capture_admission_sha256': 'e'*64},
                        {'capture_admission_sha256': None}):
            with self.subTest(state=changes):
                result, _ = self.run_case(state_changes=changes)
                self.assertEqual(result['outcome'], 'exit-unverified-after-request')

    def test_nonzero_or_missing_exit_status(self):
        result, _ = self.run_case(events=[self.die(137)])
        self.assertEqual(result['outcome'], 'abnormal-exit-after-request')
        for events in ([], [self.die(0), self.die(0)], [self.die(0, Action='kill')],
                       [dict(self.die(0), Actor=dict(ID='f'*64, Attributes=dict(exitCode='0')))],
                       [dict(self.die(0), Actor=dict(ID=CID, Attributes=dict(exitCode='zero')))]):
            with self.subTest(events=events):
                result, _ = self.run_case(events=events)
                self.assertEqual(result['outcome'], 'exit-unverified-after-request')
                self.assertNotIn('container_exit_code', result['exit_reconciliation'])

    def test_mismatched_retained_container_never_falls_back_to_events(self):
        result, calls = self.run_case(inspect=dict(Id=CID, StartedAt='other', Running=False, ExitCode=0))
        self.assertEqual(result['outcome'], 'exit-unverified-after-request')
        self.assertEqual([c[1] for c in calls], ['inspect'])

    def test_libvirt_state_never_uses_direct_keys_or_events(self):
        # A libvirt run_id takes precedence; direct-only evidence cannot verify it.
        result, calls = self.run_case(state_changes=dict(libvirt_run_id=RUN))
        self.assertEqual(result['outcome'], 'exit-unverified-after-request')
        self.assertNotIn('direct_natural_verified', result['exit_reconciliation'])
        self.assertEqual([c[1] for c in calls], ['inspect'])
        self.assertIn('private completion unavailable or mismatched',
                      result['exit_reconciliation']['errors'])

    def test_state_without_capture_identity_keeps_legacy_classification(self):
        state_changes = dict(capture_manager=None)
        result, calls = self.run_case(state_changes=state_changes)
        self.assertEqual(result['outcome'], 'exit-unverified-after-request')
        self.assertEqual([c[1] for c in calls], ['inspect'])


if __name__ == '__main__':
    unittest.main()
