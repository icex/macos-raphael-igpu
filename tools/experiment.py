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
PRELAUNCH_CONTINUATION = {
    'boot_id':'5d6f45d0-4384-4340-b819-7751bc26ebb3',
    'run_id':'e583a1b2d97a4ad3b607c1d20a29a812',
    'original_manifest_sha256':'3e55268208543c81963b08b6fa922271324c45a9d1354f012ff069fc815796a4',
    'replacement_manifest_sha256':'535ab074affacd019ce9fb389cb9657f610d6cbf7dcca7738de5cc7d298f0ddc',
    'proof_sha256':'8ce5b30f1c2ef9dfac68b00dee29ed8254845dae64dc0832ad4a1295424b034b',
    'verdict_sha256':'071dc20ef87befa35d77e8ba445310277b75ce1349325504ee6f486de09a9ba7',
    'output_sha256':'c099c8597f3da6a0f2db059bd3fd8d1fb53280db7dddcb271ddb76fe8c6609fa',
    'readiness_sha256':'86282b2a881f86b1fd4d770ec7f066c2014aab0b957b7211c0ed6c6f996f9053',
}

V2_CRITICAL_CAPTURE_MAX_BYTES = 8 * 1024 * 1024

# This is a single reviewed revision of one historical boot's initial
# validation ceiling. It is deliberately fixed to candidate 176's immutable
# cleanup and cannot describe another boot, predecessor, or ledger preimage.
CAP_REVISION_BOOT_ID = '5d6f45d0-4384-4340-b819-7751bc26ebb3'
CAP_REVISION_PRIOR_RUN_ID = 'e02fbed46a6a4df4ae48d7c1d8597985'
CAP_REVISION_RECOVERY_ID = '11602bc7c6f84c75afb1f2cb617a319c'
CAP_REVISION_LEDGER_SHA256 = '0f45b2c01b5ea6863b01bc0777824d8da3c7ee7ea5d1b900616d44cd3a1c95da'
CAP_REVISION_CANONICAL_RECEIPT_SHA256 = '4e6c1519f18c0bb60efeb816045eb3aedf6231a0ef8746a530c768996e7e6676'
CAP_REVISION_RUN_RECEIPT_SHA256 = '77b0931dcefe4c710db724d6cedbda22acf42c3c43de2f0aba25546d396ea180'
CAP_REVISION_RANGE_AUDIT_SHA256 = 'a6ad51f95e3608f47afd951f970c3f4ed849db8ad0e0aee225790c1d26875ae2'
CAP_REVISION_CANDIDATE176_CONSUMER_SHA256 = '055e44ca0cd7c06e37a98739ccbed67e3b0578c4416c7e24fb90f2b3db0929be'
CAP_REVISION_CANDIDATE176_PRODUCER_SHA256 = '8ff51636013da702fed170933ef69f62ae15bbf91d1e59011dc140b9782ee39d'
CAP_REVISION_PURPOSE = 'm7-normal-recovery-qualification'
CAP_REVISION_AUTHORITY_FIELDS = {
    'schema', 'kind', 'boot_id', 'ledger_preimage_sha256', 'prior_run_id',
    'recovery_id', 'canonical_recovery_receipt_sha256',
    'run_recovery_receipt_sha256', 'range_audit_sha256', 'design_sha256',
    'candidate176_consumer_sha256', 'candidate176_recovery_producer_sha256',
    'candidate177_experiment_py_sha256',
    'candidate177_recovery_producer_sha256', 'manifest_sha256',
    'next_run_id', 'from_max_launches', 'to_max_launches',
    'additional_launches', 'automatic_extension', 'purpose',
}


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
    if (data.get('gpu') is True and
            data.get('recovery_lease_schema') not in (2, 3)):
        missing.append('recovery_lease_schema')
    if data.get('gpu') is True and not data.get('recovery_helpers_sha256'):
        missing.append('recovery_helpers_sha256')
    return missing


def recovery_nonce_words(run_id):
    # Apple XNU pexpert/gen/bootargs.c getval uses unsigned long long and
    # argnumcpy case 8 stores the full word; PE_boot_arg_uint64_eq uses this
    # same path. High-bit 0x-prefixed values therefore retain all 64 bits.
    if not isinstance(run_id, str) or not re.fullmatch(r'[0-9a-f]{32}', run_id):
        raise ValueError('run_id must be 32 lowercase hexadecimal characters')
    return struct.unpack('<QQ', bytes.fromhex(run_id))


def _numeric_boot_argument(value):
    if not isinstance(value, str) or not re.fullmatch(
            r'(?:0|0x[0-9a-f]+|[1-9][0-9]*)', value):
        return None
    parsed = int(value, 0)
    return parsed if parsed < 1 << 64 else None


def boot_argument_errors(args, requested_diagnostic, run_id=None):
    switch_rows = [word.split('=', 1) for word in args.split() if '=' in word]
    switches = {key:value for key,value in switch_rows}
    required = dict(rgpu='0xfffa5981', rgpuvmm='3',
                    rgpumem='1' if run_id is not None else '2', rgpuptb='2',
                    rgpumqd='2', rgpuhybrid='1')
    errors = []
    rgpu_keys = [key for key, _ in switch_rows if key.startswith('rgpu')]
    if len(rgpu_keys) != len(set(rgpu_keys)):
        errors.append('duplicate_boot_argument')
    if any(switches.get(key) != value for key,value in required.items()):
        errors.append('functional_baseline')
    if not requested_diagnostic or requested_diagnostic not in args.split():
        errors.append('requested_diagnostic')
    if any(key in switches for key in ('rgpucp', 'rgpureset', 'rgpuic', 'rgpurlc', 'rgpufb')):
        errors.append('retired_experiment')
    if run_id is not None:
        nonce_lo, nonce_hi = recovery_nonce_words(run_id)
        if (_numeric_boot_argument(switches.get('rgpurnlo')) != nonce_lo or
                _numeric_boot_argument(switches.get('rgpurnhi')) != nonce_hi):
            errors.append('recovery_nonce')
    return errors


def raphael_target_marked(config):
    props = config.get('DeviceProperties', {}).get('Add', {}).get(RAPHAEL_DEVICE_PATH, {})
    return (isinstance(props.get('ATY,bin_image'), bytes) and
            props.get(RAPHAEL_TARGET_KEY) == RAPHAEL_TARGET_MARKER)


def current_identity(vm, candidate, requested_diagnostic, run_id=None,
                     recovery_lease_schema=2):
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
    boot_errors = boot_argument_errors(args, requested_diagnostic, run_id)
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
                bootdisk_sha256=sha((vm/'OpenCore.qcow2').read_bytes()),
                recovery_helpers_sha256=(
                    helper('vfio-recover').current_recovery_helpers_sha256(
                        recovery_lease_schema)
                    if run_id is not None else None))


