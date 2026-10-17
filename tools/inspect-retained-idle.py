#!/usr/bin/env python3
"""Take a nonauthorizing selector-only idle snapshot after candidate 175."""
import argparse
import ctypes
import fcntl
import hashlib
import importlib.util
import json
import mmap
import os
from pathlib import Path
import re
import struct
import sys
import time


def _helper(name):
    path = Path(__file__).with_name(name + '.py')
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


OBSERVER = _helper('inspect-retained-kiq')
RECOVERY = OBSERVER.RECOVERY
OBSERVER_SOURCE_SHA256 = 'cf6513926a9c9fbf5f11df3cd1980ca3de90a786d8ef4c5f21d8764d5755b3d9'
LOADED_OBSERVER_SOURCE_SHA256 = hashlib.sha256(
    Path(__file__).with_name('inspect-retained-kiq.py').read_bytes()).hexdigest()
BASELINE_SHA256 = 'f0282d7b51ad2a6f962c03c0bb467c9e5058784a0055a427697bbb4e31eee4f8'
BOOT_ID, RUN_ID = OBSERVER.BOOT_ID, OBSERVER.RUN_ID

BAR5_SIZE = 0x80000
VFIO_GET_API_VERSION = OBSERVER.VFIO_GET_API_VERSION
VFIO_CHECK_EXTENSION = OBSERVER.VFIO_CHECK_EXTENSION
VFIO_API_VERSION = OBSERVER.VFIO_API_VERSION
VFIO_TYPE1_IOMMU = OBSERVER.VFIO_TYPE1_IOMMU
VFIO_GROUP_GET_STATUS = OBSERVER.VFIO_GROUP_GET_STATUS
VFIO_GROUP_SET_CONTAINER = OBSERVER.VFIO_GROUP_SET_CONTAINER
VFIO_GROUP_GET_DEVICE_FD = OBSERVER.VFIO_GROUP_GET_DEVICE_FD
VFIO_SET_IOMMU = OBSERVER.VFIO_SET_IOMMU
VFIO_DEVICE_GET_REGION_INFO = OBSERVER.VFIO_DEVICE_GET_REGION_INFO
VFIO_GROUP_FLAGS_VIABLE = OBSERVER.VFIO_GROUP_FLAGS_VIABLE
VFIO_REGION_INFO_FLAG_READ = OBSERVER.VFIO_REGION_INFO_FLAG_READ
VFIO_REGION_INFO_FLAG_WRITE = OBSERVER.VFIO_REGION_INFO_FLAG_WRITE
VFIO_REGION_INFO_FLAG_MMAP = OBSERVER.VFIO_REGION_INFO_FLAG_MMAP
VFIO_PCI_BAR5_REGION_INDEX = RECOVERY.VFIO_PCI_BAR5_REGION_INDEX
VfioGroupStatus, VfioRegionInfo, ioctl = (
    OBSERVER.VfioGroupStatus, OBSERVER.VfioRegionInfo, OBSERVER.ioctl)

