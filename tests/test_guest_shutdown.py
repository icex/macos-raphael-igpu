import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class GuestShutdownTests(unittest.TestCase):
    def test_delayed_request_cannot_execute_with_wrong_permit_or_guest(self):
        path = Path(__file__).resolve().parents[1] / 'tools/guest-shutdown.py'
        self.assertTrue(path.exists(), 'missing revocable guest shutdown transport')
        spec = importlib.util.spec_from_file_location('guest_shutdown', path)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name, key in [('curl', 'PERMIT'), ('sysctl', 'GUEST_BOOT')]:
                p = root / name
                p.write_text('#!/bin/sh\nprintf %s "$'+key+'"\n'); p.chmod(0o700)
            nonce = 'a'*32; boot = 'B'*8+'-1111-2222-3333-'+'C'*12
            action = 'printf executed > marker'
            command = module.guarded_action(action, nonce, boot)
            for permit, observed_boot, expected in [(nonce, boot, True),
                    ('revoked', boot, False), (nonce, 'different-guest', False)]:
                (root / 'marker').unlink(missing_ok=True)
                subprocess.run(['sh', '-c', command], cwd=root, env=dict(os.environ,
                    PATH=str(root)+os.pathsep+os.environ['PATH'], PERMIT=permit,
                    GUEST_BOOT=observed_boot), check=False)
                self.assertEqual((root / 'marker').exists(), expected)


if __name__ == '__main__': unittest.main()
