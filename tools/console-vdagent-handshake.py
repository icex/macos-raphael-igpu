#!/usr/bin/env python3
"""Bounded capability discovery only; no feature advertisement or device settings."""
import fcntl
import json
import os
import select
import signal
import stat
import struct
import termios
import time

DEVICE = '/dev/tty.com.redhat.spice.0'
CHUNK = struct.Struct('<II')
MESSAGE = struct.Struct('<IIQI')


def announcement(request, port=1):
    payload = struct.pack('<II', request, 0)
    message = MESSAGE.pack(1, 6, 0, len(payload)) + payload
    return CHUNK.pack(port, len(message)) + message


class Parser:
    """Preserve independent message assembly for client and server chunk ports."""
    def __init__(self):
        self.wire = bytearray()
        self.ports = {1: bytearray(), 2: bytearray()}

    def feed(self, data):
        self.wire.extend(data)
        found = []
        while len(self.wire) >= CHUNK.size:
            port, size = CHUNK.unpack_from(self.wire)
            if port not in self.ports or not 1 <= size <= 2048:
                raise ValueError('invalid chunk port/size')
            if len(self.wire) < CHUNK.size + size:
                break
            body = self.ports[port]
            body.extend(self.wire[CHUNK.size:CHUNK.size + size])
            del self.wire[:CHUNK.size + size]
            if len(body) < MESSAGE.size:
                continue
            protocol, kind, opaque, length = MESSAGE.unpack_from(body)
            if protocol != 1 or length > 4096:
                raise ValueError('invalid message protocol/size')
            total = MESSAGE.size + length
            if len(body) > total:
                raise ValueError('chunk crosses message boundary')
            if len(body) == total:
                # Only capability words leave this parser. Other payloads are discarded.
                item = dict(port=port, type=kind, size=length)
                if kind == 6:
                    if length < 4 or length % 4:
                        raise ValueError('malformed capability payload')
                    words = struct.unpack('<' + 'I' * (length // 4), body[MESSAGE.size:])
                    if words[0] not in (0, 1):
                        raise ValueError('invalid capability request flag')
                    item.update(request=words[0], caps=list(words[1:]))
                found.append(item)
                body.clear()
        return found


def exchange(fd, seconds=10, clock=time.monotonic):
    """fd is nonblocking and exclusively owned by caller. Does not close it."""
    start = clock()
    deadline = start + seconds
    parser = Parser()
    pending = bytearray(announcement(1))
    received = sent = responses = zeros = 0
    initial_sent = False
    arrivals = []
    unknown = []
    client_reply = False
    while clock() < deadline:
        timeout = max(0, min(.1, deadline - clock()))
        try:
            readable, writable, _ = select.select([fd], [fd] if pending else [], [], timeout)
        except InterruptedError:
            continue
        if writable:
            try:
                n = os.write(fd, pending)
            except (BlockingIOError, InterruptedError):
                n = 0
            if n:
                sent += n
                if sent > 256:
                    raise ValueError('transmit byte limit')
                del pending[:n]
                if sent >= len(announcement(1)):
                    initial_sent = True
        if readable:
            try:
                data = os.read(fd, min(4096, 65536 - received + 1))
            except (BlockingIOError, InterruptedError):
                continue
            if not data:
                if received:
                    raise EOFError('transport closed after traffic')
                zeros += 1
                # Opening may race host readiness; never busy-loop on initial EOF.
                time.sleep(min(.02, max(0, deadline - clock())))
                continue
            received += len(data)
            if received > 65536:
                raise ValueError('receive byte limit')
            for item in parser.feed(data):
                if item['type'] != 6:
                    if len(unknown) >= 128:
                        raise ValueError('unknown message count limit')
                    unknown.append(item)
                    continue
                if len(arrivals) >= 16:
                    raise ValueError('capability arrival count limit')
                arrivals.append(dict(**item, after_request_write=initial_sent,
                                     elapsed=clock() - start))
                if item['request']:
                    responses += 1
                    if responses > 4:
                        raise ValueError('capability response limit')
                    reply = announcement(0, item['port'])
                    if sent + len(pending) + len(reply) > 256:
                        raise ValueError('transmit byte limit')
                    pending.extend(reply)
                if item['port'] == 1 and initial_sent:
                    client_reply = True
        if client_reply and not pending:
            return dict(passed=True, received_bytes=received, transmitted_bytes=sent,
                        responses=responses, initial_zero_reads=zeros, arrivals=arrivals,
                        unhandled_metadata=unknown, elapsed=clock()-start,
                        scope='capability transport compatible; no nonce freshness, feature, resize or ownership qualification')
    raise TimeoutError('capability discovery deadline; client absence remains possible')


def identity(s):
    if not stat.S_ISCHR(s.st_mode):
        raise ValueError('exact endpoint is not a character device')
    return s.st_dev, s.st_ino, s.st_rdev


def main():
    import sys
    if len(sys.argv) != 1:
        raise ValueError('no arguments or alternate device paths accepted')
    if os.geteuid() == 0 or os.getuid() != os.geteuid():
        raise ValueError('ordinary nonroot uid required')
    def timeout(signum, frame):
        raise TimeoutError('whole-probe 10-second deadline')
    signal.signal(signal.SIGALRM, timeout)
    signal.setitimer(signal.ITIMER_REAL, 10)
    before = identity(os.lstat(DEVICE))
    fd = os.open(DEVICE, os.O_RDWR | os.O_NONBLOCK | os.O_NOCTTY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        if identity(os.fstat(fd)) != before or identity(os.lstat(DEVICE)) != before:
            raise ValueError('device identity changed at open')
        fcntl.ioctl(fd, termios.TIOCEXCL)
        result = exchange(fd)
        if identity(os.fstat(fd)) != before or identity(os.lstat(DEVICE)) != before:
            raise ValueError('device identity changed during exchange')
        result.update(euid=os.geteuid(), device=DEVICE, device_identity=list(before))
    finally:
        os.close(fd)
    signal.setitimer(signal.ITIMER_REAL, 0)
    print(json.dumps(result))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Never log incoming feature payload or arbitrary exception repr.
        print(json.dumps(dict(passed=False, error_type=type(error).__name__,
                              error=str(error) if isinstance(error, (ValueError, TimeoutError, EOFError)) else 'system call failed',
                              errno=getattr(error, 'errno', None))))
        raise SystemExit(2)
