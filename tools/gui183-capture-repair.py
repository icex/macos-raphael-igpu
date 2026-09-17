#!/usr/bin/env python3
"""Offline, proof-only CR2 reconstruction for the frozen candidate-183 GUI run."""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import zlib


ROOT = Path(__file__).resolve().parents[1]
RUN_ID = '4661e574bbd5695d00176d85bfa87325'
BOOT_ID = '73ad3355-80a7-48f1-a8dd-e6f770b41de8'
BUILD_ID = '1d5f98d2e5b641eeab1869987f569e73'
DONOR_SNAPSHOT = 0
TERMINAL_SNAPSHOT = 1
ARTIFACTS = {
    'agent-server-events.jsonl': 'e2647bc44ee05519c399d94163c6e3739faa1fb6df3bd8c78217aa334a0e1acd',
    'events.jsonl': 'a4ed908959093593091461cc8667aa1845025d7a69084536b0f2e1a7597dc01f',
    'host-after.json': 'dff80636236e38c0c44d1480a8e74388e4e2a3127bb2c40a15b9414edc7c8ad7',
    'host-before.json': 'dff80636236e38c0c44d1480a8e74388e4e2a3127bb2c40a15b9414edc7c8ad7',
    'host-kernel-messages.json': 'd95602e853498523ebde440182c7d52b4c4892ac9bc015140cc8a503837bf88a',
    'manifest.json': 'b78905e67974809e085849001514a6c934d314bc43de2e0ae71a26ddc5470c11',
    'recovery.json': 'ddb66b00adb660c710cd8bc4db03fd37ab569908563630f4f1c5b99d3370055b',
    'running-identity.json': '790961400decb4bf0297545db6439cea2bb21d095bd921bf147f68e852f5d016',
    'serial.txt': 'a8c7aeda24244094d2a153df066d3857f3adfa823bb4ff62bbe72a79180c765b',
    'shutdown.json': 'a78ae63f0ebcc7bc97dcf492926f75dfbd86a5756448f700d4ddbe9c96b838ef',
    'supervision.json': '7ac98e72d946c99963480fa4a039e86a0a7686dd6a4be009a7e1534c6032d605',
    'verdict.json': '4d896e153fafbc59072eb82014e591dff8536c31d449f63f9a3e032b5052fc49',
}
HELPERS = {
    'tools/vfio-recover.py': 'cf3c3dbcfa93abe85d575d49536b948e25ef532c56858a29fb77800afeea3abe',
    'tools/recovery_lease_v2.py': '445544dd52f30cf32838472d2d248d69ea1cd3e703c8f580ecef6491238aa7d2',
    'tools/kiq-recovery-proof.py': '16af9cd9b5e807a44e0e28d6b6005840b9d720c50df2ce757b820dd5d3de0398',
    'tools/critical-replay.py': '8e0332d763be3fb6e31d5877ad78711c8673e8f5aeae56ba4989248947554b61',
    'tools/recovery_lifetime_v3.py': '61ab64bec086d0c358a05b57f893bc6267b94d9b6f431bed100de13a9d0fbcea',
}
DONOR_END = dict(count=186, bytes=24020, chunks=662,
                 crc32=0xdc5b31af, fnv1a64=0xd118231b8aa54652)
