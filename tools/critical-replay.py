#!/usr/bin/env python3
"""Pure decoder for bounded, checksummed RaphaelGPU critical replay snapshots."""

import re
import struct
import zlib


MAX_INPUT_BYTES = 8 * 1024 * 1024
MAX_PHYSICAL_LINE_BYTES = 239
MAX_RECORDS = 512
MAX_RECORD_BYTES = 511
MAX_PARTS = 13
MAX_CHUNK_BYTES = 40
WIRE_VERSION = 1

_PREFIX = r'(?:RaphaelGPU\s+rgpu:\s*@\s+)?'
_CHUNK = re.compile(
    _PREFIX +
    r'RGPU_CR2 v=1 b=([0-9a-f]{32}) s=([0-9a-f]{8}) '
    r'r=([0-9a-f]{4}) p=([0-9a-f]{2})/([0-9a-f]{2}) '
    r'n=([0-9a-f]{2}) c=([0-9a-f]{8}) d=([0-9a-f]*)')
_END = re.compile(
    _PREFIX +
    r'RGPU_END2 v=1 b=([0-9a-f]{32}) s=([0-9a-f]{8}) '
    r'first=([0-9a-f]{4}) count=([0-9a-f]{4}) '
    r'drop=([0-9a-f]{16}) trunc=([0-9a-f]{16}) '
    r'bytes=([0-9a-f]{8}) chunks=([0-9a-f]{8}) '
    r'crc=([0-9a-f]{8}) fnv=([0-9a-f]{16}) state=complete')


class CriticalReplayError(ValueError):
    pass


def _fnv1a64(data):
    value = 0xcbf29ce484222325
    for byte in data:
        value = ((value ^ byte) * 0x100000001b3) & 0xffffffffffffffff
    return value


def _new_snapshot(snapshots, snapshot, latest_seen):
    if snapshot < latest_seen:
        raise CriticalReplayError('CR2 has a stale snapshot')
    if snapshot not in snapshots:
        if snapshot <= latest_seen:
            raise CriticalReplayError('CR2 snapshot IDs do not strictly increase')
        snapshots[snapshot] = {'chunks': {}, 'end': None}
        latest_seen = snapshot
    return snapshots[snapshot], latest_seen


def _chunk_domain(build, snapshot, record, part, parts, payload):
    return (bytes([WIRE_VERSION]) + bytes.fromhex(build) +
            struct.pack('<IHBBB', snapshot, record, part, parts, len(payload)) +
            payload)


def _snapshot_domain(build, snapshot, count, dropped, truncated,
                     total_bytes, total_chunks, records):
    result = (b'RGPU-CR2\0' + bytes([WIRE_VERSION]) + bytes.fromhex(build) +
              struct.pack('<IHHQQII', snapshot, 0, count, dropped, truncated,
                          total_bytes, total_chunks))
    for record_number, record in enumerate(records):
        result += struct.pack('<HH', record_number, len(record)) + record
    return result


def _reconstruct(snapshot, expected_build):
    end = snapshot['end']
    if end is None:
        raise CriticalReplayError('CR2 snapshot is missing END')
    (build, sequence, first, count, dropped, truncated, total_bytes,
     total_chunks, expected_crc, expected_fnv) = end
    if build != expected_build:
        raise CriticalReplayError('CR2 has a foreign build')
    if first != 0:
        raise CriticalReplayError('CR2 first record is not zero')
    if count > MAX_RECORDS:
        raise CriticalReplayError('CR2 exceeds its record bound')
    if dropped or truncated:
        raise CriticalReplayError('CR2 snapshot reports loss')

    chunks = snapshot['chunks']
    if any(record >= count for record, _ in chunks):
        raise CriticalReplayError('CR2 chunk is outside the manifested record range')
    records = []
    for record_number in range(count):
        pieces = [(part, value) for (record, part), value in chunks.items()
                  if record == record_number]
        if not pieces:
            raise CriticalReplayError('CR2 snapshot has a missing chunk')
        part_counts = {value[0] for _, value in pieces}
        if len(part_counts) != 1:
            raise CriticalReplayError('CR2 record has conflicting part totals')
        parts = part_counts.pop()
        if {part for part, _ in pieces} != set(range(parts)):
            raise CriticalReplayError('CR2 snapshot has a missing chunk')
        ordered = [chunks[(record_number, part)][2] for part in range(parts)]
        if parts == 1 and not ordered[0]:
            record = b''
        else:
            if any(len(piece) != MAX_CHUNK_BYTES for piece in ordered[:-1]):
                raise CriticalReplayError('CR2 record has a short nonfinal chunk')
            if not ordered[-1]:
                raise CriticalReplayError('CR2 record has an empty final chunk')
            record = b''.join(ordered)
        if len(record) > MAX_RECORD_BYTES:
            raise CriticalReplayError('CR2 exceeds its record byte bound')
        if any(byte < 0x20 or byte > 0x7e for byte in record):
            raise CriticalReplayError('CR2 record is not printable ASCII')
        records.append(record)

    actual_bytes = sum(map(len, records))
    actual_chunks = len(chunks)
    if actual_bytes != total_bytes:
        raise CriticalReplayError('CR2 byte total mismatch')
    if actual_chunks != total_chunks:
        raise CriticalReplayError('CR2 chunk total mismatch')
    domain = _snapshot_domain(build, sequence, count, dropped, truncated,
                              total_bytes, total_chunks, records)
    if zlib.crc32(domain) & 0xffffffff != expected_crc:
        raise CriticalReplayError('CR2 snapshot CRC mismatch')
    if _fnv1a64(domain) != expected_fnv:
        raise CriticalReplayError('CR2 snapshot FNV mismatch')
    return records