SDMA0_STATUS_REG_OFFSET = (RECOVERY.GC_SEG0 + 0x0025) * 4
SDMA_STATUS_IDLE_MASK = 1
SDMA_AUX_OFFSETS = {
    'status': SDMA0_STATUS_REG_OFFSET,
    'page_rb_cntl': (RECOVERY.GC_SEG0 + 0x00d8) * 4,
    'page_ib_cntl': (RECOVERY.GC_SEG0 + 0x00e2) * 4,
    'rlc0_rb_cntl': (RECOVERY.GC_SEG0 + 0x0130) * 4,
    'rlc0_ib_cntl': (RECOVERY.GC_SEG0 + 0x013a) * 4,
    'rlc1_rb_cntl': (RECOVERY.GC_SEG0 + 0x0188) * 4,
    'rlc1_ib_cntl': (RECOVERY.GC_SEG0 + 0x0192) * 4,
}
GLOBAL_OFFSETS = {
    'cp_stat': RECOVERY.CP_STAT_OFFSET,
    'cpc_busy': RECOVERY.CP_CPC_BUSY_STAT_OFFSET,
    'me_cntl': RECOVERY.CP_ME_CNTL_OFFSET,
    'mec_cntl': RECOVERY.CP_MEC_CNTL_OFFSET,
    'rb0_active': RECOVERY.CP_RB_ACTIVE_OFFSET,
    'rb1_active': RECOVERY.CP_RB1_ACTIVE_OFFSET,
    'rb_doorbell_control': RECOVERY.CP_RB_DOORBELL_CONTROL_OFFSET,
    'pq_wptr_poll_cntl': RECOVERY.CP_PQ_WPTR_POLL_CNTL_OFFSET,
    'pq_status': RECOVERY.CP_PQ_STATUS_OFFSET,
    'doorbell_range_lower': RECOVERY.CP_MEC_DOORBELL_RANGE_LOWER_OFFSET,
    'doorbell_range_upper': RECOVERY.CP_MEC_DOORBELL_RANGE_UPPER_OFFSET,
    'sdma0_cntl': RECOVERY.SDMA0_CNTL_OFFSET,
    'sdma0_f32_cntl': RECOVERY.SDMA0_F32_CNTL_OFFSET,
    'sdma0_gfx_rb_cntl': RECOVERY.SDMA0_GFX_RB_CNTL_OFFSET,
    'sdma0_gfx_ib_cntl': RECOVERY.SDMA0_GFX_IB_CNTL_OFFSET,
    **{'sdma0_' + name: offset for name, offset in SDMA_AUX_OFFSETS.items()},
}
GRAPHICS_READ_OFFSETS = {
    RECOVERY.CP_RB_DOORBELL_CONTROL_OFFSET,
    RECOVERY.CP_RB_ACTIVE_OFFSET, RECOVERY.CP_RB1_ACTIVE_OFFSET,
    RECOVERY.CP_RB0_WPTR_OFFSET, RECOVERY.CP_RB0_WPTR_HI_OFFSET,
    RECOVERY.CP_RB0_BASE_OFFSET, RECOVERY.CP_RB0_BASE_HI_OFFSET,
    RECOVERY.CP_RB0_CNTL_OFFSET, RECOVERY.CP_RB1_WPTR_OFFSET,
    RECOVERY.CP_RB1_WPTR_HI_OFFSET, RECOVERY.CP_RB1_BASE_OFFSET,
    RECOVERY.CP_RB1_BASE_HI_OFFSET, RECOVERY.CP_RB1_CNTL_OFFSET,
}
HOST_KIQ_DETAIL_OFFSETS = {
    'dequeue': RECOVERY.CP_HQD_DEQUEUE_OFFSET,
    'rptr': RECOVERY.CP_HQD_PQ_RPTR_OFFSET,
    'wptr_lo': RECOVERY.CP_HQD_PQ_WPTR_LO_OFFSET,
    'wptr_hi': RECOVERY.CP_HQD_PQ_WPTR_HI_OFFSET,
}
READ_OFFSETS = (set(GLOBAL_OFFSETS.values()) | GRAPHICS_READ_OFFSETS |
                set(HOST_KIQ_DETAIL_OFFSETS.values()) |
                {RECOVERY.CP_HQD_ACTIVE_OFFSET,
                 RECOVERY.CP_HQD_PQ_DOORBELL_OFFSET})
COMPUTE_SELECTORS = tuple(
    RECOVERY.queue_selector(me, pipe, queue)
    for me in (1, 2) for pipe in range(4) for queue in range(8))
VALID_SELECTORS = {0, 1, *COMPUTE_SELECTORS}


class IdleInspectionError(RuntimeError):
    def __init__(self, message, evidence=None):
        super().__init__(message)
        self.evidence = evidence or {}


def _sha256(data): return hashlib.sha256(data).hexdigest()


