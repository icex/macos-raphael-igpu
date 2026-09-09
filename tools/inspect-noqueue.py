#!/usr/bin/env python3
"""Create nonauthorizing evidence from a selector-only stopped-GPU inspection."""
import argparse
import fcntl
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import time


def _helper(name):
    path = Path(__file__).with_name(name + '.py')
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RECOVERY = _helper('vfio-recover')
EXPERIMENT = _helper('experiment')

BOOT_ID = '5d6f45d0-4384-4340-b819-7751bc26ebb3'
RUN_ID = 'e583a1b2d97a4ad3b607c1d20a29a812'
BUILD_ID = 'b60df7448ea24106ae4300f6760cb171'
CID = '68919eed2dce887271e257ef6dca7f1849d4917bcfbb0b31496fdb82f7654614'
ACTUAL_KERNEL_CURSOR = (
    's=98f6cb2295dc45898ee97031451ba7c8;i=3de99;'
    'b=5d6f45d043844340b8197751bc26ebb3;m=f7aa1da1;'
    't=65b07593c52cd;x=406734b216ea3c05')
EXPECTED_RECOVERY_ERROR = (
    'RecoveryError: guest host-KIQ lifetime reservation is absent or invalid')
CONTINUATION_MARKER_RELATIVE = Path(
    f'run/prelaunch-continuations/{BOOT_ID}-{RUN_ID}.json')

PINNED_HASHES = {
    'ledger': '2d15f0cbb73d71e8efaf2a951f13c707726e9b98279a0e85208253f1941410d3',
    'manifest': '535ab074affacd019ce9fb389cb9657f610d6cbf7dcca7738de5cc7d298f0ddc',
    'serial': '0ba1b171ed24a2da8b8bd449ac5fb897abdfe33f788192f3c08cc42f294ba2bc',
    'supervision': 'bebe25c8eaa21cef44534758c264b38deca392ecbe7e179b01824b3cf01dd587',
    'shutdown': 'c51fe26d14d9b162f9927a447c14b52da8db4358a40f025ce102f1700a77f9c9',
    'recovery': '2f2de2d19dbc853e32ea05ff3db6a0b9a1a8b397494b4f6224d4bff7c3877039',
    'recovery_reservation': '2a6093acb017e83ce905047ab7ee662253ad40f9d3cd303f8cc79ddc55d4128b',
    'continuation': '3491ce539619b127c512a81ee648328d31438ed550f75dc2720d6c5a2f35806b',
    'marker': '3491ce539619b127c512a81ee648328d31438ed550f75dc2720d6c5a2f35806b',
    'events': 'f8f60f99606bdf70e293386c1e3748f1bb7c2bb86813e39d2a83aa8b2b85b5c5',
    'prelaunch_proof': '8ce5b30f1c2ef9dfac68b00dee29ed8254845dae64dc0832ad4a1295424b034b',
    'prelaunch_readiness': '86282b2a881f86b1fd4d770ec7f066c2014aab0b957b7211c0ed6c6f996f9053',
}

EXPECTED_SERIAL_BOUNDARY = {
    'build_id': BUILD_ID,
    'ordinary_records': 256,
    'ordinary_dropped': 128,
    'ordinary_truncated': 0,
    'critical_records': 34,
    'critical_dropped': 0,
    'critical_truncated': 0,
    'bar0_preflight_failed': True,
    'kiq_start_refused': True,
    'critical_events_complete': True,
}

# CP_RB1_ACTIVE follows CP_RB0_ACTIVE in the GC 10.3 register bank.
CP_RB1_ACTIVE_OFFSET = RECOVERY.CP_RB_ACTIVE_OFFSET + 4

