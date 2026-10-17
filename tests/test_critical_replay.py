import importlib.util
import re
import struct
import unittest
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILD = '0123456789abcdef0123456789abcdef'
PREFIX = 'RaphaelGPU      rgpu: @ '


def fnv1a64(data):
    value = 0xcbf29ce484222325
    for byte in data:
        value = ((value ^ byte) * 0x100000001b3) & 0xffffffffffffffff
    return value


def snapshot_lines(records, snapshot=1, build=BUILD, dropped=0, truncated=0):
    records = [record if isinstance(record, bytes) else record.encode('ascii')
               for record in records]
    chunks = []
    for record_number, record in enumerate(records):
        part_count = max(1, (len(record) + 39) // 40)
        for part in range(part_count):
            payload = record[part * 40:(part + 1) * 40]
            domain = (bytes([1]) + bytes.fromhex(build) +
                      struct.pack('<IHBBB', snapshot, record_number, part,
                                  part_count, len(payload)) + payload)
            chunks.append(
                'RGPU_CR2 v=1 b={} s={:08x} r={:04x} p={:02x}/{:02x} '
                'n={:02x} c={:08x} d={}'.format(
                    build, snapshot, record_number, part, part_count,
                    len(payload), zlib.crc32(domain) & 0xffffffff,
                    payload.hex()))
    total_bytes = sum(map(len, records))
    body = (b'RGPU-CR2\0' + bytes([1]) + bytes.fromhex(build) +
            struct.pack('<IHHQQII', snapshot, 0, len(records), dropped,
                        truncated, total_bytes, len(chunks)))
    for record_number, record in enumerate(records):
        body += struct.pack('<HH', record_number, len(record)) + record
    end = (
        'RGPU_END2 v=1 b={} s={:08x} first=0000 count={:04x} '
        'drop={:016x} trunc={:016x} bytes={:08x} chunks={:08x} '
        'crc={:08x} fnv={:016x} state=complete'.format(
            build, snapshot, len(records), dropped, truncated, total_bytes,
            len(chunks), zlib.crc32(body) & 0xffffffff, fnv1a64(body)))
    return [PREFIX + line + '\n' for line in chunks + [end]]


class CriticalReplayTests(unittest.TestCase):
    def module(self):
        path = ROOT / 'tools/critical-replay.py'
        self.assertTrue(path.exists(), 'missing critical replay decoder')
        spec = importlib.util.spec_from_file_location('critical_replay', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_reconstructs_184_and_511_byte_cross_language_vector(self):
        replay = self.module()
        records = [b'A' * 184, b'B' * 511]
        lines = snapshot_lines(records, snapshot=0x01020304)
        self.assertEqual(lines[0].removeprefix(PREFIX).rstrip('\n'),
            'RGPU_CR2 v=1 b=0123456789abcdef0123456789abcdef '
            's=01020304 r=0000 p=00/05 n=28 c=5fb98dfd '
            'd=' + '41' * 40)
        self.assertIn('p=04/05 n=18 c=ea236aa2 d=' + '41' * 24, lines[4])
        self.assertIn('p=0c/0d n=1f c=d8065aa9 d=' + '42' * 31, lines[-2])
        self.assertEqual(lines[-1].removeprefix(PREFIX).rstrip('\n'),
            'RGPU_END2 v=1 b=0123456789abcdef0123456789abcdef '
            's=01020304 first=0000 count=0002 drop=0000000000000000 '
            'trunc=0000000000000000 bytes=000002b7 chunks=00000012 '
            'crc=c8001837 fnv=2231439245f39550 state=complete')
        self.assertLess(max(len(line.encode()) for line in lines), 240)

        result = replay.parse(''.join(lines), BUILD)

        self.assertEqual(result['schema'], 2)
        self.assertEqual(result['wire_version'], 1)
        self.assertEqual(result['build'], BUILD)
        self.assertEqual(result['snapshot'], 0x01020304)
        self.assertEqual(result['records'], [record.decode() for record in records])
        self.assertEqual(result['bytes'], 695)
        self.assertEqual(result['chunks'], 18)

    def test_accepts_exact_duplicate_transport_lines(self):
        replay = self.module()
        lines = snapshot_lines(['BUILD: identity=' + BUILD, 'XH2 OWNED example'])
        serial = ''.join(lines[:-1] + lines[:-1] + [lines[-1], lines[-1]])
        self.assertEqual(replay.parse(serial, BUILD)['records'],
                         ['BUILD: identity=' + BUILD, 'XH2 OWNED example'])

    def test_rejects_missing_conflicting_and_bad_checksum_chunks(self):
        replay = self.module()
        lines = snapshot_lines([b'A' * 184])
        other = snapshot_lines([b'B' * 184])
        cases = {
            'missing chunk': lines[:2] + lines[3:],
            'conflicting chunk': lines[:-1] + [other[0], lines[-1]],
            'chunk checksum': [re.sub(r'c=[0-9a-f]{8}', 'c=deadbeef', lines[0])] +
                lines[1:],
        }
        for error, damaged in cases.items():
            with self.subTest(error=error):
                with self.assertRaisesRegex(replay.CriticalReplayError, error):
                    replay.parse(''.join(damaged), BUILD)

    def test_rejects_manifest_totals_digests_and_overflow(self):
        replay = self.module()
        lines = snapshot_lines(['BUILD: identity=' + BUILD])
        mutations = {
            'byte total': ('bytes=', 'bytes=00000000 '),
            'chunk total': ('chunks=', 'chunks=00000000 '),
            'snapshot CRC': ('crc=', 'crc=deadbeef '),
            'snapshot FNV': ('fnv=', 'fnv=deadbeefdeadbeef '),
        }
        for error, (field, replacement) in mutations.items():
            with self.subTest(error=error):
                head, _, tail = lines[-1].partition(field)
                value_tail = tail.split(' ', 1)[1]
                damaged = lines[:-1] + [head + replacement + value_tail]
                with self.assertRaisesRegex(replay.CriticalReplayError, error):
                    replay.parse(''.join(damaged), BUILD)
        with self.assertRaisesRegex(replay.CriticalReplayError, 'reports loss'):
            replay.parse(''.join(snapshot_lines(['x'], dropped=1)), BUILD)

    def test_rejects_foreign_malformed_partial_and_non_ascii_transport(self):
        replay = self.module()
        complete = snapshot_lines(['BUILD: identity=' + BUILD])
        foreign = snapshot_lines(['x'], snapshot=2, build='f' * 32)
        cases = (
            (complete + foreign, 'foreign build'),
            ([line.replace('v=1', 'v=2', 1) for line in complete], 'malformed'),
            (complete + [PREFIX + 'RGPU_CR2 v=1 b=' + BUILD], 'incomplete'),
            (snapshot_lines([b'ok\x7f']), 'printable ASCII'),
        )
        for lines, error in cases:
            with self.subTest(error=error):
                with self.assertRaisesRegex(replay.CriticalReplayError, error):
                    replay.parse(''.join(lines), BUILD)

    def test_rejects_incomplete_stale_and_changed_later_snapshots(self):
        replay = self.module()
        first = snapshot_lines(['BUILD: identity=' + BUILD, 'one'], snapshot=5)
        extended = snapshot_lines(
            ['BUILD: identity=' + BUILD, 'one', 'two'], snapshot=6)
        self.assertEqual(replay.parse(''.join(first + extended), BUILD)['snapshot'], 6)
        cases = (
            (first + snapshot_lines(['different'], snapshot=6), 'changed prefix'),
            (extended + first, 'stale snapshot'),
            (first + snapshot_lines(['BUILD: identity=' + BUILD], snapshot=6)[:-1],
             'missing END'),
        )
        for lines, error in cases:
            with self.subTest(error=error):
                with self.assertRaisesRegex(replay.CriticalReplayError, error):
                    replay.parse(''.join(lines), BUILD)

    def test_requires_transport_and_enforces_record_and_input_bounds(self):
        replay = self.module()
        with self.assertRaisesRegex(replay.CriticalReplayError, 'missing CR2'):
            replay.parse('ordinary serial\n', BUILD)
        with self.assertRaisesRegex(replay.CriticalReplayError, 'record byte bound'):
            replay.parse(''.join(snapshot_lines([b'x' * 512])), BUILD)
        with self.assertRaisesRegex(replay.CriticalReplayError, 'input byte bound'):
            replay.parse('x' * (8 * 1024 * 1024 + 1), BUILD)

class TerminalPrefixToleranceTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location(
            'critical_replay_tolerant', ROOT / 'tools/critical-replay.py')
        self.replay = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.replay)

    def _capture(self):
        first = ['BUILD: identity=' + BUILD, 'XH2 OWNED nonce=1_2']
        later = first + ['VM: fault status=0x2009bb', 'XH3 LIFETIME state=VALID']
        complete_one = snapshot_lines(first, snapshot=1)
        attempt_two = snapshot_lines(later, snapshot=2)
        # Apple's console dump interleaves character by character with one chunk
        # line and swallows the manifest of attempt two.
        garbled = attempt_two[1][:60] + 'AMDRadeonX6000_AMDNavi23GraphicsAccelerator' + \
            attempt_two[1][60:] + ' [0:6:0] GPU Log Version: 2'
        overlong = 'RGPU_CR2 v=1 ' + 'x' * 260 + '\n'
        broken_two = [attempt_two[0], garbled + '\n', overlong] + attempt_two[2:-1]
        complete_three = snapshot_lines(later, snapshot=3)
        return first, later, complete_one, broken_two, complete_three

    def test_strict_mode_still_refuses_corrupted_transport(self):
        _, _, one, two, three = self._capture()
        with self.assertRaisesRegex(self.replay.CriticalReplayError, 'malformed|bound'):
            self.replay.parse(''.join(one + two + three), BUILD)

    def test_terminal_prefix_accepts_clean_terminal_snapshot_after_corruption(self):
        _, later, one, two, three = self._capture()
        result = self.replay.parse(''.join(one + two + three), BUILD,
                                   tolerate_corruption=True)
        self.assertEqual(result['records'], later)
        self.assertEqual(result['snapshot'], 3)
        self.assertEqual(result['tolerance'], 'terminal-prefix')
        self.assertEqual(result['corrupt_lines'], 2)
        self.assertEqual(result['corrupt_reasons'],
                         ['malformed transport line', 'physical line bound exceeded'])
        self.assertEqual(result['incomplete_snapshots'],
                         [{'snapshot': 2, 'valid_chunks': len(two) - 2, 'has_end': False}])
        strict = self.replay.parse(''.join(one + three), BUILD)
        self.assertEqual(strict['records'], later)
        self.assertNotIn('tolerance', strict)

    def test_clean_capture_is_identical_in_both_modes_with_zero_corruption(self):
        _, later, one, _, three = self._capture()
        serial = ''.join(one + three)
        strict = self.replay.parse(serial, BUILD)
        tolerant = self.replay.parse(serial, BUILD, tolerate_corruption=True)
        self.assertEqual(tolerant['records'], strict['records'])
        self.assertEqual(tolerant['crc32'], strict['crc32'])
        self.assertEqual(tolerant['corrupt_lines'], 0)
        self.assertEqual(tolerant['incomplete_snapshots'], [])

    def test_terminal_prefix_refuses_incomplete_latest_attempt(self):
        _, _, one, two, _ = self._capture()
        with self.assertRaisesRegex(self.replay.CriticalReplayError, 'latest attempt is incomplete'):
            self.replay.parse(''.join(one + two), BUILD, tolerate_corruption=True)

    def test_terminal_prefix_refuses_transport_after_the_terminal_manifest(self):
        _, _, one, two, three = self._capture()
        trailing_valid = snapshot_lines(['BUILD: identity=' + BUILD], snapshot=4)[0]
        with self.assertRaisesRegex(self.replay.CriticalReplayError, 'latest attempt is incomplete'):
            self.replay.parse(''.join(one + two + three) + trailing_valid, BUILD,
                              tolerate_corruption=True)
        duplicate_terminal_chunk = three[0]
        with self.assertRaisesRegex(self.replay.CriticalReplayError, 'after the terminal manifest'):
            self.replay.parse(''.join(one + two + three) + duplicate_terminal_chunk, BUILD,
                              tolerate_corruption=True)
        trailing_garbage = 'RaphaelGPU      rgpu: @ RGPU_CR2 v=1 b=zz garbage\n'
        with self.assertRaisesRegex(self.replay.CriticalReplayError, 'after the terminal manifest'):
            self.replay.parse(''.join(one + two + three) + trailing_garbage, BUILD,
                              tolerate_corruption=True)

    def test_terminal_prefix_refuses_valid_chunks_that_conflict_with_the_prefix(self):
        first, later, one, _, three = self._capture()
        conflicting = later[:-1] + ['XH2 ABORT reason=vmm-range']
        attempt_two = snapshot_lines(conflicting, snapshot=2)[:-1]
        with self.assertRaisesRegex(self.replay.CriticalReplayError, 'conflicts with the terminal prefix'):
            self.replay.parse(''.join(one + attempt_two + three), BUILD,
                              tolerate_corruption=True)
        longer = later + ['XH2 ABORT reason=late']
        attempt_two = snapshot_lines(longer, snapshot=2)[:-1]
        with self.assertRaisesRegex(self.replay.CriticalReplayError, 'exceeds the terminal prefix'):
            self.replay.parse(''.join(one + attempt_two + three), BUILD,
                              tolerate_corruption=True)

    def test_terminal_prefix_keeps_conflicting_valid_duplicates_fatal(self):
        _, later, one, _, three = self._capture()
        other = snapshot_lines(later[:-1] + ['XH3 LIFETIME state=ABORT'], snapshot=3)
        with self.assertRaisesRegex(self.replay.CriticalReplayError, 'conflicting'):
            self.replay.parse(''.join(one + three + [other[-2], other[-1]]), BUILD,
                              tolerate_corruption=True)

    def test_terminal_prefix_still_requires_prefix_extension(self):
        first, later, one, _, three = self._capture()
        changed = snapshot_lines(['BUILD: identity=' + BUILD, 'XH2 OWNED nonce=9_9'],
                                 snapshot=1)
        with self.assertRaisesRegex(self.replay.CriticalReplayError, 'changed prefix'):
            self.replay.parse(''.join(changed + three), BUILD, tolerate_corruption=True)


class OpenAttemptToleranceTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location(
            'critical_replay_open', ROOT / 'tools/critical-replay.py')
        self.replay = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.replay)
        self.first = ['BUILD: identity=' + BUILD, 'XH3 LIFETIME state=VALID']
        self.later = self.first + ['SD: submit vmid=2', 'VM: fault status=0x201b3b']
        self.complete = snapshot_lines(self.first, snapshot=2)
        cut = snapshot_lines(self.later, snapshot=3)
        self.cut = cut[:5] + [cut[5][:40]]   # forced stop mid-chunk, no newline

    def test_open_attempt_returns_terminal_prefix_and_extra_records(self):
        serial = ''.join(self.complete + self.cut)
        with self.assertRaisesRegex(self.replay.CriticalReplayError, 'incomplete transport line'):
            self.replay.parse(serial, BUILD, tolerate_corruption=True)
        result = self.replay.parse(serial, BUILD, tolerate_corruption=True, open_attempt=True)
        self.assertEqual(result['records'], self.first)
        self.assertEqual(result['tolerance'], 'terminal-prefix-open')
        open_attempt = result['open_attempt']
        self.assertEqual(open_attempt['snapshot'], 3)
        self.assertTrue(open_attempt['truncated_tail'])
        self.assertEqual(open_attempt['complete_records'],
                         ['SD: submit vmid=2', 'VM: fault status=0x201b3b'])
        self.assertEqual(open_attempt['partial_records'], 0)
        cut_chunk = self.cut[:4] + [self.cut[4][:60]]
        result = self.replay.parse(''.join(self.complete + cut_chunk), BUILD,
                                   tolerate_corruption=True, open_attempt=True)
        self.assertEqual(result['open_attempt']['complete_records'], ['SD: submit vmid=2'])
        self.assertEqual(result['open_attempt']['partial_records'], 0)

    def test_open_attempt_still_refuses_prefix_conflicts_and_needs_terminal(self):
        conflicting = snapshot_lines(['BUILD: identity=' + BUILD, 'XH3 LIFETIME state=ABORT'],
                                     snapshot=3)[:-1]
        with self.assertRaisesRegex(self.replay.CriticalReplayError, 'conflicts with the terminal prefix'):
            self.replay.parse(''.join(self.complete + conflicting), BUILD,
                              tolerate_corruption=True, open_attempt=True)
        with self.assertRaisesRegex(self.replay.CriticalReplayError, 'latest attempt is incomplete'):
            self.replay.parse(''.join(self.cut), BUILD, tolerate_corruption=True, open_attempt=True)
        with self.assertRaisesRegex(self.replay.CriticalReplayError, 'requires terminal-prefix'):
            self.replay.parse(''.join(self.complete), BUILD, open_attempt=True)
        clean = self.replay.parse(''.join(self.complete), BUILD,
                                  tolerate_corruption=True, open_attempt=True)
        self.assertIsNone(clean['open_attempt'])
        self.assertEqual(clean['records'], self.first)


if __name__ == '__main__':
    unittest.main()
