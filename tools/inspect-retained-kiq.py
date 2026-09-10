#!/usr/bin/env python3
"""Capture retained candidate-175 host-KIQ scratch without authorizing reuse."""
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
import struct
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
LOADED_RECOVERY_SOURCE_SHA256 = hashlib.sha256(
    Path(__file__).with_name('vfio-recover.py').read_bytes()).hexdigest()

BOOT_ID = '5d6f45d0-4384-4340-b819-7751bc26ebb3'
RUN_ID = '1a065e4f5f674cc0a26d4e9dbdf59649'
BUILD_ID = '693734a021524bd29dd71df774d917a3'
RECOVERY_ID = 'e503b2ca63db4e11a21494d1841dca24'
SOURCE_COMMIT = '7db5a73d0ec830f31d80c4975e7a36c2f017326a'
HISTORICAL_SOURCE_SHA256 = (
    'b0ca780828e615d6ad5d17b360d739c1619e279e4f0e37077eb0c79ecb697298')
CURRENT_RECOVERY_SOURCE_SHA256 = (
    'd4e4994885ad8300b89f96ae78a7098e872b64055cc8123146959d2a66c39e21')

PINNED_HASHES = {
    'ledger': '69b8e1464a6866d3da2518e5db7222b0d557e0eb7f3ac3c27ebffbec139b9d15',
    'manifest': '1697d2437bca3429e0711a9de9ca379853eb0e3788dae9e0e22ce5cf8fccb3e6',
    'recovery': '117d2d4cea6b007c49fc797af7c64ef78bfeb4da8acebaa245abd945372e3e4d',
    'receipt': '9cf80653e198faa09c6f4da456e8495e07a045015c6ac0b64a7561ffbfc85fc7',
}

PINNED_ARCHIVE_INVENTORY = (
    {'name': 'agent-server-events.jsonl', 'sha256': '1e03f4af67e80981c642d41d1dfdec997117451a1ebdcd09938b6fdeea64d202'},
    {'name': 'events.jsonl', 'sha256': 'db13ddb6f382181e370b3f8955d58023678e6cfde060ab19d789d4affc114d21'},
    {'name': 'host-after.json', 'sha256': 'd2d3b118bda837c44c8ea878f7af089e6e5c5767e16912752b92b0f763a0a8ff'},
    {'name': 'host-before.json', 'sha256': 'd2d3b118bda837c44c8ea878f7af089e6e5c5767e16912752b92b0f763a0a8ff'},
    {'name': 'host-kernel-messages.json', 'sha256': '3d248d092379c6e45b2209144dca3c3f5f9e02339424f2bc03a87350b59dda06'},
    {'name': 'manifest.json', 'sha256': PINNED_HASHES['manifest']},
    {'name': 'recovery-reservation.json', 'sha256': '3a9bbc4abeb09825eb05e158beb7a3b1fdfa88f959107d02b6b6c2e7c082787e'},
    {'name': 'recovery.json', 'sha256': PINNED_HASHES['recovery']},
    {'name': 'running-identity.json', 'sha256': 'f5045f3332b38375d0696b565db98ad78303a1a7f0de4d391edfd1d18607c628'},
    {'name': 'serial.txt', 'sha256': 'cdcaacedae79a550c52f83c0a7d402a25ffb59930f84d44471e1839182db0da0'},
    {'name': 'shutdown.json', 'sha256': 'a776f6e3127da7a99028e7bd42c1aaef1399abc9f282bb5eac3a1060a5964735'},
    {'name': 'supervision.json', 'sha256': 'c00a02e0cabf19c659206aba703e21dc29261619fb5cba3c47b6712eb8936315'},
    {'name': 'verdict.json', 'sha256': '237a208fc1e10fdac1af8109f5487e10e4539442ead22883079f6d3af28a6904'},
)
PINNED_ARCHIVE_DIGEST = (
    'c3bd5a998b093eacc26568f1ab332569bd5089dd43a26664e15dd5811a24a3ac')

