#!/usr/bin/env python3
"""Native user501 control-v2 diagnostic. Each invocation performs ONE mode.

No-response observations establish framing behavior only. Root must retain
independent before/after CG mode observations to establish no mutation.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import stat
import sys
import time
import types


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('malformed', 'valid', 'no-eof'), required=True)
    parser.add_argument('--control-dir', type=Path, required=True)
    parser.add_argument('--module', type=Path, default=Path('/var/tmp/c390-addon/console-display-control.py'))
    parser.add_argument('--module-sha256', required=True)
    args = parser.parse_args()
    started = time.monotonic()
    deadline = started + 15
    evidence = dict(mode=args.mode, passed=False, phases=[],
                    scope='Protocol observations only; independent CG snapshots required for no-mutation proof')

    def record(phase, **fields):
        evidence['phases'].append(dict(phase=phase, elapsed=time.monotonic()-started, **fields))

    def remaining(cap):
        value = min(cap, deadline-time.monotonic())
        if value <= 0:
            raise TimeoutError('total diagnostic deadline')
        return value

    def alarm_handler(*_):
        raise TimeoutError('outer diagnostic alarm')

    signal.signal(signal.SIGALRM, alarm_handler)
    signal.alarm(18)
    try:
        if sys.platform != 'darwin' or os.geteuid() != 501:
            raise ValueError('requires native guest user501')
        path = args.module
        if not path.is_absolute() or path.resolve() != path:
            raise ValueError('module must be absolute and unaliased')
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, 'rb') as stream:
            metadata = os.fstat(stream.fileno())
            if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid not in (0, 501)
                    or metadata.st_mode & 0o022 or not 0 < metadata.st_size <= 1024*1024):
                raise ValueError('module identity/mode refused')
            source = stream.read(1024*1024+1)
        digest = hashlib.sha256(source).hexdigest()
        if digest != args.module_sha256:
            raise ValueError('module hash differs')
        control = types.ModuleType('reviewed_control')
        control.__file__ = str(path)
        exec(compile(source, str(path), 'exec'), control.__dict__)
        evidence['module_sha256'] = digest
        directory = args.control_dir
        if not directory.is_absolute() or directory.resolve() != directory:
            raise ValueError('control directory must be absolute and unaliased')
        endpoint = directory / 'control.sock'
        directory_id = control.identity(directory, stat.S_ISDIR, 0o700)
        endpoint_id = control.identity(endpoint, stat.S_ISSOCK, 0o600)
        sequence = secrets.randbelow(0xffffffff)+1
        request = control.REQUEST_V2.pack(control.MAGIC, 2, sequence, 1237, 745, 1)
        evidence.update(request_hex=request.hex(), requested=dict(pixel_width=1237, pixel_height=745, width=1237, height=745),
                        sequence=sequence, directory_identity=directory_id, endpoint_identity=endpoint_id)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as peer:
            peer.settimeout(remaining(2))
            peer.connect(str(endpoint))
            if control.peer_uid(peer) != 501:
                raise ValueError('wrong endpoint peer UID')
            if (control.identity(directory, stat.S_ISDIR, 0o700) != directory_id or
                    control.identity(endpoint, stat.S_ISSOCK, 0o600) != endpoint_id):
                raise ValueError('endpoint replaced during connect')
            record('connected', peer_uid=501)

            def send(data, phase):
                peer.settimeout(remaining(2));peer.sendall(data)
                record(phase, bytes=len(data), hex=data.hex())

            def quiet(phase):
                peer.settimeout(remaining(.2))
                try:
                    data = peer.recv(1)
                except socket.timeout:
                    record(phase, no_response=True, observation_seconds=.2)
                    return
                raise ValueError(phase + ': unexpected ' + ('EOF' if not data else 'response byte '+data.hex()))

            if args.mode == 'no-eof':
                send(request, 'full_frame_without_eof')
                quiet('no_eof_wait')
                # Do not close/half-close a complete valid frame: that would
                # deliver EOF and permit mutation. Let the server expire it.
                peer.settimeout(remaining(5.5))
                data = peer.recv(1)
                record('server_deadline_close', eof=data==b'', response_hex=data.hex())
                if data:
                    raise ValueError('response before client write-side EOF')
                evidence['passed'] = True
                evidence['scope'] += '; no-eof case waits for server-side deadline closure without client half-close'
            else:
                send(request[:20], 'prefix20')
                quiet('prefix20_wait')
                send(request[20:], 'scale_suffix4')
                quiet('full24_without_eof_wait')
                if args.mode == 'malformed':
                    send(b'\xff', 'trailing_byte')
                evidence['wire_hex'] = (request+(b'\xff' if args.mode == 'malformed' else b'')).hex()
                peer.shutdown(socket.SHUT_WR)
                record('write_eof')
                data = bytearray()
                while len(data) < control.REPLY.size:
                    peer.settimeout(remaining(5))
                    chunk = peer.recv(control.REPLY.size-len(data))
                    if not chunk:
                        raise EOFError('truncated reply')
                    data.extend(chunk)
                peer.settimeout(remaining(2))
                if peer.recv(1):
                    raise ValueError('extra reply bytes')
                reply = control.decode(bytes(data), sequence, 1237, 745, scale=1)
                record('reply', hex=bytes(data).hex(), fields=reply)
                if args.mode == 'malformed':
                    evidence['passed'] = reply['status'] == 1 and reply['passed'] is False
                else:
                    evidence['passed'] = reply['passed'] is True and reply['status'] == 0
        if (control.identity(directory, stat.S_ISDIR, 0o700) != directory_id or
                control.identity(endpoint, stat.S_ISSOCK, 0o600) != endpoint_id):
            raise ValueError('endpoint changed before final check')
    except Exception as error:
        evidence.update(passed=False, error_type=type(error).__name__, error=str(error))
    finally:
        signal.alarm(0)
    evidence['elapsed'] = time.monotonic()-started
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