GLOBAL_OFFSETS = {
    'cp_stat': RECOVERY.CP_STAT_OFFSET,
    'cpc_busy': RECOVERY.CP_CPC_BUSY_STAT_OFFSET,
    'me_cntl': RECOVERY.CP_ME_CNTL_OFFSET,
    'mec_cntl': RECOVERY.CP_MEC_CNTL_OFFSET,
    'rb0_active': RECOVERY.CP_RB_ACTIVE_OFFSET,
    'rb1_active': CP_RB1_ACTIVE_OFFSET,
    'rb_doorbell_control': RECOVERY.CP_RB_DOORBELL_CONTROL_OFFSET,
    'sdma0_cntl': RECOVERY.SDMA0_CNTL_OFFSET,
    'sdma0_f32_cntl': RECOVERY.SDMA0_F32_CNTL_OFFSET,
    'sdma0_gfx_rb_cntl': RECOVERY.SDMA0_GFX_RB_CNTL_OFFSET,
    'sdma0_gfx_ib_cntl': RECOVERY.SDMA0_GFX_IB_CNTL_OFFSET,
    'pq_wptr_poll_cntl': RECOVERY.CP_PQ_WPTR_POLL_CNTL_OFFSET,
    'pq_status': RECOVERY.CP_PQ_STATUS_OFFSET,
    'doorbell_range_lower': RECOVERY.CP_MEC_DOORBELL_RANGE_LOWER_OFFSET,
    'doorbell_range_upper': RECOVERY.CP_MEC_DOORBELL_RANGE_UPPER_OFFSET,
}
OBSERVATION_OFFSETS = (set(GLOBAL_OFFSETS.values()) |
                       {RECOVERY.CP_HQD_ACTIVE_OFFSET,
                        RECOVERY.CP_HQD_PQ_DOORBELL_OFFSET})
VALID_SELECTORS = ({0, 1} |
                   {RECOVERY.queue_selector(me, pipe, queue)
                    for me in (1, 2) for pipe in range(4) for queue in range(8)})


class InspectionError(RuntimeError):
    def __init__(self, message, evidence=None):
        super().__init__(message)
        self.evidence = evidence or {}


class GuardedTransport:
    """Expose only the reads and selector writes approved for this inspection."""
    def __init__(self, transport):
        self._transport = transport

    def read32(self, offset):
        if offset not in OBSERVATION_OFFSETS and offset != RECOVERY.NBIO_CONFIG_MEMSIZE_OFFSET:
            raise InspectionError(f'BAR5 read is forbidden at {offset:#x}')
        return self._transport.read32(offset)

    def write32(self, offset, value):
        if offset != RECOVERY.GRBM_GFX_CNTL_OFFSET:
            raise InspectionError(f'BAR5 write is forbidden at {offset:#x}')
        if type(value) is not int or value not in VALID_SELECTORS:
            raise InspectionError(f'GRBM selector value is forbidden: {value!r}')
        return self._transport.write32(offset, value)

    def read_vram32(self, offset):
        start = RECOVERY.HOST_KIQ_RESERVATION_OFFSET
        end = start + RECOVERY.HOST_KIQ_RESERVATION_SIZE
        if type(offset) is not int or offset & 3 or not start <= offset < end:
            raise InspectionError(f'BAR0 VRAM read is forbidden at {offset!r}')
        return self._transport.read_vram32(offset)

    def metadata(self):
        return self._transport.metadata()


def _read_descriptor(mmio):
    start = RECOVERY.HOST_KIQ_RESERVATION_OFFSET
    return b''.join(mmio.read_vram32(start + offset).to_bytes(4, 'little')
                    for offset in range(0, RECOVERY.HOST_KIQ_RESERVATION_SIZE, 4))


def _globals(mmio):
    return {name: mmio.read32(offset) for name, offset in GLOBAL_OFFSETS.items()}


def _selector_attempt(mmio, evidence, value, phase):
    row = {'sequence': len(evidence['selector_writes']), 'phase': phase,
           'value': value, 'attempted': True, 'completed': False}
    evidence['selector_writes'].append(row)
    try:
        mmio.write32(RECOVERY.GRBM_GFX_CNTL_OFFSET, value)
    except BaseException as error:
        row['error'] = type(error).__name__ + ': ' + str(error)
        return row, error
    row['completed'] = True
    return row, None


