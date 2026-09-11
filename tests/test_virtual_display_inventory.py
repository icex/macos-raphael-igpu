import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def load_tool():
    path = ROOT / 'tools/virtual-display-inventory.py'
    spec = importlib.util.spec_from_file_location('virtual_display_inventory', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class VirtualDisplayInventoryTests(unittest.TestCase):
    def valid(self):
        return {
            'schema': 1, 'nonce': 'a' * 32, 'os_build': '24G830',
            'console_uid': 0, 'console_user': 'loginwindow',
            'window_server_running': True, 'screen_capture_preflight': False,
            'classes': {name: True for name in load_tool().REQUIRED_CLASSES},
            'selectors': {name: True for name in load_tool().REQUIRED_SELECTORS},
            'screen_capture_kit': {'class': True, 'selector': True},
            'online_displays': [], 'display_list_error': 0,
        }

    def test_accepts_inventory_without_desktop_or_capture_permission(self):
        tool = load_tool()
        result = self.valid()
        output = 'RGPU_VDISPLAY_INVENTORY ' + json.dumps(result) + '\nRGPU_EXIT ' + 'a'*32 + ' 0\n'
        accepted = tool.validate_output(output, 'a' * 32)
        self.assertEqual(accepted['stage2_blockers'], [])
        self.assertEqual(accepted['capture_blockers'], [
            'console_session_unavailable', 'screen_capture_permission_absent'])

    def test_rejects_nonce_schema_spi_and_transport_mismatch(self):
        tool = load_tool()
        for label, mutate in (
            ('nonce', lambda row: row.update(nonce='b' * 32)),
            ('schema', lambda row: row.update(schema=2)),
            ('class', lambda row: row['classes'].update(CGVirtualDisplay='yes')),
            ('selector', lambda row: row['selectors'].update(applySettings_=1)),
            ('display-schema', lambda row: row.update(online_displays=[{'id': 1}])),
        ):
            with self.subTest(label=label):
                row = self.valid(); mutate(row)
                output = ('RGPU_VDISPLAY_INVENTORY ' + json.dumps(row) + '\n' +
                          'RGPU_EXIT ' + 'a'*32 + ' 0\n')
                with self.assertRaises(ValueError):
                    tool.validate_output(output, 'a' * 32)
        row = self.valid()
        with self.assertRaises(ValueError):
            tool.validate_output('RGPU_VDISPLAY_INVENTORY '+json.dumps(row)+'\n', 'a'*32)
        with self.assertRaises(ValueError):
            tool.validate_output('RGPU_VDISPLAY_INVENTORY '+json.dumps(row)+'\n' +
                                 'RGPU_EXIT '+'a'*32+' 124\n', 'a'*32)

    def test_records_spi_and_display_query_failures_as_stage2_blockers(self):
        tool = load_tool()
        row = self.valid()
        row['classes']['CGVirtualDisplay'] = False
        row['selectors']['applySettings_'] = False
        row['display_list_error'] = 1001
        output = ('RGPU_VDISPLAY_INVENTORY ' + json.dumps(row) + '\n' +
                  'RGPU_EXIT ' + 'a'*32 + ' 0\n')
        self.assertEqual(tool.validate_output(output, 'a'*32)['stage2_blockers'], [
            'virtual_display_spi_incomplete', 'online_display_list_unavailable'])

    def test_guest_command_is_bounded_inventory_only_and_self_cleaning(self):
        tool = load_tool()
        command = tool.guest_command('a' * 32, b'objective-c source', 1234567890)
        self.assertIn('/usr/bin/xcrun clang', command)
        self.assertIn('-framework CoreGraphics', command)
        self.assertIn('-framework SystemConfiguration', command)
        self.assertIn('trap cleanup EXIT HUP INT TERM', command)
        self.assertIn('metal-permit-' + 'a'*32, command)
        self.assertNotIn('CGRequestScreenCaptureAccess', command)
        self.assertNotIn('CGVirtualDisplay alloc', command)
        self.assertNotIn('sudo', command)
        source = (ROOT / 'tests/virtual_display_inventory.m').read_text()
        self.assertNotIn('CGRequestScreenCaptureAccess', source)
        self.assertNotIn('@(NSClassFromString(name) != Nil)', source)
        self.assertNotIn('@(owner && class_getInstanceMethod', source)
        self.assertNotIn('@(shareable != Nil)', source)
        self.assertNotIn('@(shareable && [shareable respondsToSelector:', source)

    def test_runner_persists_identity_and_timeout_error(self):
        tool = load_tool()

        class TimedOutTransport:
            @staticmethod
            def run_guest_command(*args, **kwargs):
                raise subprocess.TimeoutExpired('gx', 42)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            vm, output = root / 'vm', root / 'evidence'
            (vm / 'run').mkdir(parents=True)
            (vm / 'gx').write_text('fixture')
            argv = ['virtual-display-inventory.py', '--vm-dir', str(vm),
                    '--output', str(output)]
            with mock.patch.object(tool, '_metal_test', return_value=TimedOutTransport), \
                    mock.patch.object(sys, 'argv', argv), \
                    self.assertRaises(subprocess.TimeoutExpired):
                tool.main()
            self.assertTrue((output / 'identity.json').is_file())
            error = json.loads((output / 'error.json').read_text())
            self.assertEqual(error['type'], 'TimeoutExpired')
            self.assertFalse((output / 'inventory.json').exists())

    def test_accepts_one_complete_create_remove_lifecycle(self):
        tool = load_tool()
        row = {
            'schema': 1, 'nonce': 'b'*32, 'abi_valid': True,
            'session': {'user_id': 0, 'user_name': None, 'login_done': False,
                        'on_console': False, 'console_set': None},
            'method_encodings': {'display_init': '@@:@', 'mode_init': '@@:IId',
                                 'serial_num': 'v@:I', 'serial_number': 'v@:I',
                                 'hi_dpi': 'v@:I', 'rotation': 'v@:I'},
            'baseline_ids': [],
            'created': True, 'display_id': 17, 'settings_applied': True,
            'added': True, 'active': True, 'width': 1280, 'height': 720,
            'refresh': 60.0, 'retained_milliseconds': 1000,
            'removed': True, 'termination_called': True, 'final_ids': [],
            'cleanup_complete': True,
        }
        output = ('RGPU_VDISPLAY_CREATE ' + json.dumps(row) + '\n' +
                  'RGPU_EXIT ' + 'b'*32 + ' 0\n')
        self.assertEqual(tool.validate_create_output(output, 'b'*32), row)

    def test_rejects_create_remove_nonce_state_and_timeout(self):
        tool = load_tool()
        base = {
            'schema': 1, 'nonce': 'b'*32, 'abi_valid': True,
            'session': {'user_id': 0, 'user_name': None, 'login_done': False,
                        'on_console': False, 'console_set': None},
            'method_encodings': {'display_init': '@@:@', 'mode_init': '@@:IId',
                                 'serial_num': 'v@:I', 'serial_number': 'v@:I',
                                 'hi_dpi': 'v@:I', 'rotation': 'v@:I'},
            'baseline_ids': [],
            'created': True, 'display_id': 17, 'settings_applied': True,
            'added': True, 'active': True, 'width': 1280, 'height': 720,
            'refresh': 60.0, 'retained_milliseconds': 1000,
            'removed': True, 'termination_called': True, 'final_ids': [],
            'cleanup_complete': True,
        }
        for label, mutation in (
            ('nonce', {'nonce': 'c'*32}), ('abi', {'abi_valid': False}),
            ('baseline', {'baseline_ids': [1]}),
            ('mode', {'width': 1279}), ('remove', {'removed': False}),
            ('cleanup', {'cleanup_complete': False})):
            with self.subTest(label=label):
                row = dict(base, **mutation)
                output = ('RGPU_VDISPLAY_CREATE '+json.dumps(row)+'\n' +
                          'RGPU_EXIT '+'b'*32+' 0\n')
                with self.assertRaises(ValueError):
                    tool.validate_create_output(output, 'b'*32)
        output = ('RGPU_VDISPLAY_CREATE '+json.dumps(base)+'\n' +
                  'RGPU_EXIT '+'b'*32+' 124\n')
        with self.assertRaises(ValueError):
            tool.validate_create_output(output, 'b'*32)

    def test_create_command_is_explicit_and_inventory_remains_default(self):
        tool = load_tool()
        inventory = tool.guest_command('a'*32, b'source', 1234567890)
        create = tool.guest_command('b'*32, b'source', 1234567890,
                                    action='create-remove')
        self.assertIn('"$dir/inventory" '+('a'*32)+' inventory', inventory)
        self.assertIn('"$dir/inventory" '+('b'*32)+' create-remove', create)
        self.assertIn('/usr/bin/log show --start "$log_start" --end "$log_end"', create)
        self.assertIn('RGPU_VDISPLAY_LOG '+('b'*32), create)
        self.assertIn('&& ( log_start=', create)

    def test_logged_command_preserves_receipt_exit_and_caps_log(self):
        tool = load_tool()
        nonce = 'b' * 32
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            body = tool.bounded_logged_command(
                "/bin/sh -c '/usr/bin/printf PRODUCER_RECEIPT; exit 7'",
                nonce, "/usr/bin/printf '%070000d' 0")
            command = (f'dir={directory}; {body}; result=$?; '
                       f'printf "\\nRGPU_EXIT {nonce} %s\\n" "$result"')
            result = subprocess.run(['/bin/sh', '-c', command], text=True,
                                    capture_output=True, timeout=10, check=True)
            self.assertIn('PRODUCER_RECEIPT', result.stdout)
            self.assertIn('cap=65536 truncated=1', result.stdout)
            self.assertTrue(result.stdout.endswith(f'RGPU_EXIT {nonce} 7\n'))
            self.assertLess(len(result.stdout), 66000)

    def test_log_show_uses_mac_local_timestamp_format(self):
        tool = load_tool()
        frozen_error = ("log: Failed conversion of '2026-09-11T06:36:42Z' "
                        "using format '%Y-%m-%d %H:%M:%S'")
        self.assertIn('T06:36:42Z', frozen_error)
        command = tool.guest_command('d'*32, b'source', 1234567890,
                                     action='create-remove')
        self.assertIn('/bin/date "+%Y-%m-%d %H:%M:%S"', command)
        self.assertNotIn('%Y-%m-%dT%H:%M:%SZ', command)
        self.assertIn('--start "$log_start" --end "$log_end"', command)

    def test_false_guard_skips_complete_logged_action_and_keeps_exit_marker(self):
        tool = load_tool()
        nonce = 'c' * 32
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            producer = directory / 'producer-ran'
            logger = directory / 'logger-ran'
            body = tool.shell_group(tool.bounded_logged_command(
                f'/usr/bin/touch {producer}', nonce,
                f'/usr/bin/touch {logger}'))
            command = (f'dir={directory}; /usr/bin/false && {body}; result=$?; '
                       f'printf "RGPU_EXIT {nonce} %s\\n" "$result"')
            result = subprocess.run(['/bin/sh', '-c', command], text=True,
                                    capture_output=True, timeout=2, check=True)
            self.assertFalse(producer.exists())
            self.assertFalse(logger.exists())
            self.assertEqual(result.stdout, f'RGPU_EXIT {nonce} 1\n')

    def test_private_spi_declarations_and_runtime_gate_use_unsigned_int(self):
        source = (ROOT / 'tests/virtual_display_inventory.m').read_text()
        self.assertIn('@property unsigned int hiDPI;', source)
        self.assertIn('@property unsigned int rotation;', source)
        self.assertIn('@property unsigned int serialNumber;', source)
        self.assertIn('initWithWidth:(unsigned int)width height:(unsigned int)height', source)
        self.assertIn('descriptor.serialNumber = serial;', source)
        self.assertIn('BOOL abiValid = stage2ABIValid();', source)
        self.assertIn('if (abiValid && baselineError', source)
        self.assertIn('@encode(unsigned int)', source)
        self.assertIn('if (mode) {', source)

    def test_failed_init_raw_output_is_preserved(self):
        tool = load_tool()
        inventory_template = self.valid()

        class Result:
            def __init__(self, stdout): self.stdout = stdout

        class Transport:
            calls = 0

            @classmethod
            def run_guest_command(cls, vm, command, nonce, env, **kwargs):
                cls.calls += 1
                if cls.calls == 1:
                    row = dict(inventory_template, nonce=nonce)
                    return Result('RGPU_VDISPLAY_INVENTORY '+json.dumps(row)+'\n' +
                                  'RGPU_EXIT '+nonce+' 0\n')
                row = {
                    'schema': 1, 'nonce': nonce, 'abi_valid': True,
                    'session': {'user_id': 0, 'user_name': None, 'login_done': False,
                                'on_console': False, 'console_set': None},
                    'method_encodings': {'display_init': '@@:@', 'mode_init': '@@:IId',
                                         'serial_num': 'v@:I', 'serial_number': 'v@:I',
                                         'hi_dpi': 'v@:I', 'rotation': 'v@:I'},
                    'baseline_ids': [], 'created': False, 'display_id': 0,
                    'settings_applied': False, 'added': False, 'active': False,
                    'width': 0, 'height': 0, 'refresh': 0,
                    'retained_milliseconds': 1000, 'removed': False,
                    'termination_called': False, 'final_ids': [],
                    'cleanup_complete': True,
                }
                return Result('RGPU_VDISPLAY_CREATE '+json.dumps(row)+'\n' +
                              'RGPU_EXIT '+nonce+' 0\n')

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            vm, output = root / 'vm', root / 'evidence'
            (vm / 'run').mkdir(parents=True); (vm / 'gx').write_text('fixture')
            argv = ['virtual-display-inventory.py', '--vm-dir', str(vm),
                    '--output', str(output), '--create-remove']
            with mock.patch.object(tool, '_metal_test', return_value=Transport), \
                    mock.patch.object(sys, 'argv', argv), self.assertRaises(ValueError):
                tool.main()
            raw = (output / 'create-output.txt').read_text()
            self.assertIn('"created": false', raw)
            self.assertEqual(json.loads((output / 'error.json').read_text())['type'],
                             'ValueError')


if __name__ == '__main__':
    unittest.main()