class Bar5SelectorTransport(OBSERVER.Bar0ReadTransport):
    """Map BAR5 only; expose fixed reads and GRBM selector stores only."""
    def __enter__(self):
        try:
            self.container_fd = os.open(self.root/'vfio', os.O_RDWR | os.O_CLOEXEC)
            if ioctl(self.container_fd, VFIO_GET_API_VERSION) != VFIO_API_VERSION:
                raise IdleInspectionError('unsupported VFIO API version')
            if ioctl(self.container_fd, VFIO_CHECK_EXTENSION, VFIO_TYPE1_IOMMU) <= 0:
                raise IdleInspectionError('VFIO type1 IOMMU unavailable')
            self.group_fd = os.open(self.root/OBSERVER.GROUP, os.O_RDWR | os.O_CLOEXEC)
            status = VfioGroupStatus(ctypes.sizeof(VfioGroupStatus), 0)
            ioctl(self.group_fd, VFIO_GROUP_GET_STATUS, ctypes.byref(status))
            if not status.flags & VFIO_GROUP_FLAGS_VIABLE:
                raise IdleInspectionError('VFIO group is not viable')
            container = ctypes.c_int(self.container_fd)
            ioctl(self.group_fd, VFIO_GROUP_SET_CONTAINER, ctypes.byref(container))
            self.container_set = True
            ioctl(self.container_fd, VFIO_SET_IOMMU, VFIO_TYPE1_IOMMU)
            name = ctypes.create_string_buffer(OBSERVER.DEVICE.encode() + b'\0')
            self.device_fd = ioctl(self.group_fd, VFIO_GROUP_GET_DEVICE_FD,
                                   ctypes.cast(name, ctypes.c_void_p))
            region = VfioRegionInfo(ctypes.sizeof(VfioRegionInfo), 0,
                                    VFIO_PCI_BAR5_REGION_INDEX, 0, 0, 0)
            ioctl(self.device_fd, VFIO_DEVICE_GET_REGION_INFO, ctypes.byref(region))
            needed = (VFIO_REGION_INFO_FLAG_READ | VFIO_REGION_INFO_FLAG_WRITE |
                      VFIO_REGION_INFO_FLAG_MMAP)
            if region.size != BAR5_SIZE or region.flags & needed != needed:
                raise IdleInspectionError('BAR5 is not the exact selector mapping')
            self.region = region
            self.bar0 = mmap.mmap(self.device_fd, region.size, flags=mmap.MAP_SHARED,
                                  prot=mmap.PROT_READ | mmap.PROT_WRITE,
                                  offset=region.offset)
            return self
        except BaseException as error:
            try:
                self.close()
            except BaseException as close_error:
                raise IdleInspectionError(
                    f'{type(error).__name__}: {error}; close failed: {close_error}') from error
            raise

    def _raw32(self, offset): return struct.unpack_from('<I', self.bar0, offset)[0]

    def __exit__(self, kind, error, traceback):
        try:
            self.close()
        except BaseException as close_error:
            if error is not None:
                evidence = (error.evidence
                            if isinstance(error, IdleInspectionError) else None)
                raise IdleInspectionError(
                    f'{type(error).__name__}: {error}; close failed: '
                    f'{type(close_error).__name__}: {close_error}', evidence) from error
            raise

    def read32(self, offset):
        if type(offset) is not int or offset not in READ_OFFSETS:
            raise IdleInspectionError(f'forbidden BAR5 read at {offset!r}')
        return self._raw32(offset)

    def select(self, value):
        if type(value) is not int or value not in VALID_SELECTORS:
            raise IdleInspectionError(f'forbidden selector value {value!r}')
        struct.pack_into('<I', self.bar0, RECOVERY.GRBM_GFX_CNTL_OFFSET, value)
        posted = self._raw32(RECOVERY.NBIO_CONFIG_MEMSIZE_OFFSET)
        if posted != RECOVERY.resolve_expected_config_memsize():
            raise IdleInspectionError('selector posting read failed')

    def metadata(self):
        return {'index': self.region.index, 'size': self.region.size,
                'offset': self.region.offset, 'userspace_mapping': 'BAR5-only',
                'userspace_selector_writes_only': True,
                'kernel_vfio_lifecycle_configuration_activity': True}


class _TracingAdapter:
    def __init__(self, transport, evidence):
        self.transport, self.evidence, self.phase = transport, evidence, 'unset'

    def select(self, value, phase):
        row = {'sequence': len(self.evidence['selector_writes']), 'phase': phase,
               'value': value, 'attempted': True, 'completed': False}
        self.evidence['selector_writes'].append(row)
        try:
            self.transport.select(value)
        except BaseException as error:
            row['error'] = type(error).__name__ + ': ' + str(error)
            raise
        row['completed'] = True

    def write32(self, offset, value):
        if offset != RECOVERY.GRBM_GFX_CNTL_OFFSET:
            raise IdleInspectionError(f'forbidden helper write at {offset:#x}')
        self.select(value, self.phase)

    def read32(self, offset): return self.transport.read32(offset)