def _validate_device_evidence(evidence, expected_descriptor):
    if bytes.fromhex(evidence['reservation_after_hex']) != expected_descriptor:
        raise InspectionError('exact PENDING descriptor after inspection did not match', evidence)
    for pass_rows in evidence['compute_passes']:
        for row in pass_rows:
            for name in ('active', 'pq_doorbell_control'):
                if row[name] == 0xffffffff:
                    raise InspectionError(f'compute {name} is inaccessible/all-ones', evidence)
            if row['active'] & 1:
                raise InspectionError('compute queue is active', evidence)
    if evidence['compute_passes'][0] != evidence['compute_passes'][1]:
        raise InspectionError('compute snapshots changed between passes', evidence)
    for pass_rows in evidence['graphics_passes']:
        for row in pass_rows:
            for name in ('rb0_active', 'rb1_active', 'doorbell_control'):
                if row[name] == 0xffffffff:
                    raise InspectionError(f'graphics {name} is inaccessible/all-ones', evidence)
            if row['rb0_active'] & 1 or row['rb1_active'] & 1:
                raise InspectionError('graphics ring is active', evidence)
            if row['doorbell_control'] & 0xc0000000:
                raise InspectionError('graphics doorbell is enabled', evidence)
    if evidence['graphics_passes'][0] != evidence['graphics_passes'][1]:
        raise InspectionError('graphics snapshots changed between passes', evidence)
    before = evidence['globals_before']
    after = evidence['globals_after']
    for name, value in before.items():
        if value == 0xffffffff or after[name] == 0xffffffff:
            raise InspectionError(f'global {name} is inaccessible/all-ones', evidence)
    if before != after:
        raise InspectionError('global snapshots changed during inspection', evidence)
    if after['cp_stat'] != 0:
        raise InspectionError('CP_STAT is not zero', evidence)
    if after['cpc_busy'] != 0:
        raise InspectionError('CPC_BUSY is not zero', evidence)
    if after['rb0_active'] & 1 or after['rb1_active'] & 1:
        raise InspectionError('graphics ring is active', evidence)
    if after['rb_doorbell_control'] & 0xc0000000:
        raise InspectionError('graphics doorbell is enabled', evidence)
    if after['sdma0_cntl'] & RECOVERY.SDMA_AUTO_CTXSW_ENABLE_MASK:
        raise InspectionError('SDMA0 context switching is enabled', evidence)
    if after['sdma0_gfx_rb_cntl'] & RECOVERY.SDMA_RB_ENABLE_MASK:
        raise InspectionError('SDMA0 ring buffer is enabled', evidence)
    if after['sdma0_gfx_ib_cntl'] & RECOVERY.SDMA_IB_ENABLE_MASK:
        raise InspectionError('SDMA0 indirect buffer is enabled', evidence)
    if not after['sdma0_f32_cntl'] & RECOVERY.SDMA_HALT_MASK:
        raise InspectionError('SDMA0 is not halted', evidence)


