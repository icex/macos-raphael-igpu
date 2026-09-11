#!/usr/bin/env python3
"""Inventory virtual-display SPI and optionally run one nonce-bound lifecycle."""

import argparse
import base64
import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shlex
import time
import uuid


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'tests/virtual_display_inventory.m'
REQUIRED_CLASSES = (
    'CGVirtualDisplay', 'CGVirtualDisplayDescriptor',
    'CGVirtualDisplayMode', 'CGVirtualDisplaySettings')
REQUIRED_SELECTORS = (
    'initWithDescriptor_', 'applySettings_', 'displayID',
    'initWithWidth_height_refreshRate_', 'setDispatchQueue_', 'setVendorID_',
    'setProductID_', 'setSerialNum_', 'setSerialNumber_', 'setName_',
    'setWhitePoint_', 'setBluePrimary_', 'setGreenPrimary_', 'setRedPrimary_',
    'setMaxPixelsHigh_', 'setMaxPixelsWide_', 'setSizeInMillimeters_',
    'setTerminationHandler_',
    'setModes_', 'setHiDPI_', 'setRotation_')


def _metal_test():
    path = ROOT / 'tools/metal-test.py'
    spec = importlib.util.spec_from_file_location('metal_test_for_vdisplay', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def bounded_logged_command(run_binary, nonce, log_command):
    """Run the producer, then capture at most 64 KiB of logs for at most 5s."""
    return (
        'log_start=$(/bin/date "+%Y-%m-%d %H:%M:%S"); '
        f'{run_binary}; binary_result=$?; '
        '/bin/sleep 1; '
        'log_end=$(/bin/date "+%Y-%m-%d %H:%M:%S"); '
        f'{log_command} > "$dir/unified.log" 2>&1 & log_pid=$!; '
        '( /bin/sleep 4; /bin/kill -TERM "$log_pid" >/dev/null 2>&1; '
        '/bin/sleep 1; /bin/kill -KILL "$log_pid" >/dev/null 2>&1 ) & watchdog=$!; '
        'wait "$log_pid"; log_result=$?; '
        '/bin/kill "$watchdog" >/dev/null 2>&1; wait "$watchdog" 2>/dev/null; '
        'log_bytes=$(/usr/bin/wc -c < "$dir/unified.log" | /usr/bin/tr -d " "); '
        'if test "$log_bytes" -gt 65536; then truncated=1; else truncated=0; fi; '
        f'/usr/bin/printf "RGPU_VDISPLAY_LOG {nonce} start=%s end=%s status=%s '
        'bytes=%s cap=65536 truncated=%s\\n" "$log_start" "$log_end" '
        '"$log_result" "$log_bytes" "$truncated"; '
        '/usr/bin/head -c 65536 "$dir/unified.log"; (exit "$binary_result")')


def shell_group(command):
    return f'( {command} )'


def guest_command(nonce, source, expiry, action='inventory'):
    if not re.fullmatch(r'[0-9a-f]{32}', nonce) or type(source) is not bytes:
        raise ValueError('invalid inventory command input')
    if action not in ('inventory', 'create-remove'):
        raise ValueError('invalid inventory action')
    directory = f'/var/tmp/rgpu-vdisplay-inventory-{nonce}'
    encoded = base64.b64encode(source).decode('ascii')
    qdir = shlex.quote(directory)
    permit = f'http://10.0.2.2:8889/metal-permit-{nonce}'
    run_binary = f'"$dir/inventory" {shlex.quote(nonce)} {shlex.quote(action)}'
    if action == 'create-remove':
        predicate = ('process == "inventory" OR '
                     'senderImagePath CONTAINS "CoreGraphics" OR '
                     'senderImagePath CONTAINS "SkyLight" OR '
                     '(process == "WindowServer" AND '
                     '(subsystem CONTAINS[c] "display" OR category CONTAINS[c] "display"))')
        log_command = ('/usr/bin/log show --start "$log_start" --end "$log_end" '
                       '--style json --info --debug --predicate ' + shlex.quote(predicate))
        run_binary = shell_group(bounded_logged_command(run_binary, nonce,
                                                        log_command))
    shell_action = (
        f'dir={qdir}; owned=0; cleanup() {{ test "$owned" = 1 && /bin/rm -rf "$dir"; }}; '
        'trap cleanup EXIT HUP INT TERM; /bin/mkdir -m 700 "$dir" && owned=1 && '
        f'permit=$(/usr/bin/curl -fsS --max-time 3 {shlex.quote(permit)}) && '
        f'test "$permit" = {shlex.quote(nonce)} && '
        f'test $(/bin/date +%s) -le {int(expiry)} && '
        f'/usr/bin/printf %s {shlex.quote(encoded)} | /usr/bin/base64 -D > "$dir/inventory.m" && '
        '/usr/bin/xcrun clang -fobjc-arc -fblocks -O2 -Wall -Wextra -Werror '
        '-framework Foundation -framework CoreGraphics -framework SystemConfiguration '
        '"$dir/inventory.m" -o "$dir/inventory" && '
        f'{run_binary}')
    return f'( {shell_action}; result=$?; printf "\\nRGPU_EXIT {nonce} %s\\n" "$result" )'


def validate_output(output, nonce):
    if not isinstance(output, str) or not re.fullmatch(r'[0-9a-f]{32}', nonce):
        raise ValueError('invalid inventory output arguments')
    rows = [line.removeprefix('RGPU_VDISPLAY_INVENTORY ')
            for line in output.splitlines()
            if line.startswith('RGPU_VDISPLAY_INVENTORY ')]
    if len(rows) != 1:
        raise ValueError('expected exactly one virtual-display inventory')
    try:
        result = json.loads(rows[0])
    except json.JSONDecodeError as error:
        raise ValueError('malformed virtual-display inventory') from error
    exits = re.findall(r'^RGPU_EXIT '+re.escape(nonce)+r' (\d+)$', output, re.M)
    if exits != ['0']:
        raise ValueError('inventory did not exit successfully')
    if (not isinstance(result, dict) or result.get('schema') != 1 or
            result.get('nonce') != nonce or not isinstance(result.get('os_build'), str) or
            type(result.get('console_uid')) is not int or
            not isinstance(result.get('console_user'), str) or
            type(result.get('window_server_running')) is not bool or
            type(result.get('screen_capture_preflight')) is not bool or
            type(result.get('display_list_error')) is not int or
            not isinstance(result.get('online_displays'), list)):
        raise ValueError('invalid virtual-display inventory schema')
    classes, selectors = result.get('classes'), result.get('selectors')
    if (not isinstance(classes, dict) or set(classes) != set(REQUIRED_CLASSES) or
            any(type(value) is not bool for value in classes.values())):
        raise ValueError('invalid virtual-display runtime class inventory')
    if (not isinstance(selectors, dict) or set(selectors) != set(REQUIRED_SELECTORS) or
            any(type(value) is not bool for value in selectors.values())):
        raise ValueError('invalid virtual-display runtime selector inventory')
    sck = result.get('screen_capture_kit')
    if (not isinstance(sck, dict) or set(sck) != {'class', 'selector'} or
            any(type(value) is not bool for value in sck.values())):
        raise ValueError('invalid ScreenCaptureKit inventory')
    display_keys = {'id', 'online', 'active', 'builtin', 'main', 'vendor',
                    'model', 'serial', 'x', 'y', 'width', 'height', 'refresh'}
    for display in result['online_displays']:
        if (not isinstance(display, dict) or set(display) != display_keys or
                any(type(display[key]) is not bool
                    for key in ('online', 'active', 'builtin', 'main')) or
                any(type(display[key]) not in (int, float)
                    for key in display_keys - {'online', 'active', 'builtin', 'main'})):
            raise ValueError('invalid online display inventory')
    blockers = []
    if not all(classes.values()) or not all(selectors.values()):
        blockers.append('virtual_display_spi_incomplete')
    if result['display_list_error'] != 0:
        blockers.append('online_display_list_unavailable')
    capture_blockers = []
    if (result['console_uid'] == 0 or result['console_user'] in ('', 'loginwindow') or
            not result['window_server_running']):
        capture_blockers.append('console_session_unavailable')
    if not result['screen_capture_preflight']:
        capture_blockers.append('screen_capture_permission_absent')
    if not all(sck.values()):
        capture_blockers.append('screen_capture_kit_unavailable')
    return dict(result, stage2_blockers=blockers,
                capture_blockers=capture_blockers)


def validate_create_output(output, nonce):
    if not isinstance(output, str) or not re.fullmatch(r'[0-9a-f]{32}', nonce):
        raise ValueError('invalid create/remove output arguments')
    rows = [line.removeprefix('RGPU_VDISPLAY_CREATE ')
            for line in output.splitlines()
            if line.startswith('RGPU_VDISPLAY_CREATE ')]
    if len(rows) != 1:
        raise ValueError('expected exactly one create/remove result')
    try:
        result = json.loads(rows[0])
    except json.JSONDecodeError as error:
        raise ValueError('malformed create/remove result') from error
    exits = re.findall(r'^RGPU_EXIT '+re.escape(nonce)+r' (\d+)$', output, re.M)
    if exits != ['0']:
        raise ValueError('create/remove did not exit successfully')
    keys = {'schema', 'nonce', 'abi_valid', 'session', 'method_encodings',
            'baseline_ids', 'created', 'display_id',
            'settings_applied', 'added', 'active', 'width', 'height', 'refresh',
            'retained_milliseconds', 'removed', 'termination_called',
            'final_ids', 'cleanup_complete'}
    bools = ('abi_valid', 'created', 'settings_applied', 'added', 'active', 'removed',
             'termination_called', 'cleanup_complete')
    if (not isinstance(result, dict) or set(result) != keys or
            result.get('schema') != 1 or result.get('nonce') != nonce or
            any(type(result.get(key)) is not bool for key in bools) or
            type(result.get('display_id')) is not int or
            type(result.get('width')) is not int or
            type(result.get('height')) is not int or
            type(result.get('refresh')) not in (int, float) or
            type(result.get('retained_milliseconds')) is not int or
            not isinstance(result.get('baseline_ids'), list) or
            not isinstance(result.get('final_ids'), list) or
            any(type(value) is not int for value in result['baseline_ids'] + result['final_ids'])):
        raise ValueError('invalid create/remove schema')
    session = result['session']
    encodings = result['method_encodings']
    if (not isinstance(session, dict) or
            set(session) != {'user_id', 'user_name', 'login_done', 'on_console', 'console_set'} or
            any(value is not None and type(value) not in (bool, int, str)
                for value in session.values()) or
            not isinstance(encodings, dict) or
            set(encodings) != {'display_init', 'mode_init', 'serial_num',
                               'serial_number', 'hi_dpi', 'rotation'} or
            any(not isinstance(value, str) for value in encodings.values())):
        raise ValueError('invalid create/remove diagnostics')
    if (result['baseline_ids'] or result['final_ids'] or result['display_id'] <= 0 or
            not result['abi_valid'] or result['width'] != 1280 or result['height'] != 720 or
            abs(result['refresh'] - 60.0) > 0.01 or
            result['retained_milliseconds'] < 1000 or
            not all(result[key] for key in
                    ('created', 'settings_applied', 'added', 'active',
                     'removed', 'cleanup_complete'))):
        raise ValueError('create/remove lifecycle did not complete')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vm-dir', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--create-remove', action='store_true')
    args = parser.parse_args()
    vm = args.vm_dir.resolve()
    if not (vm / 'gx').is_file() or not (vm / 'run').is_dir():
        parser.error('--vm-dir must contain gx and run/')
    if args.output.exists():
        parser.error('--output must not already exist')
    source = SOURCE.read_bytes()
    nonce = uuid.uuid4().hex
    create_nonce = uuid.uuid4().hex if args.create_remove else None
    command = guest_command(nonce, source, int(time.time()) + 45)
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / 'identity.json').write_text(json.dumps({
        'nonce': nonce, 'create_nonce': create_nonce,
        'source_sha256': hashlib.sha256(source).hexdigest(),
        'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }, indent=2)+'\n')
    try:
        proc = _metal_test().run_guest_command(
            vm, command, nonce, dict(__import__('os').environ, GX_TIMEOUT='40'),
            timeout=42, execution_grace=0)
        (args.output / 'output.txt').write_text(proc.stdout)
        inventory = validate_output(proc.stdout, nonce)
        (args.output / 'inventory.json').write_text(json.dumps(inventory, indent=2)+'\n')
        if args.create_remove:
            if inventory['stage2_blockers']:
                raise ValueError('inventory has Stage 2 blockers: ' +
                                 ', '.join(inventory['stage2_blockers']))
            create_command = guest_command(create_nonce, source,
                                           int(time.time()) + 45,
                                           action='create-remove')
            create_proc = _metal_test().run_guest_command(
                vm, create_command, create_nonce,
                dict(__import__('os').environ, GX_TIMEOUT='40'),
                timeout=42, execution_grace=0)
            (args.output / 'create-output.txt').write_text(create_proc.stdout)
            lifecycle = validate_create_output(create_proc.stdout, create_nonce)
            (args.output / 'create-remove.json').write_text(
                json.dumps(lifecycle, indent=2)+'\n')
    except BaseException as error:
        (args.output / 'error.json').write_text(json.dumps({
            'type': type(error).__name__, 'error': str(error),
        }, indent=2)+'\n')
        raise


if __name__ == '__main__':
    main()
