#!/usr/bin/env python3
"""CPU-only end-to-end qualification for the dedicated COM2 CR2 transport."""

import hashlib
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUEST_SOURCE = ROOT / "tests/fixtures/com2-guest.c"
GUEST_LINKER = ROOT / "tests/fixtures/com2-guest.ld"
BUILD_ID = "0123456789abcdef0123456789abcdef"


GENERATOR_SOURCE = r'''
#include "src/CriticalReplay.hpp"
#include <array>
#include <cstdio>
#include <cstring>

namespace CR = rgpu::CriticalReplayV2;
int main() {
    static std::array<std::array<char, CR::kRecordStorageBytes>,
                      CR::kMaximumRecords> records {};
    for (size_t record = 0; record < records.size(); ++record) {
        for (size_t byte = 0; byte < CR::kRecordStorageBytes - 1; ++byte)
            records[record][byte] = static_cast<char>('!' + ((record + byte) % 94));
    }
    const auto read = [&](size_t sequence,
                          char (&out)[CR::kRecordStorageBytes]) {
        std::memcpy(out, records[sequence].data(), sizeof(out));
        return true;
    };
    const auto emit = [](const char *line) { std::printf("%s\n", line); };
    if (!CR::emitSnapshot("0123456789abcdef0123456789abcdef",
                          0x01020303, 1, 0, 0, read, emit)) return 1;
    return CR::emitSnapshot("0123456789abcdef0123456789abcdef",
                            0x01020304, CR::kMaximumRecords, 0, 0,
                            read, emit) ? 0 : 1;
}
'''


def run_checked(args, *, cwd=None, timeout=30, text=False):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True,
                          timeout=timeout, text=text)


def build_fixture(work):
    generator = work / "generator.cpp"
    generator.write_text(GENERATOR_SOURCE)
    generator_bin = work / "generator"
    run_checked(["g++", "-std=c++17", "-O2", "-I", str(ROOT),
                 str(generator), "-o", str(generator_bin)])
    payload = work / "payload.bin"
    payload.write_bytes(run_checked([str(generator_bin)]).stdout)

    run_checked(["objcopy", "-I", "binary", "-O", "elf32-i386",
                 "-B", "i386", "payload.bin", "payload.o"], cwd=work)
    run_checked(["gcc", "-m32", "-Os", "-ffreestanding", "-fno-pic",
                 "-fno-pie", "-fno-stack-protector", "-nostdlib", "-c",
                 str(GUEST_SOURCE), "-o", "guest.o"], cwd=work)
    guest = work / "com2-guest.elf"
    run_checked(["ld", "-m", "elf_i386", "-T", str(GUEST_LINKER),
                 "-o", str(guest), "guest.o", "payload.o"], cwd=work)
    return payload, guest