def inspect_device(transport, run_id):
    """Take two complete, selector-only snapshots and authorize no action."""
    mmio = GuardedTransport(transport)
    expected = RECOVERY.host_kiq_reservation_descriptor(
        run_id, RECOVERY.HOST_KIQ_RESERVATION_PENDING)
    evidence = {
        'status': 'failed', 'authorizes_cleanup': False, 'authorizes_launch': False,
        'selector_writes': [], 'compute_passes': [], 'graphics_passes': [],
        'final_default': {'attempted': False, 'completed': False},
    }
    try:
        before = _read_descriptor(mmio)
        evidence['reservation_before_hex'] = before.hex()
        if before != expected:
            raise InspectionError('exact PENDING descriptor before inspection did not match',
                                  evidence)

        _, error = _selector_attempt(mmio, evidence, 0, 'globals-before-default')
        if error:
            raise error
        evidence['globals_before'] = _globals(mmio)

        for pass_number in (1, 2):
            queues = []
            evidence['compute_passes'].append(queues)
            for me in (1, 2):
                for pipe in range(4):
                    for queue in range(8):
                        selector = RECOVERY.queue_selector(me, pipe, queue)
                        _, error = _selector_attempt(
                            mmio, evidence, selector,
                            f'compute-pass-{pass_number}-me-{me}-pipe-{pipe}-queue-{queue}')
                        if error:
                            raise error
                        queues.append({
                            'me': me, 'pipe': pipe, 'queue': queue,
                            'selector': selector,
                            'active': mmio.read32(RECOVERY.CP_HQD_ACTIVE_OFFSET),
                            'pq_doorbell_control': mmio.read32(
                                RECOVERY.CP_HQD_PQ_DOORBELL_OFFSET),
                        })
            graphics = []
            evidence['graphics_passes'].append(graphics)
            for intended_pipe in (0, 1):
                _, error = _selector_attempt(
                    mmio, evidence, intended_pipe,
                    f'graphics-pass-{pass_number}-pipe-{intended_pipe}')
                if error:
                    raise error
                graphics.append({
                    'intended_pipe': intended_pipe, 'selector': intended_pipe,
                    'rb0_active': mmio.read32(RECOVERY.CP_RB_ACTIVE_OFFSET),
                    'rb1_active': mmio.read32(CP_RB1_ACTIVE_OFFSET),
                    'doorbell_control': mmio.read32(
                        RECOVERY.CP_RB_DOORBELL_CONTROL_OFFSET),
                })
        _, error = _selector_attempt(mmio, evidence, 0, 'globals-after-default')
        if error:
            raise error
        evidence['globals_after'] = _globals(mmio)
        evidence['reservation_after_hex'] = _read_descriptor(mmio).hex()
        evidence['vfio_region'] = mmio.metadata()
    except BaseException as error:
        if isinstance(error, InspectionError) and error.evidence is evidence:
            primary = error
        else:
            primary = InspectionError(type(error).__name__ + ': ' + str(error), evidence)
    else:
        primary = None
    finally:
        if evidence['selector_writes']:
            row, error = _selector_attempt(mmio, evidence, 0, 'final-default')
            evidence['final_default'] = dict(row)
            if error and primary is None:
                primary = InspectionError(
                    'final default selector posting failed: ' + str(error), evidence)

    if primary is not None:
        raise primary
    if not evidence['final_default']['completed']:
        raise InspectionError('final default selector was not completed', evidence)
    _validate_device_evidence(evidence, expected)
    evidence['status'] = 'observed-idle'
    return evidence


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _artifact_paths(vm, evidence_dir):
    return {
        'ledger': vm / 'run/used-gpu-boots' / f'{BOOT_ID}.json',
        'manifest': vm / 'run/metal-007-174-prelaunch-continuation-manifest.json',
        'serial': evidence_dir / 'serial.txt',
        'supervision': evidence_dir / 'supervision.json',
        'shutdown': evidence_dir / 'shutdown.json',
        'recovery': evidence_dir / 'recovery.json',
        'recovery_reservation': evidence_dir / 'recovery-reservation.json',
        'continuation': evidence_dir / 'prelaunch-continuation.json',
        'marker': vm / CONTINUATION_MARKER_RELATIVE,
        'events': evidence_dir / 'events.jsonl',
        'prelaunch_proof': vm / 'run/prelaunch-einval-probe-e583a1b2.json',
        'prelaunch_readiness': vm / 'run/prelaunch-readiness-e583a1b2.json',
    }


def _watchdogs():
    return {name: Path('/proc/sys/kernel', name).read_text().strip()
            for name in ('watchdog', 'nmi_watchdog', 'hardlockup_panic')}


def _container_running(cid):
    result = subprocess.run(
        ['docker', 'inspect', '--format', '{{json .State.Running}}', cid],
        text=True, capture_output=True, timeout=5)
    if result.returncode and re.search(r'no such (?:object|container)',
                                       result.stderr, re.I):
        return False
    if result.returncode or result.stdout.strip() not in ('true', 'false'):
        raise InspectionError('cannot establish exact container state')
    return result.stdout.strip() == 'true'


