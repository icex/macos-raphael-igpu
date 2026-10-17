#!/usr/bin/env python3
"""Prepare or run a nonce-bound, single-command-buffer Metal smoke probe.

This is a diagnostic workload for isolating first submission and completion. It
does not replace the full acceptance probe and never launches a VM or changes
device ownership.
"""
import argparse
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import sys
import time
import uuid


ROOT = Path(__file__).resolve().parents[1]


def _transport():
    path = ROOT / 'tools' / 'metal-test.py'
    spec = importlib.util.spec_from_file_location('metal_transport', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.run_guest_command


def validate_output(output, run_id):
    rows = [line.removeprefix('RGPU_SMALL_METAL_RESULT ')
            for line in output.splitlines()
            if line.startswith('RGPU_SMALL_METAL_RESULT ')]
    if len(rows) != 1:
        raise ValueError('expected exactly one complete small Metal result')
    result = json.loads(rows[0])
    if not isinstance(result, dict) or result.get('run_id') != run_id:
        raise ValueError('missing or stale run ID')
    exits = re.findall(r'^RGPU_EXIT ' + re.escape(run_id) + r' (\d+)$', output, re.M)
    if exits != ['0']:
        raise ValueError('small probe did not exit successfully')
    if (result.get('passed') is not True or result.get('metal3') is not True or
            result.get('device') != 'AMD Radeon Navi23'):
        raise ValueError('small probe identity or execution failed')
    for key, minimum in (('registry_id', 1), ('completed_command_buffers', 1),
                         ('values_checked', 1)):
        if type(result.get(key)) is not int or result[key] < minimum:
            raise ValueError(f'insufficient small probe evidence: {key}')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vm-dir', type=Path, required=True)
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    vm = args.vm_dir.resolve()
    if not (vm / 'gx').is_file() or not (vm / 'run').is_dir():
        parser.error('--vm-dir must contain gx and run/')
    source = (ROOT / 'tests/small_metal_probe.m').read_bytes()
    digest = hashlib.sha256(source).hexdigest()
    run_id = uuid.uuid4().hex
    guest_dir = f'/var/tmp/rgpu-small-metal-{digest[:16]}'
    qdir = shlex.quote(guest_dir)
    payload = base64.b64encode(source).decode('ascii')
    prepare = (f'mkdir -p {qdir} && printf %s {shlex.quote(payload)} | '
               f'/usr/bin/base64 -D > {qdir}/probe.m && '
               f'/usr/bin/xcrun clang -fobjc-arc -fblocks -O2 -Wall -Wextra -Werror '
               f'-framework Foundation -framework Metal {qdir}/probe.m -o {qdir}/probe')
    if args.prepare_only:
        action = prepare
    else:
        expiry = int(time.time()) + 65
        permit = f'http://10.0.2.2:8889/metal-permit-{run_id}'
        action = (f'permit=$(/usr/bin/curl -fsS --max-time 3 {shlex.quote(permit)}) && '
                  f'test "$permit" = {shlex.quote(run_id)} && test -x {qdir}/probe && '
                  f'{qdir}/probe {shlex.quote(run_id)} {expiry}')
    command = f'( {action}; result=$?; printf "\\nRGPU_EXIT {run_id} %s\\n" "$result" )'
    try:
        proc = _transport()(vm, command, run_id, dict(os.environ, GX_TIMEOUT='70'),
                            timeout=80, execution_grace=0 if args.prepare_only else 45)
    except Exception as error:
        print(f'FAIL: {error}', file=sys.stderr)
        return 1
    print(proc.stdout, end='' if proc.stdout.endswith('\n') else '\n')
    if proc.returncode:
        return proc.returncode
    if args.prepare_only:
        return 0 if re.findall(r'^RGPU_EXIT ' + re.escape(run_id) + r' 0$', proc.stdout, re.M) else 1
    try:
        validate_output(proc.stdout, run_id)
    except (ValueError, json.JSONDecodeError) as error:
        print(f'FAIL: {error}', file=sys.stderr)
        return 1
    print('PASS: one small Metal submission completed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