TERMINAL_END = dict(count=265, bytes=32567, chunks=915,
                    crc32=0x479b28cb, fnv1a64=0xa4dd20b0b45780c4)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load_replay():
    path = ROOT / 'tools/critical-replay.py'
    spec = importlib.util.spec_from_file_location('critical_replay_gui183', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _missing_chunks():
    result = {(63, 1), (64, 0), (67, 2), (67, 3)}
    counts = {
        65: 5, 68: 4, 69: 2, 70: 4, 71: 2, 72: 4, 73: 3, 74: 10,
        75: 3, 76: 6, 77: 3, 78: 5, 79: 3, 80: 3, 81: 5, 82: 2,
        83: 3, 84: 2, 85: 4, 86: 2, 87: 4, 88: 2, 89: 4, 90: 6,
    }
    counts.update({record: 7 for record in range(91, 99)})
    counts.update({record: 6 for record in range(99, 115)})
    counts.update({record: 4 for record in range(115, 155)})
    for record, parts in counts.items():
        result.update((record, part) for part in range(parts))
    return frozenset(result)


MISSING_CHUNKS = _missing_chunks()


def _line(replay, build, snapshot, record, part, parts, payload):
    checksum = zlib.crc32(replay._chunk_domain(
        build, snapshot, record, part, parts, payload)) & 0xffffffff
    return ('RaphaelGPU      rgpu: @ RGPU_CR2 v=1 b={} s={:08x} r={:04x} '
            'p={:02x}/{:02x} n={:02x} c={:08x} d={}\n').format(
                build, snapshot, record, part, parts, len(payload), checksum,
                payload.hex())


def _transport(serial, replay, build):
    snapshots = {}
    ends = {}
    end_offsets = {}
    offset = 0
    for number, raw in enumerate(serial.splitlines(keepends=True), 1):
        line = raw.rstrip('\r\n')
        chunk, end = replay._CHUNK.fullmatch(line), replay._END.fullmatch(line)
        if chunk:
            if chunk[1] != build:
                raise ValueError('foreign build in valid transport')
            snap, record, part = map(lambda x: int(x, 16), (chunk[2], chunk[3], chunk[4]))
            parts, size, checksum = map(lambda x: int(x, 16), (chunk[5], chunk[6], chunk[7]))
            payload = bytes.fromhex(chunk[8])
            if (len(payload) != size or zlib.crc32(replay._chunk_domain(
                    build, snap, record, part, parts, payload)) & 0xffffffff != checksum):
                raise ValueError('malformed or checksum-invalid apparent target chunk')
            key = (record, part); value = (parts, size, payload, checksum)
            prior = snapshots.setdefault(snap, {}).get(key)
            if prior is not None and prior != value:
                raise ValueError('conflicting valid chunk')
            snapshots[snap][key] = value
        elif end:
            if end[1] != build:
                raise ValueError('foreign build in valid END')
            snap = int(end[2], 16)
            if snap in ends and ends[snap] != line:
                raise ValueError('conflicting valid END')
            ends[snap] = line
            end_offsets[snap] = (offset, number, raw)
        offset += len(raw.encode('utf-8'))
    return snapshots, ends, end_offsets


def _end_dict(result):
    return {key: result[key] for key in
            ('count', 'bytes', 'chunks', 'dropped', 'truncated', 'crc32', 'fnv1a64')}


def reconstruct(serial_bytes, build, donor_snapshot, terminal_snapshot, expected_missing):
    if not isinstance(serial_bytes, bytes):
        raise ValueError('serial input must be bytes')
    serial = serial_bytes.decode('utf-8')
    replay = load_replay()
    snapshots, ends, offsets = _transport(serial, replay, build)
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
        raise ValueError('original tolerant error: ' + tolerant_error)
    if set(ends) != {donor_snapshot, terminal_snapshot} or terminal_snapshot != max(ends):
        raise ValueError('donor/terminal END topology mismatch')
    if any(snapshot not in ends for snapshot in snapshots):
        raise ValueError('transport after terminal END')
    terminal_offset, terminal_line, terminal_raw = offsets[terminal_snapshot]
    if any('RGPU_CR2' in line or 'RGPU_END2' in line
           for line in serial.splitlines()[terminal_line:]):
        raise ValueError('transport after terminal END')
    donor_prefix = serial_bytes[:offsets[donor_snapshot][0] +
                                len(offsets[donor_snapshot][2].encode('utf-8'))]
    try:
        donor = replay.parse(donor_prefix.decode('utf-8'), build,
                             tolerate_corruption=True, open_attempt=True)
    except replay.CriticalReplayError as error:
        raise ValueError('donor snapshot is not intact') from error
    if donor['snapshot'] != donor_snapshot:
        raise ValueError('donor snapshot mismatch')
    if donor_snapshot == DONOR_SNAPSHOT and build == BUILD_ID and any(
            _end_dict(donor)[key] != value for key, value in DONOR_END.items()):
        raise ValueError('donor END fields mismatch')
    terminal_chunks = snapshots.get(terminal_snapshot, {})
    for (record, part), value in terminal_chunks.items():
        if record >= donor['count']:
            continue
        expected = replay._record_chunks(donor['records'][record].encode('ascii'))
        if (part >= len(expected) or value[0] != expected[part][1] or
                value[1] != len(expected[part][2]) or value[2] != expected[part][2]):
            raise ValueError('valid terminal chunk conflicts with donor prefix')
    actual_missing = set()
    for record in range(TERMINAL_END['count']):
        present = {part: value for (candidate, part), value in terminal_chunks.items()
                   if candidate == record}
        if present:
            parts = next(iter(present.values()))[0]
        elif record < donor['count']:
            parts = len(replay._record_chunks(donor['records'][record].encode('ascii')))
        else:
            raise ValueError('terminal has an undonorably missing record')
        actual_missing.update((record, part) for part in range(parts) if part not in present)
    if actual_missing != set(expected_missing):
        raise ValueError('terminal missing chunk set mismatch')
    inserted = []
    for record, part in sorted(actual_missing):
        if record >= donor['count']:
            raise ValueError('missing terminal chunk is beyond donor prefix')
        pieces = replay._record_chunks(donor['records'][record].encode('ascii'))
        donor_part, parts, payload = pieces[part]
        if donor_part != part:
            raise ValueError('donor chunk index mismatch')
        inserted.append(_line(replay, build, terminal_snapshot, record, part, parts, payload))
    inserted_bytes = ''.join(inserted).encode('ascii')
    derived = serial_bytes[:terminal_offset] + inserted_bytes + serial_bytes[terminal_offset:]
    result = replay.parse(derived.decode('utf-8'), build,
                          tolerate_corruption=True, open_attempt=True)
    if result['snapshot'] != terminal_snapshot or result['records'][:donor['count']] != donor['records']:
        raise ValueError('derived terminal does not preserve donor prefix')
    if any('ABORT' in value for value in result['records']) or re.search(
            r'XH(?:2\s+ABORT\b|3\s+.*\bstate=ABORT\b)', serial):
        raise ValueError('capture contains ABORT evidence')
    return derived, {
        'strict_original_error': strict_error,
        'tolerant_original_error': tolerant_error,
        'donor_snapshot': donor_snapshot,
        'donor_record_count': donor['count'],
        'donor_end': _end_dict(donor),
        'terminal_snapshot': terminal_snapshot,
        'terminal_end_line': terminal_line,
        'terminal_end_raw': terminal_raw.rstrip('\r\n'),
        'terminal_end': _end_dict(result),
        'missing_chunks': [list(value) for value in sorted(actual_missing)],
        'insertion_offset': terminal_offset,
        'inserted_bytes': inserted_bytes.decode('ascii'),
        'inserted_sha256': sha(inserted_bytes),
        'original_serial_sha256': sha(serial_bytes),
        'derived_serial_sha256': sha(derived),
        'records_sha256': sha(b'\0'.join(v.encode('ascii') for v in result['records'])),
        'corrupt_line_numbers': result['corrupt_line_numbers'],
    }


def build_proof(run_dir):
    run_dir = run_dir.resolve()
    if run_dir.name != 'metal-016-183-gui-73ad3355' or run_dir.parent.name != 'run':
        raise ValueError('wrong frozen GUI run directory')
    for name, expected in ARTIFACTS.items():
        if sha((run_dir / name).read_bytes()) != expected:
            raise ValueError(name + ' SHA-256 mismatch')
    for name, expected in HELPERS.items():
        if sha((ROOT / name).read_bytes()) != expected:
            raise ValueError(name + ' SHA-256 mismatch')
    manifest = json.loads((run_dir / 'manifest.json').read_bytes())
    required = {'run_id': RUN_ID, 'boot_id': BOOT_ID, 'build_id': BUILD_ID,
                'critical_replay_schema': 2, 'recovery_lease_schema': 3,
                'recovery_critical_replay_tolerance': 'terminal-prefix-open'}
    if any(manifest.get(key) != value for key, value in required.items()):
        raise ValueError('manifest identity mismatch')
    # The manifest's own recovery_helpers_sha256 is frozen by ARTIFACTS above
    # (what this run actually used); it need only name the same helper files
    # as the live HELPERS pin checked below, not match it byte-for-byte, since
    # HELPERS is deliberately kept current.
    if set(manifest.get('recovery_helpers_sha256') or {}) != set(HELPERS):
        raise ValueError('manifest identity mismatch')
    derived, reconstruction = reconstruct((run_dir / 'serial.txt').read_bytes(),
                                          BUILD_ID, DONOR_SNAPSHOT,
                                          TERMINAL_SNAPSHOT, MISSING_CHUNKS)
    if any(reconstruction['terminal_end'][key] != value
           for key, value in TERMINAL_END.items()):
        raise ValueError('terminal END fields mismatch')
    records = load_replay().parse(derived.decode(), BUILD_ID,
                                  tolerate_corruption=True, open_attempt=True)['records']
    owned = [v for v in records if v.startswith('XH2 OWNED ')]
    pool = [v for v in records if v.startswith('XH2 POOL state=ACTIVE ')]
    lifetime = [v for v in records if v.startswith('XH3 LIFETIME state=VALID ')]
    if len(owned) != 1 or len(pool) != 1 or len(lifetime) != 1:
        raise ValueError('lease/lifetime record cardinality mismatch')
    nonce = 'nonce=5d69d5bb74e56146_2573a8bf856d1700'
    if any(nonce not in value for value in owned + pool + lifetime):
        raise ValueError('lease/lifetime nonce mismatch')
    vfio_path = ROOT / 'tools/vfio-recover.py'
    spec = importlib.util.spec_from_file_location('vfio_recover_gui183', vfio_path)
    vfio = importlib.util.module_from_spec(spec); spec.loader.exec_module(vfio)
    lease = vfio.parse_v2_lease_records(
        [value for value in records if value.startswith('XH2 ')], RUN_ID)
    lifetime_path = ROOT / 'tools/recovery_lifetime_v3.py'
    spec = importlib.util.spec_from_file_location('lifetime_gui183', lifetime_path)
    lifetime_tool = importlib.util.module_from_spec(spec); spec.loader.exec_module(lifetime_tool)
    marker = lifetime_tool.make_valid_marker(lease.descriptor.pack(), lease.pool_status.pack())
    match = re.fullmatch(
        r'XH3 LIFETIME state=VALID nonce=([0-9a-f]{16})_([0-9a-f]{16}) '
        r'checksum=0x([0-9a-f]{16})', lifetime[0])
    expected_marker = (f'{marker.nonce_lo:016x}', f'{marker.nonce_hi:016x}',
                       f'{marker.checksum:016x}')
    if match is None or match.groups() != expected_marker:
        raise ValueError('lifetime record binding/checksum mismatch')
    return derived, {
        'schema': 1, 'kind': 'gui183-cr2-erasure-proof-only',
        'authorizes_gpu_action': False, 'run_id': RUN_ID, 'boot_id': BOOT_ID,
        'build_id': BUILD_ID, 'run_directory': str(run_dir),
        'artifact_sha256': ARTIFACTS, 'helper_sha256': HELPERS,
        'tool_sha256': sha(Path(__file__).read_bytes()),
        'reconstruction': reconstruction,
        'lease_records': {'owned': owned[0], 'pool': pool[0], 'lifetime': lifetime[0]},
    }


def _write_exclusive(path, data):
    with path.open('xb') as stream:
        stream.write(data); stream.flush(); os.fsync(stream.fileno())


def write_outputs(output, derived, proof):
    output.mkdir(parents=True, exist_ok=False)
    _write_exclusive(output / 'derived-serial.txt', derived)
    _write_exclusive(output / 'proof.json',
                     (json.dumps(proof, indent=2, sort_keys=True) + '\n').encode())
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    derived, proof = build_proof(args.run_dir)
    write_outputs(args.output, derived, proof)
    print(json.dumps({'proof_only': True, 'output': str(args.output),
                      'derived_sha256': sha(derived),
                      'missing_chunks': len(MISSING_CHUNKS)}))


if __name__ == '__main__':
    main()
