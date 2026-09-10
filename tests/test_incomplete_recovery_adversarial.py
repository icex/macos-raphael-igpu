"""Adversarial contracts for recovery from an incomplete CR2 capture."""
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

from tests.test_critical_replay import BUILD, snapshot_lines


ROOT = Path(__file__).resolve().parents[1]


def load_tool():
    path = ROOT / "tools/recover-incomplete-cr2.py"
    spec = importlib.util.spec_from_file_location("recover_incomplete_adversarial", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def seed_records(prefix=""):
    return [prefix + "ordinary", "XH2 OWNED nonce=owned",
            "XH2 POOL state=ACTIVE nonce=pool",
            "XH3 LIFETIME state=VALID nonce=valid"]


def valid_chunk(snapshot, record, part, parts, payload):
    domain = (bytes([1]) + bytes.fromhex(BUILD) +
              struct.pack("<IHBBB", snapshot, record, part, parts, len(payload)) + payload)
    return ("RGPU_CR2 v=1 b={} s={:08x} r={:04x} p={:02x}/{:02x} "
            "n={:02x} c={:08x} d={}\n").format(
                BUILD, snapshot, record, part, parts, len(payload),
                zlib.crc32(domain) & 0xffffffff, payload.hex())


class IncompleteRecoveryAdversarialTests(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool()
        self.replay = self.tool.load("critical-replay")

    def seed(self, lines):
        return self.tool.recovery_lease_seed("".join(lines), BUILD, self.replay)

    def test_canonical_attempt_blocks_retry_from_another_output_directory(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            proof = base / "proof.json"
            proof.write_text("{}\n")
            digest = hashlib.sha256(proof.read_bytes()).hexdigest()
            canonical = base / "canonical" / "attempt.json"
            first = base / "first"
            second = base / "second"
            receipt = {"schema": 6, "status": "recovered", "authorizes_launch": True}

            result = self.tool.execute_once(
                first, proof, digest, lambda: receipt,
                canonical_attempt=canonical, validate=lambda _receipt: [])
            self.assertEqual(result["status"], "complete")
            with self.assertRaises(FileExistsError):
                self.tool.execute_once(
                    second, proof, digest, lambda: receipt,
                    canonical_attempt=canonical, validate=lambda _receipt: [])
            self.assertFalse((second / "attempt.json").exists())

    def test_incomplete_receipt_is_failed_and_retained_for_review(self):
        receipt = {"schema": 6, "status": "incomplete", "authorizes_launch": False,
                   "boot_id": "boot", "prior_run_id": "run"}
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            proof = directory / "proof.json"
            proof.write_text("{}\n")
            digest = hashlib.sha256(proof.read_bytes()).hexdigest()
            result = self.tool.execute_once(
                directory, proof, digest, lambda: receipt,
                validate=lambda value: [] if value.get("authorizes_launch") else ["receipt"])
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["recovery"], receipt)
            self.assertIn("receipt", result["error"])
            self.assertEqual(json.loads((directory / "result.json").read_text()), result)

    def test_frozen_symlink_is_rejected_before_parsing(self):
        with tempfile.TemporaryDirectory() as td:
            run = Path(td) / "run"
            run.mkdir()
            target = Path(td) / "manifest-target.json"
            target.write_text("{}")
            (run / "manifest.json").symlink_to(target)
            with self.assertRaisesRegex(ValueError, "manifest.json is not a regular file"):
                self.tool.build_proof(run)

    def test_second_proof_build_refuses_source_or_evidence_drift(self):
        initial = {"boot_id": "same-boot", "source_sha256": {"tool": "a"}}
        changed = {"boot_id": "same-boot", "source_sha256": {"tool": "b"}}
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            evidence = base / "evidence"
            evidence.mkdir()
            proof_path = evidence / "proof.json"
            proof_path.write_text(json.dumps(initial))
            argv = ["recover-incomplete-cr2.py", "--vm-dir", str(base / "vm"),
                    "--run-dir", str(base / "run"), "--evidence-dir", str(evidence),
                    "--execute", "--reviewed-proof-sha256", "0" * 64]
            with patch.object(sys, "argv", argv), \
                 patch.object(self.tool, "build_proof", side_effect=[initial, changed]), \
                 patch.object(Path, "read_text", autospec=True,
                              side_effect=lambda path, *args, **kwargs:
                              "same-boot" if str(path).endswith("boot_id")
                              else json.dumps(initial)), \
                 self.assertRaisesRegex(SystemExit, "changed before execution"):
                self.tool.main()

    def test_rejects_abort_and_every_malformed_recovery_family(self):
        cases = [
            seed_records() + ["XH2 ABORT reason=late"],
            seed_records() + ["XH3 LIFETIME state=ABORT nonce=x"],
            seed_records() + ["XH2"],
            seed_records() + ["XH3 unknown"],
            seed_records() + ["XH2 POOL state=ACTIVE"],
        ]
        for records in cases:
            with self.subTest(record=records[-1]), self.assertRaisesRegex(
                    ValueError, "ABORT|malformed|conflicting"):
                self.seed(snapshot_lines(records, snapshot=4)[:-1])

    def test_rejects_part_count_and_record_index_conflicts(self):
        base = snapshot_lines(seed_records(), snapshot=4)[:-1]
        conflicting_part_count = valid_chunk(
            4, 1, 0, 2, b"XH2 OWNED nonce=owned".ljust(40, b"x"))
        with self.assertRaisesRegex(ValueError, "part counts|conflicting chunk"):
            self.seed(base + [conflicting_part_count])

        shifted = snapshot_lines(["padding"] + seed_records(), snapshot=5)[:-1]
        with self.assertRaisesRegex(ValueError, "record index changed"):
            self.seed(base + shifted)

    def test_rejects_noncanonical_chunk_order(self):
        lines = snapshot_lines(["x" * 80] + seed_records(), snapshot=4)[:-1]
        lines[0], lines[1] = lines[1], lines[0]
        with self.assertRaisesRegex(ValueError, "canonical|order"):
            self.seed(lines)

    def test_rejects_stale_snapshot_order(self):
        later = snapshot_lines(seed_records(), snapshot=5)[:-1]
        earlier = snapshot_lines(seed_records(), snapshot=4)[:-1]
        with self.assertRaisesRegex(ValueError, "snapshot.*order|stale snapshot"):
            self.seed(later + earlier)

    def test_rejects_end_loss_even_when_seed_records_are_complete(self):
        lines = snapshot_lines(seed_records(), snapshot=4, dropped=1)
        with self.assertRaisesRegex(ValueError, "END reports loss"):
            self.seed(lines)

    def test_rejects_chunk_after_same_snapshot_end(self):
        lines = snapshot_lines(seed_records(), snapshot=4)
        with self.assertRaisesRegex(ValueError, "END|canonical|order"):
            self.seed(lines + [lines[0]])

    def test_actual_recovery_receipt_requires_candidate_manifest_binding(self):
        vm = Path("/home/bogdan/macos-vm")
        run = vm / "run/metal-024-190"
        receipt_path = (vm / "run/vfio-recovery" /
                        "3bca3e47-1f28-4f78-af00-5dbf76b00620" /
                        "3ffc5f3dbec53665214863ed91fee0e7.json")
        if not receipt_path.exists():
            self.skipTest("candidate 190 recovery receipt unavailable")
        receipt_raw = receipt_path.read_bytes()
        self.assertEqual(hashlib.sha256(receipt_raw).hexdigest(),
                         "82560e48da2e6fb4300f5b0095e821d3da404d170108fd891ca7824aad49967a")

        # Validate copies so this test cannot mutate frozen evidence or the receipt.
        with tempfile.TemporaryDirectory() as td:
            fixture = Path(td)
            fixture_receipt = fixture / "receipt.json"
            fixture_manifest = fixture / "manifest.json"
            fixture_receipt.write_bytes(receipt_raw)
            fixture_manifest.write_bytes((run / "manifest.json").read_bytes())
            receipt = json.loads(fixture_receipt.read_text())
            manifest = json.loads(fixture_manifest.read_text())

            experiment = self.tool.load("experiment")
            boot = manifest["boot_id"]
            run_id = manifest["run_id"]
            hashes = manifest["recovery_helpers_sha256"]
            self.assertEqual(experiment.validate_recovery_receipt_v6(
                receipt, boot, run_id, hashes), [])
            self.assertEqual(experiment.validate_reuse_receipt(
                receipt, boot, run_id, vm, manifest=manifest,
                manifest_path=fixture_manifest), [])
            self.assertEqual(experiment.validate_reuse_receipt(
                receipt, boot, run_id, vm), ["recovery_receipt"])

            self.assertEqual((receipt["schema"], receipt["status"],
                              receipt["authorizes_launch"]), (6, "recovered", True))
            self.assertEqual((receipt["boot_id"], receipt["prior_run_id"]),
                             (boot, run_id))
            self.assertEqual(receipt["recovery_helpers_sha256"], hashes)
            gc = receipt["gc_quiesce"]
            self.assertEqual((gc["dequeued"], gc["dequeue_timeouts"],
                              gc["forced_inactive"], gc["active_after"]),
                             (2, 0, 0, 0))
            lifetime = gc["reservation"]["lifetime_readbacks"]
            self.assertEqual(lifetime["authenticated"], lifetime["pre_scratch"])
            self.assertTrue(gc["gfx_retirement_confirmed"])
            self.assertTrue(gc["gfx_ring_clean"])
            self.assertTrue(gc["graphics_pipe_proof_complete"])
            self.assertTrue(all(command["confirmed"] for command in receipt["commands"]))


if __name__ == "__main__":
    unittest.main()
