#!/usr/bin/env python3
"""Recover a stopped, queue-free GPU without borrowing a guest recovery lease.

MODE2 is followed by two complete selector-only scans. Only an already halted,
idle GC/SDMA with no active queues or enabled doorbells can reach PSP teardown.
No VRAM, doorbell, DMCUB or queue-programming writes are permitted here.
"""
import argparse
import fcntl
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import time
from types import SimpleNamespace
import uuid

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 9
KIND = 'mode2-noqueue-recovery'


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), ROOT/'tools'/f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R = load('vfio-recover')
N = load('noqueue-qualification')
M = load('smu-mode2-reset')
OFFSETS = dict(N.N.GLOBAL_OFFSETS,
    c2pmsg_64=R.C2PMSG_64_OFFSET, sdma0_status=R.SDMA0_STATUS_REG_OFFSET,
    sdma0_page_rb_cntl=R.SDMA0_PAGE_RB_CNTL_OFFSET,
    sdma0_page_ib_cntl=R.SDMA0_PAGE_IB_CNTL_OFFSET,
    sdma0_rlc0_rb_cntl=R.SDMA0_RLC_RB_CNTL_OFFSETS[0],
    sdma0_rlc0_ib_cntl=R.SDMA0_RLC_IB_CNTL_OFFSETS[0],
    sdma0_rlc1_rb_cntl=R.SDMA0_RLC_RB_CNTL_OFFSETS[1],
    sdma0_rlc1_ib_cntl=R.SDMA0_RLC_IB_CNTL_OFFSETS[1])
ARTIFACTS = ('manifest.json', 'serial.txt', 'critical.txt', 'shutdown.json',
             'recovery.json', 'verdict.json', 'supervision.json')
SOURCES = ('mode2-noqueue-recover', 'smu-mode2-reset', 'vfio-recover',
           'noqueue-qualification', 'inspect-noqueue', 'experiment',
           'recovery_lease_v2', 'recovery_lifetime_v3')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def source_hashes():
    return {name: sha((ROOT/'tools'/f'{name}.py').read_bytes()) for name in SOURCES}


class ScanTransport:
    def __init__(self, raw):
        self.raw = raw

    def read32(self, offset):
        if offset not in set(OFFSETS.values()) | {R.CP_HQD_ACTIVE_OFFSET,
                R.CP_HQD_PQ_DOORBELL_OFFSET, R.GRBM_GFX_CNTL_OFFSET}:
            raise ValueError('scan read outside allowlist')
        return self.raw.read32(offset)

    def select(self, value):
        if value not in N.N.VALID_SELECTORS:
            raise ValueError('invalid selector')
        self.raw.write32(R.GRBM_GFX_CNTL_OFFSET, value)
        # GRBM_GFX_CNTL readback is not a reliable queue identity on Raphael.
        # Use the existing transport's CONFIG_MEMSIZE posted-write barrier,
        # as do nv_grbm_select and the project's ordinary recovery scanner.


def scan(raw):
    mm = ScanTransport(raw)
    def globals_():
        return {key: mm.read32(offset) for key, offset in OFFSETS.items()}
    result = {'vfio_opened': True, 'errors': [], 'passes': []}
    try:
        mm.select(0)
        result['globals_before'] = globals_()
        for _ in range(2):
            queues = []
            for me in (1, 2):
                for pipe in range(4):
                    for queue in range(8):
                        mm.select(R.queue_selector(me, pipe, queue))
                        queues.append([me, pipe, queue, mm.read32(R.CP_HQD_ACTIVE_OFFSET),
                                       mm.read32(R.CP_HQD_PQ_DOORBELL_OFFSET)])
            graphics = []
            for pipe in (0, 1):
                mm.select(pipe)
                graphics.append([pipe, mm.read32(R.CP_RB_ACTIVE_OFFSET),
                                 mm.read32(R.CP_RB1_ACTIVE_OFFSET),
                                 mm.read32(R.CP_RB_DOORBELL_CONTROL_OFFSET)])
            mm.select(0)
            result['passes'].append({'hqd': queues, 'graphics': graphics, 'globals': globals_()})
        result['globals_after'] = globals_()
    finally:
        mm.select(0)
    result['selector_final'] = 0
    return result


