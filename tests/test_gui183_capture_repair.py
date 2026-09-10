import hashlib
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

from tests.test_critical_replay import snapshot_lines


ROOT = Path(__file__).resolve().parents[1]
BUILD = '0123456789abcdef0123456789abcdef'


def load_tool():
    path = ROOT / 'tools/gui183-capture-repair.py'
    spec = importlib.util.spec_from_file_location('gui183_capture_repair', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Gui183CaptureRepairTests(unittest.TestCase):
    def fixture(self):
        tool = load_tool()
        donor = ['BUILD: identity=' + BUILD] + [f'record-{n:03d}' for n in range(1, 186)]
        donor[43] = 'XH2 OWNED nonce=test'
        donor[65] = 'XH2 POOL state=ACTIVE nonce=test'
        donor[66] = 'XH3 LIFETIME state=VALID nonce=test'
        target = donor + [f'extra-{n:03d}' for n in range(186, 265)]
        lines0 = snapshot_lines(donor, snapshot=0, build=BUILD)
        lines1 = snapshot_lines(target, snapshot=1, build=BUILD)
        missing = {(63, 0), (64, 0)}
        damaged = [line for line in lines1 if not any(
            f' r={record:04x} p={part:02x}/' in line for record, part in missing)]
        damaged.insert(-1, 'RaphaelGPU rgpu: @ RGPU_CR2 interleaved garbage\n')
        return tool, ''.join(lines0 + damaged).encode(), donor, target, missing

    def test_insertion_only_reconstruction_uses_exact_donor_keys(self):
        tool, original, donor, target, missing = self.fixture()
        derived, proof = tool.reconstruct(original, BUILD, 0, 1, missing)
        offset = proof['insertion_offset']
        inserted = proof['inserted_bytes'].encode()
        self.assertEqual(derived[:offset] + derived[offset + len(inserted):], original)
        self.assertEqual(proof['missing_chunks'], [[63, 0], [64, 0]])
        replay = tool.load_replay()
        self.assertEqual(replay.parse(derived.decode(), BUILD,
                                      tolerate_corruption=True)['records'], target)
        self.assertEqual(proof['donor_record_count'], len(donor))

    def test_rejects_unexpected_missing_key_and_valid_target_conflict(self):
        tool, original, _, _, missing = self.fixture()
        with self.assertRaisesRegex(ValueError, 'missing chunk set'):
            tool.reconstruct(original, BUILD, 0, 1, {(63, 0)})
        replay = tool.load_replay()
        conflict = tool._line(replay, BUILD, 1, 63, 0, 1, b'different')
        with self.assertRaisesRegex(ValueError, 'conflicts with donor prefix'):
            tool.reconstruct(original.replace(
                b'RaphaelGPU rgpu: @ RGPU_CR2 interleaved garbage\n', conflict.encode()),
                BUILD, 0, 1, missing)

    def test_rejects_foreign_later_and_direct_abort_transport(self):
        tool, original, _, _, missing = self.fixture()
        end = original.rfind(b'RaphaelGPU      rgpu: @ RGPU_END2')
        foreign = tool._line(tool.load_replay(), 'f' * 32, 1, 63, 0, 1, b'x')
        cases = {
            'foreign build': original[:end] + foreign.encode() + original[end:],
            'transport after terminal': original + tool._line(
                tool.load_replay(), BUILD, 2, 0, 0, 1, b'x').encode(),
            'ABORT': original + b'RaphaelGPU rgpu: @ XH2 ABORT reason=test\n',
        }
        for error, value in cases.items():
            with self.subTest(error=error), self.assertRaisesRegex(ValueError, error):
                tool.reconstruct(value, BUILD, 0, 1, missing)

    def test_rejects_wrong_donor_and_terminal_mutation(self):
        tool, original, _, _, missing = self.fixture()
        with self.assertRaisesRegex(ValueError, 'donor'):
            tool.reconstruct(original, BUILD, 2, 1, missing)
        changed = original.replace(b'count=0109', b'count=0108')
        with self.assertRaises(Exception):
            tool.reconstruct(changed, BUILD, 0, 1, missing)

    def test_actual_frozen_run_is_read_only_and_reconstructs(self):
        tool = load_tool()
        run = Path(os.environ.get('RGPU_GUI183_RUN',
                                  Path.home() / 'macos-vm/run/metal-016-183-gui-73ad3355'))
        if not run.exists():
            self.skipTest('frozen GUI evidence unavailable')
        before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in run.iterdir() if p.is_file()}
        derived, proof = tool.build_proof(run)
        after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in run.iterdir() if p.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(proof['run_id'], tool.RUN_ID)
        self.assertEqual(len(proof['reconstruction']['missing_chunks']), 407)
        self.assertEqual(proof['reconstruction']['terminal_end']['crc32'], 0x479b28cb)
        self.assertEqual(proof['reconstruction']['terminal_end']['fnv1a64'], 0xa4dd20b0b45780c4)
        self.assertGreater(len(derived), len((run / 'serial.txt').read_bytes()))

    def test_write_outputs_is_exclusive_and_does_not_touch_sources(self):
        tool, original, _, _, missing = self.fixture()
        derived, proof = tool.reconstruct(original, BUILD, 0, 1, missing)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'new'
            tool.write_outputs(output, derived, proof)
            self.assertEqual((output / 'derived-serial.txt').read_bytes(), derived)
            with self.assertRaises(FileExistsError):
                tool.write_outputs(output, derived, proof)


if __name__ == '__main__':
    unittest.main()