def _serial_boundary(serial, events):
    rows = [json.loads(line) for line in events.splitlines() if line]
    folded = re.sub(r'\s+', ' ', serial)
    split_start = serial.find('XQ2: preflight faiine.')
    split_end = serial.find('led: BAR0 mapping unavailable', split_start)
    split_bar0_failure = (split_start >= 0 and split_end >= 0 and
                          split_end - split_start < 128)
    return {
        'build_id': BUILD_ID,
        'ordinary_records': 256 if 'deferred diagnostics: 256 records' in serial else None,
        'ordinary_dropped': 128 if 'diagnostics end (dropped=128 truncated=0)' in serial else None,
        'ordinary_truncated': 0 if 'diagnostics end (dropped=128 truncated=0)' in serial else None,
        'critical_records': 34 if f'RGPU_RECORDS build={BUILD_ID} count=34 dropped=0 truncated=0' in serial else None,
        'critical_dropped': 0 if rows and all(row.get('build') == BUILD_ID for row in rows) else None,
        'critical_truncated': 0 if len(rows) == 34 else None,
        'bar0_preflight_failed': (
            'XQ2: preflight failed: BAR0 mapping unavailable' in folded or
            split_bar0_failure),
        'kiq_start_refused': 'XQ2: startKIQ refused: preflight or genuine dequeue failed' in serial,
        'critical_events_complete': (len(rows) == 34 and
                                     [row.get('seq') for row in rows] == list(range(34))),
    }


def collect_proof(vm, evidence_dir, journal_cursor=None):
    paths = _artifact_paths(vm, evidence_dir)
    blobs = {name: path.read_bytes() for name, path in paths.items()}
    parsed = {name: json.loads(blobs[name]) for name in
              ('ledger', 'manifest', 'supervision', 'shutdown', 'recovery',
               'recovery_reservation', 'continuation', 'marker')}
    continuation = parsed['continuation']
    cursor, messages, faults = RECOVERY.kernel_updates(
        journal_cursor if journal_cursor is not None else continuation['kernel_cursor'])
    artifact_manifest = (evidence_dir / 'manifest.json').read_bytes()
    return {
        'boot_id': BOOT_ID, 'run_id': RUN_ID,
        'host': dict(RECOVERY.host_state(), watchdogs=_watchdogs()),
        'ledger_sha256': _sha256(blobs['ledger']), 'ledger': parsed['ledger'],
        'artifact_sha256': {name: _sha256(blob) for name, blob in blobs.items()},
        'manifest': parsed['manifest'],
        'artifact_manifest_equal': artifact_manifest == blobs['manifest'],
        'supervision': parsed['supervision'], 'shutdown': parsed['shutdown'],
        'recovery': parsed['recovery'],
        'recovery_reservation': parsed['recovery_reservation'],
        'continuation': continuation,
        'marker_equal': blobs['marker'] == blobs['continuation'],
        'continuation_marker_matches': Path(continuation['marker']) == paths['marker'],
        'serial_boundary': _serial_boundary(
            blobs['serial'].decode(errors='strict'),
            blobs['events'].decode(errors='strict')),
        'container_running': _container_running(CID),
        'residual_units': EXPERIMENT.active_launch_units(),
        'journal_cursor': cursor, 'journal_messages': messages,
        'journal_faults': faults,
    }


