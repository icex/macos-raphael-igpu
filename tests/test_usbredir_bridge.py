import os
import pathlib
import socket
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
BRIDGE = ROOT / 'tools/rgpu-usbredir-bridge.py'

# A stand-in usbredirect: records the --to address and, when asked, connects itself.
FAKE = r'''#!/usr/bin/env python3
import os, socket, sys, time
to = sys.argv[sys.argv.index('--to') + 1]
open(os.environ['FAKE_RECORD'], 'w').write(to)
if os.environ.get('FAKE_CONNECT') == '1':
    host, port = to.split(':')
    s = socket.create_connection((host, int(port)))
    s.sendall(b'hello-guest')
    time.sleep(2)
else:
    time.sleep(5)
'''


class UsbredirBridgeTests(unittest.TestCase):
    def run_bridge(self, connect_self):
        with tempfile.TemporaryDirectory() as d:
            d = pathlib.Path(d)
            (d / 'usbredirect').write_text(FAKE)
            (d / 'usbredirect').chmod(0o755)
            record = d / 'to.txt'
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.bind(str(d / 'slot.sock'))
            server.listen(1)
            env = dict(os.environ, PATH=f'{d}:{os.environ["PATH"]}', FAKE_RECORD=str(record),
                       FAKE_CONNECT='1' if connect_self else '0')
            bridge = subprocess.Popen([sys.executable, '-B', str(BRIDGE), str(d / 'slot.sock'), '0951:1666'],
                                      env=env, stderr=subprocess.PIPE)
            qemu, _ = server.accept()
            for _ in range(100):
                if record.exists() and record.read_text():
                    break
                time.sleep(0.05)
            intruder = None
            if not connect_self:
                host, port = record.read_text().split(':')
                intruder = socket.create_connection((host, int(port)))
                intruder.sendall(b'fake-device')
            qemu.settimeout(5)
            try:
                received = qemu.recv(64)
            except socket.timeout:
                received = b''
            bridge.wait(15)
            if intruder:
                intruder.close()
            return received, bridge.returncode, bridge.stderr.read()

    def test_relays_only_from_the_spawned_usbredirect(self):
        received, code, _ = self.run_bridge(connect_self=True)
        self.assertEqual(received, b'hello-guest')
        self.assertEqual(code, 0)

    def test_refuses_a_foreign_connection(self):
        received, code, err = self.run_bridge(connect_self=False)
        self.assertEqual(received, b'')
        self.assertNotEqual(code, 0)
        self.assertIn(b'refusing', err)


if __name__ == '__main__':
    unittest.main()
