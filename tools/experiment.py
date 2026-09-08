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
import struct
import threading

ROOT = Path(__file__).resolve().parents[1]
BOOT_GUID = '7C436110-AB2A-4BBB-A880-FE41995C9F82'
RAPHAEL_DEVICE_PATH = 'PciRoot(0x0)/Pci(0x6,0x0)'
RAPHAEL_TARGET_KEY = 'rgpu,raphael-target'
RAPHAEL_TARGET_MARKER = b'RGPU-RAPHAEL\x01'


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
    reset_method_text = read(device/'reset_method')
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
                reset_methods=(None if reset_method_text is None else
                               reset_method_text.split()),
                active_vm=any(n == 'macos-sequoia' or n.startswith('rgpu-launch-') for n in active.splitlines()),
                sleep_inhibited=subprocess.run(['systemctl', '--user', 'is-active', '--quiet',
                                                'rgpu-work-inhibit.service']).returncode == 0)


IDENTITY_FIELDS = ('source_commit', 'source_sha256', 'build_id', 'binary_sha256', 'info_sha256',
                   'config_sha256', 'boot_args', 'kdk_sha256', 'image_id', 'qemu_version',
                   'guest_build', 'probe_source_sha256', 'probe_binary_sha256', 'boot_id',
                   'kernel', 'bootdisk_sha256', 'build_inputs_sha256', 'run_id',
                   'harness_sha256', 'rom_sha256', 'launch_options')


def required_identity(data):
    missing = [key for key in IDENTITY_FIELDS if not data.get(key)]
    if type(data.get('gpu')) is not bool: missing.append('gpu')
    return missing


def boot_argument_errors(args, requested_diagnostic):
    switches = {word.split('=', 1)[0]:word.split('=', 1)[1]
                for word in args.split() if '=' in word}
    required = dict(rgpu='0xfffa5981', rgpuvmm='3', rgpumem='2', rgpuptb='2',
                    rgpumqd='2', rgpuhybrid='1')
    errors = []
    if any(switches.get(key) != value for key,value in required.items()):
        errors.append('functional_baseline')
    if not requested_diagnostic or requested_diagnostic not in args.split():
        errors.append('requested_diagnostic')
    if any(key in switches for key in ('rgpucp', 'rgpureset', 'rgpuic', 'rgpurlc', 'rgpufb')):
        errors.append('retired_experiment')
    return errors


def raphael_target_marked(config):
    props = config.get('DeviceProperties', {}).get('Add', {}).get(RAPHAEL_DEVICE_PATH, {})
    return (isinstance(props.get('ATY,bin_image'), bytes) and
            props.get(RAPHAEL_TARGET_KEY) == RAPHAEL_TARGET_MARKER)


def current_identity(vm, candidate, requested_diagnostic):
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
    parsed_config = plist(config)
    if not raphael_target_marked(parsed_config):
        raise ValueError('OpenCore config lacks the exact per-device Raphael target marker')
    args = parsed_config['NVRAM']['Add'][BOOT_GUID]['boot-args']
    boot_errors = boot_argument_errors(args, requested_diagnostic)
    if boot_errors:
        raise ValueError('boot arguments changed: '+','.join(boot_errors))
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
        identity = current_identity(vm, candidate, card['requested_diagnostic'])
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


def admit(manifest, host, used_boots, reuse_allowed=False):
    errors = []
    for key in ('amdgpu_initialized', 'capture_ready', 'watchdogs_verified',
                'device_pinned_awake', 'device_accessible'):
        if host.get(key) is not True:
            errors.append(key)
    if host.get('active_vm') is not False: errors.append('active_vm')
    if host.get('reset_methods') != []: errors.append('reset_method')
    if not host.get('boot_id') or host['boot_id'] != manifest.get('boot_id'):
        errors.append('boot_id')
    if host.get('boot_id') in used_boots and not reuse_allowed:
        errors.append('boot_already_used')
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


def read_boot_ledger(path):
    value = json.loads(Path(path).read_text())
    if 'launches' not in value and 'experiment' in value:
        return {'schema':2, 'boot_id':value['boot_id'], 'max_launches':3,
                'launches':[{'run_id':value['experiment'], 'legacy':True}]}
    return value


