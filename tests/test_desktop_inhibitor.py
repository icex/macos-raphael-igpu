import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DesktopInhibitorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        (self.base / 'run').mkdir()
        self.log = self.base / 'calls.jsonl'
        fake = self.base / 'docker'
        fake.write_text('#!' + sys.executable + '\n' + '''
import json, os, sys
with open(os.environ['CALLS'], 'a') as stream:
    stream.write(json.dumps(sys.argv[1:]) + '\\n')
sys.exit(1 if sys.argv[1] == os.environ.get('FAIL_STEP') else 0)
''')
        fake.chmod(0o755)
        self.pins = self.base / 'pins.json'
        self.pins.write_text(json.dumps(dict(vm_dir=str(self.base), inhibitor_container='test-inhibit')))
        self.env = dict(os.environ, PATH=str(self.base) + os.pathsep + os.environ['PATH'],
                        CALLS=str(self.log))
        self.command = [sys.executable, '-B', str(ROOT / 'tools/desktop-inhibitor.py'),
                        '--pins', str(self.pins), '--owner', 'test-owner']

    def calls(self):
        return [json.loads(row) for row in self.log.read_text().splitlines()]

    def test_success_and_failed_session_both_stop_container_and_keep_exit_code(self):
        for code in (0, 7):
            with self.subTest(code=code):
                self.log.unlink(missing_ok=True)
                result = subprocess.run(self.command + ['--', sys.executable, '-c',
                                                       f'raise SystemExit({code})'], env=self.env)
                self.assertEqual(result.returncode, code)
                self.assertEqual(self.calls(), [['update', '--restart=no', 'test-inhibit'],
                                                ['start', 'test-inhibit'],
                                                ['stop', '--timeout', '5', 'test-inhibit']])

    def test_partial_start_failure_stops_container_without_running_session(self):
        marker = self.base / 'started'
        result = subprocess.run(self.command + ['--', sys.executable, '-c',
                                f'open({str(marker)!r}, "w").close()'],
                                env=dict(self.env, FAIL_STEP='start'), capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(marker.exists())
        self.assertEqual(self.calls()[-1], ['stop', '--timeout', '5', 'test-inhibit'])

    def test_termination_releases_container_and_poststop_cleanup_is_idempotent(self):
        marker = self.base / 'started'
        child = subprocess.Popen(self.command + ['--', sys.executable, '-c',
                                 f'import time; open({str(marker)!r}, "w").close(); time.sleep(30)'],
                                 env=self.env)
        try:
            deadline = time.monotonic() + 5
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(marker.exists())
            child.send_signal(signal.SIGTERM)
            self.assertEqual(child.wait(timeout=5), 128 + signal.SIGTERM)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()
        self.assertEqual(self.calls()[-1], ['stop', '--timeout', '5', 'test-inhibit'])
        result = subprocess.run(self.command + ['--cleanup'], env=self.env)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.calls()[-2:], [['stop', '--timeout', '5', 'test-inhibit']] * 2)

    def test_concurrent_session_is_refused_and_stale_cleanup_cannot_stop_new_owner(self):
        import fcntl
        with (self.base / 'run/desktop-inhibitor.lock').open('a') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = subprocess.run(self.command + ['--', 'false'], env=self.env, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            stream.write('new-owner')
        result = subprocess.run(self.command + ['--cleanup'], env=self.env)
        self.assertEqual(result.returncode, 0)
        self.assertFalse(self.log.exists())

    def test_poststop_waits_for_original_cleanup_lock(self):
        import fcntl
        with (self.base / 'run/desktop-inhibitor.lock').open('a') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            stream.write('test-owner')
            stream.flush()
            cleanup = subprocess.Popen(self.command + ['--cleanup'], env=self.env)
            try:
                with self.assertRaises(subprocess.TimeoutExpired):
                    cleanup.wait(timeout=0.2)
                self.assertFalse(self.log.exists())
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)
                cleanup.wait(timeout=5)
        self.assertEqual(cleanup.returncode, 0)
        self.assertEqual(self.calls(), [['stop', '--timeout', '5', 'test-inhibit']])
