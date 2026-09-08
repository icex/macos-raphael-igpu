#!/usr/bin/env python3
"""Identity and admission primitives for one bounded GPU experiment. No device resets."""
import json
import os
from pathlib import Path
import re
import hashlib
import shutil
import subprocess
import tempfile
import uuid
import argparse
import fcntl
import importlib.util
import plistlib
import time
import shlex
import signal
import gzip

ROOT = Path(__file__).resolve().parents[1]
BOOT_GUID = '7C436110-AB2A-4BBB-A880-FE41995C9F82'


def helper(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), Path(__file__).with_name(name+'.py'))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def command(args, timeout=15):
    return subprocess.check_output(args, text=True, timeout=timeout).strip()


def plist(data):
    # Docker-OSX's XML has comments before the XML declaration.
    start = data.find(b'<?xml')
    return plistlib.loads(data[start:] if start >= 0 else data)


def amdgpu_initialized(journal):
    completed = re.search(r'Initialized amdgpu [^\n]+ for 0000:7b:00\.0\b', journal)
    failed = re.search(r'amdgpu 0000:7b:00\.0[^\n]*(?:probe.*failed|Fatal error|hw_init.*failed)', journal, re.I)
    return bool(completed) and not failed


def host_snapshot():
    device = Path('/sys/bus/pci/devices/0000:7b:00.0')
    def read(path):
        try: return Path(path).read_text().strip()
        except OSError: return None
    group = (device / 'iommu_group').resolve().name
    driver = (device / 'driver').resolve().name
    journal = subprocess.run(['journalctl', '-k', '-b', '--no-pager'],
                             text=True, capture_output=True, timeout=15)
    active = command(['docker', 'ps', '-a', '--filter', 'status=running', '--filter',
                      'status=created', '--filter', 'status=paused', '--filter',
                      'status=restarting', '--format', '{{.Names}}'])
    try: pstore = [p.name for p in Path('/sys/fs/pstore').iterdir()]
    except OSError: pstore = None
    config = read('/etc/systemd/journald.conf.d/10-crash-durability.conf') or ''
    watchdogs = {name: read('/proc/sys/kernel/'+name)
                 for name in ('watchdog', 'nmi_watchdog', 'hardlockup_panic')}
    return dict(boot_id=read('/proc/sys/kernel/random/boot_id'), kernel=os.uname().release,
                driver=driver, device=(read(device/'vendor') or '').removeprefix('0x')+':'+
                    (read(device/'device') or '').removeprefix('0x'), iommu_group=group,
                amdgpu_initialized=amdgpu_initialized(journal.stdout) if journal.returncode == 0 else None,
                watchdogs=watchdogs, watchdogs_verified=all(v == '1' for v in watchdogs.values()),
                capture_ready=(read('/sys/module/pstore/parameters/backend') == 'efi_pstore' and
                               'Storage=persistent' in config and 'SyncIntervalSec=1s' in config),
                pstore_files=pstore,
                device_pinned_awake=read(device/'power/control') == 'on' and read(device/'power/runtime_status') == 'active',
                device_accessible=os.access('/dev/vfio/'+group, os.R_OK | os.W_OK),
                active_vm=any(n == 'macos-sequoia' or n.startswith('rgpu-launch-') for n in active.splitlines()),
                sleep_inhibited=subprocess.run(['systemctl', '--user', 'is-active', '--quiet',
                                                'rgpu-work-inhibit.service']).returncode == 0)


IDENTITY_FIELDS = ('source_commit', 'source_sha256', 'build_id', 'binary_sha256', 'info_sha256',
                   'config_sha256', 'boot_args', 'kdk_sha256', 'image_id', 'qemu_version',
                   'guest_build', 'probe_source_sha256', 'probe_binary_sha256', 'boot_id',
                   'kernel', 'bootdisk_sha256', 'build_inputs_sha256', 'run_id',
                   'harness_sha256', 'rom_sha256', 'launch_options')


def required_identity(data):
    return [key for key in IDENTITY_FIELDS if not data.get(key)]