RECOVERY_BAR_REGIONS = {
    '0': {'index':0, 'size':0x10000000, 'offset':0 << 40,
          'read':True, 'write':True, 'mmap':True},
    '2': {'index':2, 'size':0x00200000, 'offset':2 << 40,
          'read':True, 'write':True, 'mmap':True},
    '5': {'index':5, 'size':0x00080000, 'offset':5 << 40,
          'read':True, 'write':True, 'mmap':True},
}
RECOVERY_RESERVATION_MAGIC = int.from_bytes(b'RGPUKIR1', 'little')
RECOVERY_RESERVATION_VERSION = 1
RECOVERY_RESERVATION_ACTIVE = int.from_bytes(b'ACTV', 'little')
RECOVERY_HEAP_LIMIT = 0x0f000000
RECOVERY_RESERVATION_START = 0x0f000000
RECOVERY_SCRATCH_START = 0x0f100000
RECOVERY_RESERVATION_END = 0x10000000


def _recovery_checksum(prior_run_id):
    try:
        nonce_lo, nonce_hi = struct.unpack('<QQ', bytes.fromhex(prior_run_id))
    except (ValueError, TypeError, struct.error):
        return None
    values = (RECOVERY_RESERVATION_MAGIC, RECOVERY_RESERVATION_VERSION,
              RECOVERY_RESERVATION_ACTIVE, RECOVERY_HEAP_LIMIT,
              RECOVERY_RESERVATION_START, RECOVERY_SCRATCH_START,
              RECOVERY_RESERVATION_END, nonce_lo, nonce_hi)
    checksum = 0x9e3779b97f4a7c15
    for value in values:
        checksum ^= value
    return checksum & 0xffffffffffffffff


def _valid_hdp_flush(value):
    return (isinstance(value, dict) and set(value) == {'remap', 'posted_read'} and
            type(value.get('remap')) is int and value.get('remap') == 0x7f000 and
            type(value.get('posted_read')) is int and
            0 <= value['posted_read'] <= 0xffffffff and
            value['posted_read'] != 0xffffffff)


def _valid_reservation(value, prior_run_id):
    integer_keys = ('version','state','heap_limit','reservation_start',
                    'scratch_start','reservation_end','checksum')
    return (isinstance(value, dict) and
            set(value) == set(integer_keys) | {
                'run_id','consumed','consume_hdp_flush'} and
            all(type(value.get(key)) is int for key in integer_keys) and
            value.get('version') == RECOVERY_RESERVATION_VERSION and
            value.get('state') == RECOVERY_RESERVATION_ACTIVE and
            value.get('heap_limit') == RECOVERY_HEAP_LIMIT and
            value.get('reservation_start') == RECOVERY_RESERVATION_START and
            value.get('scratch_start') == RECOVERY_SCRATCH_START and
            value.get('reservation_end') == RECOVERY_RESERVATION_END and
            value.get('run_id') == prior_run_id and
            value.get('checksum') == _recovery_checksum(prior_run_id) and
            value.get('consumed') is True and
            _valid_hdp_flush(value.get('consume_hdp_flush')))


def _valid_recovery_regions(value):
    if not isinstance(value, dict):
        return False
    if set(value) != {'index','size','offset','read','write','mmap','regions'}:
        return False
    regions = value.get('regions')
    if not isinstance(regions, dict) or set(regions) != set(RECOVERY_BAR_REGIONS):
        return False
    for index, expected in RECOVERY_BAR_REGIONS.items():
        observed = regions.get(index)
        if (not isinstance(observed, dict) or set(observed) != set(expected) or
                any(type(observed.get(key)) is not type(want)
                    for key, want in expected.items())):
            return False
    top = {key:value.get(key) for key in ('index','size','offset','read','write','mmap')}
    return (all(type(top.get(key)) is type(want)
                for key, want in RECOVERY_BAR_REGIONS['5'].items()) and
            top == RECOVERY_BAR_REGIONS['5'] and regions == RECOVERY_BAR_REGIONS)


