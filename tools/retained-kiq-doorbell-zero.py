#!/usr/bin/env python3
"""Try one halted, inactive KIQ write-pointer update through doorbell zero."""
import argparse
import ctypes
import errno
import fcntl
import hashlib
import importlib.util
import json
import mmap
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import _ctypes


def _helper(name):
    path = Path(__file__).with_name(name + '.py')
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PREPARATION = _helper('prepare-retained-kiq')
SCANNER, RECOVERY = PREPARATION.SCANNER, PREPARATION.RECOVERY
OBSERVER = SCANNER.OBSERVER
PREPARATION_SOURCE_SHA256 = (
    '45535eeaff653ca60ae880cc32530016886a94985a3d30b6bff51d10cefb7085')
LOADED_PREPARATION_SOURCE_SHA256 = hashlib.sha256(
    Path(__file__).with_name('prepare-retained-kiq.py').read_bytes()).hexdigest()
PREPARATION_RESULT_SHA256 = (
    '99bb203ee46b24c1adf55c38366dadbaa238776508cf9d1d46842e125ebbd8ea')
BOOT_ID, RUN_ID = PREPARATION.BOOT_ID, PREPARATION.RUN_ID

BAR2_SIZE = 0x200000
BAR2_MAP_SIZE = 8
DOORBELL_ENABLE = 0x40000000
DOORBELL_HIT = 0x80000000
DOORBELL_ALLOWED = DOORBELL_ENABLE | DOORBELL_HIT
PQ_GATE = RECOVERY.CP_PQ_DOORBELL_ENABLE_MASK
OBSERVATION_BUDGET_NS = 2_000_000
CTYPES_SHA256 = '16ff8ef1cf8e38262db2fbcf1b953e44debacacc62c313f1d52b6ceaa8b48592'
CTYPES_BUILD_ID = '033feee458ae59a5c8aebcae73512fde5dc0f163'
CTYPES_PATH = Path(_ctypes.__file__).resolve()
LOADED_CTYPES_SHA256 = hashlib.sha256(CTYPES_PATH.read_bytes()).hexdigest()

VFIO_GET_API_VERSION = OBSERVER.VFIO_GET_API_VERSION
VFIO_CHECK_EXTENSION = OBSERVER.VFIO_CHECK_EXTENSION
VFIO_API_VERSION = OBSERVER.VFIO_API_VERSION
VFIO_TYPE1_IOMMU = OBSERVER.VFIO_TYPE1_IOMMU
VFIO_GROUP_GET_STATUS = OBSERVER.VFIO_GROUP_GET_STATUS
VFIO_GROUP_SET_CONTAINER = OBSERVER.VFIO_GROUP_SET_CONTAINER
VFIO_GROUP_UNSET_CONTAINER = OBSERVER.VFIO_GROUP_UNSET_CONTAINER
VFIO_GROUP_GET_DEVICE_FD = OBSERVER.VFIO_GROUP_GET_DEVICE_FD
VFIO_SET_IOMMU = OBSERVER.VFIO_SET_IOMMU
VFIO_DEVICE_GET_REGION_INFO = OBSERVER.VFIO_DEVICE_GET_REGION_INFO
VFIO_GROUP_FLAGS_VIABLE = OBSERVER.VFIO_GROUP_FLAGS_VIABLE
VFIO_REGION_INFO_FLAG_READ = OBSERVER.VFIO_REGION_INFO_FLAG_READ
VFIO_REGION_INFO_FLAG_WRITE = OBSERVER.VFIO_REGION_INFO_FLAG_WRITE
VFIO_REGION_INFO_FLAG_MMAP = OBSERVER.VFIO_REGION_INFO_FLAG_MMAP
VFIO_PCI_BAR2_REGION_INDEX = RECOVERY.VFIO_PCI_BAR2_REGION_INDEX
VFIO_PCI_BAR5_REGION_INDEX = RECOVERY.VFIO_PCI_BAR5_REGION_INDEX
VfioGroupStatus, VfioRegionInfo, ioctl = (
    OBSERVER.VfioGroupStatus, OBSERVER.VfioRegionInfo, OBSERVER.ioctl)


class DoorbellZeroError(RuntimeError):
    def __init__(self, message, evidence=None):
        super().__init__(message)
        self.evidence = evidence or {}


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _elf_build_id(path):
    result = subprocess.run(['readelf', '-n', str(path)], text=True,
                            capture_output=True, timeout=10)
    match = re.search(r'Build ID:\s*([0-9a-f]+)', result.stdout, re.I)
    if result.returncode or match is None:
        raise DoorbellZeroError('cannot establish _ctypes ELF build ID')
    return match.group(1).lower()