def current_identity(vm, candidate):
    build = json.loads((candidate / 'build-manifest.json').read_text())
    bundle = candidate / 'RaphaelGPU.kext/Contents'
    expected = dict(binary_sha256=sha((bundle/'MacOS/RaphaelGPU').read_bytes()),
                    info_sha256=sha((bundle/'Info.plist').read_bytes()))
    if expected['binary_sha256'] != build['executable_sha256'] or expected['info_sha256'] != build['info_sha256']:
        raise ValueError('candidate differs from its build manifest')
    if not build.get('source_clean'): raise ValueError('candidate was built from an uncommitted tree')
    inputs = json.loads((ROOT/'build-support/inputs.json').read_text())
    if any(build.get(key) != value for key, value in inputs.items()):
        raise ValueError('candidate build inputs differ from current pinned inputs')
    if sha(gzip.decompress((ROOT/'build-support/rlc_fw.h.gz').read_bytes())) != inputs['firmware_header_sha256']:
        raise ValueError('firmware payload differs from the compiled input')
    if os.environ.get('BOOTDISK_MODE', 'custom') != 'custom':
        raise ValueError('only the prepared custom bootdisk is admitted')
    if os.environ.get('NVRAM', 'stock') != 'stock':
        raise ValueError('persistent NVRAM is not admitted for the fixed baseline')
    builder = helper('build-release')
    source_digest = builder.tree_digest(ROOT/'src')
    if source_digest != build['source_sha256']: raise ValueError('current source differs from built source')
    image = image_files(vm/'run/oc-raw.img')
    if validate_identity(expected, image): raise ValueError('ESP executable or Info.plist differs from candidate')
    config = (vm/'config.plist').read_bytes()
    if sha(config) != image['config_sha256']: raise ValueError('ESP config differs from intended boot config')
    args = plist(config)['NVRAM']['Add'][BOOT_GUID]['boot-args']
    switches = {word.split('=', 1)[0]:word.split('=', 1)[1] for word in args.split() if '=' in word}
    required = dict(rgpu='0xfffa5981', rgpuvmm='3', rgpumem='2', rgpuptb='2', rgpumqd='2', rgpuhybrid='1')
    if any(switches.get(key) != value for key,value in required.items()):
        raise ValueError('functional baseline or hybrid diagnostic boot arguments changed')
    if any(key in switches for key in ('rgpucp', 'rgpureset', 'rgpuic', 'rgpurlc', 'rgpufb')):
        raise ValueError('retired hardware experiments cannot be admitted')
    extension = vm/'kdk/x/System/Library/Extensions'
    kdk = {name: sha(path.read_bytes()) for name, path in {
        'HWLibs': extension/'AMDRadeonX6000HWServices.kext/Contents/PlugIns/AMDRadeonX6000HWLibs.kext/Contents/MacOS/AMDRadeonX6000HWLibs',
        'Framebuffer': extension/'AMDRadeonX6000Framebuffer.kext/Contents/MacOS/AMDRadeonX6000Framebuffer',
        'X6000': extension/'AMDRadeonX6000.kext/Contents/MacOS/AMDRadeonX6000'}.items()}
    pinned = json.loads((ROOT/'findings/baseline-identities.json').read_text())
    if kdk != {k:v['sha256'] for k,v in pinned['binaries'].items()}: raise ValueError('KDK identity changed')
    guest = json.loads((vm/'run/guest-identity.json').read_text())
    source_hash = sha((ROOT/'tests/metal_probe.m').read_bytes())
    if guest['probe_source_sha256'] != source_hash or guest['guest_build'] != '24G830':
        raise ValueError('guest probe preparation or OS build mismatch')
    image_name = os.environ.get('IMAGE', 'sickcodes/docker-osx:latest')
    image_id = command(['docker', 'image', 'inspect', '--format', '{{.Id}}', image_name])
    host = host_snapshot()
    return dict(image, build_id=build['build_id'], source_sha256=source_digest,
                source_commit=command(['git', '-C', str(ROOT), 'rev-parse', 'HEAD']),
                source_clean=not bool(command(['git', '-C', str(ROOT), 'status', '--porcelain'])),
                built_from_commit=build['source_commit'], kdk_sha256=kdk,
                build_inputs_sha256=sha((ROOT/'build-support/inputs.json').read_bytes()),
                boot_args=args,
                harness_sha256={name:sha((vm/name).read_bytes()) for name in
                    ('macos-vm.sh', 'vm-supervision.py', 'sercat.py', 'agent-server.py', 'gx', 'gpu-bind.sh')},
                rom_sha256=sha((vm/'run/gpu-patched.rom').read_bytes()),
                launch_options={'BOOTDISK_MODE':'custom', 'NVRAM':'stock'},
                image_id=image_id, guest_build=guest['guest_build'], probe_source_sha256=source_hash,
                probe_binary_sha256=guest['probe_binary_sha256'], boot_id=host['boot_id'], kernel=host['kernel'],
                bootdisk_sha256=sha((vm/'OpenCore.qcow2').read_bytes()))