def validate_pre_vfio(proof):
    errors = []
    if proof.get('boot_id') != BOOT_ID or proof.get('run_id') != RUN_ID:
        errors.append('pinned boot/run')
    host = proof.get('host', {})
    errors.extend('host ' + name for name in RECOVERY.validate_host_state(host, BOOT_ID))
    if host.get('pci_command') != 3:
        errors.append('host PCI_COMMAND')
    if host.get('watchdogs') != {'watchdog': '1', 'nmi_watchdog': '1',
                                 'hardlockup_panic': '1'}:
        errors.append('host watchdogs')
    if proof.get('artifact_sha256') != PINNED_HASHES:
        for name, digest in PINNED_HASHES.items():
            if proof.get('artifact_sha256', {}).get(name) != digest:
                errors.append(name + ' hash')
    ledger = proof.get('ledger', {})
    launches = ledger.get('launches', []) if isinstance(ledger, dict) else []
    if (proof.get('ledger_sha256') != PINNED_HASHES['ledger'] or
            ledger.get('schema') != 2 or ledger.get('boot_id') != BOOT_ID or
            ledger.get('max_launches') != 3 or len(launches) != 1 or
            launches[-1].get('run_id') != RUN_ID):
        errors.append('exact latest ledger')
    manifest = proof.get('manifest', {})
    if (manifest.get('boot_id'), manifest.get('run_id'), manifest.get('build_id')) != (
            BOOT_ID, RUN_ID, BUILD_ID) or proof.get('artifact_manifest_equal') is not True:
        errors.append('exact manifest identity')
    supervision = proof.get('supervision', {})
    if (supervision.get('cid') != CID or supervision.get('max_seconds') != 180 or
            supervision.get('timer_unit') != f'rgpu-deadline-{CID}.timer' or
            supervision.get('serial_unit') != f'rgpu-serial-{CID}.service' or
            not re.fullmatch(r'rgpu-launch-[0-9a-f]{32}\.service',
                             str(supervision.get('launch_unit', '')))):
        errors.append('exact supervision/CID')
    shutdown = proof.get('shutdown', {})
    if shutdown.get('cid') != CID or shutdown.get('outcome') != 'exited-after-guest-request':
        errors.append('clean guest shutdown')
    if proof.get('container_running') is not False:
        errors.append('exact container still running')
    recovery = proof.get('recovery', {})
    if recovery != {'status': 'failed', 'error': EXPECTED_RECOVERY_ERROR}:
        errors.append('recovery boundary')
    reservation = proof.get('recovery_reservation', {})
    if (reservation.get('boot_id'), reservation.get('run_id'), reservation.get('state')) != (
            BOOT_ID, RUN_ID, 'pending'):
        errors.append('pending recovery reservation')
    continuation = proof.get('continuation', {})
    expected_continuation = (
        continuation.get('schema') == 1 and
        continuation.get('kind') == 'one-shot-prelaunch-continuation' and
        continuation.get('boot_id') == BOOT_ID and continuation.get('run_id') == RUN_ID and
        continuation.get('kernel_cursor') == ACTUAL_KERNEL_CURSOR and
        continuation.get('ledger_sha256') == PINNED_HASHES['ledger'] and
        continuation.get('replacement_manifest_sha256') == PINNED_HASHES['manifest'] and
        proof.get('continuation_marker_matches') is True and
        proof.get('marker_equal') is True)
    if not expected_continuation:
        errors.append('consumed continuation marker')
    if proof.get('serial_boundary') != EXPECTED_SERIAL_BOUNDARY:
        errors.append('serial/build/startup boundary')
    if proof.get('residual_units') != []:
        errors.append('residual unit/watchdog')
    if proof.get('journal_faults') != []:
        errors.append('kernel fault since actual-174 boundary')
    resets = [message for message in proof.get('journal_messages', []) if re.search(
        rf'vfio-pci {re.escape(RECOVERY.DEVICE)}: (?:resetting|reset done)\b', message, re.I)]
    if resets:
        errors.append('implicit reset since actual-174 boundary')
    return errors


def _stable_pre_post_errors(before, after):
    errors = validate_pre_vfio(after)
    for name in ('boot_id', 'run_id', 'host', 'ledger_sha256', 'ledger',
                 'artifact_sha256', 'manifest', 'artifact_manifest_equal',
                 'supervision', 'shutdown', 'recovery', 'recovery_reservation',
                 'continuation', 'marker_equal', 'serial_boundary',
                 'continuation_marker_matches',
                 'container_running', 'residual_units'):
        if before.get(name) != after.get(name):
            errors.append('post-inspection ' + name + ' changed')
    if after.get('journal_faults'):
        errors.append('post-inspection kernel fault')
    if after.get('residual_units'):
        errors.append('post-inspection residual unit')
    return errors