def prepare(vm, spec, output, gpu=True, run_id=None):
    card = json.loads(spec.read_text())
    replay_schema = critical_replay_schema(card)
    lease_schema = card.get('recovery_lease_schema', 2)
    if type(lease_schema) is not int or lease_schema not in (2, 3):
        raise ValueError('recovery lease schema must be numeric 2 or 3')
    if gpu and lease_schema == 3 and replay_schema != 2:
        raise ValueError('schema-3 recovery lease requires critical replay schema 2')
    if gpu and run_id is None:
        raise ValueError('GPU preparation requires an explicit run_id')
    if run_id is not None:
        recovery_nonce_words(run_id)
    candidate = vm/'run'/('candidate-'+card['candidate_version'].split('.')[-1])
    with (vm/'run/redeploy.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        pending = vm/'run/launch-pending'
        host = host_snapshot()
        if host['active_vm'] or (pending.exists() and any(pending.iterdir())):
            raise ValueError('active or pending VM prevents preparation')
        identity = current_identity(
            vm, candidate, card['requested_diagnostic'], run_id if gpu else None,
            lease_schema)
        if not identity['source_clean']: raise ValueError('commit source and tooling before preparation')
        if card['requested_diagnostic'] not in identity['boot_args'].split():
            raise ValueError('required diagnostic boot argument is absent')
        identity.update(run_id=run_id or uuid.uuid4().hex, max_seconds=card['max_seconds'],
                        gpu=gpu,
                        recovery_lease_schema=lease_schema if gpu else None,
                        vfio_device='0000:7b:00.0', experiment=card['id'], spec=card,
                        candidate_directory=str(candidate.relative_to(vm)))
        if replay_schema is not None:
            identity['critical_replay_schema'] = replay_schema
        tolerance = critical_replay_tolerance(card)
        if tolerance is not None:
            if replay_schema != 2:
                raise ValueError('critical replay tolerance requires schema 2 transport')
            identity['critical_replay_tolerance'] = tolerance
        recovery_tolerance = recovery_critical_replay_tolerance(card)
        if 'recovery_critical_replay_tolerance' in card:
            if not gpu or replay_schema != 2 or lease_schema != 3:
                raise ValueError(
                    'recovery critical replay tolerance requires GPU CR2 schema-3 recovery')
            identity['recovery_critical_replay_tolerance'] = recovery_tolerance
        identity['qemu_version'] = command(['docker', 'run', '--rm', '--entrypoint',
            'qemu-system-x86_64', identity['image_id'], '--version']).splitlines()[0]
        verify_bootdisk(vm, identity['image_id'], identity)
        identity['bootdisk_verified'] = True
        missing = required_identity(identity)
        if missing: raise ValueError('missing identity fields: '+','.join(missing))
        output.parent.mkdir(parents=True, exist_ok=True)
        write_once(output, identity)
        return identity


def canonical_v2_records(serial, expected_build):
    """Extract every complete v2 wire record from replay and direct logging."""
    if not isinstance(serial, str) or not isinstance(expected_build, str):
        raise ValueError('canonical critical capture has invalid arguments')
    if len(serial.encode('utf-8')) > V2_CRITICAL_CAPTURE_MAX_BYTES:
        raise ValueError('canonical critical capture exceeds its byte bound')
    serial = serial.replace('\r', '')
    if serial and not serial.endswith('\n'):
        tail = serial.rsplit('\n', 1)[-1]
        if re.search(r'(?:RaphaelGPU\s+rgpu:\s*@\s+|RGPU_EVENT\s+build=\S+\s+'
                     r'seq=\d+\s+)XH2(?:\s|$)', tail):
            raise ValueError('canonical critical capture has an incomplete protocol tail')
        serial = (serial.rsplit('\n', 1)[0] + '\n') if '\n' in serial else ''
    counts = []
    records = {}
    wire = []
    build_seen = False
    direct_builds = set()
    direct_wire = []
    structured_builds = set()
    for line in serial.splitlines():
        summary = re.search(
            r'RGPU_RECORDS build=(\S+) count=(\d+) dropped=(\d+) truncated=(\d+)',
            line)
        if summary:
            structured_builds.add(summary[1])
        if summary and summary[1] == expected_build:
            if int(summary[3]) or int(summary[4]):
                raise ValueError('canonical critical capture reports loss')
            counts.append(int(summary[2]))
        event = re.search(r'RGPU_EVENT build=(\S+) seq=(\d+) (.+)$', line)
        if event:
            structured_builds.add(event[1])
        if event and event[1] == expected_build:
            seq, payload = int(event[2]), event[3]
            previous = records.get(seq)
            if previous is not None and previous != payload:
                raise ValueError('canonical critical capture has a conflicting replay')
            records[seq] = payload
            build_seen |= payload == 'BUILD: identity='+expected_build
            if payload.startswith('XH2 '):
                wire.append(payload)
            continue
        direct = re.fullmatch(r'.*RaphaelGPU\s+rgpu:\s*@\s+(.*)', line)
        if direct:
            payload = direct[1]
            direct_build = re.fullmatch(r'BUILD: identity=(\S+)', payload)
            if direct_build:
                direct_builds.add(direct_build[1])
            build_seen |= payload == 'BUILD: identity='+expected_build
            if payload.startswith('XH2 '):
                wire.append(payload)
                direct_wire.append(payload)
    if direct_builds - {expected_build} or structured_builds - {expected_build}:
        raise ValueError('canonical critical capture has a conflicting build identity')
    if counts:
        count = max(counts)
        if count > 512:
            raise ValueError('canonical critical capture exceeds its record bound')
        if set(records) != set(range(count)) and not (
                expected_build in direct_builds and direct_wire):
            raise ValueError('canonical critical capture is incomplete')
    elif records:
        raise ValueError('canonical critical capture has events without a summary')
    if not build_seen:
        raise ValueError('canonical critical capture has no matching build identity')
    return wire


def recover_v2(recovery_tool, vm, manifest, serial, replay_evidence=None):
    """Parse and recover through one module instance to preserve strict types.

    ``replay_evidence`` receives the terminal-prefix tolerance facts (corrupt
    line count and numbers, incomplete attempts, terminal digests) whenever the
    manifest selects that tolerance, so the caller can preserve them beside the
    receipt. Strict transport leaves it untouched.
    """
    validate_manifest_replay_contract(manifest)
    lease_schema = manifest.get('recovery_lease_schema')
    if type(lease_schema) is not int or lease_schema not in (2, 3):
        raise ValueError('recovery lease schema must be numeric 2 or 3')
    if lease_schema == 3:
        if manifest.get('critical_replay_schema') != 2:
            raise ValueError('schema-3 recovery requires complete CR2 transport')
        tolerance = recovery_critical_replay_tolerance(manifest)
        replay = helper('critical-replay')
        snapshot = (replay.parse(serial, manifest['build_id']) if tolerance is None else
                    replay.parse(serial, manifest['build_id'], tolerate_corruption=True,
                                 open_attempt=tolerance == 'terminal-prefix-open'))
        open_attempt = snapshot.get('open_attempt')
        if open_attempt is not None:
            # Records the cut-off attempt added beyond the terminal prefix are
            # the only unknown; an abort among them refuses recovery outright.
            # The persistent lifetime marker is authenticated by recovery itself.
            if any('ABORT' in record for record in open_attempt['complete_records']):
                raise ValueError('open CR2 attempt records an abort')
        snapshot_records = snapshot['records']
        if tolerance is not None and replay_evidence is not None:
            replay_evidence.update({
                key: snapshot[key] for key in (
                    'tolerance', 'snapshot', 'count', 'corrupt_lines',
                    'corrupt_line_numbers', 'corrupt_reasons',
                    'incomplete_snapshots', 'crc32', 'fnv1a64')})
            replay_evidence['open_attempt'] = snapshot.get('open_attempt')
            replay_evidence['serial_sha256'] = sha(serial.encode('utf-8'))
        if any(record == 'XH2' for record in snapshot_records):
            raise ValueError('schema-3 recovery has a malformed XH2 record')
        records = [record for record in snapshot_records
                   if record.startswith('XH2 ')]
    else:
        records = canonical_v2_records(serial, manifest['build_id'])
    lease_evidence = recovery_tool.parse_v2_lease_records(
        records, manifest['run_id'])
    arguments = {
        'lease_evidence':lease_evidence,
        'recovery_helpers_sha256':manifest['recovery_helpers_sha256'],
    }
    if lease_schema == 3:
        arguments['recovery_lease_schema'] = 3
    return recovery_tool.recover(vm, manifest['run_id'], **arguments)


def parse_manifest_serial(classifier, manifest, serial):
    schema = manifest.get('critical_replay_schema')
    if schema is None:
        return classifier.parse_serial(serial)
    tolerance = critical_replay_tolerance(manifest)
    if tolerance is None:
        return classifier.parse_serial(
            serial, critical_replay_schema=schema,
            expected_build=manifest.get('build_id'))
    return classifier.parse_serial(
        serial, critical_replay_schema=schema,
        expected_build=manifest.get('build_id'),
        critical_replay_tolerance=tolerance)


def definitive_capture_loss(events):
    return any(
        event.get('kind') == 'capture_loss' and (
            event.get('definitive') is True or
            event.get('reason') in ('overflow', 'conflicting replay'))
        for event in events)


def critical_replay_schema(data):
    if 'critical_replay_schema' not in data:
        return None
    schema = data['critical_replay_schema']
    if type(schema) is not int or schema != 2:
        raise ValueError('critical replay schema must be numeric 2')
    return schema


CRITICAL_REPLAY_TOLERANCES = ('terminal-prefix', 'terminal-prefix-open')
RECOVERY_CRITICAL_REPLAY_TOLERANCES = ('terminal-prefix-open',)


def critical_replay_tolerance(data):
    """Return the reviewed CR2 corruption tolerance a card or manifest selects."""
    if 'critical_replay_tolerance' not in data:
        return None
    tolerance = data['critical_replay_tolerance']
    if tolerance not in CRITICAL_REPLAY_TOLERANCES:
        raise ValueError('critical replay tolerance must be terminal-prefix or terminal-prefix-open')
    return tolerance


def recovery_critical_replay_tolerance(data):
    """Return recovery's selector, preserving manifests created before it existed."""
    key = 'recovery_critical_replay_tolerance'
    if key not in data:
        return critical_replay_tolerance(data)
    tolerance = data[key]
    if tolerance not in RECOVERY_CRITICAL_REPLAY_TOLERANCES:
        raise ValueError(
            'recovery critical replay tolerance must be terminal-prefix-open')
    return tolerance


def validate_manifest_replay_contract(manifest):
    """Bind a new recovery-only selector to the embedded experiment card."""
    critical_replay_schema(manifest)
    critical_replay_tolerance(manifest)
    key = 'recovery_critical_replay_tolerance'
    spec = manifest.get('spec')
    manifest_has_selector = key in manifest
    card_has_selector = isinstance(spec, dict) and key in spec
    if not manifest_has_selector and not card_has_selector:
        return None
    recovery_tolerance = recovery_critical_replay_tolerance(manifest)
    if (not manifest_has_selector or not card_has_selector or
            spec.get(key) != recovery_tolerance):
        raise ValueError(
            'recovery critical replay tolerance does not match experiment card')
    if (manifest.get('gpu') is not True or
            manifest.get('critical_replay_schema') != 2 or
            manifest.get('recovery_lease_schema') != 3):
        raise ValueError(
            'recovery critical replay tolerance requires GPU CR2 schema-3 recovery')
    return None


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


def write_bytes_once(path, value):
    """Durably preserve already authenticated bytes under an exclusive path."""
    if not isinstance(value, bytes):
        raise TypeError('exclusive byte evidence must be bytes')
    with Path(path).open('xb') as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())
    fd = os.open(Path(path).parent, os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)


def evidence_digest(directory):
    """Bind a continuation to every regular file in immutable prior evidence."""
    rows = []
    for path in sorted(Path(directory).iterdir(), key=lambda item:item.name):
        if not path.is_file() or path.is_symlink():
            raise ValueError('original output contains unsupported entries')
        rows.append({'name':path.name, 'sha256':sha(path.read_bytes())})
    return sha(json.dumps(rows, sort_keys=True, separators=(',', ':')).encode()), rows


def active_launch_units():
    result = subprocess.run([
        'systemctl', '--user', 'list-units', '--all', '--plain',
        '--no-legend', 'rgpu-launch-*', 'rgpu-serial-*', 'rgpu-deadline-*'],
        text=True, capture_output=True, timeout=10)
    if result.returncode:
        raise RuntimeError('cannot establish launch-unit state: '+result.stderr.strip())
    return [line.split()[0] for line in result.stdout.splitlines() if line.split()]


def current_qemu_version(image_id):
    return command(['docker', 'run', '--rm', '--entrypoint', 'qemu-system-x86_64',
                    image_id, '--version']).splitlines()[0]


def prelaunch_continuation_marker(vm, boot_id, run_id):
    return vm/'run/prelaunch-continuations'/(boot_id+'-'+run_id+'.json')


