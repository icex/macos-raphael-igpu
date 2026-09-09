#!/usr/bin/env python3
"""One-shot startup-noqueue cleanup for the pinned candidate-174 failure."""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import sys
import time
import uuid


def _helper(name):
    path = Path(__file__).with_name(name + '.py')
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RECOVERY = _helper('vfio-recover')
INSPECTOR = _helper('inspect-noqueue')

BOOT_ID = INSPECTOR.BOOT_ID
RUN_ID = INSPECTOR.RUN_ID
BUILD_ID = INSPECTOR.BUILD_ID
INSPECTION_SHA256 = '42b7549d1964a5c4f7117c08afb246a3c406f0817e4374c8df2b51280d823d9c'
ARCHIVE_SHA256 = 'd92043abcbd6d921c01db404db38dc1e7dbfd6a92e5624e1b5cc97961664b4c3'
LEDGER_SHA256 = INSPECTOR.PINNED_HASHES['ledger']
PINNED_DEVICE_SHA256 = 'd5d2ad074b8ebf2a0b29c1b9329179cca79acb8127432c43ffc3ac8e50581768'
ARCHIVE_FILES = (
    'agent-server-events.jsonl', 'events.jsonl', 'host-after.json',
    'host-before.json', 'host-kernel-messages.json', 'manifest.json',
    'prelaunch-continuation.json', 'recovery-reservation.json', 'recovery.json',
    'running-identity.json', 'serial.txt', 'shutdown.json', 'supervision.json',
    'verdict.json',
)

SDMA0_STATUS_REG_OFFSET = (RECOVERY.GC_SEG0 + 0x0025) * 4
SDMA_STATUS_IDLE_MASK = 0x00000001
SDMA_AUX_OFFSETS = {
    'status': SDMA0_STATUS_REG_OFFSET,
    'page_rb_cntl': (RECOVERY.GC_SEG0 + 0x00d8) * 4,
    'page_ib_cntl': (RECOVERY.GC_SEG0 + 0x00e2) * 4,
    'rlc0_rb_cntl': (RECOVERY.GC_SEG0 + 0x0130) * 4,
    'rlc0_ib_cntl': (RECOVERY.GC_SEG0 + 0x013a) * 4,
    'rlc1_rb_cntl': (RECOVERY.GC_SEG0 + 0x0188) * 4,
    'rlc1_ib_cntl': (RECOVERY.GC_SEG0 + 0x0192) * 4,
}


class StartupRecoveryError(RuntimeError):
    def __init__(self, message, evidence=None):
        super().__init__(message)
        self.evidence = evidence or {}


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def source_hashes():
    """Bind the cleanup and admission implementation actually in use."""
    paths = {
        'startup-noqueue-recover.py': Path(__file__),
        'inspect-noqueue.py': Path(__file__).with_name('inspect-noqueue.py'),
        'vfio-recover.py': Path(__file__).with_name('vfio-recover.py'),
        'experiment.py': Path(__file__).with_name('experiment.py'),
        'inspection.json': (Path(__file__).parents[1] /
                            'findings/recovery-tests/startup-noqueue-174/inspection.json'),
    }
    return {name: _sha256(path.read_bytes()) for name, path in paths.items()}


def archive_digest(evidence_dir):
    """Hash canonical JSON of the exact 14-file origin filename/digest map."""
    root = Path(evidence_dir)
    mapping = {name: _sha256((root / name).read_bytes()) for name in ARCHIVE_FILES}
    encoded = (json.dumps(mapping, sort_keys=True, separators=(',', ':')) + '\n').encode()
    return _sha256(encoded), mapping


def _archive_map_digest(mapping):
    encoded = (json.dumps(mapping, sort_keys=True, separators=(',', ':')) + '\n').encode()
    return _sha256(encoded)


def _read_descriptor(mmio):
    start = RECOVERY.HOST_KIQ_RESERVATION_OFFSET
    return b''.join(mmio.read_vram32(start + at).to_bytes(4, 'little')
                    for at in range(0, RECOVERY.HOST_KIQ_RESERVATION_SIZE, 4))


def _unhalted_scan_errors(scan):
    errors = []
    expected = RECOVERY.host_kiq_reservation_descriptor(
        RUN_ID, RECOVERY.HOST_KIQ_RESERVATION_PENDING).hex()
    exact_keys = {'status', 'authorizes_cleanup', 'authorizes_launch',
                  'selector_writes', 'compute_passes', 'graphics_passes',
                  'final_default', 'reservation_before_hex',
                  'reservation_after_hex', 'globals_before', 'globals_after',
                  'vfio_region'}
    if not isinstance(scan, dict) or set(scan) != exact_keys:
        return ['device fields']
    if (scan.get('status') != 'failed' or scan.get('authorizes_cleanup') is not False or
            scan.get('authorizes_launch') is not False):
        errors.append('device status')
    if scan.get('reservation_before_hex') != expected or \
            scan.get('reservation_after_hex') != expected:
        errors.append('pending descriptor')
    if scan.get('globals_before') != scan.get('globals_after'):
        errors.append('global stability')
    values = scan.get('globals_after', {})
    required = set(INSPECTOR.GLOBAL_OFFSETS)
    if set(values) != required or any(type(values.get(key)) is not int for key in required):
        errors.append('global fields')
        return errors
    if any(value == 0xffffffff for value in values.values()):
        errors.append('global accessibility')
    if values['cp_stat'] != 0 or values['cpc_busy'] != 0:
        errors.append('CP idle')
    if values['me_cntl'] != 0 or values['mec_cntl'] != 0:
        errors.append('CP initial controls')
    if values['rb0_active'] & 1 or values['rb1_active'] & 1 or \
            values['rb_doorbell_control'] & 0xc0000000:
        errors.append('graphics idle')
    if values['pq_wptr_poll_cntl'] & RECOVERY.CP_PQ_WPTR_POLL_ENABLE_MASK:
        errors.append('pointer polling')
    if values['sdma0_cntl'] & RECOVERY.SDMA_AUTO_CTXSW_ENABLE_MASK or \
            values['sdma0_gfx_rb_cntl'] & RECOVERY.SDMA_RB_ENABLE_MASK or \
            values['sdma0_gfx_ib_cntl'] & RECOVERY.SDMA_IB_ENABLE_MASK:
        errors.append('SDMA disabled inputs')
    if values['sdma0_f32_cntl'] != 0:
        errors.append('SDMA exact unhalted state')
    compute = scan.get('compute_passes')
    if (not isinstance(compute, list) or len(compute) != 2 or
            any(not isinstance(rows, list) or len(rows) != 64 for rows in compute) or
            compute[0] != compute[1]):
        errors.append('compute passes')
    else:
        for row in compute[0]:
            if row.get('active') != 0 or row.get('pq_doorbell_control') != 0:
                errors.append('compute queue state')
                break
    graphics = scan.get('graphics_passes')
    if (not isinstance(graphics, list) or len(graphics) != 2 or
            graphics[0] != graphics[1] or
            [row.get('selector') for row in graphics[0]] != [0, 1]):
        errors.append('graphics passes')
    else:
        for row in graphics[0]:
            if (row.get('rb0_active') != 0 or row.get('rb1_active') != 0 or
                    row.get('doorbell_control') != 0):
                errors.append('graphics queue state')
                break
    final = scan.get('final_default', {})
    writes = scan.get('selector_writes')
    if (not isinstance(writes, list) or len(writes) != 135 or
            any(row.get('attempted') is not True or row.get('completed') is not True
                for row in writes) or final.get('value') != 0 or
            final.get('attempted') is not True or final.get('completed') is not True):
        errors.append('selector trace')
    return sorted(set(errors))


