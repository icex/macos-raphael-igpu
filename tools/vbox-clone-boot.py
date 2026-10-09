#!/usr/bin/env python3
"""Bounded software-only VBox boot; requires explicit --execute. Never uses VFIO."""
import argparse
import fcntl
import hashlib
import re
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET


EXCHANGE_DIR = Path('/home/bogdan/macos-vm/run/c410-exchange')
EXCHANGE_SIZE = 32 * 1024 * 1024

def exchange_input(path):
    """Validate only the independent, bounded exchange medium; never guest disks."""
    st = path.lstat()
    if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or
            st.st_nlink != 1 or st.st_mode & 0o077 or
            not 512 <= st.st_size <= 40 * 1024 * 1024 or
            path.parent.resolve() != EXCHANGE_DIR or path.name != 'exchange.vdi'):
        raise ValueError('exchange must be private independent bounded owned VDI')
    raw = subprocess.run(['qemu-img', 'info', '--output=json', str(path.resolve())],
                         capture_output=True, check=True, timeout=10).stdout
    info = json.loads(raw)
    if info.get('format') != 'vdi' or info.get('virtual-size') != EXCHANGE_SIZE or info.get('backing-filename'):
        raise ValueError('exchange requires standalone32MiB VDI')
    return dict(path=str(path.resolve()), bytes=st.st_size,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                virtual_size=EXCHANGE_SIZE, port=5, device=0)

def exchange_medium(home, exchange):
    # VBox7.2 showmediuminfo has human-readable output only. Restrict keys,
    # require one exact identity/path/format; retain complete output privately.
    raw = call(home, ['showmediuminfo', 'disk', exchange['path']])
    fields = {}
    for line in raw.splitlines():
        if ':' not in line: continue
        key, value = line.split(':', 1)
        if key in ('UUID', 'Location', 'Storage format'):
            if key in fields: raise RuntimeError('duplicate exchange medium identity')
            fields[key] = value.strip()
    ident = fields.get('UUID', '')
    if (not re.fullmatch('[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', ident) or
            fields.get('Location') != exchange['path'] or fields.get('Storage format') != 'VDI'):
        raise RuntimeError('exchange medium identity mismatch')
    if exchange.get('uuid', ident) != ident: raise RuntimeError('exchange UUID changed')
    return ident

def close_exchange(home, exchange):
    medium_uuid = exchange_medium(home, exchange)
    call(home, ['closemedium', 'disk', medium_uuid])
    return hashlib.sha256(Path(exchange['path']).read_bytes()).hexdigest()


def verify_exchange_attachment(home, ident, exchange):
    if state(home, ident) != 'poweroff': raise RuntimeError('exchange requires owned stopped VM')
    raw = call(home, ['showvminfo', ident, '--machinereadable'])
    fields = dict(line.split('=', 1) for line in raw.splitlines() if '=' in line)
    def value(key): return fields.get('"'+key+'"', fields.get(key, '')).strip('"')
    scope = json.loads(private_file(home / 'scope.json'))
    expected_cfg = str(home / 'vms' / scope['name'] / (scope['name'] + '.vbox'))
    if value('UUID') != ident or value('CfgFile') != expected_cfg or value('VMState') != 'poweroff':
        raise RuntimeError('exchange attachment observation lost stopped identity')
    if value('SATA-5-0') != exchange['path'] or value('SATA-ImageUUID-5-0') != exchange['uuid']:
        raise RuntimeError('exchange attachment differs from scoped medium')


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


class VBoxCallError(RuntimeError):
    def __init__(self, locked=False, console_unavailable=False):
        super().__init__('VBoxManage command failed; private log retained')
        self.locked = locked
        self.console_unavailable = console_unavailable


