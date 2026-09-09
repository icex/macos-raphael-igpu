#!/usr/bin/env python3
"""Quiesce Raphael PSP rings through user-owned VFIO and issue a reuse receipt."""
import argparse
import ctypes
import errno
import fcntl
import json
import mmap
import os
from pathlib import Path
import re
import struct
import subprocess
import time
import uuid

DEVICE = '0000:7b:00.0'
DEVICE_ID = '1002:13c0'
GROUP = '31'
MAX_LAUNCHES_PER_BOOT = 3

VFIO_TYPE = ord(';')
VFIO_BASE = 100
VFIO_GET_API_VERSION = (VFIO_TYPE << 8) | (VFIO_BASE + 0)
VFIO_CHECK_EXTENSION = (VFIO_TYPE << 8) | (VFIO_BASE + 1)
VFIO_SET_IOMMU = (VFIO_TYPE << 8) | (VFIO_BASE + 2)
VFIO_GROUP_GET_STATUS = (VFIO_TYPE << 8) | (VFIO_BASE + 3)
VFIO_GROUP_SET_CONTAINER = (VFIO_TYPE << 8) | (VFIO_BASE + 4)
VFIO_GROUP_UNSET_CONTAINER = (VFIO_TYPE << 8) | (VFIO_BASE + 5)
VFIO_GROUP_GET_DEVICE_FD = (VFIO_TYPE << 8) | (VFIO_BASE + 6)
VFIO_DEVICE_GET_REGION_INFO = (VFIO_TYPE << 8) | (VFIO_BASE + 8)
VFIO_API_VERSION = 0
VFIO_TYPE1_IOMMU = 1
VFIO_GROUP_FLAGS_VIABLE = 1
VFIO_REGION_INFO_FLAG_READ = 1
VFIO_REGION_INFO_FLAG_WRITE = 2
VFIO_REGION_INFO_FLAG_MMAP = 4
VFIO_PCI_BAR0_REGION_INDEX = 0
VFIO_PCI_BAR2_REGION_INDEX = 2
VFIO_PCI_BAR5_REGION_INDEX = 5

MP0_BASE = 0x16000
C2PMSG_64_OFFSET = (MP0_BASE + 0x80) * 4
DESTROY_RINGS = 0x00030000
DESTROY_GPCOM_RING = 0x000C0000
READY_MASK = 0x8000FFFF
READY_FLAG = 0x80000000
PCI_COMMAND_MASTER = 0x4

# GC 10.3 register indices are dword addressed. These are the same offsets used
# by Linux gfx_v10_0_hw_fini/gfx_v10_0_kiq_init_register and the measured Apple
# queue diagnostics. No PCI, PSP, or GRBM soft reset is part of this sequence.
GC_SEG0 = 0x1260
GRBM_GFX_CNTL_OFFSET = (GC_SEG0 + 0x0DC2) * 4
CP_PQ_WPTR_POLL_CNTL_OFFSET = (GC_SEG0 + 0x1E23) * 4
CP_ME_CNTL_OFFSET = (GC_SEG0 + 0x0F56) * 4
CP_MEC_CNTL_OFFSET = (GC_SEG0 + 0x0F55) * 4
CP_STAT_OFFSET = (GC_SEG0 + 0x0F40) * 4
CP_CPC_BUSY_STAT_OFFSET = (GC_SEG0 + 0x0E25) * 4
CP_RB_ACTIVE_OFFSET = (GC_SEG0 + 0x1F40) * 4
CP_RB1_ACTIVE_OFFSET = (GC_SEG0 + 0x1F41) * 4
CP_RB_DOORBELL_CONTROL_OFFSET = (GC_SEG0 + 0x1E8D) * 4
CP_RB0_BASE_OFFSET = (GC_SEG0 + 0x1DE0) * 4
CP_RB0_CNTL_OFFSET = (GC_SEG0 + 0x1DE1) * 4
CP_RB0_BASE_HI_OFFSET = (GC_SEG0 + 0x1E51) * 4
CP_RB0_WPTR_OFFSET = (GC_SEG0 + 0x1DF4) * 4
CP_RB0_WPTR_HI_OFFSET = (GC_SEG0 + 0x1DF5) * 4
CP_RB1_BASE_OFFSET = (GC_SEG0 + 0x1E00) * 4
CP_RB1_CNTL_OFFSET = (GC_SEG0 + 0x1E01) * 4
CP_RB1_BASE_HI_OFFSET = (GC_SEG0 + 0x1E52) * 4
CP_RB1_WPTR_OFFSET = (GC_SEG0 + 0x1DF6) * 4
CP_RB1_WPTR_HI_OFFSET = (GC_SEG0 + 0x1DF7) * 4
GCMC_VM_FB_LOCATION_BASE_OFFSET = (GC_SEG0 + 0x16FC) * 4
GCMC_VM_FB_LOCATION_TOP_OFFSET = (GC_SEG0 + 0x16FD) * 4
GCMC_VM_FB_OFFSET_OFFSET = (GC_SEG0 + 0x16E7) * 4
GCVM_CONTEXT0_PTB_LO_OFFSET = (GC_SEG0 + 0x1667) * 4
GCVM_CONTEXT0_PTB_HI_OFFSET = (GC_SEG0 + 0x1668) * 4
GCVM_CONTEXT0_START_LO_OFFSET = (GC_SEG0 + 0x1687) * 4
GCVM_CONTEXT0_START_HI_OFFSET = (GC_SEG0 + 0x1688) * 4
GCVM_CONTEXT0_END_LO_OFFSET = (GC_SEG0 + 0x16A7) * 4
GCVM_CONTEXT0_END_HI_OFFSET = (GC_SEG0 + 0x16A8) * 4
GCVM_CONTEXT0_CNTL_OFFSET = (GC_SEG0 + 0x15FC) * 4
CP_MEC_DOORBELL_RANGE_LOWER_OFFSET = (GC_SEG0 + 0x1DFC) * 4
CP_MEC_DOORBELL_RANGE_UPPER_OFFSET = (GC_SEG0 + 0x1DFD) * 4
CP_PQ_STATUS_OFFSET = (GC_SEG0 + 0x1E58) * 4
CP_MQD_BASE_ADDR_OFFSET = (GC_SEG0 + 0x1FA9) * 4
CP_MQD_BASE_ADDR_HI_OFFSET = (GC_SEG0 + 0x1FAA) * 4
CP_HQD_ACTIVE_OFFSET = (GC_SEG0 + 0x1FAB) * 4
CP_HQD_VMID_OFFSET = (GC_SEG0 + 0x1FAC) * 4
CP_HQD_PERSISTENT_STATE_OFFSET = (GC_SEG0 + 0x1FAD) * 4
CP_HQD_PQ_BASE_OFFSET = (GC_SEG0 + 0x1FB1) * 4
CP_HQD_PQ_BASE_HI_OFFSET = (GC_SEG0 + 0x1FB2) * 4
CP_HQD_PQ_RPTR_OFFSET = (GC_SEG0 + 0x1FB3) * 4
CP_HQD_PQ_RPTR_REPORT_ADDR_OFFSET = (GC_SEG0 + 0x1FB4) * 4
CP_HQD_PQ_RPTR_REPORT_ADDR_HI_OFFSET = (GC_SEG0 + 0x1FB5) * 4
CP_HQD_PQ_WPTR_POLL_ADDR_OFFSET = (GC_SEG0 + 0x1FB6) * 4
CP_HQD_PQ_WPTR_POLL_ADDR_HI_OFFSET = (GC_SEG0 + 0x1FB7) * 4
CP_HQD_PQ_DOORBELL_OFFSET = (GC_SEG0 + 0x1FB8) * 4
CP_HQD_PQ_CONTROL_OFFSET = (GC_SEG0 + 0x1FBA) * 4
CP_HQD_IB_CONTROL_OFFSET = (GC_SEG0 + 0x1FBE) * 4
CP_HQD_DEQUEUE_OFFSET = (GC_SEG0 + 0x1FC1) * 4
CP_MQD_CONTROL_OFFSET = (GC_SEG0 + 0x1FCB) * 4
CP_HQD_EOP_BASE_ADDR_OFFSET = (GC_SEG0 + 0x1FCE) * 4
CP_HQD_EOP_BASE_ADDR_HI_OFFSET = (GC_SEG0 + 0x1FCF) * 4
CP_HQD_EOP_CONTROL_OFFSET = (GC_SEG0 + 0x1FD0) * 4
CP_HQD_PQ_WPTR_LO_OFFSET = (GC_SEG0 + 0x1FDF) * 4
CP_HQD_PQ_WPTR_HI_OFFSET = (GC_SEG0 + 0x1FE0) * 4
# Raphael IP discovery gives SDMA0 the same segment-zero base as GC.  The
# generated gc_10_3_0 register header's "base address: 0x4980" describes a
# static ASIC layout and must not replace the live discovery base.  Apple
# confirms the addressing in sdma_5_2_stop_engine: SDMA0 uses block 0x23,
# base index 0, then the register offsets below.
SDMA0_CNTL_OFFSET = (GC_SEG0 + 0x001C) * 4
SDMA0_F32_CNTL_OFFSET = (GC_SEG0 + 0x002A) * 4
SDMA0_GFX_RB_CNTL_OFFSET = (GC_SEG0 + 0x0080) * 4
SDMA0_GFX_IB_CNTL_OFFSET = (GC_SEG0 + 0x008A) * 4
CP_ME_HALT_MASK = 0x15000000  # CE_HALT | PFP_HALT | ME_HALT
CP_MEC_HALT_MASK = 0x50000000 # MEC_ME1_HALT | MEC_ME2_HALT
CP_MEC2_HALT_MASK = 0x10000000
CP_RB_DOORBELL_ENABLE_MASK = 0x40000000
CP_RB_DOORBELL_HIT_MASK = 0x80000000
CP_RB_DOORBELL_BIF_DROP_MASK = 0x00000002
CP_RB_DOORBELL_OFFSET_MASK = 0x0ffffffc
CP_RB_DOORBELL_STATUS_MASK = (CP_RB_DOORBELL_ENABLE_MASK |
                              CP_RB_DOORBELL_HIT_MASK |
                              CP_RB_DOORBELL_BIF_DROP_MASK)
CP_PQ_DOORBELL_ENABLE_MASK = 0x2
CP_PQ_WPTR_POLL_ENABLE_MASK = 0x80000000
SDMA_HALT_MASK = 0x1
SDMA_AUTO_CTXSW_ENABLE_MASK = 0x00040000
SDMA_RB_ENABLE_MASK = 0x1
SDMA_IB_ENABLE_MASK = 0x1