def validate_pinned_inspection(raw):
    errors = []
    if not isinstance(raw, bytes) or _sha256(raw) != INSPECTION_SHA256:
        errors.append('inspection hash')
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return sorted(set(errors + ['inspection JSON']))
    exact_keys = {'schema', 'kind', 'status', 'authorizes_cleanup',
                  'authorizes_launch', 'boot_id', 'run_id', 'build_id',
                  'preflight', 'device', 'postflight', 'device_error',
                  'error', 'created_epoch'}
    if set(value) != exact_keys:
        errors.append('receipt fields')
    if (value.get('schema') != 1 or value.get('kind') != 'stopped-gpu-noqueue-inspection' or
            value.get('status') != 'failed' or value.get('authorizes_cleanup') is not False or
            value.get('authorizes_launch') is not False):
        errors.append('status')
    if (value.get('boot_id'), value.get('run_id'), value.get('build_id')) != (
            BOOT_ID, RUN_ID, BUILD_ID):
        errors.append('identity')
    if (value.get('device_error') != 'SDMA0 is not halted' or
            value.get('error') != 'device inspection: SDMA0 is not halted'):
        errors.append('failure boundary')
    errors += _unhalted_scan_errors(value.get('device'))
    pre = value.get('preflight')
    post = value.get('postflight')
    if not isinstance(pre, dict) or INSPECTOR.validate_pre_vfio(pre):
        errors.append('inspection preflight')
    if (not isinstance(post, dict) or INSPECTOR.validate_pre_vfio(post) or
            INSPECTOR._stable_pre_post_errors(pre, post)):
        errors.append('inspection postflight')
    return sorted(set(errors))


class TransactionTransport:
    """Record and enforce the complete startup-noqueue transport allowlist."""
    def __init__(self, transport):
        self._transport = transport
        self.writes = []
        self._last_reads = {}
        self._psp_commands = []
        self._vram_consumed = False

    def read32(self, offset):
        allowed = (INSPECTOR.OBSERVATION_OFFSETS | set(SDMA_AUX_OFFSETS.values()) |
                   {RECOVERY.NBIO_CONFIG_MEMSIZE_OFFSET, RECOVERY.C2PMSG_64_OFFSET})
        if offset not in allowed:
            raise StartupRecoveryError(f'BAR5 read is forbidden at {offset:#x}')
        value = self._transport.read32(offset)
        self._last_reads[offset] = value
        return value

    def _allowed_write(self, offset, value):
        prior = self._last_reads.get(offset)
        if offset == RECOVERY.GRBM_GFX_CNTL_OFFSET:
            return value in INSPECTOR.VALID_SELECTORS
        if offset == RECOVERY.CP_PQ_WPTR_POLL_CNTL_OFFSET:
            return prior is not None and value == prior & ~RECOVERY.CP_PQ_WPTR_POLL_ENABLE_MASK
        if offset == RECOVERY.CP_ME_CNTL_OFFSET:
            return prior is not None and value == prior | RECOVERY.CP_ME_HALT_MASK
        if offset == RECOVERY.CP_MEC_CNTL_OFFSET:
            return prior is not None and value == prior | RECOVERY.CP_MEC_HALT_MASK
        if offset == RECOVERY.SDMA0_F32_CNTL_OFFSET:
            return prior is not None and value == prior | RECOVERY.SDMA_HALT_MASK
        if offset == RECOVERY.C2PMSG_64_OFFSET:
            expected = (RECOVERY.DESTROY_RINGS, RECOVERY.DESTROY_GPCOM_RING)
            return len(self._psp_commands) < 2 and value == expected[len(self._psp_commands)]
        return False

    def write32(self, offset, value):
        if not self._allowed_write(offset, value):
            raise StartupRecoveryError(f'BAR5 write is forbidden at {offset:#x}')
        row = {'sequence': len(self.writes), 'region': 'BAR5', 'operation': 'write32',
               'offset': offset, 'value': value, 'attempted': True, 'completed': False}
        self.writes.append(row)
        try:
            self._transport.write32(offset, value)
        except BaseException as error:
            row['error'] = type(error).__name__ + ': ' + str(error)
            raise
        row['completed'] = True
        if offset == RECOVERY.C2PMSG_64_OFFSET:
            self._psp_commands.append(value)

    def read_vram32(self, offset):
        start = RECOVERY.HOST_KIQ_RESERVATION_OFFSET
        end = start + RECOVERY.HOST_KIQ_RESERVATION_SIZE
        if type(offset) is not int or offset & 3 or not start <= offset < end:
            raise StartupRecoveryError(f'BAR0 read is forbidden at {offset!r}')
        return self._transport.read_vram32(offset)

    def consume_pending(self):
        expected = RECOVERY.host_kiq_reservation_descriptor(
            RUN_ID, RECOVERY.HOST_KIQ_RESERVATION_PENDING)
        before = _read_descriptor(self)
        if before != expected:
            raise StartupRecoveryError('PENDING descriptor changed before consume')
        if self._vram_consumed:
            raise StartupRecoveryError('PENDING descriptor consume already attempted')
        row = {'sequence': len(self.writes), 'region': 'BAR0',
               'operation': 'consume_pending',
               'offset': RECOVERY.HOST_KIQ_RESERVATION_OFFSET,
               'size': len(expected), 'before_sha256': _sha256(before),
               'attempted': True, 'completed': False}
        self.writes.append(row)
        self._vram_consumed = True
        try:
            self._transport.write_vram(RECOVERY.HOST_KIQ_RESERVATION_OFFSET,
                                       b'\0' * len(expected))
        except BaseException as error:
            row['error'] = type(error).__name__ + ': ' + str(error)
            raise
        row['completed'] = True
        flush = {'sequence': len(self.writes), 'region': 'BAR5',
                 'operation': 'flush_hdp', 'attempted': True, 'completed': False}
        self.writes.append(flush)
        try:
            result = self._transport.flush_hdp()
        except BaseException as error:
            flush['error'] = type(error).__name__ + ': ' + str(error)
            raise
        flush['result'] = result
        flush['completed'] = True
        after = _read_descriptor(self)
        if after != b'\0' * len(expected):
            raise StartupRecoveryError('PENDING descriptor consume did not persist')
        return {'before_hex': before.hex(), 'after_hex': after.hex(),
                'hdp_flush': result}

    def metadata(self):
        return self._transport.metadata()

    def ring_doorbell64(self, index, value):
        raise StartupRecoveryError('BAR2 access is forbidden')