LOADED_CTYPES_BUILD_ID = _elf_build_id(CTYPES_PATH)


class DoorbellZeroTransport:
    """Map BAR5 plus eight BAR2 bytes and expose only the fixed transaction."""
    def __init__(self, vfio_root=Path('/dev/vfio')):
        self.root = Path(vfio_root)
        self.container_fd = self.group_fd = self.device_fd = None
        self.container_set = False
        self.bar0 = self.bar2 = None  # scanner names the BAR5 mapping bar0
        self.region = self.bar2_region = None
        self._selected = 0
        self.write_log, self.doorbell_log = [], []
        self._operations, self._attempted_operations = [], []

    def __enter__(self):
        try:
            self.container_fd = os.open(self.root/'vfio', os.O_RDWR | os.O_CLOEXEC)
            if ioctl(self.container_fd, VFIO_GET_API_VERSION) != VFIO_API_VERSION:
                raise DoorbellZeroError('unsupported VFIO API version')
            if ioctl(self.container_fd, VFIO_CHECK_EXTENSION, VFIO_TYPE1_IOMMU) <= 0:
                raise DoorbellZeroError('VFIO type1 IOMMU unavailable')
            self.group_fd = os.open(self.root/OBSERVER.GROUP, os.O_RDWR | os.O_CLOEXEC)
            status = VfioGroupStatus(ctypes.sizeof(VfioGroupStatus), 0)
            ioctl(self.group_fd, VFIO_GROUP_GET_STATUS, ctypes.byref(status))
            if not status.flags & VFIO_GROUP_FLAGS_VIABLE:
                raise DoorbellZeroError('VFIO group is not viable')
            container = ctypes.c_int(self.container_fd)
            ioctl(self.group_fd, VFIO_GROUP_SET_CONTAINER, ctypes.byref(container))
            self.container_set = True
            ioctl(self.container_fd, VFIO_SET_IOMMU, VFIO_TYPE1_IOMMU)
            name = ctypes.create_string_buffer(OBSERVER.DEVICE.encode() + b'\0')
            self.device_fd = ioctl(self.group_fd, VFIO_GROUP_GET_DEVICE_FD,
                                   ctypes.cast(name, ctypes.c_void_p))
            needed = (VFIO_REGION_INFO_FLAG_READ | VFIO_REGION_INFO_FLAG_WRITE |
                      VFIO_REGION_INFO_FLAG_MMAP)
            for index, size, map_size in (
                    (VFIO_PCI_BAR5_REGION_INDEX, SCANNER.BAR5_SIZE,
                     SCANNER.BAR5_SIZE),
                    (VFIO_PCI_BAR2_REGION_INDEX, BAR2_SIZE, BAR2_MAP_SIZE)):
                region = VfioRegionInfo(ctypes.sizeof(VfioRegionInfo), 0,
                                        index, 0, 0, 0)
                ioctl(self.device_fd, VFIO_DEVICE_GET_REGION_INFO,
                      ctypes.byref(region))
                if region.size != size or region.flags & needed != needed:
                    raise DoorbellZeroError(f'BAR{index} is not the exact mapping')
                mapping = mmap.mmap(self.device_fd, map_size, flags=mmap.MAP_SHARED,
                                    prot=mmap.PROT_READ | mmap.PROT_WRITE,
                                    offset=region.offset)
                if index == VFIO_PCI_BAR5_REGION_INDEX:
                    self.region, self.bar0 = region, mapping
                else:
                    self.bar2_region, self.bar2 = region, mapping
            return self
        except BaseException as error:
            try:
                self.close()
            except BaseException as close_error:
                raise DoorbellZeroError(
                    f'{type(error).__name__}: {error}; close failed: '
                    f'{type(close_error).__name__}: {close_error}') from error
            raise

    def close(self):
        errors = []
        for name, label in (('bar2', 'BAR2'), ('bar0', 'BAR5')):
            mapping = getattr(self, name)
            if mapping is not None:
                try:
                    mapping.close()
                except BaseException as error:
                    errors.append(f'{label} unmap: {type(error).__name__}: {error}')
                setattr(self, name, None)
        if self.device_fd is not None:
            try:
                os.close(self.device_fd)
            except BaseException as error:
                errors.append('device close: ' + type(error).__name__ + ': ' + str(error))
            self.device_fd = None
        if self.group_fd is not None and self.container_set:
            try:
                ioctl(self.group_fd, VFIO_GROUP_UNSET_CONTAINER)
            except OSError as error:
                if error.errno not in (errno.ENODEV, errno.EINVAL):
                    errors.append('container unset: ' + type(error).__name__ + ': ' + str(error))
            self.container_set = False
        for name in ('group_fd', 'container_fd'):
            fd = getattr(self, name)
            if fd is not None:
                try:
                    os.close(fd)
                except BaseException as error:
                    errors.append(name + ' close: ' + type(error).__name__ + ': ' + str(error))
                setattr(self, name, None)
        if errors:
            raise DoorbellZeroError('; '.join(errors))

    def __exit__(self, kind, error, traceback):
        try:
            self.close()
        except BaseException as close_error:
            if error is not None:
                evidence = (error.evidence
                            if isinstance(error, DoorbellZeroError) else None)
                raise DoorbellZeroError(
                    f'{type(error).__name__}: {error}; close failed: '
                    f'{type(close_error).__name__}: {close_error}', evidence) from error
            raise

    def _raw32(self, offset):
        return RECOVERY._load_mmio_u32(self.bar0, offset)

    def read32(self, offset):
        if type(offset) is not int or offset not in SCANNER.READ_OFFSETS:
            raise DoorbellZeroError(f'forbidden BAR5 read at {offset!r}')
        return self._raw32(offset)

    def _posting_barrier(self):
        value = self._raw32(RECOVERY.NBIO_CONFIG_MEMSIZE_OFFSET)
        expected = RECOVERY.resolve_expected_config_memsize()
        if value != expected:
            raise DoorbellZeroError(
                f'posting read is {value:#x}, expected {expected:#x}')
        return value

    def select(self, value):
        if type(value) is not int or value not in SCANNER.VALID_SELECTORS:
            raise DoorbellZeroError(f'forbidden selector value {value!r}')
        RECOVERY._store_mmio_u32(self.bar0, RECOVERY.GRBM_GFX_CNTL_OFFSET, value)
        self._selected = value
        self._posting_barrier()

    def _control_static_problem(self, operation, offset, value):
        prior = self._attempted_operations
        if self._selected != RECOVERY.HOST_KIQ_SELECTOR:
            return 'control write requires selector 9'
        if operation == 'enable-hqd-doorbell':
            if prior or offset != RECOVERY.CP_HQD_PQ_DOORBELL_OFFSET or \
                    value != DOORBELL_ENABLE:
                return 'forbidden control enable-hqd-doorbell'
        elif operation == 'enable-global-pq-doorbell':
            if (prior != ['enable-hqd-doorbell'] or
                    self._operations != ['enable-hqd-doorbell'] or
                    offset != RECOVERY.CP_PQ_STATUS_OFFSET or value != PQ_GATE):
                return 'forbidden control enable-global-pq-doorbell'
        elif operation == 'disable-global-pq-doorbell':
            if (not prior or prior[-1] == operation or prior[0] !=
                    'enable-hqd-doorbell' or
                    offset != RECOVERY.CP_PQ_STATUS_OFFSET or value != 0):
                return 'forbidden control disable-global-pq-doorbell'
        elif operation == 'disable-hqd-doorbell':
            if (not prior or prior[-1] != 'disable-global-pq-doorbell' or
                    operation in prior or
                    offset != RECOVERY.CP_HQD_PQ_DOORBELL_OFFSET or value != 0):
                return 'forbidden control disable-hqd-doorbell'
        else:
            return 'forbidden control operation'
        return None

    def _control_readback_problem(self, operation, observed, posted):
        if operation == 'enable-hqd-doorbell':
            if observed != DOORBELL_HIT:
                return 'HQD doorbell preimage changed'
            if not posted & DOORBELL_ENABLE or posted & ~DOORBELL_ALLOWED:
                return 'HQD doorbell enable did not read back'
        elif operation == 'enable-global-pq-doorbell':
            if observed != 0:
                return 'global PQ doorbell preimage changed'
            if posted != PQ_GATE:
                return 'global PQ doorbell enable did not read back'
        elif operation == 'disable-global-pq-doorbell':
            if observed & ~PQ_GATE:
                return 'global PQ doorbell close preimage changed'
            if posted != 0:
                return 'global PQ doorbell close did not read back'
        elif operation == 'disable-hqd-doorbell':
            if observed & ~DOORBELL_ALLOWED:
                return 'HQD doorbell close preimage changed'
            if posted & ~DOORBELL_HIT:
                return 'HQD doorbell close did not read back'
        return None

    def write_control(self, operation, offset, value):
        row = {'sequence': len(self.write_log), 'operation': operation,
               'offset': offset, 'value': value, 'selector': self._selected,
               'attempted': True, 'store_completed': False, 'completed': False}
        self.write_log.append(row)
        try:
            problem = self._control_static_problem(operation, offset, value)
            if problem:
                raise DoorbellZeroError(problem)
            self._attempted_operations.append(operation)
            observed = self._raw32(offset)
            row['observed_before'] = observed
            if observed == 0xffffffff:
                raise DoorbellZeroError('control preimage is inaccessible/all-ones')
            preimage_problem = self._control_readback_problem(
                operation, observed, value)
            if preimage_problem and 'preimage' in preimage_problem:
                raise DoorbellZeroError(preimage_problem)
            RECOVERY._store_mmio_u32(self.bar0, offset, value)
            row['store_completed'] = True
            posted = self._raw32(offset)
            row['posted'] = posted
            problem = self._control_readback_problem(operation, observed, posted)
            if problem:
                raise DoorbellZeroError(problem)
            self._operations.append(operation)
            row['completed'] = True
            return posted
        except BaseException as error:
            row['error'] = type(error).__name__ + ': ' + str(error)
            raise

    def ring_doorbell64(self, index, value):
        if self.doorbell_log:
            raise DoorbellZeroError('doorbell store was already attempted')
        if type(index) is not int or type(value) is not int or index != 0 or value != 0:
            raise DoorbellZeroError('forbidden doorbell index/value')
        if (self._selected != RECOVERY.HOST_KIQ_SELECTOR or
                self._operations != ['enable-hqd-doorbell',
                                     'enable-global-pq-doorbell']):
            raise DoorbellZeroError('doorbell gates are not enabled')
        row = {'sequence': 0, 'index': 0, 'offset': 0, 'value': 0,
               'width_bits': 64, 'attempted': True,
               'store_completed': False, 'completed': False}
        self.doorbell_log.append(row)
        try:
            RECOVERY._store_mmio_u64(self.bar2, 0, 0)
            row['store_completed'] = True
            row['barrier'] = self._posting_barrier()
            row['completed'] = True
            return row['barrier']
        except BaseException as error:
            row['error'] = type(error).__name__ + ': ' + str(error)
            raise

    def metadata(self):
        if self.region is None or self.bar2_region is None:
            raise DoorbellZeroError('VFIO region metadata is unavailable')
        return {
            'regions': {
                '2': {'index': self.bar2_region.index,
                      'size': self.bar2_region.size,
                      'offset': self.bar2_region.offset,
                      'userspace_mapped_bytes': BAR2_MAP_SIZE},
                '5': {'index': self.region.index, 'size': self.region.size,
                      'offset': self.region.offset,
                      'userspace_mapped_bytes': self.region.size}},
            'userspace_mapping': 'BAR2-eight-bytes-and-BAR5-only',
            'userspace_writes': 'fixed-doorbell-zero-transaction-only',
            'native_bar2_store_width_bits': 64,
            'kernel_vfio_lifecycle_configuration_activity': True,
        }