def validate_prelaunch_continuation(vm, manifest_path, manifest, original_output,
                                    proof_path, observed, host, cursor_result):
    """Validate the single known EINVAL prelaunch failure without general retries."""
    errors = []
    original_output = Path(original_output)
    proof_path = Path(proof_path)
    original_manifest_bytes = verdict_bytes = proof_bytes = b''
    output_sha, inventory = None, []
    try:
        original_manifest_bytes = (original_output/'manifest.json').read_bytes()
        replacement_manifest_bytes = Path(manifest_path).read_bytes()
        original_manifest = json.loads(original_manifest_bytes)
        if json.loads(replacement_manifest_bytes) != manifest:
            errors.append('replacement_manifest')
        allowed = {'binary_sha256','info_sha256','build_id','source_sha256',
                   'source_commit','built_from_commit','bootdisk_sha256',
                   'candidate_directory','spec','prelaunch_replacement_reason'}
        if set(manifest) != set(original_manifest) | {'prelaunch_replacement_reason'}:
            errors.append('replacement_manifest')
        for key in set(original_manifest) - allowed:
            if manifest.get(key) != original_manifest.get(key):
                errors.append('replacement_manifest')
        original_spec = dict(original_manifest.get('spec', {}))
        replacement_spec = dict(manifest.get('spec', {}))
        original_spec.pop('candidate_version', None)
        replacement_spec.pop('candidate_version', None)
        if (original_spec != replacement_spec or
                original_manifest.get('spec', {}).get('candidate_version') != '1.0.173' or
                manifest.get('spec', {}).get('candidate_version') != '1.0.174' or
                manifest.get('candidate_directory') != 'run/candidate-174' or
                manifest.get('prelaunch_replacement_reason') !=
                    'remove unsafe SEM diagnostic reads and preserve bounded critical capture'):
            errors.append('replacement_manifest')
        verdict_bytes = (original_output/'verdict.json').read_bytes()
        verdict = json.loads(verdict_bytes)
        if (verdict.get('valid') is not False or verdict.get('verdict') != 'INVALID' or
                verdict.get('error') != 'OSError: [Errno 22] Invalid argument'):
            errors.append('original_error')
        if ((original_output/'recovery-reservation.json').exists() or
                (original_output/'supervision.json').exists()):
            errors.append('original_after_prelaunch')
        output_sha, inventory = evidence_digest(original_output)
        for name in ('host-before.json', 'host-after.json'):
            old_host = json.loads((original_output/name).read_text())
            if (admit(manifest, old_host, set()) or
                    old_host.get('sleep_inhibited') is not True):
                errors.append('original_host_state')
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        errors.append('original_output')
        output_sha, inventory, verdict_bytes = None, [], b''
        replacement_manifest_bytes = b''

    recovery = helper('vfio-recover')
    try:
        proof_bytes = proof_path.read_bytes()
        proof = json.loads(proof_bytes)
        descriptor = proof.get('descriptor', {})
        proof_keys = {'schema','purpose','boot_id','run_id','constructor','failure',
                      'descriptor','before','after','kernel_messages','pre_faults',
                      'post_faults','stages'}
        expected_descriptor_sha = sha(recovery.host_kiq_reservation_descriptor(
            manifest['run_id'], recovery.HOST_KIQ_RESERVATION_PENDING))
        stage_shape = [(row.get('operation'), row.get('request'))
                       for row in proof.get('stages', [])]
        expected_stages = [
            ('ioctl','0x3b64'), ('ioctl','0x3b65'), ('ioctl','0x3b67'),
            ('ioctl','0x3b68'), ('ioctl','0x3b66'), ('ioctl','0x3b6a'),
            ('ioctl','0x3b6c'), ('mmap',None), ('ioctl','0x3b6c'),
            ('mmap',None), ('ioctl','0x3b6c'), ('mmap',None),
            ('ioctl','0x3b69')]
        if (set(proof) != proof_keys or proof.get('schema') != 1 or
                proof.get('purpose') != 'locate prelaunch EINVAL without writes' or
                proof.get('boot_id') != manifest.get('boot_id') or
                proof.get('run_id') != manifest.get('run_id') or
                proof.get('constructor') != 'ok' or proof.get('failure') is not None or
                set(descriptor) != {'exact_pending_match','expected_sha256',
                                    'expected_size','observed_sha256','size'} or
                descriptor.get('exact_pending_match') is not True or
                descriptor.get('expected_size') != 72 or descriptor.get('size') != 72 or
                descriptor.get('expected_sha256') != descriptor.get('observed_sha256') or
                descriptor.get('expected_sha256') != expected_descriptor_sha or
                recovery.validate_host_state(proof.get('before', {}), manifest['boot_id']) or
                recovery.validate_host_state(proof.get('after', {}), manifest['boot_id']) or
                proof.get('kernel_messages') != [] or proof.get('pre_faults') != [] or
                proof.get('post_faults') != [] or not isinstance(proof.get('stages'), list) or
                stage_shape != expected_stages or
                any(row.get('status') != 'ok' for row in proof['stages'])):
            errors.append('prelaunch_proof')
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        proof_bytes = b''
        errors.append('prelaunch_proof')

    readiness_path = vm/'run/prelaunch-readiness-e583a1b2.json'
    readiness = {}
    try:
        readiness_bytes = readiness_path.read_bytes()
        readiness = json.loads(readiness_bytes)
        if (sha(readiness_bytes) != PRELAUNCH_CONTINUATION['readiness_sha256'] or
                readiness.get('schema') != 1 or
                readiness.get('purpose') != 'bounded read-only prelaunch HDP readiness' or
                readiness.get('boot_id') != manifest.get('boot_id') or
                readiness.get('run_id') != manifest.get('run_id') or
                readiness.get('writes_permitted') is not False or
                readiness.get('marker_created') is not False or
                readiness.get('failure') !=
                    'RuntimeError: HDP remap 0x385c != 0x7f000' or
                readiness.get('constructor') != 'ok' or
                readiness.get('exact_pending') is not None or
                readiness.get('descriptor', {}).get('run_id') != manifest.get('run_id') or
                readiness.get('descriptor', {}).get('state') !=
                    recovery.HOST_KIQ_RESERVATION_PENDING or
                readiness.get('hdp_remap_offset_register') != 0x385c or
                readiness.get('config_memsize') != 0x200 or
                readiness.get('config_memsize_valid') is not True or
                readiness.get('active_launch_units') != [] or
                readiness.get('kernel_messages_before') != [] or
                readiness.get('kernel_faults_before') != [] or
                readiness.get('failure_kernel_messages') != [] or
                readiness.get('failure_kernel_faults') != [] or
                recovery.validate_host_state(
                    readiness.get('before_pci', {}), manifest['boot_id']) or
                recovery.validate_host_state(
                    readiness.get('failure_after_pci', {}), manifest['boot_id'])):
            errors.append('prelaunch_readiness')
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        readiness_bytes = b''
        errors.append('prelaunch_readiness')

    expected_identity = {key:manifest[key] for key in observed if key in manifest}
    expected_identity.pop('source_commit', None)
    errors += validate_identity(expected_identity, observed)
    if (observed.get('source_clean') is not True or
            observed.get('source_sha256') != manifest.get('source_sha256')):
        errors.append('source_identity')
    if current_qemu_version(observed.get('image_id')) != manifest.get('qemu_version'):
        errors.append('qemu_version')
    pinned = PRELAUNCH_CONTINUATION
    if (manifest.get('boot_id') != pinned['boot_id'] or
            manifest.get('run_id') != pinned['run_id'] or
            sha(original_manifest_bytes) != pinned['original_manifest_sha256'] or
            not pinned.get('replacement_manifest_sha256') or
            sha(replacement_manifest_bytes) != pinned['replacement_manifest_sha256'] or
            sha(verdict_bytes) != pinned['verdict_sha256'] or
            output_sha != pinned['output_sha256'] or
            sha(proof_bytes) != pinned['proof_sha256']):
        errors.append('continuation_identity')
    host_errors = admit(manifest, host, {host.get('boot_id')})
    if host_errors != ['boot_already_used']:
        errors += ['host_'+error for error in host_errors if error != 'boot_already_used']
        if 'boot_already_used' not in host_errors: errors.append('ledger_missing')
    try:
        recovery_host = recovery.host_state()
        errors += ['resume_'+error for error in
                   recovery.validate_host_state(recovery_host, manifest['boot_id'])]
    except Exception:
        recovery_host = None
        errors.append('resume_host_state')
    cursor, messages, faults = cursor_result
    if not cursor or messages or faults: errors.append('kernel_cursor')
    units = active_launch_units()
    if units: errors.append('active_launch_units')

    ledger_path = vm/'run/used-gpu-boots'/(manifest['boot_id']+'.json')
    try:
        ledger_bytes = ledger_path.read_bytes()
        ledger = json.loads(ledger_bytes)
        launches = ledger.get('launches')
        if (ledger.get('schema') != 2 or ledger.get('boot_id') != manifest['boot_id'] or
                not isinstance(launches, list) or not launches or
                launches[-1].get('run_id') != manifest['run_id']):
            errors.append('boot_ledger')
        if readiness.get('ledger_sha256') != sha(ledger_bytes):
            errors.append('prelaunch_readiness')
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        ledger_bytes = b''
        errors.append('boot_ledger')
    if errors:
        raise ValueError('prelaunch continuation refused: '+','.join(sorted(set(errors))))
    return {
        'schema':1, 'kind':'one-shot-prelaunch-continuation',
        'boot_id':manifest['boot_id'], 'run_id':manifest['run_id'],
        'original_output':str(original_output.resolve()),
        'original_output_sha256':output_sha, 'original_files':inventory,
        'original_manifest_sha256':sha(original_manifest_bytes),
        'replacement_manifest_sha256':sha(replacement_manifest_bytes),
        'original_verdict_sha256':sha(verdict_bytes),
        'prelaunch_proof':str(proof_path.resolve()),
        'prelaunch_proof_sha256':sha(proof_bytes),
        'prelaunch_readiness':str(readiness_path.resolve()),
        'prelaunch_readiness_sha256':sha(readiness_bytes),
        'ledger_sha256':sha(ledger_bytes), 'kernel_cursor':cursor,
        'resume_host_state':recovery_host, 'active_launch_units':units,
        'coordinator_commit':command(['git','-C',str(ROOT),'rev-parse','HEAD']),
        'experiment_py_sha256':sha((ROOT/'tools/experiment.py').read_bytes()),
        'vfio_recover_py_sha256':sha((ROOT/'tools/vfio-recover.py').read_bytes()),
    }, ledger_path, ledger_bytes


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
# Schema 5 conservatively excluded the whole recovery reservation above the
# scratch start. Schema 6 pins the bytes its producer can mutate: consuming the
# 72-byte descriptor, then the bounded host-KIQ image through its fence DWORD.
RECOVERY_LEGACY_GART_EXCLUSION = (
    (RECOVERY_SCRATCH_START, RECOVERY_RESERVATION_END - RECOVERY_SCRATCH_START),
)
RECOVERY_V6_MUTATED_RANGES = (
    (RECOVERY_RESERVATION_START, 72),
    (RECOVERY_SCRATCH_START, 0x0f113004 - RECOVERY_SCRATCH_START),
)


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
            type(value.get('remap')) is int and value.get('remap') in (0x385c, 0x7f000) and
            type(value.get('posted_read')) is int and value.get('posted_read') == 0x200)


def _valid_reservation(value, prior_run_id):
    if isinstance(value, dict) and value.get('schema') in (2, 3):
        try:
            validator = ('valid_v3_lease_proof' if value.get('schema') == 3
                         else 'valid_v2_lease_proof')
            return getattr(helper('vfio-recover'), validator)(value, prior_run_id)
        except Exception:
            return False
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


def _valid_gart(value, forbidden_ranges=RECOVERY_LEGACY_GART_EXCLUSION):
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
            not any(offset < start + size and start < offset + value['size']
                    for start, size in forbidden_ranges))


def _active_reservation_observation(prior_run_id):
    return {
        'version':RECOVERY_RESERVATION_VERSION,
        'state':RECOVERY_RESERVATION_ACTIVE,
        'heap_limit':RECOVERY_HEAP_LIMIT,
        'reservation_start':RECOVERY_RESERVATION_START,
        'scratch_start':RECOVERY_SCRATCH_START,
        'reservation_end':RECOVERY_RESERVATION_END,
        'run_id':prior_run_id,
        'checksum':_recovery_checksum(prior_run_id),
    }


def _valid_graphics_snapshot(value):
    row_keys = {'intended_pipe','selector','rb0_active','rb1_active','active',
                'doorbell_control','doorbell_offset','doorbell_status','wptr',
                'wptr_hi','base','base_hi','cntl'}
    if (not isinstance(value, dict) or set(value) != {'pipes','final_default'} or
            value.get('final_default') != {'value':0, 'completed':True}):
        return False
    pipes = value.get('pipes')
    if not isinstance(pipes, list) or len(pipes) != 2:
        return False
    for index, row in enumerate(pipes):
        if (not isinstance(row, dict) or set(row) != row_keys or
                any(type(item) is not int for item in row.values()) or
                row['intended_pipe'] != index or row['selector'] != index or
                row['active'] != row['rb0_active' if index == 0 else 'rb1_active'] or
                row['doorbell_offset'] != (row['doorbell_control'] & 0x0ffffffc) or
                row['doorbell_status'] != (row['doorbell_control'] & 0xc0000002)):
            return False
        for key in ('active','doorbell_control','wptr','wptr_hi','base','base_hi','cntl'):
            if row[key] == 0xffffffff:
                return False
    pipe1 = pipes[1]
    return not (pipe1['rb1_active'] & 1) and pipe1['doorbell_status'] == 0


def _valid_graphics_guard(value, prior_run_id):
    before = value.get('reservation_before') if isinstance(value, dict) else None
    if isinstance(before, dict) and before.get('schema') in (2, 3):
        try:
            return helper('vfio-recover').valid_apple_graphics_pipe_guard(
                value, prior_run_id)
        except Exception:
            return False
    expected_reservation = _active_reservation_observation(prior_run_id)
    return (isinstance(value, dict) and
            set(value) == {'policy','reservation_before','reservation_after',
                           'reservation_unchanged','pipe1_supported_state','snapshot'} and
            value.get('policy') == 'x6000-24G830-single-legacy-gfx-pipe-v1' and
            value.get('reservation_before') == expected_reservation and
            value.get('reservation_after') == expected_reservation and
            value.get('reservation_unchanged') is True and
            value.get('pipe1_supported_state') is True and
            _valid_graphics_snapshot(value.get('snapshot')))


def _graphics_was_stale(snapshot):
    return any((row['active'] & 1) or row['doorbell_status'] or row['wptr'] or
               row['wptr_hi'] or row['base'] or row['base_hi'] or row['cntl']
               for row in snapshot['pipes'])