def call(home, args, timeout=15):
    env = dict(os.environ, VBOX_USER_HOME=str(home / 'config'), LC_ALL='C')
    p = subprocess.run(['VBoxManage', *args], env=env, capture_output=True, timeout=timeout)
    # Raw output may contain machine identity. Never echo it.
    with (home / 'commands-private.log').open('ab') as f:
        f.write(p.stdout + p.stderr)
    if p.returncode:
        raise VBoxCallError(
            locked=(args[0] == 'unregistervm' and b'while it is locked' in p.stderr and
                    b'VBOX_E_INVALID_OBJECT_STATE' in p.stderr),
            console_unavailable=(args[0] == 'showvminfo' and
                b'Failed to get a console object from the direct session (VBOX_E_INVALID_OBJECT_STATE)' in p.stderr and
                b'code VBOX_E_VM_ERROR (0x80bb0003)' in p.stderr and
                b'LockMachine(a->session, LockType_Shared)' in p.stderr))
    return p.stdout.decode(errors='replace')


def state(home, ident, timeout=15):
    raw = call(home, ['showvminfo', ident, '--machinereadable'], timeout=timeout)
    fields = dict(line.split('=', 1) for line in raw.splitlines() if '=' in line)
    if fields.get('UUID', '').strip('"') != ident:
        raise RuntimeError('machine identity mismatch')
    scope = json.loads(private_file(home / 'scope.json'))
    expected = home / 'vms' / scope['name'] / (scope['name'] + '.vbox')
    if fields.get('CfgFile', '').strip('"') != str(expected):
        raise RuntimeError('machine config binding mismatch')
    exchange = scope.get('exchange')
    if exchange and exchange.get('uuid'):
        for key, expected_value in [('SATA-5-0', exchange['path']), ('SATA-ImageUUID-5-0', exchange['uuid'])]:
            observed = fields.get('"'+key+'"', fields.get(key, '')).strip('"')
            if observed != expected_value: raise RuntimeError('scoped exchange attachment changed')
    return fields.get('VMState', '').strip('"')


def unregister_stopped(home, ident):
    # Poweroff completion can precede GUI session unlock. Never retry a foreign,
    # running or otherwise failed machine, and never force-unlock its session.
    deadline = time.monotonic() + 15
    attempts = 0
    owned_stopped_observed = False
    while time.monotonic() < deadline:
        try:
            current = state(home, ident, timeout=max(.01, min(2, deadline-time.monotonic())))
        except VBoxCallError as exc:
            if not owned_stopped_observed or not exc.console_unavailable:
                raise
            # GUI unlock can temporarily break this read; no unregister is issued
            # until another full UUID/config/stopped observation succeeds.
            time.sleep(min(.1, max(0, deadline-time.monotonic())))
            continue
        if current not in ('poweroff', 'aborted'):
            raise RuntimeError('unregister requires owned stopped machine')
        owned_stopped_observed = True
        attempts += 1
        try:
            call(home, ['unregistervm', ident], timeout=max(.01, min(2, deadline-time.monotonic())))
            return attempts
        except VBoxCallError as exc:
            if not exc.locked:
                raise
            time.sleep(min(.1, max(0, deadline-time.monotonic())))
    raise RuntimeError('owned stopped GUI session did not unlock within15seconds')


