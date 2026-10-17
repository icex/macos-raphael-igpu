import contextlib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load_tool():
    path = ROOT / 'tools/gui183-recovery-once.py'
    spec = importlib.util.spec_from_file_location('gui183_recovery_once', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Gui183RecoveryOnceTests(unittest.TestCase):
    @contextlib.contextmanager
    def frozen_source_tree(self, tool):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative in tool.SOURCES:
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                source = (ROOT / 'tests/fixtures/gui183-pinned-experiment.py'
                          if relative == 'tools/experiment.py' else ROOT / relative)
                data = source.read_bytes()
                self.assertEqual(hashlib.sha256(data).hexdigest(),
                                 tool.SOURCES[relative], relative)
                target.write_bytes(data)
            original = tool.ROOT
            original_validate = tool.validate_sources
            tool.ROOT = root
            tool.validate_sources = lambda: original_validate(root)
            try:
                yield
            finally:
                tool.ROOT = original
                tool.validate_sources = original_validate

    def test_execute_once_writes_attempt_before_callback_and_result(self):
        tool = load_tool()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            proof = directory / 'proof.json'; proof.write_text('{}\n')
            digest = hashlib.sha256(proof.read_bytes()).hexdigest()
            entered = []
            @contextlib.contextmanager
            def preflight():
                entered.append('gate'); yield
            def recover():
                self.assertTrue((directory / 'attempt.json').exists())
                entered.append('recover')
                return {'receipt': {'status': 'recovered'}, 'receipt_sha256': 'a' * 64}
            result = tool.execute_once(directory, proof, digest, preflight, recover,
                                       'attempt.json', 'result.json')
            self.assertEqual(entered, ['gate', 'recover'])
            self.assertEqual(result['status'], 'complete')

    def test_callback_exception_is_durable_and_never_retried(self):
        tool = load_tool()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            proof = directory / 'proof.json'; proof.write_text('{}\n')
            digest = hashlib.sha256(proof.read_bytes()).hexdigest()
            @contextlib.contextmanager
            def preflight(): yield
            result = tool.execute_once(directory, proof, digest, preflight,
                                       lambda: (_ for _ in ()).throw(RuntimeError('boom')),
                                       'attempt.json', 'result.json')
            self.assertEqual(result['status'], 'failed')
            self.assertIn('RuntimeError: boom', result['error'])
            with self.assertRaises(FileExistsError):
                tool.execute_once(directory, proof, digest, preflight, lambda: None,
                                  'attempt.json', 'result.json')

    def test_wrong_hash_and_existing_files_refuse_before_preflight(self):
        tool = load_tool()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            proof = directory / 'proof.json'; proof.write_text('{}\n')
            entered = []
            @contextlib.contextmanager
            def preflight(): entered.append(True); yield
            with self.assertRaisesRegex(ValueError, 'reviewed proof'):
                tool.execute_once(directory, proof, '0' * 64, preflight, lambda: None)
            (directory / 'gui183-recovery-result.json').write_text('{}\n')
            digest = hashlib.sha256(proof.read_bytes()).hexdigest()
            with self.assertRaises(FileExistsError):
                tool.execute_once(directory, proof, digest, preflight, lambda: None)
            self.assertEqual(entered, [])

    def test_preflight_rejects_wrong_boot_active_guest_pending_and_locks(self):
        tool = load_tool()
        class FakeExperiment:
            @staticmethod
            def host_snapshot(): return {'boot_id': tool.BOOT_ID, 'active_vm': False}
        with tempfile.TemporaryDirectory() as temporary:
            vm = Path(temporary); (vm / 'run/launch-pending').mkdir(parents=True)
            with tool.live_preflight(vm, FakeExperiment()): pass
            FakeExperiment.host_snapshot = staticmethod(
                lambda: {'boot_id': 'wrong', 'active_vm': False})
            with self.assertRaisesRegex(ValueError, 'boot'):
                with tool.live_preflight(vm, FakeExperiment()): pass
            FakeExperiment.host_snapshot = staticmethod(
                lambda: {'boot_id': tool.BOOT_ID, 'active_vm': True})
            with self.assertRaisesRegex(ValueError, 'active'):
                with tool.live_preflight(vm, FakeExperiment()): pass
            FakeExperiment.host_snapshot = staticmethod(
                lambda: {'boot_id': tool.BOOT_ID, 'active_vm': False})
            (vm / 'run/launch-pending/x').write_text('x')
            with self.assertRaisesRegex(ValueError, 'pending'):
                with tool.live_preflight(vm, FakeExperiment()): pass
            (vm / 'run/launch-pending/x').unlink()
            locker = ('import fcntl,sys,time; f=open(sys.argv[1],"a"); '
                      'fcntl.flock(f,fcntl.LOCK_EX); print("ready",flush=True); time.sleep(5)')
            for name in ('experiment.lock', 'redeploy.lock'):
                process = subprocess.Popen(
                    [sys.executable, '-c', locker, str(vm / 'run' / name)],
                    stdout=subprocess.PIPE, text=True)
                try:
                    self.assertEqual(process.stdout.readline().strip(), 'ready')
                    with self.assertRaises(BlockingIOError):
                        with tool.live_preflight(vm, FakeExperiment()): pass
                finally:
                    process.terminate(); process.wait(timeout=2); process.stdout.close()

    def test_actual_proof_rebuild_is_read_only_and_exact(self):
        tool = load_tool()
        vm = Path(os.environ.get('RGPU_VM_DIR', Path.home() / 'macos-vm'))
        run = vm / 'run/metal-016-183-gui-73ad3355'
        if not run.exists(): self.skipTest('frozen GUI run unavailable')
        before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in run.iterdir() if p.is_file()}
        with self.frozen_source_tree(tool):
            derived, proof = tool.validate_reviewed_proof(vm)
        after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in run.iterdir() if p.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(hashlib.sha256(derived).hexdigest(), tool.DERIVED_SHA256)
        self.assertEqual(proof['run_id'], tool.RUN_ID)

    def test_source_validation_rejects_helper_drift(self):
        tool = load_tool()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); (root / 'tools').mkdir()
            for relative in tool.SOURCES:
                target = root / relative; target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b'wrong')
            with self.assertRaisesRegex(ValueError, 'SHA-256'):
                tool.validate_sources(root)

    def test_current_experiment_source_is_rejected_by_frozen_runner(self):
        tool = load_tool()
        with self.assertRaisesRegex(ValueError, 'tools/experiment.py SHA-256 mismatch'):
            tool.validate_sources(ROOT)

    def test_missing_reviewed_proof_refuses(self):
        tool = load_tool()
        with tempfile.TemporaryDirectory() as temporary:
            vm = Path(temporary); (vm / 'run/metal-016-183-gui-73ad3355').mkdir(parents=True)
            with self.frozen_source_tree(tool):
                with self.assertRaises(FileNotFoundError):
                    tool.validate_reviewed_proof(vm)

    def test_canonical_receipt_requires_exact_json_and_hashes_bytes(self):
        tool = load_tool()
        with tempfile.TemporaryDirectory() as temporary:
            vm = Path(temporary)
            path = vm / 'run/vfio-recovery' / tool.BOOT_ID / (tool.RUN_ID + '.json')
            path.parent.mkdir(parents=True)
            receipt = {'status': 'recovered', 'recovery_id': 'a' * 32}
            path.write_text(json.dumps(receipt, sort_keys=True) + '\n')
            proof = {'artifact_sha256': {'serial.txt': 'b' * 64}}
            result = tool.canonical_receipt(vm, receipt, {'snapshot': 1}, proof)
            self.assertEqual(result['receipt_sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
            with self.assertRaisesRegex(ValueError, 'canonical recovery receipt'):
                tool.canonical_receipt(vm, {'status': 'different'}, {}, proof)


if __name__ == '__main__': unittest.main()
