import importlib.util
import json
import os
import pathlib
import subprocess
import textwrap
import unittest
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]


def experiment():
    spec = importlib.util.spec_from_file_location('desktop_session_experiment', ROOT / 'tools/experiment.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DesktopSessionTests(unittest.TestCase):
    def test_installed_release_disables_startup_workload_only_for_desktop(self):
        m = experiment()
        card = json.loads((ROOT / 'experiments/metal-324.json').read_text())
        self.assertEqual(m.startup_workload(card), 'none')
        self.assertEqual(m.startup_workload({}), 'probe')
        for spec in ({'startup_workload': 'none'},
                     {'startup_workload': 'unknown', 'session': 'desktop'},
                     {'startup_workload': 'none', 'session': 'desktop',
                      'post_probe_debug': {'scenario': 'test'}}):
            with self.assertRaises(ValueError):
                m.startup_workload(spec)

    def test_desktop_without_tests_still_holds_session_and_quiesces_capture(self):
        m = experiment()
        manifest = {'spec': {'session': 'desktop', 'startup_workload': 'none'}}
        with patch.object(m, 'run_probe') as probe, \
             patch.object(m, 'write_once') as write, \
             patch.object(m, 'hold_interactive_session') as hold, \
             patch.object(m, 'post_probe_debug_contract', return_value=None), \
             patch.object(m, 'critical_replay_quiesce', return_value={'version': 1}), \
             patch.object(m, 'quiesce_critical_producer', return_value={'ack': True}) as quiesce:
            result = m.run_ready_session(None, manifest, {}, ROOT, None, None, None, 100)
        self.assertEqual(result, (None, {'ack': True}))
        probe.assert_not_called()
        write.assert_not_called()
        hold.assert_called_once()
        quiesce.assert_called_once()

    def test_unbounded_desktop_waits_past_old_limit_until_user_stop(self):
        m = experiment()
        card = json.loads((ROOT / 'experiments/metal-324.json').read_text())
        self.assertEqual(card['max_seconds'], 0)
        self.assertEqual(card['interactive_hold_seconds'], 0)
        self.assertTrue(m.unlimited_desktop(card))
        self.assertFalse(m.unlimited_desktop(dict(card, session='experiment')))
        self.assertFalse(m.unlimited_desktop(dict(card, startup_workload='probe')))
        with tempfile.TemporaryDirectory() as tmp:
            vm = pathlib.Path(tmp); (vm/'run').mkdir(); out = vm/'results'; out.mkdir()
            for name in ('serial.log', 'critical.log'):
                (vm/'run'/name).write_text('')
            supervisor = SimpleNamespace(verify=Mock())
            def stop_after_copy(_):
                (out/'stop-requested').touch()
            with patch.object(m.time, 'time', return_value=9999999999), \
                 patch.object(m.time, 'sleep', side_effect=stop_after_copy), \
                 patch.object(m, 'parse_manifest_captures', return_value=[]), \
                 patch.object(m, 'live_capture_state', return_value='ready'):
                m.hold_interactive_session(vm, {'spec': card, 'run_id': 'r'}, {}, out,
                                          supervisor, SimpleNamespace(error=None), None, 100)
            self.assertIsNone(json.loads((out/'interactive-ready.json').read_text())['deadline_epoch'])
            self.assertEqual(supervisor.verify.call_count, 2)

    def test_desktop_completion_does_not_claim_probe_success_or_mask_faults(self):
        m = experiment()
        manifest = {'spec': {'session': 'desktop', 'startup_workload': 'none'}}
        classifier = m.helper('classify-run')
        with patch.object(classifier, 'classify_probe_readiness',
                          return_value={'verdict': 'PROBE_NOT_RUN', 'valid': True}):
            result = classifier.classify(manifest, [], None)
        self.assertEqual(result['verdict'], 'DESKTOP_SESSION_COMPLETE')
        self.assertEqual(result['probe_status'], 'not-requested')
        with patch.object(classifier, 'classify_probe_readiness',
                          return_value={'verdict': 'GPU_FAULT', 'valid': True}):
            self.assertEqual(classifier.classify(manifest, [], None)['verdict'], 'GPU_FAULT')

    def test_only_desktop_cards_lift_the_experiment_session_limit(self):
        m = experiment()
        self.assertEqual(m.session_limit_seconds({}), 43200)
        self.assertEqual(m.session_limit_seconds({'session': 'experiment'}), 43200)
        self.assertEqual(m.session_limit_seconds({'session': 'desktop'}), m.DESKTOP_SESSION_SECONDS)
        # The supervisor deadline must stay a valid 32-bit epoch for the systemd timer.
        self.assertLess(1791800000 + m.DESKTOP_SESSION_SECONDS, 2 ** 31)

    def test_desktop_release_card_runs_until_shutdown_with_all_console_features(self):
        card = json.loads((ROOT / 'experiments/metal-274.json').read_text())
        m = experiment()
        self.assertEqual(card['session'], 'desktop')
        self.assertEqual(card['max_seconds'], m.DESKTOP_SESSION_SECONDS)
        self.assertEqual(card['interactive_hold_seconds'], m.DESKTOP_SESSION_SECONDS)
        options = card['launch_options']
        self.assertEqual((options['VM_CONSOLE'], options['CONSOLE_VDAGENT'], options['CONSOLE_USBREDIR'],
                          options['AUDIO']), ('igpu', 'on', 'on', 'usb'))


    def test_entry_guards_admit_the_direct_igpu_console_agent_and_usbredir(self):
        source = (ROOT / 'tools/vm-entry.sh').read_text()
        guards = source[source.index('case "${CONSOLE_VDAGENT:-off}"'):source.index('case "${CONSOLE_SNAPSHOT:-off}"')]
        base = dict(os.environ, VM_MANAGER='direct', VM_CONSOLE='igpu', GENERIC_GRAPHICS='off',
                    CONSOLE_VDAGENT='on', CONSOLE_USBREDIR='on')
        run = lambda env: subprocess.run(['bash', '-c', guards], env=env, capture_output=True, timeout=3)
        self.assertEqual(run(base).returncode, 0)
        for key, value in (('GENERIC_GRAPHICS', 'on'), ('VM_MANAGER', 'libvirt'), ('VM_CONSOLE', 'off')):
            self.assertNotEqual(run(dict(base, **{key: value})).returncode, 0, key)


    def test_usbredir_sockets_are_not_counted_as_serial_channels(self):
        # 481's first QEMU start failed its running identity: the serial-topology parser took
        # the usbredir Unix-socket chardevs for UARTs.
        source = (ROOT / 'tools/experiment.py').read_text()
        parser = source[source.index('  selected=[]'):source.index('  agent=[]')]
        args = [b'qemu', b'-chardev', b'socket,id=rgpu_console,path=/run/vm/serial.sock,server=on,wait=off',
                b'-device', b'isa-serial,chardev=rgpu_console,index=0',
                b'-chardev', b'socket,id=rgpu_usbredir0,path=/run/vm/usbredir-0.sock,server=on,wait=off',
                b'-device', b'usb-redir,id=rgpu_usbredir_dev0,chardev=rgpu_usbredir0,bus=xhci.0']
        scope = {'args': args}
        exec(textwrap.dedent(parser), scope)
        self.assertEqual(scope['selected'], [
            'socket,id=rgpu_console,path=/run/vm/serial.sock,server=on,wait=off',
            'isa-serial,chardev=rgpu_console,index=0'])


if __name__ == '__main__':
    unittest.main()