def scan_errors(value, final=False):
    mailbox = value.get('globals_before', {}).get('c2pmsg_64')
    errors = []
    if (type(mailbox) is not int or mailbox == 0xffffffff or
            mailbox & R.READY_MASK != R.READY_FLAG or
            (final and mailbox != (R.DESTROY_GPCOM_RING | R.READY_FLAG))):
        errors.append('psp_mailbox')
    errors += N.validate_snapshot(value, expected_mailbox=mailbox, check_journal=False)
    if set(value.get('globals_before', {})) != set(OFFSETS):
        errors.append('global_coverage')
    return sorted(set(errors))


def teardown(raw, evidence, execute):
    evidence['before_teardown'] = scan(raw)
    errors = scan_errors(evidence['before_teardown'])
    if errors:
        raise ValueError('stopped scan refused: ' + ','.join(errors))
    if execute:
        evidence['commands'] = [R.run_command(raw, c, label) for c, label in (
            (R.DESTROY_RINGS, 'destroy all rings'),
            (R.DESTROY_GPCOM_RING, 'destroy GPCOM ring'))]
        evidence['after_teardown'] = scan(raw)
        errors = scan_errors(evidence['after_teardown'], final=True)
        if errors:
            raise ValueError('final scan refused: ' + ','.join(errors))


def reset_errors(value, boot):
    errors = []
    if (value.get('boot_id') != boot or value.get('device') != R.DEVICE or
            value.get('mode') != 'execute' or value.get('error')):
        errors.append('reset_identity')
    for key, message, argument in (('version_probe', 2, 0), ('reset', 10, 2)):
        row = value.get(key, {})
        if (row.get('message') != message or row.get('argument') != argument or
                row.get('response') != 1 or row.get('ok') is not True):
            errors.append(key)
    if (value.get('gc_after', {}).get('CP_STAT') != 0 or
            value.get('gc_after', {}).get('RLC_CNTL') != 0 or
            value.get('pci_config_changed_dwords') != [] or
            value.get('pci_command_before') != value.get('pci_command_after') or
            value.get('pci_command_after', 4) & 4 or
            value.get('memsize_before') != R.resolve_expected_config_memsize() or
            value.get('memsize_after') != value.get('memsize_before')):
        errors.append('reset_state')
    return errors


def host_gate(boot):
    state = R.host_state()
    errors = R.validate_host_state(state, boot)
    pci = Path('/sys/bus/pci/devices')/R.DEVICE
    if (pci/'power/control').read_text().strip() != 'on':
        errors.append('power_control')
    if (pci/'power/runtime_status').read_text().strip() != 'active':
        errors.append('runtime_status')
    if errors:
        raise ValueError('host gate: ' + ','.join(errors))
    return state


def input_evidence(vm, run_dir, boot):
    raw = {name: (run_dir/name).read_bytes() for name in ARTIFACTS}
    manifest = json.loads(raw['manifest.json'])
    run = manifest['run_id']
    if not re.fullmatch('[0-9a-f]{32}', run) or manifest['boot_id'] != boot:
        raise ValueError('run identity')
    shutdown = json.loads(raw['shutdown.json'])
    supervision = json.loads(raw['supervision.json'])
    if (shutdown.get('cid') != supervision.get('cid') or shutdown.get('outcome') not in
            ('already-stopped', 'forced', 'forced-after-abort', 'exited-after-guest-request',
             'forced-after-shutdown-error')):
        raise ValueError('shutdown not confirmed')
    if json.loads(raw['recovery.json']).get('status') != 'failed':
        raise ValueError('ordinary recovery has not failed')
    ledger_path = vm/'run/used-gpu-boots'/f'{boot}.json'
    ledger_raw = ledger_path.read_bytes()
    ledger = json.loads(ledger_raw)
    if ledger.get('boot_id') != boot or ledger['launches'][-1]['run_id'] != run:
        raise ValueError('not the latest run')
    return run, sha(ledger_raw), {name: sha(data) for name, data in raw.items()}


