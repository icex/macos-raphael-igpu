"""Host release integration with real handoff files and mocked external probes.

No Docker, libvirt daemon, capture process or GPU is started. These checks cover
the supervisor's release ordering and artifact bindings, not live cleanup.
"""
import copy
from contextlib import ExitStack
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tools' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


supervisor = load('release_supervisor_test', 'vm-supervision.py')
handoff = load('release_handoff_test', 'libvirt-console-handoff.py')


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.vm = Path(self.tmp.name)
        (self.vm / 'run').mkdir()
        modules = {}
        for name in handoff.MODULES:
            raw = (ROOT / 'tools' / name).read_bytes()
            (self.vm / name).write_bytes(raw)
            modules[name] = handoff.sha(raw)
        self.clock = 1000.0
        self.network = dict(name='fixture-lan', mac='52:54:00:00:00:01')
        manifest = dict(run_id='a' * 32,
                        boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                        image_id='sha256:' + 'b' * 64, max_seconds=120,
                        launch_options={'VM_MANAGER': 'libvirt'})
        self.directory, self.admission_digest = handoff.prepare(
            self.vm / 'run', manifest, json.dumps(manifest).encode(), self.network,
            modules, now=self.clock)
        self.admission = json.loads((self.directory / 'admission.json').read_text())
        self.paused = dict(run_id=manifest['run_id'], paused=True,
                           plan_sha256='c' * 64,
                           identity=dict(name='rgpu-' + manifest['run_id'],
                                         uuid='00000000-0000-0000-0000-000000000000',
                                         run_id=manifest['run_id'], pid=45, start_ticks=200),
                           scope=dict(kind='pid-namespace', inode=123, init_start_ticks=100),
                           domain_id=1, argv_sha256='d' * 64)
        handoff.write_once(self.directory / 'paused.json', self.paused)
        self.observed = copy.deepcopy(self.paused)
        self.state = dict(cid='e' * 64, started_at='2026-10-09T00:00:00Z',
                          deadline_epoch=1122)
        self.calls = []
        self.verify_count = 0
        self.fail_verify_at = None
        self.running_mutation = None
        self.time_after_inspection = None
        self.host_network = copy.deepcopy(self.network)
        self.host_image = manifest['image_id']
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.dict(os.environ, {
            'RGPU_LIBVIRT_RUN_ID': manifest['run_id'],
            'RGPU_LIBVIRT_ADMISSION_SHA256': self.admission_digest}))
        self.stack.enter_context(mock.patch.object(supervisor.time, 'time', side_effect=lambda: self.clock))
        self.stack.enter_context(mock.patch.object(supervisor, 'binary', side_effect=lambda x: '/fixture/' + x))
        self.stack.enter_context(mock.patch.object(supervisor, 'run', side_effect=self.external))
        self.stack.enter_context(mock.patch.object(supervisor, 'verify', side_effect=self.verify))
        # The supervisor dynamically imports the real network module. Replace
        # only its host probe after import; preserve actual handoff validation.
        original_exec = importlib.machinery.SourceFileLoader.exec_module
        def exec_module(loader, module):
            original_exec(loader, module)
            if module.__name__ == 'libvirt_network':
                module.capture_host = self.capture_host
        self.stack.enter_context(mock.patch.object(importlib.machinery.SourceFileLoader,
                                                  'exec_module', exec_module))

    def external(self, argv, **kwargs):
        self.assertFalse((self.directory / 'resume.json').exists())
        self.assertEqual(argv[0], '/fixture/docker')
        if argv[1] == 'inspect':
            self.assertEqual(argv[-1], self.state['cid'])
            self.calls.append('image')
            return self.host_image
        self.assertEqual(argv, ['/fixture/docker', 'exec', self.state['cid'],
                               'python3', '-B', '/run/rgpu-tools/libvirt-console-entry.py',
                               'inspect-paused'])
        self.assertGreater(kwargs['timeout'], 0)
        self.calls.append('independent-paused')
        if self.time_after_inspection is not None:
            self.clock = self.time_after_inspection
        return json.dumps(self.observed)

    def capture_host(self, name, mac):
        self.assertEqual((name, mac), (self.network['name'], self.network['mac']))
        self.assertFalse((self.directory / 'resume.json').exists())
        self.calls.append('network')
        return self.host_network

    def verify(self, state):
        self.assertIs(state, self.state)
        self.verify_count += 1
        self.calls.append('drains-and-timer')
        if self.verify_count == self.fail_verify_at:
            raise RuntimeError('capture drain unavailable')
        permit_path = self.directory / 'resume.json'
        if permit_path.exists() and not (self.directory / 'running.json').exists():
            permit = json.loads(permit_path.read_text())
            handoff.validate_permit(permit, self.admission, self.admission_digest, self.paused)
            running = dict(cid=permit['cid'], started_at=permit['started_at'],
                           run_id=self.paused['run_id'], identity=copy.deepcopy(self.paused['identity']),
                           scope=copy.deepcopy(self.paused['scope']),
                           plan_sha256=self.paused['plan_sha256'])
            if self.running_mutation:
                self.running_mutation(running)
            handoff.write_once(self.directory / 'running.json', running)

    def release(self):
        supervisor.release_libvirt(self.vm, self.state)

    def test_release_publishes_bound_permit_only_after_independent_checks(self):
        self.release()
        self.assertEqual(self.calls, ['drains-and-timer', 'image', 'independent-paused',
                                     'network', 'drains-and-timer', 'drains-and-timer'])
        permit = json.loads((self.directory / 'resume.json').read_text())
        self.assertEqual(permit['cid'], self.state['cid'])
        self.assertEqual(permit['started_at'], self.state['started_at'])
        self.assertEqual(permit['deadline_epoch'], self.admission['deadline_epoch'])
        self.assertEqual(self.state['libvirt_plan_sha256'], self.paused['plan_sha256'])
        self.assertEqual(self.state['libvirt_run_id'], self.paused['run_id'])

    def test_initial_capture_failure_prevents_even_independent_inspection(self):
        self.fail_verify_at = 1
        with self.assertRaisesRegex(RuntimeError, 'capture drain'):
            self.release()
        self.assertEqual(self.calls, ['drains-and-timer'])
        self.assertFalse((self.directory / 'resume.json').exists())

    def test_capture_loss_after_inspection_still_prevents_permit(self):
        self.fail_verify_at = 2
        with self.assertRaisesRegex(RuntimeError, 'capture drain'):
            self.release()
        self.assertIn('independent-paused', self.calls)
        self.assertFalse((self.directory / 'resume.json').exists())

    def test_replaced_paused_process_prevents_permit(self):
        self.observed['identity']['start_ticks'] += 1
        with self.assertRaisesRegex(ValueError, 'paused identity'):
            self.release()
        self.assertFalse((self.directory / 'resume.json').exists())

    def test_changed_host_network_prevents_permit(self):
        self.host_network['mac'] = '52:54:00:00:00:02'
        with self.assertRaisesRegex(RuntimeError, 'macvtap changed'):
            self.release()
        self.assertFalse((self.directory / 'resume.json').exists())

    def test_wrong_container_image_prevents_paused_inspection(self):
        self.host_image = 'sha256:' + 'f' * 64
        with self.assertRaisesRegex(RuntimeError, 'image differs'):
            self.release()
        self.assertNotIn('independent-paused', self.calls)
        self.assertFalse((self.directory / 'resume.json').exists())

    def test_expiration_during_inspection_prevents_permit(self):
        self.time_after_inspection = 1121
        with self.assertRaisesRegex(RuntimeError, 'handoff deadline'):
            self.release()
        self.assertFalse((self.directory / 'resume.json').exists())

    def test_shorter_handoff_budget_expires_before_admission_deadline(self):
        self.time_after_inspection = 1030
        self.assertLess(self.time_after_inspection, self.admission['deadline_epoch'])
        with self.assertRaisesRegex(RuntimeError, 'handoff deadline'):
            self.release()
        self.assertFalse((self.directory / 'resume.json').exists())

    def test_expired_admission_never_reaches_external_probes(self):
        self.clock = 1121
        with self.assertRaisesRegex(ValueError, 'deadline'):
            self.release()
        self.assertEqual(self.calls, [])
        self.assertFalse((self.directory / 'resume.json').exists())

    def test_changed_resumed_identity_does_not_mark_handoff_success(self):
        self.running_mutation = lambda record: record['identity'].update(start_ticks=999)
        with self.assertRaisesRegex(RuntimeError, 'resumed domain identity'):
            self.release()
        self.assertTrue((self.directory / 'resume.json').exists())
        self.assertNotIn('libvirt_run_id', self.state)


if __name__ == '__main__':
    unittest.main()
