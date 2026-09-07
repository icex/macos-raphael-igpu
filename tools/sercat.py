#!/usr/bin/env python3
"""Drain the guest serial port into run/serial.log."""
import socket, sys, time
import os, os.path
VM = os.path.dirname(os.path.abspath(__file__))
p = os.environ.get("VM_SERIAL", os.path.join(VM, "run", "serial.sock"))
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
with open(os.path.join(VM, "run", "serial.log"), "ab", buffering=0) as f:
    while True:
        try:
            d = s.recv(65536)
            if not d: break
            f.write(d)
            os.fsync(f.fileno())
        except socket.timeout: pass
        except Exception: break
