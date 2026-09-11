import os
import builtins
from pathlib import Path
import runpy
import socket
import tempfile
import threading
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "sercat.py"
CID = "a" * 64


class FakeSocket:
    def __init__(self, payload):
        self.payload = list(payload)
        self.connects = []
        self.sent = []

    def connect(self, path):
        self.connects.append(path)

    def settimeout(self, _seconds):
        pass

    def recv(self, _size):
        return self.payload.pop(0)

    def sendall(self, value):
        self.sent.append(value)


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

    def test_critical_quiesce_request_is_cid_bound_and_retransmitted(self):
        class IdleThenClose(FakeSocket):
            def recv(self, _size):
                value = self.payload.pop(0)
                if isinstance(value, BaseException):
                    raise value
                return value

        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            output = base / "critical.log"
            control = base / ("critical-quiesce-" + CID + ".request")
            control.write_text(
                f"RGPUQ2 v=1 cid={CID} b={'c'*32} run={'d'*32}\n")
            fake = IdleThenClose([socket.timeout(), socket.timeout(), b""])
            env = {"VM_SERIAL_SOCKET": str(base / "critical.sock"),
                   "VM_SERIAL_OUTPUT": str(output),
                   "VM_SERIAL_CHANNEL": "critical", "VM_SERIAL_CID": CID}
            with patch.dict(os.environ, env, clear=True), \
                 patch.object(socket, "socket", return_value=fake), \
                 patch("os.fsync"), \
                 patch("time.monotonic", side_effect=[0, 1, 2]):
                runpy.run_path(str(TOOL), run_name="__main__")
            self.assertEqual(fake.sent, [b"RGPUQ2\n"] * 3)

            control.write_text(
                f"RGPUQ2 v=1 cid={'b'*64} b={'c'*32} run={'d'*32}\n")
            rejected = FakeSocket([b""])
            with patch.dict(os.environ, env, clear=True), \
                 patch.object(socket, "socket", return_value=rejected), \
                 patch("os.fsync"), \
                 self.assertRaisesRegex(SystemExit, "serial capture failed"):
                runpy.run_path(str(TOOL), run_name="__main__")
            self.assertEqual(rejected.sent, [])

    def test_console_collector_never_reads_or_sends_quiesce_control(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            output = base / "console.log"
            (base / ("critical-quiesce-" + CID + ".request")).write_text(CID + "\n")
            fake = FakeSocket([b""])
            env = {"VM_SERIAL_SOCKET": str(base / "console.sock"),
                   "VM_SERIAL_OUTPUT": str(output),
                   "VM_SERIAL_CHANNEL": "console", "VM_SERIAL_CID": CID}
            with patch.dict(os.environ, env, clear=True), \
                 patch.object(socket, "socket", return_value=fake), \
                 patch("os.fsync"):
                runpy.run_path(str(TOOL), run_name="__main__")
            self.assertEqual(fake.sent, [])

    def test_request_removal_between_exists_and_open_is_benign(self):
        class IdleThenClose(FakeSocket):
            def recv(self, _size):
                value = self.payload.pop(0)
                if isinstance(value, BaseException):
                    raise value
                return value
        with tempfile.TemporaryDirectory() as td:
            base = Path(td); output = base / "critical.log"
            fake = IdleThenClose([socket.timeout(), b""])
            env = {"VM_SERIAL_SOCKET": str(base / "critical.sock"),
                   "VM_SERIAL_OUTPUT": str(output),
                   "VM_SERIAL_CHANNEL": "critical", "VM_SERIAL_CID": CID}
            control = base / ("critical-quiesce-" + CID + ".request")
            real_exists = os.path.exists
            def exists(path):
                return True if str(path) == str(control) else real_exists(path)
            with patch.dict(os.environ, env, clear=True), \
                 patch.object(socket, "socket", return_value=fake), \
                 patch("os.path.exists", side_effect=exists), \
                 patch("os.open", side_effect=FileNotFoundError()), \
                 patch("os.fsync"):
                runpy.run_path(str(TOOL), run_name="__main__")
            self.assertEqual(fake.sent, [])

    def test_slow_fsync_does_not_stop_socket_drain(self):
        """Durability I/O must not backpressure QEMU's UART socket."""
        fsync_started = threading.Event()
        second_recv = threading.Event()
        fsync_calls = []

        class BackpressureSocket(FakeSocket):
            assert_fsync_started = False

            def recv(self, size):
                if len(self.payload) == 2:
                    self.assert_fsync_started = fsync_started.wait(1)
                    second_recv.set()
                return super().recv(size)

        def slow_fsync(_fd):
            fsync_calls.append(True)
            fsync_started.set()
            if len(fsync_calls) == 1 and not second_recv.wait(1):
                raise OSError("collector stopped draining while fsync was blocked")

        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            output = base / "critical.log"
            fake = BackpressureSocket([b"first", b"second", b""])
            env = {
                "VM_SERIAL_SOCKET": str(base / "critical.sock"),
                "VM_SERIAL_OUTPUT": str(output),
                "VM_SERIAL_CHANNEL": "critical",
            }
            with patch.dict(os.environ, env, clear=True), \
                 patch.object(socket, "socket", return_value=fake), \
                 patch("os.fsync", side_effect=slow_fsync):
                runpy.run_path(str(TOOL), run_name="__main__")

            self.assertTrue(fake.assert_fsync_started)
            self.assertEqual(output.read_bytes(), b"firstsecond")
            self.assertEqual(len(fsync_calls), 2)

    def test_fsync_failure_is_reported_after_socket_drain(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            output = base / "critical.log"
            fake = FakeSocket([b"wire", b""])
            env = {
                "VM_SERIAL_SOCKET": str(base / "critical.sock"),
                "VM_SERIAL_OUTPUT": str(output),
                "VM_SERIAL_CHANNEL": "critical",
            }
            with patch.dict(os.environ, env, clear=True), \
                 patch.object(socket, "socket", return_value=fake), \
                 patch("os.fsync", side_effect=OSError("I/O error")), \
                 self.assertRaisesRegex(SystemExit, "serial log fsync failed"):
                runpy.run_path(str(TOOL), run_name="__main__")
            self.assertEqual(output.read_bytes(), b"wire")

    def test_fsync_failure_is_detected_while_socket_is_idle(self):
        fsync_called = threading.Event()

        class IdleSocket(FakeSocket):
            calls = 0

            def recv(self, _size):
                self.calls += 1
                if self.calls == 1:
                    return b"wire"
                fsync_called.wait(1)
                raise socket.timeout()

        def failed_fsync(_fd):
            fsync_called.set()
            raise OSError("I/O error")

        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            fake = IdleSocket([])
            env = {"VM_SERIAL_SOCKET": str(base / "critical.sock"),
                   "VM_SERIAL_OUTPUT": str(base / "critical.log"),
                   "VM_SERIAL_CHANNEL": "critical"}
            with patch.dict(os.environ, env, clear=True), \
                 patch.object(socket, "socket", return_value=fake), \
                 patch("os.fsync", side_effect=failed_fsync), \
                 self.assertRaisesRegex(SystemExit, "serial log fsync failed"):
                runpy.run_path(str(TOOL), run_name="__main__")
            self.assertEqual(fake.calls, 2)

    def test_ready_file_failure_stops_sync_worker(self):
        original_open = builtins.open
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            output = base / "critical.log"
            ready = base / "critical.ready"
            fake = FakeSocket([b""])
            env = {"VM_SERIAL_SOCKET": str(base / "critical.sock"),
                   "VM_SERIAL_OUTPUT": str(output), "VM_SERIAL_READY": str(ready),
                   "VM_SERIAL_CID": CID, "VM_SERIAL_CHANNEL": "critical"}

            def fail_ready(path, mode="r", *args, **kwargs):
                if str(path) == str(ready):
                    raise OSError("ready write failed")
                return original_open(path, mode, *args, **kwargs)

            with patch.dict(os.environ, env, clear=True), \
                 patch.object(socket, "socket", return_value=fake), \
                 patch("builtins.open", side_effect=fail_ready), \
                 self.assertRaisesRegex(OSError, "ready write failed"):
                runpy.run_path(str(TOOL), run_name="__main__")
            self.assertFalse(any(thread.name == "serial-log-sync"
                                 for thread in threading.enumerate()))

    def test_short_file_writes_are_completed_before_sync(self):
        original_open = builtins.open

        class ShortWriter:
            def __init__(self, wrapped):
                self.wrapped = wrapped

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return self.wrapped.__exit__(*args)

            def fileno(self):
                return self.wrapped.fileno()

            def write(self, data):
                return self.wrapped.write(data[:2])

        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            output = base / "critical.log"
            fake = FakeSocket([b"abcdef", b""])
            env = {"VM_SERIAL_SOCKET": str(base / "critical.sock"),
                   "VM_SERIAL_OUTPUT": str(output), "VM_SERIAL_CHANNEL": "critical"}

            def short_open(path, mode="r", *args, **kwargs):
                opened = original_open(path, mode, *args, **kwargs)
                return ShortWriter(opened) if str(path) == str(output) and mode == "ab" else opened

            with patch.dict(os.environ, env, clear=True), \
                 patch.object(socket, "socket", return_value=fake), \
                 patch("builtins.open", side_effect=short_open):
                runpy.run_path(str(TOOL), run_name="__main__")
            self.assertEqual(output.read_bytes(), b"abcdef")

    def test_socket_error_is_nonzero_capture_failure(self):
        fake = FakeSocket([OSError("socket failed")])
        fake.recv = lambda _size: (_ for _ in ()).throw(fake.payload[0])
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            env = {"VM_SERIAL_SOCKET": str(base / "critical.sock"),
                   "VM_SERIAL_OUTPUT": str(base / "critical.log"),
                   "VM_SERIAL_CHANNEL": "critical"}
            with patch.dict(os.environ, env, clear=True), \
                 patch.object(socket, "socket", return_value=fake), \
                 self.assertRaisesRegex(SystemExit, "serial capture failed"):
                runpy.run_path(str(TOOL), run_name="__main__")


if __name__ == "__main__":
    unittest.main()
