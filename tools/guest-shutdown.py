#!/usr/bin/env python3
"""Request macOS root-agent poweroff for one identified guest; keep host caps armed."""
import argparse
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import time
import uuid


def guarded_action(action, nonce, guest_boot):
    if not re.fullmatch(r'[0-9a-f]{32}', nonce) or not re.fullmatch(r'[0-9A-Fa-f-]{36}', guest_boot):
        raise ValueError('invalid request or guest identity')
    return (f'permit=$(curl -fsS --max-time 2 http://10.0.2.2:8889/shutdown-permit-{nonce}) && '
            f'test "$permit" = {shlex.quote(nonce)} && '
            f'test "$(sysctl -n kern.bootsessionuuid)" = {shlex.quote(guest_boot)} && '+action)


def shutdown(vm, state, guest_boot, grace=20):
    if not 1 <= grace <= 20: raise ValueError('guest shutdown grace must be 1..20 seconds')
    spec = importlib.util.spec_from_file_location('supervisor', Path(__file__).with_name('vm-supervision.py'))
    supervisor = importlib.util.module_from_spec(spec); spec.loader.exec_module(supervisor)
    nonce = uuid.uuid4().hex
    command = guarded_action('/sbin/shutdown -h now', nonce, guest_boot)
    permit = vm / 'run' / ('shutdown-permit-'+nonce)
    pending = vm / 'run/cmd.txt'
    with (vm / 'run/metal-test.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if not supervisor.same_start_running(state):
            return dict(cid=state['cid'], outcome='already-stopped')
        supervisor.verify(state)
        budget = grace
        if state.get('deadline_epoch'):
            budget = min(budget, max(0, state['deadline_epoch']-time.time()-5))
        until = time.monotonic()+budget
        requested = False
        try:
            if budget >= 1:
                permit.write_text(nonce)
                temp = pending.with_name('shutdown-command-'+nonce)
                temp.write_text(command)
                temp.replace(pending)
                requested = True
                while time.monotonic() < until:
                    if not supervisor.same_start_running(state):
                        return dict(cid=state['cid'], outcome='exited-after-guest-request',
                                    guest_boot_uuid=guest_boot, request_id=nonce)
                    time.sleep(0.2)
        finally:
            permit.unlink(missing_ok=True)
            try:
                if pending.read_text() == command: pending.unlink(missing_ok=True)
            except FileNotFoundError: pass
        supervisor.stop_exact(state['cid'])
        return dict(cid=state['cid'], outcome='forced', request_sent=requested,
                    guest_boot_uuid=guest_boot, request_id=nonce)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vm-dir', type=Path, required=True)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--guest-identity', type=Path, required=True)
    args = parser.parse_args()
    identity = json.loads(args.guest_identity.read_text())
    print(json.dumps(shutdown(args.vm_dir, json.loads(args.state.read_text()),
                              identity['guest_boot_uuid']), indent=2))