def _capture_scan(transport):
    try:
        return SCANNER.scan_device(transport)
    except SCANNER.IdleInspectionError as error:
        return error.evidence


def _scan_shape(scan, label):
    if (not isinstance(scan, dict) or len(scan.get('passes', [])) != 2 or
            scan['passes'][0] != scan['passes'][1] or
            scan.get('final_default') != {
                'attempted': True, 'completed': True, 'value': 0} or
            len(scan.get('selector_writes', [])) != 137 or
            any(row.get('completed') is not True
                for row in scan.get('selector_writes', []))):
        raise DoorbellZeroError(label + ' is incomplete or unstable')


def _exact_pre_scan(scan, expected):
    _scan_shape(scan, 'pre-scan')
    if scan['passes'] != expected['passes']:
        raise DoorbellZeroError('pre-scan does not match exact retained state')
    for observed in scan['passes']:
        values = observed['globals']
        if (values['cp_stat'] != 0 or values['cpc_busy'] != 0 or
                values['me_cntl'] & RECOVERY.CP_ME_HALT_MASK !=
                RECOVERY.CP_ME_HALT_MASK or
                values['mec_cntl'] & RECOVERY.CP_MEC_HALT_MASK !=
                RECOVERY.CP_MEC_HALT_MASK or
                values['pq_wptr_poll_cntl'] != 0 or values['pq_status'] != 0 or
                values['doorbell_range_lower'] != 0 or
                values['doorbell_range_upper'] != 0):
            raise DoorbellZeroError('pre-scan CP/doorbell gates are not closed')
        if (values['sdma0_f32_cntl'] != RECOVERY.SDMA_HALT_MASK or
                not values['sdma0_status'] & SCANNER.SDMA_STATUS_IDLE_MASK or
                values['sdma0_page_ib_cntl'] != 0x100 or
                values['sdma0_page_rb_cntl'] != 0x80840020):
            raise DoorbellZeroError('pre-scan SDMA/PAGE gates changed')
        for row in observed['compute']:
            if row['active'] != 0 or row['pq_doorbell_control'] & ~DOORBELL_HIT:
                raise DoorbellZeroError('pre-scan compute queue gate failed')
            if row['pq_doorbell_control'] & DOORBELL_ENABLE:
                raise DoorbellZeroError('pre-scan compute doorbell is enabled')
        target = next(row for row in observed['compute']
                      if row['selector'] == RECOVERY.HOST_KIQ_SELECTOR)
        if (target['pq_doorbell_control'] != DOORBELL_HIT or
                target['host_kiq'] != {
                    'dequeue': 0, 'rptr': 0, 'wptr_lo': 0x100, 'wptr_hi': 0}):
            raise DoorbellZeroError('pre-scan selector 9 state changed')


