#!/usr/bin/env python3
"""Drain the guest serial port into run/serial.log."""
import socket, sys, time
import os, os.path
VM = os.path.dirname(os.path.abspath(__file__))
channel = os.environ.get("VM_SERIAL_CHANNEL")
if channel is not None and channel not in ("console", "critical"):
    sys.exit("invalid serial channel")
p = os.environ.get("VM_SERIAL_SOCKET", os.environ.get(
    "VM_SERIAL", os.path.join(VM, "run", "serial.sock")))
output = os.environ.get("VM_SERIAL_OUTPUT", os.path.join(VM, "run", "serial.log"))
for _ in range(60):
    try:
        s = socket.socket(socket.AF_UNIX); s.connect(p); break
    except Exception: time.sleep(1)
else:
    sys.exit("no serial socket")
s.settimeout(1)
# fsync every chunk, not just buffering=0.
#
# The host has hard-hung twice with the VM running, and both times this log was the only
# place that could have said where the guest was -- and both times it was useless.
# buffering=0 gets the bytes out of Python, but they then sit in the page cache until btrfs
# commits, so the last tens of seconds before a hang are lost: after the second crash the
# file ended at "BdsDxe: starting Boot0001" with 304 bytes, which says nothing about how far
# the guest actually got. An fsync per chunk costs nothing at these volumes (a few hundred
# kilobytes over a boot) and is the difference between having evidence and guessing.
with open(output, "ab", buffering=0) as f:
    # Optional launch-specific proof: published only after connect and log open.
    ready = os.environ.get("VM_SERIAL_READY")
    if ready:
        with open(ready, "w") as marker:
            token = os.environ["VM_SERIAL_CID"]
            marker.write(token if channel is None else token + " " + channel)
    while True:
        try:
            d = s.recv(65536)
            if not d: break
            f.write(d)
            os.fsync(f.fileno())
        except socket.timeout: pass
        except Exception: break