def _capture_unhalted_scan(mmio):
    try:
        INSPECTOR.inspect_device(mmio, RUN_ID)
    except INSPECTOR.InspectionError as error:
        if str(error) != 'SDMA0 is not halted':
            raise StartupRecoveryError('fresh scan failed: ' + str(error), error.evidence)
        scan = error.evidence
    else:
        raise StartupRecoveryError('fresh scan unexpectedly passed instead of exact F32=0')
    errors = _unhalted_scan_errors(scan)
    if errors:
        raise StartupRecoveryError('fresh scan invalid: ' + ','.join(errors), scan)
    return scan


def _validate_aux_snapshot(row, prefix='auxiliary'):
    if set(row) != set(SDMA_AUX_OFFSETS) or any(type(value) is not int
                                                for value in row.values()):
        raise StartupRecoveryError(prefix + ' SDMA fields invalid')
    if any(value == 0xffffffff for value in row.values()):
        raise StartupRecoveryError(prefix + ' SDMA observation is inaccessible')
    if not row['status'] & SDMA_STATUS_IDLE_MASK:
        raise StartupRecoveryError('SDMA0 status is not idle')
    if any(row[name] & 1 for name in row if name != 'status'):
        raise StartupRecoveryError('PAGE/RLC SDMA ring or IB is enabled')


def _aux_sdma_passes(mmio, passes=None):
    passes = [] if passes is None else passes
    for _ in range(2):
        row = {}
        passes.append(row)
        for name, offset in SDMA_AUX_OFFSETS.items():
            row[name] = mmio.read32(offset)
    if passes[0] != passes[1]:
        raise StartupRecoveryError('auxiliary SDMA observations changed')
    for row in passes:
        _validate_aux_snapshot(row)
    return passes


def _scan_hqds(mmio, evidence=None):
    scan = evidence if evidence is not None else {
        'rows': [], 'final_default': {'attempted': False, 'completed': False}}
    rows = scan['rows']
    primary = None
    try:
        for me in (1, 2):
            for pipe in range(4):
                for queue in range(8):
                    selector = RECOVERY.queue_selector(me, pipe, queue)
                    mmio.write32(RECOVERY.GRBM_GFX_CNTL_OFFSET, selector)
                    active = mmio.read32(RECOVERY.CP_HQD_ACTIVE_OFFSET)
                    doorbell = mmio.read32(RECOVERY.CP_HQD_PQ_DOORBELL_OFFSET)
                    row = {'me': me, 'pipe': pipe, 'queue': queue,
                           'selector': selector, 'active': active,
                           'pq_doorbell_control': doorbell}
                    rows.append(row)
                    if active == 0xffffffff or doorbell == 0xffffffff or active & 1:
                        raise StartupRecoveryError('HQD rescan is inaccessible or active')
                    if doorbell:
                        raise StartupRecoveryError(
                            'HQD doorbell changed from pinned zero state')
    except BaseException as error:
        primary = error
    finally:
        try:
            mmio.write32(RECOVERY.GRBM_GFX_CNTL_OFFSET, 0)
            final = {'attempted': True, 'completed': True, 'value': 0}
        except BaseException as error:
            final = {'attempted': True, 'completed': False, 'value': 0,
                     'error': type(error).__name__ + ': ' + str(error)}
        scan['final_default'] = final
    if primary is not None:
        if not final['completed']:
            scan['primary_error'] = type(primary).__name__ + ': ' + str(primary)
            raise StartupRecoveryError(
                str(primary) + '; HQD rescan final default failed', scan) from primary
        raise StartupRecoveryError(str(primary), scan) from primary
    if not final['completed']:
        raise StartupRecoveryError('HQD rescan final default failed',
                                   scan)
    return scan


def _final_scan_errors(scan, aux):
    errors = []
    values = scan.get('globals_after', {}) if isinstance(scan, dict) else {}
    if scan.get('status') != 'observed-idle':
        errors.append('strict scan')
    if values.get('me_cntl', 0) & RECOVERY.CP_ME_HALT_MASK != RECOVERY.CP_ME_HALT_MASK:
        errors.append('ME halt')
    if values.get('mec_cntl', 0) & RECOVERY.CP_MEC_HALT_MASK != RECOVERY.CP_MEC_HALT_MASK:
        errors.append('MEC halt')
    if values.get('pq_wptr_poll_cntl', 0) & RECOVERY.CP_PQ_WPTR_POLL_ENABLE_MASK:
        errors.append('pointer polling')
    if values.get('sdma0_f32_cntl', 0) & RECOVERY.SDMA_HALT_MASK != RECOVERY.SDMA_HALT_MASK:
        errors.append('SDMA halt')
    try:
        _validate_aux_value(aux)
    except StartupRecoveryError as error:
        errors.append(str(error))
    return errors


def _validate_aux_value(passes):
    if not isinstance(passes, list) or len(passes) != 2 or passes[0] != passes[1]:
        raise StartupRecoveryError('final auxiliary SDMA observations changed')
    for row in passes:
        _validate_aux_snapshot(row, 'final auxiliary')


def _sdma_gfx_inputs(mmio, row=None):
    row = {} if row is None else row
    gates = {
        'auto_ctxsw': RECOVERY.SDMA_AUTO_CTXSW_ENABLE_MASK,
        'gfx_rb': RECOVERY.SDMA_RB_ENABLE_MASK,
        'gfx_ib': RECOVERY.SDMA_IB_ENABLE_MASK,
    }
    offsets = {'auto_ctxsw': RECOVERY.SDMA0_CNTL_OFFSET,
               'gfx_rb': RECOVERY.SDMA0_GFX_RB_CNTL_OFFSET,
               'gfx_ib': RECOVERY.SDMA0_GFX_IB_CNTL_OFFSET}
    for name, offset in offsets.items():
        row[name] = mmio.read32(offset)
        if (type(row[name]) is not int or row[name] == 0xffffffff or
                row[name] & gates[name]):
            raise StartupRecoveryError(
                'SDMA0 GFX/context input is enabled or inaccessible')
    return row


def _immediate_sdma_inputs(mmio, row=None):
    row = {} if row is None else row
    for name, offset in SDMA_AUX_OFFSETS.items():
        if name != 'status':
            row[name] = mmio.read32(offset)
    gfx_offsets = {
        'auto_ctxsw': RECOVERY.SDMA0_CNTL_OFFSET,
        'gfx_rb': RECOVERY.SDMA0_GFX_RB_CNTL_OFFSET,
        'gfx_ib': RECOVERY.SDMA0_GFX_IB_CNTL_OFFSET,
    }
    gfx_gates = {
        'auto_ctxsw': RECOVERY.SDMA_AUTO_CTXSW_ENABLE_MASK,
        'gfx_rb': RECOVERY.SDMA_RB_ENABLE_MASK,
        'gfx_ib': RECOVERY.SDMA_IB_ENABLE_MASK,
    }
    for name, offset in gfx_offsets.items():
        row[name] = mmio.read32(offset)
        if (type(row[name]) is not int or row[name] == 0xffffffff or
                row[name] & gfx_gates[name]):
            raise StartupRecoveryError(
                'SDMA0 GFX/context input is enabled or inaccessible')
    row['status'] = mmio.read32(SDMA0_STATUS_REG_OFFSET)
    _validate_aux_snapshot({name: row[name] for name in SDMA_AUX_OFFSETS},
                           'immediate pre-halt')
    return row