DEVICE = '0000:7b:00.0'
GROUP = '31'
CANONICAL_DEVICE = '/sys/devices/pci0000:00/0000:00:08.1/0000:7b:00.0'
CANONICAL_PARENT = '/sys/devices/pci0000:00/0000:00:08.1'
KERNEL_RELEASE = '7.2.3-1-cachyos-bore'
VFIO_MODULE_SHA256 = 'd0bfbf478f892d57eb6f42a0d5d51f20a611bc7ee538643cc820932167686381'
VFIO_MODULE_BUILD_ID = 'a002a05ce4a09429cf6bc9906d1893ec7f304e81'
EXPECTED_SIBLINGS = {
    '0000:7b:00.0': {'device': '1002:13c0', 'driver': 'vfio-pci', 'iommu_group': '31'},
    '0000:7b:00.1': {'device': '1002:1640', 'driver': 'snd_hda_intel', 'iommu_group': '32'},
    '0000:7b:00.2': {'device': '1022:1649', 'driver': 'ccp', 'iommu_group': '33'},
    '0000:7b:00.3': {'device': '1022:15b6', 'driver': 'xhci_hcd', 'iommu_group': '34'},
    '0000:7b:00.4': {'device': '1022:15b7', 'driver': 'xhci_hcd', 'iommu_group': '35'},
    '0000:7b:00.6': {'device': '1022:15e3', 'driver': None, 'iommu_group': '36'},
}
EXPECTED_RESET_DOMAIN = {
    'canonical_parent': CANONICAL_PARENT,
    'domain_bus_device': '0000:7b:00',
    'functions': ['0', '1', '2', '3', '4', '6'],
    'canonical_devices': {
        bdf: f'{CANONICAL_PARENT}/{bdf}' for bdf in EXPECTED_SIBLINGS
    },
    'physical_slot': {bdf: None for bdf in EXPECTED_SIBLINGS},
}

VRAM_BAR_SIZE = 0x10000000
READ_RANGES = (
    ('ring', 0x0f100000, 0x10000),
    ('mqd', 0x0f110000, 0x800),
    ('pointers', 0x0f111000, 0x10),
    ('eop', 0x0f112000, 0x1000),
    ('fence', 0x0f113000, 0x4),
)
RANGES_BY_NAME = {name: (offset, size) for name, offset, size in READ_RANGES}
RING_USED_DWORDS = 0x100
NOP = 0xffff1000
FB_BASE = 0xf400000000

VFIO_GET_API_VERSION = RECOVERY.VFIO_GET_API_VERSION
VFIO_CHECK_EXTENSION = RECOVERY.VFIO_CHECK_EXTENSION
VFIO_API_VERSION = RECOVERY.VFIO_API_VERSION
VFIO_TYPE1_IOMMU = RECOVERY.VFIO_TYPE1_IOMMU
VFIO_GROUP_GET_STATUS = RECOVERY.VFIO_GROUP_GET_STATUS
VFIO_GROUP_SET_CONTAINER = RECOVERY.VFIO_GROUP_SET_CONTAINER
VFIO_GROUP_UNSET_CONTAINER = RECOVERY.VFIO_GROUP_UNSET_CONTAINER
VFIO_GROUP_GET_DEVICE_FD = RECOVERY.VFIO_GROUP_GET_DEVICE_FD
VFIO_SET_IOMMU = RECOVERY.VFIO_SET_IOMMU
VFIO_DEVICE_GET_REGION_INFO = RECOVERY.VFIO_DEVICE_GET_REGION_INFO
VFIO_GROUP_FLAGS_VIABLE = RECOVERY.VFIO_GROUP_FLAGS_VIABLE
VFIO_REGION_INFO_FLAG_READ = RECOVERY.VFIO_REGION_INFO_FLAG_READ
VFIO_REGION_INFO_FLAG_WRITE = RECOVERY.VFIO_REGION_INFO_FLAG_WRITE
VFIO_REGION_INFO_FLAG_MMAP = RECOVERY.VFIO_REGION_INFO_FLAG_MMAP
VFIO_PCI_BAR0_REGION_INDEX = RECOVERY.VFIO_PCI_BAR0_REGION_INDEX
VfioGroupStatus = RECOVERY.VfioGroupStatus
VfioRegionInfo = RECOVERY.VfioRegionInfo
ioctl = RECOVERY.ioctl


class ObserverError(RuntimeError):
    def __init__(self, message, evidence=None):
        super().__init__(message)
        self.evidence = evidence or {}


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _put32(image, offset, value):
    struct.pack_into('<I', image, offset, value & 0xffffffff)