def _exact_post_scan(scan, expected):
    _scan_shape(scan, 'post-scan')
    for observed, reference in zip(scan['passes'], expected['passes']):
        changed = json.loads(json.dumps(reference))
        target = next(row for row in changed['compute']
                      if row['selector'] == RECOVERY.HOST_KIQ_SELECTOR)
        target['host_kiq']['wptr_lo'] = 0
        actual = next(row for row in observed['compute']
                      if row['selector'] == RECOVERY.HOST_KIQ_SELECTOR)
        if actual['pq_doorbell_control'] & ~DOORBELL_HIT:
            raise DoorbellZeroError('post-scan selector 9 doorbell gate is open')
        target['pq_doorbell_control'] = actual['pq_doorbell_control']
        if observed != changed:
            raise DoorbellZeroError('post-scan state changed outside selector 9 WPTR/HIT')
        if actual['host_kiq']['wptr_lo'] != 0 or \
                actual['host_kiq']['wptr_hi'] != 0:
            raise DoorbellZeroError('WPTR remained nonzero after doorbell zero')


def _select(transport, evidence, value, phase):
    row = {'sequence': len(evidence['control_selectors']), 'phase': phase,
           'value': value, 'attempted': True, 'completed': False}
    evidence['control_selectors'].append(row)
    try:
        transport.select(value)
        row['completed'] = True
    except BaseException as error:
        row['error'] = type(error).__name__ + ': ' + str(error)
        raise