def _psp_command(mmio, command, label, commands, sleep, polls):
    row = {'label': label, 'command': command, 'confirmed': False}
    commands.append(row)
    row['before'] = mmio.read32(RECOVERY.C2PMSG_64_OFFSET)
    mmio.write32(RECOVERY.C2PMSG_64_OFFSET, command)
    for attempt in range(polls):
        response = mmio.read32(RECOVERY.C2PMSG_64_OFFSET)
        row.update(response=response, polls=attempt)
        if ((response & RECOVERY.READY_MASK) == RECOVERY.READY_FLAG and
                ((response >> 16) & 0x7fff) == (command >> 16)):
            row['confirmed'] = True
            return row
        sleep(0.001)
    raise StartupRecoveryError(
        f'{label} did not complete: 0x{row["before"]:08x} -> 0x{row.get("response", 0):08x}')


def execute_transaction(transport, pinned_inspection, sleep, polls):
    """Execute with an explicitly supplied transport; never opens VFIO itself."""
    mmio = TransactionTransport(transport)
    evidence = {'status': 'failed', 'authorizes_launch': False,
                'writes': mmio.writes, 'commands': []}
    try:
        pre_scan = _capture_unhalted_scan(mmio)
        evidence['pre_scan'] = pre_scan
        if pre_scan != pinned_inspection.get('device'):
            raise StartupRecoveryError('fresh scan differs from pinned inspection', evidence)
        evidence['aux_sdma_before'] = []
        _aux_sdma_passes(mmio, evidence['aux_sdma_before'])

        values = pre_scan['globals_after']
        if values['pq_wptr_poll_cntl'] & RECOVERY.CP_PQ_WPTR_POLL_ENABLE_MASK:
            mmio.read32(RECOVERY.CP_PQ_WPTR_POLL_CNTL_OFFSET)
            mmio.write32(RECOVERY.CP_PQ_WPTR_POLL_CNTL_OFFSET,
                         values['pq_wptr_poll_cntl'] &
                         ~RECOVERY.CP_PQ_WPTR_POLL_ENABLE_MASK)

        me = mmio.read32(RECOVERY.CP_ME_CNTL_OFFSET)
        if me & RECOVERY.CP_ME_HALT_MASK != RECOVERY.CP_ME_HALT_MASK:
            mmio.write32(RECOVERY.CP_ME_CNTL_OFFSET, me | RECOVERY.CP_ME_HALT_MASK)
        mec = mmio.read32(RECOVERY.CP_MEC_CNTL_OFFSET)
        if mec & RECOVERY.CP_MEC_HALT_MASK != RECOVERY.CP_MEC_HALT_MASK:
            mmio.write32(RECOVERY.CP_MEC_CNTL_OFFSET, mec | RECOVERY.CP_MEC_HALT_MASK)
        if (mmio.read32(RECOVERY.CP_ME_CNTL_OFFSET) & RECOVERY.CP_ME_HALT_MASK !=
                RECOVERY.CP_ME_HALT_MASK or
                mmio.read32(RECOVERY.CP_MEC_CNTL_OFFSET) & RECOVERY.CP_MEC_HALT_MASK !=
                RECOVERY.CP_MEC_HALT_MASK or
                mmio.read32(RECOVERY.CP_STAT_OFFSET) != 0 or
                mmio.read32(RECOVERY.CP_CPC_BUSY_STAT_OFFSET) != 0):
            raise StartupRecoveryError('command processors did not halt cleanly', evidence)

        evidence['hqd_after_cp_halt'] = {
            'rows': [], 'final_default': {'attempted': False, 'completed': False}}
        _scan_hqds(mmio, evidence['hqd_after_cp_halt'])

        evidence['aux_sdma_pre_halt'] = []
        _aux_sdma_passes(mmio, evidence['aux_sdma_pre_halt'])
        immediate = {}
        evidence['sdma_inputs_immediate_before_halt'] = immediate
        _immediate_sdma_inputs(mmio, immediate)
        evidence['sdma_status_before_halt'] = immediate['status']
        f32 = mmio.read32(RECOVERY.SDMA0_F32_CNTL_OFFSET)
        evidence['sdma_f32_before_halt'] = f32
        if f32 != 0:
            raise StartupRecoveryError('SDMA0 F32 changed from exact unhalted state', evidence)
        mmio.write32(RECOVERY.SDMA0_F32_CNTL_OFFSET, f32 | RECOVERY.SDMA_HALT_MASK)
        evidence['sdma_f32_after_halt'] = mmio.read32(
            RECOVERY.SDMA0_F32_CNTL_OFFSET)
        if (evidence['sdma_f32_after_halt'] == 0xffffffff or
                evidence['sdma_f32_after_halt'] & RECOVERY.SDMA_HALT_MASK == 0):
            raise StartupRecoveryError('SDMA0 halt did not persist', evidence)
        evidence['sdma_status_after_halt'] = mmio.read32(SDMA0_STATUS_REG_OFFSET)
        if (evidence['sdma_status_after_halt'] == 0xffffffff or
                not evidence['sdma_status_after_halt'] & SDMA_STATUS_IDLE_MASK):
            raise StartupRecoveryError('SDMA0 status is not idle after halt', evidence)
        evidence['sdma_gfx_inputs_after_halt'] = {}
        _sdma_gfx_inputs(mmio, evidence['sdma_gfx_inputs_after_halt'])

        _psp_command(mmio, RECOVERY.DESTROY_RINGS, 'destroy all rings',
                     evidence['commands'], sleep, polls)
        _psp_command(mmio, RECOVERY.DESTROY_GPCOM_RING, 'destroy GPCOM ring',
                     evidence['commands'], sleep, polls)

        try:
            final_scan = INSPECTOR.inspect_device(mmio, RUN_ID)
        except INSPECTOR.InspectionError as error:
            evidence['final_scan'] = error.evidence
            raise StartupRecoveryError('final scan failed: ' + str(error), evidence) from error
        evidence['final_scan'] = final_scan
        evidence['aux_sdma_after'] = []
        _aux_sdma_passes(mmio, evidence['aux_sdma_after'])
        final_errors = _final_scan_errors(final_scan, evidence['aux_sdma_after'])
        if final_errors:
            raise StartupRecoveryError('final scan failed: ' + ','.join(final_errors), evidence)
        evidence['reservation'] = mmio.consume_pending()
        evidence['bar5'] = mmio.metadata()
        evidence['status'] = 'recovered'
        return evidence
    except StartupRecoveryError as error:
        if error.evidence is evidence:
            raise
        raise StartupRecoveryError(str(error), evidence) from error
    except BaseException as error:
        raise StartupRecoveryError(type(error).__name__ + ': ' + str(error), evidence) from error


def collect_preflight(vm, evidence_dir, inspection_path, cursor=None):
    raw = inspection_path.read_bytes()
    proof = INSPECTOR.collect_proof(vm, evidence_dir, cursor)
    archive_sha256, archive_files = archive_digest(evidence_dir)
    origin = Path(vm) / 'run/metal-007-174-prelaunch-continuation'
    origin_sha256, origin_files = archive_digest(origin)
    return {'inspection': json.loads(raw), 'inspection_sha256': _sha256(raw),
            'inspection_bytes': raw, 'host_proof': proof,
            'journal_cursor': proof['journal_cursor'],
            'archive_sha256': archive_sha256, 'archive_files': archive_files,
            'origin_archive_sha256': origin_sha256,
            'origin_archive_files': origin_files,
            'source_hashes': source_hashes()}


