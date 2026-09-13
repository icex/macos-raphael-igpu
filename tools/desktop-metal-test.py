#!/usr/bin/env python3
"""Validate the nonce-bound desktop Metal evidence probe (tests/desktop_metal_probe.m).

A pass requires one small compute command to complete on the Navi23 Metal 3
device. The desktop evidence (which Metal device drives each active display and
which processes hold IOAccelerator user clients) is returned for the record; it
does not gate the pass, because a headless guest may have no active display.
"""
import importlib.util
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
PREFIX = 'RGPU_DESKTOP_METAL_RESULT '


def _transport():
    path = ROOT / 'tools' / 'metal-test.py'
    spec = importlib.util.spec_from_file_location('metal_transport', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.run_guest_command


def parse_result(output, run_id):
    rows = [line[len(PREFIX):] for line in output.splitlines() if line.startswith(PREFIX)]
    if len(rows) != 1:
        raise ValueError('expected exactly one complete desktop Metal result')
    result = json.loads(rows[0])
    if not isinstance(result, dict) or result.get('run_id') != run_id:
        raise ValueError('missing or stale run ID')
    return result


def validate_output(output, run_id):
    result = parse_result(output, run_id)
    exits = re.findall(r'^RGPU_EXIT ' + re.escape(run_id) + r' (\d+)$', output, re.M)
    if exits != ['0']:
        raise ValueError('desktop probe did not exit successfully')
    if (result.get('passed') is not True or result.get('metal3') is not True or
            result.get('device') != 'AMD Radeon Navi23'):
        raise ValueError('desktop probe identity or execution failed')
    for key in ('registry_id', 'completed_command_buffers', 'values_checked'):
        if type(result.get(key)) is not int or result[key] < 1:
            raise ValueError(f'insufficient desktop probe evidence: {key}')
    return result


def desktop_evidence(result):
    """Summarize the desktop fields of a parsed result."""
    accelerators = result.get('accelerators') if isinstance(result.get('accelerators'), list) else []
    same = [a for a in accelerators if isinstance(a, dict) and a.get('same_as_metal_device') is True]
    clients = sorted({c for a in same for c in a.get('user_clients', []) if isinstance(c, str)})
    return dict(display_on_device=result.get('display_on_device') is True,
                displays=len(result.get('displays') or []),
                windowserver_accelerator_client=result.get('windowserver_accelerator_client') is True,
                device_clients=clients)
