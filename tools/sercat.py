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
with open(os.path.join(VM, "run", "serial.log"), "ab", buffering=0) as f:
    while True:
        try:
            d = s.recv(65536)
            if not d: break
            f.write(d)
        except socket.timeout: pass
        except Exception: break