def _preflight_errors(value):
    errors = validate_pinned_inspection(value.get('inspection_bytes'))
    if value.get('inspection_sha256') != INSPECTION_SHA256:
        errors.append('inspection hash')
    if value.get('inspection') != json.loads(value.get('inspection_bytes', b'null')):
        errors.append('inspection value')
    archive_files = value.get('archive_files')
    origin_files = value.get('origin_archive_files')
    if (value.get('archive_sha256') != ARCHIVE_SHA256 or
            value.get('origin_archive_sha256') != ARCHIVE_SHA256 or
            not isinstance(archive_files, dict) or
            not isinstance(origin_files, dict) or archive_files != origin_files or
            set(archive_files) != set(ARCHIVE_FILES) or
            any(not re.fullmatch(r'[0-9a-f]{64}', str(digest))
                for digest in archive_files.values()) or
            _archive_map_digest(archive_files) != ARCHIVE_SHA256):
        errors.append('archive digest')
    if value.get('source_hashes') != source_hashes():
        errors.append('cleanup source hashes')
    proof = value.get('host_proof')
    if not isinstance(proof, dict) or INSPECTOR.validate_pre_vfio(proof):
        errors.append('current host proof')
    return sorted(set(errors))


def _attempt_record(preflight):
    manifest = preflight['host_proof']['manifest']
    return {'schema': 1, 'kind': 'startup-noqueue-attempt',
            'boot_id': BOOT_ID, 'prior_run_id': RUN_ID, 'build_id': BUILD_ID,
            'attempt_id': uuid.uuid4().hex, 'recovery_id': uuid.uuid4().hex,
            'inspection_sha256': INSPECTION_SHA256,
            'ledger_sha256': LEDGER_SHA256, 'archive_sha256': ARCHIVE_SHA256,
            'guest_source_commit': manifest['source_commit'],
            'guest_source_sha256': manifest['source_sha256'],
            'source_hashes': preflight['source_hashes'],
            'created_epoch': time.time()}


def _json_safe_preflight(value):
    return {key: item for key, item in value.items() if key != 'inspection_bytes'}


def _json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()


def _valid_host_proof(proof):
    return (isinstance(proof, dict) and not INSPECTOR.validate_pre_vfio(proof) and
            proof.get('host', {}).get('pci_command') == 3 and
            proof.get('host', {}).get('reset_methods') == [])


def _validate_strict_scan(scan, expected_descriptor, expected_status):
    exact_keys = {'status', 'authorizes_cleanup', 'authorizes_launch',
                  'selector_writes', 'compute_passes', 'graphics_passes',
                  'final_default', 'reservation_before_hex',
                  'reservation_after_hex', 'globals_before', 'globals_after',
                  'vfio_region'}
    if (not isinstance(scan, dict) or set(scan) != exact_keys or
            scan.get('status') != expected_status or
            scan.get('authorizes_cleanup') is not False or
            scan.get('authorizes_launch') is not False or
            scan.get('reservation_before_hex') != expected_descriptor.hex() or
            scan.get('reservation_after_hex') != expected_descriptor.hex()):
        raise StartupRecoveryError('strict scan fields')
    selectors = [RECOVERY.queue_selector(me, pipe, queue)
                 for me in (1, 2) for pipe in range(4) for queue in range(8)]
    compute = scan['compute_passes']
    if (not isinstance(compute, list) or len(compute) != 2 or
            any(not isinstance(rows, list) or len(rows) != 64 for rows in compute) or
            compute[0] != compute[1]):
        raise StartupRecoveryError('strict compute passes')
    for rows in compute:
        for index, row in enumerate(rows):
            me = 1 + index // 32
            pipe = index % 32 // 8
            queue = index % 8
            expected = {'me': me, 'pipe': pipe, 'queue': queue,
                        'selector': selectors[index], 'active': 0,
                        'pq_doorbell_control': 0}
            if row != expected:
                raise StartupRecoveryError('strict compute row')
    graphics = scan['graphics_passes']
    if (not isinstance(graphics, list) or len(graphics) != 2 or
            graphics[0] != graphics[1] or
            any(not isinstance(rows, list) or len(rows) != 2 for rows in graphics)):
        raise StartupRecoveryError('strict graphics passes')
    for rows in graphics:
        for pipe, row in enumerate(rows):
            if row != {'selector': pipe, 'intended_pipe': pipe,
                       'rb0_active': 0, 'rb1_active': 0,
                       'doorbell_control': 0}:
                raise StartupRecoveryError('strict graphics row')
    globals_before, globals_after = scan['globals_before'], scan['globals_after']
    if (not isinstance(globals_before, dict) or
            set(globals_before) != set(INSPECTOR.GLOBAL_OFFSETS) or
            globals_before != globals_after or
            any(type(value) is not int or value == 0xffffffff
                for value in globals_before.values())):
        raise StartupRecoveryError('strict globals')
    expected_selector_values = [0]
    for _ in range(2):
        expected_selector_values += selectors + [0, 1]
    expected_selector_values += [0, 0]
    writes = scan['selector_writes']
    if (not isinstance(writes, list) or len(writes) != 135 or
            [row.get('sequence') for row in writes] != list(range(135)) or
            [row.get('value') for row in writes] != expected_selector_values or
            any(set(row) != {'sequence', 'phase', 'value', 'attempted', 'completed'} or
                row['attempted'] is not True or row['completed'] is not True or
                not isinstance(row['phase'], str) for row in writes) or
            scan['final_default'] != writes[-1]):
        raise StartupRecoveryError('strict selector trace')
    try:
        INSPECTOR._validate_device_evidence(scan, expected_descriptor)
    except BaseException as error:
        raise StartupRecoveryError('strict scan state') from error