def perform_inspection(preflight_reader, transport_factory, postflight_reader):
    try:
        pre = preflight_reader()
    except BaseException as error:
        raise InspectionError(
            'pre-VFIO proof collection failed: ' + type(error).__name__ + ': ' + str(error),
            {'schema': 1, 'kind': 'stopped-gpu-noqueue-inspection',
             'status': 'failed', 'authorizes_cleanup': False,
             'authorizes_launch': False}) from error
    errors = validate_pre_vfio(pre)
    if errors:
        raise InspectionError('pre-VFIO proof failed: ' + ', '.join(errors),
                              {'preflight': pre})
    device_error = None
    device = None
    try:
        with transport_factory() as transport:
            device = inspect_device(transport, RUN_ID)
    except BaseException as error:
        if isinstance(error, InspectionError):
            device_error = error
            device = error.evidence
        else:
            device_error = InspectionError(
                'transport boundary ' + type(error).__name__ + ': ' + str(error))
            if device is None:
                device = device_error.evidence
    try:
        post = postflight_reader(pre['journal_cursor'])
        post_errors = _stable_pre_post_errors(pre, post)
    except BaseException as error:
        post = {'collection_error': type(error).__name__ + ': ' + str(error)}
        post_errors = ['post-inspection proof collection failed']
    combined = {
        'schema': 1, 'kind': 'stopped-gpu-noqueue-inspection',
        'status': 'failed', 'authorizes_cleanup': False, 'authorizes_launch': False,
        'boot_id': BOOT_ID, 'run_id': RUN_ID, 'build_id': BUILD_ID,
        'preflight': pre, 'device': device, 'postflight': post,
    }
    if device_error is not None:
        combined['device_error'] = str(device_error)
    if post_errors:
        combined['postflight_errors'] = post_errors
    if device_error is not None or post_errors:
        parts = []
        if device_error is not None:
            parts.append('device inspection: ' + str(device_error))
        if post_errors:
            parts.append('post-inspection: ' + ', '.join(post_errors))
        raise InspectionError('; '.join(parts), combined)
    combined['status'] = 'observed-idle'
    return combined


def write_inspection_once(path, evidence):
    RECOVERY.write_once(path, evidence)


def inspect_once(vm, evidence_dir, output):
    vm = Path(vm).resolve()
    evidence_dir = Path(evidence_dir).resolve()
    output = Path(output).resolve()
    expected_directory = (vm / 'run/noqueue-inspections').resolve()
    if output.parent != expected_directory or output.suffix != '.json':
        raise InspectionError(
            f'output must use distinct noqueue inspection path below: {expected_directory}')
    lock_path = vm / 'run/experiment.lock'
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError(f'inspection artifact already exists: {output}')
    with lock_path.open('a') as owner:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            result = perform_inspection(
                lambda: collect_proof(vm, evidence_dir), RECOVERY.LegacyVfio,
                lambda cursor: collect_proof(vm, evidence_dir, cursor))
        except InspectionError as error:
            result = error.evidence or {
                'schema': 1, 'kind': 'stopped-gpu-noqueue-inspection',
                'status': 'failed', 'authorizes_cleanup': False,
                'authorizes_launch': False, 'error': str(error),
            }
            result['status'] = 'failed'
            result.setdefault('schema', 1)
            result.setdefault('kind', 'stopped-gpu-noqueue-inspection')
            result['authorizes_cleanup'] = False
            result['authorizes_launch'] = False
            result['error'] = str(error)
            result['created_epoch'] = time.time()
            write_inspection_once(output, result)
            raise
        result['created_epoch'] = time.time()
        write_inspection_once(output, result)
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vm-dir', required=True, type=Path)
    parser.add_argument('--evidence-dir', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = inspect_once(args.vm_dir.resolve(), args.evidence_dir.resolve(),
                              args.output.resolve())
    except BaseException as error:
        print(json.dumps({'status': 'failed', 'authorizes_cleanup': False,
                          'authorizes_launch': False,
                          'error': type(error).__name__ + ': ' + str(error)}, indent=2))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