def _graphics_final_clean(snapshot):
    if not _valid_graphics_snapshot(snapshot):
        return False
    pipe0 = snapshot['pipes'][0]
    return all(pipe0[key] == 0 for key in (
        'active','doorbell_control','wptr','wptr_hi','base','base_hi','cntl'))


def _valid_host_kiq(value, reservation, gc, hqd_doorbell_values,
                    gart_forbidden_ranges=RECOVERY_LEGACY_GART_EXCLUSION):
    if not isinstance(value, dict):
        return False
    expected_keys = {'status','selector','packet_dwords','rptr_after',
                     'fence_sequence','fence_after','gfx_active_after_unmap',
                     'gfx_active_before_scrub','gfx_doorbell_offset','addresses',
                     'gart','reservation','hdp_flush','cleanup_confirmed','cleanup',
                     'graphics_pipes_after_unmap','final_gate'}
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
            not _valid_gart(value.get('gart'), gart_forbidden_ranges) or
            not _valid_graphics_snapshot(value.get('graphics_pipes_after_unmap')) or
            value.get('graphics_pipes_after_unmap') !=
                gc.get('graphics_pipes_after_retirement') or
            value['graphics_pipes_after_unmap']['pipes'][0]['active'] & 1 or
            value.get('cleanup_confirmed') is not True):
        return False
    if not isinstance(addresses, dict) or set(addresses) != {
            'ring','mqd','rptr','wptr','eop','fence'}:
        return False
    if any(type(addresses[key]) is not int for key in addresses):
        return False
    if isinstance(reservation, dict) and reservation.get('schema') in (2, 3):
        lease_start = reservation.get('lease_start')
        if type(lease_start) is not int:
            return False
        layout_offsets = {
            'ring':lease_start+0x1000, 'mqd':lease_start+0x11000,
            'rptr':lease_start+0x12000, 'wptr':lease_start+0x12008,
            'eop':lease_start+0x13000, 'fence':lease_start+0x14000,
        }
    else:
        layout_offsets = {
            'ring':0x0f100000, 'mqd':0x0f110000, 'rptr':0x0f111000,
            'wptr':0x0f111008, 'eop':0x0f112000, 'fence':0x0f113000,
        }
    fb_base = addresses['ring'] - layout_offsets['ring']
    if fb_base <= 0 or fb_base & 0xffffff:
        return False
    expected_addresses = {name:fb_base+offset
                          for name,offset in layout_offsets.items()}
    if addresses != expected_addresses:
        return False
    cleanup_keys = {'mec_cntl','hqd_active','hqd_doorbell','hqd_rptr',
                    'hqd_wptr_lo','hqd_wptr_hi','pq_status',
                    'doorbell_range_lower','doorbell_range_upper','wptr_poll_cntl'}
    if (not isinstance(cleanup, dict) or set(cleanup) != cleanup_keys or
            any(type(cleanup.get(key)) is not int for key in cleanup_keys)):
        return False
    if (cleanup['mec_cntl'] & 0x50000000 != 0x50000000 or
            cleanup.get('hqd_active') != 0 or
            cleanup.get('hqd_doorbell') not in hqd_doorbell_values or
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
        'gfx_ring_clean','gfx_retirement_confirmed','graphics_pipe_proof_complete')}
    return (isinstance(gate, dict) and set(gate) == set(expected_gate) and
            all(type(gate.get(key)) is type(expected) and gate.get(key) == expected
                for key, expected in expected_gate.items()))


def _validate_recovery_receipt(receipt, boot_id, prior_run_id,
                               hqd_doorbell_values,
                               gart_forbidden_ranges=RECOVERY_LEGACY_GART_EXCLUSION):
    errors = []
    exact = {'schema':5, 'status':'recovered', 'authorizes_launch':True,
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
            gc.get('gfx_retirement_confirmed') is not True or
            gc.get('graphics_pipe_proof_complete') is not True):
        errors.append('recovery_receipt')
    if isinstance(gc, dict):
        reservation = gc.get('reservation')
        if not _valid_reservation(reservation, prior_run_id):
            errors.append('recovery_receipt')
        guard = gc.get('graphics_pipe_guard')
        before = gc.get('graphics_pipes_before')
        after_retirement = gc.get('graphics_pipes_after_retirement')
        final = gc.get('graphics_pipes_final')
        if (not _valid_graphics_guard(guard, prior_run_id) or
                not _valid_graphics_snapshot(before) or
                not _valid_graphics_snapshot(after_retirement) or
                not _graphics_final_clean(final)):
            errors.append('recovery_receipt')
        if _valid_graphics_snapshot(before):
            pipe0 = before['pipes'][0]
            needs_unmap = bool((pipe0['active'] & 1) or pipe0['doorbell_status'])
            if (gc.get('gfx_needs_unmap') is not needs_unmap or
                    gc.get('gfx_was_stale') is not _graphics_was_stale(before)):
                errors.append('recovery_receipt')
        host_kiq = gc.get('host_kiq')
        if gc.get('gfx_needs_unmap') is True:
            if not _valid_host_kiq(host_kiq, reservation, gc,
                                   hqd_doorbell_values, gart_forbidden_ranges):
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


def validate_recovery_receipt(receipt, boot_id, prior_run_id):
    return _validate_recovery_receipt(
        receipt, boot_id, prior_run_id, hqd_doorbell_values=(0,))


def validate_recovery_receipt_v6(receipt, boot_id, prior_run_id,
                                 recovery_helpers_sha256=None):
    """Validate the PAGE/RLC-complete normal-recovery receipt schema."""
    if not isinstance(receipt, dict):
        return ['recovery_receipt']
    gc = receipt.get('gc_quiesce')
    if not isinstance(gc, dict):
        return ['recovery_receipt']

    errors = []
    reservation = gc.get('reservation')
    native_schema = (reservation.get('schema') if isinstance(reservation, dict)
                     else None)
    native = native_schema in (2, 3)
    gart_forbidden_ranges = RECOVERY_V6_MUTATED_RANGES
    if native:
        expected_helper_paths = {
            'tools/vfio-recover.py', 'tools/recovery_lease_v2.py',
            'tools/kiq-recovery-proof.py'}
        if native_schema == 3:
            expected_helper_paths |= {
                'tools/critical-replay.py', 'tools/recovery_lifetime_v3.py'}
        receipt_helpers = receipt.get('recovery_helpers_sha256')
        if (not isinstance(recovery_helpers_sha256, dict) or
                set(recovery_helpers_sha256) != expected_helper_paths or
                any(not re.fullmatch(r'[0-9a-f]{64}', str(value))
                    for value in recovery_helpers_sha256.values()) or
                receipt_helpers != recovery_helpers_sha256 or
                not _valid_reservation(reservation, prior_run_id) or
                (native_schema == 3 and
                 receipt.get('recovery_lease_schema') != 3) or
                (native_schema == 2 and
                 'recovery_lease_schema' in receipt) or
                'stopped_wptr_doorbell_clear' in gc):
            errors.append('recovery_receipt')
        lease_start = reservation.get('lease_start')
        if type(lease_start) is int:
            gart_forbidden_ranges = (
                (lease_start+0x1000, 0x10000),
                (lease_start+0x11000, 0x800),
                (lease_start+0x12000, 4),
                (lease_start+0x12008, 8),
                (lease_start+0x13000, 0x1000),
                (lease_start+0x14000, 4),
            )
        else:
            errors.append('recovery_receipt')
    legacy = dict(receipt)
    legacy['schema'] = 5
    legacy_gc = dict(gc)
    if 'stopped_wptr_doorbell_clear' in gc and not native:
        try:
            derived, proof_errors = helper(
                'kiq-recovery-proof').derive_effective_host_kiq(receipt)
        except Exception:
            derived, proof_errors = None, ['schema6_stopped_wptr_proof']
        if (proof_errors or not isinstance(derived, dict) or
                set(derived) != {'source', 'host_kiq'} or
                derived.get('source') != 'stopped_wptr_doorbell_clear' or
                not isinstance(derived.get('host_kiq'), dict)):
            errors.append('recovery_receipt')
        else:
            legacy_gc['host_kiq'] = derived['host_kiq']
        legacy_gc.pop('stopped_wptr_doorbell_clear', None)
    for key in ('sdma0_page_ib_before', 'sdma0_page_ib_after',
                'sdma0_page_rb_before', 'sdma0_page_rb_after',
                'sdma0_status_before', 'sdma0_status_after',
                'sdma0_shutdown_trace', 'sdma0_rlc_inputs'):
        legacy_gc.pop(key, None)
    legacy['gc_quiesce'] = legacy_gc
    errors.extend(_validate_recovery_receipt(
        legacy, boot_id, prior_run_id,
        hqd_doorbell_values=(0, 0x80000000),
        gart_forbidden_ranges=gart_forbidden_ranges))
    if receipt.get('schema') != 6:
        errors.append('recovery_receipt')

    # Every SDMA value used by the producer's shutdown decision must be a
    # readable DWORD. In particular, all-ones must not satisfy HALT or IDLE.
    def valid_sdma_dword(value):
        return type(value) is int and 0 <= value < 0xffffffff

    sdma_values = ('sdma0_before', 'sdma0_after',
                   'sdma0_cntl_before', 'sdma0_cntl_after',
                   'sdma0_rb_before', 'sdma0_rb_after',
                   'sdma0_ib_before', 'sdma0_ib_after',
                   'sdma0_page_ib_before', 'sdma0_page_ib_after',
                   'sdma0_page_rb_before', 'sdma0_page_rb_after',
                   'sdma0_status_before', 'sdma0_status_after')
    if any(not valid_sdma_dword(gc.get(key)) for key in sdma_values):
        errors.append('recovery_receipt')

    page_registers = {'ib':0x4d08, 'rb':0x4ce0}
    expected_trace = []
    for kind in ('ib', 'rb'):
        before = gc.get(f'sdma0_page_{kind}_before')
        after = gc.get(f'sdma0_page_{kind}_after')
        if (not valid_sdma_dword(before) or not valid_sdma_dword(after) or
                after != before & ~1 or after & 1):
            errors.append('recovery_receipt')
        expected_trace.append({
            'step':f'disable-page-{kind}',
            'register':page_registers[kind],
            'before':before,
            'written':before & ~1 if type(before) is int else None,
            'readback':after,
        })
    if gc.get('sdma0_shutdown_trace') != expected_trace:
        errors.append('recovery_receipt')

    status_after = gc.get('sdma0_status_after')
    if not valid_sdma_dword(status_after) or status_after & 1 != 1:
        errors.append('recovery_receipt')

    rlc = gc.get('sdma0_rlc_inputs')
    rlc_keys = {'index', 'rb_before', 'rb_after', 'ib_before', 'ib_after'}
    if (not isinstance(rlc, list) or len(rlc) != 2 or
            any(not isinstance(row, dict) or set(row) != rlc_keys
                for row in rlc) or
            [row.get('index') for row in rlc if isinstance(row, dict)] != [0, 1]):
        errors.append('recovery_receipt')
    else:
        for row in rlc:
            values = [row.get(key) for key in
                      ('rb_before', 'rb_after', 'ib_before', 'ib_after')]
            if (any(not valid_sdma_dword(value) for value in values) or
                    row['rb_after'] != row['rb_before'] or
                    row['ib_after'] != row['ib_before'] or
                    row['rb_after'] & 1 or row['ib_after'] & 1):
                errors.append('recovery_receipt')

    return sorted(set(errors))


