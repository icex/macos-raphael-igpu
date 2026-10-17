#!/usr/bin/env python3
"""Retain QEMU's VFIO ownership outside its container until DMA is stopped.

The SCM_RIGHTS device fd keeps the legacy VFIO group and container alive on
process/container death. Never open a second VFIO device, reset, or rebind.
Once a device fd is received, any unproved cleanup retains it indefinitely.
"""
import argparse
import array
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import select
import signal
import socket
import struct
import subprocess
import time


def load_helper(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


IH = load_helper('ih_dma')
ENGINES = load_helper('dma_engines')
DEVICE = '0000:7b:00.0'
VFIO_GET_INFO = (ord(';') << 8) | 107
VFIO_GET_REGION = (ord(';') << 8) | 108
# Existing writeback stop list in RaphaelGPU.cpp, independent of guest readiness.
DISPLAY_STOPS = tuple(reg * 4 for reg in (0x66ea, 0x3732, 0x1390, 0x139a))


def source_hashes():
    return {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
            for name in ('dma-guard.py', 'ih_dma.py', 'dma_engines.py')}


def validate_receipt(value, boot, cid):
    try:
        if (value.get('schema') != 2 or value.get('boot_id') != boot or
                value.get('device') != DEVICE or value.get('status') != 'released' or
                value.get('peer', {}).get('cid') != cid or
                value.get('helper_sha256') != source_hashes()):
            return ['dma_guard_identity']
        errors = IH.validate(value.get('ih_dma', {})) + ENGINES.validate(value.get('dma_engines', {}))
        rows = value['display_stops']
        if (len(rows) != len(DISPLAY_STOPS) or
                [row['offset'] for row in rows] != list(DISPLAY_STOPS) or
                any(type(row['before']) is not int or not 0 <= row['before'] < 0xffffffff or
                    row['after'] != row['before'] & ~1 for row in rows)):
            errors.append('dma_guard_display_stops')
        return errors
    except (KeyError, TypeError, ValueError):
        return ['dma_guard_malformed']


def region(fd, index):
    data = bytearray(struct.pack('<IIIIQQ', 32, 0, index, 0, 0, 0))
    fcntl.ioctl(fd, VFIO_GET_REGION, data)
    _, flags, observed, _, size, offset = struct.unpack('<IIIIQQ', data)
    if observed != index or flags & 3 != 3:
        raise ValueError('VFIO region is not readable/writable')
    return size, offset


class Device:
    """Use VFIO region IO: no privileged sysfs MMIO mapping is needed."""
    def __init__(self, fd):
        self.fd = fd
        info = bytearray(struct.pack('<IIII', 16, 0, 0, 0))
        fcntl.ioctl(fd, VFIO_GET_INFO, info)
        _, flags, regions, _ = struct.unpack('<IIII', info)
        if not flags & 2 or regions < 8:  # VFIO_DEVICE_FLAGS_PCI
            raise ValueError('not a VFIO PCI descriptor')
        self.size, self.bar = region(fd, 5)
        config_size, self.config = region(fd, 7)
        if self.size < 0x20000 or config_size < 8:
            raise ValueError('VFIO region coverage')
        if os.pread(fd, 4, self.config) != struct.pack('<HH', 0x1002, 0x13c0):
            raise ValueError('VFIO descriptor is not Raphael')

    def read32(self, offset):
        if offset & 3 or not 0 <= offset <= self.size - 4:
            raise ValueError('unaligned/outside BAR5')
        data = os.pread(self.fd, 4, self.bar + offset)
        if len(data) != 4:
            raise ValueError('short VFIO register read')
        return struct.unpack('<I', data)[0]

    def write32(self, offset, value):
        if offset & 3 or not 0 <= offset <= self.size - 4:
            raise ValueError('unaligned/outside BAR5')
        if os.pwrite(self.fd, struct.pack('<I', value), self.bar + offset) != 4:
            raise ValueError('short VFIO register write')
        self.read32(offset)  # Posted-write flush.


def quiesce(device):
    display = []
    for offset in DISPLAY_STOPS:
        old = device.read32(offset)
        if old == 0xffffffff:
            raise ValueError('inaccessible display stop register')
        if old & 1:
            device.write32(offset, old & ~1)
        after = device.read32(offset)
        if after != old & ~1:
            raise ValueError('display stop readback mismatch')
        display.append({'offset': offset, 'before': old, 'after': after})
    ih_proof = IH.quiesce(device)
    engines = ENGINES.quiesce(device)
    return {'display_stops': display, 'ih_dma': ih_proof, 'dma_engines': engines}


def write_receipt(path, value):
    temporary = path.with_suffix('.tmp')
    with temporary.open('w') as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def peer_identity(connection, name, vm):
    pid, uid, gid = struct.unpack('3i', connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
    if uid not in (0, os.getuid()):
        raise ValueError('guard peer uid differs from the admitted QEMU owner')
    # Supervision publishes the CID before renaming this unique launch to the
    # familiar macos-sequoia name. The descriptor may arrive on either side.
    identity = vm/'run'/(name+'.cid')
    until = time.monotonic()+10
    while not identity.is_file():
        if time.monotonic() >= until:
            raise ValueError('guard launch CID was not published')
        time.sleep(0.01)
    cid = identity.read_text().strip()
    if not re.fullmatch('[0-9a-f]{64}', cid):
        raise ValueError('guard launch CID is malformed')
    info = json.loads(subprocess.check_output(
        ['docker', 'inspect', '--format', '{{json .}}', cid], text=True, timeout=5))
    if (info['Id'] != cid or info['Name'] not in ('/' + name, '/macos-sequoia') or
            info['State']['Running'] is not True):
        raise ValueError('guard container identity')
    if cid not in Path(f'/proc/{pid}/cgroup').read_text():
        raise ValueError('guard peer outside admitted container')
    cmdline = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
    if not cmdline or Path(os.fsdecode(cmdline[0])).name != 'qemu-system-x86_64':
        raise ValueError('guard peer is not QEMU')
    return {'pid': pid, 'uid': uid, 'gid': gid, 'cid': cid,
            'started_at': info['State']['StartedAt']}


def serve(vm, name):
    if not re.fullmatch(r'rgpu-launch-[0-9a-f]{32}', name):
        raise ValueError('guard requires a unique supervised launch name')
    directory = vm.resolve() / 'run/dma-guards'
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    endpoint = directory / (name + '.sock')
    receipt_path = directory / (name + '.json')
    receipt = {'schema': 2, 'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
               'launch_name': name, 'device': DEVICE, 'status': 'waiting',
               'authorizes_launch': False, 'helper_sha256': source_hashes()}
    held_fds = []
    # Service stop cannot drop ownership while DMA is unproved. The VM's own
    # service deadline still stops guest execution independently.
    def terminated(*_):
        if not held_fds:
            raise SystemExit('guard stopped before device ownership')
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, terminated)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    try:
        listener.bind(str(endpoint))  # Existing socket is a refusal, never unlink it.
        os.chmod(endpoint, 0o600)
        listener.listen(1)
        listener.settimeout(90)
        write_receipt(receipt_path, receipt)
        connection, _ = listener.accept()
        with connection:
            connection.settimeout(10)
            data, ancillary, flags, _ = connection.recvmsg(4, socket.CMSG_SPACE(4), socket.MSG_CMSG_CLOEXEC)
            for level, kind, payload in ancillary:
                if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                    descriptors = array.array('i')
                    descriptors.frombytes(payload[:len(payload) - len(payload) % descriptors.itemsize])
                    held_fds.extend(descriptors)
            if data != b'RIG1' or flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC) or len(held_fds) != 1:
                raise ValueError('guard descriptor protocol')
            receipt.update(status='owned', peer=peer_identity(connection, name, vm))
            device = Device(held_fds[0])
            pidfd = os.pidfd_open(receipt['peer']['pid'])
            write_receipt(receipt_path, receipt)
            connection.sendall(b'ARM1')
            connection.settimeout(None)
            command = connection.recv(4)
            if command != b'STOP':
                # EOF alone is not process death. Retain the IOMMU context until
                # all QEMU threads, including KVM vCPUs, have exited.
                poll = select.poll()
                poll.register(pidfd, select.POLLIN)
                poll.poll()
                receipt['trigger'] = 'qemu-death'
            else:
                receipt['trigger'] = 'qemu-stopped-exit-hook'
            receipt.update(quiesce(device), status='quiesced')
            write_receipt(receipt_path, receipt)
            # Normal QEMU waits for this ACK before VFIO listener unmaps RAM.
            if command == b'STOP':
                connection.sendall(b'SAFE')
            os.close(pidfd)
        for fd in held_fds:
            os.close(fd)
        held_fds.clear()
        receipt.update(status='released', released_monotonic=time.monotonic())
        write_receipt(receipt_path, receipt)
    except BaseException as error:
        receipt.update(status='retained' if held_fds else 'failed-before-ownership',
                       error=f'{type(error).__name__}: {error}')
        try:
            write_receipt(receipt_path, receipt)
        finally:
            if held_fds:
                # Preserve the kernel DMA context on every error. An operator
                # can inspect the receipt; never turn a cleanup error into DMA
                # hitting the host identity domain by unwinding/closing the fd.
                while True:
                    signal.pause()
        raise
    finally:
        listener.close()
        if not held_fds:
            endpoint.unlink(missing_ok=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vm-dir', type=Path, required=True)
    parser.add_argument('--name', required=True)
    args = parser.parse_args()
    serve(args.vm_dir, args.name)
