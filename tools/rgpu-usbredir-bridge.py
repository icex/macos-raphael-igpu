#!/usr/bin/env python3
"""Bridge the host's usbredirect to one of QEMU's usb-redir Unix sockets.

usbredirect only speaks TCP. QEMU's slot is a Unix socket in the run directory that only
its owner can open. This listens on an ephemeral loopback port, starts usbredirect for the
device, accepts exactly one connection and checks that the connecting socket belongs to
that usbredirect process (via /proc) before relaying, so no other local process can
present a USB device to the guest through the bridge.

usage: rgpu-usbredir-bridge.py UNIX_SOCKET VID:PID
"""
import os
import select
import signal
import socket
import subprocess
import sys
import time


def socket_inodes(pid):
    inodes = set()
    for fd in os.listdir(f'/proc/{pid}/fd'):
        try:
            target = os.readlink(f'/proc/{pid}/fd/{fd}')
        except OSError:
            continue
        if target.startswith('socket:['):
            inodes.add(target[8:-1])
    return inodes


def tcp_inode(local_port, remote_port):
    """Inode of the 127.0.0.1:remote_port -> 127.0.0.1:local_port client socket."""
    want_local = f'0100007F:{remote_port:04X}'
    want_remote = f'0100007F:{local_port:04X}'
    with open('/proc/net/tcp') as table:
        for line in table.readlines()[1:]:
            fields = line.split()
            if fields[1] == want_local and fields[2] == want_remote:
                return fields[9]
    return None


def main():
    # systemctl stop sends SIGTERM: unwind so usbredirect is stopped and the device returns
    # to its Linux drivers.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    path, device = sys.argv[1], sys.argv[2]
    unix = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    unix.connect(path)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(('127.0.0.1', 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    child = subprocess.Popen(['usbredirect', '--device', device, '--to', f'127.0.0.1:{port}'])
    listener.settimeout(10)
    conn, peer = listener.accept()
    listener.close()
    inode = None
    for _ in range(20):                     # the table entry appears with the connection
        inode = tcp_inode(port, peer[1])
        if inode:
            break
        time.sleep(0.05)
    if child.poll() is not None or inode is None or inode not in socket_inodes(child.pid):
        conn.close()
        child.terminate()
        sys.exit('refusing a connection that is not from the usbredirect we started')
    peers = {conn: unix, unix: conn}
    try:
        while child.poll() is None:
            ready, _, _ = select.select(list(peers), [], [], 1.0)
            for sock in ready:
                data = sock.recv(65536)
                if not data:
                    return
                peers[sock].sendall(data)
    finally:
        conn.close()
        unix.close()
        if child.poll() is None:
            child.terminate()
            child.wait(10)


if __name__ == '__main__':
    main()
