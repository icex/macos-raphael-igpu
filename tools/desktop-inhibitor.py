#!/usr/bin/env python3
"""Own the preflight inhibitor container for one desktop launcher service.

Run under systemd-inhibit; the container is a legacy preflight gate, not a
logind inhibitor. ExecStopPost invokes --cleanup after abnormal service exit.
"""
import argparse
import fcntl
import json
import signal
import subprocess
import sys
from pathlib import Path


def docker(*args):
    return subprocess.run(['docker', *args], check=True, timeout=30)


def session(name, command, cleanup=False):
    if cleanup:
        docker('stop', '--timeout', '5', name)
        return 0
    child = None

    def stop(signum, _frame):
        # Preserve the service's normal termination semantics; never reset a GPU.
        if child is not None:
            child.send_signal(signum)
        else:
            raise SystemExit(128 + signum)

    for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(signum, stop)
    try:
        # A previous always-on helper must not restart at the next host boot.
        docker('update', '--restart=no', name)
        docker('start', name)
        child = subprocess.Popen(command)
        code = child.wait()
        return 128 - code if code < 0 else code
    finally:
        docker('stop', '--timeout', '5', name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pins', type=Path, required=True)
    parser.add_argument('--owner', required=True)
    parser.add_argument('--cleanup', action='store_true')
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    pins = json.loads(args.pins.read_text())
    name = pins['inhibitor_container']
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not args.cleanup and not command:
        parser.error('a session command is required')
    # Also excludes simultaneous clicks and prevents stale cleanup from stopping
    # the helper owned by another desktop session.
    lock = Path(pins['vm_dir']) / 'run' / 'desktop-inhibitor.lock'
    with lock.open('a+') as stream:
        try:
            # ExecStopPost can overlap the original process's finally block.
            # Wait for that cleanup, then check the owner before touching Docker.
            fcntl.flock(stream, fcntl.LOCK_EX if args.cleanup else
                        fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('another desktop session owns the inhibitor')
        stream.seek(0)
        if args.cleanup:
            if stream.read() != args.owner:
                return 0
        else:
            stream.truncate(0)
            stream.write(args.owner)
            stream.flush()
        return session(name, command, args.cleanup)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        print(f'desktop inhibitor: {error}', file=sys.stderr)
        sys.exit(1)