def validate_reuse_receipt(receipt, boot_id, prior_run_id, vm=None,
                           next_run_id=None, manifest=None, manifest_path=None):
    """Dispatch normal and startup-only receipts without weakening either schema."""
    if isinstance(receipt, dict) and receipt.get('schema') == 4:
        errors = []
        try:
            errors.extend(helper('startup-noqueue-recover').validate_receipt(
                receipt, boot_id, prior_run_id, vm))
        except Exception:
            errors.append('startup_noqueue_receipt')
        for key in ('recovery_id', 'attempt_id'):
            if not re.fullmatch(r'[0-9a-f]{32}', str(receipt.get(key, ''))):
                errors.append('startup_noqueue_receipt')
        if vm is not None:
            try:
                raw = (Path(vm) / 'run/used-gpu-boots' /
                       (boot_id + '.json')).read_bytes()
                if (not re.fullmatch(r'[0-9a-f]{64}',
                                     str(receipt.get('ledger_sha256', ''))) or
                        hashlib.sha256(raw).hexdigest() !=
                        receipt.get('ledger_sha256')):
                    errors.append('startup_noqueue_receipt')
            except OSError:
                errors.append('startup_noqueue_receipt')
        return sorted(set(errors))
    if isinstance(receipt, dict) and receipt.get('schema') == 7:
        if (vm is None or next_run_id is None or manifest is None or
                manifest_path is None):
            return ['retained_kiq_continuation_receipt']
        try:
            return helper('retained-kiq-continuation').validate_receipt(
                receipt, vm, boot_id, prior_run_id, next_run_id,
                manifest, manifest_path)
        except Exception:
            return ['retained_kiq_continuation_receipt']
    if isinstance(receipt, dict) and receipt.get('schema') == 6:
        helper_hashes = (manifest.get('recovery_helpers_sha256')
                         if isinstance(manifest, dict) and
                         manifest.get('recovery_lease_schema') in (2, 3) else None)
        return validate_recovery_receipt_v6(
            receipt, boot_id, prior_run_id, helper_hashes)
    return validate_recovery_receipt(receipt, boot_id, prior_run_id)


def reuse_authorization(vm, boot_id, run_id, manifest=None, manifest_path=None):
    path = vm/'run/used-gpu-boots'/(boot_id+'.json')
    if not path.exists(): return None, []
    try: ledger = read_boot_ledger(path)
    except (OSError, ValueError, KeyError): return None, ['boot_ledger']
    launches = ledger.get('launches')
    if not isinstance(launches, list) or not launches: return None, ['boot_ledger']
    if any(row.get('run_id') == run_id for row in launches): return None, ['run_id_reused']
    if len(launches) >= 3: return None, ['launch_ceiling']
    prior = launches[-1].get('run_id')
    continuation_path = (vm/'run/retained-kiq-continuations'/boot_id/
                         (str(prior)+'.json'))
    if continuation_path.exists():
        receipt_path = continuation_path
        error_key = 'retained_kiq_continuation_receipt'
    else:
        receipt_path = vm/'run/vfio-recovery'/boot_id/(str(prior)+'.json')
        error_key = 'recovery_receipt'
    if not receipt_path.exists() and error_key == 'recovery_receipt':
        startup_path = (vm/'run/startup-noqueue-recovery'/boot_id/
                        (str(prior)+'.json'))
        if startup_path.exists():
            receipt_path = startup_path
            error_key = 'startup_noqueue_receipt'
    try: receipt = json.loads(receipt_path.read_text())
    except (OSError, ValueError): return None, [error_key]
    errors = validate_reuse_receipt(
        receipt, boot_id, prior, vm, run_id, manifest, manifest_path)
    used_recovery_ids = {row.get('recovery_id') for row in launches}
    if receipt.get('recovery_id') in used_recovery_ids:
        errors.append(error_key)
    if receipt.get('schema') == 4:
        used_attempt_ids = {row.get('attempt_id') for row in launches}
        if receipt.get('attempt_id') in used_attempt_ids:
            errors.append('startup_noqueue_receipt')
    if receipt.get('schema') == 7:
        used_authorization_ids = {row.get('authorization_id') for row in launches}
        if receipt.get('authorization_id') in used_authorization_ids:
            errors.append('retained_kiq_continuation_receipt')
    return (receipt if not errors else None), sorted(set(errors))


def cap_revision_authority_path(vm, boot_id, run_id):
    return (Path(vm) / 'run/cap-revision-authorities' / boot_id /
            (run_id + '.json'))


def cap_revision_authorization(vm, manifest, manifest_path,
                               expected_authority_sha256):
    """Validate the one candidate-176-to-177 cap revision without consuming it."""
    errors = []
    boot_id = manifest.get('boot_id') if isinstance(manifest, dict) else None
    run_id = manifest.get('run_id') if isinstance(manifest, dict) else None
    spec = manifest.get('spec') if isinstance(manifest, dict) else None
    if (boot_id != CAP_REVISION_BOOT_ID or
            not re.fullmatch(r'[0-9a-f]{32}', str(run_id or '')) or
            manifest.get('gpu') is not True or
            manifest.get('candidate_directory') != 'run/candidate-177' or
            type(manifest.get('max_seconds')) is not int or
            manifest.get('max_seconds') != 180 or
            not isinstance(spec, dict) or spec.get('candidate_version') != '1.0.177' or
            spec.get('id') != 'metal-010' or manifest.get('experiment') != 'metal-010' or
            spec.get('requested_diagnostic') != 'rgpusubmit=1' or
            type(spec.get('max_seconds')) is not int or
            spec.get('max_seconds') != 180):
        return None, ['cap_revision_manifest']
    if not re.fullmatch(r'[0-9a-f]{64}', str(expected_authority_sha256 or '')):
        return None, ['cap_revision_authority']

    authority_path = cap_revision_authority_path(vm, boot_id, run_id)
    ledger_path = Path(vm)/'run/used-gpu-boots'/(boot_id+'.json')
    canonical_path = (Path(vm)/'run/vfio-recovery'/boot_id/
                      (CAP_REVISION_PRIOR_RUN_ID+'.json'))
    run_path = Path(vm)/'run/metal-009-176/recovery.json'
    manifest_path = Path(manifest_path)
    try:
        authority_raw = authority_path.read_bytes()
        authority = json.loads(authority_raw)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None, ['cap_revision_authority']
    if sha(authority_raw) != expected_authority_sha256:
        errors.append('cap_revision_authority')

    try:
        manifest_raw = manifest_path.read_bytes()
        if json.loads(manifest_raw) != manifest:
            errors.append('cap_revision_manifest')
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        manifest_raw = b''
        errors.append('cap_revision_manifest')

    try:
        ledger_raw = ledger_path.read_bytes()
        ledger = json.loads(ledger_raw)
        launches = ledger.get('launches') if isinstance(ledger, dict) else None
        if (sha(ledger_raw) != CAP_REVISION_LEDGER_SHA256 or
                not isinstance(ledger, dict) or
                ledger.get('schema') != 2 or ledger.get('boot_id') != boot_id or
                ledger.get('max_launches') != 3 or
                not isinstance(launches, list) or len(launches) != 3 or
                any(not isinstance(row, dict) for row in launches) or
                launches[-1].get('run_id') != CAP_REVISION_PRIOR_RUN_ID or
                any(row.get('run_id') == run_id for row in launches) or
                CAP_REVISION_RECOVERY_ID in {
                    row.get('recovery_id') for row in launches}):
            errors.append('cap_revision_ledger')
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        ledger_raw = b''; ledger = None
        errors.append('cap_revision_ledger')

    receipt_raws = []
    receipts = []
    for path, expected_hash in (
            (canonical_path, CAP_REVISION_CANONICAL_RECEIPT_SHA256),
            (run_path, CAP_REVISION_RUN_RECEIPT_SHA256)):
        try:
            raw = path.read_bytes(); value = json.loads(raw)
            receipt_raws.append(raw); receipts.append(value)
            if sha(raw) != expected_hash:
                errors.append('cap_revision_receipt')
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            errors.append('cap_revision_receipt')
    receipt = receipts[0] if receipts else None
    if (len(receipts) != 2 or receipts[0] != receipts[1] or
            not isinstance(receipt, dict) or
            receipt.get('recovery_id') != CAP_REVISION_RECOVERY_ID or
            validate_recovery_receipt_v6(
                receipt, boot_id, CAP_REVISION_PRIOR_RUN_ID)):
        errors.append('cap_revision_receipt')

    artifacts = {
        'range_audit_sha256':ROOT/'findings/experiments/metal-009-176/recovery-gart-range-audit.md',
        'design_sha256':ROOT/'docs/superpowers/specs/2026-09-09-same-boot-qualification-cap-revision-design.md',
        'candidate177_experiment_py_sha256':Path(__file__).resolve(),
        'candidate177_recovery_producer_sha256':ROOT/'tools/vfio-recover.py',
    }
    artifact_hashes = {}
    try:
        artifact_hashes = {key:sha(path.read_bytes())
                           for key, path in artifacts.items()}
    except OSError:
        errors.append('cap_revision_source')
    if (artifact_hashes.get('range_audit_sha256') !=
            CAP_REVISION_RANGE_AUDIT_SHA256):
        errors.append('cap_revision_evidence')

    fixed = {
        'schema':1, 'kind':'same-boot-qualification-cap-revision',
        'boot_id':CAP_REVISION_BOOT_ID,
        'ledger_preimage_sha256':CAP_REVISION_LEDGER_SHA256,
        'prior_run_id':CAP_REVISION_PRIOR_RUN_ID,
        'recovery_id':CAP_REVISION_RECOVERY_ID,
        'canonical_recovery_receipt_sha256':
            CAP_REVISION_CANONICAL_RECEIPT_SHA256,
        'run_recovery_receipt_sha256':CAP_REVISION_RUN_RECEIPT_SHA256,
        'range_audit_sha256':CAP_REVISION_RANGE_AUDIT_SHA256,
        'candidate176_consumer_sha256':
            CAP_REVISION_CANDIDATE176_CONSUMER_SHA256,
        'candidate176_recovery_producer_sha256':
            CAP_REVISION_CANDIDATE176_PRODUCER_SHA256,
        'design_sha256':artifact_hashes.get('design_sha256'),
        'candidate177_experiment_py_sha256':
            artifact_hashes.get('candidate177_experiment_py_sha256'),
        'candidate177_recovery_producer_sha256':
            artifact_hashes.get('candidate177_recovery_producer_sha256'),
        'manifest_sha256':sha(manifest_raw),
        'next_run_id':run_id,
        'from_max_launches':3, 'to_max_launches':4,
        'additional_launches':1, 'automatic_extension':False,
        'purpose':CAP_REVISION_PURPOSE,
    }
    if (not isinstance(authority, dict) or
            set(authority) != CAP_REVISION_AUTHORITY_FIELDS or
            any(type(authority.get(key)) is not type(value) or
                authority.get(key) != value for key, value in fixed.items())):
        errors.append('cap_revision_authority')
    if errors:
        return None, sorted(set(errors))
    return {
        'authority':authority,
        'authority_path':authority_path,
        'authority_raw':authority_raw,
        'authority_sha256':expected_authority_sha256,
        'ledger_path':ledger_path,
        'ledger_raw':ledger_raw,
        'receipt':receipt,
        'receipt_raws':receipt_raws,
        'manifest_raw':manifest_raw,
    }, []


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


def _journal_cursor_position(cursor, boot_id):
    if not isinstance(cursor, str):
        return None
    match = re.search(r'(?:^|;)i=([0-9a-f]+);b=([A-Za-z0-9-]+)(?:;|$)',
                      cursor)
    if (not match or
            match[2].replace('-', '').lower() != boot_id.replace('-', '').lower()):
        return None
    return int(match[1], 16)


