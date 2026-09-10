#!/usr/bin/env python3
"""One-run CR2 erasure proof for candidate 183; proof-only unless explicitly executed."""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import struct
import sys
import time
import zlib


ROOT = Path(__file__).resolve().parents[1]
RUN_ID = 'f1728b74e128c5acd35661334bff12be'
BOOT_ID = 'd67da91d-94e6-42f0-8dd1-78b42f5496e1'
BUILD_ID = '1d5f98d2e5b641eeab1869987f569e73'
MANIFEST_SHA256 = 'e809cee6b8dc3cb8749d56dcedeb4dcdb55ab98caf21ee3a5bdd7de59f660775'
SERIAL_SHA256 = 'af132e635729bee36634c4bd4f5280bf63735183f88b465e8a3d34c1c0df0ce1'
RECOVERY_SHA256 = 'ddb66b00adb660c710cd8bc4db03fd37ab569908563630f4f1c5b99d3370055b'
VERDICT_SHA256 = '4d896e153fafbc59072eb82014e591dff8536c31d449f63f9a3e032b5052fc49'
DONOR_SNAPSHOT = 2
TERMINAL_SNAPSHOT = 3
MISSING_RECORD = 134
MISSING_PARTS = 4
DONOR_END = {
    'count': 267, 'bytes': 32715, 'chunks': 920,
    'crc32': 0x46697678, 'fnv1a64': 0x02ed1d53e9c30321,
}
TERMINAL_END = {
    'count': 285, 'bytes': 34431, 'chunks': 971,
    'crc32': 0xf18488f3, 'fnv1a64': 0x72e0f4557e90ee72,
}
HELPERS = {
    'tools/vfio-recover.py': '3616a938db007c84ecae6048bfd83100902759a328dda92c1d5394801e2d288e',
    'tools/recovery_lease_v2.py': '445544dd52f30cf32838472d2d248d69ea1cd3e703c8f580ecef6491238aa7d2',
    'tools/kiq-recovery-proof.py': '16af9cd9b5e807a44e0e28d6b6005840b9d720c50df2ce757b820dd5d3de0398',
    'tools/critical-replay.py': '8e0332d763be3fb6e31d5877ad78711c8673e8f5aeae56ba4989248947554b61',
    'tools/recovery_lifetime_v3.py': '61ab64bec086d0c358a05b57f893bc6267b94d9b6f431bed100de13a9d0fbcea',
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load_tool(name):
    path = ROOT / 'tools' / (name + '.py')
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _end_dict(result):
    return {key: result[key] for key in
            ('count', 'bytes', 'chunks', 'dropped', 'truncated', 'crc32', 'fnv1a64')}


def _chunk_line(replay, build, snapshot, record, part, parts, payload):
    checksum = zlib.crc32(replay._chunk_domain(
        build, snapshot, record, part, parts, payload)) & 0xffffffff
    return ('RaphaelGPU      rgpu: @ RGPU_CR2 v=1 b={} s={:08x} r={:04x} '
            'p={:02x}/{:02x} n={:02x} c={:08x} d={}\n').format(
                build, snapshot, record, part, parts, len(payload), checksum,
                payload.hex())


def _find_end_line(replay, serial, snapshot):
    matches = []
    offset = 0
    for number, raw_line in enumerate(serial.splitlines(keepends=True), 1):
        line = raw_line.rstrip('\r\n')
        match = replay._END.fullmatch(line)
        if match and int(match[2], 16) == snapshot:
            matches.append((offset, number, raw_line, match))
        offset += len(raw_line.encode('utf-8'))
    if len(matches) != 1:
        raise ValueError('expected exactly one target terminal END')
    return matches[0]


def validate_lifetime_record(record, lease, lifetime):
    match = re.fullmatch(
        r'XH3 LIFETIME state=VALID nonce=([0-9a-f]{16})_([0-9a-f]{16}) '
        r'checksum=0x([0-9a-f]{16})', record)
    if match is None:
        raise ValueError('candidate183 lifetime record has invalid grammar')
    marker = lifetime.make_valid_marker(
        lease.descriptor.pack(), lease.pool_status.pack())
    expected = (f'{marker.nonce_lo:016x}', f'{marker.nonce_hi:016x}',
                f'{marker.checksum:016x}')
    if match.groups() != expected:
        raise ValueError('candidate183 lifetime record binding or checksum mismatch')
    return marker


def reconstruct_erasure(serial_bytes, build, donor_snapshot, terminal_snapshot,
                        record, expected_parts):
    """Return an insertion-only derived transcript and its pure provenance."""
    if not isinstance(serial_bytes, bytes):
        raise ValueError('original serial must be bytes')
    try:
        serial = serial_bytes.decode('utf-8')
    except UnicodeDecodeError as error:
        raise ValueError('original serial is not UTF-8') from error
    if any(re.fullmatch(r'.*RaphaelGPU\s+rgpu:\s*@\s+XH(?:2\s+ABORT\b|3\s+.*\bstate=ABORT\b).*',
                        line) for line in serial.splitlines()):
        raise ValueError('original transcript contains direct ABORT evidence')
    replay = load_tool('critical-replay')
    try:
        replay.parse(serial, build)
    except replay.CriticalReplayError as error:
        strict_error = str(error)
    else:
        raise ValueError('original strict parse unexpectedly succeeds')
    try:
        replay.parse(serial, build, tolerate_corruption=True, open_attempt=True)
    except replay.CriticalReplayError as error:
        tolerant_error = str(error)
    else:
        raise ValueError('original tolerant parse unexpectedly succeeds')
    if tolerant_error != 'CR2 snapshot has a missing chunk':
        raise ValueError('original tolerant failure is not the pinned missing chunk')

    donor_offset, donor_line_number, donor_end_line, _ = _find_end_line(
        replay, serial, donor_snapshot)
    donor_end_offset = donor_offset + len(donor_end_line.encode('utf-8'))
    donor_result = replay.parse(
        serial_bytes[:donor_end_offset].decode('utf-8'), build,
        tolerate_corruption=True, open_attempt=True)
    if donor_result['snapshot'] != donor_snapshot or record >= donor_result['count']:
        raise ValueError('donor snapshot or record mismatch')
    donor_record = donor_result['records'][record].encode('ascii')
    pieces = replay._record_chunks(donor_record)
    if len(pieces) != expected_parts:
        raise ValueError('donor record part count mismatch')
    donor_chunks = []
    for line_number, raw_line in enumerate(serial.splitlines(keepends=True), 1):
        match = replay._CHUNK.fullmatch(raw_line.rstrip('\r\n'))
        if (match is None or int(match[2], 16) != donor_snapshot or
                int(match[3], 16) != record):
            continue
        part = int(match[4], 16)
        if part >= len(pieces):
            raise ValueError('donor record has an unexpected physical part')
        expected_part, expected_total, expected_payload = pieces[part]
        if (part != expected_part or int(match[5], 16) != expected_total or
                bytes.fromhex(match[8]) != expected_payload):
            raise ValueError('donor chunk does not match reconstructed donor record')
        donor_chunks.append({
            'part': part, 'line_number': line_number,
            'line': raw_line.rstrip('\r\n'),
            'checksum': int(match[7], 16),
            'sha256': sha(raw_line.encode('utf-8')),
        })
    if [value['part'] for value in donor_chunks] != list(range(expected_parts)):
        raise ValueError('donor chunk provenance is incomplete or duplicated')

    target_offset, target_line_number, target_end_line, _ = _find_end_line(
        replay, serial, terminal_snapshot)
    marker_after = False
    target_has_part = False
    for number, line in enumerate(serial.splitlines(), 1):
        if number > target_line_number and ('RGPU_CR2' in line or 'RGPU_END2' in line):
            marker_after = True
        match = replay._CHUNK.fullmatch(line)
        if (match and int(match[2], 16) == terminal_snapshot and
                int(match[3], 16) == record):
            target_has_part = True
    if marker_after:
        raise ValueError('transport after terminal END')
    if target_has_part:
        raise ValueError('target record already has a physical part')

    inserted_lines = [_chunk_line(
        replay, build, terminal_snapshot, record, part, parts, payload)
        for part, parts, payload in pieces]
    inserted_bytes = ''.join(inserted_lines).encode('ascii')
    derived = serial_bytes[:target_offset] + inserted_bytes + serial_bytes[target_offset:]
    result = replay.parse(derived.decode('utf-8'), build,
                          tolerate_corruption=True, open_attempt=True)
    if result['snapshot'] != terminal_snapshot:
        raise ValueError('derived transcript did not select terminal snapshot')
    if result['records'][:donor_result['count']] != donor_result['records']:
        raise ValueError('derived terminal changed donor prefix')
    if any('ABORT' in value for value in result['records']):
        raise ValueError('derived terminal contains ABORT')

    canonical_lines = []
    for record_number, value in enumerate(result['records']):
        for part, parts, payload in replay._record_chunks(value.encode('ascii')):
            canonical_lines.append(_chunk_line(
                replay, build, terminal_snapshot, record_number,
                part, parts, payload))
    canonical_lines.append(target_end_line if target_end_line.endswith(('\n', '\r'))
                           else target_end_line + '\n')
    canonical = ''.join(canonical_lines).encode('utf-8')
    strict_terminal = replay.parse(canonical.decode('utf-8'), build)
    if strict_terminal['records'] != result['records']:
        raise ValueError('canonical terminal diagnostic mismatch')

    end = _end_dict(result)
    return derived, {
        'original_serial_sha256': sha(serial_bytes),
        'derived_serial_sha256': sha(derived),
        'strict_original_error': strict_error,
        'tolerant_original_error': tolerant_error,
        'donor_snapshot': donor_snapshot,
        'donor_end_line': donor_line_number,
        'donor_end_raw': donor_end_line.rstrip('\r\n'),
        'donor_end': _end_dict(donor_result),
        'terminal_snapshot': terminal_snapshot,
        'terminal_end_line': target_line_number,
        'terminal_end_raw': target_end_line.rstrip('\r\n'),
        'terminal_end': end,
        'terminal_count': result['count'],
        'missing_record': record,
        'missing_parts': list(range(expected_parts)),
        'donor_record': donor_record.decode('ascii'),
        'donor_record_sha256': sha(donor_record),
        'donor_chunks': donor_chunks,
        'insertion_offset': target_offset,
        'inserted_bytes': inserted_bytes.decode('ascii'),
        'inserted_chunks': [
            {'part': index, 'line': line.rstrip('\n'),
             'sha256': sha(line.encode('ascii'))}
            for index, line in enumerate(inserted_lines)],
        'canonical_terminal_sha256': sha(canonical),
        'reconstructed_records_sha256': sha(
            b'\0'.join(value.encode('ascii') for value in result['records'])),
        'record_count': result['count'],
        'corrupt_lines': result['corrupt_lines'],
        'corrupt_line_numbers': result['corrupt_line_numbers'],
    }


def _require_file(path, expected):
    data = path.read_bytes()
    if sha(data) != expected:
        raise ValueError(path.name + ' SHA-256 mismatch')
    return data


def require_helper_files(root, expected):
    current = {path: sha((root / path).read_bytes()) for path in expected}
    if current != expected:
        raise ValueError('candidate183 recovery helper drift')
    return current


def build_proof(run_dir):
    run_dir = run_dir.resolve()
    if run_dir.name != 'metal-016-183' or run_dir.parent.name != 'run':
        raise ValueError('candidate183 repair requires run/metal-016-183')
    manifest_bytes = _require_file(run_dir / 'manifest.json', MANIFEST_SHA256)
    serial_bytes = _require_file(run_dir / 'serial.txt', SERIAL_SHA256)
    _require_file(run_dir / 'recovery.json', RECOVERY_SHA256)
    _require_file(run_dir / 'verdict.json', VERDICT_SHA256)
    manifest = json.loads(manifest_bytes)
    required = {
        'run_id': RUN_ID, 'boot_id': BOOT_ID, 'build_id': BUILD_ID,
        'candidate_directory': 'run/candidate-183',
        'critical_replay_schema': 2, 'recovery_lease_schema': 3,
        'recovery_critical_replay_tolerance': 'terminal-prefix-open',
        'recovery_helpers_sha256': HELPERS,
    }
    if any(manifest.get(key) != value for key, value in required.items()):
        raise ValueError('candidate183 manifest identity mismatch')
    require_helper_files(ROOT, HELPERS)
    derived, reconstruction = reconstruct_erasure(
        serial_bytes, BUILD_ID, DONOR_SNAPSHOT, TERMINAL_SNAPSHOT,
        MISSING_RECORD, MISSING_PARTS)
    if reconstruction['strict_original_error'] != 'CR2 has a malformed transport line':
        raise ValueError('candidate183 strict parse error changed')
    if any(reconstruction['donor_end'][key] != value
           for key, value in DONOR_END.items()):
        raise ValueError('candidate183 donor END mismatch')
    if any(reconstruction['terminal_end'][key] != value
           for key, value in TERMINAL_END.items()):
        raise ValueError('candidate183 terminal END mismatch')
    expected_nonce = struct.unpack('<QQ', bytes.fromhex(RUN_ID))
    nonce = f'{expected_nonce[0]:x}_{expected_nonce[1]:x}'
    records = load_tool('critical-replay').parse(
        derived.decode(), BUILD_ID, tolerate_corruption=True,
        open_attempt=True)['records']
    owned = [value for value in records if value.startswith('XH2 OWNED ')]
    pool = [value for value in records if value.startswith('XH2 POOL state=ACTIVE ')]
    lifetime_records = [value for value in records if value.startswith('XH3 LIFETIME ')]
    if (len(owned) != 1 or len(pool) != 1 or len(lifetime_records) != 1 or
            any(('nonce=' + nonce) not in value for value in owned + pool)):
        raise ValueError('candidate183 lease identity records mismatch')
    vfio = load_tool('vfio-recover')
    lease = vfio.parse_v2_lease_records([value for value in records
                                         if value.startswith('XH2 ')], RUN_ID)
    lifetime_tool = load_tool('recovery_lifetime_v3')
    validate_lifetime_record(lifetime_records[0], lease, lifetime_tool)
    proof = {
        'schema': 1,
        'kind': 'candidate183-cr2-erasure-recovery-proof',
        'run_id': RUN_ID, 'boot_id': BOOT_ID, 'build_id': BUILD_ID,
        'vm_directory': str(run_dir.parent.parent),
        'run_directory': str(run_dir),
        'manifest_sha256': MANIFEST_SHA256,
        'serial_sha256': SERIAL_SHA256,
        'failed_recovery_sha256': RECOVERY_SHA256,
        'verdict_sha256': VERDICT_SHA256,
        'recovery_helpers_sha256': HELPERS,
        'additional_source_sha256': {
            'tools/experiment.py': sha((ROOT / 'tools/experiment.py').read_bytes()),
            'tools/candidate183-recovery-repair.py': sha(Path(__file__).read_bytes()),
        },
        'reconstruction': reconstruction,
        'terminal_end': reconstruction['terminal_end'],
        'lease_records': {'owned': owned[0], 'pool': pool[0],
                          'lifetime': lifetime_records[0]},
    }
    return derived, proof


def write_once(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return path


def require_boot_id(path):
    if path.read_text().strip() != BOOT_ID:
        raise ValueError('candidate183 recovery repair requires the pinned live boot')


def execute_once(directory, proof_path, reviewed_proof_sha256, recover,
                 attempt_name='attempt.json', result_name='result.json'):
    if (not re.fullmatch(r'[0-9a-f]{64}', reviewed_proof_sha256) or
            sha(proof_path.read_bytes()) != reviewed_proof_sha256):
        raise ValueError('reviewed proof SHA-256 mismatch')
    attempt_path = directory / attempt_name
    result_path = directory / result_name
    if attempt_path.exists():
        raise FileExistsError(str(attempt_path))
    if result_path.exists():
        raise FileExistsError(str(result_path))
    write_once(attempt_path, {
        'schema': 1, 'kind': 'candidate183-recovery-repair-attempt',
        'proof_sha256': reviewed_proof_sha256, 'created_epoch': time.time(),
    })
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
    parser.add_argument('--proof-only', action='store_true',
                        help='write the proof (the default and only mode without --execute)')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--reviewed-proof-sha256')
    args = parser.parse_args()
    if args.execute and args.proof_only:
        raise SystemExit('--proof-only and --execute are mutually exclusive')
    vm = args.vm_dir.resolve()
    run_dir = vm / 'run/metal-016-183'
    derived, proof = build_proof(run_dir)
    proof_path = run_dir / 'candidate183-recovery-repair-proof.json'
    if not args.execute:
        write_once(proof_path, proof)
        print(json.dumps({'proof': str(proof_path), 'sha256': sha(proof_path.read_bytes())},
                         indent=2))
        return
    if not args.reviewed_proof_sha256:
        raise SystemExit('--execute requires --reviewed-proof-sha256')
    if json.loads(proof_path.read_text()) != proof:
        raise SystemExit('reviewed proof bytes do not match current reconstruction')
    require_boot_id(Path('/proc/sys/kernel/random/boot_id'))
    manifest = json.loads(_require_file(run_dir / 'manifest.json', MANIFEST_SHA256))

    def recover():
        experiment_path = ROOT / 'tools/experiment.py'
        if sha(experiment_path.read_bytes()) != proof['additional_source_sha256'][
                'tools/experiment.py']:
            raise ValueError('experiment helper changed after proof review')
        require_helper_files(ROOT, proof['recovery_helpers_sha256'])
        experiment = load_tool('experiment')
        recovery_tool = experiment.helper('vfio-recover')
        replay = {}
        receipt = experiment.recover_v2(
            recovery_tool, vm, manifest, derived.decode('utf-8'), replay)
        receipt_path = vm / 'run/vfio-recovery' / BOOT_ID / (RUN_ID + '.json')
        receipt_bytes = receipt_path.read_bytes()
        if json.loads(receipt_bytes) != receipt:
            raise ValueError('canonical recovery receipt differs from returned receipt')
        return {'receipt': receipt, 'receipt_sha256': sha(receipt_bytes),
            'receipt_path': str(receipt_path.relative_to(vm)),
            'replay': replay, 'original_serial_sha256': SERIAL_SHA256,
            'derived_serial_sha256': sha(derived)}

    result = execute_once(
        run_dir, proof_path, args.reviewed_proof_sha256, recover,
        'candidate183-recovery-repair-attempt.json',
        'candidate183-recovery-repair-result.json')
    print(json.dumps(result, indent=2, sort_keys=True))
    if result.get('status') != 'complete' or result.get('recovery', {}).get(
            'receipt', {}).get('status') != 'recovered':
        sys.exit(1)


if __name__ == '__main__':
    main()