def _valid_gart(value):
    keys = {'control','root','start_page','end_page','physical_fb',
            'bar_offset','size','active'}
    if not isinstance(value, dict) or set(value) != keys:
        return False
    if any(type(value.get(key)) is not int for key in
           ('control','root','start_page','end_page','physical_fb','size')):
        return False
    active = value.get('active')
    if type(active) is not bool:
        return False
    if value['physical_fb'] <= 0 or value['physical_fb'] & 0xffffff:
        return False
    if not active:
        return (value['control'] & 7) == 0 and (value['root'] & 1) == 0 and \
               value['start_page'] == 0 and value['end_page'] == 0 and \
               value['bar_offset'] is None and value['size'] == 0
    offset = value.get('bar_offset')
    flags = value['root'] & 0xfff
    expected_size = (value['end_page'] - value['start_page'] + 1) * 8
    return ((value['control'] & 7) == 1 and flags in (1, 5) and
            value['end_page'] >= value['start_page'] and
            type(offset) is int and offset >= 0 and
            value['size'] == expected_size and 0 < value['size'] <= 0x10000000 and
            (value['root'] & ~0xfff) - value['physical_fb'] == offset and
            offset + value['size'] <= 0x10000000 and
            not (offset < RECOVERY_RESERVATION_END and
                 RECOVERY_SCRATCH_START < offset + value['size']))


def _valid_host_kiq(value, reservation, gc):
    if not isinstance(value, dict):
        return False
    expected_keys = {'status','selector','packet_dwords','rptr_after',
                     'fence_sequence','fence_after','gfx_active_after_unmap',
                     'gfx_active_before_scrub','gfx_doorbell_offset','addresses',
                     'gart','reservation','hdp_flush','cleanup_confirmed','cleanup',
                     'final_gate'}
    if set(value) != expected_keys:
        return False
    fence = value.get('fence_sequence')
    addresses = value.get('addresses')
    cleanup = value.get('cleanup')
    gate = value.get('final_gate')
    integer_fields = ('selector','packet_dwords','rptr_after','fence_sequence',
                      'fence_after','gfx_active_after_unmap',
                      'gfx_active_before_scrub','gfx_doorbell_offset')
    if (any(type(value.get(key)) is not int for key in integer_fields) or
            value.get('status') != 'retired' or value.get('selector') != 9 or
            value.get('packet_dwords') != 0x100 or
            value.get('rptr_after') != 0x100 or
            type(fence) is not int or not 1 <= fence <= 0xffffffff or
            value.get('fence_after') != fence or
            value.get('gfx_active_after_unmap') != 0 or
            value.get('gfx_active_before_scrub') != 0 or
            value.get('gfx_doorbell_offset') != 0x400 or
            value.get('reservation') != reservation or
            not _valid_hdp_flush(value.get('hdp_flush')) or
            not _valid_gart(value.get('gart')) or
            value.get('cleanup_confirmed') is not True):
        return False
    if not isinstance(addresses, dict) or set(addresses) != {
            'ring','mqd','rptr','wptr','eop','fence'}:
        return False
    if any(type(addresses[key]) is not int for key in addresses):
        return False
    fb_base = addresses['ring'] - 0x0f100000
    if fb_base <= 0 or fb_base & 0xffffff:
        return False
    expected_addresses = {name:fb_base+offset for name,offset in {
        'ring':0x0f100000, 'mqd':0x0f110000, 'rptr':0x0f111000,
        'wptr':0x0f111008, 'eop':0x0f112000, 'fence':0x0f113000}.items()}
    if addresses != expected_addresses:
        return False
    cleanup_keys = {'mec_cntl','hqd_active','hqd_doorbell','hqd_rptr',
                    'hqd_wptr_lo','hqd_wptr_hi','pq_status',
                    'doorbell_range_lower','doorbell_range_upper','wptr_poll_cntl'}
    if (not isinstance(cleanup, dict) or set(cleanup) != cleanup_keys or
            any(type(cleanup.get(key)) is not int for key in cleanup_keys)):
        return False
    if (cleanup['mec_cntl'] & 0x50000000 != 0x50000000 or
            cleanup.get('hqd_active') != 0 or cleanup.get('hqd_doorbell') != 0 or
            cleanup.get('hqd_rptr') != 0 or cleanup.get('hqd_wptr_lo') != 0 or
            cleanup.get('hqd_wptr_hi') != 0 or
            type(cleanup.get('pq_status')) is not int or cleanup['pq_status'] & 2 or
            cleanup.get('doorbell_range_lower') != 0 or
            cleanup.get('doorbell_range_upper') != 0 or
            type(cleanup.get('wptr_poll_cntl')) is not int or
            cleanup['wptr_poll_cntl'] & 0x80000000):
        return False
    expected_gate = {key:gc.get(key) for key in (
        'active_after','cp_stat_after','cp_cpc_busy_after','pq_wptr_poll_after',
        'pq_status_after','doorbell_range_lower_after','doorbell_range_upper_after',
        'gfx_ring_clean','gfx_retirement_confirmed')}
    return (isinstance(gate, dict) and set(gate) == set(expected_gate) and
            all(type(gate.get(key)) is type(expected) and gate.get(key) == expected
                for key, expected in expected_gate.items()))