def reserve_cap_revision(directory, boot_id, experiment, recovery, manifest,
                         manifest_path, authorization):
    """Atomically record the sole 3-to-4 policy revision and fourth launch."""
    if (not isinstance(manifest, dict) or boot_id != manifest.get('boot_id') or
            experiment != manifest.get('run_id') or
            not isinstance(authorization, dict)):
        raise ValueError('cap revision refused: cap_revision_authority')
    vm = Path(directory).parent.parent
    expected_sha = authorization.get('authority_sha256')
    checked, errors = cap_revision_authorization(
        vm, manifest, manifest_path, expected_sha)
    if (errors or checked is None or recovery != checked['receipt']):
        raise ValueError('cap revision refused: '+','.join(
            sorted(set(errors or ['cap_revision_receipt']))))

    fresh_host = host_snapshot()
    host_errors = admit(manifest, fresh_host, {boot_id}, reuse_allowed=True)
    if fresh_host.get('sleep_inhibited') is not True:
        host_errors.append('sleep_inhibited')
    try:
        units = active_launch_units()
    except Exception:
        units = None; host_errors.append('active_launch_units')
    if units:
        host_errors.append('active_launch_units')
    pending = vm/'run/launch-pending'
    try:
        pending_names = sorted(path.name for path in pending.iterdir())
    except FileNotFoundError:
        pending_names = []
    except OSError:
        pending_names = None; host_errors.append('pending_launch')
    if pending_names:
        host_errors.append('pending_launch')

    try:
        recovery_tool = helper('vfio-recover')
        vfio_gate = recovery_tool.host_state()
        host_errors.extend(recovery_tool.validate_host_state(vfio_gate, boot_id))
    except Exception:
        vfio_gate = None; host_errors.append('vfio_host_gate')
    if host_errors:
        raise ValueError('cap revision refused: '+','.join(sorted(set(host_errors))))

    cursor_before = recovery.get('kernel_cursor_after')
    before_position = _journal_cursor_position(cursor_before, boot_id)
    if before_position is None:
        raise ValueError('cap revision refused: kernel_cursor')
    try:
        cursor_after, messages, faults = kernel_updates(cursor_before)
    except Exception:
        raise ValueError('cap revision refused: kernel_cursor') from None
    after_position = _journal_cursor_position(cursor_after, boot_id)
    implicit_resets = [message for message in messages if re.search(
        r'vfio-pci 0000:7b:00\.0: (?:resetting|reset done)\b',
        message, re.I)]
    if after_position is None or after_position < before_position:
        errors.append('kernel_cursor')
    cap_faults = list(faults) + [message for message in messages if re.search(
        r'BUG:|Oops:|Hardware Error|IO_PAGE_FAULT|hard LOCKUP|soft lockup|MCE:|'
        r'AMD-Vi:.*fault|vfio.*(?:error|failed)', message, re.I)]
    if cap_faults:
        errors.append('kernel_fault')
    if implicit_resets:
        errors.append('implicit_reset')
    if errors:
        raise ValueError('cap revision refused: '+','.join(sorted(set(errors))))

    # Repeat every immutable binding after the live gates and journal scan. The
    # bytes used for the transition may not change between review and replace.
    final, errors = cap_revision_authorization(
        vm, manifest, manifest_path, expected_sha)
    if errors or final is None:
        raise ValueError('cap revision refused: '+','.join(
            sorted(set(errors or ['cap_revision_authority']))))
    for key in ('authority_raw', 'ledger_raw', 'receipt_raws', 'manifest_raw'):
        if final[key] != checked[key]:
            raise ValueError('cap revision refused: concurrent_change')

    ledger = json.loads(final['ledger_raw'])
    launches = list(ledger['launches'])
    revision = {
        'authority_sha256':expected_sha,
        'ledger_preimage_sha256':CAP_REVISION_LEDGER_SHA256,
        'from_max_launches':3, 'to_max_launches':4,
        'additional_launches':1, 'purpose':CAP_REVISION_PURPOSE,
        'kernel_cursor_before':cursor_before,
        'kernel_cursor_after':cursor_after,
        'kernel_messages':messages,
        'host_gate':fresh_host,
        'vfio_gate':vfio_gate,
        'active_launch_units':units,
        'pending_launches':pending_names,
    }
    launches.append({
        'run_id':experiment, 'reserved_epoch':time.time(),
        'recovery_id':CAP_REVISION_RECOVERY_ID,
        'prior_run_id':CAP_REVISION_PRIOR_RUN_ID,
        'cap_revision_authority_sha256':expected_sha,
        'qualification':CAP_REVISION_PURPOSE,
    })
    updated = dict(ledger)
    updated.update(schema=3, initial_max_launches=3, max_launches=4,
                   cap_revisions=[revision], launches=launches)
    replace_json(final['ledger_path'], updated)
    return cursor_after


def warm_qualification_authorization(vm, manifest, manifest_path, output,
                                     policy_sha256, activation_sha256,
                                     classifier=None):
    """Validate one exact finite candidate-178 activation without reserving it."""
    classifier = classifier or helper('classify-run')
    retained = helper('retained-kiq-continuation')
    recovery = helper('vfio-recover')
    hooks = argparse.Namespace(
        validate_receipt=validate_recovery_receipt_v6,
        validate_running=validate_running,
        parse_serial=lambda evidence_manifest, serial:
            parse_manifest_serial(classifier, evidence_manifest, serial),
        classify_readiness=classifier.classify_probe_readiness,
        admit_host=admit,
        validate_full_host=lambda host, boot: retained.host_errors(
            host, boot, prefix='warm qualification saved '),
        validate_vfio=recovery.validate_host_state,
    )
    return helper('warm-qualification').authorize(
        vm, manifest, manifest_path, output, policy_sha256,
        activation_sha256, hooks)


def candidate179_authorization(vm, manifest, manifest_path, output,
                               policy_sha256, activation_sha256,
                               helper_name='candidate179-qualification',
                               label='candidate179'):
    """Validate one exact finite authority without reserving its launch.

    The candidate-179 helper pins its identities as constants; the generic
    one-run helper pins them inside its policy. Both share this gate wiring.
    """
    retained = helper('retained-kiq-continuation')
    recovery = helper('vfio-recover')
    helper_hashes = (manifest.get('recovery_helpers_sha256')
                     if isinstance(manifest, dict) else None)
    hooks = argparse.Namespace(
        validate_receipt=(
            validate_recovery_receipt_v6 if helper_name == 'candidate179-qualification'
            else lambda receipt, boot, prior: validate_recovery_receipt_v6(
                receipt, boot, prior, helper_hashes)),
        validate_host=lambda host, boot: retained.host_errors(
            host, boot, prefix=label + ' '),
        validate_vfio=recovery.validate_host_state,
    )
    return helper(helper_name).authorize(
        vm, manifest, manifest_path, output, policy_sha256,
        activation_sha256, hooks)


def reserve_candidate179_qualification(directory, boot_id, experiment, recovery,
                                       manifest, manifest_path, output,
                                       authorization):
    """Collect the locked live gate and atomically append candidate 179 once."""
    if (not isinstance(authorization, dict) or
            boot_id != manifest.get('boot_id') or
            experiment != manifest.get('run_id') or
            recovery != authorization.get('receipt')):
        raise ValueError('candidate179 qualification refused: authority')
    helper_name = authorization.get('helper_name', 'candidate179-qualification')
    label = authorization.get('label', 'candidate179')
    vm = Path(directory).parent.parent
    gate_errors = []
    cursor_before = recovery.get('kernel_cursor_after')
    before_position = _journal_cursor_position(cursor_before, boot_id)
    try:
        capture_host = host_snapshot()
        gate_errors.extend(admit(
            manifest, capture_host, {boot_id}, reuse_allowed=True))
        if capture_host.get('sleep_inhibited') is not True:
            gate_errors.append('sleep_inhibited')
    except Exception:
        capture_host = None
        gate_errors.append('capture_host')
    try:
        retained = helper('retained-kiq-continuation')
        full_host = retained.collect_fresh_host(cursor_before)
        gate_errors.extend(retained.host_errors(
            full_host, boot_id, prefix=label + ' '))
    except Exception:
        full_host = None
        gate_errors.append('full_host')
    if isinstance(full_host, dict) and isinstance(capture_host, dict):
        host_gate = dict(full_host)
        for key in ('amdgpu_initialized', 'capture_ready', 'watchdogs_verified',
                    'device_pinned_awake', 'device_accessible', 'pstore_files'):
            host_gate[key] = capture_host.get(key)
    else:
        host_gate = None
    try:
        units = active_launch_units()
    except Exception:
        units = None
        gate_errors.append('active_launch_units')
    if units:
        gate_errors.append('active_launch_units')
    pending = vm/'run/launch-pending'
    try:
        pending_names = sorted(path.name for path in pending.iterdir())
    except FileNotFoundError:
        pending_names = []
    except OSError:
        pending_names = None
        gate_errors.append('pending_launch')
    if pending_names:
        gate_errors.append('pending_launch')
    try:
        recovery_tool = helper('vfio-recover')
        vfio_gate = recovery_tool.host_state()
        gate_errors.extend(recovery_tool.validate_host_state(vfio_gate, boot_id))
    except Exception:
        vfio_gate = None
        gate_errors.append('vfio_host_gate')
    try:
        requested = manifest.get('spec', {}).get('requested_diagnostic')
        identity_gate = current_identity(
            vm, vm/manifest['candidate_directory'], requested,
            run_id=manifest['run_id'],
            recovery_lease_schema=manifest.get('recovery_lease_schema', 2))
        identity_gate.update(run_id=manifest['run_id'],
                             recovery_lease_schema=manifest.get('recovery_lease_schema', 2))
        gate_errors.extend(validate_identity(
            {key:manifest[key] for key in identity_gate if key in manifest},
            identity_gate))
    except Exception:
        identity_gate = None
        gate_errors.append('current_identity')
    cursor_after = full_host.get('journal_cursor') if isinstance(full_host, dict) else None
    messages = full_host.get('journal_messages') if isinstance(full_host, dict) else None
    after_position = _journal_cursor_position(cursor_after, boot_id)
    if before_position is None or after_position is None or after_position < before_position:
        gate_errors.append('kernel_cursor')
    if not isinstance(messages, list):
        gate_errors.append('kernel_messages')
    if gate_errors:
        raise ValueError(label + ' qualification refused: '+','.join(
            sorted(set(gate_errors))))
    gate = {
        'kernel_cursor_before':cursor_before,
        'kernel_cursor_after':cursor_after,
        'kernel_messages':messages,
        'host_gate':host_gate,
        'vfio_gate':vfio_gate,
        'identity_gate':identity_gate,
        'active_launch_units':units,
        'pending_launches':pending_names,
    }
    qualification = helper(helper_name)
    path, updated = qualification.build_reservation(
        authorization, boot_id, experiment, recovery, gate, time.time())
    replace_json(path, updated)
    return cursor_after


