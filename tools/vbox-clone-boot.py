#!/usr/bin/env python3
"""Bounded software-only VBox boot; requires explicit --execute. Never uses VFIO."""
import argparse
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET


def private_file(path):
    st = path.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise ValueError('expected private owned regular file')
    return path.read_bytes()


def config_key(path, key):
    """Only an unregistered, newly created machine file is modified."""
    if len(key) != 64 or any(c < 32 or c > 126 for c in key):
        raise ValueError('SMC key must be exactly64 printable ASCII bytes')
    tree = ET.parse(path)
    root = tree.getroot()
    ns = root.tag.split('}')[0] + '}' if '}' in root.tag else ''
    machine = root.find(ns + 'Machine')
    if machine is None:
        raise ValueError('missing machine')
    extra = machine.find(ns + 'ExtraData')
    if extra is None:
        extra = ET.SubElement(machine, ns + 'ExtraData')
    if any(e.get('name') == 'VBoxInternal2/SmcDeviceKey' for e in extra):
        raise ValueError('unexpected existing key')
    ET.SubElement(extra, ns + 'ExtraDataItem', name='VBoxInternal2/SmcDeviceKey', value=key.decode('ascii'))
    tree.write(path, encoding='utf-8', xml_declaration=True)
    path.chmod(0o600)


def call(home, args, timeout=15):
    env = dict(os.environ, VBOX_USER_HOME=str(home / 'config'))
    p = subprocess.run(['VBoxManage', *args], env=env, capture_output=True, timeout=timeout)
    # Raw output may contain machine identity. Never echo it.
    with (home / 'commands-private.log').open('ab') as f:
        f.write(p.stdout + p.stderr)
    if p.returncode:
        raise RuntimeError('VBoxManage command failed; private log retained')
    return p.stdout.decode(errors='replace')


def state(home, ident):
    raw = call(home, ['showvminfo', ident, '--machinereadable'])
    fields = dict(line.split('=', 1) for line in raw.splitlines() if '=' in line)
    if fields.get('UUID', '').strip('"') != ident:
        raise RuntimeError('machine identity mismatch')
    scope = json.loads(private_file(home / 'scope.json'))
    expected = home / 'vms' / scope['name'] / (scope['name'] + '.vbox')
    if fields.get('CfgFile', '').strip('"') != str(expected):
        raise RuntimeError('machine config binding mismatch')
    return fields.get('VMState', '').strip('"')


def stop(home, ident):
    current = state(home, ident)
    if current not in ('poweroff', 'aborted'):
        call(home, ['controlvm', ident, 'poweroff'])
    for _ in range(30):
        current = state(home, ident)
        if current in ('poweroff', 'aborted'):
            return current
        time.sleep(.2)
    raise RuntimeError('owned VM stop unproven')