def _control(transport, evidence, operation, offset, value):
    prior = len(getattr(transport, 'write_log', []))
    try:
        return transport.write_control(operation, offset, value)
    finally:
        log = getattr(transport, 'write_log', [])
        if evidence['writes'] is not log:
            evidence['writes'][:] = list(log)
        if len(evidence['writes']) < prior:
            raise DoorbellZeroError('control evidence regressed', evidence)


def _interim_sample(transport, evidence):
    row = {}
    evidence['interim_samples'].append(row)
    for name, offset in (
            ('active', RECOVERY.CP_HQD_ACTIVE_OFFSET),
            ('mec_cntl', RECOVERY.CP_MEC_CNTL_OFFSET),
            ('wptr_lo', RECOVERY.CP_HQD_PQ_WPTR_LO_OFFSET),
            ('wptr_hi', RECOVERY.CP_HQD_PQ_WPTR_HI_OFFSET)):
        try:
            row[name] = transport.read32(offset)
        except BaseException as error:
            row['error_field'] = name
            row['error'] = type(error).__name__ + ': ' + str(error)
            raise
        value = row[name]
        if type(value) is not int or value == 0xffffffff:
            raise DoorbellZeroError(f'interim {name} is inaccessible', evidence)
        if name == 'active' and value != 0:
            raise DoorbellZeroError('interim ACTIVE changed', evidence)
        if name == 'mec_cntl' and value & RECOVERY.CP_MEC_HALT_MASK != \
                RECOVERY.CP_MEC_HALT_MASK:
            raise DoorbellZeroError('interim MEC halt changed', evidence)
        if name == 'wptr_lo' and value not in (0, 0x100):
            raise DoorbellZeroError('interim WPTR_LO changed unexpectedly', evidence)
        if name == 'wptr_hi' and value != 0:
            raise DoorbellZeroError('interim WPTR_HI changed unexpectedly', evidence)
    return row