def validate_recovery_receipt(receipt, boot_id, prior_run_id):
    errors = []
    exact = {'schema':3, 'status':'recovered', 'authorizes_launch':True,
             'boot_id':boot_id,
             'prior_run_id':prior_run_id, 'device':'0000:7b:00.0',
             'iommu_group':'31', 'driver':'vfio-pci'}
    if any(receipt.get(key) != value for key,value in exact.items()):
        errors.append('recovery_receipt')
    if not re.fullmatch(r'[0-9a-f]{32}', str(receipt.get('recovery_id', ''))):
        errors.append('recovery_receipt')
    for key in ('pci_command_before', 'pci_command_after'):
        value = receipt.get(key)
        if type(value) is not int or value & 4: errors.append('recovery_receipt')
    if (receipt.get('reset_methods_before') != [] or
            receipt.get('reset_methods_after') != []):
        errors.append('recovery_receipt')
    if not _valid_recovery_regions(receipt.get('bar5')):
        errors.append('recovery_receipt')
    messages = receipt.get('kernel_messages')
    if (not isinstance(messages, list) or
            any(not isinstance(message, str) for message in messages) or
            any(re.search(r'vfio-pci 0000:7b:00\.0: (?:resetting|reset done)\b',
                          message, re.I) for message in messages)):
        errors.append('recovery_receipt')
    gc = receipt.get('gc_quiesce')
    exact_zero_gc = ('active_after','dequeue_timeouts','forced_inactive',
                     'cp_stat_after','cp_cpc_busy_after',
                     'doorbell_range_lower_after','doorbell_range_upper_after',
                     'gfx_rb_active_after','gfx_rb_doorbell_after',
                     'gfx_rb_wptr_after','gfx_rb_wptr_hi_after',
                     'gfx_rb_base_after','gfx_rb_base_hi_after','gfx_rb_cntl_after')
    if (not isinstance(gc, dict) or
            any(type(gc.get(key)) is not int or gc.get(key) != 0
                for key in exact_zero_gc) or
            gc.get('status') != 'quiesced' or
            type(gc.get('cp_me_after')) is not int or
            gc['cp_me_after'] & 0x15000000 != 0x15000000 or
            type(gc.get('cp_mec_after')) is not int or
            gc['cp_mec_after'] & 0x50000000 != 0x50000000 or
            type(gc.get('pq_wptr_poll_after')) is not int or
            gc['pq_wptr_poll_after'] & 0x80000000 != 0 or
            type(gc.get('pq_status_after')) is not int or
            gc['pq_status_after'] & 2 != 0 or
            type(gc.get('sdma0_after')) is not int or gc['sdma0_after'] & 1 != 1 or
            type(gc.get('sdma0_cntl_after')) is not int or
            gc['sdma0_cntl_after'] & 0x00040000 != 0 or
            type(gc.get('sdma0_rb_after')) is not int or gc['sdma0_rb_after'] & 1 != 0 or
            type(gc.get('sdma0_ib_after')) is not int or gc['sdma0_ib_after'] & 1 != 0 or
            gc.get('gfx_ring_clean') is not True or
            gc.get('gfx_retirement_confirmed') is not True):
        errors.append('recovery_receipt')
    if isinstance(gc, dict):
        reservation = gc.get('reservation')
        if not _valid_reservation(reservation, prior_run_id):
            errors.append('recovery_receipt')
        host_kiq = gc.get('host_kiq')
        if gc.get('gfx_needs_unmap') is True:
            if not _valid_host_kiq(host_kiq, reservation, gc):
                errors.append('recovery_receipt')
        elif (gc.get('gfx_needs_unmap') is not False or
              host_kiq != {'status':'not-needed'}):
            errors.append('recovery_receipt')
    commands = receipt.get('commands')
    if (not isinstance(commands, list) or len(commands) != 2 or
            [row.get('command') for row in commands] != [0x00030000, 0x000c0000] or
            any(row.get('confirmed') is not True for row in commands) or
            any(type(row.get('response')) is not int or
                (row['response'] & 0x8000ffff) != 0x80000000 or
                ((row['response'] >> 16) & 0x7fff) != (row['command'] >> 16)
                for row in commands)):
        errors.append('recovery_receipt')
    return sorted(set(errors))