def reserve_warm_qualification(directory, boot_id, experiment, recovery,
                               manifest, manifest_path, output, authorization):
    """Recheck live gates and append only row 5 or 6 of the finite plan."""
    if (not isinstance(authorization, dict) or
            boot_id != manifest.get('boot_id') or
            experiment != manifest.get('run_id')):
        raise ValueError('warm qualification refused: authority')
    vm = Path(directory).parent.parent
    policy_sha = authorization.get('policy_sha256')
    activation_sha = authorization.get('activation_sha256')
    checked, errors = warm_qualification_authorization(
        vm, manifest, manifest_path, output, policy_sha, activation_sha)
    if errors or checked is None or recovery != checked.get('receipt'):
        raise ValueError('warm qualification refused: '+','.join(
            sorted(set(errors or ['receipt']))))

    cursor_before = recovery.get('kernel_cursor_after')
    before_position = _journal_cursor_position(cursor_before, boot_id)
    gate_errors = []
    try:
        capture_host = host_snapshot()
        gate_errors.extend(admit(
            manifest, capture_host, {boot_id}, reuse_allowed=True))
        if capture_host.get('sleep_inhibited') is not True:
            gate_errors.append('sleep_inhibited')
    except Exception:
        capture_host = None; gate_errors.append('capture_host')
    try:
        retained = helper('retained-kiq-continuation')
        full_host = retained.collect_fresh_host(cursor_before)
        gate_errors.extend(retained.host_errors(
            full_host, boot_id, prefix='warm qualification '))
    except Exception:
        full_host = None; gate_errors.append('full_host')
    if isinstance(full_host, dict) and isinstance(capture_host, dict):
        host_gate = dict(full_host)
        for key in ('amdgpu_initialized', 'capture_ready', 'watchdogs_verified',
                    'device_pinned_awake', 'device_accessible', 'pstore_files'):
            host_gate[key] = capture_host.get(key)
    else:
        host_gate = None
    try:
        units = active_launch_units()
    except Exception:
        units = None; gate_errors.append('active_launch_units')
    if units:
        gate_errors.append('active_launch_units')
    pending = vm/'run/launch-pending'
    try:
        pending_names = sorted(path.name for path in pending.iterdir())
    except FileNotFoundError:
        pending_names = []
    except OSError:
        pending_names = None; gate_errors.append('pending_launch')
    if pending_names:
        gate_errors.append('pending_launch')
    try:
        recovery_tool = helper('vfio-recover')
        vfio_gate = recovery_tool.host_state()
        gate_errors.extend(recovery_tool.validate_host_state(vfio_gate, boot_id))
    except Exception:
        vfio_gate = None; gate_errors.append('vfio_host_gate')
    try:
        requested = manifest.get('spec', {}).get('requested_diagnostic')
        identity_gate = current_identity(
            vm, vm/manifest['candidate_directory'], requested)
        gate_errors.extend(validate_identity(
            {key:manifest[key] for key in identity_gate if key in manifest},
            identity_gate))
    except Exception:
        identity_gate = None; gate_errors.append('current_identity')

    cursor_after = full_host.get('journal_cursor') if isinstance(full_host, dict) else None
    messages = full_host.get('journal_messages') if isinstance(full_host, dict) else None
    after_position = _journal_cursor_position(cursor_after, boot_id)
    if before_position is None or after_position is None or after_position < before_position:
        gate_errors.append('kernel_cursor')
    if not isinstance(messages, list):
        gate_errors.append('kernel_messages')
    if gate_errors:
        raise ValueError('warm qualification refused: '+','.join(
            sorted(set(gate_errors))))

    final, errors = warm_qualification_authorization(
        vm, manifest, manifest_path, output, policy_sha, activation_sha)
    if errors or final is None or final.get('receipt') != recovery:
        raise ValueError('warm qualification refused: '+','.join(
            sorted(set(errors or ['receipt']))))
    immutable = (
        'policy_raw', 'activation_raw', 'ledger_raw', 'manifest_raws',
        'receipt_raws', 'candidate176_receipt_raws',
        'candidate177_receipt_raws', 'a_activation_raw',
    )
    if any(final.get(key) != checked.get(key) for key in immutable):
        raise ValueError('warm qualification refused: concurrent_change')
    gate = {
        'kernel_cursor_before':cursor_before,
        'kernel_cursor_after':cursor_after,
        'kernel_messages':messages,
        'host_gate':host_gate,
        'vfio_gate':vfio_gate,
        'identity_gate':identity_gate,
        'active_launch_units':units,
        'pending_launches':pending_names,
    }
    warm = helper('warm-qualification')
    path, updated = warm.build_reservation(
        final, boot_id, experiment, recovery, gate, time.time())
    replace_json(path, updated)
    return cursor_after


def reserve_boot(directory, boot_id, experiment, recovery=None,
                 manifest=None, manifest_path=None):
    if not re.fullmatch(r'[A-Za-z0-9-]+', boot_id):
        raise ValueError('invalid host boot ID')
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (boot_id+'.json')
    if not path.exists():
        write_once(path, {'schema':2, 'boot_id':boot_id, 'max_launches':3,
                          'launches':[{'run_id':experiment, 'reserved_epoch':time.time()}]})
        return
    if recovery is None: raise FileExistsError(path)
    ledger_raw = path.read_bytes()
    ledger = read_boot_ledger(path); launches = ledger.get('launches', [])
    prior = launches[-1].get('run_id') if launches else None
    startup = isinstance(recovery, dict) and recovery.get('schema') == 4
    retained = isinstance(recovery, dict) and recovery.get('schema') == 7
    error_key = ('startup_noqueue_receipt' if startup else
                 'retained_kiq_continuation_receipt' if retained else
                 'recovery_receipt')
    vm = directory.parent.parent
    errors = validate_reuse_receipt(
        recovery, boot_id, prior, vm if startup or retained else None,
        experiment if retained else None, manifest if retained else None,
        manifest_path if retained else None)
    if len(launches) >= 3: errors.append('launch_ceiling')
    if any(row.get('run_id') == experiment for row in launches): errors.append('run_id_reused')
    if recovery.get('recovery_id') in {row.get('recovery_id') for row in launches}:
        errors.append(error_key)
    if startup and recovery.get('attempt_id') in {
            row.get('attempt_id') for row in launches}:
        errors.append('startup_noqueue_receipt')
    if retained and recovery.get('authorization_id') in {
            row.get('authorization_id') for row in launches}:
        errors.append('retained_kiq_continuation_receipt')
    # The startup-only proof binds the exact newline-preserving ledger preimage.
    # Re-read immediately before append so an admission-time proof cannot reserve
    # against a stale or reformatted ledger.
    if startup or retained:
        current_raw = path.read_bytes()
        if (current_raw != ledger_raw or
                hashlib.sha256(current_raw).hexdigest() !=
                recovery.get('ledger_sha256')):
            errors.append(error_key)
    if errors: raise ValueError('reuse reservation refused: '+','.join(sorted(set(errors))))
    reservation = {'run_id':experiment, 'reserved_epoch':time.time(),
                   'recovery_id':recovery['recovery_id'], 'prior_run_id':prior}
    if startup:
        reservation['attempt_id'] = recovery['attempt_id']
    if retained:
        reservation['authorization_id'] = recovery['authorization_id']
    launches.append(reservation)
    ledger.update(schema=2, boot_id=boot_id, max_launches=3, launches=launches)
    ledger.pop('experiment', None)
    replace_json(path, ledger)


def reserve_launch_and_cursor(directory, boot_id, experiment, recovery,
                              manifest, manifest_path, cap_revision=None,
                              warm_qualification=None, output=None,
                              candidate179=None):
    modes = sum(value is not None for value in (
        cap_revision, warm_qualification, candidate179))
    if modes > 1:
        raise ValueError('mixed launch authority')
    if candidate179 is not None:
        return reserve_candidate179_qualification(
            directory, boot_id, experiment, recovery, manifest,
            manifest_path, output, candidate179)
    if warm_qualification is not None:
        return reserve_warm_qualification(
            directory, boot_id, experiment, recovery, manifest,
            manifest_path, output, warm_qualification)
    if cap_revision is not None:
        return reserve_cap_revision(
            directory, boot_id, experiment, recovery, manifest,
            manifest_path, cap_revision)
    reserve_boot(directory, boot_id, experiment, recovery, manifest, manifest_path)
    return kernel_updates()[0]


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