def execute_transaction(transport, expected_device, clock_ns=time.monotonic_ns):
    evidence = {
        'status': 'failed', 'authorizes_launch': False,
        'authorizes_recovery': False, 'authorizes_cleanup': False,
        'before': None, 'after': None, 'writes': [], 'doorbell_writes': [],
        'control_selectors': [], 'interim_samples': [],
        'timing': {'observation_budget_ns': OBSERVATION_BUDGET_NS,
                   'started_before_hqd_enable': True},
        'gate_close': {'global': {'attempted': False, 'completed': False},
                       'hqd': {'attempted': False, 'completed': False}},
        'final_default': {'attempted': False, 'completed': False, 'value': 0},
    }
    if hasattr(transport, 'write_log'): evidence['writes'] = transport.write_log
    if hasattr(transport, 'doorbell_log'):
        evidence['doorbell_writes'] = transport.doorbell_log
    selector_started = gate_mutation_started = False
    gate_start = None
    primary = None
    try:
        evidence['before'] = _capture_scan(transport)
        _exact_pre_scan(evidence['before'], expected_device)
        # A selector store may reach the device even if its posting read fails.
        # Take cleanup ownership before attempting the first control selector.
        selector_started = True
        _select(transport, evidence, RECOVERY.HOST_KIQ_SELECTOR,
                'doorbell-select-kiq')
        # This is an elapsed-time observation, not a real-time guarantee. Start
        # before the first ingress-enabling store so it covers every open-gate
        # operation and the finally cleanup.
        gate_start = clock_ns()
        gate_mutation_started = True
        _control(transport, evidence, 'enable-hqd-doorbell',
                 RECOVERY.CP_HQD_PQ_DOORBELL_OFFSET, DOORBELL_ENABLE)
        _control(transport, evidence, 'enable-global-pq-doorbell',
                 RECOVERY.CP_PQ_STATUS_OFFSET, PQ_GATE)
        try:
            transport.ring_doorbell64(0, 0)
        finally:
            log = getattr(transport, 'doorbell_log', [])
            if evidence['doorbell_writes'] is not log:
                evidence['doorbell_writes'][:] = list(log)
        deadline = gate_start + OBSERVATION_BUDGET_NS
        while True:
            row = _interim_sample(transport, evidence)
            if row['wptr_lo'] == 0 and row['wptr_hi'] == 0:
                break
            if clock_ns() >= deadline:
                primary = DoorbellZeroError(
                    'WPTR remained nonzero within bounded observation', evidence)
                break
    except BaseException as error:
        primary = error
    finally:
        cleanup_errors = []
        if gate_mutation_started:
            global_row = evidence['gate_close']['global']
            global_row['attempted'] = True
            try:
                _control(transport, evidence, 'disable-global-pq-doorbell',
                         RECOVERY.CP_PQ_STATUS_OFFSET, 0)
                global_row['completed'] = True
            except BaseException as error:
                global_row['error'] = type(error).__name__ + ': ' + str(error)
                cleanup_errors.append('global gate close: ' + str(error))
            if gate_start is not None:
                try:
                    elapsed = max(0, clock_ns() - gate_start)
                    evidence['gate_open_elapsed_ns'] = elapsed
                    evidence['timing']['through_global_close_ns'] = elapsed
                except BaseException as error:
                    evidence['timing']['global_close_clock_error'] = \
                        type(error).__name__ + ': ' + str(error)
                    cleanup_errors.append('global close clock: ' + str(error))
            hqd_row = evidence['gate_close']['hqd']
            hqd_row['attempted'] = True
            try:
                _control(transport, evidence, 'disable-hqd-doorbell',
                         RECOVERY.CP_HQD_PQ_DOORBELL_OFFSET, 0)
                hqd_row['completed'] = True
            except BaseException as error:
                hqd_row['error'] = type(error).__name__ + ': ' + str(error)
                cleanup_errors.append('HQD gate close: ' + str(error))
        if selector_started:
            evidence['final_default']['attempted'] = True
            try:
                _select(transport, evidence, 0, 'doorbell-final-default')
                evidence['final_default']['completed'] = True
            except BaseException as error:
                evidence['final_default']['error'] = \
                    type(error).__name__ + ': ' + str(error)
                cleanup_errors.append('selector restore: ' + str(error))
        if selector_started:
            try:
                evidence['after'] = _capture_scan(transport)
                if not cleanup_errors:
                    _exact_post_scan(evidence['after'], expected_device)
            except BaseException as error:
                cleanup_errors.append('post-scan: ' + str(error))
        if cleanup_errors:
            cleanup = '; '.join(cleanup_errors)
            primary = DoorbellZeroError(
                (str(primary) + '; ' if primary is not None else '') + cleanup,
                evidence)
    try:
        evidence['vfio_region'] = transport.metadata()
    except BaseException as error:
        if primary is None:
            primary = error
        else:
            primary = DoorbellZeroError(
                f'{primary}; metadata failed: {type(error).__name__}: {error}', evidence)
    if primary is not None:
        evidence['error'] = type(primary).__name__ + ': ' + str(primary)
        if isinstance(primary, DoorbellZeroError) and primary.evidence is evidence:
            raise primary
        raise DoorbellZeroError(type(primary).__name__ + ': ' + str(primary), evidence)
    evidence['status'] = 'doorbell-wptr-cleared-nonauthorizing'
    return evidence