def _capture_graphics(mmio, number, result):
    result.update({'pipes': [],
                   'final_default': {'value': 0, 'completed': False}})
    try:
        for (pipe, selector, active_offset, wptr_offset, wptr_hi_offset,
             base_offset, base_hi_offset, cntl_offset) in \
                RECOVERY.GRAPHICS_PIPE_DESCRIPTORS:
            mmio.select(selector, f'pass-{number}-graphics')
            row = {'intended_pipe': pipe, 'selector': selector}
            result['pipes'].append(row)
            row['doorbell_control'] = mmio.read32(
                RECOVERY.CP_RB_DOORBELL_CONTROL_OFFSET)
            row['doorbell_offset'] = (row['doorbell_control'] &
                                      RECOVERY.CP_RB_DOORBELL_OFFSET_MASK)
            row['doorbell_status'] = (row['doorbell_control'] &
                                      RECOVERY.CP_RB_DOORBELL_STATUS_MASK)
            row['rb0_active'] = mmio.read32(RECOVERY.CP_RB_ACTIVE_OFFSET)
            row['rb1_active'] = mmio.read32(RECOVERY.CP_RB1_ACTIVE_OFFSET)
            row['active'] = (row['rb0_active']
                             if active_offset == RECOVERY.CP_RB_ACTIVE_OFFSET
                             else row['rb1_active'])
            row['wptr'] = mmio.read32(wptr_offset)
            row['wptr_hi'] = mmio.read32(wptr_hi_offset)
            row['base'] = mmio.read32(base_offset)
            row['base_hi'] = mmio.read32(base_hi_offset)
            row['cntl'] = mmio.read32(cntl_offset)
    finally:
        mmio.select(0, f'pass-{number}-graphics')
        result['final_default']['completed'] = True


def _capture_pass(mmio, number, result):
    mmio.select(0, f'pass-{number}-globals-default')
    result.update({'globals': {}, 'compute': [], 'graphics': {}})
    for name, offset in GLOBAL_OFFSETS.items():
        result['globals'][name] = mmio.read32(offset)
    for me in (1, 2):
        for pipe in range(4):
            for queue in range(8):
                selector = RECOVERY.queue_selector(me, pipe, queue)
                mmio.select(selector,
                            f'pass-{number}-me-{me}-pipe-{pipe}-queue-{queue}')
                row = {'me': me, 'pipe': pipe, 'queue': queue,
                       'selector': selector}
                result['compute'].append(row)
                row['active'] = mmio.read32(RECOVERY.CP_HQD_ACTIVE_OFFSET)
                row['pq_doorbell_control'] = mmio.read32(
                    RECOVERY.CP_HQD_PQ_DOORBELL_OFFSET)
                if selector == RECOVERY.HOST_KIQ_SELECTOR:
                    row['host_kiq'] = {}
                    for name, offset in HOST_KIQ_DETAIL_OFFSETS.items():
                        row['host_kiq'][name] = mmio.read32(offset)
    _capture_graphics(mmio, number, result['graphics'])