def prepare(vm, spec, output, gpu=True):
    card = json.loads(spec.read_text())
    candidate = vm/'run'/('candidate-'+card['candidate_version'].split('.')[-1])
    with (vm/'run/redeploy.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        pending = vm/'run/launch-pending'
        host = host_snapshot()
        if host['active_vm'] or (pending.exists() and any(pending.iterdir())):
            raise ValueError('active or pending VM prevents preparation')
        identity = current_identity(vm, candidate)
        if not identity['source_clean']: raise ValueError('commit source and tooling before preparation')
        if card['requested_diagnostic'] not in identity['boot_args'].split():
            raise ValueError('required diagnostic boot argument is absent')
        identity.update(run_id=uuid.uuid4().hex, max_seconds=card['max_seconds'],
                        gpu=gpu,
                        vfio_device='0000:7b:00.0', experiment=card['id'], spec=card,
                        candidate_directory=str(candidate.relative_to(vm)))
        identity['qemu_version'] = command(['docker', 'run', '--rm', '--entrypoint',
            'qemu-system-x86_64', identity['image_id'], '--version']).splitlines()[0]
        verify_bootdisk(vm, identity['image_id'], identity)
        identity['bootdisk_verified'] = True
        missing = required_identity(identity)
        if missing: raise ValueError('missing identity fields: '+','.join(missing))
        output.parent.mkdir(parents=True, exist_ok=True)
        write_once(output, identity)
        return identity


def verify_bootdisk(vm, image_id, expected):
    # Hashing a stale qcow2 faithfully does not prove it contains the staged ESP.
    # Inspect a converted copy while no VM owns the disk; never run this in exposure.
    with tempfile.TemporaryDirectory(prefix='verify-bootdisk-', dir=vm/'run') as temp:
        command(['docker', 'run', '--rm', '-v', str(vm/'OpenCore.qcow2')+':/bootdisk.qcow2:ro',
                 '-v', temp+':/verified', '--entrypoint', 'qemu-img', image_id,
                 'convert', '-f', 'qcow2', '-O', 'raw', '/bootdisk.qcow2', '/verified/disk.raw'], timeout=30)
        got = image_files(Path(temp)/'disk.raw')
        errors = validate_identity({k:expected[k] for k in got}, got)
        if errors: raise ValueError('actual bootdisk differs from staged ESP: '+','.join(errors))


def sha(data):
    return hashlib.sha256(data).hexdigest()


def image_files(image, offset=1048576):
    address = str(image) + (f'@@{offset}' if offset else '')
    def read(name):
        return subprocess.check_output(['mtype', '-i', address, '::/EFI/OC/'+name],
                                       env=dict(os.environ, MTOOLS_SKIP_CHECK='1'), timeout=15)
    return {'binary_sha256': sha(read('Kexts/RaphaelGPU.kext/Contents/MacOS/RaphaelGPU')),
            'info_sha256': sha(read('Kexts/RaphaelGPU.kext/Contents/Info.plist')),
            'config_sha256': sha(read('config.plist'))}


def stage_image(image, bundle, config, offset=1048576):
    """Caller must hold VM lock and establish no active VM. Never edit in place."""
    binary = (bundle / 'Contents/MacOS/RaphaelGPU').read_bytes()
    info = (bundle / 'Contents/Info.plist').read_bytes()
    if not binary or not info or not config: raise ValueError('incomplete staging input')
    expected = dict(binary_sha256=sha(binary), info_sha256=sha(info), config_sha256=sha(config))
    with tempfile.TemporaryDirectory(prefix='rgpu-stage-', dir=image.parent) as temp:
        stage = Path(temp) / image.name
        shutil.copyfile(image, stage)
        configuration = Path(temp) / 'config.plist'
        configuration.write_bytes(config)
        address = str(stage) + (f'@@{offset}' if offset else '')
        env = dict(os.environ, MTOOLS_SKIP_CHECK='1')
        subprocess.run(['mdeltree', '-i', address, '::/EFI/OC/Kexts/RaphaelGPU.kext'],
                       env=env, capture_output=True, timeout=15)
        subprocess.run(['mcopy', '-s', '-o', '-i', address, str(bundle), '::/EFI/OC/Kexts/'],
                       env=env, check=True, capture_output=True, timeout=30)
        subprocess.run(['mcopy', '-o', '-i', address, str(configuration), '::/EFI/OC/config.plist'],
                       env=env, check=True, capture_output=True, timeout=15)
        errors = validate_identity(expected, image_files(stage, offset))
        if errors: raise ValueError('ESP readback mismatch: '+','.join(errors))
        backup = image.with_name(image.name+'.backup-'+uuid.uuid4().hex)
        # Hard link retains the old inode; replace publishes the verified new one.
        os.link(image, backup)
        with stage.open('rb') as stream: os.fsync(stream.fileno())
        stage.replace(image)
        directory = os.open(image.parent, os.O_DIRECTORY)
        try: os.fsync(directory)
        finally: os.close(directory)
    return dict(expected, backup=str(backup))


def validate_identity(expected, observed):
    return [key for key, value in expected.items()
            if value is None or observed.get(key) != value]


def admit(manifest, host, used_boots):
    errors = []
    for key in ('amdgpu_initialized', 'capture_ready', 'watchdogs_verified',
                'device_pinned_awake', 'device_accessible'):
        if host.get(key) is not True:
            errors.append(key)
    if host.get('active_vm') is not False: errors.append('active_vm')
    if not host.get('boot_id') or host['boot_id'] != manifest.get('boot_id'):
        errors.append('boot_id')
    if host.get('boot_id') in used_boots: errors.append('boot_already_used')
    if host.get('driver') != 'vfio-pci': errors.append('driver')
    if host.get('device') != '1002:13c0': errors.append('device')
    if host.get('iommu_group') != '31': errors.append('iommu_group')
    if manifest.get('source_clean') is not True: errors.append('source_clean')
    if manifest.get('vfio_device') != '0000:7b:00.0': errors.append('vfio_device')
    if type(manifest.get('max_seconds')) is not int or manifest['max_seconds'] != 180:
        errors.append('max_seconds')
    return errors


def write_once(path, value):
    """O_EXCL is the reservation. A crash leaves a consumed path, never a retry."""
    with Path(path).open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    fd = os.open(Path(path).parent, os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)


def reserve_boot(directory, boot_id, experiment):
    if not re.fullmatch(r'[A-Za-z0-9-]+', boot_id):
        raise ValueError('invalid host boot ID')
    directory.mkdir(parents=True, exist_ok=True)
    write_once(directory / (boot_id+'.json'), {'boot_id': boot_id, 'experiment': experiment})


def probe_fits(now, launch_deadline, container_deadline, probe_seconds=45, cleanup_seconds=25):
    if launch_deadline is None or container_deadline is None: return False
    return now + probe_seconds + cleanup_seconds < min(launch_deadline, container_deadline)


def validate_running(manifest, observed):
    errors = []
    if manifest['image_id'] != observed.get('image_id'): errors.append('image_id')
    vfio = observed.get('vfio_args', [])
    if manifest.get('gpu') is False:
        if vfio: errors.append('unexpected_vfio_device')
        return errors
    if len(vfio) != 1 or 'host='+manifest['vfio_device'] not in vfio[0].split(','):
        errors.append('vfio_device')
    return errors


def running_identity(cid):
    # Never print complete argv: Apple's SMC argument contains a key. Only PCI
    # passthrough options and a digest of all argv are retained.
    script = '''import os,json,hashlib
rows=[]
for pid in os.listdir('/proc'):
 if not pid.isdigit():continue
 try:raw=open('/proc/'+pid+'/cmdline','rb').read();args=raw.split(b'\\0')
 except OSError:continue
 if args and args[0].split(b'/')[-1]==b'qemu-system-x86_64':
  rows.append({'vfio_args':[a.decode() for a in args if a.startswith(b'vfio-pci,')], 'argv_sha256':hashlib.sha256(raw).hexdigest()})
assert len(rows)==1
print(json.dumps(rows[0]))
'''
    data = json.loads(command(['docker', 'exec', cid, 'python3', '-c', script]))
    data['image_id'] = command(['docker', 'inspect', '--format', '{{.Image}}', cid])
    return data


def kernel_updates(cursor=None):
    args = ['journalctl', '-k', '-b', '--no-pager', '--show-cursor', '-o', 'json']
    args += ['--after-cursor', cursor] if cursor else ['-n', '0']
    data = command(args, timeout=2)
    marker = re.search(r'^-- cursor: (.+)$', data, re.M)
    if not marker: raise RuntimeError('host kernel capture cursor unavailable')
    messages = []
    for line in data.splitlines():
        if line.startswith('{'):
            row = json.loads(line)
            if isinstance(row.get('MESSAGE'), str): messages.append(row['MESSAGE'])
    faults = [message for message in messages if re.search(
        r'BUG:|Oops:|Hardware Error|IO_PAGE_FAULT|hard LOCKUP|soft lockup|AMD-Vi:.*fault', message, re.I)]
    return marker[1], messages, faults


def run_probe(vm, manifest):
    metal = helper('metal-test')
    nonce = manifest['run_id']
    binary = '/var/tmp/rgpu-metal-'+manifest['probe_source_sha256'][:16]+'/probe'
    action = (f'permit=$(/usr/bin/curl -fsS --max-time 3 http://10.0.2.2:8889/metal-permit-{nonce}) && '
              f'test "$permit" = {shlex.quote(nonce)} && '
              f'test "$(/usr/bin/sw_vers -buildVersion)" = {shlex.quote(manifest["guest_build"])} && '
              f'test "$(/usr/bin/openssl dgst -sha256 {shlex.quote(binary)} | /usr/bin/awk \'{{print $NF}}\')" = '
              f'{shlex.quote(manifest["probe_binary_sha256"])} && '
              f'{shlex.quote(binary)} {shlex.quote(nonce)} {int(time.time())+60}')
    shell = f'( {action}; result=$?; printf "\\nRGPU_EXIT {nonce} %s\\n" "$result" )'
    result = metal.run_guest_command(vm, shell, nonce, dict(os.environ, GX_TIMEOUT='48'),
                                    timeout=50, execution_grace=0)
    return dict(run_id=nonce, output=result.stdout, transport_exit=result.returncode)


def run_one(vm, manifest_path, output):
    """One launch, no handoff/reset/retry. Failure permanently consumes this boot."""
    manifest = json.loads(manifest_path.read_text())
    missing = required_identity(manifest)
    if missing: raise ValueError('incomplete prepared identity: '+','.join(missing))
    if manifest.get('bootdisk_verified') is not True:
        raise ValueError('actual bootdisk content has not been verified')
    supervisor = helper('vm-supervision'); classifier = helper('classify-run')
    state = None; probe = None; failure = None; shutdown_result = None; host_messages = []
    output.mkdir(parents=True, exist_ok=False)
    write_once(output/'manifest.json', manifest)
    def cancelled(signum, frame): raise RuntimeError('experiment cancelled')
    previous = signal.signal(signal.SIGTERM, cancelled)
    try:
        with (vm/'run/experiment.lock').open('a') as owner:
            fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with (vm/'run/redeploy.lock').open('a') as media:
                fcntl.flock(media, fcntl.LOCK_EX | fcntl.LOCK_NB)
                pending = vm/'run/launch-pending'; pending.mkdir(exist_ok=True)
                if any(pending.iterdir()): raise ValueError('another supervised launch is pending')
                observed = current_identity(vm, vm/manifest['candidate_directory'])
                errors = validate_identity({key:manifest[key] for key in observed if key in manifest}, observed)
                host = host_snapshot(); write_once(output/'host-before.json', host)
                used = vm/'run/used-gpu-boots'; used.mkdir(exist_ok=True)
                if manifest.get('gpu') is False:
                    if host['active_vm']: errors.append('active_vm')
                else:
                    errors += admit(manifest, host, {p.stem for p in used.glob('*.json')})
                if not host['sleep_inhibited']: errors.append('sleep_inhibited')
                if errors: raise ValueError('admission refused: '+','.join(errors))
                if manifest.get('gpu') is not False:
                    reserve_boot(used, host['boot_id'], manifest['run_id'])
                cursor, _, _ = kernel_updates()
                (vm/'run/serial.log').write_text('')
                launch_requested = time.time()
                # Lock already held. start_locked creates its durable reservation
                # before invoking systemd, and owns all cleanup on partial launch.
                launch_env = dict(manifest['launch_options'], IMAGE=manifest['image_id'])
                old_env = {k:os.environ.get(k) for k in launch_env}
                os.environ.update(launch_env)
                gpu_args = [] if manifest.get('gpu') is False else [
                    '--gpu', manifest['vfio_device'], '--gpu-id', '0x73ff', '--gpu-rom', 'run/gpu-patched.rom']
                try:
                    state = supervisor.start_locked(vm, manifest['max_seconds'], gpu_args)
                finally:
                    for key,value in old_env.items():
                        if value is None: os.environ.pop(key, None)
                        else: os.environ[key] = value
                state['launch_deadline_epoch'] = launch_requested+manifest['max_seconds']
                write_once(output/'supervision.json', state)
            running = running_identity(state['cid']); write_once(output/'running-identity.json', running)
            errors = validate_running(manifest, running)
            if errors: raise ValueError('running identity mismatch: '+','.join(errors))
            end = min(state['launch_deadline_epoch'], state['deadline_epoch'])-25
            decisive_since = None
            next_host_check = 0
            while time.time() < end:
                supervisor.verify(state)
                if time.time() >= next_host_check:
                    cursor, messages, faults = kernel_updates(cursor)
                    host_messages.extend(messages)
                    if faults: raise RuntimeError('new host kernel fault during exposure')
                    next_host_check = time.time()+3
                serial = (vm/'run/serial.log').read_text(errors='replace')
                events = classifier.parse_serial(serial)
                if any(e['kind'] == 'capture_loss' and e.get('reason') in
                       ('overflow', 'conflicting replay') for e in events):
                    raise RuntimeError('definitive critical capture loss; aborting exposure')
                if manifest.get('gpu') is False and any(e['kind'] == 'build' and
                        e['build'] == manifest['build_id'] for e in events) and not any(
                        e['kind'] == 'capture_loss' for e in events):
                    break
                result = classifier.classify(manifest, events, None)
                if result['verdict'] == 'PROBE_NOT_RUN':
                    if manifest['spec'].get('run_probe_only_after_native_start') is True and probe_fits(time.time(), state['launch_deadline_epoch'], state['deadline_epoch'],
                                  probe_seconds=50):
                        probe = run_probe(vm, manifest)
                    break
                if result['verdict'] not in ('INCONCLUSIVE',):
                    if decisive_since is None: decisive_since = time.time()
                    if time.time()-decisive_since >= 2: break
                time.sleep(0.5)
            shutdown_result = supervisor.shutdown(state, grace=20)
    except BaseException as error:
        failure = type(error).__name__+': '+str(error)
        if isinstance(error, getattr(supervisor, 'ManagedStopUnconfirmed', type(None))):
            shutdown_result = dict(outcome='STOP_UNCONFIRMED', error=str(error))
        if state:
            try:
                supervisor.stop_exact(state['cid'])
                shutdown_result = dict(cid=state['cid'], outcome='forced-after-abort')
            except Exception as stop_error:
                shutdown_result = dict(cid=state['cid'], outcome='STOP_UNCONFIRMED', error=str(stop_error))
    finally:
        signal.signal(signal.SIGTERM, previous)
    serial = (vm/'run/serial.log').read_text(errors='replace') if state else ''
    (output/'serial.txt').write_text(serial)
    events = classifier.parse_serial(serial)
    (output/'events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events))
    if probe is not None: write_once(output/'probe.json', probe)
    write_once(output/'shutdown.json', shutdown_result)
    write_once(output/'host-after.json', host_snapshot())
    write_once(output/'host-kernel-messages.json', host_messages)
    result = classifier.classify(manifest, events, probe)
    if manifest.get('gpu') is False and not failure:
        result.update(valid=False, verdict='GPULESS_CAPTURE_CHECK',
                      next_action='no GPU execution tested; inspect captured build and cleanup')
    if failure:
        result.update(valid=False, verdict='INVALID', error=failure)
    if shutdown_result and shutdown_result['outcome'] == 'STOP_UNCONFIRMED':
        result.update(valid=False, verdict='STOP_UNCONFIRMED')
    write_once(output/'verdict.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'run', 'host'])
    parser.add_argument('--vm-dir', type=Path, required=True)
    parser.add_argument('--spec', type=Path)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--gpu-less', action='store_true', help='prepare a no-passthrough coordinator validation')
    args = parser.parse_args()
    if args.action == 'host': result = host_snapshot()
    elif args.action == 'prepare':
        if not args.spec or not args.output: parser.error('prepare requires --spec and --output')
        result = prepare(args.vm_dir.resolve(), args.spec, args.output, gpu=not args.gpu_less)
    else:
        if not args.manifest or not args.output: parser.error('run requires --manifest and --output')
        result = run_one(args.vm_dir.resolve(), args.manifest, args.output)
    print(json.dumps(result, indent=2))