def load_replay():
    path = ROOT / "tools/critical-replay.py"
    spec = importlib.util.spec_from_file_location("critical_replay_qualification", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def wait_for(predicate, message, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError(message)


def qmp_cont(path):
    client = socket.socket(socket.AF_UNIX)
    client.settimeout(3)
    client.connect(str(path))
    client.recv(4096)
    client.sendall(b'{"execute":"qmp_capabilities"}\n')
    client.recv(4096)
    client.sendall(b'{"execute":"cont"}\n')
    client.recv(4096)
    client.close()


def validate_captures(console, critical):
    ready = ("RGPU_UART_READY v=1 b=" + BUILD_ID + " port=2\n").encode()
    if not critical.startswith(ready):
        raise AssertionError("COM2 producer readiness is absent or conflicting")
    if b"COM1-BEGIN\n" not in console or b"COM1-END\n" not in console:
        raise AssertionError("COM1 flood did not complete")
    if b"RGPU_CR2 v=1 b=broken" not in console:
        raise AssertionError("COM1 malformed CR2 fixture is absent")
    return load_replay().parse(critical[len(ready):].decode("ascii"), BUILD_ID)


class SupervisedQemu:
    IMAGE = "sha256:3a3c82c79bc4e73531f819ccdfa4053b3084efd7c1f645678dbf8b4b3a24369c"

    def __init__(self, root, guest, *, swap_indices=False, swap_sockets=False,
                 missing_channel=None):
        self.root = root
        self.run_dir = root / "run"
        self.run_dir.mkdir(parents=True)
        shutil.copy2(ROOT / "tools/sercat.py", root / "sercat.py")
        shutil.copy2(guest, root / "com2-guest.elf")
        self.name = "rgpu-com2-qualification-" + next(tempfile._get_candidate_names())
        first, second = ((1, 0) if swap_indices else (0, 1))
        console_socket, critical_socket = (
            ("critical.sock", "serial.sock") if swap_sockets else
            ("serial.sock", "critical.sock"))
        qemu = [
            "-accel", "tcg", "-machine", "pc", "-cpu", "max", "-m", "16M",
            "-nodefaults", "-vga", "none", "-display", "none", "-no-reboot",
            "-net", "none", "-S",
            "-qmp", "unix:/run/com2/run/qmp.sock,server=on,wait=off",
        ]
        if missing_channel != "console":
            qemu += [
                "-chardev", f"socket,id=rgpu_console,path=/run/com2/run/{console_socket},server=on,wait=off",
                "-device", f"isa-serial,chardev=rgpu_console,index={first}"]
        if missing_channel != "critical":
            qemu += [
                "-chardev", f"socket,id=rgpu_critical,path=/run/com2/run/{critical_socket},server=on,wait=off",
                "-device", f"isa-serial,chardev=rgpu_critical,index={second}"]
        qemu += ["-device", "isa-debug-exit,iobase=0xf4,iosize=0x04",
                 "-kernel", "/run/com2/com2-guest.elf"]
        command = [
            "docker", "run", "-d", "--name", self.name, "--network", "none",
            "--mount", f"type=bind,src={root},dst=/run/com2",
            "--entrypoint", "/usr/sbin/qemu-system-x86_64", self.IMAGE, *qemu,
        ]
        self.cid = run_checked(command, text=True).stdout.strip()
        if len(self.cid) != 64:
            raise AssertionError("Docker did not return a full container ID")
        self.state = None

    def arm(self):
        for filename in ("qmp.sock", "serial.sock", "critical.sock"):
            wait_for(lambda f=filename: (self.run_dir / f).exists(),
                     f"QEMU did not create {filename}")
        result = run_checked([
            "python3", str(ROOT / "tools/vm-supervision.py"), "arm",
            "--vm-dir", str(self.root), "--cid", self.cid,
            "--max-seconds", "0", "--critical-serial",
        ], timeout=70, text=True)
        import json
        self.state = json.loads(result.stdout)
        return self.state

    def arm_without_socket_precheck(self):
        result = subprocess.run([
            "python3", str(ROOT / "tools/vm-supervision.py"), "arm",
            "--vm-dir", str(self.root), "--cid", self.cid,
            "--max-seconds", "0", "--critical-serial",
        ], timeout=70, text=True, capture_output=True)
        return result

    def cont(self):
        qmp_cont(self.run_dir / "qmp.sock")

    def running(self):
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Running}}", self.cid],
            capture_output=True, text=True)
        return result.returncode == 0 and result.stdout.strip() == "true"

    def stop_exact(self):
        subprocess.run(["docker", "stop", "--time", "0", self.cid],
                       capture_output=True, text=True)

    def cleanup(self):
        self.stop_exact()
        for stem in ("serial", "critical", "deadline"):
            subprocess.run(["systemctl", "--user", "stop",
                            f"rgpu-{stem}-{self.cid}.service"], capture_output=True)
            subprocess.run(["systemctl", "--user", "stop",
                            f"rgpu-{stem}-{self.cid}.timer"], capture_output=True)
        subprocess.run(["docker", "rm", "-f", self.cid], capture_output=True)

    def stop_collector(self, channel):
        unit = self.state[("serial" if channel == "console" else channel) + "_unit"]
        run_checked(["systemctl", "--user", "stop", unit], timeout=20)

    def read_logs(self):
        return ((self.run_dir / "serial.log").read_bytes(),
                (self.run_dir / "critical.log").read_bytes())