def _validation_errors(evidence):
    errors = []
    passes = evidence.get('passes', [])
    if len(passes) != 2 or passes[0] != passes[1]:
        return ['full observations changed between passes']
    for scan in passes:
        values = scan['globals']
        if any(type(value) is not int or value == 0xffffffff for value in values.values()):
            errors.append('global all-ones/inaccessible')
        if values['cp_stat'] != 0: errors.append('CP_STAT is not zero')
        if values['cpc_busy'] != 0: errors.append('CPC_BUSY is not zero')
        if values['me_cntl'] & RECOVERY.CP_ME_HALT_MASK != RECOVERY.CP_ME_HALT_MASK:
            errors.append('ME halt is absent')
        if values['mec_cntl'] & RECOVERY.CP_MEC_HALT_MASK != RECOVERY.CP_MEC_HALT_MASK:
            errors.append('MEC halt is absent')
        if values['rb0_active'] & 1 or values['rb1_active'] & 1:
            errors.append('graphics global is active')
        if values['rb_doorbell_control'] & RECOVERY.CP_RB_DOORBELL_STATUS_MASK:
            errors.append('graphics global doorbell is enabled/hit')
        if values['pq_wptr_poll_cntl'] & RECOVERY.CP_PQ_WPTR_POLL_ENABLE_MASK:
            errors.append('PQ polling is enabled')
        if values['pq_status'] & RECOVERY.CP_PQ_DOORBELL_ENABLE_MASK:
            errors.append('PQ doorbell gate is enabled')
        if values['doorbell_range_lower'] or values['doorbell_range_upper']:
            errors.append('MEC doorbell range is nonzero')
        if values['sdma0_cntl'] & RECOVERY.SDMA_AUTO_CTXSW_ENABLE_MASK:
            errors.append('SDMA input is enabled')
        if values['sdma0_gfx_rb_cntl'] & RECOVERY.SDMA_RB_ENABLE_MASK or \
                values['sdma0_gfx_ib_cntl'] & RECOVERY.SDMA_IB_ENABLE_MASK:
            errors.append('SDMA input is enabled')
        if values['sdma0_f32_cntl'] & RECOVERY.SDMA_HALT_MASK != RECOVERY.SDMA_HALT_MASK:
            errors.append('SDMA halt is absent')
        if not values['sdma0_status'] & SDMA_STATUS_IDLE_MASK:
            errors.append('SDMA idle is absent')
        if any(values['sdma0_' + name] & 1 for name in SDMA_AUX_OFFSETS
               if name != 'status'):
            errors.append('SDMA input is enabled')
        for row in scan['compute']:
            if row['active'] == 0xffffffff or row['pq_doorbell_control'] == 0xffffffff:
                errors.append('compute all-ones/inaccessible')
            elif row['active'] & 1:
                errors.append('compute queue is active')
            if row['pq_doorbell_control']:
                errors.append('compute doorbell is nonzero')
            if row['selector'] == RECOVERY.HOST_KIQ_SELECTOR:
                detail = row.get('host_kiq', {})
                if set(detail) != set(HOST_KIQ_DETAIL_OFFSETS) or any(
                        type(value) is not int or value == 0xffffffff
                        for value in detail.values()):
                    errors.append('selector 9 detail is inaccessible')
                elif any(detail.values()) or row['active'] != 0:
                    errors.append('selector 9 state is not zero')
        graphics = scan['graphics']
        if not RECOVERY._graphics_snapshot_accessible(graphics):
            errors.append('graphics snapshot is malformed/inaccessible')
        else:
            for row in graphics['pipes']:
                if row['rb0_active'] & 1 or row['rb1_active'] & 1:
                    errors.append('graphics pipe is active')
                if row['doorbell_status']:
                    errors.append('graphics pipe doorbell is enabled/hit')
            if not RECOVERY.valid_apple_graphics_snapshot(graphics):
                errors.append('graphics snapshot is malformed/inaccessible')
    return sorted(set(errors))


def scan_device(transport):
    evidence = {'status': 'failed', 'authorizes_launch': False,
                'authorizes_recovery': False, 'authorizes_cleanup': False,
                'passes': [], 'selector_writes': [],
                'final_default': {'attempted': False, 'completed': False, 'value': 0}}
    mmio = _TracingAdapter(transport, evidence)
    primary = None
    try:
        for number in (1, 2):
            row = {'globals': {}, 'compute': [], 'graphics': {}}
            evidence['passes'].append(row)
            _capture_pass(mmio, number, row)
        evidence['vfio_region'] = transport.metadata()
        errors = _validation_errors(evidence)
        if errors:
            raise IdleInspectionError(', '.join(errors), evidence)
    except BaseException as error:
        primary = error
    finally:
        try:
            mmio.select(0, 'final-default')
            evidence['final_default'] = {'attempted': True, 'completed': True, 'value': 0}
        except BaseException as error:
            evidence['final_default'] = {
                'attempted': True, 'completed': False, 'value': 0,
                'error': type(error).__name__ + ': ' + str(error)}
            if primary is None:
                primary = error
            else:
                primary = IdleInspectionError(
                    f'{primary}; final default failed: {error}', evidence)
    if primary is not None:
        evidence['error'] = type(primary).__name__ + ': ' + str(primary)
        if isinstance(primary, IdleInspectionError) and primary.evidence is evidence:
            raise primary
        raise IdleInspectionError(type(primary).__name__ + ': ' + str(primary), evidence)
    evidence['status'] = 'observed-idle'
    return evidence


