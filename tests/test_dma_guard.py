"""Real SCM_RIGHTS/pidfd lifetime checks with a memfd, never a host device."""
import array
import importlib.util
import json
import multiprocessing
import os
from pathlib import Path
import socket
import struct
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('guard', ROOT/'tools/dma-guard.py')
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)
NAME = 'rgpu-launch-' + 'd'*32
CID = 'a'*64


def serve_memfd(vm, fail_write=False):
    class MemfdDevice:
        def __init__(self, fd):
            self.fd = fd

        def read32(self, offset):
            return struct.unpack('<I', os.pread(self.fd, 4, offset))[0]

        def write32(self, offset, value):
            if not fail_write or (fail_write == 'engine' and offset != dict((n, o) for n, o, _, _ in guard.ENGINES.CONTROLS)['me']):
                os.pwrite(self.fd, struct.pack('<I', value), offset)

    def peer(connection, _, _vm):
        pid, uid, gid = struct.unpack('3i', connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        return {'pid': pid, 'uid': uid, 'gid': gid, 'cid': CID, 'started_at': 'fixture'}
    guard.Device = MemfdDevice
    guard.peer_identity = peer
    guard.serve(Path(vm), NAME)


def connect(endpoint, fd):
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    connection.settimeout(3)
    connection.connect(str(endpoint))
    connection.sendmsg([b'RIG1'], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array('i', [fd]))])
    if connection.recv(4) != b'ARM1':
        raise RuntimeError('guard did not arm')
    return connection


def dying_client(endpoint, fd):
    connection = connect(endpoint, fd)
    # Simulate _exit/SIGKILL: no STOP request or QEMU exit hook.
    os._exit(0)


class GuardLifetimeTests(unittest.TestCase):
    def test_peer_binding_survives_supervised_container_rename(self):
        left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        try:
            for name in ('/'+NAME, '/macos-sequoia'):
                info = {'Id': CID, 'Name': name, 'State': {'Running': True, 'StartedAt': 'fixture'}}
                with patch.object(guard.Path, 'is_file', return_value=True), \
                     patch.object(guard.Path, 'read_text', autospec=True,
                        side_effect=lambda p: CID if p.name.endswith('.cid') else 'docker-'+CID+'.scope'), \
                     patch.object(guard.Path, 'read_bytes', return_value=b'qemu-system-x86_64\0'), \
                     patch.object(guard.subprocess, 'check_output', return_value=json.dumps(info)) as inspect:
                    peer = guard.peer_identity(left, NAME, Path('/fixture'))
                    self.assertEqual(peer['cid'], CID)
                    self.assertEqual(inspect.call_args.args[0][-1], CID)
        finally:
            left.close()
            right.close()

    def exercise(self, mode):
        context = multiprocessing.get_context('fork')
        with tempfile.TemporaryDirectory() as tmp:
            vm = Path(tmp)
            endpoint = vm/'run/dma-guards'/(NAME+'.sock')
            receipt = endpoint.with_suffix('.json')
            fd = os.memfd_create('DMA-GUARD-TEST-NOT-A-DEVICE')
            os.ftruncate(fd, 0x20000)
            os.pwrite(fd, struct.pack('<I', 1), dict(guard.ENGINES.STATUS)['sdma'])
            for control, _, _ in guard.IH.RINGS:
                os.pwrite(fd, struct.pack('<I', 0x1033011f), (guard.IH.BASE+control)*4)
            for offset in guard.DISPLAY_STOPS:
                os.pwrite(fd, struct.pack('<I', 0x21), offset)
            server = context.Process(target=serve_memfd, args=(tmp, 'engine' if mode == 'engine-failure' else mode == 'failure'))
            server.start()
            try:
                until = time.monotonic()+3
                while not receipt.exists():
                    self.assertLess(time.monotonic(), until)
                    time.sleep(0.01)
                if mode == 'death':
                    client = context.Process(target=dying_client, args=(endpoint, fd))
                    client.start()
                    client.join(3)
                    self.assertEqual(client.exitcode, 0)
                else:
                    with connect(endpoint, fd) as connection:
                        connection.sendall(b'STOP')
                        if mode not in ('failure', 'engine-failure'):
                            self.assertEqual(connection.recv(4), b'SAFE')
                until = time.monotonic()+3
                while True:
                    value = json.loads(receipt.read_text())
                    if value['status'] in ('released', 'retained'):
                        break
                    self.assertLess(time.monotonic(), until)
                    time.sleep(0.01)
                if mode in ('failure', 'engine-failure'):
                    self.assertEqual(value['status'], 'retained')
                    self.assertTrue(server.is_alive())
                    self.assertIn('readback mismatch', value['error'])
                    self.assertTrue(any('DMA-GUARD-TEST-NOT-A-DEVICE' in str(p.readlink())
                                        for p in Path(f'/proc/{server.pid}/fd').iterdir()))
                else:
                    server.join(3)
                    self.assertEqual(server.exitcode, 0)
                    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
                    self.assertEqual(guard.validate_receipt(value, boot, CID), [])
                    self.assertEqual(value['trigger'], 'qemu-death' if mode == 'death'
                                     else 'qemu-stopped-exit-hook')
                    for control, _, mask in guard.IH.RINGS:
                        value = struct.unpack('<I', os.pread(fd, 4, (guard.IH.BASE+control)*4))[0]
                        self.assertFalse(value & mask)
            finally:
                if server.is_alive():
                    server.kill()  # Only the explicitly created memfd fixture.
                server.join(3)
                os.close(fd)

    def test_native_exit_acknowledges_before_release(self):
        self.exercise('native')

    def test_process_death_quiesces_with_retained_descriptor(self):
        self.exercise('death')

    def test_failed_engine_halt_retains_descriptor_and_refuses_ack(self):
        self.exercise('engine-failure')

    def test_failed_readback_retains_descriptor_and_refuses_ack(self):
        self.exercise('failure')


if __name__ == '__main__':
    unittest.main()
