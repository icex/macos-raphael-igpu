#!/usr/bin/env python3
"""Drain the guest serial port into run/serial.log."""
import re, socket, stat, sys, threading, time
import os, os.path
VM = os.path.dirname(os.path.abspath(__file__))
channel = os.environ.get("VM_SERIAL_CHANNEL")
if channel is not None and channel not in ("console", "critical"):
    sys.exit("invalid serial channel")
p = os.environ.get("VM_SERIAL_SOCKET", os.environ.get(
    "VM_SERIAL", os.path.join(VM, "run", "serial.sock")))
output = os.environ.get("VM_SERIAL_OUTPUT", os.path.join(VM, "run", "serial.log"))
cid = os.environ.get("VM_SERIAL_CID")
control = None
if channel == "critical" and cid is not None:
    if len(cid) != 64 or any(ch not in "0123456789abcdef" for ch in cid):
        sys.exit("invalid serial collector CID")
    control = os.path.join(os.path.dirname(output),
                           "critical-quiesce-" + cid + ".request")
for _ in range(60):
    try:
        s = socket.socket(socket.AF_UNIX); s.connect(p); break
    except Exception: time.sleep(1)
else:
    sys.exit("no serial socket")
s.settimeout(1)
# Make every received generation durable, not just visible through buffering=0.
#
# The host has hard-hung twice with the VM running, and both times this log was the only
# place that could have said where the guest was -- and both times it was useless.
# buffering=0 gets the bytes out of Python, but they then sit in the page cache until btrfs
# commits, so the last tens of seconds before a hang are lost: after the second crash the
# file ended at "BdsDxe: starting Boot0001" with 304 bytes, which says nothing about how far
# the guest actually got. The sync worker coalesces overlapping requests but does not mark a
# generation complete until fsync returns; this keeps filesystem latency out of socket drain.
with open(output, "ab", buffering=0) as f:
    condition = threading.Condition()
    sync = {"requested": 0, "completed": 0, "error": None, "stopping": False}

    def sync_log():
        # Keep socket draining independent of filesystem writeback. A generation
        # requested during fsync is deliberately synced again before exit.
        while True:
            with condition:
                condition.wait_for(
                    lambda: sync["requested"] > sync["completed"] or sync["stopping"])
                if sync["requested"] == sync["completed"] and sync["stopping"]:
                    return
                target = sync["requested"]
            try:
                os.fsync(f.fileno())
            except OSError as error:
                with condition:
                    sync["error"] = error
                    condition.notify_all()
                return
            with condition:
                sync["completed"] = target
                condition.notify_all()

    sync_thread = threading.Thread(target=sync_log, name="serial-log-sync", daemon=True)
    sync_thread.start()
    capture_error = None
    last_control_sent = None
    def send_quiesce_if_requested():
        if control is None or not os.path.exists(control):
            return last_control_sent
        descriptor = None
        try:
            descriptor = os.open(control, os.O_RDONLY | os.O_NONBLOCK |
                                 getattr(os, "O_NOFOLLOW", 0))
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 180:
                raise RuntimeError("invalid critical quiesce request")
            value = os.read(descriptor, 181)
        except FileNotFoundError:
            return last_control_sent
        except OSError as error:
            raise RuntimeError("critical quiesce request unreadable") from error
        finally:
            if descriptor is not None:
                os.close(descriptor)
        match = re.fullmatch(
            rb"RGPUQ2 v=1 cid=([0-9a-f]{64}) b=([0-9a-f]{32}) "
            rb"run=([0-9a-f]{32})\n", value)
        if match is None or match[1].decode() != cid:
            raise RuntimeError("invalid critical quiesce request")
        now = time.monotonic()
        if last_control_sent is None or now - last_control_sent >= 1:
            s.sendall(b"RGPUQ2\n")
            return now
        return last_control_sent
    try:
        # Optional launch-specific proof: published only after connect, log open,
        # and sync-worker start. The finally block also covers marker failures.
        ready = os.environ.get("VM_SERIAL_READY")
        if ready:
            with open(ready, "w") as marker:
                token = os.environ["VM_SERIAL_CID"]
                marker.write(token if channel is None else token + " " + channel)
        while True:
            with condition:
                if sync["error"] is not None:
                    break
            try:
                last_control_sent = send_quiesce_if_requested()
                d = s.recv(65536)
                if not d:
                    break
                view = memoryview(d)
                while view:
                    written = f.write(view)
                    if written is None or written <= 0:
                        raise OSError("serial log write made no progress")
                    view = view[written:]
                with condition:
                    sync["requested"] += 1
                    condition.notify()
            except socket.timeout:
                continue
            except Exception as error:
                capture_error = error
                break
    finally:
        with condition:
            sync["stopping"] = True
            condition.notify_all()
        sync_thread.join(10)
    if sync_thread.is_alive():
        sys.exit("serial log fsync did not finish within 10 seconds")
    if sync["error"] is not None:
        sys.exit("serial log fsync failed")
    if capture_error is not None:
        sys.exit("serial capture failed")
