#!/usr/bin/env python3
"""One-use recovery runner for the reviewed GUI-183 CR2 proof; inert by default."""

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
RUN_ID = '4661e574bbd5695d00176d85bfa87325'
BOOT_ID = '73ad3355-80a7-48f1-a8dd-e6f770b41de8'
BUILD_ID = '1d5f98d2e5b641eeab1869987f569e73'
MANIFEST_SHA256 = 'b78905e67974809e085849001514a6c934d314bc43de2e0ae71a26ddc5470c11'
PROOF_SHA256 = '59809d556b050cd8f1b1629601efdffedec34b37ab8cfbabdb3204429abaf3fb'
DERIVED_SHA256 = 'd33deff7cd420013a290d195967c0e43689c3810422b9647b8336a83180f0675'
SOURCES = {
    'tools/gui183-capture-repair.py': 'fb16e64de01fedb8ee17a608e0ca4dc063a64129aedecc84b89100c7c19d85e6',
    'tools/experiment.py': 'f7ec043ea8456f60b1ff69c4595bcaeb76bd620aee9b696e69a8790d5b038503',
    'tools/critical-replay.py': '8e0332d763be3fb6e31d5877ad78711c8673e8f5aeae56ba4989248947554b61',
    'tools/vfio-recover.py': 'cf3c3dbcfa93abe85d575d49536b948e25ef532c56858a29fb77800afeea3abe',
    'tools/recovery_lease_v2.py': '445544dd52f30cf32838472d2d248d69ea1cd3e703c8f580ecef6491238aa7d2',
    'tools/kiq-recovery-proof.py': '16af9cd9b5e807a44e0e28d6b6005840b9d720c50df2ce757b820dd5d3de0398',
    'tools/recovery_lifetime_v3.py': '61ab64bec086d0c358a05b57f893bc6267b94d9b6f431bed100de13a9d0fbcea',
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load(name):
    path = ROOT / 'tools' / (name + '.py')
    spec = importlib.util.spec_from_file_location(name.replace('-', '_') + '_gui183_once', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_sources(root=ROOT):
    for relative, expected in SOURCES.items():
        if sha((root / relative).read_bytes()) != expected:
            raise ValueError(relative + ' SHA-256 mismatch')
    return dict(SOURCES)


def validate_reviewed_proof(vm):
    validate_sources()
    run = vm.resolve() / 'run/metal-016-183-gui-73ad3355'
    proof_path = run / 'gui-capture-reconstruction/proof.json'
    proof_bytes = proof_path.read_bytes()
    if sha(proof_bytes) != PROOF_SHA256:
        raise ValueError('reviewed proof SHA-256 mismatch')
    proof_tool = load('gui183-capture-repair')
    derived, rebuilt = proof_tool.build_proof(run)
    if sha(derived) != DERIVED_SHA256:
        raise ValueError('rebuilt derived capture SHA-256 mismatch')
    reviewed = json.loads(proof_bytes)
    # helper_sha256/tool_sha256 are a live fingerprint of the recovery helpers
    # and of this tool, not reconstruction output; they legitimately move when
    # a helper is deliberately updated (e.g. tools/vfio-recover.py's
    # UMA-size-dependent CONFIG_MEMSIZE detection). Require the same helper
    # files to still be named, but not byte-identical hashes, and compare
    # everything else -- the actual reconstruction -- exactly.
    fingerprint_keys = ('helper_sha256', 'tool_sha256')
    if (set(reviewed.get('helper_sha256') or {}) !=
            set(rebuilt.get('helper_sha256') or {}) or
            {k: v for k, v in reviewed.items() if k not in fingerprint_keys} !=
            {k: v for k, v in rebuilt.items() if k not in fingerprint_keys}):
        raise ValueError('reviewed proof differs from current exact reconstruction')
    if (reviewed.get('run_id'), reviewed.get('boot_id'), reviewed.get('build_id'),
            reviewed.get('authorizes_gpu_action')) != (RUN_ID, BOOT_ID, BUILD_ID, False):
        raise ValueError('reviewed proof identity or authority mismatch')
    manifest = run / 'manifest.json'
    if sha(manifest.read_bytes()) != MANIFEST_SHA256:
        raise ValueError('manifest SHA-256 mismatch')
    return derived, reviewed


@contextmanager
def live_preflight(vm, experiment):
    """Hold the media lock; verify boot/guest state and experiment-lock availability."""
    run = vm / 'run'; run.mkdir(parents=True, exist_ok=True)
    with (run / 'experiment.lock').open('a') as experiment_lock:
        fcntl.flock(experiment_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(experiment_lock, fcntl.LOCK_UN)
    with (run / 'redeploy.lock').open('a') as media_lock:
        fcntl.flock(media_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        host = experiment.host_snapshot()
        if host.get('boot_id') != BOOT_ID:
            raise ValueError('live boot does not match reviewed boot')
        if host.get('active_vm'):
            raise ValueError('active guest prevents recovery')
        pending = run / 'launch-pending'
        if pending.exists() and any(pending.iterdir()):
            raise ValueError('pending guest launch prevents recovery')
        yield host


def write_once(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def canonical_receipt(vm, receipt, replay, proof):
    receipt_path = vm / 'run/vfio-recovery' / BOOT_ID / (RUN_ID + '.json')
    receipt_bytes = receipt_path.read_bytes()
    if json.loads(receipt_bytes) != receipt:
        raise ValueError('canonical recovery receipt differs from returned receipt')
    return {'receipt': receipt, 'receipt_sha256': sha(receipt_bytes),
            'receipt_path': str(receipt_path.relative_to(vm)), 'replay': replay,
            'original_serial_sha256': proof['artifact_sha256']['serial.txt'],
            'derived_serial_sha256': DERIVED_SHA256}


def execute_once(directory, proof_path, reviewed_proof_sha256, preflight, recover,
                 attempt_name='gui183-recovery-attempt.json',
                 result_name='gui183-recovery-result.json'):
    if (not re.fullmatch(r'[0-9a-f]{64}', reviewed_proof_sha256) or
            sha(proof_path.read_bytes()) != reviewed_proof_sha256):
        raise ValueError('reviewed proof SHA-256 mismatch')
    attempt, result_path = directory / attempt_name, directory / result_name
    if attempt.exists(): raise FileExistsError(str(attempt))
    if result_path.exists(): raise FileExistsError(str(result_path))
    with preflight():
        write_once(attempt, {'schema': 1, 'kind': 'gui183-recovery-attempt',
                             'proof_sha256': reviewed_proof_sha256,
                             'created_epoch': time.time()})
        try:
            recovery = recover()
            result = {'schema': 1, 'status': 'complete',
                      'proof_sha256': reviewed_proof_sha256, 'recovery': recovery}
        except BaseException as error:
            result = {'schema': 1, 'status': 'failed',
                      'proof_sha256': reviewed_proof_sha256,
                      'error': type(error).__name__ + ': ' + str(error)}
        write_once(result_path, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vm-dir', required=True, type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--proof-only', action='store_true')
    mode.add_argument('--execute', action='store_true')
    parser.add_argument('--reviewed-proof-sha256')
    args = parser.parse_args()
    vm = args.vm_dir.resolve()
    derived, proof = validate_reviewed_proof(vm)
    if not args.execute:
        print(json.dumps({'proof_only': True, 'proof_sha256': PROOF_SHA256,
                          'derived_sha256': sha(derived), 'run_id': RUN_ID}, indent=2))
        return
    if args.reviewed_proof_sha256 != PROOF_SHA256:
        raise SystemExit('--execute requires the exact --reviewed-proof-sha256')
    run = vm / 'run/metal-016-183-gui-73ad3355'
    proof_path = run / 'gui-capture-reconstruction/proof.json'
    manifest = json.loads((run / 'manifest.json').read_bytes())
    experiment = load('experiment')

    def recover():
        validate_sources()
        recovery_tool = experiment.helper('vfio-recover')
        replay = {}
        receipt = experiment.recover_v2(
            recovery_tool, vm, manifest, derived.decode('utf-8'), replay)
        return canonical_receipt(vm, receipt, replay, proof)

    result = execute_once(run, proof_path, args.reviewed_proof_sha256,
                          lambda: live_preflight(vm, experiment), recover)
    print(json.dumps(result, indent=2, sort_keys=True))
    if (result.get('status') != 'complete' or
            result.get('recovery', {}).get('receipt', {}).get('status') != 'recovered'):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