# Crash recovery uses only GPU-local VRAM.  QEMU's IOMMU mappings are gone by
# the time this process opens VFIO, so rebuilding the KIQ in system memory would
# require bus mastering and a new DMA map.  The fixed scratch area is below the
# measured GART table at BAR0+0x0fdfc000 and is overwritten on every recovery.
VRAM_BAR_SIZE = 0x10000000
HOST_KIQ_RING_OFFSET = 0x0f100000
HOST_KIQ_RING_SIZE = 0x10000
HOST_KIQ_MQD_OFFSET = 0x0f110000
HOST_KIQ_MQD_SIZE = 0x800
HOST_KIQ_RPTR_OFFSET = 0x0f111000
HOST_KIQ_WPTR_OFFSET = 0x0f111008
HOST_KIQ_EOP_OFFSET = 0x0f112000
HOST_KIQ_EOP_SIZE = 0x1000
HOST_KIQ_FENCE_OFFSET = 0x0f113000
HOST_KIQ_HEAP_LIMIT = 0x0f000000
HOST_KIQ_RESERVATION_OFFSET = HOST_KIQ_HEAP_LIMIT
HOST_KIQ_RESERVATION_END = VRAM_BAR_SIZE
HOST_KIQ_RESERVATION_MAGIC = int.from_bytes(b'RGPUKIR1', 'little')
HOST_KIQ_RESERVATION_VERSION = 1
HOST_KIQ_RESERVATION_PENDING = int.from_bytes(b'PEND', 'little')
HOST_KIQ_RESERVATION_ACTIVE = int.from_bytes(b'ACTV', 'little')
HOST_KIQ_RESERVATION_FORMAT = '<QIIQQQQQQQ'
HOST_KIQ_RESERVATION_SIZE = struct.calcsize(HOST_KIQ_RESERVATION_FORMAT)
HOST_KIQ_RING_USED_DWORDS = 0x100
HOST_KIQ_FENCE_SEQUENCE_DWORD = 10
HOST_KIQ_NOP = 0xffff1000
HOST_KIQ_SELECTOR = 0x9  # MEC2, pipe 1, queue 0: Apple's measured KIQ.
HOST_KIQ_UNMAP_GFX = (0xC004A300, 0x30000000, 0x00000400, 0, 0, 0)
HOST_KIQ_WRITE_FENCE = (0xC0033700, 0x00100500)
APPLE_GRAPHICS_PIPE_POLICY = 'x6000-24G830-single-legacy-gfx-pipe-v1'

GRAPHICS_PIPE_DESCRIPTORS = (
    (0, 0, CP_RB_ACTIVE_OFFSET, CP_RB0_WPTR_OFFSET, CP_RB0_WPTR_HI_OFFSET,
     CP_RB0_BASE_OFFSET, CP_RB0_BASE_HI_OFFSET, CP_RB0_CNTL_OFFSET),
    (1, 1, CP_RB1_ACTIVE_OFFSET, CP_RB1_WPTR_OFFSET, CP_RB1_WPTR_HI_OFFSET,
     CP_RB1_BASE_OFFSET, CP_RB1_BASE_HI_OFFSET, CP_RB1_CNTL_OFFSET),
)

# NBIO 7.2 selects either its native HDP_MEM_FLUSH_CNTL address or the final
# BAR5 page. Linux writes the selected register then reads CONFIG_MEMSIZE to
# order the write. Keep action-register posting reads away from their target.
NBIO_SEG2 = 0xd20
NBIO_REMAP_HDP_MEM_FLUSH_OFFSET = (NBIO_SEG2 + 0x12d) * 4
NBIO_CONFIG_MEMSIZE_OFFSET = (NBIO_SEG2 + 0x0c3) * 4
HDP_MEM_FLUSH_NATIVE_OFFSET = (NBIO_SEG2 + 0x0f7) * 4
HDP_MEM_FLUSH_REMAP_OFFSET = 0x7f000
HDP_MEM_FLUSH_TARGETS = (HDP_MEM_FLUSH_NATIVE_OFFSET, HDP_MEM_FLUSH_REMAP_OFFSET)
EXPECTED_CONFIG_MEMSIZE = 0x200


class RecoveryError(RuntimeError):
    def __init__(self, message, *, evidence=None):
        super().__init__(message)
        self.evidence = evidence


class VfioGroupStatus(ctypes.Structure):
    _fields_ = [('argsz', ctypes.c_uint32), ('flags', ctypes.c_uint32)]


class VfioRegionInfo(ctypes.Structure):
    _fields_ = [('argsz', ctypes.c_uint32), ('flags', ctypes.c_uint32),
                ('index', ctypes.c_uint32), ('cap_offset', ctypes.c_uint32),
                ('size', ctypes.c_uint64), ('offset', ctypes.c_uint64)]


_libc = ctypes.CDLL(None, use_errno=True)
_libc.ioctl.restype = ctypes.c_int


def ioctl(fd, request, argument=0):
    result = _libc.ioctl(fd, request, argument)
    if result < 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code))
    return result


def _store_mmio_u64(buffer, offset, value):
    """Perform one naturally aligned native-width BAR store."""
    if offset < 0 or offset & 7 or offset + ctypes.sizeof(ctypes.c_uint64) > len(buffer):
        raise RecoveryError('64-bit MMIO store is not aligned and bounded')
    cell = ctypes.c_uint64.from_buffer(buffer, offset)
    try:
        cell.value = value & 0xffffffffffffffff
    finally:
        del cell


def write_once(path, value):
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


def active_qemu():
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():
            continue
        try:
            argv = (entry / 'cmdline').read_bytes().split(b'\0')
        except OSError:
            continue
        if argv and Path(os.fsdecode(argv[0])).name.startswith('qemu-system-'):
            return True
    return False


def host_state():
    root = Path('/sys/bus/pci/devices') / DEVICE
    try:
        vendor = int((root/'vendor').read_text().strip(), 16)
        device = int((root/'device').read_text().strip(), 16)
        driver = (root/'driver').resolve(strict=True).name
        group = (root/'iommu_group').resolve(strict=True).name
        with (root/'config').open('rb') as stream:
            stream.seek(4)
            pci_command = struct.unpack('<H', stream.read(2))[0]
        reset_methods = (root/'reset_method').read_text().split()
    except (OSError, ValueError, struct.error) as error:
        raise RecoveryError('cannot establish PCI identity: '+str(error)) from error
    return {
        'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
        'active_vm': active_qemu(),
        'driver': driver,
        'device': f'{vendor:04x}:{device:04x}',
        'iommu_group': group,
        'pci_command': pci_command,
        'reset_methods': reset_methods,
    }


def validate_host_state(state, expected_boot):
    errors = []
    if state.get('boot_id') != expected_boot: errors.append('boot_id')
    if state.get('active_vm') is not False: errors.append('active_vm')
    if state.get('driver') != 'vfio-pci': errors.append('driver')
    if state.get('device') != DEVICE_ID: errors.append('device')
    if state.get('iommu_group') != GROUP: errors.append('iommu_group')
    command = state.get('pci_command')
    if type(command) is not int or command & PCI_COMMAND_MASTER: errors.append('bus_master')
    if state.get('reset_methods') != []: errors.append('reset_method')
    return errors


def kernel_updates(cursor=None):
    args = ['journalctl', '-k', '-b', '--no-pager', '--show-cursor', '-o', 'json']
    args += ['--after-cursor', cursor] if cursor else ['-n', '0']
    result = subprocess.run(args, text=True, capture_output=True, timeout=5)
    if result.returncode:
        raise RecoveryError('kernel journal capture failed: '+result.stderr.strip())
    marker = re.search(r'^-- cursor: (.+)$', result.stdout, re.M)
    if not marker:
        raise RecoveryError('kernel journal cursor unavailable')
    messages = []
    for line in result.stdout.splitlines():
        if not line.startswith('{'):
            continue
        row = json.loads(line)
        if isinstance(row.get('MESSAGE'), str): messages.append(row['MESSAGE'])
    faults = [message for message in messages if re.search(
        r'BUG:|Oops:|Hardware Error|IO_PAGE_FAULT|hard LOCKUP|soft lockup|MCE:|'
        r'AMD-Vi:.*fault|vfio.*(?:error|failed)', message, re.I)]
    return marker[1], messages, faults


class LegacyVfio:
    """Own one VFIO group and map BAR0 VRAM, BAR2 doorbells, and BAR5 MMIO."""
    def __init__(self, vfio_root=Path('/dev/vfio')):
        self.root = Path(vfio_root)
        self.container_fd = self.group_fd = self.device_fd = None
        self.bar = None
        self.bars = {}
        self._regions = {}
        self.container_set = False

    def __enter__(self):
        try:
            self.container_fd = os.open(self.root/'vfio', os.O_RDWR | os.O_CLOEXEC)
            if ioctl(self.container_fd, VFIO_GET_API_VERSION) != VFIO_API_VERSION:
                raise RecoveryError('unsupported VFIO API version')
            if ioctl(self.container_fd, VFIO_CHECK_EXTENSION, VFIO_TYPE1_IOMMU) <= 0:
                raise RecoveryError('VFIO type1 IOMMU unavailable')
            self.group_fd = os.open(self.root/GROUP, os.O_RDWR | os.O_CLOEXEC)
            status = VfioGroupStatus(ctypes.sizeof(VfioGroupStatus), 0)
            ioctl(self.group_fd, VFIO_GROUP_GET_STATUS, ctypes.byref(status))
            if not status.flags & VFIO_GROUP_FLAGS_VIABLE:
                raise RecoveryError('VFIO group is not viable')
            container = ctypes.c_int(self.container_fd)
            ioctl(self.group_fd, VFIO_GROUP_SET_CONTAINER, ctypes.byref(container))
            self.container_set = True
            ioctl(self.container_fd, VFIO_SET_IOMMU, VFIO_TYPE1_IOMMU)
            name = ctypes.create_string_buffer(DEVICE.encode()+b'\0')
            self.device_fd = ioctl(self.group_fd, VFIO_GROUP_GET_DEVICE_FD,
                                   ctypes.cast(name, ctypes.c_void_p))
            needed = VFIO_REGION_INFO_FLAG_READ | VFIO_REGION_INFO_FLAG_WRITE | VFIO_REGION_INFO_FLAG_MMAP
            minimums = {VFIO_PCI_BAR0_REGION_INDEX: VRAM_BAR_SIZE,
                        VFIO_PCI_BAR2_REGION_INDEX: 8,
                        VFIO_PCI_BAR5_REGION_INDEX:
                            max(C2PMSG_64_OFFSET + 4,
                                HDP_MEM_FLUSH_REMAP_OFFSET + 4)}
            for index in (VFIO_PCI_BAR0_REGION_INDEX, VFIO_PCI_BAR2_REGION_INDEX,
                          VFIO_PCI_BAR5_REGION_INDEX):
                region = VfioRegionInfo(ctypes.sizeof(VfioRegionInfo), 0,
                                        index, 0, 0, 0)
                ioctl(self.device_fd, VFIO_DEVICE_GET_REGION_INFO, ctypes.byref(region))
                if region.size < minimums[index] or region.flags & needed != needed:
                    raise RecoveryError(f'BAR{index} is not safely mappable')
                self._regions[index] = region
                self.bars[index] = mmap.mmap(
                    self.device_fd, region.size, flags=mmap.MAP_SHARED,
                    prot=mmap.PROT_READ | mmap.PROT_WRITE, offset=region.offset)
            self.bar = self.bars[VFIO_PCI_BAR5_REGION_INDEX]
            return self
        except BaseException:
            self.close()
            raise

    def close(self):
        for index in sorted(self.bars, reverse=True):
            self.bars[index].close()
        self.bars.clear(); self.bar = None
        if self.device_fd is not None:
            os.close(self.device_fd); self.device_fd = None
        if self.group_fd is not None and self.container_set:
            try:
                ioctl(self.group_fd, VFIO_GROUP_UNSET_CONTAINER)
            except OSError as error:
                if error.errno not in (errno.ENODEV, errno.EINVAL): raise
            self.container_set = False
        if self.group_fd is not None:
            os.close(self.group_fd); self.group_fd = None
        if self.container_fd is not None:
            os.close(self.container_fd); self.container_fd = None

    def __exit__(self, kind, error, trace):
        self.close()

    def read32(self, offset):
        return struct.unpack_from('<I', self.bar, offset)[0]

    def posted_barrier(self):
        value = self.read32(NBIO_CONFIG_MEMSIZE_OFFSET)
        if value != EXPECTED_CONFIG_MEMSIZE:
            raise RecoveryError(
                f'NBIO CONFIG_MEMSIZE is {value:#x}, expected {EXPECTED_CONFIG_MEMSIZE:#x}')
        return value

    def write32(self, offset, value):
        struct.pack_into('<I', self.bar, offset, value)
        self.posted_barrier()

    def flush_hdp(self):
        remap = self.read32(NBIO_REMAP_HDP_MEM_FLUSH_OFFSET)
        if remap not in HDP_MEM_FLUSH_TARGETS or remap & 3 or remap + 4 > len(self.bar):
            raise RecoveryError(
                f'HDP flush target is {remap:#x}, expected a source-backed NBIO target')
        struct.pack_into('<I', self.bar, remap, 0)
        posted = self.posted_barrier()
        return {'remap': remap, 'posted_read': posted}

    def read_vram32(self, offset):
        if offset < 0 or offset + 4 > VRAM_BAR_SIZE:
            raise RecoveryError('VRAM read is outside BAR0')
        return struct.unpack_from('<I', self.bars[VFIO_PCI_BAR0_REGION_INDEX], offset)[0]

    def write_vram(self, offset, data):
        if offset < 0 or offset + len(data) > VRAM_BAR_SIZE:
            raise RecoveryError('VRAM write is outside BAR0')
        bar = self.bars[VFIO_PCI_BAR0_REGION_INDEX]
        bar[offset:offset+len(data)] = data
        # mmap.flush() is msync(2), which VFIO device mappings reject with
        # EINVAL. Publication is ordered by the explicit HDP flush and posted
        # read at each reservation or execution boundary.

    def ring_doorbell64(self, index, value):
        if index != 0:
            raise RecoveryError('recovery may ring only KIQ doorbell zero')
        offset = index * 8
        bar = self.bars[VFIO_PCI_BAR2_REGION_INDEX]
        _store_mmio_u64(bar, offset, value)
        self.posted_barrier()

    def metadata(self):
        def describe(region):
            flags = region.flags
            return {'index': region.index, 'size': region.size,
                    'offset': region.offset,
                    'read': bool(flags & VFIO_REGION_INFO_FLAG_READ),
                    'write': bool(flags & VFIO_REGION_INFO_FLAG_WRITE),
                    'mmap': bool(flags & VFIO_REGION_INFO_FLAG_MMAP)}
        result = describe(self._regions[VFIO_PCI_BAR5_REGION_INDEX])
        result['regions'] = {str(index): describe(region)
                             for index, region in sorted(self._regions.items())}
        return result