def reuse_authorization(vm, boot_id, run_id):
    path = vm/'run/used-gpu-boots'/(boot_id+'.json')
    if not path.exists(): return None, []
    try: ledger = read_boot_ledger(path)
    except (OSError, ValueError, KeyError): return None, ['boot_ledger']
    launches = ledger.get('launches')
    if not isinstance(launches, list) or not launches: return None, ['boot_ledger']
    if any(row.get('run_id') == run_id for row in launches): return None, ['run_id_reused']
    if len(launches) >= 3: return None, ['launch_ceiling']
    prior = launches[-1].get('run_id')
    receipt_path = vm/'run/vfio-recovery'/boot_id/(str(prior)+'.json')
    try: receipt = json.loads(receipt_path.read_text())
    except (OSError, ValueError): return None, ['recovery_receipt']
    errors = validate_recovery_receipt(receipt, boot_id, prior)
    if receipt.get('recovery_id') in {row.get('recovery_id') for row in launches}:
        errors.append('recovery_receipt')
    return (receipt if not errors else None), sorted(set(errors))


def replace_json(path, value):
    path = Path(path)
    temp = path.with_name(path.name+'.new-'+uuid.uuid4().hex)
    try:
        with temp.open('x') as stream:
            json.dump(value, stream, indent=2)
            stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        temp.replace(path)
        directory = os.open(path.parent, os.O_DIRECTORY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        temp.unlink(missing_ok=True)


def reserve_boot(directory, boot_id, experiment, recovery=None):
    if not re.fullmatch(r'[A-Za-z0-9-]+', boot_id):
        raise ValueError('invalid host boot ID')
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (boot_id+'.json')
    if not path.exists():
        write_once(path, {'schema':2, 'boot_id':boot_id, 'max_launches':3,
                          'launches':[{'run_id':experiment, 'reserved_epoch':time.time()}]})
        return
    if recovery is None: raise FileExistsError(path)
    ledger = read_boot_ledger(path); launches = ledger.get('launches', [])
    prior = launches[-1].get('run_id') if launches else None
    errors = validate_recovery_receipt(recovery, boot_id, prior)
    if len(launches) >= 3: errors.append('launch_ceiling')
    if any(row.get('run_id') == experiment for row in launches): errors.append('run_id_reused')
    if recovery.get('recovery_id') in {row.get('recovery_id') for row in launches}:
        errors.append('recovery_receipt')
    if errors: raise ValueError('reuse reservation refused: '+','.join(sorted(set(errors))))
    launches.append({'run_id':experiment, 'reserved_epoch':time.time(),
                     'recovery_id':recovery['recovery_id'], 'prior_run_id':prior})
    ledger.update(schema=2, boot_id=boot_id, max_launches=3, launches=launches)
    ledger.pop('experiment', None)
    replace_json(path, ledger)


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


class HostMonitor:
    """Keep journal capture live across blocking startup, probe, and shutdown."""
    def __init__(self, cursor, interrupt, interval=1):
        self.cursor = cursor; self.interrupt = interrupt; self.interval = interval
        self.messages = []; self.error = None; self.error_kind = None
        self.done = threading.Event()
        self.thread = threading.Thread(target=self.watch, name='rgpu-host-monitor')

    def poll(self):
        try:
            self.cursor, messages, faults = kernel_updates(self.cursor)
            self.messages.extend(messages)
            if faults:
                self.error_kind = 'fault'
                # error is the publication flag read by the main thread; its
                # kind must already be visible when that flag becomes non-null.
                self.error = 'new host kernel fault during exposure'
        except Exception as error:
            # Never demote a detected hardware/kernel fault if the capture
            # channel itself also fails during cleanup.
            if self.error_kind != 'fault':
                self.error_kind = 'capture'
                self.error = 'host kernel capture failed: '+str(error)

    def watch(self):
        while not self.done.wait(self.interval):
            self.poll()
            if self.error:
                self.interrupt()
                return

    def start(self): self.thread.start()

    def stop(self):
        self.done.set()
        self.thread.join()  # kernel_updates itself is bounded to two seconds.
        self.poll()  # Include faults emitted during cleanup before any verdict.


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
    """One bounded launch; a verified prior recovery may authorize same-boot reuse."""
    manifest = json.loads(manifest_path.read_text())
    missing = required_identity(manifest)
    if missing: raise ValueError('incomplete prepared identity: '+','.join(missing))
    if manifest.get('bootdisk_verified') is not True:
        raise ValueError('actual bootdisk content has not been verified')
    supervisor = helper('vm-supervision'); classifier = helper('classify-run')
    guest_shutdown = helper('guest-shutdown')
    state = None; probe = None; failure = None; shutdown_result = None; host_messages = []
    recovery_result = None
    running_validated = False
    monitor = None
    output.mkdir(parents=True, exist_ok=False)
    write_once(output/'manifest.json', manifest)
    def cancelled(signum, frame): raise RuntimeError('experiment cancelled')
    def host_fault(signum, frame): raise RuntimeError(monitor.error or 'host monitor aborted exposure')
    previous = signal.signal(signal.SIGTERM, cancelled)
    previous_fault = signal.signal(signal.SIGUSR1, host_fault)
    try:
        with (vm/'run/experiment.lock').open('a') as owner:
            fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with (vm/'run/redeploy.lock').open('a') as media:
                fcntl.flock(media, fcntl.LOCK_EX | fcntl.LOCK_NB)
                pending = vm/'run/launch-pending'; pending.mkdir(exist_ok=True)
                if any(pending.iterdir()): raise ValueError('another supervised launch is pending')
                requested = manifest.get('spec', {}).get('requested_diagnostic')
                observed = current_identity(vm, vm/manifest['candidate_directory'], requested)
                errors = validate_identity({key:manifest[key] for key in observed if key in manifest}, observed)
                host = host_snapshot(); write_once(output/'host-before.json', host)
                used = vm/'run/used-gpu-boots'; used.mkdir(exist_ok=True)
                recovery = None; reuse_errors = []
                if manifest.get('gpu') is False:
                    if host['active_vm']: errors.append('active_vm')
                else:
                    recovery, reuse_errors = reuse_authorization(vm, host['boot_id'],
                                                                  manifest['run_id'])
                    errors += reuse_errors
                    errors += admit(manifest, host, {p.stem for p in used.glob('*.json')},
                                    reuse_allowed=recovery is not None)
                if not host['sleep_inhibited']: errors.append('sleep_inhibited')
                if errors: raise ValueError('admission refused: '+','.join(errors))
                if manifest.get('gpu') is not False:
                    reserve_boot(used, host['boot_id'], manifest['run_id'], recovery)
                cursor, _, _ = kernel_updates()
                monitor = HostMonitor(cursor, lambda:os.kill(os.getpid(), signal.SIGUSR1))
                monitor.start()
                if manifest.get('gpu') is not False:
                    reservation = helper('vfio-recover').prepare_launch(
                        host['boot_id'], manifest['run_id'])
                    write_once(output/'recovery-reservation.json', reservation)
                (vm/'run/serial.log').write_text('')
                (vm/'run/agent-server-events.jsonl').unlink(missing_ok=True)
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
            running_validated = True
            end = min(state['launch_deadline_epoch'], state['deadline_epoch'])-25
            decisive_since = None
            while time.time() < end:
                supervisor.verify(state)
                if monitor.error: raise RuntimeError(monitor.error)
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
            shutdown_result = guest_shutdown.shutdown(
                vm, state, expected_build=manifest['guest_build'], grace=20)
    except BaseException as error:
        signal.signal(signal.SIGUSR1, lambda signum, frame:None)
        failure = type(error).__name__+': '+str(error)
        managed_unconfirmed = isinstance(
            error, getattr(supervisor, 'ManagedStopUnconfirmed', type(None)))
        if managed_unconfirmed:
            shutdown_result = dict(outcome='STOP_UNCONFIRMED', error=str(error))
        if state and not managed_unconfirmed:
            try:
                # A validated guest still owns live DMA mappings. Loss of the
                # journal capture channel must try guest/ACPI shutdown first;
                # an actual host kernel fault takes the shortest exact-stop path.
                if running_validated and not (
                        monitor and getattr(monitor, 'error_kind', None) == 'fault'):
                    shutdown_result = guest_shutdown.shutdown(
                        vm, state, expected_build=manifest['guest_build'], grace=20)
                else:
                    supervisor.stop_exact(state['cid'])
                    shutdown_result = dict(cid=state['cid'], outcome='forced-after-abort')
            except Exception as stop_error:
                try:
                    supervisor.stop_exact(state['cid'])
                    shutdown_result = dict(cid=state['cid'], outcome='forced-after-shutdown-error',
                                           error=str(stop_error))
                except Exception as force_error:
                    shutdown_result = dict(cid=state['cid'], outcome='STOP_UNCONFIRMED',
                                           error=str(force_error))
    finally:
        # Once cleanup is underway, retain faults without interrupting cleanup.
        signal.signal(signal.SIGUSR1, lambda signum, frame:None)
        if monitor:
            monitor.stop()
            host_messages = monitor.messages
            if monitor.error: failure = monitor.error
        signal.signal(signal.SIGUSR1, previous_fault)
        signal.signal(signal.SIGTERM, previous)
    if (manifest.get('gpu') is not False and state and shutdown_result and
            shutdown_result.get('outcome') != 'STOP_UNCONFIRMED' and
            not (monitor and monitor.error)):
        try:
            recovery_result = helper('vfio-recover').recover(vm, manifest['run_id'])
        except BaseException as error:
            recovery_result = {'status':'failed',
                               'error':type(error).__name__+': '+str(error)}
    serial = (vm/'run/serial.log').read_text(errors='replace') if state else ''
    (output/'serial.txt').write_text(serial)
    agent_events = vm/'run/agent-server-events.jsonl'
    if agent_events.is_file():
        (output/'agent-server-events.jsonl').write_bytes(agent_events.read_bytes())
    events = classifier.parse_serial(serial)
    (output/'events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events))
    if probe is not None: write_once(output/'probe.json', probe)
    write_once(output/'shutdown.json', shutdown_result)
    write_once(output/'host-after.json', host_snapshot())
    write_once(output/'host-kernel-messages.json', host_messages)
    if recovery_result is not None: write_once(output/'recovery.json', recovery_result)
    result = classifier.classify(manifest, events, probe)
    result['warm_reuse'] = (recovery_result or {'status':'not-attempted'})['status']
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
    if args.gpu_less and args.action != 'prepare':
        parser.error('--gpu-less is only valid with prepare; run uses the explicit prepared mode')
    if args.action == 'host': result = host_snapshot()
    elif args.action == 'prepare':
        if not args.spec or not args.output: parser.error('prepare requires --spec and --output')
        result = prepare(args.vm_dir.resolve(), args.spec, args.output, gpu=not args.gpu_less)
    else:
        if not args.manifest or not args.output: parser.error('run requires --manifest and --output')
        result = run_one(args.vm_dir.resolve(), args.manifest, args.output)
    print(json.dumps(result, indent=2))
