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
CP_HQD_ACTIVE_OFFSET = (GC_SEG0 + 0x1FAB) * 4
CP_HQD_PQ_RPTR_OFFSET = (GC_SEG0 + 0x1FB3) * 4
CP_HQD_PQ_DOORBELL_OFFSET = (GC_SEG0 + 0x1FB8) * 4
CP_HQD_DEQUEUE_OFFSET = (GC_SEG0 + 0x1FC1) * 4
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
SDMA_HALT_MASK = 0x1
SDMA_AUTO_CTXSW_ENABLE_MASK = 0x00040000
SDMA_RB_ENABLE_MASK = 0x1
SDMA_IB_ENABLE_MASK = 0x1


class RecoveryError(RuntimeError):
    pass


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
    """Own one VFIO group and expose only BAR5 MMIO for the transaction."""
    def __init__(self, vfio_root=Path('/dev/vfio')):
        self.root = Path(vfio_root)
        self.container_fd = self.group_fd = self.device_fd = None
        self.bar = None
        self._region = None
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
            region = VfioRegionInfo(ctypes.sizeof(VfioRegionInfo), 0,
                                    VFIO_PCI_BAR5_REGION_INDEX, 0, 0, 0)
            ioctl(self.device_fd, VFIO_DEVICE_GET_REGION_INFO, ctypes.byref(region))
            needed = VFIO_REGION_INFO_FLAG_READ | VFIO_REGION_INFO_FLAG_WRITE | VFIO_REGION_INFO_FLAG_MMAP
            if region.size < C2PMSG_64_OFFSET + 4 or region.flags & needed != needed:
                raise RecoveryError('BAR5 is not safely mappable at the PSP mailbox')
            self._region = region
            self.bar = mmap.mmap(self.device_fd, region.size,
                                 flags=mmap.MAP_SHARED,
                                 prot=mmap.PROT_READ | mmap.PROT_WRITE,
                                 offset=region.offset)
            return self
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.bar is not None:
            self.bar.close(); self.bar = None
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

    def write32(self, offset, value):
        struct.pack_into('<I', self.bar, offset, value)
        self.read32(offset)  # Posted-write flush through the same MMIO aperture.

    def metadata(self):
        flags = self._region.flags
        return {'index': self._region.index, 'size': self._region.size,
                'offset': self._region.offset,
                'read': bool(flags & VFIO_REGION_INFO_FLAG_READ),
                'write': bool(flags & VFIO_REGION_INFO_FLAG_WRITE),
                'mmap': bool(flags & VFIO_REGION_INFO_FLAG_MMAP)}


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


def quiesce_gc(mmio, sleep=time.sleep, polls=50):
    """Drain GC queues, halt command processors/SDMA, and prove no HQD is active.

    Firmware dequeue gets the first chance while the MECs still run. Once QEMU has
    removed guest DMA mappings that request may never finish, so the bounded fallback
    follows AMD's own inactive-queue paths: halt both MECs, disable the doorbell, then
    clear ACTIVE and stale pointers. Every transition is read back before a receipt can
    authorize another launch.
    """
    if not 1 <= polls <= 1000:
        raise ValueError('GC dequeue polls must be 1..1000')
    active = []
    dequeued = []
    stuck = []
    try:
        poll_control = mmio.read32(CP_PQ_WPTR_POLL_CNTL_OFFSET)
        mmio.write32(CP_PQ_WPTR_POLL_CNTL_OFFSET, poll_control & ~1)
        if mmio.read32(CP_PQ_WPTR_POLL_CNTL_OFFSET) & 1:
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
        return {
            'status': 'quiesced', 'active_before': len(active),
            'dequeued': len(dequeued), 'dequeue_timeouts': len(stuck),
            'forced_inactive': len(stuck), 'queues': active,
            'cp_me_before': me_before, 'cp_me_after': me_after,
            'cp_mec_before': mec_before, 'cp_mec_after': mec_after,
            'sdma0_cntl_before': sdma_cntl_before,
            'sdma0_cntl_after': sdma_cntl_after,
            'sdma0_rb_before': sdma_rb_before,
            'sdma0_rb_after': sdma_rb_after,
            'sdma0_ib_before': sdma_ib_before,
            'sdma0_ib_after': sdma_ib_after,
            'sdma0_before': sdma_before, 'sdma0_after': sdma_after,
            'active_after': 0,
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
        gc_quiesce = quiesce_gc(transport, sleep, min(polls, 50))
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
    return {
        'schema': 2, 'status': 'recovered', 'boot_id': expected_boot,
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
