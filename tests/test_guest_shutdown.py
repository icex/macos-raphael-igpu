import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch


class GuestShutdownTests(unittest.TestCase):
    def module(self):
        path = Path(__file__).resolve().parents[1] / 'tools/guest-shutdown.py'
        self.assertTrue(path.exists(), 'missing revocable guest shutdown transport')
        spec = importlib.util.spec_from_file_location('guest_shutdown', path)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        return module

    def test_delayed_request_cannot_execute_with_wrong_permit_or_guest(self):
        module = self.module()
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

    def test_identity_response_is_bound_to_nonce_build_and_one_boot(self):
        module = self.module()
        nonce = 'a'*32
        boot = '4FC361A8-FE81-49C0-8317-3F85F2666225'
        output = f'noise\nRGPU_GUEST_ID {nonce} {boot} 24G830\n'
        self.assertEqual(module.parse_identity(output, nonce, '24G830'), boot)
        for bad in (output.replace(nonce, 'b'*32), output.replace('24G830', 'wrong'),
                    output+f'RGPU_GUEST_ID {nonce} {boot} 24G830\n'):
            with self.assertRaises(ValueError):
                module.parse_identity(bad, nonce, '24G830')

    def test_identity_command_runs_only_with_live_permit_and_expected_build(self):
        module = self.module()
        nonce = 'a'*32
        boot = '4FC361A8-FE81-49C0-8317-3F85F2666225'
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            scripts = {
                'curl': '#!/bin/sh\nprintf %s "$PERMIT"\n',
                'sysctl': '#!/bin/sh\nprintf %s "$GUEST_BOOT"\n',
                'sw_vers': '#!/bin/sh\nprintf %s "$GUEST_BUILD"\n',
            }
            for name, body in scripts.items():
                path = root/name; path.write_text(body); path.chmod(0o700)
            command = module.identity_command(nonce, '24G830')
            env = dict(os.environ, PATH=str(root)+os.pathsep+os.environ['PATH'],
                       PERMIT=nonce, GUEST_BOOT=boot, GUEST_BUILD='24G830')
            output = subprocess.check_output(['sh', '-c', command], env=env, text=True)
            self.assertEqual(module.parse_identity(output, nonce, '24G830'), boot)
            for key, value in [('PERMIT', 'revoked'), ('GUEST_BUILD', 'wrong')]:
                denied = dict(env, **{key:value})
                self.assertNotEqual(subprocess.run(['sh', '-c', command], env=denied).returncode, 0)

    def test_identify_revokes_permit_and_pending_command(self):
        module = self.module()
        boot = '4FC361A8-FE81-49C0-8317-3F85F2666225'
        with tempfile.TemporaryDirectory() as temp:
            vm = Path(temp); (vm/'run').mkdir()
            gx = vm/'gx'
            gx.write_text('#!/usr/bin/env python3\nimport re,sys\n'
                          'n=re.search(r"RGPU_GUEST_ID ([0-9a-f]{32})",sys.argv[1]).group(1)\n'
                          f'print("RGPU_GUEST_ID",n,"{boot}","24G830")\n')
            gx.chmod(0o700)
            self.assertEqual(module.identify(vm, '24G830', timeout=2), boot)
            self.assertEqual(list((vm/'run').glob('shutdown-permit-*')), [])
            self.assertFalse((vm/'run/cmd.txt').exists())

    def test_identify_accepts_relative_vm_directory(self):
        module = self.module()
        boot = '4FC361A8-FE81-49C0-8317-3F85F2666225'
        with tempfile.TemporaryDirectory() as temp:
            vm = Path(temp); (vm/'run').mkdir()
            gx = vm/'gx'
            gx.write_text('#!/usr/bin/env python3\nimport re,sys\n'
                          'n=re.search(r"RGPU_GUEST_ID ([0-9a-f]{32})",sys.argv[1]).group(1)\n'
                          f'print("RGPU_GUEST_ID",n,"{boot}","24G830")\n')
            gx.chmod(0o700)
            previous = Path.cwd()
            try:
                os.chdir(vm)
                self.assertEqual(module.identify(Path('.'), '24G830', timeout=2), boot)
            finally:
                os.chdir(previous)

    def test_shutdown_identifies_current_boot_before_requesting_poweroff(self):
        module = self.module()
        boot = '4FC361A8-FE81-49C0-8317-3F85F2666225'
        with tempfile.TemporaryDirectory() as temp:
            vm = Path(temp); (vm/'run').mkdir()
            state = {'cid':'c'*64, 'deadline_epoch':None}
            observed_commands = []
            def running(_state):
                pending = vm/'run/cmd.txt'
                if pending.exists():
                    observed_commands.append(pending.read_text())
                    return False
                return True
            supervisor = SimpleNamespace(same_start_running=running,
                                         verify=lambda state:None,
                                         stop_exact=lambda cid:self.fail('native exit must not force stop'))
            with patch.object(module, 'load_supervisor', return_value=supervisor), \
                 patch.object(module, 'identify', return_value=boot):
                result = module.shutdown(vm, state, expected_build='24G830', grace=2)
            self.assertEqual(result['outcome'], 'exited-after-guest-request')
            self.assertEqual(result['guest_boot_uuid'], boot)
            self.assertEqual(len(observed_commands), 1)
            self.assertIn(boot, observed_commands[0])
            self.assertEqual(list((vm/'run').glob('shutdown-permit-*')), [])


if __name__ == '__main__': unittest.main()