EXPECTED_MQD_DIFF = {
    0x158: 0x12fbe02c, 0x15c: 0x00000106,
    0x168: 0x12fbe020, 0x16c: 0x00000106,
    0x174: 0x00000100, 0x178: 0x00000100,
}


def baseline_content_errors(value):
    errors = []
    if (value.get('status') != 'observed' or value.get('authorizes_launch') is not False or
            value.get('authorizes_recovery') is not False or
            value.get('authorizes_cleanup') is not False):
        errors.append('baseline status')
    device = value.get('device', {})
    analysis = device.get('analysis', {})
    if (analysis.get('ring_exact') is not True or
            analysis.get('fence_matches_sequence') is not True or
            analysis.get('sequence') != 0x667b2f65 or
            analysis.get('current_fence') != 0x667b2f65 or
            analysis.get('current_report') != 0x100 or
            analysis.get('stored_wptr') != 0x100):
        errors.append('baseline retained execution evidence')
    try:
        row = next(row for row in device['ranges'] if row['name'] == 'mqd')
        actual = bytes.fromhex(row['passes'][0]['data_hex'])
        second = bytes.fromhex(row['passes'][1]['data_hex'])
        _, expected = OBSERVER.expected_images(analysis['sequence'])
        diff = {offset: struct.unpack_from('<I', actual, offset)[0]
                for offset in range(0, len(actual), 4)
                if actual[offset:offset+4] != expected[offset:offset+4]}
        if (actual != second or row.get('stable') is not True or
                _sha256(actual) != '3329c7874b030528c47fb6946858820a5b8847537e065ef17dc40d867460b3c7' or
                diff != EXPECTED_MQD_DIFF):
            errors.append('baseline exact MQD lifecycle diff')
    except (KeyError, StopIteration, TypeError, ValueError, struct.error):
        errors.append('baseline MQD capture')
    return errors


def collect_preflight(vm, evidence_dir, expected_scanner_source_sha256,
                      journal_cursor=None):
    vm = Path(vm).resolve()
    base = OBSERVER.collect_preflight(
        vm, evidence_dir, OBSERVER_SOURCE_SHA256, journal_cursor)
    path = vm/'run/retained-kiq-inspections'/f'{BOOT_ID}-{RUN_ID}.json'
    raw = path.read_bytes()
    return {
        'base': base, 'base_errors': OBSERVER.preflight_errors(base),
        'baseline_sha256': _sha256(raw),
        'baseline_errors': baseline_content_errors(json.loads(raw)),
        'scanner_source_sha256': _sha256(Path(__file__).read_bytes()),
        'expected_scanner_source_sha256': expected_scanner_source_sha256,
        'loaded_observer_source_sha256': LOADED_OBSERVER_SOURCE_SHA256,
        'current_observer_source_sha256': _sha256(
            Path(__file__).with_name('inspect-retained-kiq.py').read_bytes()),
    }


def preflight_errors(proof):
    errors = list(proof.get('base_errors', ['base proof missing']))
    if errors: errors = ['base: ' + error for error in errors]
    if proof.get('baseline_sha256') != BASELINE_SHA256 or proof.get('baseline_errors') != []:
        errors.append('baseline retained observation')
    if (proof.get('loaded_observer_source_sha256') != OBSERVER_SOURCE_SHA256 or
            proof.get('current_observer_source_sha256') != OBSERVER_SOURCE_SHA256):
        errors.append('observer source changed')
    if proof.get('scanner_source_sha256') != proof.get('expected_scanner_source_sha256'):
        errors.append('scanner source changed')
    return errors