def _validate_transaction(value):
    exact_keys = {
        'status', 'authorizes_launch', 'writes', 'commands', 'pre_scan',
        'aux_sdma_before', 'hqd_after_cp_halt', 'aux_sdma_pre_halt',
        'sdma_inputs_immediate_before_halt', 'sdma_status_before_halt',
        'sdma_gfx_inputs_after_halt',
        'sdma_f32_before_halt', 'sdma_f32_after_halt',
        'sdma_status_after_halt', 'final_scan', 'aux_sdma_after',
        'reservation', 'bar5',
    }
    if not isinstance(value, dict) or set(value) != exact_keys:
        raise StartupRecoveryError('transaction fields')
    if value['status'] != 'recovered' or value['authorizes_launch'] is not False:
        raise StartupRecoveryError('transaction status')
    if _sha256(json.dumps(value['pre_scan'], sort_keys=True,
                          separators=(',', ':')).encode()) != PINNED_DEVICE_SHA256:
        raise StartupRecoveryError('transaction pre-scan')
    if _unhalted_scan_errors(value['pre_scan']):
        raise StartupRecoveryError('transaction pre-scan state')
    for key in ('aux_sdma_before', 'aux_sdma_pre_halt', 'aux_sdma_after'):
        _validate_aux_value(value[key])
    immediate = value['sdma_inputs_immediate_before_halt']
    expected_gfx_input_keys = {'auto_ctxsw', 'gfx_rb', 'gfx_ib'}
    if (not isinstance(immediate, dict) or
            set(immediate) != set(SDMA_AUX_OFFSETS) | expected_gfx_input_keys):
        raise StartupRecoveryError('transaction immediate SDMA input fields')
    _validate_aux_snapshot({name: immediate[name] for name in SDMA_AUX_OFFSETS},
                           'receipt immediate pre-halt')
    for row in ({name: immediate[name] for name in expected_gfx_input_keys},
                value['sdma_gfx_inputs_after_halt']):
        if not isinstance(row, dict) or set(row) != expected_gfx_input_keys:
            raise StartupRecoveryError('transaction SDMA GFX input fields')
        gates = {'auto_ctxsw': RECOVERY.SDMA_AUTO_CTXSW_ENABLE_MASK,
                 'gfx_rb': RECOVERY.SDMA_RB_ENABLE_MASK,
                 'gfx_ib': RECOVERY.SDMA_IB_ENABLE_MASK}
        if any(type(row[name]) is not int or row[name] == 0xffffffff or
               row[name] & mask for name, mask in gates.items()):
            raise StartupRecoveryError('transaction SDMA GFX inputs')
    if (type(value['sdma_status_before_halt']) is not int or
            type(value['sdma_status_after_halt']) is not int or
            value['sdma_status_before_halt'] == 0xffffffff or
            value['sdma_status_after_halt'] == 0xffffffff or
            value['sdma_status_before_halt'] != immediate['status'] or
            not value['sdma_status_before_halt'] & SDMA_STATUS_IDLE_MASK or
            not value['sdma_status_after_halt'] & SDMA_STATUS_IDLE_MASK):
        raise StartupRecoveryError('transaction SDMA status')
    if (type(value['sdma_f32_before_halt']) is not int or
            value['sdma_f32_before_halt'] != 0 or
            type(value['sdma_f32_after_halt']) is not int or
            value['sdma_f32_after_halt'] == 0xffffffff or
            value['sdma_f32_after_halt'] & RECOVERY.SDMA_HALT_MASK !=
            RECOVERY.SDMA_HALT_MASK):
        raise StartupRecoveryError('transaction SDMA halt readback')

    hqd = value['hqd_after_cp_halt']
    expected_selectors = [RECOVERY.queue_selector(me, pipe, queue)
                          for me in (1, 2) for pipe in range(4)
                          for queue in range(8)]
    if (not isinstance(hqd, dict) or set(hqd) != {'rows', 'final_default'} or
            not isinstance(hqd['rows'], list) or len(hqd['rows']) != 64 or
            [row.get('selector') for row in hqd['rows']] != expected_selectors or
            hqd['final_default'] != {'attempted': True, 'completed': True, 'value': 0}):
        raise StartupRecoveryError('transaction HQD scan')
    for index, row in enumerate(hqd['rows']):
        expected_row = {'me': 1 + index // 32, 'pipe': index % 32 // 8,
                        'queue': index % 8, 'selector': expected_selectors[index],
                        'active': 0, 'pq_doorbell_control': 0}
        if row != expected_row:
            raise StartupRecoveryError('transaction HQD row')

    final_scan = value['final_scan']
    pending = RECOVERY.host_kiq_reservation_descriptor(
        RUN_ID, RECOVERY.HOST_KIQ_RESERVATION_PENDING)
    _validate_strict_scan(final_scan, pending, 'observed-idle')
    if _final_scan_errors(final_scan, value['aux_sdma_after']):
        raise StartupRecoveryError('transaction final state')

    commands = value['commands']
    expected_commands = (RECOVERY.DESTROY_RINGS, RECOVERY.DESTROY_GPCOM_RING)
    if (not isinstance(commands, list) or len(commands) != 2 or
            [row.get('command') for row in commands] != list(expected_commands) or
            [row.get('label') for row in commands] !=
            ['destroy all rings', 'destroy GPCOM ring'] or
            any(set(row) != {'label', 'command', 'confirmed', 'before', 'response', 'polls'} or
                row.get('confirmed') is not True or
                type(row.get('before')) is not int or
                type(row.get('response')) is not int or
                type(row.get('polls')) is not int or row['polls'] < 0 or
                (row['response'] & RECOVERY.READY_MASK) != RECOVERY.READY_FLAG or
                ((row['response'] >> 16) & 0x7fff) != (row['command'] >> 16)
                for row in commands)):
        raise StartupRecoveryError('transaction PSP commands')

    expected_pending = pending.hex()
    reservation = value['reservation']
    if (not isinstance(reservation, dict) or
            set(reservation) != {'before_hex', 'after_hex', 'hdp_flush'} or
            reservation.get('before_hex') != expected_pending or
            reservation.get('after_hex') != '00' * RECOVERY.HOST_KIQ_RESERVATION_SIZE or
            not isinstance(reservation.get('hdp_flush'), dict) or
            set(reservation['hdp_flush']) != {'remap', 'posted_read'} or
            reservation['hdp_flush'].get('remap') not in RECOVERY.HDP_MEM_FLUSH_TARGETS or
            reservation['hdp_flush'].get('posted_read') !=
            RECOVERY.EXPECTED_CONFIG_MEMSIZE):
        raise StartupRecoveryError('transaction reservation')
    if value['bar5'] != value['pre_scan']['vfio_region']:
        raise StartupRecoveryError('transaction BAR metadata')
    if final_scan['vfio_region'] != value['bar5']:
        raise StartupRecoveryError('transaction final BAR metadata')

    writes = value['writes']
    if (not isinstance(writes, list) or
            [row.get('sequence') for row in writes] != list(range(len(writes))) or
            any(row.get('attempted') is not True or row.get('completed') is not True
                for row in writes)):
        raise StartupRecoveryError('transaction write trace')
    write32_keys = {'sequence', 'region', 'operation', 'offset', 'value',
                    'attempted', 'completed'}
    if any(row.get('operation') == 'write32' and
           (set(row) != write32_keys or row.get('region') != 'BAR5') for row in writes):
        raise StartupRecoveryError('transaction write32 fields')
    def selector_tuples(values):
        return [('write32', 'BAR5', RECOVERY.GRBM_GFX_CNTL_OFFSET, item)
                for item in values]
    pre_values = [row['value'] for row in value['pre_scan']['selector_writes']]
    final_values = [row['value'] for row in final_scan['selector_writes']]
    expected_trace = selector_tuples(pre_values) + [
        ('write32', 'BAR5', RECOVERY.CP_ME_CNTL_OFFSET, RECOVERY.CP_ME_HALT_MASK),
        ('write32', 'BAR5', RECOVERY.CP_MEC_CNTL_OFFSET, RECOVERY.CP_MEC_HALT_MASK),
    ] + selector_tuples(expected_selectors + [0]) + [
        ('write32', 'BAR5', RECOVERY.SDMA0_F32_CNTL_OFFSET, RECOVERY.SDMA_HALT_MASK),
        ('write32', 'BAR5', RECOVERY.C2PMSG_64_OFFSET, RECOVERY.DESTROY_RINGS),
        ('write32', 'BAR5', RECOVERY.C2PMSG_64_OFFSET, RECOVERY.DESTROY_GPCOM_RING),
    ] + selector_tuples(final_values) + [
        ('consume_pending', 'BAR0', RECOVERY.HOST_KIQ_RESERVATION_OFFSET, None),
        ('flush_hdp', 'BAR5', None, None),
    ]
    actual_trace = [(row.get('operation'), row.get('region'), row.get('offset'),
                     row.get('value')) for row in writes]
    if actual_trace != expected_trace:
        raise StartupRecoveryError('transaction ordered trace')
    consume, flush = writes[-2:]
    if (set(consume) != {'sequence', 'region', 'operation', 'offset', 'size',
                         'before_sha256', 'attempted', 'completed'} or
            consume['size'] != RECOVERY.HOST_KIQ_RESERVATION_SIZE or
            consume['before_sha256'] != _sha256(pending) or
            set(flush) != {'sequence', 'region', 'operation', 'attempted',
                           'completed', 'result'} or
            flush['result'] != reservation['hdp_flush']):
        raise StartupRecoveryError('transaction consume trace')


