import hashlib
import importlib.util
import json
from pathlib import Path
import re
import tempfile
import unittest

from tests.test_critical_replay import snapshot_lines


ROOT = Path(__file__).resolve().parents[1]
BUILD = '0123456789abcdef0123456789abcdef'
RUN_ID = '00112233445566778899aabbccddeeff'


def load_tool():
    path = ROOT / 'tools/candidate183-recovery-repair.py'
    spec = importlib.util.spec_from_file_location('candidate183_recovery_repair', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture(*, abort=False):
    donor = ['BUILD: identity=' + BUILD]
    donor.extend('event-%03d' % index for index in range(1, 134))
    donor.append(('XH2 ABORT reason=test' + ' ' * 100) if abort else 'D' * 121)
    target = donor + ['terminal-extra']
    donor_lines = snapshot_lines(donor, snapshot=2, build=BUILD)
    target_lines = snapshot_lines(target, snapshot=3, build=BUILD)
    damaged = [line for line in target_lines
               if not re.search(r' s=00000003 r=0086 p=', line)]
    damaged.insert(-1, 'RaphaelGPU rgpu: @ RGPU_CR2 interleaved garbage\n')
    return ''.join(donor_lines + damaged).encode(), donor, target


class Candidate183RecoveryRepairTests(unittest.TestCase):
    def test_inserts_only_donor_chunks_before_original_terminal_end(self):
        tool = load_tool()
        original, donor, target = fixture()
        derived, proof = tool.reconstruct_erasure(
            original, BUILD, donor_snapshot=2, terminal_snapshot=3,
            record=134, expected_parts=4)

        inserted = proof['inserted_bytes'].encode()
        offset = proof['insertion_offset']
        self.assertEqual(derived[:offset] + derived[offset + len(inserted):], original)
        self.assertEqual(derived[offset:offset + len(inserted)], inserted)
        self.assertEqual(proof['donor_record'], donor[134])
        self.assertEqual(proof['terminal_count'], len(target))
        self.assertEqual(proof['reconstructed_records_sha256'], hashlib.sha256(
            b'\0'.join(record.encode() for record in target)).hexdigest())
        self.assertEqual(len(proof['inserted_chunks']), 4)

    def test_unchanged_parser_refuses_original_and_accepts_derived_terminal(self):
        tool = load_tool()
        original, _, target = fixture()
        derived, proof = tool.reconstruct_erasure(
            original, BUILD, donor_snapshot=2, terminal_snapshot=3,
            record=134, expected_parts=4)
        replay = tool.load_tool('critical-replay')
        with self.assertRaisesRegex(replay.CriticalReplayError,
                                    'malformed transport line'):
            replay.parse(original.decode(), BUILD)
        with self.assertRaisesRegex(replay.CriticalReplayError, 'missing chunk'):
            replay.parse(original.decode(), BUILD, tolerate_corruption=True,
                         open_attempt=True)
        parsed = replay.parse(derived.decode(), BUILD, tolerate_corruption=True,
                              open_attempt=True)
        self.assertEqual(parsed['records'], target)
        self.assertEqual(parsed['crc32'], proof['terminal_end']['crc32'])
        self.assertEqual(parsed['fnv1a64'], proof['terminal_end']['fnv1a64'])

    def test_rejects_existing_target_part_conflict_and_later_transport(self):
        tool = load_tool()
        original, _, _ = fixture()
        donor_part = next(line for line in original.decode().splitlines(True)
                          if ' s=00000002 r=0086 p=00/04 ' in line)
        conflict = donor_part.replace('s=00000002', 's=00000003')
        # Its checksum remains donor-bound, so it is invalid rather than silently useful.
        cases = {
            'target record already has': original.replace(
                b'RaphaelGPU rgpu: @ RGPU_CR2 interleaved garbage\n',
                conflict.encode()),
            'transport after terminal': original + snapshot_lines(
                ['later'], snapshot=4, build=BUILD)[0].encode(),
        }
        for error, serial in cases.items():
            with self.subTest(error=error):
                with self.assertRaisesRegex(ValueError, error):
                    tool.reconstruct_erasure(serial, BUILD, 2, 3, 134, 4)

    def test_rejects_abort_in_reconstructed_records(self):
        tool = load_tool()
        original, _, _ = fixture(abort=True)
        with self.assertRaisesRegex(ValueError, 'ABORT'):
            tool.reconstruct_erasure(original, BUILD, 2, 3, 134, 4)

    def test_rejects_direct_abort_evidence_outside_replay(self):
        tool = load_tool()
        original, _, _ = fixture()
        original += b'RaphaelGPU      rgpu: @ XH2 ABORT nonce=bad reason=1\n'
        with self.assertRaisesRegex(ValueError, 'direct ABORT'):
            tool.reconstruct_erasure(original, BUILD, 2, 3, 134, 4)

    def test_execute_once_marks_attempt_before_callback_and_refuses_retry(self):
        tool = load_tool()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            proof_path = directory / 'proof.json'
            proof_path.write_text(json.dumps({'schema': 1}) + '\n')
            proof_sha = hashlib.sha256(proof_path.read_bytes()).hexdigest()
            observations = []

            def recover():
                observations.append((directory / 'attempt.json').exists())
                return {'schema': 6, 'status': 'recovered', 'recovery_id': 'a' * 32}

            result = tool.execute_once(directory, proof_path, proof_sha, recover)
            self.assertEqual(observations, [True])
            self.assertEqual(result['recovery']['recovery_id'], 'a' * 32)
            with self.assertRaisesRegex(FileExistsError, 'attempt.json'):
                tool.execute_once(directory, proof_path, proof_sha, recover)

    def test_execute_once_requires_exact_reviewed_proof_hash_without_write(self):
        tool = load_tool()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            proof_path = directory / 'proof.json'
            proof_path.write_text('{}\n')
            with self.assertRaisesRegex(ValueError, 'reviewed proof SHA-256'):
                tool.execute_once(directory, proof_path, '0' * 64, lambda: None)
            self.assertFalse((directory / 'attempt.json').exists())
            self.assertFalse((directory / 'result.json').exists())

    def test_execute_once_refuses_preexisting_result_before_callback(self):
        tool = load_tool()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            proof_path = directory / 'proof.json'
            proof_path.write_text('{}\n')
            proof_sha = hashlib.sha256(proof_path.read_bytes()).hexdigest()
            (directory / 'result.json').write_text('{}\n')
            called = []
            with self.assertRaisesRegex(FileExistsError, 'result.json'):
                tool.execute_once(directory, proof_path, proof_sha,
                                  lambda: called.append(True))
            self.assertEqual(called, [])
            self.assertFalse((directory / 'attempt.json').exists())

    def test_actual_frozen_candidate183_reconstructs_without_writing(self):
        tool = load_tool()
        run = Path('/home/bogdan/macos-vm/run/metal-016-183')
        if not run.exists():
            self.skipTest('frozen candidate183 evidence is not installed')
        before = sorted((path.name, hashlib.sha256(path.read_bytes()).hexdigest())
                        for path in run.iterdir() if path.is_file())
        _, proof = tool.build_proof(run)
        after = sorted((path.name, hashlib.sha256(path.read_bytes()).hexdigest())
                       for path in run.iterdir() if path.is_file())
        self.assertEqual(before, after)
        self.assertEqual(proof['run_id'], 'f1728b74e128c5acd35661334bff12be')
        self.assertEqual(proof['terminal_end']['crc32'], 0xf18488f3)
        self.assertEqual(proof['terminal_end']['fnv1a64'], 0x72e0f4557e90ee72)

    def test_lifetime_log_requires_exact_grammar_and_derived_checksum(self):
        tool = load_tool()
        run = Path('/home/bogdan/macos-vm/run/metal-016-183')
        if not run.exists():
            self.skipTest('frozen candidate183 evidence is not installed')
        derived, _ = tool.build_proof(run)
        replay = tool.load_tool('critical-replay')
        records = replay.parse(derived.decode(), tool.BUILD_ID,
                               tolerate_corruption=True, open_attempt=True)['records']
        vfio = tool.load_tool('vfio-recover')
        lease = vfio.parse_v2_lease_records(
            [value for value in records if value.startswith('XH2 ')], tool.RUN_ID)
        lifetime = tool.load_tool('recovery_lifetime_v3')
        line = next(value for value in records
                    if value.startswith('XH3 LIFETIME state=VALID '))
        tool.validate_lifetime_record(line, lease, lifetime)
        mutations = (line + ' trailing', line.replace('checksum=0x', 'checksum=0x0'),
                     line.replace('state=VALID', 'state=ABORT'))
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                with self.assertRaisesRegex(ValueError, 'lifetime'):
                    tool.validate_lifetime_record(mutation, lease, lifetime)

    def test_build_proof_rejects_changed_frozen_input(self):
        tool = load_tool()
        source = Path('/home/bogdan/macos-vm/run/metal-016-183')
        if not source.exists():
            self.skipTest('frozen candidate183 evidence is not installed')
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary) / 'run/metal-016-183'
            run.mkdir(parents=True)
            for name in ('manifest.json', 'serial.txt', 'recovery.json', 'verdict.json'):
                (run / name).write_bytes((source / name).read_bytes())
            (run / 'serial.txt').write_bytes((run / 'serial.txt').read_bytes() + b'x')
            with self.assertRaisesRegex(ValueError, 'serial.txt SHA-256 mismatch'):
                tool.build_proof(run)

    def test_requires_pinned_boot_id(self):
        tool = load_tool()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'boot_id'
            path.write_text('different\n')
            with self.assertRaisesRegex(ValueError, 'pinned live boot'):
                tool.require_boot_id(path)

    def test_helper_recheck_rejects_drift(self):
        tool = load_tool()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / 'tools/helper.py'
            path.parent.mkdir()
            path.write_bytes(b'original')
            expected = {'tools/helper.py': hashlib.sha256(b'original').hexdigest()}
            tool.require_helper_files(root, expected)
            path.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'helper drift'):
                tool.require_helper_files(root, expected)


if __name__ == '__main__':
    unittest.main()