def preparation_result_errors(value):
    errors = []
    if (value.get('status') != 'failed' or value.get('boot_id') != BOOT_ID or
            value.get('run_id') != RUN_ID or
            value.get('authorizes_launch') is not False or
            value.get('authorizes_recovery') is not False or
            value.get('authorizes_cleanup') is not False or
            value.get('device_error') != 'WPTR posting/readback failed'):
        errors.append('preparation identity/status')
    transaction = value.get('transaction', {})
    try:
        writes = transaction['writes']
        if (len(writes) != 3 or writes[0]['posted'] != 0x100 or
                writes[1]['posted'] != 0x80840020 or
                writes[2]['observed_before'] != 0x100 or
                writes[2]['value'] != 0 or writes[2]['posted'] != 0x100 or
                writes[2]['store_completed'] is not True or
                writes[2]['completed'] is not False or
                transaction['after']['passes'][0] !=
                transaction['after']['passes'][1]):
            errors.append('preparation exact transaction')
    except (KeyError, IndexError, TypeError):
        errors.append('preparation transaction missing')
    return errors


def collect_preflight(vm, evidence_dir, expected_tool_source_sha256,
                      journal_cursor=None):
    vm = Path(vm).resolve()
    preparation_proof = PREPARATION.collect_preflight(
        vm, evidence_dir, PREPARATION_SOURCE_SHA256, journal_cursor)
    path = vm/'run/retained-kiq-preparations'/f'{BOOT_ID}-{RUN_ID}.json'
    raw = path.read_bytes()
    value = json.loads(raw)
    return {
        'preparation_proof': preparation_proof,
        'preparation_errors': PREPARATION.preflight_errors(preparation_proof),
        'preparation_result_sha256': _sha256(raw),
        'preparation_result_errors': preparation_result_errors(value),
        'preparation_result': value,
        'tool_source_sha256': _sha256(Path(__file__).read_bytes()),
        'expected_tool_source_sha256': expected_tool_source_sha256,
        'loaded_preparation_source_sha256': LOADED_PREPARATION_SOURCE_SHA256,
        'current_preparation_source_sha256': _sha256(
            Path(__file__).with_name('prepare-retained-kiq.py').read_bytes()),
        'loaded_ctypes_sha256': LOADED_CTYPES_SHA256,
        'current_ctypes_sha256': _sha256(CTYPES_PATH.read_bytes()),
        'loaded_ctypes_build_id': LOADED_CTYPES_BUILD_ID,
        'current_ctypes_build_id': _elf_build_id(CTYPES_PATH),
    }


def preflight_errors(proof):
    errors = ['preparation: ' + error for error in
              proof.get('preparation_errors', ['preparation proof missing'])]
    if (proof.get('preparation_result_sha256') != PREPARATION_RESULT_SHA256 or
            proof.get('preparation_result_errors') != []):
        errors.append('exact retained preparation result')
    if (proof.get('loaded_preparation_source_sha256') != PREPARATION_SOURCE_SHA256 or
            proof.get('current_preparation_source_sha256') != PREPARATION_SOURCE_SHA256):
        errors.append('preparation source changed')
    if proof.get('tool_source_sha256') != proof.get('expected_tool_source_sha256'):
        errors.append('tool source changed')
    if (proof.get('loaded_ctypes_sha256') != CTYPES_SHA256 or
            proof.get('current_ctypes_sha256') != CTYPES_SHA256 or
            proof.get('loaded_ctypes_build_id') != CTYPES_BUILD_ID or
            proof.get('current_ctypes_build_id') != CTYPES_BUILD_ID):
        errors.append('_ctypes native-store dependency changed')
    return errors


def postflight_errors(before, after):
    errors = preflight_errors(after)
    errors.extend('preparation postflight: ' + error for error in
                  PREPARATION.postflight_errors(
                      before.get('preparation_proof', {}),
                      after.get('preparation_proof', {})))
    for key in ('preparation_result_sha256', 'preparation_result_errors',
                'tool_source_sha256', 'expected_tool_source_sha256',
                'loaded_preparation_source_sha256',
                'current_preparation_source_sha256',
                'loaded_ctypes_sha256', 'current_ctypes_sha256',
                'loaded_ctypes_build_id', 'current_ctypes_build_id'):
        if before.get(key) != after.get(key): errors.append(key + ' changed')
    return errors