def stop(home, ident):
    # Separate descriptors make flock serialize controller and watchdog callers.
    with (home / 'cleanup.lock').open('a') as lock:
        os.chmod(home / 'cleanup.lock', 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        scope = json.loads(private_file(home / 'scope.json'))
        if scope['uuid'] != ident:
            raise RuntimeError('cleanup scope mismatch')
        proof = home / 'stopped.json'
        if proof.exists():
            previous = json.loads(private_file(proof))
            if previous.get('uuid') != ident or previous.get('state') not in ('poweroff', 'aborted'):
                raise RuntimeError('invalid previous stopped proof')
            return previous['state']
        current = state(home, ident)
        if current not in ('poweroff', 'aborted'):
            call(home, ['controlvm', ident, 'poweroff'])
        for _ in range(30):
            current = state(home, ident)
            if current in ('poweroff', 'aborted'):
                with proof.open('x') as f:
                    os.chmod(proof, 0o600)
                    json.dump({'uuid': ident, 'state': current}, f)
                return current
            time.sleep(.2)
        raise RuntimeError('owned VM stop unproven')


def derive_key(source, destination):
    # Archived reviewed QEMU argv, never an arbitrary executable/shell expansion.
    st = source.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_size > 131072:
        raise ValueError('invalid bounded argv artifact')
    raw = source.read_bytes()
    args = json.loads(raw)
    if not isinstance(args, list) or not all(isinstance(v, str) for v in args):
        raise ValueError('expected argv list')
    found = []
    for i, arg in enumerate(args):
        if arg.startswith('isa-applesmc'):
            match = re.fullmatch(r'isa-applesmc,osk=([A-Za-z0-9 ()]{64})', arg)
            if i == 0 or args[i-1] != '-device' or not match:
                raise ValueError('unexpected SMC device encoding')
            found.append(match.group(1).encode('ascii'))
    if len(found) != 1:
        raise ValueError('SMC device must be unique')
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as f:
        f.write(found[0]); f.flush(); os.fsync(f.fileno())
    return {'source_sha256': hashlib.sha256(raw).hexdigest(), 'key_bytes': 64}


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


def parser():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--execute', action='store_true')
    ap.add_argument('--derive-smc-key', nargs=2, type=Path, metavar=('PRIVATE_ARGV', 'NEW_PRIVATE_KEY'))
    ap.add_argument('--loader', type=Path)
    ap.add_argument('--disk', type=Path)
    ap.add_argument('--exchange', type=Path)
    ap.add_argument('--smc-key-file', type=Path)
    ap.add_argument('--output', type=Path)
    ap.add_argument('--seconds', type=int, default=240)
    ap.add_argument('--cpus', type=int, choices=(1, 8), default=8)
    ap.add_argument('--tsc-mode', choices=('auto', 'RealTSCOffset'), default='auto')
    ap.add_argument('--watchdog', nargs=3, metavar=('HOME', 'UUID', 'DEADLINE'))
    ap.add_argument('--graphics-controller', choices=('vboxvga', 'vmsvga'), default='vboxvga')
    return ap

def main():
    ap = parser()
    a = ap.parse_args()
    if a.derive_smc_key:
        if a.execute or a.watchdog:
            ap.error('key extraction is standalone')
        print(json.dumps(derive_key(*a.derive_smc_key))); return
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
    if a.loader.resolve() == a.disk.resolve():
        raise ValueError('loader and system disk must differ')
    exchange = exchange_input(a.exchange) if a.exchange else None
    if exchange and Path(exchange['path']) in (a.loader.resolve(), a.disk.resolve()):
        raise ValueError('exchange must differ from boot media')
    lease_fd = os.open(a.loader.parent / 'boot-controller.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    fcntl.flock(lease_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if a.smc_key_file.lstat().st_size > 66:
        raise ValueError('oversized key file')
    key = private_file(a.smc_key_file).rstrip(b'\r\n')
    home = a.output.resolve()
    if home.exists():
        raise ValueError('output must be new')
    home.mkdir(mode=0o700, parents=False)
    (home / 'config').mkdir(mode=0o700)
    ident = str(uuid.uuid4()); name = 'rgpu-c398-' + ident[:8]
    deadline = time.monotonic() + a.seconds
    scope = {'uuid': ident, 'name': name, 'deadline_monotonic': deadline,
             'loader': str(a.loader.resolve()), 'disk': str(a.disk.resolve()), 'gpu': False,
             'graphics_controller': a.graphics_controller,
             'cpus': a.cpus, 'cpu_profile': 'Intel Core i7-6700K',
             'tsc_override': None if a.tsc_mode == 'auto' else a.tsc_mode}
    if exchange: scope['exchange'] = exchange
    (home / 'scope.json').write_text(json.dumps(scope, indent=2) + '\n')
    registered = False
    guard = None
    result = {'uuid': ident, 'guest_boot_qualified': False}
    if exchange: result['exchange_closed'] = False
    try:
        call(home, ['createvm', '--name', name, '--uuid', ident, '--ostype', 'MacOS_64', '--basefolder', str(home / 'vms')])
        config = home / 'vms' / name / (name + '.vbox')
        config_key(config, key); del key
        registered = True  # reconcile even an ambiguous registration failure
        call(home, ['registervm', str(config)])
        if a.tsc_mode != 'auto':
            call(home, ['setextradata', ident, 'VBoxInternal/TM/TSCMode', a.tsc_mode])
        call(home, ['modifyvm', ident, '--memory', '8192', '--cpus', str(a.cpus), '--cpu-profile', 'Intel Core i7-6700K',
                    '--firmware', 'efi64', '--chipset', 'ich9', '--ioapic', 'on', '--graphicscontroller', a.graphics_controller,
                    '--vram', '64', '--accelerate-3d', 'off', '--nic1', 'none', '--audio-enabled', 'off',
                    '--usb-xhci', 'on', '--mouse', 'usbtablet', '--keyboard', 'usb',
                    '--uart1', '0x3f8', '4', '--uart-mode1', 'file', str(home / 'uart1.log'),
                    '--uart2', '0x2f8', '3', '--uart-mode2', 'file', str(home / 'uart2.log')])
        call(home, ['storagectl', ident, '--name', 'SATA', '--add', 'sata', '--controller', 'IntelAhci', '--portcount', '6', '--bootable', 'on'])
        for port, disk in [('2', a.loader), ('4', a.disk)]:
            call(home, ['storageattach', ident, '--storagectl', 'SATA', '--port', port, '--device', '0', '--type', 'hdd', '--medium', str(disk.resolve())])
        if exchange:
            # Recheck exact bytes immediately before attachment, no generic extra disks.
            if exchange_input(a.exchange) != exchange: raise RuntimeError('exchange changed before attachment')
            call(home, ['storageattach', ident, '--storagectl', 'SATA', '--port', '5', '--device', '0', '--type', 'hdd', '--medium', exchange['path']])
            exchange['uuid'] = exchange_medium(home, exchange)
            scope['exchange'] = exchange
            (home / 'scope.json').write_text(json.dumps(scope, indent=2)+'\n')
            verify_exchange_attachment(home, ident, exchange)
        if time.monotonic() >= deadline - 20:
            raise RuntimeError('setup exhausted deadline')
        guard = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--watchdog', str(home), ident, str(deadline)], start_new_session=True, pass_fds=(lease_fd,), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
            if current == 'gurumeditation':
                result['functional_failure'] = 'firmware-or-vm-guru'
                break
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
                (home / 'finished').write_text('VM stop independently verified\n')
                result['unregister_attempts'] = unregister_stopped(home, ident)
                result['unregistered'] = True
                if exchange and exchange.get('uuid'):
                    # unregister detached the owned VM; close only the exact medium,
                    # never delete it. A retained use/lock fails closed.
                    result['exchange_sha256_after'] = close_exchange(home, exchange)
                    result['exchange_closed'] = True
                (home / 'finished').write_text('stopped and unregistered\n')
            except Exception as e:
                result['cleanup_error'] = type(e).__name__
        else:
            (home / 'finished').write_text('not registered\n')
        (home / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        if guard and (home / 'finished').exists():
            guard.wait(timeout=3)
    print(json.dumps({k:v for k,v in result.items() if k not in ('uuid',)}))
    return 1 if any(k in result for k in ('error_type', 'cleanup_error', 'functional_failure')) else 0


if __name__ == '__main__':
    sys.exit(main())
