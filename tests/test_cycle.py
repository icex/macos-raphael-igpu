"""Tests for tools/cycle.py -- the single change/test/run entry point.

The gates matter more than the happy path: a cycle must refuse to touch the GPU when the
device is not on vfio-pci, the inhibitor is absent, the worktree is dirty, the card or
identities are missing, or the regression suite fails.
"""
import argparse
import importlib.util
import json
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("cycle", ROOT / "tools" / "cycle.py")
cycle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cycle)


def make_args(**overrides):
    defaults = dict(candidate="231", card="metal-079", attempt=None, skip_tests=True,
                    allow_dirty=False, dry_run=True, worktree=None,
                    pins=str(ROOT / "experiments" / "pins.json"))
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class PinsTest(unittest.TestCase):
    def test_repository_pins_are_valid(self):
        pins = cycle.load_pins(ROOT / "experiments" / "pins.json")
        self.assertEqual(pins["schema"], 1)
        for key in ("vm_dir", "gpu_bdf", "image_id", "inhibitor_container", "lilu"):
            self.assertIn(key, pins)
        for key in ("bundle", "executable_sha256", "info_sha256", "build_manifest_sha256"):
            self.assertIn(key, pins["lilu"])
        self.assertTrue(pins["image_id"].startswith("sha256:"))

    def test_missing_key_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "pins.json"
            path.write_text(json.dumps({"vm_dir": "/tmp"}), encoding="utf-8")
            with self.assertRaises(cycle.CycleError):
                cycle.load_pins(path)

    def test_unreadable_pins_are_refused(self):
        with self.assertRaises(cycle.CycleError):
            cycle.load_pins(Path("/nonexistent/pins.json"))


class ResetNumberingTest(unittest.TestCase):
    def test_continues_the_existing_sequence(self):
        with tempfile.TemporaryDirectory() as temp:
            vm = Path(temp)
            (vm / "run").mkdir()
            for name in ("mode2-reset-1.json", "mode2-reset-7.json", "mode2-reset-x.json"):
                (vm / "run" / name).write_text("{}", encoding="utf-8")
            self.assertEqual(cycle.next_reset_index(vm), 8)

    def test_starts_at_one_when_empty(self):
        with tempfile.TemporaryDirectory() as temp:
            vm = Path(temp)
            (vm / "run").mkdir()
            self.assertEqual(cycle.next_reset_index(vm), 1)