def run_one(vm, manifest_path, output, resume_prelaunch=None, prelaunch_proof=None,
            cap_revision_authority_sha256=None,
            warm_qualification_policy_sha256=None,
            warm_qualification_activation_sha256=None,
            candidate179_policy_sha256=None,
            candidate179_activation_sha256=None,
            one_run_policy_sha256=None,
            one_run_activation_sha256=None):
    """One bounded launch; a verified prior recovery may authorize same-boot reuse."""
    one_run_requested = bool(one_run_policy_sha256 or one_run_activation_sha256)
    if bool(one_run_policy_sha256) != bool(one_run_activation_sha256):
        raise ValueError('one-run qualification requires policy and activation hashes')
    if one_run_requested and (candidate179_policy_sha256 or
                              candidate179_activation_sha256):
        raise ValueError('one-run qualification cannot use another launch mode')
    qualification_helper = 'candidate179-qualification'
    qualification_label = 'candidate179'
    if one_run_requested:
        candidate179_policy_sha256 = one_run_policy_sha256
        candidate179_activation_sha256 = one_run_activation_sha256
        qualification_helper = 'one-run-qualification'
        qualification_label = 'one-run'
    if bool(resume_prelaunch) != bool(prelaunch_proof):
        raise ValueError('prelaunch continuation requires both evidence paths')
    if cap_revision_authority_sha256 and resume_prelaunch:
        raise ValueError('cap revision cannot use prelaunch continuation')
    warm_requested = bool(warm_qualification_policy_sha256 or
                          warm_qualification_activation_sha256)
    if bool(warm_qualification_policy_sha256) != bool(
            warm_qualification_activation_sha256):
        raise ValueError('warm qualification requires policy and activation hashes')
    if warm_requested and (resume_prelaunch or cap_revision_authority_sha256):
        raise ValueError('warm qualification cannot use another launch mode')
    candidate179_requested = bool(candidate179_policy_sha256 or
                                  candidate179_activation_sha256)
    if bool(candidate179_policy_sha256) != bool(candidate179_activation_sha256):
        raise ValueError('candidate179 qualification requires policy and activation hashes')
    if candidate179_requested and (resume_prelaunch or
            cap_revision_authority_sha256 or warm_requested):
        raise ValueError('candidate179 qualification cannot use another launch mode')
    manifest = json.loads(manifest_path.read_text())
    validate_manifest_replay_contract(manifest)
    if (manifest.get('gpu') is True and
            manifest.get('recovery_lease_schema') not in (2, 3)):
        raise ValueError('GPU run requires a supported recovery lease manifest')
    missing = required_identity(manifest)
    if missing: raise ValueError('incomplete prepared identity: '+','.join(missing))
    if manifest.get('bootdisk_verified') is not True:
        raise ValueError('actual bootdisk content has not been verified')
    candidate179 = None
    if candidate179_requested:
        candidate179, errors = candidate179_authorization(
            vm, manifest, manifest_path, output,
            candidate179_policy_sha256, candidate179_activation_sha256,
            qualification_helper, qualification_label)
        if errors or candidate179 is None:
            raise ValueError(qualification_label + ' qualification refused: '+','.join(
                sorted(set(errors or [qualification_label + '_authority']))))
    supervisor = helper('vm-supervision'); classifier = helper('classify-run')
    guest_shutdown = helper('guest-shutdown')
    recovery_tool = helper('vfio-recover') if manifest.get('gpu') is True else None
    state = None; probe = None; failure = None; shutdown_result = None; host_messages = []
    recovery_result = None
    running_validated = False
    monitor = None
    output_initialized = False
    def initialize_output():
        nonlocal output_initialized
        if output_initialized:
            return
        output.mkdir(parents=True, exist_ok=False)
        if candidate179_requested:
            write_bytes_once(output/'manifest.json', candidate179['manifest_raw'])
        else:
            write_once(output/'manifest.json', manifest)
        output_initialized = True
    if not candidate179_requested:
        initialize_output()
    def cancelled(signum, frame): raise RuntimeError('experiment cancelled')
    def host_fault(signum, frame): raise RuntimeError(monitor.error or 'host monitor aborted exposure')
    previous = signal.signal(signal.SIGTERM, cancelled)
    previous_fault = signal.signal(signal.SIGUSR1, host_fault)
    try:
        with (vm/'run/experiment.lock').open('a') as owner:
            fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with (vm/'run/redeploy.lock').open('a') as media:
                fcntl.flock(media, fcntl.LOCK_EX | fcntl.LOCK_NB)
                if candidate179_requested:
                    locked, errors = candidate179_authorization(
                        vm, manifest, manifest_path, output,
                        candidate179_policy_sha256,
                        candidate179_activation_sha256,
                        qualification_helper, qualification_label)
                    immutable = ('policy_raw', 'activation_raw', 'manifest_raw',
                                 'ledger_raw', 'receipt_raws', 'card_raw',
                                 'design_raw')
                    changed = ([key for key in immutable
                                if locked is not None and
                                locked.get(key) != candidate179.get(key)])
                    if errors or locked is None or changed:
                        raise ValueError(
                            'candidate179 qualification refused: concurrent_change' +
                            (':' + ','.join(changed) if changed else ''))
                    candidate179 = locked
                    initialize_output()
                pending = vm/'run/launch-pending'; pending.mkdir(exist_ok=True)
                if any(pending.iterdir()): raise ValueError('another supervised launch is pending')
                requested = manifest.get('spec', {}).get('requested_diagnostic')
                observed = current_identity(
                    vm, vm/manifest['candidate_directory'], requested,
                    manifest['run_id'] if manifest.get('gpu') is True else None,
                    manifest.get('recovery_lease_schema', 2))
                host = host_snapshot(); write_once(output/'host-before.json', host)
                used = vm/'run/used-gpu-boots'; used.mkdir(exist_ok=True)
                recovery = None; reuse_errors = []
                cap_revision = None; warm_qualification = None
                reservation_cursor = None
                continuation = None; continuation_ledger = None
                if resume_prelaunch:
                    cursor_result = kernel_updates()
                    continuation, continuation_ledger, continuation_ledger_bytes = \
                        validate_prelaunch_continuation(
                            vm, manifest_path, manifest, resume_prelaunch,
                            prelaunch_proof, observed, host, cursor_result)
                    errors = []
                else:
                    errors = validate_identity(
                        {key:manifest[key] for key in observed if key in manifest}, observed)
                if manifest.get('gpu') is False:
                    if resume_prelaunch: errors.append('gpu_less_continuation')
                    if cap_revision_authority_sha256:
                        errors.append('gpu_less_cap_revision')
                    if warm_requested:
                        errors.append('gpu_less_warm_qualification')
                    if host['active_vm']: errors.append('active_vm')
                elif not resume_prelaunch:
                    if candidate179_requested:
                        recovery = candidate179['receipt']
                    elif warm_requested:
                        warm_qualification, reuse_errors = \
                            warm_qualification_authorization(
                                vm, manifest, manifest_path, output,
                                warm_qualification_policy_sha256,
                                warm_qualification_activation_sha256,
                                classifier)
                        if warm_qualification is not None:
                            recovery = warm_qualification['receipt']
                    elif cap_revision_authority_sha256:
                        cap_revision, reuse_errors = cap_revision_authorization(
                            vm, manifest, manifest_path,
                            cap_revision_authority_sha256)
                        if cap_revision is not None:
                            recovery = cap_revision['receipt']
                    else:
                        # Schema-2 launches have no generic same-boot authority.
                        # A reviewed finite policy must select and bind one exact
                        # launch instead of inheriting the historical rolling cap.
                        recovery = None
                        if (used/(host['boot_id']+'.json')).exists():
                            reuse_errors = ['v2_reuse_requires_finite_authority']
                    errors += reuse_errors
                    errors += admit(manifest, host, {p.stem for p in used.glob('*.json')},
                                    reuse_allowed=recovery is not None)
                if not host['sleep_inhibited']: errors.append('sleep_inhibited')
                if errors: raise ValueError('admission refused: '+','.join(errors))
                if manifest.get('gpu') is not False and not resume_prelaunch:
                    reservation_cursor = reserve_launch_and_cursor(
                        used, host['boot_id'], manifest['run_id'], recovery,
                        manifest, manifest_path, cap_revision,
                        warm_qualification, output, candidate179)
                cursor = (cursor_result[0] if resume_prelaunch else
                          reservation_cursor or kernel_updates()[0])
                monitor = HostMonitor(cursor, lambda:os.kill(os.getpid(), signal.SIGUSR1))
                monitor.start()
                if manifest.get('gpu') is not False:
                    if resume_prelaunch:
                        marker_dir = vm/'run/prelaunch-continuations'
                        marker_dir.mkdir(exist_ok=True)
                        marker = prelaunch_continuation_marker(
                            vm, host['boot_id'], manifest['run_id'])
                        continuation['marker'] = str(marker.resolve())
                        write_once(output/'prelaunch-continuation.json', continuation)
                        # This per-boot/run O_EXCL marker is consumed before VFIO opens.
                        write_once(marker, continuation)
                        if continuation_ledger.read_bytes() != continuation_ledger_bytes:
                            raise RuntimeError('boot ledger changed before VFIO continuation')
                    if (resume_prelaunch and
                            continuation_ledger.read_bytes() != continuation_ledger_bytes):
                        raise RuntimeError('boot ledger changed during prelaunch continuation')
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
                events = parse_manifest_serial(classifier, manifest, serial)
                if definitive_capture_loss(events):
                    raise RuntimeError('definitive critical capture loss; aborting exposure')
                if manifest.get('gpu') is False and any(e['kind'] == 'build' and
                        e['build'] == manifest['build_id'] for e in events) and not any(
                        e['kind'] == 'capture_loss' for e in events):
                    break
                result = classifier.classify_probe_readiness(manifest, events)
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
    replay_evidence = {}
    if (manifest.get('gpu') is not False and state and shutdown_result and
            shutdown_result.get('outcome') != 'STOP_UNCONFIRMED' and
            not (monitor and monitor.error)):
        try:
            recovery_serial = (vm/'run/serial.log').read_text(errors='replace')
            recovery_result = recover_v2(
                recovery_tool, vm, manifest, recovery_serial, replay_evidence)
        except BaseException as error:
            recovery_result = {'status':'failed',
                               'error':type(error).__name__+': '+str(error)}
    initialize_output()
    serial = (vm/'run/serial.log').read_text(errors='replace') if state else ''
    (output/'serial.txt').write_text(serial)
    agent_events = vm/'run/agent-server-events.jsonl'
    if agent_events.is_file():
        (output/'agent-server-events.jsonl').write_bytes(agent_events.read_bytes())
    events = parse_manifest_serial(classifier, manifest, serial)
    (output/'events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events))
    if probe is not None: write_once(output/'probe.json', probe)
    write_once(output/'shutdown.json', shutdown_result)
    write_once(output/'host-after.json', host_snapshot())
    write_once(output/'host-kernel-messages.json', host_messages)
    if recovery_result is not None: write_once(output/'recovery.json', recovery_result)
    if replay_evidence: write_once(output/'recovery-replay.json', replay_evidence)
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
    parser.add_argument('--run-id', help='explicit 32-hex launch identity already staged in boot arguments')
    parser.add_argument('--gpu-less', action='store_true', help='prepare a no-passthrough coordinator validation')
    parser.add_argument('--resume-prelaunch', type=Path)
    parser.add_argument('--prelaunch-proof', type=Path)
    parser.add_argument('--cap-revision-authority-sha256')
    parser.add_argument('--warm-qualification-policy-sha256')
    parser.add_argument('--warm-qualification-activation-sha256')
    parser.add_argument('--candidate179-policy-sha256')
    parser.add_argument('--candidate179-activation-sha256')
    parser.add_argument('--one-run-policy-sha256')
    parser.add_argument('--one-run-activation-sha256')
    args = parser.parse_args()
    one_run_requested = bool(args.one_run_policy_sha256 or
                             args.one_run_activation_sha256)
    if bool(args.one_run_policy_sha256) != bool(args.one_run_activation_sha256):
        parser.error('one-run qualification requires both hashes')
    if one_run_requested and args.action != 'run':
        parser.error('one-run qualification is only valid with run')
    if one_run_requested and (args.resume_prelaunch or args.cap_revision_authority_sha256 or
                              args.warm_qualification_policy_sha256 or
                              args.candidate179_policy_sha256):
        parser.error('one-run qualification cannot be combined with another launch mode')
    if ((args.resume_prelaunch or args.prelaunch_proof) and args.action != 'run'):
        parser.error('prelaunch continuation options are only valid with run')
    if bool(args.resume_prelaunch) != bool(args.prelaunch_proof):
        parser.error('prelaunch continuation requires both evidence paths')
    if args.cap_revision_authority_sha256 and args.action != 'run':
        parser.error('cap revision authority is only valid with run')
    if args.cap_revision_authority_sha256 and args.resume_prelaunch:
        parser.error('cap revision authority cannot be combined with prelaunch continuation')
    warm_requested = bool(args.warm_qualification_policy_sha256 or
                          args.warm_qualification_activation_sha256)
    if bool(args.warm_qualification_policy_sha256) != bool(
            args.warm_qualification_activation_sha256):
        parser.error('warm qualification requires both hashes')
    if warm_requested and args.action != 'run':
        parser.error('warm qualification is only valid with run')
    if warm_requested and (args.resume_prelaunch or
                           args.cap_revision_authority_sha256):
        parser.error('warm qualification cannot be combined with another launch mode')
    candidate179_requested = bool(args.candidate179_policy_sha256 or
                                  args.candidate179_activation_sha256)
    if bool(args.candidate179_policy_sha256) != bool(
            args.candidate179_activation_sha256):
        parser.error('candidate179 qualification requires both hashes')
    if candidate179_requested and args.action != 'run':
        parser.error('candidate179 qualification is only valid with run')
    if candidate179_requested and (args.resume_prelaunch or
            args.cap_revision_authority_sha256 or warm_requested):
        parser.error('candidate179 qualification cannot be combined with another launch mode')
    if args.gpu_less and args.action != 'prepare':
        parser.error('--gpu-less is only valid with prepare; run uses the explicit prepared mode')
    if args.run_id and args.action != 'prepare':
        parser.error('--run-id is only valid with prepare')
    if args.action == 'prepare' and not args.gpu_less and not args.run_id:
        parser.error('GPU prepare requires --run-id')
    if args.action == 'host': result = host_snapshot()
    elif args.action == 'prepare':
        if not args.spec or not args.output: parser.error('prepare requires --spec and --output')
        result = prepare(args.vm_dir.resolve(), args.spec, args.output,
                         gpu=not args.gpu_less, run_id=args.run_id)
    else:
        if not args.manifest or not args.output: parser.error('run requires --manifest and --output')
        result = run_one(args.vm_dir.resolve(), args.manifest, args.output,
                         args.resume_prelaunch, args.prelaunch_proof,
                         args.cap_revision_authority_sha256,
                         args.warm_qualification_policy_sha256,
                         args.warm_qualification_activation_sha256,
                         args.candidate179_policy_sha256,
                         args.candidate179_activation_sha256,
                         args.one_run_policy_sha256,
                         args.one_run_activation_sha256)
    print(json.dumps(result, indent=2))