def watchdog(home, ident, deadline):
    os.umask(0o077)
    scope = json.loads(private_file(home / 'scope.json'))
    if scope['uuid'] != ident or scope['deadline_monotonic'] != deadline:
        raise ValueError('watchdog scope mismatch')
    (home / 'watchdog-ready').write_text('ready\n')
    while time.monotonic() < deadline:
        if (home / 'finished').exists():
            return
        time.sleep(.2)
    try:
        result = {'deadline_stop': stop(home, ident)}
    except Exception as e:
        result = {'deadline_stop_error': type(e).__name__}
    (home / 'watchdog-result.json').write_text(json.dumps(result) + '\n')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--execute', action='store_true')
    ap.add_argument('--loader', type=Path)
    ap.add_argument('--disk', type=Path)
    ap.add_argument('--smc-key-file', type=Path)
    ap.add_argument('--output', type=Path)
    ap.add_argument('--seconds', type=int, default=240)
    ap.add_argument('--watchdog', nargs=3, metavar=('HOME', 'UUID', 'DEADLINE'))
    a = ap.parse_args()
    if a.watchdog:
        watchdog(Path(a.watchdog[0]), a.watchdog[1], float(a.watchdog[2])); return
    if not a.execute or not all((a.loader, a.disk, a.smc_key_file, a.output)) or not 30 <= a.seconds <= 300:
        ap.error('explicit --execute, private derivatives/key/output and30..300seconds required')
    os.umask(0o077)
    for p in (a.loader, a.disk):
        st = p.lstat()
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_nlink != 1:
            raise ValueError('independent owned regular derivative required')
        if p.parent.resolve() != Path('/home/bogdan/macos-vm/run/c398-vbox-clones') or not p.name.endswith('-boot.vdi'):
            raise ValueError('only named398 writable derivatives permitted')
    key = private_file(a.smc_key_file).rstrip(b'\r\n')
    home = a.output.resolve()
    if home.exists():
        raise ValueError('output must be new')
    home.mkdir(mode=0o700, parents=False)
    (home / 'config').mkdir(mode=0o700)
    ident = str(uuid.uuid4()); name = 'rgpu-c398-' + ident[:8]
    deadline = time.monotonic() + a.seconds
    scope = {'uuid': ident, 'name': name, 'deadline_monotonic': deadline,
             'loader': str(a.loader.resolve()), 'disk': str(a.disk.resolve()), 'gpu': False}
    (home / 'scope.json').write_text(json.dumps(scope, indent=2) + '\n')
    registered = False
    guard = None
    result = {'uuid': ident, 'guest_boot_qualified': False}
    try:
        call(home, ['createvm', '--name', name, '--uuid', ident, '--ostype', 'MacOS_64', '--basefolder', str(home / 'vms')])
        config = home / 'vms' / name / (name + '.vbox')
        config_key(config, key); del key
        registered = True  # reconcile even an ambiguous registration failure
        call(home, ['registervm', str(config)])
        call(home, ['modifyvm', ident, '--memory', '8192', '--cpus', '8', '--cpu-profile', 'Intel Core i7-6700K',
                    '--firmware', 'efi64', '--chipset', 'ich9', '--ioapic', 'on', '--graphicscontroller', 'vboxvga',
                    '--vram', '64', '--accelerate-3d', 'off', '--nic1', 'none', '--audio-enabled', 'off',
                    '--usb-xhci', 'on', '--mouse', 'usbtablet', '--keyboard', 'usb',
                    '--uart1', '0x3f8', '4', '--uart-mode1', 'file', str(home / 'uart1.log'),
                    '--uart2', '0x2f8', '3', '--uart-mode2', 'file', str(home / 'uart2.log')])
        call(home, ['storagectl', ident, '--name', 'SATA', '--add', 'sata', '--controller', 'IntelAhci', '--portcount', '6', '--bootable', 'on'])
        for port, disk in [('2', a.loader), ('4', a.disk)]:
            call(home, ['storageattach', ident, '--storagectl', 'SATA', '--port', port, '--device', '0', '--type', 'hdd', '--medium', str(disk.resolve())])
        if time.monotonic() >= deadline - 20:
            raise RuntimeError('setup exhausted deadline')
        guard = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--watchdog', str(home), ident, str(deadline)], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        until = time.monotonic() + 3
        while not (home / 'watchdog-ready').exists() and time.monotonic() < until:
            time.sleep(.05)
        if not (home / 'watchdog-ready').exists() or guard.poll() is not None:
            raise RuntimeError('watchdog not armed')
        call(home, ['startvm', ident, '--type', 'gui'], timeout=min(30, max(1, deadline-time.monotonic())))
        index = 0
        while time.monotonic() < deadline - 2:
            if guard.poll() is not None:
                raise RuntimeError('watchdog exited before completion')
            current = state(home, ident)
            if current in ('poweroff', 'aborted'):
                break
            if current == 'running':
                try:
                    call(home, ['controlvm', ident, 'screenshotpng', str(home / ('screen-%03d.png' % index))], timeout=5)
                except (RuntimeError, subprocess.TimeoutExpired):
                    pass
                index += 1
            time.sleep(min(5, max(0, deadline - time.monotonic() - 2)))
        result['screenshots_attempted'] = index
    except Exception as e:
        result['error_type'] = type(e).__name__
    finally:
        if registered:
            try:
                result['final_state'] = stop(home, ident)
                call(home, ['unregistervm', ident])
                result['unregistered'] = True
                (home / 'finished').write_text('stopped and unregistered\n')
            except Exception as e:
                result['cleanup_error'] = type(e).__name__
        else:
            (home / 'finished').write_text('not registered\n')
        (home / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        if guard and (home / 'finished').exists():
            guard.wait(timeout=3)
    print(json.dumps({k:v for k,v in result.items() if k not in ('uuid',)}))
    return 1 if 'error_type' in result or 'cleanup_error' in result else 0


if __name__ == '__main__':
    sys.exit(main())