def run_command(mmio, command, label, sleep=time.sleep, polls=2000):
    before = mmio.read32(C2PMSG_64_OFFSET)
    mmio.write32(C2PMSG_64_OFFSET, command)
    value = before
    for attempt in range(polls):
        value = mmio.read32(C2PMSG_64_OFFSET)
        ready = (value & READY_MASK) == READY_FLAG
        matches = ((value >> 16) & 0x7fff) == (command >> 16)
        if ready and matches:
            return {'label': label, 'command': command, 'before': before,
                    'response': value, 'polls': attempt, 'confirmed': True}
        sleep(0.001)
    raise RecoveryError(f'{label} did not complete: 0x{before:08x} -> 0x{value:08x}')


def queue_selector(me, pipe, queue):
    if me not in (1, 2) or not 0 <= pipe < 4 or not 0 <= queue < 8:
        raise ValueError('invalid MEC queue selector')
    return pipe | (me << 2) | (queue << 8)


def host_kiq_scratch_ranges():
    return ((HOST_KIQ_RING_OFFSET, HOST_KIQ_RING_SIZE),
            (HOST_KIQ_MQD_OFFSET, HOST_KIQ_MQD_SIZE),
            (HOST_KIQ_RPTR_OFFSET, 4), (HOST_KIQ_WPTR_OFFSET, 8),
            (HOST_KIQ_EOP_OFFSET, HOST_KIQ_EOP_SIZE),
            (HOST_KIQ_FENCE_OFFSET, 4))


def _reservation_checksum(values):
    checksum = 0x9e3779b97f4a7c15
    for value in values:
        checksum ^= value
    return checksum & 0xffffffffffffffff


def _reservation_nonce(run_id):
    if not isinstance(run_id, str) or not re.fullmatch(r'[0-9a-f]{32}', run_id):
        raise ValueError('reservation run_id must be 32 lowercase hex characters')
    raw = bytes.fromhex(run_id)
    return struct.unpack('<QQ', raw)


def host_kiq_reservation_descriptor(run_id, state):
    if state not in (HOST_KIQ_RESERVATION_PENDING, HOST_KIQ_RESERVATION_ACTIVE):
        raise ValueError('invalid host-KIQ reservation state')
    nonce_lo, nonce_hi = _reservation_nonce(run_id)
    values = (HOST_KIQ_RESERVATION_MAGIC, HOST_KIQ_RESERVATION_VERSION,
              state, HOST_KIQ_HEAP_LIMIT, HOST_KIQ_RESERVATION_OFFSET,
              HOST_KIQ_RING_OFFSET, HOST_KIQ_RESERVATION_END,
              nonce_lo, nonce_hi)
    return struct.pack(HOST_KIQ_RESERVATION_FORMAT, *values,
                       _reservation_checksum(values))


def _read_vram_bytes(mmio, offset, size):
    if size & 3:
        raise ValueError('VRAM evidence reads must be dword sized')
    return b''.join(struct.pack('<I', mmio.read_vram32(offset + at))
                    for at in range(0, size, 4))


def inspect_host_kiq_reservation(mmio, run_id, state=HOST_KIQ_RESERVATION_ACTIVE):
    raw = _read_vram_bytes(mmio, HOST_KIQ_RESERVATION_OFFSET,
                           HOST_KIQ_RESERVATION_SIZE)
    expected = host_kiq_reservation_descriptor(run_id, state)
    if raw != expected:
        try:
            fields = struct.unpack(HOST_KIQ_RESERVATION_FORMAT, raw)
            actual_nonce = struct.pack('<QQ', fields[7], fields[8]).hex()
        except struct.error:
            actual_nonce = 'invalid'
        if actual_nonce != run_id:
            raise RecoveryError('guest host-KIQ reservation launch nonce does not match')
        raise RecoveryError('guest host-KIQ lifetime reservation is absent or invalid')
    fields = struct.unpack(HOST_KIQ_RESERVATION_FORMAT, raw)
    return {'version': fields[1], 'state': fields[2], 'heap_limit': fields[3],
            'reservation_start': fields[4], 'scratch_start': fields[5],
            'reservation_end': fields[6], 'run_id':run_id,
            'checksum': fields[9]}


def snapshot_graphics_pipes(mmio):
    """Read the conservative 2x2 ACTIVE matrix and restore selector zero."""
    snapshot = {'pipes': [],
                'final_default': {'value': 0, 'completed': False}}
    try:
        for (pipe, selector, active_offset, wptr_offset, wptr_hi_offset,
             base_offset, base_hi_offset, cntl_offset) in GRAPHICS_PIPE_DESCRIPTORS:
            mmio.write32(GRBM_GFX_CNTL_OFFSET, selector)
            doorbell = mmio.read32(CP_RB_DOORBELL_CONTROL_OFFSET)
            rb0_active = mmio.read32(CP_RB_ACTIVE_OFFSET)
            rb1_active = mmio.read32(CP_RB1_ACTIVE_OFFSET)
            snapshot['pipes'].append({
                'intended_pipe': pipe,
                'selector': selector,
                'rb0_active': rb0_active,
                'rb1_active': rb1_active,
                'active': rb0_active if active_offset == CP_RB_ACTIVE_OFFSET
                          else rb1_active,
                'doorbell_control': doorbell,
                'doorbell_offset': doorbell & CP_RB_DOORBELL_OFFSET_MASK,
                'doorbell_status': doorbell & CP_RB_DOORBELL_STATUS_MASK,
                'wptr': mmio.read32(wptr_offset),
                'wptr_hi': mmio.read32(wptr_hi_offset),
                'base': mmio.read32(base_offset),
                'base_hi': mmio.read32(base_hi_offset),
                'cntl': mmio.read32(cntl_offset),
            })
    finally:
        mmio.write32(GRBM_GFX_CNTL_OFFSET, 0)
        snapshot['final_default']['completed'] = True
    return snapshot


def _graphics_snapshot_accessible(snapshot):
    fields = ('doorbell_control', 'wptr', 'wptr_hi', 'base', 'base_hi', 'cntl')
    pipes = snapshot.get('pipes') if isinstance(snapshot, dict) else None
    return (isinstance(pipes, list) and len(pipes) == 2 and
            snapshot.get('final_default') == {'value': 0, 'completed': True} and
            all(row.get(field) != 0xffffffff for row in pipes for field in fields) and
            pipes[0].get('rb0_active') != 0xffffffff and
            pipes[1].get('rb1_active') != 0xffffffff)


def _apple_pipe1_supported(snapshot):
    if not _graphics_snapshot_accessible(snapshot):
        return False
    pipe0, pipe1 = snapshot['pipes']
    return (pipe0.get('intended_pipe') == 0 and pipe0.get('selector') == 0 and
            pipe1.get('intended_pipe') == 1 and pipe1.get('selector') == 1 and
            not (pipe1.get('rb1_active', 1) & 1) and
            pipe1.get('doorbell_status') == 0)


def valid_apple_graphics_snapshot(snapshot):
    """Validate a schema-5 two-selector snapshot for Apple's one-pipe policy."""
    row_keys = {'intended_pipe', 'selector', 'rb0_active', 'rb1_active',
                'active', 'doorbell_control', 'doorbell_offset',
                'doorbell_status', 'wptr', 'wptr_hi', 'base', 'base_hi', 'cntl'}
    if (not isinstance(snapshot, dict) or
            set(snapshot) != {'pipes', 'final_default'} or
            not _apple_pipe1_supported(snapshot)):
        return False
    for index, row in enumerate(snapshot['pipes']):
        if (not isinstance(row, dict) or set(row) != row_keys or
                any(type(value) is not int for value in row.values()) or
                row['intended_pipe'] != index or row['selector'] != index or
                row['active'] != row['rb0_active' if index == 0 else 'rb1_active'] or
                row['doorbell_offset'] !=
                    (row['doorbell_control'] & CP_RB_DOORBELL_OFFSET_MASK) or
                row['doorbell_status'] !=
                    (row['doorbell_control'] & CP_RB_DOORBELL_STATUS_MASK)):
            return False
    return True


