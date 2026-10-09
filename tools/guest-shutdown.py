#!/usr/bin/env python3
"""Request macOS root-agent poweroff for one identified guest; keep host caps armed."""
import argparse
import fcntl
import hashlib
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


def reconcile_exit(vm, state, result, supervisor=None):
    """Read-only final classification; never grants shutdown/recovery eligibility.

    Capture hooks persist after stop_exact, so this belongs after cleanup, not
    inside the first stopped-container polling observation. Missing evidence is
    explicitly unverified; no grace, retry, stop or synthesized terminal here.
    """
    if not result or result.get('outcome') not in (
            'exited-after-guest-request', 'exited-after-acpi-request'):
        return result
    result = dict(result, observed_outcome=result['outcome'])
    evidence = {'capture_receipts': [], 'errors': [], 'private_terminal_verified': False}
    result['exit_reconciliation'] = evidence
    supervisor = supervisor or load_supervisor()
    cid = state.get('cid', '')
    if not re.fullmatch('[0-9a-f]{64}', cid) or result.get('cid') != cid:
        result['outcome'] = 'exit-unverified-after-request'
        evidence['errors'].append('shutdown identity mismatch')
        return result
    forced = False
    run = Path(vm)/'run'
    # Two capture channels normally yield two receipts; bound malformed inventories.
    paths = list(run.glob('capture-exit-'+cid+'-*.json'))
    if len(paths) > 16:
        evidence['errors'].append('capture receipt inventory limit')
        paths = []
    for path in sorted(paths):
        try:
            if path.is_symlink() or path.stat().st_size > 65536:
                raise ValueError('unsafe receipt file')
            raw = path.read_bytes()
            receipt = json.loads(raw)
            if (receipt.get('cid') != cid or
                    receipt.get('started_at') != state.get('started_at') or
                    receipt.get('run_id') != state.get('libvirt_run_id') or
                    not state.get('libvirt_run_id')):
                raise ValueError('capture receipt binding mismatch')
            outcome = receipt.get('outcome')
            if outcome not in ('already-stopped', 'natural-container-exit',
                    'container-stopped-during-shutdown-wait', 'immediate-stop',
                    'shutdown-wait-expired', 'receipt-grace-expired'):
                raise ValueError('unknown capture outcome')
            evidence['capture_receipts'].append(dict(path=str(path),
                sha256=hashlib.sha256(raw).hexdigest(), outcome=outcome,
                channel=receipt.get('channel'),
                deferred=receipt.get('deferred'),
                shutdown_event_wait=receipt.get('shutdown_event_wait')))
            forced |= outcome in ('immediate-stop', 'shutdown-wait-expired',
                                  'receipt-grace-expired')
        except (OSError, ValueError, TypeError, AttributeError):
            evidence['errors'].append('invalid capture receipt: '+path.name)
    try:
        selected = ('{"Id":{{json .Id}},"StartedAt":{{json .State.StartedAt}},'
                    '"Running":{{json .State.Running}},"ExitCode":{{json .State.ExitCode}}}')
        info = json.loads(supervisor.run([supervisor.binary('docker'), 'inspect',
            '--format', selected, cid], timeout=2))
        if (info.get('Id') != cid or info.get('StartedAt') != state.get('started_at')
                or info.get('Running') is not False or type(info.get('ExitCode')) is not int):
            evidence['container_binding_mismatch'] = True
            raise ValueError('stopped container binding mismatch')
        evidence['container_exit_code'] = info['ExitCode']
    except Exception:
        evidence['errors'].append('stopped container inspection unavailable or mismatched')
    # Container removal is normal launcher cleanup. Retained private completion
    # plus every expected natural capture can establish temporal completion even
    # when Docker can no longer report an exit code. Never synthesize exit0.
    natural = evidence['capture_receipts']
    expected = ['console', 'critical'] if state.get('critical_enabled') else ['console']
    if (not forced and not any(e.startswith(('invalid capture', 'capture receipt'))
                             for e in evidence['errors']) and
            sorted(r['channel'] for r in natural if isinstance(r['channel'], str)) == expected and
            len(natural) == len(expected) and
            all(r['outcome'] == 'natural-container-exit' or
                (r['outcome'] == 'container-stopped-during-shutdown-wait' and
                 r['deferred'] is True and r['shutdown_event_wait'] is True)
                for r in natural)):
        try:
            run_id = state['libvirt_run_id']
            if not re.fullmatch('[0-9a-f]{32}', run_id):
                raise ValueError('invalid private run')
            directory = run/('libvirt-'+run_id)
            records = {}
            hashes = {}
            for name in ('running', 'terminal'):
                path = directory/(name+'.json')
                if directory.is_symlink() or path.is_symlink() or path.stat().st_size > 65536:
                    raise ValueError('unsafe private receipt')
                raw = path.read_bytes(); records[name] = json.loads(raw)
                hashes[name] = hashlib.sha256(raw).hexdigest()
            running, terminal = records['running'], records['terminal']
            for value in (running, terminal):
                if any(value.get(k) != v for k, v in dict(cid=cid,
                        started_at=state['started_at'], run_id=run_id).items()):
                    raise ValueError('private binding mismatch')
            identity = running['identity']; scope = running['scope']
            if (running.get('plan_sha256') != state.get('libvirt_plan_sha256') or
                    not re.fullmatch('[0-9a-f]{64}', state.get('libvirt_plan_sha256', '')) or
                    terminal.get('identity') != identity or terminal.get('scope') != scope or
                    not isinstance(identity, dict) or identity.get('run_id') != run_id or
                    identity.get('name') != 'rgpu-'+run_id or
                    any(type(identity.get(k)) is not int or identity[k] <= 0
                        for k in ('pid', 'start_ticks')) or
                    not re.fullmatch(UUID_PATTERN, identity.get('uuid', '')) or
                    not isinstance(scope, dict) or scope.get('kind') != 'pid-namespace' or
                    any(type(scope.get(k)) is not int or scope[k] <= 0
                        for k in ('device', 'inode', 'init_start_ticks')) or
                    terminal.get('reason') != 'guest-shutdown' or
                    terminal.get('process_exited') is not True):
                raise ValueError('private completion mismatch')
            evidence['private_terminal_verified'] = True
            evidence['private_receipt_sha256'] = hashes
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            evidence['errors'].append('private completion unavailable or mismatched')
    if forced:
        # A hook records its stop attempt after stop_exact; it does not prove
        # whether that command killed QEMU or raced an already completed exit.
        result['outcome'] = 'capture-abort-after-request'
    elif evidence.get('container_exit_code', 0) != 0:
        result['outcome'] = 'abnormal-exit-after-request'
    elif evidence.get('container_binding_mismatch'):
        result['outcome'] = 'exit-unverified-after-request'
    elif not evidence['private_terminal_verified'] and (
            evidence['errors'] or 'container_exit_code' not in evidence):
        result['outcome'] = 'exit-unverified-after-request'
    # Exit0 alone is only temporal evidence, not a private QEMU terminal proof.
    return result


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
        # The root agent is preferred because it proves the guest build and boot UUID,
        # but loss of that HTTP poller must not jump straight to killing QEMU. The
        # supervisor's ACPI path re-verifies the exact container and the QEMU peer of
        # its monitor socket before sending system_powerdown. That gives macOS a final,
        # bounded chance to execute the driver's native stop/power-off methods.
        remaining = max(0.0, until-time.monotonic())
        if supervisor.same_start_running(state) and remaining >= 1:
            try:
                acpi = supervisor.shutdown(state, grace=max(1, min(20, int(remaining))))
                outcome = acpi.get('outcome')
                if outcome == 'exited-after-request':
                    outcome = 'exited-after-acpi-request'
                return dict(cid=state['cid'], outcome=outcome,
                            request_sent=requested, guest_boot_uuid=guest_boot,
                            request_id=nonce if requested else None, request_error=error,
                            acpi_request_sent=bool(acpi.get('request_sent', True)),
                            acpi_request_error=acpi.get('request_error'))
            except Exception as failure:
                acpi_error = str(failure)
        else:
            acpi_error = 'no bounded grace remains for ACPI powerdown'
        supervisor.stop_exact(state['cid'])
        return dict(cid=state['cid'], outcome='forced', request_sent=requested,
                    guest_boot_uuid=guest_boot, request_id=nonce if requested else None,
                    request_error=error, acpi_request_sent=False,
                    acpi_request_error=acpi_error)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vm-dir', type=Path, required=True)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--expected-build', required=True)
    args = parser.parse_args()
    print(json.dumps(shutdown(args.vm_dir, json.loads(args.state.read_text()),
                              args.expected_build), indent=2))