TOLERANCE_TERMINAL_PREFIX = 'terminal-prefix'


def _record_chunks(record):
    """Split one decoded record into the (part, parts, payload) chunks the guest emits."""
    parts = max(1, (len(record) + MAX_CHUNK_BYTES - 1) // MAX_CHUNK_BYTES)
    return [(part, parts, record[part * MAX_CHUNK_BYTES:(part + 1) * MAX_CHUNK_BYTES])
            for part in range(parts)]


def parse(serial, expected_build, tolerate_corruption=False):
    """Return the latest complete CR2 snapshot bound to ``expected_build``.

    Strict mode (the default) refuses the whole capture on any malformed,
    over-length or checksum-failing transport line. ``tolerate_corruption``
    selects the reviewed terminal-prefix rule instead: physical lines that do not
    decode to a checksum-valid chunk or manifest are counted as corruption; every
    checksum-valid chunk from an incomplete attempt must still agree with the
    terminal complete snapshot; the latest attempt must be complete; and no
    transport line of any kind may follow the terminal manifest. Conflicting
    valid chunks or manifests remain fatal in both modes.
    """
    if (not isinstance(serial, str) or not isinstance(expected_build, str) or
            not re.fullmatch(r'[0-9a-f]{32}', expected_build)):
        raise CriticalReplayError('CR2 parser arguments are invalid')
    if len(serial.encode('utf-8')) > MAX_INPUT_BYTES:
        raise CriticalReplayError('CR2 input byte bound exceeded')
    serial = serial.replace('\r', '')
    if serial and not serial.endswith('\n'):
        tail = serial.rsplit('\n', 1)[-1]
        if 'RGPU_CR2' in tail or 'RGPU_END2' in tail:
            raise CriticalReplayError('CR2 has an incomplete transport line')
        serial = serial.rsplit('\n', 1)[0] + ('\n' if '\n' in serial else '')

    snapshots = {}
    latest_seen = -1
    transport_seen = False
    corrupt_lines = []
    marker_lines = []
    for line_number, line in enumerate(serial.splitlines()):
        if 'RGPU_CR2' not in line and 'RGPU_END2' not in line:
            continue
        transport_seen = True
        marker_lines.append(line_number)
        if len(line.encode('utf-8')) > MAX_PHYSICAL_LINE_BYTES:
            if tolerate_corruption:
                corrupt_lines.append((line_number, 'physical line bound exceeded'))
                continue
            raise CriticalReplayError('CR2 physical line bound exceeded')
        chunk = _CHUNK.fullmatch(line)
        end = _END.fullmatch(line)
        if chunk is None and end is None:
            if tolerate_corruption:
                corrupt_lines.append((line_number, 'malformed transport line'))
                continue
            raise CriticalReplayError('CR2 has a malformed transport line')
        match = chunk or end
        build = match[1]
        snapshot_number = int(match[2], 16)
        if build != expected_build:
            raise CriticalReplayError('CR2 has a foreign build')
        if chunk:
            record = int(chunk[3], 16)
            part = int(chunk[4], 16)
            parts = int(chunk[5], 16)
            size = int(chunk[6], 16)
            checksum = int(chunk[7], 16)
            data_hex = chunk[8]
            if (record >= MAX_RECORDS or not 1 <= parts <= MAX_PARTS or
                    part >= parts or size > MAX_CHUNK_BYTES or
                    len(data_hex) != size * 2):
                if tolerate_corruption:
                    corrupt_lines.append((line_number, 'invalid chunk bounds'))
                    continue
                raise CriticalReplayError('CR2 has invalid chunk bounds')
            payload = bytes.fromhex(data_hex)
            if zlib.crc32(_chunk_domain(
                    build, snapshot_number, record, part, parts, payload)) & 0xffffffff != checksum:
                if tolerate_corruption:
                    corrupt_lines.append((line_number, 'chunk checksum mismatch'))
                    continue
                raise CriticalReplayError('CR2 chunk checksum mismatch')
            snapshot, latest_seen = _new_snapshot(
                snapshots, snapshot_number, latest_seen)
            key = (record, part)
            value = (parts, size, payload, checksum)
            if key in snapshot['chunks'] and snapshot['chunks'][key] != value:
                raise CriticalReplayError('CR2 has a conflicting chunk')
            snapshot['chunks'][key] = value
        else:
            snapshot, latest_seen = _new_snapshot(
                snapshots, snapshot_number, latest_seen)
            values = (build, snapshot_number, int(end[3], 16), int(end[4], 16),
                      int(end[5], 16), int(end[6], 16), int(end[7], 16),
                      int(end[8], 16), int(end[9], 16), int(end[10], 16))
            if snapshot['end'] is not None and snapshot['end'] != values:
                raise CriticalReplayError('CR2 has a conflicting END')
            snapshot['end'] = values
            snapshot['end_line'] = line_number

    if not transport_seen:
        raise CriticalReplayError('missing CR2 transport')
    if not tolerate_corruption:
        decoded = []
        previous = None
        for snapshot_number in sorted(snapshots):
            records = _reconstruct(snapshots[snapshot_number], expected_build)
            if previous is not None and (
                    len(records) < len(previous) or records[:len(previous)] != previous):
                raise CriticalReplayError('CR2 later snapshot changed prefix')
            decoded.append((snapshot_number, records, snapshots[snapshot_number]['end']))
            previous = records
        snapshot_number, records, end = decoded[-1]
        result = _result(expected_build, snapshot_number, records, end)
        return result

    if not snapshots:
        raise CriticalReplayError('CR2 has no decodable transport')
    complete_numbers = [number for number, value in snapshots.items()
                        if value['end'] is not None]
    # The guest never starts a later attempt after a complete one unless it has
    # more to say; an incomplete later attempt therefore hides records.
    if not complete_numbers or max(snapshots) != max(complete_numbers):
        raise CriticalReplayError('CR2 latest attempt is incomplete')
    terminal_number = max(complete_numbers)
    terminal = snapshots[terminal_number]
    records = _reconstruct(terminal, expected_build)
    if any(line_number > terminal['end_line'] for line_number in marker_lines):
        raise CriticalReplayError('CR2 has transport after the terminal manifest')
    incomplete = []
    for snapshot_number in sorted(snapshots):
        if snapshot_number == terminal_number:
            continue
        earlier = snapshots[snapshot_number]
        try:
            earlier_records = _reconstruct(earlier, expected_build)
        except CriticalReplayError:
            earlier_records = None
        if earlier_records is not None:
            if (len(earlier_records) > len(records) or
                    records[:len(earlier_records)] != earlier_records):
                raise CriticalReplayError('CR2 later snapshot changed prefix')
            continue
        # Every checksum-valid chunk of an incomplete attempt must reproduce the
        # terminal record bytes exactly; anything else is a conflict, not corruption.
        for (record, part), (parts, size, payload, _) in earlier['chunks'].items():
            if record >= len(records):
                raise CriticalReplayError('CR2 incomplete attempt exceeds the terminal prefix')
            expected = _record_chunks(records[record])
            if (part >= len(expected) or expected[part][1] != parts or
                    expected[part][2] != payload or len(payload) != size):
                raise CriticalReplayError('CR2 incomplete attempt conflicts with the terminal prefix')
        incomplete.append({
            'snapshot': snapshot_number,
            'valid_chunks': len(earlier['chunks']),
            'has_end': earlier['end'] is not None,
        })
    result = _result(expected_build, terminal_number, records, terminal['end'])
    result['tolerance'] = TOLERANCE_TERMINAL_PREFIX
    result['corrupt_lines'] = len(corrupt_lines)
    result['corrupt_line_numbers'] = [line_number for line_number, _ in corrupt_lines]
    result['corrupt_reasons'] = sorted({reason for _, reason in corrupt_lines})
    result['incomplete_snapshots'] = incomplete
    return result


def _result(expected_build, snapshot_number, records, end):
    return {
        'schema': 2,
        'wire_version': WIRE_VERSION,
        'build': expected_build,
        'snapshot': snapshot_number,
        'records': [record.decode('ascii') for record in records],
        'count': len(records),
        'dropped': end[4],
        'truncated': end[5],
        'bytes': end[6],
        'chunks': end[7],
        'crc32': end[8],
        'fnv1a64': end[9],
    }