def postflight_errors(before, after):
    errors = preflight_errors(after)
    errors.extend('base postflight: ' + error for error in
                  OBSERVER.postflight_errors(before.get('base', {}),
                                             after.get('base', {})))
    for key in ('baseline_sha256', 'baseline_errors',
                'scanner_source_sha256', 'expected_scanner_source_sha256',
                'loaded_observer_source_sha256', 'current_observer_source_sha256'):
        if before.get(key) != after.get(key): errors.append(key + ' changed')
    return errors


def run_inspection(preflight_reader, transport_factory, postflight_reader, output):
    output = Path(output); attempt = output.with_suffix('.attempt.json')
    if output.exists() or attempt.exists():
        raise FileExistsError('retained idle inspection path was already consumed')
    base = {'schema': 1, 'kind': 'retained-idle-selector-inspection',
            'status': 'failed', 'authorizes_launch': False,
            'authorizes_recovery': False, 'authorizes_cleanup': False,
            'boot_id': BOOT_ID, 'run_id': RUN_ID}
    try:
        pre = preflight_reader()
    except BaseException as error:
        result = dict(base, error='preflight collection: ' + str(error),
                      created_epoch=time.time())
        OBSERVER._write_once(output, result)
        raise IdleInspectionError(result['error'], result) from error
    errors = preflight_errors(pre)
    if errors:
        result = dict(base, preflight=pre, error='pre-VFIO ' + ', '.join(errors),
                      created_epoch=time.time())
        OBSERVER._write_once(output, result)
        raise IdleInspectionError(result['error'], result)
    OBSERVER._write_once(attempt, dict(base, status='device-open-attempted',
                                       created_epoch=time.time()))
    device = device_error = None
    try:
        with transport_factory() as transport: device = scan_device(transport)
    except BaseException as error:
        device_error = error
        if isinstance(error, IdleInspectionError): device = error.evidence
    try:
        post = postflight_reader(pre['base']['journal_cursor'])
        post_errors = postflight_errors(pre, post)
    except BaseException as error:
        post = {'collection_error': type(error).__name__ + ': ' + str(error)}
        post_errors = ['postflight collection failed']
    result = dict(base, preflight=pre, device=device, postflight=post,
                  created_epoch=time.time())
    if device_error is not None: result['device_error'] = str(device_error)
    if post_errors: result['postflight_errors'] = post_errors
    if device_error is not None or post_errors:
        result['error'] = '; '.join(filter(None, (
            'device: ' + str(device_error) if device_error else '',
            'postflight: ' + ', '.join(post_errors) if post_errors else '')))
        OBSERVER._write_once(output, result)
        raise IdleInspectionError(result['error'], result)
    result['status'] = 'observed-idle'
    OBSERVER._write_once(output, result)
    return result


def inspect_once(vm, evidence_dir, output, expected_scanner_source_sha256):
    vm, evidence_dir, output = map(lambda path: Path(path).resolve(),
                                   (vm, evidence_dir, output))
    expected = vm/'run/retained-idle-inspections'/f'{BOOT_ID}-{RUN_ID}.json'
    if output != expected.resolve(): raise IdleInspectionError(f'output must be {expected}')
    lock = vm/'run/experiment.lock'; lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open('a') as owner:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return run_inspection(
            lambda: collect_preflight(vm, evidence_dir, expected_scanner_source_sha256),
            Bar5SelectorTransport,
            lambda cursor: collect_preflight(
                vm, evidence_dir, expected_scanner_source_sha256, cursor), output)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vm-dir', required=True, type=Path)
    parser.add_argument('--evidence-dir', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--expected-source-sha256', required=True)
    args = parser.parse_args(argv)
    try:
        if not re.fullmatch(r'[0-9a-f]{64}', args.expected_source_sha256):
            raise IdleInspectionError('expected source SHA-256 is invalid')
        result = inspect_once(args.vm_dir, args.evidence_dir, args.output,
                              args.expected_source_sha256)
    except BaseException as error:
        print(json.dumps({'status': 'failed', 'authorizes_launch': False,
                          'authorizes_recovery': False, 'authorizes_cleanup': False,
                          'error': type(error).__name__ + ': ' + str(error)}, indent=2))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True)); return 0


if __name__ == '__main__': sys.exit(main())
