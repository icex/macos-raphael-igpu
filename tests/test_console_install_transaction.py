import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('console_transaction', ROOT/'tools/console-install-transaction.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PowerLoss(BaseException):
    pass


class InstallationTests(unittest.TestCase):
    def setUp(self):
        # Real owner-only ancestors, same condition as /Users/name in the guest.
        self.directory = tempfile.TemporaryDirectory(dir=ROOT.parent, prefix='candidate-installer-test-')
        self.home = Path(self.directory.name)
        self.tx = module.Transaction(self.home, active=lambda app: None)
        self.fd = self.tx.lock()

    def tearDown(self):
        os.close(self.fd)
        self.directory.cleanup()

    def build(self, stage):
        (stage/'Raphael Console.app/Contents').mkdir(parents=True)
        (stage/'Raphael Console.app/Contents/program').write_bytes(b'new program')
        (stage/'support').mkdir()
        (stage/'support/start-console.sh').write_bytes(b'new launcher')
        (stage/'support/build-provenance.json').write_bytes(b'new provenance')
        (stage/'agent.plist').write_bytes(b'new agent')

    def seed(self):
        self.tx.app.mkdir()
        (self.tx.app/'old').write_bytes(b'old app')
        for target in self.tx.targets[1:]:
            target.write_bytes(b'old '+target.name.encode())
        (self.tx.support/'presenter.log').write_bytes(b'keep logs')
        return [module.digest(p) for p in self.tx.targets]

    def test_success_preserves_unrelated_logs_and_has_build_before_publish(self):
        before = self.seed()
        def checked_build(stage):
            self.assertEqual([module.digest(p) for p in self.tx.targets], before)
            self.build(stage)
        stage = self.tx.install(checked_build)
        self.assertFalse(self.tx.journal.exists())
        self.assertTrue((stage/'result.json').is_file())
        self.assertEqual((self.tx.app/'Contents/program').read_bytes(), b'new program')
        self.assertEqual((self.tx.support/'presenter.log').read_bytes(), b'keep logs')
        self.assertEqual([module.digest(stage/('old-%d'%i)) for i in range(4)], before)

    def test_build_error_does_not_replace_installed_files(self):
        before = self.seed()
        def fail(stage):
            self.build(stage)
            raise RuntimeError('compiler failure')
        with self.assertRaisesRegex(RuntimeError, 'compiler failure'):
            self.tx.install(fail)
        self.assertEqual([module.digest(p) for p in self.tx.targets], before)
        self.assertFalse(self.tx.journal.exists())

    def test_interruption_after_every_publication_rename_restores_old_install(self):
        before = self.seed()
        real_rename = module.rename
        for crash_after in range(1, 9):
            with self.subTest(crash_after=crash_after):
                calls = 0
                def interrupted(source, target):
                    nonlocal calls
                    real_rename(source, target)
                    if self.tx.journal.exists():
                        calls += 1
                        if calls == crash_after:
                            raise PowerLoss()
                with patch.object(module, 'rename', interrupted), self.assertRaises(PowerLoss):
                    self.tx.install(self.build)
                self.assertTrue(self.tx.journal.exists())
                with self.assertRaisesRegex(RuntimeError, 'Pending transaction'):
                    self.tx.install(self.build)
                self.tx.recover()
                self.assertEqual([module.digest(p) for p in self.tx.targets], before)

    def test_new_install_interruption_recovers_absence(self):
        real_rename = module.rename
        def interrupted(source, target):
            real_rename(source, target)
            if self.tx.journal.exists():
                raise PowerLoss()
        with patch.object(module, 'rename', interrupted), self.assertRaises(PowerLoss):
            self.tx.install(self.build)
        self.tx.recover()
        self.assertEqual([module.digest(p) for p in self.tx.targets], [None]*4)

    def test_concurrent_edit_refuses_recovery_before_any_restoration(self):
        self.seed()
        real_finish = self.tx.finish
        with patch.object(self.tx, 'finish', side_effect=PowerLoss), self.assertRaises(PowerLoss):
            self.tx.install(self.build)
        (self.tx.app/'Contents/program').write_bytes(b'user changed this')
        current = [module.digest(p) for p in self.tx.targets]
        with self.assertRaisesRegex(RuntimeError, 'Concurrent change'):
            self.tx.recover()
        self.assertEqual([module.digest(p) for p in self.tx.targets], current)
        self.assertTrue(self.tx.journal.exists())

    def test_running_session_refused_before_build(self):
        self.seed()
        self.tx.active = lambda app: (_ for _ in ()).throw(RuntimeError('active'))
        with self.assertRaisesRegex(RuntimeError, 'active'):
            self.tx.install(lambda stage: self.fail('build must not run'))

    def test_final_recheck_refuses_session_started_during_build(self):
        before = self.seed()
        def build(stage):
            self.build(stage)
            self.tx.active = lambda app: (_ for _ in ()).throw(RuntimeError('became active'))
        with self.assertRaisesRegex(RuntimeError, 'became active'):
            self.tx.install(build)
        self.assertEqual([module.digest(p) for p in self.tx.targets], before)

    def test_second_installer_cannot_take_live_lock(self):
        with self.assertRaises(BlockingIOError):
            self.tx.lock()

    def test_symlink_destination_and_ancestor_refused(self):
        self.tx.app.symlink_to(self.home/'outside')
        with self.assertRaisesRegex(RuntimeError, 'unsupported'):
            self.tx.install(self.build)
        self.tx.app.unlink()
        other = self.home/'other';other.mkdir()
        self.tx.support.rmdir();self.tx.support.symlink_to(other)
        with self.assertRaisesRegex(RuntimeError, 'real directory'):
            self.tx.lock()

    def test_no_replace_rename_never_clobbers_raced_destination(self):
        source = self.home/'source';target = self.home/'target'
        source.write_bytes(b'ours');target.write_bytes(b'concurrent user data')
        with self.assertRaises(FileExistsError):
            module.rename(source, target)
        self.assertEqual(target.read_bytes(), b'concurrent user data')
        self.assertEqual(source.read_bytes(), b'ours')

    def test_publication_error_automatically_restores(self):
        before = self.seed()
        real = module.rename
        failed = False
        def fail_once(source, target):
            nonlocal failed
            if Path(target) == self.tx.targets[1] and not failed:
                failed = True
                raise OSError('simulated write failure')
            real(source, target)
        with patch.object(module, 'rename', fail_once), self.assertRaisesRegex(OSError, 'simulated'):
            self.tx.install(self.build)
        self.assertEqual([module.digest(p) for p in self.tx.targets], before)
        self.assertFalse(self.tx.journal.exists())

    def test_recovery_itself_can_resume_after_interruption(self):
        before = self.seed()
        with patch.object(self.tx, 'finish', side_effect=PowerLoss), self.assertRaises(PowerLoss):
            self.tx.install(self.build)
        real = module.rename
        def interrupted(source, target):
            real(source, target)
            raise PowerLoss()
        with patch.object(module, 'rename', interrupted), self.assertRaises(PowerLoss):
            self.tx.recover()
        self.tx.recover()
        self.assertEqual([module.digest(p) for p in self.tx.targets], before)

    def test_missing_stage_is_not_recreated(self):
        with patch.object(self.tx, 'finish', side_effect=PowerLoss), self.assertRaises(PowerLoss):
            self.tx.install(self.build)
        import json
        value = json.loads(self.tx.journal.read_text())
        missing = self.tx.app.parent/'.raphael-install-missing'
        value['stage'] = str(missing)
        self.tx.journal.write_text(json.dumps(value))
        with self.assertRaisesRegex(RuntimeError, 'staging directory'):
            self.tx.recover()
        self.assertFalse(missing.exists())

    def test_launchctl_observer_error_is_not_absence(self):
        import subprocess
        with patch.object(module.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', 'permission denied')):
            with self.assertRaisesRegex(RuntimeError, 'Cannot establish'):
                module.refuse_active(self.tx.app)

    def test_relative_helper_command_is_active(self):
        import subprocess
        absent = subprocess.CompletedProcess([], 113, '', 'Could not find service "org.raphaelgpu.console" in domain')
        with patch.object(module.subprocess, 'run', return_value=absent), patch.object(module.subprocess, 'check_output', return_value='./console-presenter auto 60 6000'):
            with self.assertRaisesRegex(RuntimeError, 'helper is running'):
                module.refuse_active(self.tx.app)

    def test_source_replaced_between_check_and_rename_is_preserved(self):
        source=self.home/'source';target=self.home/'destination'
        source.write_bytes(b'expected')
        expected=module.digest(source)
        real=module.rename
        changed=False
        def raced(a,b):
            nonlocal changed
            if not changed:
                changed=True
                Path(a).write_bytes(b'concurrent edit')
            real(a,b)
        with patch.object(module,'rename',raced), self.assertRaisesRegex(RuntimeError,'during rename'):
            module.move_verified(source,target,expected)
        self.assertEqual(source.read_bytes(),b'concurrent edit')
        self.assertFalse(target.exists())