def expected_images(sequence):
    """Reconstruct the immutable 7db5a73 host-KIQ input image."""
    ring_addr = FB_BASE + RANGES_BY_NAME['ring'][0]
    mqd_addr = FB_BASE + RANGES_BY_NAME['mqd'][0]
    rptr_addr = FB_BASE + RANGES_BY_NAME['pointers'][0]
    wptr_addr = FB_BASE + 0x0f111008
    eop_addr = FB_BASE + RANGES_BY_NAME['eop'][0]
    fence_addr = FB_BASE + RANGES_BY_NAME['fence'][0]
    ring = bytearray(struct.pack('<I', NOP) * (RANGES_BY_NAME['ring'][1] // 4))
    struct.pack_into('<6I', ring, 0, 0xC004A300, 0x30000000, 0x400, 0, 0, 0)
    struct.pack_into('<5I', ring, 24, 0xC0033700, 0x00100500,
                     fence_addr & 0xffffffff, fence_addr >> 32, sequence)
    mqd = bytearray(RANGES_BY_NAME['mqd'][1])
    _put32(mqd, 0x000, 0xC0310800)
    _put32(mqd, 0x02C, 1)
    for offset in (0x05C, 0x060, 0x068, 0x06C):
        _put32(mqd, offset, 0xffffffff)
    _put32(mqd, 0x080, 3)
    _put32(mqd, 0x200, mqd_addr & 0xfffffffc)
    _put32(mqd, 0x204, mqd_addr >> 32)
    _put32(mqd, 0x208, 1)
    _put32(mqd, 0x210, 0x0BE05300)
    _put32(mqd, 0x220, (ring_addr >> 8) & 0xffffffff)
    _put32(mqd, 0x224, ring_addr >> 40)
    _put32(mqd, 0x22C, rptr_addr & 0xfffffffc)
    _put32(mqd, 0x230, (rptr_addr >> 32) & 0xffff)
    _put32(mqd, 0x234, wptr_addr & 0xfffffffc)
    _put32(mqd, 0x238, (wptr_addr >> 32) & 0xffff)
    _put32(mqd, 0x23C, 0x40000000)
    _put32(mqd, 0x244, 0xD130060D)
    _put32(mqd, 0x254, 0x00300000)
    _put32(mqd, 0x288, 0x100)
    _put32(mqd, 0x294, (eop_addr >> 8) & 0xffffffff)
    _put32(mqd, 0x298, eop_addr >> 40)
    _put32(mqd, 0x29C, 6)
    return bytes(ring), bytes(mqd)


class Bar0ReadTransport:
    """Map only BAR0 with PROT_READ; userspace exposes no mutation operation."""
    def __init__(self, vfio_root=Path('/dev/vfio')):
        self.root = Path(vfio_root)
        self.container_fd = self.group_fd = self.device_fd = None
        self.container_set = False
        self.bar0 = None
        self.region = None

    def __enter__(self):
        primary = None
        try:
            self.container_fd = os.open(self.root/'vfio', os.O_RDWR | os.O_CLOEXEC)
            if ioctl(self.container_fd, VFIO_GET_API_VERSION) != VFIO_API_VERSION:
                raise ObserverError('unsupported VFIO API version')
            if ioctl(self.container_fd, VFIO_CHECK_EXTENSION, VFIO_TYPE1_IOMMU) <= 0:
                raise ObserverError('VFIO type1 IOMMU unavailable')
            self.group_fd = os.open(self.root/GROUP, os.O_RDWR | os.O_CLOEXEC)
            status = VfioGroupStatus(ctypes.sizeof(VfioGroupStatus), 0)
            ioctl(self.group_fd, VFIO_GROUP_GET_STATUS, ctypes.byref(status))
            if not status.flags & VFIO_GROUP_FLAGS_VIABLE:
                raise ObserverError('VFIO group is not viable')
            container = ctypes.c_int(self.container_fd)
            ioctl(self.group_fd, VFIO_GROUP_SET_CONTAINER, ctypes.byref(container))
            self.container_set = True
            ioctl(self.container_fd, VFIO_SET_IOMMU, VFIO_TYPE1_IOMMU)
            name = ctypes.create_string_buffer(DEVICE.encode() + b'\0')
            self.device_fd = ioctl(self.group_fd, VFIO_GROUP_GET_DEVICE_FD,
                                   ctypes.cast(name, ctypes.c_void_p))
            region = VfioRegionInfo(ctypes.sizeof(VfioRegionInfo), 0,
                                    VFIO_PCI_BAR0_REGION_INDEX, 0, 0, 0)
            ioctl(self.device_fd, VFIO_DEVICE_GET_REGION_INFO, ctypes.byref(region))
            needed = VFIO_REGION_INFO_FLAG_READ | VFIO_REGION_INFO_FLAG_MMAP
            if region.size != VRAM_BAR_SIZE or region.flags & needed != needed:
                raise ObserverError('BAR0 is not the exact readable mapping')
            self.region = region
            self.bar0 = mmap.mmap(self.device_fd, region.size, flags=mmap.MAP_SHARED,
                                  prot=mmap.PROT_READ, offset=region.offset)
            return self
        except BaseException as error:
            primary = error
            try:
                self.close()
            except BaseException as close_error:
                raise ObserverError(
                    f'{type(error).__name__}: {error}; close failed: '
                    f'{type(close_error).__name__}: {close_error}') from error
            raise primary

    def close(self):
        errors = []
        if self.bar0 is not None:
            try:
                self.bar0.close()
            except BaseException as error:
                errors.append('BAR0 unmap: ' + type(error).__name__ + ': ' + str(error))
            self.bar0 = None
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
            raise ObserverError('; '.join(errors))

    def __exit__(self, kind, error, traceback):
        try:
            self.close()
        except BaseException as close_error:
            if error is not None:
                evidence = error.evidence if isinstance(error, ObserverError) else None
                raise ObserverError(
                    f'{type(error).__name__}: {error}; close failed: '
                    f'{type(close_error).__name__}: {close_error}', evidence) from error
            raise

    def read_range(self, name, offset, size):
        if type(name) is not str or RANGES_BY_NAME.get(name) != (offset, size):
            raise ObserverError(f'forbidden BAR0 read: {name!r} {offset!r} {size!r}')
        if self.bar0 is None:
            raise ObserverError('BAR0 is not mapped')
        return bytes(self.bar0[offset:offset + size])

    def metadata(self):
        if self.region is None:
            raise ObserverError('BAR0 region metadata is unavailable')
        return {'index': self.region.index, 'size': self.region.size,
                'offset': self.region.offset,
                'region_read_capable': bool(
                    self.region.flags & VFIO_REGION_INFO_FLAG_READ),
                'region_write_capable': bool(
                    self.region.flags & VFIO_REGION_INFO_FLAG_WRITE),
                'region_mmap_capable': bool(
                    self.region.flags & VFIO_REGION_INFO_FLAG_MMAP),
                'userspace_mapping': 'BAR0-only',
                'userspace_mapping_protection': 'read-only',
                'userspace_mutation_methods': False,
                'kernel_vfio_lifecycle_configuration_activity': True}


def observe_device(transport):
    evidence = {'status': 'failed', 'authorizes_launch': False,
                'authorizes_recovery': False, 'authorizes_cleanup': False,
                'passes': [[], []]}
    try:
        raw_passes = []
        for pass_index in range(2):
            values = {}
            raw_passes.append(values)
            for name, offset, size in READ_RANGES:
                data = transport.read_range(name, offset, size)
                if type(data) is not bytes or len(data) != size:
                    raise ObserverError(f'{name} capture has the wrong size', evidence)
                values[name] = data
                evidence['passes'][pass_index].append({
                    'name': name, 'offset': offset, 'size': size,
                    'sha256': _sha256(data), 'data_hex': data.hex(),
                })
        evidence['ranges'] = []
        for name, offset, size in READ_RANGES:
            first, second = raw_passes[0][name], raw_passes[1][name]
            evidence['ranges'].append({
                'name': name, 'offset': offset, 'size': size,
                'passes': [
                    {'sha256': _sha256(first), 'data_hex': first.hex()},
                    {'sha256': _sha256(second), 'data_hex': second.hex()},
                ], 'stable': first == second,
            })
            if first != second:
                raise ObserverError(f'{name} changed between capture passes', evidence)
        ring = raw_passes[0]['ring']
        sequence = struct.unpack_from('<I', ring, 10 * 4)[0]
        expected_ring, expected_mqd = expected_images(sequence)
        pointers = raw_passes[0]['pointers']
        report = struct.unpack_from('<I', pointers, 0)[0]
        stored_wptr = struct.unpack_from('<Q', pointers, 8)[0]
        fence = struct.unpack('<I', raw_passes[0]['fence'])[0]
        ring_exact = sequence != 0 and ring == expected_ring
        evidence['analysis'] = {
            'sequence': sequence, 'ring_exact': ring_exact,
            'mqd_exact': raw_passes[0]['mqd'] == expected_mqd,
            'stored_wptr': stored_wptr, 'stored_wptr_expected': RING_USED_DWORDS,
            'current_report': report, 'current_fence': fence,
            'report_is_current_observation_only': True,
            'fence_matches_sequence': sequence != 0 and fence == sequence,
            'aggregate_sha256': _sha256(b''.join(
                raw_passes[0][name] for name, _, _ in READ_RANGES)),
        }
        evidence['vfio_region'] = transport.metadata()
        evidence['status'] = 'observed'
        if evidence['analysis']['fence_matches_sequence']:
            evidence['interpretation'] = (
                'retained-fence-matches-sequence'
                if (ring_exact and evidence['analysis']['mqd_exact'] and
                    stored_wptr == RING_USED_DWORDS)
                else 'scratch-identity-inconsistent')
        else:
            evidence['interpretation'] = 'inconclusive'
        evidence['historical_receipt_unchanged'] = True
        return evidence
    except BaseException as error:
        if isinstance(error, ObserverError) and error.evidence is evidence:
            raise
        raise ObserverError(type(error).__name__ + ': ' + str(error), evidence) from error


def _read(path):
    return Path(path).read_text().strip()


def _siblings():
    base = Path('/sys/bus/pci/devices')
    result = {}
    for path in sorted(base.glob('0000:7b:*')):
        try:
            vendor = int((path/'vendor').read_text().strip(), 16)
            device = int((path/'device').read_text().strip(), 16)
            group = (path/'iommu_group').resolve(strict=True).name
            try:
                driver = (path/'driver').resolve(strict=True).name
            except OSError:
                driver = None
        except (OSError, ValueError) as error:
            raise ObserverError('cannot establish reset-domain siblings: ' + str(error))
        result[path.name] = {'device': f'{vendor:04x}:{device:04x}',
                             'driver': driver, 'iommu_group': group}
    return result


def _reset_domain():
    base = Path('/sys/bus/pci/devices')
    paths = sorted(base.glob('0000:7b:*'))
    return {
        'canonical_parent': str((base/DEVICE).resolve(strict=True).parent),
        'domain_bus_device': DEVICE.rsplit('.', 1)[0],
        'functions': [path.name.rsplit('.', 1)[1] for path in paths],
        'canonical_devices': {path.name: str(path.resolve(strict=True)) for path in paths},
        'physical_slot': {
            path.name: ((path/'physical_slot').read_text().strip()
                        if (path/'physical_slot').exists() else None)
            for path in paths
        },
    }


def _active_units():
    result = subprocess.run([
        'systemctl', '--user', 'list-units', '--all', '--plain', '--no-legend',
        'rgpu-launch-*', 'rgpu-serial-*', 'rgpu-deadline-*'],
        text=True, capture_output=True, timeout=10)
    if result.returncode:
        raise ObserverError('cannot establish launch-unit state: ' + result.stderr.strip())
    return [line.split()[0] for line in result.stdout.splitlines() if line.split()]


def _sleep_inhibited():
    """Require one well-formed logind block inhibitor covering sleep and idle."""
    try:
        result = subprocess.run(
            ['busctl', '--system', '--json=short', 'call',
             'org.freedesktop.login1', '/org/freedesktop/login1',
             'org.freedesktop.login1.Manager', 'ListInhibitors'],
            text=True, capture_output=True, timeout=15, check=False)
        if result.returncode:
            return False
        payload = json.loads(result.stdout)
        if (payload.get('type') != 'a(ssssuu)' or type(payload.get('data')) is not list or
                len(payload['data']) != 1 or type(payload['data'][0]) is not list):
            return False
        matching = False
        for fields in payload['data'][0]:
            if (type(fields) is not list or len(fields) != 6 or
                    not all(isinstance(fields[i], str) for i in range(4)) or
                    not all(type(fields[i]) is int and 0 <= fields[i] < 1 << 32
                            for i in (4, 5))):
                return False
            what, _who, _why, mode = fields[:4]
            if mode == 'block' and len(what.split(':')) == 2 and \
                    set(what.split(':')) == {'sleep', 'idle'}:
                matching = True
        return matching
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, AttributeError):
        return False


def collect_host():
    host = RECOVERY.host_state()
    device = Path('/sys/bus/pci/devices') / DEVICE
    host.update({
        'canonical_device': str(device.resolve(strict=True)),
        'power_control': _read(device/'power/control'),
        'power_state': _read(device/'power_state'),
        'runtime_status': _read(device/'power/runtime_status'),
        'enable_count': _read(device/'enable'),
        'sleep_inhibited': _sleep_inhibited(),
        'watchdogs': {name: _read(Path('/proc/sys/kernel')/name)
                      for name in ('watchdog', 'nmi_watchdog', 'hardlockup_panic')},
        'residual_units': _active_units(), 'siblings': _siblings(),
        'reset_domain': _reset_domain(), 'kernel_release': os.uname().release,
        'vfio_module_sha256': _sha256((
            Path('/lib/modules')/os.uname().release/
            'kernel/drivers/vfio/pci/vfio-pci-core.ko.zst').read_bytes()),
        'vfio_module_build_id': (
            Path('/sys/module/vfio_pci_core/notes/.note.gnu.build-id')
            .read_bytes()[-20:].hex()),
    })
    return host


def _archive_inventory(directory):
    rows = []
    for path in sorted(Path(directory).iterdir(), key=lambda item: item.name):
        if not path.is_file() or path.is_symlink():
            raise ObserverError('candidate175 archive contains unsupported entries')
        rows.append({'name': path.name, 'sha256': _sha256(path.read_bytes())})
    digest = _sha256(json.dumps(rows, sort_keys=True,
                                separators=(',', ':')).encode())
    return rows, digest


def collect_preflight(vm, evidence_dir, expected_observer_source_sha256,
                      journal_cursor=None):
    vm, evidence_dir = Path(vm).resolve(), Path(evidence_dir).resolve()
    expected_evidence = (vm/'run/metal-008-175-bar0').resolve()
    if evidence_dir != expected_evidence:
        raise ObserverError(f'evidence directory must be {expected_evidence}')
    paths = {
        'ledger': vm/'run/used-gpu-boots'/f'{BOOT_ID}.json',
        'manifest': vm/'run/metal-008-175-manifest.json',
        'recovery': evidence_dir/'recovery.json',
        'receipt': vm/'run/vfio-recovery'/BOOT_ID/f'{RUN_ID}.json',
    }
    blobs = {name: path.read_bytes() for name, path in paths.items()}
    parsed = {name: json.loads(blob) for name, blob in blobs.items()}
    inventory, archive_digest = _archive_inventory(evidence_dir)
    source = subprocess.run(
        ['git', '-C', str(Path(__file__).resolve().parents[1]), 'show',
         f'{SOURCE_COMMIT}:tools/vfio-recover.py'],
        capture_output=True, timeout=10)
    if source.returncode:
        raise ObserverError('cannot read historical recovery source')
    cursor_source = (parsed['receipt'].get('kernel_cursor_after')
                     if journal_cursor is None else journal_cursor)
    cursor, messages, faults = RECOVERY.kernel_updates(cursor_source)
    return {
        'boot_id': BOOT_ID, 'run_id': RUN_ID, 'host': collect_host(),
        'ledger': parsed['ledger'], 'ledger_sha256': _sha256(blobs['ledger']),
        'artifact_sha256': {name: _sha256(blob) for name, blob in blobs.items()},
        'archive_inventory': inventory, 'archive_digest': archive_digest,
        'manifest': parsed['manifest'], 'recovery': parsed['recovery'],
        'receipt': parsed['receipt'],
        'recovery_receipt_equal': parsed['recovery'] == parsed['receipt'],
        'historical_source_sha256': _sha256(source.stdout),
        'loaded_recovery_source_sha256': LOADED_RECOVERY_SOURCE_SHA256,
        'current_recovery_source_sha256': _sha256(
            Path(__file__).with_name('vfio-recover.py').read_bytes()),
        'observer_source_sha256': _sha256(Path(__file__).read_bytes()),
        'expected_observer_source_sha256': expected_observer_source_sha256,
        'journal_cursor': cursor, 'journal_messages': messages,
        'journal_faults': faults,
    }


def preflight_errors(proof):
    errors = []
    if (proof.get('boot_id'), proof.get('run_id')) != (BOOT_ID, RUN_ID):
        errors.append('pinned boot/run identity')
    if proof.get('artifact_sha256') != PINNED_HASHES:
        errors.append('exact evidence hashes')
    if (proof.get('archive_inventory') != list(PINNED_ARCHIVE_INVENTORY) or
            proof.get('archive_digest') != PINNED_ARCHIVE_DIGEST):
        errors.append('exact evidence archive')
    if proof.get('historical_source_sha256') != HISTORICAL_SOURCE_SHA256:
        errors.append('historical source hash')
    if (proof.get('loaded_recovery_source_sha256') != CURRENT_RECOVERY_SOURCE_SHA256 or
            proof.get('loaded_recovery_source_sha256') !=
            proof.get('current_recovery_source_sha256') or
            not re.fullmatch(r'[0-9a-f]{64}', str(
                proof.get('loaded_recovery_source_sha256', '')))):
        errors.append('loaded recovery helper source changed')
    if (proof.get('observer_source_sha256') !=
            proof.get('expected_observer_source_sha256')):
        errors.append('reviewed observer source hash')
    ledger = proof.get('ledger', {})
    launches = ledger.get('launches', []) if isinstance(ledger, dict) else []
    if (proof.get('ledger_sha256') != PINNED_HASHES['ledger'] or
            ledger.get('schema') != 2 or ledger.get('boot_id') != BOOT_ID or
            ledger.get('max_launches') != 3 or len(launches) != 2 or
            launches[-1].get('run_id') != RUN_ID):
        errors.append('exact latest ledger')
    manifest = proof.get('manifest', {})
    if (manifest.get('boot_id'), manifest.get('run_id'),
            manifest.get('build_id'), manifest.get('source_commit')) != (
                BOOT_ID, RUN_ID, BUILD_ID, SOURCE_COMMIT):
        errors.append('manifest identity')
    expected_recovery = (5, 'incomplete', False, BOOT_ID, RUN_ID, RECOVERY_ID)
    for name in ('recovery', 'receipt'):
        value = proof.get(name, {})
        observed = (value.get('schema'), value.get('status'),
                    value.get('authorizes_launch'), value.get('boot_id'),
                    value.get('prior_run_id'), value.get('recovery_id'))
        if observed != expected_recovery:
            errors.append(name + ' identity/incomplete status')
    if proof.get('recovery_receipt_equal') is not True:
        errors.append('recovery/receipt content equality')
    host = proof.get('host', {})
    for name in RECOVERY.validate_host_state(host, BOOT_ID):
        errors.append('host ' + name)
    if host.get('pci_command') != 3:
        errors.append('host PCI command')
    if host.get('canonical_device') != CANONICAL_DEVICE:
        errors.append('host canonical device')
    if ((host.get('power_control'), host.get('power_state'),
         host.get('runtime_status'), host.get('enable_count')) !=
            ('on', 'D0', 'active', '0')):
        errors.append('host power state')
    if host.get('sleep_inhibited') is not True:
        errors.append('host sleep inhibitor')
    if host.get('watchdogs') != {'watchdog': '1', 'nmi_watchdog': '1',
                                 'hardlockup_panic': '1'}:
        errors.append('host watchdogs')
    if host.get('residual_units') != []:
        errors.append('host residual launch units')
    if host.get('siblings') != EXPECTED_SIBLINGS:
        errors.append('host reset-domain siblings')
    if host.get('reset_domain') != EXPECTED_RESET_DOMAIN:
        errors.append('host reset-domain canonical identity')
    if (host.get('kernel_release') != KERNEL_RELEASE or
            host.get('vfio_module_sha256') != VFIO_MODULE_SHA256 or
            host.get('vfio_module_build_id') != VFIO_MODULE_BUILD_ID):
        errors.append('host VFIO module identity')
    if proof.get('journal_faults') != []:
        errors.append('host journal faults')
    messages = proof.get('journal_messages')
    if not isinstance(messages, list) or any(re.search(
            rf'(?:{re.escape(DEVICE)}[^\n]*\breset|\breset[^\n]*'
            rf'{re.escape(DEVICE)}|vfio[^\n]*\breset)', str(message), re.I)
            for message in messages):
        errors.append('host implicit reset messages')
    if not isinstance(proof.get('journal_cursor'), str) or not proof['journal_cursor']:
        errors.append('host journal cursor')
    if not re.fullmatch(r'[0-9a-f]{64}', str(proof.get('observer_source_sha256', ''))):
        errors.append('observer source identity')
    return errors


def postflight_errors(before, after):
    errors = preflight_errors(after)
    for key in ('host', 'ledger_sha256', 'artifact_sha256', 'archive_inventory',
                'archive_digest', 'historical_source_sha256',
                'loaded_recovery_source_sha256',
                'current_recovery_source_sha256',
                'observer_source_sha256', 'expected_observer_source_sha256'):
        if before.get(key) != after.get(key):
            errors.append(key + ' changed')
    return errors


def _write_once(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def run_observation(preflight_reader, transport_factory, postflight_reader, output):
    output = Path(output)
    attempt = output.with_suffix('.attempt.json')
    if output.exists() or attempt.exists():
        raise FileExistsError('retained-KIQ observation path was already consumed')
    base = {'schema': 1, 'kind': 'retained-host-kiq-observation',
            'status': 'failed', 'authorizes_launch': False,
            'authorizes_recovery': False, 'authorizes_cleanup': False,
            'boot_id': BOOT_ID, 'run_id': RUN_ID,
            'recovery_id': RECOVERY_ID}
    try:
        preflight = preflight_reader()
    except BaseException as error:
        result = dict(base, error='preflight collection: ' +
                      type(error).__name__ + ': ' + str(error),
                      created_epoch=time.time())
        _write_once(output, result)
        raise ObserverError(result['error'], result) from error
    errors = preflight_errors(preflight)
    if errors:
        result = dict(base, preflight=preflight,
                      error='pre-VFIO proof failed: ' + ', '.join(errors),
                      created_epoch=time.time())
        _write_once(output, result)
        raise ObserverError(result['error'], result)
    _write_once(attempt, dict(base, status='device-open-attempted',
                              observer_source_sha256=preflight['observer_source_sha256'],
                              created_epoch=time.time()))
    device = None
    device_error = None
    try:
        with transport_factory() as transport:
            device = observe_device(transport)
    except BaseException as error:
        device_error = error
        if isinstance(error, ObserverError) and error.evidence:
            device = error.evidence
    try:
        postflight = postflight_reader(preflight['journal_cursor'])
        post_errors = postflight_errors(preflight, postflight)
    except BaseException as error:
        postflight = {'collection_error': type(error).__name__ + ': ' + str(error)}
        post_errors = ['postflight collection failed']
    result = dict(base, preflight=preflight, device=device, postflight=postflight,
                  created_epoch=time.time())
    if device_error is not None:
        result['device_error'] = type(device_error).__name__ + ': ' + str(device_error)
    if post_errors:
        result['postflight_errors'] = post_errors
    if device_error is not None or post_errors:
        parts = []
        if device_error is not None:
            parts.append('device observation: ' + str(device_error))
        if post_errors:
            parts.append('postflight: ' + ', '.join(post_errors))
        result['error'] = '; '.join(parts)
        _write_once(output, result)
        raise ObserverError(result['error'], result)
    result['status'] = 'observed'
    _write_once(output, result)
    return result


def inspect_once(vm, evidence_dir, output, expected_observer_source_sha256):
    vm, evidence_dir, output = map(lambda value: Path(value).resolve(),
                                   (vm, evidence_dir, output))
    expected_parent = (vm/'run/retained-kiq-inspections').resolve()
    expected_name = f'{BOOT_ID}-{RUN_ID}.json'
    if output.parent != expected_parent or output.name != expected_name:
        raise ObserverError(f'output must be {expected_parent/expected_name}')
    lock = vm/'run/experiment.lock'
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open('a') as owner:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return run_observation(
            lambda: collect_preflight(
                vm, evidence_dir, expected_observer_source_sha256),
            Bar0ReadTransport,
            lambda cursor: collect_preflight(
                vm, evidence_dir, expected_observer_source_sha256, cursor), output)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vm-dir', type=Path, required=True)
    parser.add_argument('--evidence-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--expected-source-sha256', required=True)
    args = parser.parse_args(argv)
    try:
        if not re.fullmatch(r'[0-9a-f]{64}', args.expected_source_sha256):
            raise ObserverError('expected source SHA-256 must be 64 lowercase hex digits')
        result = inspect_once(args.vm_dir, args.evidence_dir, args.output,
                              args.expected_source_sha256)
    except BaseException as error:
        print(json.dumps({'status': 'failed', 'authorizes_launch': False,
                          'authorizes_recovery': False,
                          'error': type(error).__name__ + ': ' + str(error)}, indent=2))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