def build_receipt(transaction, attempt, attempt_sha256, before, after):
    _validate_transaction(transaction)
    if not _valid_host_proof(before) or not _valid_host_proof(after) or \
            INSPECTOR._stable_pre_post_errors(before, after):
        raise StartupRecoveryError('host proof is not stable')
    host_before, host_after = before['host'], after['host']
    return {
        'schema': 4, 'kind': 'startup-noqueue-recovery', 'status': 'recovered',
        'authorizes_launch': True, 'boot_id': BOOT_ID, 'prior_run_id': RUN_ID,
        'build_id': BUILD_ID, 'device': RECOVERY.DEVICE,
        'iommu_group': RECOVERY.GROUP, 'driver': 'vfio-pci',
        'recovery_id': attempt['recovery_id'], 'attempt_id': attempt['attempt_id'],
        'inspection_sha256': INSPECTION_SHA256, 'ledger_sha256': LEDGER_SHA256,
        'archive_sha256': ARCHIVE_SHA256, 'attempt_sha256': attempt_sha256,
        'guest_source_commit': attempt['guest_source_commit'],
        'guest_source_sha256': attempt['guest_source_sha256'],
        'source_hashes': attempt['source_hashes'], 'attempt': attempt,
        'pci_command_before': host_before['pci_command'],
        'pci_command_after': host_after['pci_command'],
        'reset_methods_before': host_before['reset_methods'],
        'reset_methods_after': host_after['reset_methods'],
        'kernel_cursor_before': before['journal_cursor'],
        'kernel_cursor_after': after['journal_cursor'],
        'kernel_messages': after['journal_messages'],
        'host_before': before, 'host_after': after,
        'bar5': transaction['bar5'], 'transaction': transaction,
    }


def validate_receipt(receipt, boot_id, prior_run_id, vm=None):
    """Validate only the distinct one-shot schema-4 startup receipt."""
    try:
        if (boot_id, prior_run_id) != (BOOT_ID, RUN_ID):
            raise StartupRecoveryError('receipt pinned identity')
        expected_keys = {
            'schema', 'kind', 'status', 'authorizes_launch', 'boot_id',
            'prior_run_id', 'build_id', 'device', 'iommu_group', 'driver',
            'recovery_id', 'attempt_id', 'inspection_sha256', 'ledger_sha256',
            'archive_sha256', 'attempt_sha256', 'guest_source_commit',
            'guest_source_sha256', 'source_hashes', 'attempt',
            'pci_command_before', 'pci_command_after', 'reset_methods_before',
            'reset_methods_after', 'kernel_cursor_before', 'kernel_cursor_after',
            'kernel_messages', 'host_before', 'host_after', 'bar5', 'transaction',
        }
        if not isinstance(receipt, dict) or set(receipt) != expected_keys:
            raise StartupRecoveryError('receipt fields')
        exact = {
            'schema': 4, 'kind': 'startup-noqueue-recovery', 'status': 'recovered',
            'authorizes_launch': True, 'boot_id': boot_id,
            'prior_run_id': prior_run_id, 'build_id': BUILD_ID,
            'device': RECOVERY.DEVICE, 'iommu_group': RECOVERY.GROUP,
            'driver': 'vfio-pci', 'inspection_sha256': INSPECTION_SHA256,
            'ledger_sha256': LEDGER_SHA256, 'archive_sha256': ARCHIVE_SHA256,
        }
        if any(receipt.get(key) != expected for key, expected in exact.items()):
            raise StartupRecoveryError('receipt identity')
        for key in ('recovery_id', 'attempt_id'):
            if not re.fullmatch(r'[0-9a-f]{32}', str(receipt.get(key, ''))):
                raise StartupRecoveryError('receipt ID')
        hashes = source_hashes()
        if receipt['source_hashes'] != hashes:
            raise StartupRecoveryError('receipt source hashes')
        attempt = receipt['attempt']
        attempt_keys = {
            'schema', 'kind', 'boot_id', 'prior_run_id', 'build_id',
            'attempt_id', 'recovery_id', 'inspection_sha256', 'ledger_sha256',
            'archive_sha256', 'guest_source_commit', 'guest_source_sha256',
            'source_hashes', 'created_epoch',
        }
        if (not isinstance(attempt, dict) or set(attempt) != attempt_keys or
                attempt.get('schema') != 1 or
                attempt.get('kind') != 'startup-noqueue-attempt' or
                attempt.get('boot_id') != boot_id or
                attempt.get('prior_run_id') != prior_run_id or
                attempt.get('build_id') != BUILD_ID or
                attempt.get('attempt_id') != receipt['attempt_id'] or
                attempt.get('recovery_id') != receipt['recovery_id'] or
                attempt.get('inspection_sha256') != INSPECTION_SHA256 or
                attempt.get('ledger_sha256') != LEDGER_SHA256 or
                attempt.get('archive_sha256') != ARCHIVE_SHA256 or
                attempt.get('source_hashes') != hashes or
                type(attempt.get('created_epoch')) not in (int, float) or
                isinstance(attempt.get('created_epoch'), bool) or
                not math.isfinite(attempt['created_epoch']) or
                receipt.get('guest_source_commit') != attempt.get('guest_source_commit') or
                receipt.get('guest_source_sha256') != attempt.get('guest_source_sha256') or
                receipt.get('attempt_sha256') != _sha256(_json_bytes(attempt))):
            raise StartupRecoveryError('receipt attempt')
        if vm is not None:
            path = (Path(vm) / 'run/startup-noqueue-attempts' / boot_id /
                    (prior_run_id + '.json'))
            if path.read_bytes() != _json_bytes(attempt):
                raise StartupRecoveryError('receipt attempt file')
            ledger_path = Path(vm) / 'run/used-gpu-boots' / (boot_id + '.json')
            if _sha256(ledger_path.read_bytes()) != LEDGER_SHA256:
                raise StartupRecoveryError('receipt ledger preimage')
        if (receipt['pci_command_before'] != 3 or receipt['pci_command_after'] != 3 or
                receipt['reset_methods_before'] != [] or
                receipt['reset_methods_after'] != [] or
                receipt['kernel_cursor_before'] != receipt['host_before']['journal_cursor'] or
                receipt['kernel_cursor_after'] != receipt['host_after']['journal_cursor'] or
                receipt['kernel_messages'] != receipt['host_after']['journal_messages'] or
                not _valid_host_proof(receipt['host_before']) or
                not _valid_host_proof(receipt['host_after']) or
                INSPECTOR._stable_pre_post_errors(
                    receipt['host_before'], receipt['host_after'])):
            raise StartupRecoveryError('receipt host proof')
        manifests = [receipt[side].get('manifest', {})
                     for side in ('host_before', 'host_after')]
        if any(attempt.get('guest_source_commit') != manifest.get('source_commit') or
               attempt.get('guest_source_sha256') != manifest.get('source_sha256')
               for manifest in manifests):
            raise StartupRecoveryError('receipt guest source identity')
        _validate_transaction(receipt['transaction'])
        if receipt['bar5'] != receipt['transaction']['bar5']:
            raise StartupRecoveryError('receipt BAR metadata')
    except BaseException:
        return ['startup_noqueue_receipt']
    return []


