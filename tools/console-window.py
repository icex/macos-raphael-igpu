#!/usr/bin/env python3
"""Open the running experiment's QEMU console in a local desktop window."""
import argparse
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess


def console_endpoint(vm, state, container, mode="bochs"):
    if (not container.get('State', {}).get('Running') or
            container.get('Id') != state.get('cid') or
            container['State'].get('StartedAt') != state.get('started_at')):
        raise ValueError('the supervised VM is no longer running with this identity')
    env = container.get('Config', {}).get('Env', [])
    if mode not in ('bochs', 'bochs-spice') or [v for v in env if v.startswith('VM_CONSOLE=')] != ['VM_CONSOLE='+mode]:
        raise ValueError('the running VM does not select the Bochs console')
    sock = vm / ('run/console-spice.sock' if mode == 'bochs-spice' else 'run/console-vnc.sock')
    info = sock.lstat()
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
        raise ValueError('console endpoint must be a local socket owned by this user')
    return sock


def viewer_command(vm, state, container, viewer):
    sock = console_endpoint(vm, state, container)
    # Window closure disconnects only this viewer. The harness retains VM ownership.
    # Resize must be coordinated with the macOS presenter, not sent to QEMU alone.
    return [viewer, '-Shared', '-RemoteResize=0', '-FullScreen=0',
            '-AcceptClipboard=0', '-SendClipboard=0', '-SendPrimary=0', str(sock)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vm-dir', type=Path, default=Path.home()/'macos-vm')
    parser.add_argument('--state', type=Path, required=True,
                        help='the active experiment results/supervision.json')
    parser.add_argument('--check', action='store_true', help='validate without opening a window')
    args = parser.parse_args()
    try:
        viewer = shutil.which('vncviewer')
        if not viewer:
            raise ValueError('TigerVNC vncviewer is required')
        state = json.loads(args.state.read_text())
        container = json.loads(subprocess.check_output(
            ['docker', 'inspect', state['cid']], text=True, timeout=10))[0]
        command = viewer_command(args.vm_dir.resolve(), state, container, viewer)
        if args.check:
            print(json.dumps({'ready': True, 'command': command}))
            return
        if not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
            raise ValueError('run this command from the Linux desktop session')
        os.execv(viewer, command)
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as error:
        parser.exit(1, f'console-window: {error}\n')


if __name__ == '__main__':
    main()
