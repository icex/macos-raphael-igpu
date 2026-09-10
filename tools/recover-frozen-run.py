#!/usr/bin/env python3
"""Retire a frozen GPU run whose strict CR2 parse failed, under the reviewed rule.

The candidate 180 capture ended with a checksum-clean terminal CR2 snapshot, but
Apple's concurrent console dump garbled 27 physical lines of an earlier attempt
and the strict parser refused the whole capture, leaving no recovery receipt.
This tool applies the terminal-prefix tolerance to exactly one archived run:

  1. pin the run's manifest, raw serial, the replay parser, the recovery helpers
     and this tool by SHA-256 into an exclusive proof file inside the run output;
  2. decode the terminal snapshot with the tolerant parser and record every
     corrupt line number, every incomplete attempt, and the terminal digests;
  3. refuse if any decoded record is an XH2 ABORT or the lifetime marker is not
     VALID in the guest evidence;
  4. call the unchanged schema-3 recovery, which still requires exact current
     OWNED / ACTIVE POOL / VALID BAR readbacks before any scratch write and
     writes its own immutable receipt.

The original failed receipt and verdict are never modified. Nothing here
authorizes a launch; the coordinator's reuse validators still decide that.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def load(name):
    path = ROOT / 'tools' / (name + '.py')
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_once(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')
        stream.flush()
    return path


def build_proof(vm, run_dir, tolerance):
    manifest_bytes = (run_dir / 'manifest.json').read_bytes()
    serial_bytes = (run_dir / 'serial.txt').read_bytes()
    manifest = json.loads(manifest_bytes)
    if manifest.get('critical_replay_schema') != 2 or manifest.get('recovery_lease_schema') != 3:
        raise ValueError('frozen-run recovery needs CR2 transport and schema-3 recovery')
    replay = load('critical-replay')
    serial = serial_bytes.decode('utf-8', errors='replace')
    strict_error = None
    try:
        replay.parse(serial, manifest['build_id'])
    except replay.CriticalReplayError as error:
        strict_error = str(error)
    if strict_error is None:
        raise ValueError('strict CR2 parse succeeds; use the ordinary recovery path')
    snapshot = replay.parse(serial, manifest['build_id'], tolerate_corruption=True,
                            open_attempt=tolerance == 'terminal-prefix-open')
    records = snapshot['records']
    open_attempt = snapshot.get('open_attempt')
    if open_attempt is not None:
        records = records + open_attempt['complete_records']
    aborts = [record for record in records if 'ABORT' in record]
    if aborts:
        raise ValueError('terminal snapshot contains an abort record: ' + aborts[0])
    valid = [record for record in records if record.startswith('XH3 LIFETIME state=VALID')]
    if not valid:
        raise ValueError('terminal snapshot has no VALID lifetime marker record')
    helpers = {relative: sha_bytes((ROOT / relative).read_bytes()) for relative in (
        'tools/critical-replay.py', 'tools/vfio-recover.py', 'tools/recovery_lease_v2.py',
        'tools/recovery_lifetime_v3.py', 'tools/experiment.py', 'tools/recover-frozen-run.py')}
    # The frozen manifest pins the helper set that failed to decode the capture.
    # The receipt is produced by the current helpers, whose hashes the next
    # manifest will pin; both sets are preserved here for the audit trail.
    original_helpers = manifest.get('recovery_helpers_sha256')
    if not isinstance(original_helpers, dict) or not original_helpers:
        raise ValueError('frozen manifest lacks recovery helper hashes')
    return manifest, serial, {
        'schema': 1,
        'kind': 'frozen-run-terminal-prefix-recovery-proof',
        'run_id': manifest['run_id'],
        'boot_id': manifest['boot_id'],
        'build_id': manifest['build_id'],
        'run_directory': str(run_dir),
        'manifest_sha256': sha_bytes(manifest_bytes),
        'serial_sha256': sha_bytes(serial_bytes),
        'strict_parse_error': strict_error,
        'tolerance': tolerance,
        'terminal_snapshot': snapshot['snapshot'],
        'record_count': snapshot['count'],
        'corrupt_lines': snapshot['corrupt_lines'],
        'corrupt_line_numbers': snapshot['corrupt_line_numbers'],
        'corrupt_reasons': snapshot['corrupt_reasons'],
        'incomplete_snapshots': snapshot['incomplete_snapshots'],
        'open_attempt': open_attempt,
        'crc32': snapshot['crc32'],
        'fnv1a64': snapshot['fnv1a64'],
        'lifetime_records': valid,
        'helper_sha256': helpers,
        'original_recovery_helpers_sha256': original_helpers,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vm-dir', required=True, type=Path)
    parser.add_argument('--run-dir', required=True, type=Path)
    parser.add_argument('--tolerance', required=True,
                        choices=['terminal-prefix', 'terminal-prefix-open'])
    parser.add_argument('--execute', action='store_true',
                        help='perform the recovery; absent means write the proof and stop')
    args = parser.parse_args()
    vm = args.vm_dir.resolve()
    run_dir = args.run_dir.resolve()
    manifest, serial, proof = build_proof(vm, run_dir, args.tolerance)
    proof_path = run_dir / 'recovery-replay-proof.json'
    if proof_path.exists():
        # A proof-only pass may precede execution, but only the identical proof.
        if json.loads(proof_path.read_text()) != proof:
            raise SystemExit('an older, different recovery proof exists for this run; refused')
    else:
        write_once(proof_path, proof)
    if (run_dir / 'recovery-retry.json').exists():
        raise SystemExit('a recovery retry record already exists for this run; automatic retry refused')
    print(json.dumps({key: proof[key] for key in (
        'run_id', 'terminal_snapshot', 'record_count', 'corrupt_lines',
        'incomplete_snapshots', 'strict_parse_error')}, indent=2))
    if not args.execute:
        print('proof written; recovery not executed (no --execute)')
        return
    experiment = load('experiment')
    recovery_tool = experiment.helper('vfio-recover')
    vfio = load('vfio-recover')
    current_helpers = vfio.current_recovery_helpers_sha256(3)
    manifest = dict(manifest, critical_replay_tolerance=args.tolerance,
                    recovery_helpers_sha256=current_helpers)
    replay_evidence = {}
    try:
        result = experiment.recover_v2(recovery_tool, vm, manifest, serial, replay_evidence)
    except BaseException as error:
        result = {'status': 'failed', 'error': type(error).__name__ + ': ' + str(error)}
    result_path = run_dir / 'recovery-retry.json'
    write_once(result_path, {'proof_sha256': sha_bytes(proof_path.read_bytes()),
                             'recovery_helpers_sha256': current_helpers,
                             'replay': replay_evidence, 'recovery': result})
    print(json.dumps(result, indent=2))
    if result.get('status') != 'recovered':
        sys.exit(1)


if __name__ == '__main__':
    main()
