import importlib.util
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load_tool():
    path = ROOT / 'tools/temporary-autologin.py'
    spec = importlib.util.spec_from_file_location('temporary_autologin', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TemporaryAutoLoginTests(unittest.TestCase):
    def test_secret_file_must_be_private_regular_non_symlink(self):
        tool = load_tool()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            secret = root / '.guestpw'
            secret.write_bytes(b'correct horse\n')
            secret.chmod(0o600)
            self.assertEqual(tool.read_secret(secret), bytearray(b'correct horse'))
            secret.chmod(0o640)
            with self.assertRaises(ValueError):
                tool.read_secret(secret)
            secret.chmod(0o600)
            link = root / 'link'
            link.symlink_to(secret)
            with self.assertRaises(ValueError):
                tool.read_secret(link)
            secret.write_bytes(b'')
            with self.assertRaises(ValueError):
                tool.read_secret(secret)
            secret.write_bytes(b'a\0b')
            with self.assertRaises(ValueError):
                tool.read_secret(secret)

    def test_container_identity_is_exact_supervised_full_cid(self):
        tool = load_tool()
        cid = 'a' * 64
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            (run / 'supervision.json').write_text(
                '{"cid":"'+cid+'","deadline_epoch":9999999999}')
            self.assertEqual(tool.supervised_cid(run, now=1), cid)
            (run / 'supervision.json').write_text('{"cid":"short"}')
            with self.assertRaises(ValueError):
                tool.supervised_cid(run, now=1)

    def test_arm_command_orders_recovery_before_mutation_and_has_no_secret(self):
        tool = load_tool()
        nonce = 'b' * 32
        command = tool.arm_command(nonce, 'testuser', 2000000000, 8890)
        self.assertIn('http://10.0.2.2:8890/secret/'+nonce, command)
        self.assertIn('/usr/bin/xcrun clang', command)
        self.assertIn('fdesetup status', command)
        self.assertIn('profiles status -type enrollment', command)
        self.assertIn('UniqueID', command)
        daemon = tool._daemon_plist(nonce, '/private/restore.sh')
        self.assertIn('StartInterval', daemon)
        self.assertIn('RunAtLoad', daemon)
        self.assertIn('killall cfprefsd', command)
        self.assertGreaterEqual(command.count('date +%s'), 2)
        self.assertIn('metal-permit-'+nonce, command)
        self.assertIn('/bin/bash -o pipefail', command)
        self.assertIn("find /var/db -maxdepth 1 -name 'rgpu-autologin-*'", command)
        self.assertIn('test ! -L /etc/kcpassword', command)
        self.assertLess(command.index('launchctl bootstrap system'),
                        command.index('defaults write /Library/Preferences/com.apple.loginwindow'))
        self.assertLess(command.index('curl -fsS'),
                        command.index('defaults write /Library/Preferences/com.apple.loginwindow'))
        self.assertNotIn('correct horse', command)
        self.assertNotIn('kcpassword_sha', command)

    def test_restore_script_preserves_failed_recovery_artifacts(self):
        tool = load_tool()
        script = tool.restore_script('c' * 32, 2000000000)
        self.assertIn('cmp -s', script)
        self.assertIn('RESTORE_FAILED', script)
        self.assertIn('restore.lock', script)
        self.assertIn('RESTORED', script)
        self.assertIn('exit 1', script)
        self.assertNotIn('rm -rf "$state"', script)
        self.assertIn('killall cfprefsd', script)

    def test_one_shot_server_is_path_bound_single_use_and_silent(self):
        tool = load_tool()
        source = tool.ONE_SHOT_SERVER
        self.assertIn('self.path != "/secret/" + token', source)
        self.assertIn('handle_request()', source)
        self.assertIn('os.getpid()', source)
        self.assertNotIn('serve_forever', source)
        self.assertIn('def log_message', source)
        self.assertIn('Content-Length', source)
        argv = tool.secret_server_argv('d' * 64)
        self.assertEqual(argv[:3], ['docker', 'exec', '-i'])
        self.assertEqual(argv[3], 'd' * 64)
        self.assertNotIn('password', ' '.join(argv).lower())

    def test_encoder_uses_undocumented_twelve_byte_padding(self):
        tool = load_tool()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, binary, output = root/'encoder.c', root/'encoder', root/'encoded'
            source.write_text(tool.ENCODER_C)
            subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', str(source), '-o', str(binary)],
                           check=True, capture_output=True)
            subprocess.run([str(binary), str(output)], input=b'a', check=True,
                           capture_output=True)
            self.assertEqual(output.read_bytes(), bytes.fromhex(
                '1c895223d2bcddeaa3b91f7d'))
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
            for length, expected_size in ((12, 24), (24, 36)):
                boundary = root/f'encoded-{length}'
                subprocess.run([str(binary), str(boundary)], input=b'x'*length, check=True,
                               capture_output=True)
                encoded = boundary.read_bytes()
                self.assertEqual(len(encoded), expected_size)
                key = bytes.fromhex('7d895223d2bcddeaa3b91f')
                decoded = bytes(value ^ key[i % len(key)] for i, value in enumerate(encoded))
                self.assertEqual(decoded[:length], b'x'*length)
                self.assertEqual(decoded[length:], b'\0'*(expected_size-length))

    def test_receipt_requires_fixed_non_secret_schema(self):
        tool = load_tool()
        nonce = 'e' * 32
        output = ('RGPU_AUTOLOGIN {"schema":1,"nonce":"'+nonce+'",'
                  '"action":"armed","account":"testuser","uid":501,'
                  '"recovery_installed":true,"restoration_verified":false}\n'
                  'RGPU_EXIT '+nonce+' 0\n')
        self.assertEqual(tool.validate_receipt(output, nonce, 'armed')['uid'], 501)
        with self.assertRaises(ValueError):
            tool.validate_receipt(output.replace('"schema":1', '"schema":2'), nonce, 'armed')
        with self.assertRaises(ValueError):
            tool.validate_receipt(output + 'RGPU_EXIT '+nonce+' 0\n', nonce, 'armed')
        with self.assertRaises(ValueError):
            tool.validate_receipt(output.replace('"recovery_installed":true',
                                                 '"recovery_installed":false'), nonce, 'armed')


if __name__ == '__main__':
    unittest.main()
