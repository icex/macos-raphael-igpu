#!/usr/bin/env python3
"""Exercise AppleSMC through QEMU qtest, without guest disks, KVM or VFIO."""
import argparse
import json
import pathlib
import socket
import subprocess
import tempfile
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("qemu")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as directory:
        sockpath = str(pathlib.Path(directory) / "qtest.sock")
        with open(pathlib.Path(directory) / "stderr", "w+") as log:
            process = subprocess.Popen([
                args.qemu, "-machine", "q35", "-accel", "tcg", "-S", "-nodefaults",
                "-display", "none", "-device", "isa-applesmc,osk=" + "x" * 64,
                "-qtest", f"unix:{sockpath},server=on,wait=off",
            ], stdout=log, stderr=log)
            try:
                deadline = time.monotonic() + 10
                while not pathlib.Path(sockpath).exists():
                    if process.poll() is not None or time.monotonic() > deadline:
                        log.seek(0)
                        raise RuntimeError(log.read())
                    time.sleep(0.02)
                with socket.socket(socket.AF_UNIX) as connection:
                    connection.settimeout(5)
                    connection.connect(sockpath)
                    stream = connection.makefile("rwb", buffering=0)

                    def command(text):
                        stream.write((text + "\n").encode())
                        reply = stream.readline().decode().strip()
                        assert reply.startswith("OK"), (text, reply)
                        return int(reply.split()[1], 0) if " " in reply else None

                    def out(port, value):
                        command(f"outb {port:#x} {value:#x}")

                    def inp(port):
                        return command(f"inb {port:#x}")

                    def request(op, argument, length, error=0):
                        out(0x304, op)
                        assert inp(0x304) == 0x0c
                        for byte in argument:
                            out(0x300, byte)
                            assert inp(0x304) == 4
                        out(0x300, length)
                        assert inp(0x31e) == error
                        assert inp(0x304) == (0 if error else 5)
                        if error:
                            return b""
                        data = bytes(inp(0x300) for _ in range(length))
                        assert inp(0x304) == 0
                        return data

                    keys = [request(0x12, index.to_bytes(4, "big"), 4)
                            for index in range(6)]
                    assert set(keys) == {b"REV ", b"OSK0", b"OSK1", b"NATJ", b"MSSP", b"MSSD"}
                    for index in (6, 7, 255, 256, 0xffffffff):
                        request(0x12, index.to_bytes(4, "big"), 4, 0xb8)
                    assert request(0x10, b"OSK0", 32) == b"x" * 32
                    assert request(0x10, b"OSK1", 32) == b"x" * 32
                    request(0x10, b"NONE", 1, 0x84)
                    assert request(0x12, bytes(4), 4) == keys[0]
                    # An interrupted command must retain the existing retry handshake.
                    out(0x304, 0x12)
                    out(0x300, 0)
                    out(0x304, 0x10)
                    assert inp(0x304) == 8 and inp(0x31e) == 0x80
                    assert request(0x10, b"OSK0", 32) == b"x" * 32
                    print(json.dumps({"passed": True, "keys": [key.decode() for key in keys],
                                      "checks": ["enumeration", "end-of-list", "large-index",
                                                 "existing-read", "error-recovery", "interruption"]}))
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == "__main__":
    main()