def recover_once(vm, evidence_dir, inspection_path, output, *, preflight_reader,
                 postflight_reader, transport_factory):
    """Own the one-shot files and call only the explicitly injected VFIO factory."""
    vm = Path(vm).resolve()
    output = Path(output).resolve()
    expected_dir = (vm / 'run/startup-noqueue-results').resolve()
    if output.parent != expected_dir or output.suffix != '.json':
        raise StartupRecoveryError('output must be a startup-noqueue result JSON')
    if output.exists():
        raise FileExistsError(output)
    lock = vm / 'run/experiment.lock'
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open('a') as owner:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            preflight = preflight_reader()
        except BaseException as error:
            result = {'schema': 1, 'kind': 'startup-noqueue-result',
                      'status': 'failed', 'authorizes_launch': False,
                      'phase': 'preflight',
                      'error': type(error).__name__ + ': ' + str(error)}
            RECOVERY.write_once(output, result)
            raise StartupRecoveryError(result['error'], result) from error
        try:
            errors = _preflight_errors(preflight)
        except BaseException as error:
            result = {'schema': 1, 'kind': 'startup-noqueue-result',
                      'status': 'failed', 'authorizes_launch': False,
                      'phase': 'preflight',
                      'error': type(error).__name__ + ': ' + str(error)}
            RECOVERY.write_once(output, result)
            raise StartupRecoveryError(result['error'], result) from error
        if errors:
            result = {'schema': 1, 'kind': 'startup-noqueue-result',
                      'status': 'failed', 'authorizes_launch': False,
                      'phase': 'preflight', 'preflight': _json_safe_preflight(preflight),
                      'error': 'pre-VFIO proof failed: ' + ','.join(errors)}
            RECOVERY.write_once(output, result)
            raise StartupRecoveryError(result['error'], result)
        attempt_path = (vm / 'run/startup-noqueue-attempts' / BOOT_ID /
                        (RUN_ID + '.json'))
        receipt_path = (vm / 'run/startup-noqueue-recovery' / BOOT_ID /
                        (RUN_ID + '.json'))
        if attempt_path.exists():
            result = {'schema': 1, 'kind': 'startup-noqueue-result',
                      'status': 'failed', 'authorizes_launch': False,
                      'phase': 'pre-VFIO',
                      'error': 'startup-noqueue attempt already exists'}
            RECOVERY.write_once(output, result)
            raise StartupRecoveryError(result['error'], result)
        if receipt_path.exists():
            result = {'schema': 1, 'kind': 'startup-noqueue-result',
                      'status': 'failed', 'authorizes_launch': False,
                      'phase': 'pre-VFIO',
                      'error': 'startup-noqueue receipt already exists'}
            RECOVERY.write_once(output, result)
            raise StartupRecoveryError(result['error'], result)
        attempt = _attempt_record(preflight)
        RECOVERY.write_once(attempt_path, attempt)
        attempt_raw = attempt_path.read_bytes()
        result = {'schema': 1, 'kind': 'startup-noqueue-result',
                  'status': 'failed', 'authorizes_launch': False,
                  'attempt': attempt, 'attempt_sha256': _sha256(attempt_raw),
                  'preflight': _json_safe_preflight(preflight)}
        transaction_error = None
        try:
            with transport_factory() as transport:
                result['transaction'] = execute_transaction(
                    transport, preflight['inspection'], sleep=time.sleep, polls=2000)
        except BaseException as error:
            transaction_error = error
            if isinstance(error, StartupRecoveryError):
                result['transaction'] = error.evidence
            result['error'] = type(error).__name__ + ': ' + str(error)
        try:
            postflight = postflight_reader(preflight['journal_cursor'])
            result['postflight'] = _json_safe_preflight(postflight)
            post_errors = _preflight_errors(postflight)
            post_errors += INSPECTOR._stable_pre_post_errors(
                preflight['host_proof'], postflight['host_proof'])
        except BaseException as error:
            postflight = {}
            result['postflight'] = {'error': type(error).__name__ + ': ' + str(error)}
            post_errors = ['postflight collection']
        if post_errors:
            result['postflight_errors'] = sorted(set(post_errors))
        if postflight.get('source_hashes') != preflight.get('source_hashes'):
            post_errors.append('cleanup source hashes changed')
            result['postflight_errors'] = sorted(set(post_errors))
        if transaction_error is not None or post_errors:
            RECOVERY.write_once(output, result)
            message = result.get('error', 'postflight failed')
            raise StartupRecoveryError(message, result)
        try:
            receipt = build_receipt(
                result['transaction'], attempt, result['attempt_sha256'],
                preflight['host_proof'], postflight['host_proof'])
            receipt_errors = validate_receipt(receipt, BOOT_ID, RUN_ID, vm=vm)
            if receipt_errors:
                raise StartupRecoveryError(
                    'receipt validation failed: ' + ','.join(receipt_errors))
        except BaseException as error:
            result['error'] = type(error).__name__ + ': ' + str(error)
            RECOVERY.write_once(output, result)
            raise StartupRecoveryError(result['error'], result)
        receipt_raw = _json_bytes(receipt)
        result.update(status='recovered', receipt_sha256=_sha256(receipt_raw),
                      receipt=str(receipt_path))
        RECOVERY.write_once(output, result)
        RECOVERY.write_once(receipt_path, receipt)
        return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vm-dir', required=True, type=Path)
    parser.add_argument('--evidence-dir', required=True, type=Path)
    parser.add_argument('--inspection', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    vm = args.vm_dir.resolve()
    try:
        recover_once(
            vm, args.evidence_dir.resolve(), args.inspection.resolve(),
            args.output.resolve(),
            preflight_reader=lambda: collect_preflight(
                vm, args.evidence_dir.resolve(), args.inspection.resolve()),
            postflight_reader=lambda cursor: collect_preflight(
                vm, args.evidence_dir.resolve(), args.inspection.resolve(), cursor),
            transport_factory=RECOVERY.LegacyVfio)
    except BaseException as error:
        print(json.dumps({'status': 'failed', 'authorizes_launch': False,
                          'error': type(error).__name__ + ': ' + str(error)}, indent=2))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