def validate_receipt(value, vm, boot, prior):
    try:
        if (value.get('schema') != SCHEMA or value.get('kind') != KIND or
                value.get('status') != 'recovered' or value.get('authorizes_launch') is not True or
                value.get('boot_id') != boot or value.get('prior_run_id') != prior or
                not re.fullmatch('[0-9a-f]{32}', value.get('recovery_id', '')) or
                value.get('helper_sha256') != source_hashes()):
            return ['mode2_noqueue_identity']
        run, ledger_sha, hashes = input_evidence(Path(vm), Path(value['run_directory']), boot)
        errors = []
        if run != prior or ledger_sha != value['ledger_sha256'] or hashes != value['artifact_sha256']:
            errors.append('mode2_noqueue_binding')
        for key in ('host_before', 'host_after'):
            errors += R.validate_host_state(value[key], boot)
        errors += reset_errors(value['reset'], boot)
        errors += scan_errors(value['before_teardown'])
        errors += scan_errors(value['after_teardown'], final=True)
        commands = value['commands']
        if len(commands) != 2:
            errors.append('psp_commands')
        else:
            for row, command in zip(commands, (R.DESTROY_RINGS, R.DESTROY_GPCOM_RING)):
                if (row.get('command') != command or row.get('confirmed') is not True or
                        row.get('response') != command | R.READY_FLAG):
                    errors.append('psp_commands')
        messages = value.get('kernel_messages')
        if (not isinstance(messages, list) or any(not isinstance(m, str) for m in messages) or
                any(re.search(r'BUG:|Oops:|Hardware Error|IO_PAGE_FAULT|hard LOCKUP|soft lockup|MCE:|AMD-Vi:.*fault|vfio.*(?:error|failed)|vfio-pci .*: (?:resetting|reset done)', m, re.I) for m in messages)):
            errors.append('kernel_messages')
        if value.get('kernel_faults') != [] or not value.get('kernel_cursor_before') or not value.get('kernel_cursor_after'):
            errors.append('kernel_evidence')
        if value.get('errors') != []:
            errors.append('recovery_errors')
        return sorted(set(errors))
    except (KeyError, TypeError, ValueError, OSError, AttributeError):
        return ['mode2_noqueue_malformed']


def recover(vm, run_dir, output, execute=False):
    with (vm/'run/experiment.lock').open('a') as owner:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        run, ledger_sha, hashes = input_evidence(vm, run_dir, boot)
        canonical = vm/'run/vfio-recovery'/boot/f'{run}.json'
        if output.exists() or canonical.exists():
            raise ValueError('refusing to replace recovery evidence')
        evidence = dict(schema=SCHEMA, kind=KIND, boot_id=boot, prior_run_id=run,
            recovery_id=uuid.uuid4().hex, run_directory=str(run_dir), ledger_sha256=ledger_sha,
            artifact_sha256=hashes, helper_sha256=source_hashes(), created_epoch=time.time(),
            status='inspection', authorizes_launch=False, errors=[])
        attempt = output.with_suffix(output.suffix + '.attempt')
        if execute:
            R.write_once(attempt, dict(boot_id=boot, prior_run_id=run,
                ledger_sha256=ledger_sha, helper_sha256=source_hashes(),
                started_epoch=time.time()))
        try:
            if list((vm/'run/launch-pending').glob('*')):
                raise ValueError('launch pending')
            evidence['host_before'] = host_gate(boot)
            cursor, _, faults = R.kernel_updates()
            evidence['kernel_cursor_before'] = cursor
            if faults:
                raise ValueError('host fault before recovery')
            if execute:
                evidence['reset'] = M.run(SimpleNamespace(execute=True))
                errors = reset_errors(evidence['reset'], boot)
                if errors:
                    raise ValueError('MODE2 refused: ' + ','.join(errors))
            with R.LegacyVfio() as mmio:
                teardown(mmio, evidence, execute)
            evidence['host_after'] = host_gate(boot)
            after, messages, faults = R.kernel_updates(cursor)
            evidence.update(kernel_cursor_after=after, kernel_messages=messages, kernel_faults=faults)
            if faults or any(re.search(r'vfio-pci .*: (?:resetting|reset done)', m) for m in messages):
                raise ValueError('host fault or implicit PCI reset')
            if execute:
                evidence.update(status='recovered', authorizes_launch=True)
                errors = validate_receipt(evidence, vm, boot, run)
                if errors:
                    raise ValueError('receipt validation: ' + ','.join(errors))
        except Exception as error:
            evidence.update(status='failed', authorizes_launch=False)
            evidence['errors'].append(type(error).__name__ + ': ' + str(error))
        R.write_once(output, evidence)
        if evidence['authorizes_launch']:
            R.write_once(canonical, evidence)
        return evidence


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vm-dir', required=True, type=Path)
    parser.add_argument('--run-dir', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    result = recover(args.vm_dir.resolve(), args.run_dir.resolve(), args.output.resolve(), args.execute)
    print(json.dumps(result, indent=2))
    raise SystemExit(1 if result['errors'] else 0)