def valid_apple_graphics_pipe_guard(proof, run_id):
    """Validate the exact ACTIVE-bound pre-consumption schema-5 guard."""
    try:
        fields = struct.unpack(
            HOST_KIQ_RESERVATION_FORMAT,
            host_kiq_reservation_descriptor(run_id, HOST_KIQ_RESERVATION_ACTIVE))
    except (TypeError, ValueError):
        return False
    expected_reservation = {
        'version': fields[1], 'state': fields[2], 'heap_limit': fields[3],
        'reservation_start': fields[4], 'scratch_start': fields[5],
        'reservation_end': fields[6], 'run_id': run_id, 'checksum': fields[9],
    }
    return (isinstance(proof, dict) and
            set(proof) == {'policy', 'reservation_before', 'reservation_after',
                           'reservation_unchanged', 'pipe1_supported_state',
                           'snapshot'} and
            proof.get('policy') == APPLE_GRAPHICS_PIPE_POLICY and
            proof.get('reservation_before') == expected_reservation and
            proof.get('reservation_after') == expected_reservation and
            proof.get('reservation_unchanged') is True and
            proof.get('pipe1_supported_state') is True and
            valid_apple_graphics_snapshot(proof.get('snapshot')))


def guard_apple_graphics_pipes(mmio, run_id):
    """Fail before reservation consumption if Apple has a live second gfx pipe."""
    reservation_before = inspect_host_kiq_reservation(mmio, run_id)
    pipes = snapshot_graphics_pipes(mmio)
    reservation_after = inspect_host_kiq_reservation(mmio, run_id)
    unchanged = reservation_before == reservation_after
    if not unchanged:
        raise RecoveryError('ACTIVE reservation changed during graphics pipe guard')
    pipe1_supported = _apple_pipe1_supported(pipes)
    if not pipe1_supported:
        if not _graphics_snapshot_accessible(pipes):
            raise RecoveryError('graphics pipe snapshot is inaccessible/all-ones')
        raise RecoveryError('graphics pipe 1 is live or faulted and unsupported by '
                            'the Apple single-pipe recovery path')
    return {
        'policy': APPLE_GRAPHICS_PIPE_POLICY,
        'reservation_before': reservation_before,
        'reservation_after': reservation_after,
        'reservation_unchanged': unchanged,
        'pipe1_supported_state': pipe1_supported,
        'snapshot': pipes,
    }


def consume_host_kiq_reservation(mmio, run_id):
    proof = inspect_host_kiq_reservation(mmio, run_id)
    mmio.write_vram(HOST_KIQ_RESERVATION_OFFSET,
                    b'\0' * HOST_KIQ_RESERVATION_SIZE)
    proof['consume_hdp_flush'] = mmio.flush_hdp()
    if any(mmio.read_vram32(HOST_KIQ_RESERVATION_OFFSET + at)
           for at in range(0, HOST_KIQ_RESERVATION_SIZE, 4)):
        raise RecoveryError('guest host-KIQ lifetime reservation would not consume')
    proof['consumed'] = True
    return proof


def valid_consumed_reservation(proof, run_id):
    """Return whether *proof* is the exact launch-bound ACTIVE reservation."""
    try:
        expected = struct.unpack(
            HOST_KIQ_RESERVATION_FORMAT,
            host_kiq_reservation_descriptor(run_id, HOST_KIQ_RESERVATION_ACTIVE))
    except (TypeError, ValueError):
        return False
    flush = proof.get('consume_hdp_flush') if isinstance(proof, dict) else None
    integer_keys = ('version', 'state', 'heap_limit', 'reservation_start',
                    'scratch_start', 'reservation_end', 'checksum')
    return (isinstance(proof, dict) and
            set(proof) == set(integer_keys) | {
                'run_id', 'consumed', 'consume_hdp_flush'} and
            all(type(proof.get(key)) is int for key in integer_keys) and
            proof.get('version') == expected[1] and
            proof.get('state') == expected[2] and
            proof.get('heap_limit') == expected[3] and
            proof.get('reservation_start') == expected[4] and
            proof.get('scratch_start') == expected[5] and
            proof.get('reservation_end') == expected[6] and
            proof.get('run_id') == run_id and
            proof.get('checksum') == expected[9] and
            proof.get('consumed') is True and
            isinstance(flush, dict) and set(flush) == {'remap', 'posted_read'} and
            type(flush.get('remap')) is int and
            flush.get('remap') in HDP_MEM_FLUSH_TARGETS and
            type(flush.get('posted_read')) is int and
            flush.get('posted_read') == EXPECTED_CONFIG_MEMSIZE)


def prepare_host_kiq_reservation(mmio, run_id):
    """Publish a launch-bound challenge that only the initialized guest activates."""
    descriptor = host_kiq_reservation_descriptor(
        run_id, HOST_KIQ_RESERVATION_PENDING)
    mmio.write_vram(HOST_KIQ_RESERVATION_OFFSET, descriptor)
    flush = mmio.flush_hdp()
    if _read_vram_bytes(mmio, HOST_KIQ_RESERVATION_OFFSET,
                        HOST_KIQ_RESERVATION_SIZE) != descriptor:
        raise RecoveryError('prelaunch host-KIQ reservation challenge did not persist')
    return {'run_id':run_id, 'state':'pending', 'hdp_flush':flush}


def prepare_launch(expected_boot, run_id, state_reader=host_state,
                   transport_factory=LegacyVfio, expected_pending=False):
    """Install the one-launch challenge while the inactive device remains on VFIO."""
    before = state_reader()
    errors = validate_host_state(before, expected_boot)
    if errors:
        raise RecoveryError('pre-challenge gate failed: '+','.join(errors))
    with transport_factory() as transport:
        prior_pending = None
        if expected_pending:
            prior_pending = inspect_host_kiq_reservation(
                transport, run_id, HOST_KIQ_RESERVATION_PENDING)
        challenge = prepare_host_kiq_reservation(transport, run_id)
        region = transport.metadata()
    after = state_reader()
    errors = validate_host_state(after, expected_boot)
    if errors:
        raise RecoveryError('post-challenge gate failed: '+','.join(errors))
    return {'boot_id':expected_boot, 'run_id':run_id, 'state':'pending',
            'pci_command_before':before['pci_command'],
            'pci_command_after':after['pci_command'], 'vfio_region':region,
            'prior_pending':prior_pending, 'challenge':challenge}


def _put32(image, offset, value):
    struct.pack_into('<I', image, offset, value & 0xffffffff)


