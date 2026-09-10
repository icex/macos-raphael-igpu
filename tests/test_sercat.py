import os
from pathlib import Path
import runpy
import socket
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "sercat.py"
CID = "a" * 64


class FakeSocket:
    def __init__(self, payload):
        self.payload = list(payload)
        self.connects = []

    def connect(self, path):
        self.connects.append(path)

    def settimeout(self, _seconds):
        pass

    def recv(self, _size):
        return self.payload.pop(0)


class SercatTests(unittest.TestCase):
    def run_collector(self, channel, payload=b"wire\n"):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            sock = base / f"{channel}.sock"
            output = base / f"{channel}.log"
            ready = base / f"{channel}.ready"
            fake = FakeSocket([payload, b""])
            env = {
                "VM_SERIAL_SOCKET": str(sock), "VM_SERIAL_OUTPUT": str(output),
                "VM_SERIAL_READY": str(ready), "VM_SERIAL_CID": CID,
                "VM_SERIAL_CHANNEL": channel,
            }
            with patch.dict(os.environ, env, clear=True), \
                 patch.object(socket, "socket", return_value=fake), \
                 patch("os.fsync") as fsync:
                runpy.run_path(str(TOOL), run_name="__main__")
            return fake.connects, output.read_bytes(), ready.read_text(), fsync.call_count

    def test_explicit_critical_channel_isolated_and_durable(self):
        connects, captured, ready, fsyncs = self.run_collector("critical", b"CR2\x00\xff")
        self.assertEqual(Path(connects[0]).name, "critical.sock")
        self.assertEqual(captured, b"CR2\x00\xff")
        self.assertEqual(ready, CID + " critical")
        self.assertEqual(fsyncs, 1)

    def test_explicit_console_channel_binds_ready_identity(self):
        _, captured, ready, _ = self.run_collector("console")
        self.assertEqual(captured, b"wire\n")
        self.assertEqual(ready, CID + " console")

    def test_unknown_channel_refuses_before_connect(self):
        fake = FakeSocket([b""])
        with patch.dict(os.environ, {"VM_SERIAL_CHANNEL": "other"}, clear=True), \
             patch.object(socket, "socket", return_value=fake), \
             self.assertRaises(SystemExit):
            runpy.run_path(str(TOOL), run_name="__main__")
        self.assertEqual(fake.connects, [])


if __name__ == "__main__":
    unittest.main()