class PreflightGateTest(unittest.TestCase):
    """Each gate must abort before any device access."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.vm = Path(self.temp.name) / "vm"
        (self.vm / "run").mkdir(parents=True)
        self.worktree = Path(self.temp.name) / "wt"
        (self.worktree / "experiments").mkdir(parents=True)
        (self.worktree / "experiments" / "metal-079.json").write_text("{}", encoding="utf-8")
        (self.vm / "run" / "candidate-231-build-identities.json").write_text("{}", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=self.worktree, check=True)
        subprocess.run(["git", "add", "-A"], cwd=self.worktree, check=True)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-q", "-m", "t"], cwd=self.worktree, check=True)
        self.pins = {"vm_dir": str(self.vm), "gpu_bdf": "0000:7b:00.0",
                     "image_id": "sha256:" + "0" * 64, "inhibitor_container": "rgpu-inhibit",
                     "lilu": {}}
        self.power = patch.object(cycle.Path, 'read_text', return_value='on')
        self.power.start()
        self.boot = patch.object(cycle, 'boot_id', return_value='test-boot')
        self.boot.start()
        self._driver = cycle.gpu_driver
        self._container = cycle.container_running
        cycle.gpu_driver = lambda bdf: "vfio-pci"
        cycle.container_running = lambda name: True

    def tearDown(self):
        cycle.gpu_driver = self._driver
        cycle.container_running = self._container
        self.power.stop()
        self.boot.stop()
        self.temp.cleanup()

    def test_passes_when_every_gate_holds(self):
        facts = cycle.preflight(make_args(), self.pins, self.worktree, self.vm)
        self.assertEqual(len(facts["commit"]), 40)
        self.assertEqual(len(facts["card_sha256"]), 64)
        self.assertEqual(len(facts["identities_sha256"]), 64)

    def test_refuses_unpinned_power_before_reset(self):
        with patch.object(cycle.Path, 'read_text', return_value='auto'):
            with self.assertRaisesRegex(cycle.CycleError, 'power/control'):
                cycle.preflight(make_args(), self.pins, self.worktree, self.vm)

    def test_used_boot_requires_explicit_reuse(self):
        ledger = self.vm / 'run/used-gpu-boots/test-boot.json'
        ledger.parent.mkdir()
        ledger.write_text('{}')
        with self.assertRaisesRegex(cycle.CycleError, 'boot_already_used'):
            cycle.preflight(make_args(), self.pins, self.worktree, self.vm)
        cycle.preflight(make_args(manual_reuse=True, ack_risk=True), self.pins, self.worktree, self.vm)

    def test_refuses_when_gpu_not_on_vfio(self):
        cycle.gpu_driver = lambda bdf: "amdgpu"
        with self.assertRaises(cycle.CycleError) as caught:
            cycle.preflight(make_args(), self.pins, self.worktree, self.vm)
        self.assertIn("vfio-pci", str(caught.exception))

    def test_refuses_when_inhibitor_absent(self):
        cycle.container_running = lambda name: False
        with self.assertRaises(cycle.CycleError) as caught:
            cycle.preflight(make_args(), self.pins, self.worktree, self.vm)
        self.assertIn("inhibitor", str(caught.exception))

    def test_refuses_dirty_worktree_unless_allowed(self):
        (self.worktree / "dirty.txt").write_text("x", encoding="utf-8")
        with self.assertRaises(cycle.CycleError):
            cycle.preflight(make_args(), self.pins, self.worktree, self.vm)
        facts = cycle.preflight(make_args(allow_dirty=True), self.pins, self.worktree, self.vm)
        self.assertEqual(len(facts["commit"]), 40)

    def test_refuses_missing_card(self):
        with self.assertRaises(cycle.CycleError) as caught:
            cycle.preflight(make_args(card="absent"), self.pins, self.worktree, self.vm)
        self.assertIn("card", str(caught.exception))

    def test_refuses_missing_identities(self):
        (self.vm / "run" / "candidate-231-build-identities.json").unlink()
        with self.assertRaises(cycle.CycleError) as caught:
            cycle.preflight(make_args(), self.pins, self.worktree, self.vm)
        self.assertIn("identities", str(caught.exception))

    def test_attempt_namespace_identities_are_preferred(self):
        scoped = self.vm / "run" / "candidate-231-attempt-retry1-build-identities.json"
        scoped.write_text('{"scoped": true}', encoding="utf-8")
        facts = cycle.preflight(make_args(attempt="retry1"), self.pins, self.worktree, self.vm)
        self.assertEqual(facts["identities"], str(scoped))


if __name__ == "__main__":
    unittest.main()


class CommandRegressionTest(unittest.TestCase):
    def test_attempt_keeps_candidate_version_pair(self):
        with tempfile.TemporaryDirectory() as temp:
            vm = Path(temp)
            (vm / 'run').mkdir()
            (vm / 'run/candidate231-attempt-retry1-qualification-run-id.txt').write_text('abc')
            pins = {'image_id': 'image', 'lilu': {'bundle': 'lilu',
                    'executable_sha256': 'exe', 'info_sha256': 'info',
                    'build_manifest_sha256': 'manifest'}}
            facts = dict(commit='commit', boot_id='boot', card_sha256='card',
                         identities_sha256='identities')
            with patch.object(cycle, 'run_step') as step:
                cycle.stage(make_args(attempt='retry1'), pins, facts, vm, vm)
            command = step.call_args.args[1]
            self.assertEqual(command[command.index('--candidate-version') + 1], '1.0.231')
            self.assertEqual(command[command.index('--attempt') + 1], 'retry1')

    def test_failed_run_is_not_a_successful_cycle(self):
        with patch.object(cycle, 'load_pins', return_value={'vm_dir': '/vm'}), \
             patch.object(cycle, 'preflight', return_value={'commit': 'c', 'boot_id': 'b'}), \
             patch.object(cycle, 'mode2_reset', return_value={}), \
             patch.object(cycle, 'stage', return_value='run'), \
             patch.object(cycle, 'prepare_and_run', return_value={
                 'verdict': {'verdict': 'INVALID', 'returncode': 0}, 'returncode': 0}), \
             patch('sys.argv', ['cycle', '--candidate', '231', '--card', 'metal-079']):
            self.assertNotEqual(cycle.main(), 0)


    def test_run_forwards_only_explicit_reuse_and_keeps_failure(self):
        for manual in (False, True):
            with self.subTest(manual=manual), tempfile.TemporaryDirectory() as temp:
                vm = Path(temp)
                completed = subprocess.CompletedProcess([], 7, '{"verdict":"WRAPPER_FAILURE"}\n', '')
                with patch.object(cycle, 'run_step', return_value=completed) as step:
                    result = cycle.prepare_and_run(
                        make_args(manual_reuse=manual, ack_risk=manual), {'image_id': 'sha256:pinned'}, vm, vm, 'run')
                for call in step.call_args_list:
                    self.assertEqual(call.kwargs['env'], {'IMAGE': 'sha256:pinned'})
                command = step.call_args.args[1]
                self.assertEqual('--manual-reuse' in command, manual)
                self.assertEqual('--ack-risk' in command, manual)
                self.assertEqual(result['returncode'], 7)

    def test_cli_rejects_incomplete_reuse_before_preflight(self):
        for flag in ('--manual-reuse', '--ack-risk'):
            with self.subTest(flag=flag), patch.object(cycle, 'preflight') as preflight, \
                 patch('sys.argv', ['cycle', '--candidate', '231', '--card', 'metal-079', flag]):
                with self.assertRaises(SystemExit) as caught:
                    cycle.main()
                self.assertEqual(caught.exception.code, 2)
                preflight.assert_not_called()