def _host_kiq_image(fb_base, fence_sequence, gfx_doorbell_offset):
    """Build a v10 compute MQD and ordered UNMAP plus completion fence."""
    ring_addr = fb_base + HOST_KIQ_RING_OFFSET
    mqd_addr = fb_base + HOST_KIQ_MQD_OFFSET
    rptr_addr = fb_base + HOST_KIQ_RPTR_OFFSET
    wptr_addr = fb_base + HOST_KIQ_WPTR_OFFSET
    eop_addr = fb_base + HOST_KIQ_EOP_OFFSET
    fence_addr = fb_base + HOST_KIQ_FENCE_OFFSET

    ring = bytearray(struct.pack('<I', HOST_KIQ_NOP) * (HOST_KIQ_RING_SIZE // 4))
    unmap = (HOST_KIQ_UNMAP_GFX[0], HOST_KIQ_UNMAP_GFX[1],
             gfx_doorbell_offset, 0, 0, 0)
    struct.pack_into('<6I', ring, 0, *unmap)
    struct.pack_into('<5I', ring, 24, *HOST_KIQ_WRITE_FENCE,
                     fence_addr & 0xffffffff, fence_addr >> 32, fence_sequence)
    mqd = bytearray(HOST_KIQ_MQD_SIZE)
    _put32(mqd, 0x000, 0xC0310800)
    _put32(mqd, 0x02C, 1)          # compute_pipelinestat_enable
    for offset in (0x05C, 0x060, 0x068, 0x06C):
        _put32(mqd, offset, 0xffffffff)
    _put32(mqd, 0x080, 3)          # compute_misc_reserved
    _put32(mqd, 0x200, mqd_addr & 0xfffffffc)
    _put32(mqd, 0x204, mqd_addr >> 32)
    _put32(mqd, 0x208, 1)          # cp_hqd_active
    _put32(mqd, 0x20C, 0)          # VMID 0
    _put32(mqd, 0x210, 0x0BE05300) # PRELOAD_SIZE=0x53, no request
    _put32(mqd, 0x220, (ring_addr >> 8) & 0xffffffff)
    _put32(mqd, 0x224, ring_addr >> 40)
    _put32(mqd, 0x228, 0)
    _put32(mqd, 0x22C, rptr_addr & 0xfffffffc)
    _put32(mqd, 0x230, (rptr_addr >> 32) & 0xffff)
    _put32(mqd, 0x234, wptr_addr & 0xfffffffc)
    _put32(mqd, 0x238, (wptr_addr >> 32) & 0xffff)
    _put32(mqd, 0x23C, 0x40000000) # doorbell zero, enabled
    _put32(mqd, 0x244, 0xD130060D) # UNORD_DISPATCH + queue/cache policy
    _put32(mqd, 0x254, 0x00300000) # MIN_IB_AVAIL_SIZE=3
    _put32(mqd, 0x260, 0)
    _put32(mqd, 0x288, 0x100)
    _put32(mqd, 0x294, (eop_addr >> 8) & 0xffffffff)
    _put32(mqd, 0x298, eop_addr >> 40)
    _put32(mqd, 0x29C, 6)
    _put32(mqd, 0x2D8, 0)
    _put32(mqd, 0x2DC, 0)
    return ring, mqd, {
        'ring': ring_addr, 'mqd': mqd_addr, 'rptr': rptr_addr,
        'wptr': wptr_addr, 'eop': eop_addr, 'fence': fence_addr,
    }


def _framebuffer_aperture(mmio):
    base = mmio.read32(GCMC_VM_FB_LOCATION_BASE_OFFSET) & 0xffffff
    top = mmio.read32(GCMC_VM_FB_LOCATION_TOP_OFFSET) & 0xffffff
    if base == 0 or top < base:
        raise RecoveryError(f'invalid framebuffer aperture {base:#x}..{top:#x}')
    return base << 24, (top - base + 1) << 24


def _runtime_gart_bar_range(mmio, aperture_size):
    control = mmio.read32(GCVM_CONTEXT0_CNTL_OFFSET)
    raw_root = ((mmio.read32(GCVM_CONTEXT0_PTB_HI_OFFSET) << 32) |
                mmio.read32(GCVM_CONTEXT0_PTB_LO_OFFSET))
    start_lo = mmio.read32(GCVM_CONTEXT0_START_LO_OFFSET)
    start_hi = mmio.read32(GCVM_CONTEXT0_START_HI_OFFSET)
    end_lo = mmio.read32(GCVM_CONTEXT0_END_LO_OFFSET)
    end_hi = mmio.read32(GCVM_CONTEXT0_END_HI_OFFSET)
    physical_fb = (mmio.read32(GCMC_VM_FB_OFFSET_OFFSET) & 0xffffff) << 24
    result = {'control': control, 'root': raw_root, 'start_page': 0,
              'end_page': 0, 'physical_fb': physical_fb,
              'bar_offset': None, 'size': 0, 'active': False}
    if (control & 7) == 0 and (raw_root & 1) == 0:
        return result
    flags = raw_root & 0xfff
    if ((control & 7) != 1 or flags not in (1, 5) or
            (start_hi | end_hi) & ~0xf or raw_root > 0x0000ffffffffffff):
        raise RecoveryError('cannot translate enabled GART page table metadata')
    start = (start_hi << 32) | start_lo
    end = (end_hi << 32) | end_lo
    if end < start or physical_fb == 0:
        raise RecoveryError('cannot translate enabled GART page table range')
    root = raw_root & ~0xfff
    size = (end - start + 1) * 8
    visible = min(aperture_size, VRAM_BAR_SIZE)
    if root < physical_fb or size == 0 or size > visible:
        raise RecoveryError('cannot translate enabled GART page table to BAR0')
    offset = root - physical_fb
    if offset > visible - size:
        raise RecoveryError('cannot translate enabled GART page table to BAR0')
    result.update(start_page=start, end_page=end, bar_offset=offset,
                  size=size, active=True)
    return result


def _ranges_overlap(first_start, first_size, second_start, second_size):
    return first_start < second_start + second_size and second_start < first_start + first_size


def retire_legacy_gfx_with_host_kiq(mmio, prior_run_id, sleep=time.sleep, polls=2000,
                                    reservation_proof=None):
    """Execute graphics UNMAP_QUEUES from a temporary VRAM-backed KIQ.

    The transaction never enables PCI bus mastering and never depends on QEMU's
    discarded DMA mappings.  Its finally block leaves MEC1/MEC2 halted, disables
    the temporary doorbell, and restores the default GRBM selector on every path.
    """
    if not 1 <= polls <= 10000:
        raise ValueError('host KIQ polls must be 1..10000')
    # The recovery coordinator supplies this proof after consuming the ACTIVE
    # launch reservation at the recovery boundary. Standalone diagnostic calls
    # consume once here, before their first GC mutation.
    reservation = (consume_host_kiq_reservation(mmio, prior_run_id)
                   if reservation_proof is None else reservation_proof)
    if not valid_consumed_reservation(reservation, prior_run_id):
        raise RecoveryError('consumed host-KIQ reservation proof is invalid')
    fb_base, aperture_size = _framebuffer_aperture(mmio)
    scratch_end = max(offset + size for offset, size in host_kiq_scratch_ranges())
    if scratch_end > min(aperture_size, VRAM_BAR_SIZE):
        raise RecoveryError('host KIQ scratch is outside the framebuffer aperture')
    gart = _runtime_gart_bar_range(mmio, aperture_size)
    if gart['bar_offset'] is not None:
        for offset, size in host_kiq_scratch_ranges():
            if _ranges_overlap(offset, size, gart['bar_offset'], gart['size']):
                raise RecoveryError('host KIQ scratch overlaps the live GART page table')
    gfx_doorbell = mmio.read32(CP_RB_DOORBELL_CONTROL_OFFSET)
    gfx_doorbell_offset = gfx_doorbell & CP_RB_DOORBELL_OFFSET_MASK
    if gfx_doorbell_offset != HOST_KIQ_UNMAP_GFX[2]:
        raise RecoveryError(
            f'graphics doorbell offset is {gfx_doorbell_offset:#x}, expected 0x400')
    fence_sequence = uuid.uuid4().int & 0xffffffff or 1
    ring, mqd, addresses = _host_kiq_image(
        fb_base, fence_sequence, gfx_doorbell_offset)
    mec_before = mmio.read32(CP_MEC_CNTL_OFFSET)
    poll_before = mmio.read32(CP_PQ_WPTR_POLL_CNTL_OFFSET)
    pq_status_before = mmio.read32(CP_PQ_STATUS_OFFSET)
    rptr_after = 0
    retired = False
    gfx_active_after_unmap = None
    fence_after = 0
    report_after = 0
    polls_completed = 0
    terminal_poll = None
    hdp_flush = None
    result = None
    failure = None
    failure_traceback = None
    failure_evidence = {
        'aperture': {'base': fb_base, 'size': aperture_size},
        'addresses': addresses,
        'packet': {
            'unmap': list(HOST_KIQ_UNMAP_GFX),
            'write_fence': list(HOST_KIQ_WRITE_FENCE),
            'ring_used_dwords': HOST_KIQ_RING_USED_DWORDS,
        },
        'fence_sequence': fence_sequence,
        'gfx_doorbell_offset': gfx_doorbell_offset,
        'gart': gart,
        'reservation': reservation,
        'hdp_flush': None,
        'terminal_poll': None,
        'cleanup': {'readbacks': {}, 'errors': []},
    }
    try:
        mmio.write32(CP_MEC_CNTL_OFFSET, mec_before | CP_MEC_HALT_MASK)
        if mmio.read32(CP_MEC_CNTL_OFFSET) & CP_MEC_HALT_MASK != CP_MEC_HALT_MASK:
            raise RecoveryError('cannot halt MECs before host KIQ setup')

        # The queue is backed only by BAR0. Populate it after both MECs have
        # stopped, then prove CPU writes reached VRAM before programming HQD.
        mmio.write_vram(HOST_KIQ_RING_OFFSET, ring)
        mmio.write_vram(HOST_KIQ_MQD_OFFSET, mqd)
        mmio.write_vram(HOST_KIQ_RPTR_OFFSET, b'\0' * 4)
        mmio.write_vram(HOST_KIQ_WPTR_OFFSET,
                        struct.pack('<Q', HOST_KIQ_RING_USED_DWORDS))
        mmio.write_vram(HOST_KIQ_EOP_OFFSET, b'\0' * HOST_KIQ_EOP_SIZE)
        mmio.write_vram(HOST_KIQ_FENCE_OFFSET, b'\0' * 4)
        if mmio.read_vram32(HOST_KIQ_RING_OFFSET) != HOST_KIQ_UNMAP_GFX[0]:
            raise RecoveryError('host KIQ ring failed VRAM readback')
        if mmio.read_vram32(HOST_KIQ_MQD_OFFSET) != 0xC0310800:
            raise RecoveryError('host KIQ MQD failed VRAM readback')
        hdp_flush = mmio.flush_hdp()
        failure_evidence['hdp_flush'] = hdp_flush

        mmio.write32(GRBM_GFX_CNTL_OFFSET, HOST_KIQ_SELECTOR)
        if mmio.read32(CP_HQD_ACTIVE_OFFSET) & 1:
            raise RecoveryError('host KIQ selector is still active before setup')

        # This is gfx_v10_0_kiq_init_register's order with values from the
        # scratch MQD. EOP writes are made but are not used as a success signal;
        # this part has been measured executing KIQ packets with EOP base zero.
        mmio.write32(CP_PQ_WPTR_POLL_CNTL_OFFSET,
                     poll_before & ~CP_PQ_WPTR_POLL_ENABLE_MASK)
        if mmio.read32(CP_PQ_WPTR_POLL_CNTL_OFFSET) & CP_PQ_WPTR_POLL_ENABLE_MASK:
            raise RecoveryError('host KIQ write-pointer polling would not disable')
        mmio.write32(CP_HQD_PQ_DOORBELL_OFFSET, 0)
        mmio.write32(CP_HQD_EOP_BASE_ADDR_OFFSET,
                     (addresses['eop'] >> 8) & 0xffffffff)
        mmio.write32(CP_HQD_EOP_BASE_ADDR_HI_OFFSET, addresses['eop'] >> 40)
        mmio.write32(CP_HQD_EOP_CONTROL_OFFSET, 6)
        mmio.write32(CP_MQD_BASE_ADDR_OFFSET, addresses['mqd'] & 0xfffffffc)
        mmio.write32(CP_MQD_BASE_ADDR_HI_OFFSET, addresses['mqd'] >> 32)
        mmio.write32(CP_MQD_CONTROL_OFFSET, 0x100)
        mmio.write32(CP_HQD_PQ_BASE_OFFSET,
                     (addresses['ring'] >> 8) & 0xffffffff)
        mmio.write32(CP_HQD_PQ_BASE_HI_OFFSET, addresses['ring'] >> 40)
        mmio.write32(CP_HQD_PQ_CONTROL_OFFSET, 0xD130060D)
        mmio.write32(CP_HQD_PQ_RPTR_REPORT_ADDR_OFFSET,
                     addresses['rptr'] & 0xfffffffc)
        mmio.write32(CP_HQD_PQ_RPTR_REPORT_ADDR_HI_OFFSET,
                     (addresses['rptr'] >> 32) & 0xffff)
        mmio.write32(CP_HQD_PQ_WPTR_POLL_ADDR_OFFSET,
                     addresses['wptr'] & 0xfffffffc)
        mmio.write32(CP_HQD_PQ_WPTR_POLL_ADDR_HI_OFFSET,
                     (addresses['wptr'] >> 32) & 0xffff)
        mmio.write32(CP_MEC_DOORBELL_RANGE_LOWER_OFFSET, 0)
        mmio.write32(CP_MEC_DOORBELL_RANGE_UPPER_OFFSET, 0)
        mmio.write32(CP_HQD_PQ_DOORBELL_OFFSET, 0x40000000)
        mmio.write32(CP_HQD_PQ_RPTR_OFFSET, 0)
        mmio.write32(CP_HQD_PQ_WPTR_LO_OFFSET, 0)
        mmio.write32(CP_HQD_PQ_WPTR_HI_OFFSET, 0)
        mmio.write32(CP_HQD_VMID_OFFSET, 0)
        mmio.write32(CP_HQD_PERSISTENT_STATE_OFFSET, 0x0BE05300)
        mmio.write32(CP_HQD_IB_CONTROL_OFFSET, 0x00300000)
        mmio.write32(CP_HQD_ACTIVE_OFFSET, 1)
        if not (mmio.read32(CP_HQD_ACTIVE_OFFSET) & 1):
            raise RecoveryError('host KIQ would not activate')
        mmio.write32(CP_PQ_STATUS_OFFSET,
                     pq_status_before | CP_PQ_DOORBELL_ENABLE_MASK)
        if not (mmio.read32(CP_PQ_STATUS_OFFSET) & CP_PQ_DOORBELL_ENABLE_MASK):
            raise RecoveryError('host KIQ global doorbell gate would not enable')

        # Apple's KIQ is MEC2. Leave MEC1 halted and start only MEC2.
        running = (mec_before | CP_MEC_HALT_MASK) & ~CP_MEC2_HALT_MASK
        mmio.write32(CP_MEC_CNTL_OFFSET, running)
        if mmio.read32(CP_MEC_CNTL_OFFSET) & CP_MEC2_HALT_MASK:
            raise RecoveryError('MEC2 would not start for host KIQ')
        mmio.ring_doorbell64(0, HOST_KIQ_RING_USED_DWORDS)
        for attempt in range(polls):
            rptr_after = mmio.read32(CP_HQD_PQ_RPTR_OFFSET)
            report_after = mmio.read_vram32(HOST_KIQ_RPTR_OFFSET)
            fence_after = mmio.read_vram32(HOST_KIQ_FENCE_OFFSET)
            polls_completed = attempt + 1
            terminal_poll = {
                'polls': polls_completed,
                'rptr': rptr_after,
                'report': report_after,
                'fence': fence_after,
            }
            if ((rptr_after == HOST_KIQ_RING_USED_DWORDS or
                 report_after == HOST_KIQ_RING_USED_DWORDS) and
                    fence_after == fence_sequence):
                rptr_after = HOST_KIQ_RING_USED_DWORDS
                break
            sleep(0.001)
        else:
            if (rptr_after == HOST_KIQ_RING_USED_DWORDS or
                    report_after == HOST_KIQ_RING_USED_DWORDS):
                raise RecoveryError('host KIQ completion fence did not execute')
            raise RecoveryError('host KIQ did not consume graphics UNMAP_QUEUES')

        # RPTR only proves the packet was fetched. The graphics ring must report
        # inactive before any host-side register scrub can count as proof.
        mmio.write32(GRBM_GFX_CNTL_OFFSET, 0)
        graphics_pipes_after_unmap = None
        for _ in range(polls):
            graphics_pipes_after_unmap = snapshot_graphics_pipes(mmio)
            gfx_active_after_unmap = graphics_pipes_after_unmap['pipes'][0]['active']
            if not _apple_pipe1_supported(graphics_pipes_after_unmap):
                raise RecoveryError('graphics pipe 1 became live or faulted after '
                                    'the pipe-0 UNMAP_QUEUES')
            if not (gfx_active_after_unmap & 1):
                break
            sleep(0.001)
        else:
            raise RecoveryError('graphics ring remained active after UNMAP_QUEUES')

        mmio.write32(GRBM_GFX_CNTL_OFFSET, HOST_KIQ_SELECTOR)
        mmio.write32(CP_HQD_DEQUEUE_OFFSET, 1)
        for _ in range(polls):
            if not (mmio.read32(CP_HQD_ACTIVE_OFFSET) & 1):
                retired = True
                break
            sleep(0.001)
        if not retired:
            raise RecoveryError('host KIQ would not retire after graphics unmap')
        result = {'status': 'retired', 'selector': HOST_KIQ_SELECTOR,
                  'packet_dwords': HOST_KIQ_RING_USED_DWORDS,
                  'rptr_after': rptr_after,
                  'fence_sequence': fence_sequence, 'fence_after': fence_after,
                  'gfx_active_after_unmap': gfx_active_after_unmap,
                  'graphics_pipes_after_unmap': graphics_pipes_after_unmap,
                  'gfx_doorbell_offset': gfx_doorbell_offset,
                  'addresses': addresses, 'gart': gart,
                  'reservation': reservation, 'hdp_flush': hdp_flush}
    except BaseException as error:
        failure = error
        failure_traceback = error.__traceback__

    failure_evidence['terminal_poll'] = terminal_poll

    cleanup_errors = []
    cleanup_readbacks = {
        'mec_cntl': None,
        'hqd_active': None,
        'hqd_doorbell': None,
        'hqd_rptr': None,
        'hqd_wptr_lo': None,
        'hqd_wptr_hi': None,
        'pq_status': None,
        'doorbell_range_lower': None,
        'doorbell_range_upper': None,
        'wptr_poll_cntl': None,
    }
    failure_evidence['cleanup'] = {
        'readbacks': cleanup_readbacks,
        'errors': cleanup_errors,
    }

    def cleanup(label, action):
        try:
            action()
        except BaseException as error:
            cleanup_errors.append(f'{label}: {type(error).__name__}: {error}')

    def require(label, condition):
        if not condition:
            raise RecoveryError(label)

    def verify_readback(key, offset, label, predicate):
        value = mmio.read32(offset)
        cleanup_readbacks[key] = value
        require(label, predicate(value))

    def verify_wptr_clear():
        lo = mmio.read32(CP_HQD_PQ_WPTR_LO_OFFSET)
        cleanup_readbacks['hqd_wptr_lo'] = lo
        if lo != 0:
            raise RecoveryError('host KIQ wptr did not clear')
        hi = mmio.read32(CP_HQD_PQ_WPTR_HI_OFFSET)
        cleanup_readbacks['hqd_wptr_hi'] = hi
        require('host KIQ wptr did not clear', hi == 0)

    cleanup('halt MECs', lambda:mmio.write32(
        CP_MEC_CNTL_OFFSET, mec_before | CP_MEC_HALT_MASK))
    cleanup('select host KIQ', lambda:mmio.write32(
        GRBM_GFX_CNTL_OFFSET, HOST_KIQ_SELECTOR))
    cleanup('disable host KIQ doorbell', lambda:mmio.write32(
        CP_HQD_PQ_DOORBELL_OFFSET, 0))
    cleanup('clear host KIQ active', lambda:mmio.write32(CP_HQD_ACTIVE_OFFSET, 0))
    cleanup('clear host KIQ dequeue', lambda:mmio.write32(CP_HQD_DEQUEUE_OFFSET, 0))
    cleanup('clear host KIQ rptr', lambda:mmio.write32(CP_HQD_PQ_RPTR_OFFSET, 0))
    cleanup('clear host KIQ wptr lo', lambda:mmio.write32(CP_HQD_PQ_WPTR_LO_OFFSET, 0))
    cleanup('clear host KIQ wptr hi', lambda:mmio.write32(CP_HQD_PQ_WPTR_HI_OFFSET, 0))
    cleanup('disable doorbell lower range', lambda:mmio.write32(
        CP_MEC_DOORBELL_RANGE_LOWER_OFFSET, 0))
    cleanup('disable doorbell upper range', lambda:mmio.write32(
        CP_MEC_DOORBELL_RANGE_UPPER_OFFSET, 0))
    cleanup('disable PQ doorbell gate', lambda:mmio.write32(
        CP_PQ_STATUS_OFFSET, pq_status_before & ~CP_PQ_DOORBELL_ENABLE_MASK))
    cleanup('disable wptr polling', lambda:mmio.write32(
        CP_PQ_WPTR_POLL_CNTL_OFFSET,
        poll_before & ~CP_PQ_WPTR_POLL_ENABLE_MASK))
    cleanup('verify MEC halt', lambda:verify_readback(
        'mec_cntl', CP_MEC_CNTL_OFFSET, 'MEC halt did not read back',
        lambda value:value & CP_MEC_HALT_MASK == CP_MEC_HALT_MASK))
    cleanup('verify host KIQ inactive', lambda:verify_readback(
        'hqd_active', CP_HQD_ACTIVE_OFFSET, 'host KIQ active did not clear',
        lambda value:not (value & 1)))
    cleanup('verify host KIQ doorbell disabled', lambda:verify_readback(
        'hqd_doorbell', CP_HQD_PQ_DOORBELL_OFFSET,
        'host KIQ doorbell did not disable',
        lambda value:not (value & CP_RB_DOORBELL_ENABLE_MASK)))
    cleanup('verify host KIQ rptr clear', lambda:verify_readback(
        'hqd_rptr', CP_HQD_PQ_RPTR_OFFSET, 'host KIQ rptr did not clear',
        lambda value:value == 0))
    cleanup('verify host KIQ wptr clear', verify_wptr_clear)
    cleanup('verify PQ doorbell gate disabled', lambda:verify_readback(
        'pq_status', CP_PQ_STATUS_OFFSET, 'PQ doorbell gate did not disable',
        lambda value:not (value & CP_PQ_DOORBELL_ENABLE_MASK)))
    cleanup('verify doorbell lower range disabled', lambda:verify_readback(
        'doorbell_range_lower', CP_MEC_DOORBELL_RANGE_LOWER_OFFSET,
        'doorbell lower range did not disable', lambda value:value == 0))
    cleanup('verify doorbell upper range disabled', lambda:verify_readback(
        'doorbell_range_upper', CP_MEC_DOORBELL_RANGE_UPPER_OFFSET,
        'doorbell upper range did not disable', lambda value:value == 0))
    cleanup('verify wptr polling disabled', lambda:verify_readback(
        'wptr_poll_cntl', CP_PQ_WPTR_POLL_CNTL_OFFSET,
        'wptr polling did not disable',
        lambda value:not (value & CP_PQ_WPTR_POLL_ENABLE_MASK)))
    cleanup('restore default selector', lambda:mmio.write32(GRBM_GFX_CNTL_OFFSET, 0))

    if cleanup_errors:
        prefix = f'{failure}; ' if failure is not None else ''
        raise RecoveryError(prefix+'host KIQ cleanup failed: '+'; '.join(cleanup_errors),
                            evidence=failure_evidence) \
            from failure
    if failure is not None:
        if isinstance(failure, RecoveryError):
            failure.evidence = failure_evidence
        raise failure.with_traceback(failure_traceback)
    # Preserve the cleanup readbacks, rather than reducing them to a boolean.
    # Receipt admission can then reject a forged or incomplete cleanup claim.
    mmio.write32(GRBM_GFX_CNTL_OFFSET, HOST_KIQ_SELECTOR)
    try:
        cleanup_proof = {
            'mec_cntl': mmio.read32(CP_MEC_CNTL_OFFSET),
            'hqd_active': mmio.read32(CP_HQD_ACTIVE_OFFSET),
            'hqd_doorbell': mmio.read32(CP_HQD_PQ_DOORBELL_OFFSET),
            'hqd_rptr': mmio.read32(CP_HQD_PQ_RPTR_OFFSET),
            'hqd_wptr_lo': mmio.read32(CP_HQD_PQ_WPTR_LO_OFFSET),
            'hqd_wptr_hi': mmio.read32(CP_HQD_PQ_WPTR_HI_OFFSET),
            'pq_status': mmio.read32(CP_PQ_STATUS_OFFSET),
            'doorbell_range_lower': mmio.read32(CP_MEC_DOORBELL_RANGE_LOWER_OFFSET),
            'doorbell_range_upper': mmio.read32(CP_MEC_DOORBELL_RANGE_UPPER_OFFSET),
            'wptr_poll_cntl': mmio.read32(CP_PQ_WPTR_POLL_CNTL_OFFSET),
        }
    finally:
        mmio.write32(GRBM_GFX_CNTL_OFFSET, 0)
    result['cleanup_confirmed'] = True
    result['cleanup'] = cleanup_proof
    result['gfx_active_before_scrub'] = result['gfx_active_after_unmap']
    return result


def quiesce_gc(mmio, sleep=time.sleep, polls=50, kiq_polls=None, prior_run_id=None,
               reservation_proof=None, graphics_pipe_guard=None):
    """Drain GC queues, halt command processors/SDMA, and prove no HQD is active.

    Firmware dequeue gets the first chance while the MECs still run. Once QEMU has
    removed guest DMA mappings that request may never finish, so the bounded fallback
    follows AMD's own inactive-queue paths: halt both MECs, disable the doorbell, then
    clear ACTIVE and stale pointers. Every transition is read back before a receipt can
    authorize another launch.
    """
    if not 1 <= polls <= 1000:
        raise ValueError('GC dequeue polls must be 1..1000')
    if kiq_polls is None:
        kiq_polls = polls
    if not 1 <= kiq_polls <= 10000:
        raise ValueError('host KIQ polls must be 1..10000')
    active = []
    dequeued = []
    stuck = []
    host_kiq = {'status': 'not-needed'}
    try:
        graphics_pipes_before = snapshot_graphics_pipes(mmio)
        if not _apple_pipe1_supported(graphics_pipes_before):
            raise RecoveryError('graphics pipe 1 became live or faulted after the '
                                'pre-consumption guard')
        poll_control = mmio.read32(CP_PQ_WPTR_POLL_CNTL_OFFSET)
        mmio.write32(CP_PQ_WPTR_POLL_CNTL_OFFSET,
                     poll_control & ~CP_PQ_WPTR_POLL_ENABLE_MASK)
        if mmio.read32(CP_PQ_WPTR_POLL_CNTL_OFFSET) & CP_PQ_WPTR_POLL_ENABLE_MASK:
            raise RecoveryError('CP write-pointer polling would not disable')
        for me in (1, 2):
            for pipe in range(4):
                for queue in range(8):
                    selector = queue_selector(me, pipe, queue)
                    mmio.write32(GRBM_GFX_CNTL_OFFSET, selector)
                    if not (mmio.read32(CP_HQD_ACTIVE_OFFSET) & 1):
                        continue
                    row = {'me': me, 'pipe': pipe, 'queue': queue,
                           'selector': selector}
                    active.append(row)
                    mmio.write32(CP_HQD_DEQUEUE_OFFSET, 1)
                    for attempt in range(polls):
                        if not (mmio.read32(CP_HQD_ACTIVE_OFFSET) & 1):
                            row['polls'] = attempt
                            dequeued.append(row)
                            break
                        sleep(0.001)
                    else:
                        row['polls'] = polls
                        stuck.append(row)
                    if row in dequeued:
                        mmio.write32(CP_HQD_PQ_DOORBELL_OFFSET, 0)
                        mmio.write32(CP_HQD_DEQUEUE_OFFSET, 0)

        # Never start MEC2 for the temporary KIQ while any earlier queue is
        # still live. Re-scan because a queue could become active while the
        # first pass is walking the other selectors.
        stuck_selectors = {row['selector'] for row in stuck}
        for me in (1, 2):
            for pipe in range(4):
                for queue in range(8):
                    selector = queue_selector(me, pipe, queue)
                    mmio.write32(GRBM_GFX_CNTL_OFFSET, selector)
                    if (mmio.read32(CP_HQD_ACTIVE_OFFSET) & 1 and
                            selector not in stuck_selectors):
                        row = {'me': me, 'pipe': pipe, 'queue': queue,
                               'selector': selector, 'polls': polls,
                               'appeared_on_rescan': True}
                        active.append(row)
                        stuck.append(row)
                        stuck_selectors.add(selector)

        mmio.write32(GRBM_GFX_CNTL_OFFSET, 0)
        gfx0_before = graphics_pipes_before['pipes'][0]
        gfx_rb_active_before = gfx0_before['active']
        gfx_rb_doorbell_before = gfx0_before['doorbell_control']
        gfx_rb_wptr_before = gfx0_before['wptr']
        gfx_rb_wptr_hi_before = gfx0_before['wptr_hi']
        gfx_rb_base_before = gfx0_before['base']
        gfx_rb_base_hi_before = gfx0_before['base_hi']
        gfx_rb_cntl_before = gfx0_before['cntl']
        gfx_needs_unmap = bool((gfx_rb_active_before & 1) or
                               gfx0_before['doorbell_status'])
        gfx_was_stale = any(
            (row['active'] & 1) or row['doorbell_status'] or row['wptr'] or
            row['wptr_hi'] or row['base'] or row['base_hi'] or row['cntl']
            for row in graphics_pipes_before['pipes'])
        if gfx_needs_unmap and not stuck and prior_run_id is not None:
            try:
                host_kiq = retire_legacy_gfx_with_host_kiq(
                    mmio, prior_run_id, sleep=sleep, polls=kiq_polls,
                    reservation_proof=reservation_proof)
            except RecoveryError as error:
                host_kiq = {'status': 'failed', 'error': str(error)}
                if error.evidence is not None:
                    host_kiq['evidence'] = error.evidence
        elif gfx_needs_unmap and not stuck:
            host_kiq = {'status': 'blocked-no-launch-id'}
        elif gfx_needs_unmap:
            host_kiq = {'status': 'blocked-active-hqd',
                        'selectors': sorted(stuck_selectors)}

        if host_kiq.get('status') == 'retired':
            graphics_pipes_after_retirement = host_kiq['graphics_pipes_after_unmap']
        else:
            graphics_pipes_after_retirement = snapshot_graphics_pipes(mmio)

        # Linux sdma_v5_2_hw_fini disables context switching and the GFX
        # ring/IB before halting the engine.  Preserve that order so no SDMA
        # fetch can race teardown of QEMU's DMA mappings.
        sdma_cntl_before = mmio.read32(SDMA0_CNTL_OFFSET)
        mmio.write32(SDMA0_CNTL_OFFSET,
                     sdma_cntl_before & ~SDMA_AUTO_CTXSW_ENABLE_MASK)
        sdma_rb_before = mmio.read32(SDMA0_GFX_RB_CNTL_OFFSET)
        mmio.write32(SDMA0_GFX_RB_CNTL_OFFSET,
                     sdma_rb_before & ~SDMA_RB_ENABLE_MASK)
        sdma_ib_before = mmio.read32(SDMA0_GFX_IB_CNTL_OFFSET)
        mmio.write32(SDMA0_GFX_IB_CNTL_OFFSET,
                     sdma_ib_before & ~SDMA_IB_ENABLE_MASK)
        sdma_before = mmio.read32(SDMA0_F32_CNTL_OFFSET)
        mmio.write32(SDMA0_F32_CNTL_OFFSET, sdma_before | SDMA_HALT_MASK)
        sdma_cntl_after = mmio.read32(SDMA0_CNTL_OFFSET)
        sdma_rb_after = mmio.read32(SDMA0_GFX_RB_CNTL_OFFSET)
        sdma_ib_after = mmio.read32(SDMA0_GFX_IB_CNTL_OFFSET)
        sdma_after = mmio.read32(SDMA0_F32_CNTL_OFFSET)
        if sdma_cntl_after & SDMA_AUTO_CTXSW_ENABLE_MASK:
            raise RecoveryError('SDMA0 context switching would not stop')
        if sdma_rb_after & SDMA_RB_ENABLE_MASK:
            raise RecoveryError('SDMA0 ring buffer would not stop')
        if sdma_ib_after & SDMA_IB_ENABLE_MASK:
            raise RecoveryError('SDMA0 indirect buffer would not stop')
        if sdma_after & SDMA_HALT_MASK != SDMA_HALT_MASK:
            raise RecoveryError('SDMA0 would not halt')

        me_before = mmio.read32(CP_ME_CNTL_OFFSET)
        mmio.write32(CP_ME_CNTL_OFFSET, me_before | CP_ME_HALT_MASK)
        mec_before = mmio.read32(CP_MEC_CNTL_OFFSET)
        mmio.write32(CP_MEC_CNTL_OFFSET, mec_before | CP_MEC_HALT_MASK)
        me_after = mmio.read32(CP_ME_CNTL_OFFSET)
        mec_after = mmio.read32(CP_MEC_CNTL_OFFSET)
        if me_after & CP_ME_HALT_MASK != CP_ME_HALT_MASK:
            raise RecoveryError('graphics command processor would not halt')
        if mec_after & CP_MEC_HALT_MASK != CP_MEC_HALT_MASK:
            raise RecoveryError('compute command processors would not halt')

        # Leave every global compute-queue ingress gate disabled. A new guest
        # rebuilds these values; recovery must not restore stale launch state.
        mmio.write32(CP_MEC_DOORBELL_RANGE_LOWER_OFFSET, 0)
        mmio.write32(CP_MEC_DOORBELL_RANGE_UPPER_OFFSET, 0)
        mmio.write32(CP_PQ_STATUS_OFFSET,
                     mmio.read32(CP_PQ_STATUS_OFFSET) &
                     ~CP_PQ_DOORBELL_ENABLE_MASK)
        pq_wptr_poll_after = mmio.read32(CP_PQ_WPTR_POLL_CNTL_OFFSET)
        pq_status_after = mmio.read32(CP_PQ_STATUS_OFFSET)
        doorbell_range_lower_after = mmio.read32(CP_MEC_DOORBELL_RANGE_LOWER_OFFSET)
        doorbell_range_upper_after = mmio.read32(CP_MEC_DOORBELL_RANGE_UPPER_OFFSET)
        if (pq_wptr_poll_after & CP_PQ_WPTR_POLL_ENABLE_MASK or
                pq_status_after & CP_PQ_DOORBELL_ENABLE_MASK or
                doorbell_range_lower_after or doorbell_range_upper_after):
            raise RecoveryError('global compute queue gates would not disable')

        # UNMAP_QUEUES removes the scheduler mapping. With every CP halted it is
        # then safe to erase the legacy ring programming that Apple will rebuild
        # on the next launch. These writes were measured as ignored before unmap,
        # hence a clean readback alone cannot substitute for host_kiq=retired.
        mmio.write32(GRBM_GFX_CNTL_OFFSET, 0)
        mmio.write32(CP_RB_DOORBELL_CONTROL_OFFSET, 0)
        mmio.write32(CP_RB_ACTIVE_OFFSET, 0)
        mmio.write32(CP_RB0_WPTR_OFFSET, 0)
        mmio.write32(CP_RB0_WPTR_HI_OFFSET, 0)
        mmio.write32(CP_RB0_BASE_OFFSET, 0)
        mmio.write32(CP_RB0_BASE_HI_OFFSET, 0)
        mmio.write32(CP_RB0_CNTL_OFFSET, 0)
        graphics_pipes_final = snapshot_graphics_pipes(mmio)
        gfx0_final = graphics_pipes_final['pipes'][0]
        gfx_rb_active_after = gfx0_final['active']
        gfx_rb_doorbell_after = gfx0_final['doorbell_control']
        gfx_rb_wptr_after = gfx0_final['wptr']
        gfx_rb_wptr_hi_after = gfx0_final['wptr_hi']
        gfx_rb_base_after = gfx0_final['base']
        gfx_rb_base_hi_after = gfx0_final['base_hi']
        gfx_rb_cntl_after = gfx0_final['cntl']
        gfx_ring_clean = ((gfx_rb_active_after & 1) == 0 and
                          gfx0_final['doorbell_status'] == 0 and
                          gfx_rb_wptr_after == 0 and gfx_rb_wptr_hi_after == 0 and
                          gfx_rb_base_after == 0 and gfx_rb_base_hi_after == 0 and
                          gfx_rb_cntl_after == 0 and
                          _apple_pipe1_supported(graphics_pipes_final))
        graphics_pipe_proof_complete = (
            valid_apple_graphics_pipe_guard(graphics_pipe_guard, prior_run_id) and
            valid_apple_graphics_snapshot(graphics_pipes_before) and
            valid_apple_graphics_snapshot(graphics_pipes_after_retirement) and
            valid_apple_graphics_snapshot(graphics_pipes_final))
        gfx_retirement_confirmed = (not gfx_needs_unmap or
                                    host_kiq.get('status') == 'retired')

        for row in stuck:
            mmio.write32(GRBM_GFX_CNTL_OFFSET, row['selector'])
            mmio.write32(CP_HQD_PQ_DOORBELL_OFFSET, 0)
            mmio.write32(CP_HQD_ACTIVE_OFFSET, 0)
            mmio.write32(CP_HQD_DEQUEUE_OFFSET, 0)
            mmio.write32(CP_HQD_PQ_RPTR_OFFSET, 0)
            mmio.write32(CP_HQD_PQ_WPTR_LO_OFFSET, 0)
            mmio.write32(CP_HQD_PQ_WPTR_HI_OFFSET, 0)
            if mmio.read32(CP_HQD_ACTIVE_OFFSET) & 1:
                raise RecoveryError('halted HQD would not become inactive at selector '
                                    f'{row["selector"]:#x}')

        remaining = []
        for me in (1, 2):
            for pipe in range(4):
                for queue in range(8):
                    selector = queue_selector(me, pipe, queue)
                    mmio.write32(GRBM_GFX_CNTL_OFFSET, selector)
                    if mmio.read32(CP_HQD_ACTIVE_OFFSET) & 1:
                        remaining.append(selector)
        if remaining:
            raise RecoveryError('active HQDs remain after halt: '+
                                ','.join(f'{selector:#x}' for selector in remaining))
        cp_stat_after = mmio.read32(CP_STAT_OFFSET)
        cp_cpc_busy_after = mmio.read32(CP_CPC_BUSY_STAT_OFFSET)
        active_after = sum(1 for row in graphics_pipes_final['pipes']
                           if row['active'] & 1)
        if host_kiq.get('status') == 'retired':
            host_kiq['final_gate'] = {
                'active_after': active_after,
                'cp_stat_after': cp_stat_after,
                'cp_cpc_busy_after': cp_cpc_busy_after,
                'pq_wptr_poll_after': pq_wptr_poll_after,
                'pq_status_after': pq_status_after,
                'doorbell_range_lower_after': doorbell_range_lower_after,
                'doorbell_range_upper_after': doorbell_range_upper_after,
                'gfx_ring_clean': gfx_ring_clean,
                'gfx_retirement_confirmed': gfx_retirement_confirmed,
                'graphics_pipe_proof_complete': graphics_pipe_proof_complete,
            }
        return {
            'status': 'quiesced', 'active_before': len(active),
            'dequeued': len(dequeued), 'dequeue_timeouts': len(stuck),
            'forced_inactive': len(stuck), 'queues': active,
            'cp_me_before': me_before, 'cp_me_after': me_after,
            'cp_mec_before': mec_before, 'cp_mec_after': mec_after,
            'cp_stat_after': cp_stat_after,
            'cp_cpc_busy_after': cp_cpc_busy_after,
            'pq_wptr_poll_after': pq_wptr_poll_after,
            'pq_status_after': pq_status_after,
            'doorbell_range_lower_after': doorbell_range_lower_after,
            'doorbell_range_upper_after': doorbell_range_upper_after,
            'graphics_pipe_guard': graphics_pipe_guard,
            'graphics_pipes_before': graphics_pipes_before,
            'graphics_pipes_after_retirement': graphics_pipes_after_retirement,
            'graphics_pipes_final': graphics_pipes_final,
            'graphics_pipe_proof_complete': graphics_pipe_proof_complete,
            'gfx_rb_active_before': gfx_rb_active_before,
            'gfx_rb_active_after': gfx_rb_active_after,
            'gfx_rb_doorbell_before': gfx_rb_doorbell_before,
            'gfx_rb_doorbell_after': gfx_rb_doorbell_after,
            'gfx_rb_wptr_before': gfx_rb_wptr_before,
            'gfx_rb_wptr_hi_before': gfx_rb_wptr_hi_before,
            'gfx_rb_wptr_after': gfx_rb_wptr_after,
            'gfx_rb_wptr_hi_after': gfx_rb_wptr_hi_after,
            'gfx_rb_base_before': gfx_rb_base_before,
            'gfx_rb_base_after': gfx_rb_base_after,
            'gfx_rb_base_hi_before': gfx_rb_base_hi_before,
            'gfx_rb_base_hi_after': gfx_rb_base_hi_after,
            'gfx_rb_cntl_before': gfx_rb_cntl_before,
            'gfx_rb_cntl_after': gfx_rb_cntl_after,
            'gfx_ring_clean': gfx_ring_clean,
            'gfx_was_stale': gfx_was_stale,
            'gfx_needs_unmap': gfx_needs_unmap,
            'gfx_retirement_confirmed': gfx_retirement_confirmed,
            'host_kiq': host_kiq,
            'reservation': reservation_proof,
            'sdma0_cntl_before': sdma_cntl_before,
            'sdma0_cntl_after': sdma_cntl_after,
            'sdma0_rb_before': sdma_rb_before,
            'sdma0_rb_after': sdma_rb_after,
            'sdma0_ib_before': sdma_ib_before,
            'sdma0_ib_after': sdma_ib_after,
            'sdma0_before': sdma_before, 'sdma0_after': sdma_after,
            'active_after': active_after,
        }
    finally:
        mmio.write32(GRBM_GFX_CNTL_OFFSET, 0)


def perform_recovery(expected_boot, prior_run_id, state_reader, transport_factory,
                     journal_reader, sleep=time.sleep, polls=2000):
    cursor, _, initial_faults = journal_reader()
    if initial_faults:
        raise RecoveryError('host fault already present at recovery boundary')
    before = state_reader()
    errors = validate_host_state(before, expected_boot)
    if errors:
        raise RecoveryError('pre-recovery gate failed: '+','.join(errors))
    commands = []
    with transport_factory() as transport:
        region = transport.metadata()
        # The exact Apple build creates only pipe 0. Inspect both pipe banks while
        # the ACTIVE reservation is still reusable, and refuse an unsupported live
        # pipe 1 before consuming it. Selector writes are restored to zero and the
        # reservation is authenticated again on both sides of this bounded guard.
        graphics_pipe_guard = guard_apple_graphics_pipes(transport, prior_run_id)
        reservation = consume_host_kiq_reservation(transport, prior_run_id)
        gc_quiesce = quiesce_gc(transport, sleep, min(polls, 50), polls,
                                prior_run_id, reservation,
                                graphics_pipe_guard=graphics_pipe_guard)
        commands.append(run_command(transport, DESTROY_RINGS, 'destroy all rings', sleep, polls))
        commands.append(run_command(transport, DESTROY_GPCOM_RING, 'destroy GPCOM ring', sleep, polls))
    after = state_reader()
    errors = validate_host_state(after, expected_boot)
    if errors:
        raise RecoveryError('post-recovery gate failed: '+','.join(errors))
    final_cursor, messages, faults = journal_reader(cursor)
    if faults:
        raise RecoveryError('new host kernel fault during recovery: '+'; '.join(faults))
    implicit_resets = [message for message in messages if re.search(
        rf'vfio-pci {re.escape(DEVICE)}: (?:resetting|reset done)\b', message, re.I)]
    if implicit_resets:
        raise RecoveryError('VFIO performed a forbidden implicit PCI reset: '+
                            '; '.join(implicit_resets))
    safe_for_reuse = (valid_consumed_reservation(
                          gc_quiesce.get('reservation'), prior_run_id) and
                      gc_quiesce['dequeue_timeouts'] == 0 and
                      gc_quiesce['forced_inactive'] == 0 and
                      gc_quiesce['cp_stat_after'] == 0 and
                      gc_quiesce['cp_cpc_busy_after'] == 0 and
                      gc_quiesce['cp_me_after'] & CP_ME_HALT_MASK == CP_ME_HALT_MASK and
                      gc_quiesce['cp_mec_after'] & CP_MEC_HALT_MASK == CP_MEC_HALT_MASK and
                      not (gc_quiesce['pq_wptr_poll_after'] &
                           CP_PQ_WPTR_POLL_ENABLE_MASK) and
                      not (gc_quiesce['pq_status_after'] &
                           CP_PQ_DOORBELL_ENABLE_MASK) and
                      gc_quiesce['doorbell_range_lower_after'] == 0 and
                      gc_quiesce['doorbell_range_upper_after'] == 0 and
                      gc_quiesce['sdma0_after'] & SDMA_HALT_MASK == SDMA_HALT_MASK and
                      not (gc_quiesce['sdma0_cntl_after'] & SDMA_AUTO_CTXSW_ENABLE_MASK) and
                      not (gc_quiesce['sdma0_rb_after'] & SDMA_RB_ENABLE_MASK) and
                      not (gc_quiesce['sdma0_ib_after'] & SDMA_IB_ENABLE_MASK) and
                      gc_quiesce['gfx_ring_clean'] and
                      gc_quiesce['gfx_retirement_confirmed'] and
                      gc_quiesce['graphics_pipe_proof_complete'])
    return {
        'schema': 5, 'status': 'recovered' if safe_for_reuse else 'incomplete',
        'authorizes_launch': safe_for_reuse, 'boot_id': expected_boot,
        'prior_run_id': prior_run_id, 'device': DEVICE, 'iommu_group': GROUP,
        'driver': 'vfio-pci', 'pci_command_before': before['pci_command'],
        'pci_command_after': after['pci_command'],
        'reset_methods_before': before['reset_methods'],
        'reset_methods_after': after['reset_methods'], 'bar5': region,
        'gc_quiesce': gc_quiesce,
        'commands': commands, 'kernel_cursor_before': cursor,
        'kernel_cursor_after': final_cursor, 'kernel_messages': messages,
    }


def read_ledger(path):
    value = json.loads(path.read_text())
    if 'launches' not in value and 'experiment' in value:
        value = {'boot_id': value['boot_id'],
                 'launches': [{'run_id': value['experiment'], 'legacy': True}]}
    return value


def recover(vm, prior_run_id):
    if not re.fullmatch(r'[0-9a-f]{32}', prior_run_id):
        raise RecoveryError('prior run ID must be 32 lowercase hexadecimal characters')
    lock_path = vm/'run/experiment.lock'
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open('a') as owner:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        initial = host_state()
        boot_id = initial['boot_id']
        ledger_path = vm/'run/used-gpu-boots'/(boot_id+'.json')
        if not ledger_path.exists():
            raise RecoveryError('no launch ledger exists for this host boot')
        ledger = read_ledger(ledger_path)
        launches = ledger.get('launches', [])
        if not launches or launches[-1].get('run_id') != prior_run_id:
            raise RecoveryError('prior run is not the latest launch on this boot')
        path = vm/'run/vfio-recovery'/boot_id/(prior_run_id+'.json')
        if path.exists():
            raise RecoveryError('an immutable recovery receipt already exists for this run')
        evidence = perform_recovery(boot_id, prior_run_id, host_state, LegacyVfio, kernel_updates)
        evidence['recovery_id'] = uuid.uuid4().hex
        evidence['created_epoch'] = time.time()
        write_once(path, evidence)
        return evidence


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vm-dir', required=True, type=Path)
    parser.add_argument('--prior-run', required=True)
    parser.add_argument('--output', type=Path,
                        help='write success or failure evidence in addition to the receipt')
    args = parser.parse_args()
    try:
        result = recover(args.vm_dir.resolve(), args.prior_run)
    except BaseException as error:
        result = {'status':'failed', 'error':type(error).__name__+': '+str(error)}
        if args.output: write_once(args.output, result)
        print(json.dumps(result, indent=2))
        raise SystemExit(1)
    if args.output: write_once(args.output, result)
    print(json.dumps(result, indent=2))