class CriticalTransportQualification(unittest.TestCase):
    def test_source_built_guest_fixture_is_present(self):
        self.assertTrue(GUEST_SOURCE.is_file(), "missing source-built COM2 guest")
        self.assertTrue(GUEST_LINKER.is_file(), "missing COM2 guest linker script")

    def test_maximum_fixture_uses_unchanged_formatter_and_parser(self):
        with tempfile.TemporaryDirectory(prefix="rgpu-com2-build-") as raw:
            payload, guest = build_fixture(Path(raw))
            data = payload.read_bytes()
            replay = load_replay()
            parsed = replay.parse(data.decode("ascii"), BUILD_ID)
            self.assertEqual(parsed["records"], [
                "".join(chr(ord("!") + ((record + byte) % 94))
                        for byte in range(511))
                for record in range(512)
            ])
            self.assertEqual(parsed["bytes"], 512 * 511)
            self.assertEqual(parsed["chunks"], 512 * 13)
            self.assertTrue(guest.is_file())
            # 8-N-1 consumes ten wire bits per byte at 115200 baud.
            minimum_seconds = len(data) * 10 / 115200
            self.assertGreater(minimum_seconds, 90)
            print("maximum CR2 fixture:", len(data), "bytes;",
                  f"{minimum_seconds:.3f}s nominal wire time; sha256",
                  hashlib.sha256(data).hexdigest())

    @unittest.skipUnless(shutil.which("docker") and shutil.which("systemd-run"),
                         "Docker and user systemd are required for the offline gate")
    def test_real_dual_collectors_and_supervisor_capture_isolated_channels(self):
        with tempfile.TemporaryDirectory(prefix="rgpu-com2-qualified-") as raw:
            work = Path(raw)
            payload, guest = build_fixture(work)
            vm = SupervisedQemu(work / "vm", guest)
            self.addCleanup(vm.cleanup)
            state = vm.arm()
            self.assertEqual(state["cid"], vm.cid)
            self.assertEqual(Path(state["serial_ready"]).read_text(), vm.cid + " console")
            self.assertEqual(Path(state["critical_ready"]).read_text(), vm.cid + " critical")
            started = time.monotonic()
            vm.cont()
            wait_for(lambda: not vm.running(), "tiny guest did not exit", timeout=30)
            wait_for(lambda: (vm.run_dir / "critical.log").stat().st_size >=
                     len(payload.read_bytes()), "critical collector lost bytes")
            console, critical = vm.read_logs()
            parsed = validate_captures(console, critical)
            self.assertEqual(len(parsed["records"]), 512)
            self.assertEqual(critical.split(b"\n", 1)[1], payload.read_bytes())
            self.assertLess(time.monotonic() - started, 30)
            vm.cleanup()
            self.assertFalse(vm.running())
            for name in ("serial.sock", "critical.sock", "qmp.sock"):
                path = vm.run_dir / name
                if path.exists():
                    probe = socket.socket(socket.AF_UNIX)
                    with self.assertRaises(OSError):
                        probe.connect(str(path))
                    probe.close()

    @unittest.skipUnless(shutil.which("docker") and shutil.which("systemd-run"),
                         "Docker and user systemd are required for the offline gate")
    def test_swapped_uart_indices_fail_producer_capture_acceptance(self):
        with tempfile.TemporaryDirectory(prefix="rgpu-com2-swapped-") as raw:
            work = Path(raw)
            _, guest = build_fixture(work)
            vm = SupervisedQemu(work / "vm", guest, swap_indices=True)
            self.addCleanup(vm.cleanup)
            vm.arm()
            vm.cont()
            wait_for(lambda: not vm.running(), "swapped guest did not exit", timeout=30)
            wait_for(lambda: (vm.run_dir / "serial.log").stat().st_size > 100000,
                     "swapped capture did not drain")
            console, critical = vm.read_logs()
            with self.assertRaisesRegex(AssertionError, "producer readiness"):
                validate_captures(console, critical)

    @unittest.skipUnless(shutil.which("docker") and shutil.which("systemd-run"),
                         "Docker and user systemd are required for the offline gate")
    def test_swapped_socket_paths_fail_producer_capture_acceptance(self):
        with tempfile.TemporaryDirectory(prefix="rgpu-com2-sockets-") as raw:
            work = Path(raw)
            _, guest = build_fixture(work)
            vm = SupervisedQemu(work / "vm", guest, swap_sockets=True)
            self.addCleanup(vm.cleanup)
            vm.arm()
            vm.cont()
            wait_for(lambda: not vm.running(), "socket-swapped guest did not exit", timeout=30)
            wait_for(lambda: (vm.run_dir / "serial.log").stat().st_size > 100000,
                     "socket-swapped capture did not drain")
            with self.assertRaisesRegex(AssertionError, "producer readiness"):
                validate_captures(*vm.read_logs())

    @unittest.skipUnless(shutil.which("docker") and shutil.which("systemd-run"),
                         "Docker and user systemd are required for the offline gate")
    def test_stale_ready_files_cannot_satisfy_new_arm(self):
        with tempfile.TemporaryDirectory(prefix="rgpu-com2-stale-") as raw:
            work = Path(raw)
            _, guest = build_fixture(work)
            vm = SupervisedQemu(work / "vm", guest)
            self.addCleanup(vm.cleanup)
            for stem in ("serial", "critical"):
                (vm.run_dir / f"{stem}-{vm.cid}.ready").write_text(
                    "f" * 64 + " " + ("console" if stem == "serial" else "critical"))
            state = vm.arm()
            self.assertEqual(Path(state["serial_ready"]).read_text(), vm.cid + " console")
            self.assertEqual(Path(state["critical_ready"]).read_text(), vm.cid + " critical")

    @unittest.skipUnless(shutil.which("docker") and shutil.which("systemd-run"),
                         "Docker and user systemd are required for the offline gate")
    def test_swapped_channel_tokens_refuse_verify_and_stop_exact_cid(self):
        with tempfile.TemporaryDirectory(prefix="rgpu-com2-token-") as raw:
            work = Path(raw)
            _, guest = build_fixture(work)
            vm = SupervisedQemu(work / "vm", guest)
            self.addCleanup(vm.cleanup)
            state = vm.arm()
            Path(state["serial_ready"]).write_text(vm.cid + " critical")
            state_file = work / "supervision.json"
            state_file.write_text(json.dumps(state))
            checked = subprocess.run([
                "python3", str(ROOT / "tools/vm-supervision.py"), "verify",
                "--state", str(state_file)], capture_output=True, text=True,
                timeout=20)
            self.assertNotEqual(checked.returncode, 0)
            wait_for(lambda: not vm.running(),
                     "token mismatch did not stop the exact container")
            inspected = run_checked([
                "docker", "inspect", "--format", "{{.Id}}", vm.cid],
                text=True).stdout.strip()
            self.assertEqual(inspected, vm.cid)

    @unittest.skipUnless(shutil.which("docker") and shutil.which("systemd-run"),
                         "Docker and user systemd are required for the offline gate")
    def test_forced_close_preserves_only_an_admissible_open_attempt(self):
        with tempfile.TemporaryDirectory(prefix="rgpu-com2-partial-") as raw:
            work = Path(raw)
            payload, guest = build_fixture(work)
            data = payload.read_bytes()
            first_end = data.index(b"RGPU_END2")
            first_end = data.index(b"\n", first_end) + 1
            ready_bytes = len(("RGPU_UART_READY v=1 b=" + BUILD_ID +
                               " port=2\n").encode())
            targets = (first_end + 8192, len(data) // 2, len(data) - 200000)
            for number, target in enumerate(targets):
                with self.subTest(offset=target):
                    vm = SupervisedQemu(work / f"vm-{number}", guest)
                    try:
                        vm.arm()
                        vm.cont()
                        log = vm.run_dir / "critical.log"
                        wait_for(lambda: log.exists() and log.stat().st_size >=
                                 ready_bytes + target,
                                 "collector did not reach forced-close offset", timeout=30)
                        vm.stop_exact()
                        wait_for(lambda: not vm.running(), "exact close did not stop QEMU")
                        captured = log.read_bytes()[ready_bytes:]
                        self.assertLess(len(captured), len(data))
                        replay = load_replay()
                        with self.assertRaises(replay.CriticalReplayError):
                            replay.parse(captured.decode("ascii"), BUILD_ID)
                        accepted = replay.parse(
                            captured.decode("ascii"), BUILD_ID,
                            tolerate_corruption=True, open_attempt=True)
                        self.assertEqual(accepted["snapshot"], 0x01020303)
                        self.assertIsNotNone(accepted["open_attempt"])
                        self.assertNotIn(
                            b"RGPU_END2 v=1 b=" + BUILD_ID.encode() +
                            b" s=01020304", captured)
                    finally:
                        vm.cleanup()

    @unittest.skipUnless(shutil.which("docker") and shutil.which("systemd-run"),
                         "Docker and user systemd are required for the offline gate")
    def test_either_collector_loss_stops_exact_cid(self):
        with tempfile.TemporaryDirectory(prefix="rgpu-com2-loss-") as raw:
            work = Path(raw)
            payload, guest = build_fixture(work)
            for number, channel in enumerate(("console", "critical")):
                with self.subTest(channel=channel):
                    vm = SupervisedQemu(work / f"vm-{number}", guest)
                    try:
                        vm.arm()
                        vm.cont()
                        log = vm.run_dir / ("critical.log" if channel == "critical"
                                            else "serial.log")
                        wait_for(lambda: log.exists() and log.stat().st_size > 10000,
                                 f"{channel} collector did not receive a prefix")
                        vm.stop_collector(channel)
                        wait_for(lambda: not vm.running(),
                                 f"{channel} loss did not stop exact container")
                        if channel == "critical":
                            self.assertLess(log.stat().st_size,
                                            len(payload.read_bytes()))
                    finally:
                        vm.cleanup()

    @unittest.skipUnless(shutil.which("docker") and shutil.which("systemd-run"),
                         "Docker and user systemd are required for the offline gate")
    def test_missing_either_socket_hits_shared_deadline_and_stops_exact_cid(self):
        with tempfile.TemporaryDirectory(prefix="rgpu-com2-missing-") as raw:
            work = Path(raw)
            _, guest = build_fixture(work)
            for number, channel in enumerate(("console", "critical")):
                with self.subTest(channel=channel):
                    vm = SupervisedQemu(work / f"vm-{number}", guest,
                                        missing_channel=channel)
                    try:
                        started = time.monotonic()
                        result = vm.arm_without_socket_precheck()
                        elapsed = time.monotonic() - started
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn("shared deadline", result.stderr)
                        self.assertGreaterEqual(elapsed, 59)
                        self.assertLess(elapsed, 70)
                        wait_for(lambda: not vm.running(),
                                 "missing collector did not stop exact container")
                    finally:
                        vm.cleanup()


if __name__ == "__main__":
    unittest.main(verbosity=2)
