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
import subprocess
import time
import uuid


UUID_PATTERN = r'[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}'


def parse_identity(output, nonce, expected_build):
    rows = re.findall(r'^RGPU_GUEST_ID ([0-9a-f]{32}) ('+UUID_PATTERN+r') (\S+)$',
                      output, re.M)
    if len(rows) != 1 or rows[0][0] != nonce or rows[0][2] != expected_build:
        raise ValueError('missing, stale, or ambiguous guest identity response')
    return rows[0][1]


def identity_command(nonce, expected_build):
    if not re.fullmatch(r'[0-9a-f]{32}', nonce) or not re.fullmatch(r'[0-9A-Za-z.]+', expected_build):
        raise ValueError('invalid request or expected guest build')
    return (f'permit=$(curl -fsS --max-time 2 http://10.0.2.2:8889/shutdown-permit-{nonce}) && '
            f'test "$permit" = {shlex.quote(nonce)} && '
            'build=$(sw_vers -buildVersion) && '
            f'test "$build" = {shlex.quote(expected_build)} && '
            f'printf "RGPU_GUEST_ID {nonce} %s %s\\n" "$(sysctl -n kern.bootsessionuuid)" "$build"')


def identify(vm, expected_build, timeout=8):
    vm = vm.resolve()
    nonce = uuid.uuid4().hex
    command = identity_command(nonce, expected_build)
    permit = vm / 'run' / ('shutdown-permit-'+nonce)
    pending = vm / 'run/cmd.txt'
    permit.write_text(nonce)
    try:
        result = subprocess.run([str(vm/'gx'), command], text=True, capture_output=True,
                                timeout=timeout+2,
                                env=dict(os.environ, GX_TIMEOUT=str(timeout)))
        if result.returncode:
            raise ValueError('guest identity transport failed')
        return parse_identity(result.stdout, nonce, expected_build)
    finally:
        permit.unlink(missing_ok=True)
        try:
            if pending.read_text() == command:
                pending.unlink(missing_ok=True)
        except FileNotFoundError:
            pass


def guarded_action(action, nonce, guest_boot):
    if not re.fullmatch(r'[0-9a-f]{32}', nonce) or not re.fullmatch(r'[0-9A-Fa-f-]{36}', guest_boot):
        raise ValueError('invalid request or guest identity')
    return (f'permit=$(curl -fsS --max-time 2 http://10.0.2.2:8889/shutdown-permit-{nonce}) && '
            f'test "$permit" = {shlex.quote(nonce)} && '
            f'test "$(sysctl -n kern.bootsessionuuid)" = {shlex.quote(guest_boot)} && '+action)


def load_supervisor():
    spec = importlib.util.spec_from_file_location(
        'supervisor', Path(__file__).with_name('vm-supervision.py'))
    supervisor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(supervisor)
    return supervisor


def shutdown(vm, state, expected_build, grace=20):
    if not 1 <= grace <= 20: raise ValueError('guest shutdown grace must be 1..20 seconds')
    vm = vm.resolve()
    supervisor = load_supervisor()
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
        guest_boot = None
        error = None
        try:
            if budget >= 2:
                guest_boot = identify(vm, expected_build, timeout=min(8, max(1, int(budget-1))))
                if not supervisor.same_start_running(state):
                    return dict(cid=state['cid'], outcome='exited-before-guest-request',
                                guest_boot_uuid=guest_boot)
                supervisor.verify(state)
                nonce = uuid.uuid4().hex
                command = guarded_action('/sbin/shutdown -h now', nonce, guest_boot)
                permit = vm / 'run' / ('shutdown-permit-'+nonce)
                pending = vm / 'run/cmd.txt'
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
        except Exception as failure:
            error = str(failure)
        finally:
            if requested:
                permit.unlink(missing_ok=True)
                try:
                    if pending.read_text() == command: pending.unlink(missing_ok=True)
                except FileNotFoundError: pass
        supervisor.stop_exact(state['cid'])
        return dict(cid=state['cid'], outcome='forced', request_sent=requested,
                    guest_boot_uuid=guest_boot,
                    request_id=nonce if requested else None, request_error=error)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vm-dir', type=Path, required=True)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--expected-build', required=True)
    args = parser.parse_args()
    print(json.dumps(shutdown(args.vm_dir, json.loads(args.state.read_text()),
                              args.expected_build), indent=2))