def run_transaction(preflight_reader, transport_factory, postflight_reader,
                    output, expected_device=None, clock_ns=time.monotonic_ns):
    output = Path(output); attempt = output.with_suffix('.attempt.json')
    if output.exists() or attempt.exists():
        raise FileExistsError('retained KIQ doorbell-zero path was already consumed')
    base = {'schema': 1, 'kind': 'retained-kiq-doorbell-zero',
            'status': 'failed', 'authorizes_launch': False,
            'authorizes_recovery': False, 'authorizes_cleanup': False,
            'boot_id': BOOT_ID, 'run_id': RUN_ID}
    try:
        preflight = preflight_reader()
    except BaseException as error:
        result = dict(base, error='preflight collection: ' + str(error),
                      created_epoch=time.time())
        OBSERVER._write_once(output, result)
        raise DoorbellZeroError(result['error'], result) from error
    errors = preflight_errors(preflight)
    if errors:
        result = dict(base, preflight=preflight,
                      error='pre-VFIO ' + ', '.join(errors),
                      created_epoch=time.time())
        OBSERVER._write_once(output, result)
        raise DoorbellZeroError(result['error'], result)
    if expected_device is None:
        expected_device = preflight['preparation_result']['transaction']['after']
    OBSERVER._write_once(
        attempt, dict(base, status='device-open-attempted',
                      created_epoch=time.time()))
    transaction = inner_error = device_error = None
    try:
        with transport_factory() as transport:
            try:
                transaction = execute_transaction(
                    transport, expected_device, clock_ns)
            except BaseException as error:
                inner_error = error
                if isinstance(error, DoorbellZeroError):
                    transaction = error.evidence
                raise
    except BaseException as error:
        if (inner_error is not None and error is not inner_error and
                str(inner_error) not in str(error)):
            device_error = DoorbellZeroError(
                f'{inner_error}; close failed: {type(error).__name__}: {error}',
                transaction)
        else:
            device_error = error
    try:
        postflight = postflight_reader(
            preflight['preparation_proof']['scanner_proof']['base']['journal_cursor'])
        post_errors = postflight_errors(preflight, postflight)
    except BaseException as error:
        postflight = {'collection_error': type(error).__name__ + ': ' + str(error)}
        post_errors = ['postflight collection failed']
    result = dict(base, preflight=preflight, transaction=transaction,
                  postflight=postflight, created_epoch=time.time())
    if device_error is not None: result['device_error'] = str(device_error)
    if post_errors: result['postflight_errors'] = post_errors
    if device_error is not None or post_errors:
        result['error'] = '; '.join(filter(None, (
            'device: ' + str(device_error) if device_error else '',
            'postflight: ' + ', '.join(post_errors) if post_errors else '')))
        OBSERVER._write_once(output, result)
        raise DoorbellZeroError(result['error'], result)
    result['status'] = 'completed-nonauthorizing'
    OBSERVER._write_once(output, result)
    return result


def prepare_once(vm, evidence_dir, output, expected_tool_source_sha256):
    vm, evidence_dir, output = map(lambda value: Path(value).resolve(),
                                   (vm, evidence_dir, output))
    expected = vm/'run/retained-kiq-doorbell-zero'/f'{BOOT_ID}-{RUN_ID}.json'
    if output != expected.resolve():
        raise DoorbellZeroError(f'output must be {expected}')
    lock = vm/'run/experiment.lock'; lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open('a') as owner:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return run_transaction(
            lambda: collect_preflight(vm, evidence_dir,
                                      expected_tool_source_sha256),
            DoorbellZeroTransport,
            lambda cursor: collect_preflight(
                vm, evidence_dir, expected_tool_source_sha256, cursor),
            output)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vm-dir', required=True, type=Path)
    parser.add_argument('--evidence-dir', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--expected-source-sha256', required=True)
    args = parser.parse_args(argv)
    try:
        if not re.fullmatch(r'[0-9a-f]{64}', args.expected_source_sha256):
            raise DoorbellZeroError('expected source SHA-256 is invalid')
        result = prepare_once(args.vm_dir, args.evidence_dir, args.output,
                              args.expected_source_sha256)
    except BaseException as error:
        print(json.dumps({'status': 'failed', 'authorizes_launch': False,
                          'authorizes_recovery': False,
                          'authorizes_cleanup': False,
                          'error': type(error).__name__ + ': ' + str(error)},
                         indent=2))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True)); return 0


if __name__ == '__main__':
    sys.exit(main())
