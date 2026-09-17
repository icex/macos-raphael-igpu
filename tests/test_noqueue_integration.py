import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]

def load(name):
    path = ROOT / "tools" / (name + ".py")
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


class NoQueueIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.nq = load("noqueue-qualification")
        cls.experiment = load("experiment")

    def snapshot(self):
        r = self.nq.R
        globals_ = {
            "c2pmsg_64": 0x80030000, "cp_stat": 0, "cpc_busy": 0,
            "me_cntl": r.CP_ME_HALT_MASK, "mec_cntl": r.CP_MEC_HALT_MASK,
            "pq_wptr_poll_cntl": 0, "pq_status": 0, "rb_doorbell_control": 0,
            "sdma0_gfx_rb_cntl": 0, "sdma0_gfx_ib_cntl": 0,
            "sdma0_page_rb_cntl": 0, "sdma0_page_ib_cntl": 0,
            "sdma0_rlc0_rb_cntl": 0, "sdma0_rlc0_ib_cntl": 0,
            "sdma0_rlc1_rb_cntl": 0, "sdma0_rlc1_ib_cntl": 0,
            "sdma0_cntl": 0, "sdma0_f32_cntl": r.SDMA_HALT_MASK,
            "sdma0_status": r.SDMA_STATUS_IDLE_MASK,
        }
        hqd = [[me, pipe, queue, 0, 0]
               for me in (1, 2) for pipe in range(4) for queue in range(8)]
        graphics = [[pipe, 0, 0, 0] for pipe in (0, 1)]
        scan = {"vfio_opened": True, "errors": [],
                "kernel_faults_before": [], "kernel_faults_after": [],
                "kernel_cursor_before": "cursor", "kernel_cursor_after": "cursor",
                "globals_before": globals_, "globals_after": globals_,
                "passes": [{"globals": globals_, "hqd": hqd, "graphics": graphics}] * 2,
                "selector_final": 0}
        return scan

    def test_complete_quiescent_snapshot_is_accepted(self):
        self.assertEqual(self.nq.validate_snapshot(self.snapshot()), [])

    def test_missing_hqd_or_active_queue_refuses(self):
        scan = self.snapshot(); scan["passes"][0]["hqd"] = scan["passes"][0]["hqd"][:-1]
        self.assertIn("hqd_coverage", self.nq.validate_snapshot(scan))
        scan = self.snapshot(); scan["passes"][0]["hqd"][0][3] = 1
        self.assertIn("hqd_active", self.nq.validate_snapshot(scan))

    def test_invalid_proof_does_not_append_or_consume_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); ledger = root / "boot-A.json"
            ledger.write_text(json.dumps({"schema": 2, "boot_id": "boot-A",
                                          "max_launches": 3,
                                          "launches": [{"run_id": "prior"}]}))
            before = ledger.read_bytes()
            manifest = root / "manifest.json"; manifest.write_text("{}")
            with self.assertRaises(ValueError):
                self.experiment.reserve_boot(root, "boot-A", "next",
                                              manifest_path=manifest,
                                              noqueue_proof={"schema": 8})
            self.assertEqual(ledger.read_bytes(), before)

    def proof(self, ledger_raw, manifest, boot="boot-A", run="next", prior="prior"):
        proof = self.snapshot()
        proof.update({"schema": 8, "kind": "same-boot-noqueue-qualification",
                      "authorizes_launch": True, "boot_id": boot, "run_id": run,
                      "prior_run_id": prior,
                      "ledger_preimage_sha256": self.nq.sha(ledger_raw),
                      "manifest_sha256": self.nq.sha(manifest.read_bytes()),
                      "helper_sha256": {
                          str(p): self.nq.sha(p.read_bytes())
                          for p in (Path(self.nq.__file__), Path(self.nq.R.__file__),
                                    Path(self.nq.N.__file__))},
                      "host_before": {"boot_id": boot, "active_vm": False,
                                      "driver": "vfio-pci", "device": "1002:13c0",
                                      "iommu_group": "31", "pci_command": 0,
                                      "reset_methods": []},
                      "host_after": {"boot_id": boot, "active_vm": False,
                                     "driver": "vfio-pci", "device": "1002:13c0",
                                     "iommu_group": "31", "pci_command": 0,
                                     "reset_methods": []},
                      "power_control": "on", "runtime_status": "active",
                      "post_host_gate_errors": []})
        return proof

    def test_valid_proof_appends_row_and_preserves_prior_reservation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); manifest = root / "manifest.json"; manifest.write_text("{}")
            ledger = root / "boot-A.json"
            ledger.write_text(json.dumps({"schema": 2, "boot_id": "boot-A",
                                          "max_launches": 3,
                                          "launches": [{"run_id": "prior"}]}))
            before = json.loads(ledger.read_text())
            raw = ledger.read_bytes()
            self.experiment.reserve_boot(root, "boot-A", "next", manifest_path=manifest,
                                         noqueue_proof=self.proof(raw, manifest))
            value = json.loads(ledger.read_text())
            self.assertEqual(value["launches"][0], before["launches"][0])
            self.assertEqual(value["launches"][-1]["run_id"], "next")
            self.assertEqual(len(value["launches"]), 2)

    def test_stale_duplicate_and_exhausted_proof_refuse_without_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); manifest = root / "manifest.json"; manifest.write_text("{}")
            ledger = root / "boot-A.json"
            ledger.write_text(json.dumps({"schema": 2, "boot_id": "boot-A",
                                          "max_launches": 3,
                                          "launches": [{"run_id": "prior"}]}))
            stale = self.proof(ledger.read_bytes(), manifest)
            ledger.write_text(ledger.read_text().replace("prior", "changed"))
            with self.assertRaises(ValueError):
                self.experiment.reserve_boot(root, "boot-A", "next", manifest_path=manifest,
                                             noqueue_proof=stale)
            duplicate = self.proof(ledger.read_bytes(), manifest, run="changed", prior="changed")
            with self.assertRaises(ValueError):
                self.experiment.reserve_boot(root, "boot-A", "changed", manifest_path=manifest,
                                             noqueue_proof=duplicate)
            # reserve_boot itself no longer enforces a launch-count ceiling (that
            # generic admission requirement is gone); noqueue-qualification.py's own
            # proof validator still bounds its own scheme independently, via "cap".
            ledger.write_text(json.dumps({"schema": 2, "boot_id": "boot-A", "max_launches": 3,
                                          "launches": [{"run_id": str(i)} for i in range(3)]}))
            with self.assertRaisesRegex(ValueError, "cap"):
                self.experiment.reserve_boot(root, "boot-A", "fresh", manifest_path=manifest,
                                             noqueue_proof=self.proof(ledger.read_bytes(), manifest,
                                                                       run="fresh", prior="2"))

    def test_noqueue_run_requires_proof_before_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); manifest = root / "manifest.json"
            manifest.write_text("{}")
            with self.assertRaises(ValueError):
                self.experiment.run_one(root, manifest, root / "output",
                                        noqueue_reuse={"schema": 8})

    def test_authorize_returns_validator_complete_proof_with_quiescent_vfio(self):
        nq, r = self.nq, self.nq.R
        class FakeVfio:
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def metadata(self): return {}
            def write32(self, _offset, _value): return None
            def read_vram32(self, _offset): return 0
            def read32(self, offset):
                if offset == r.C2PMSG_64_OFFSET: return 0x80030000
                if offset == r.SDMA0_STATUS_REG_OFFSET: return r.SDMA_STATUS_IDLE_MASK
                globals_ = self_globals()
                if offset in {value for value in nq.N.GLOBAL_OFFSETS.values()}:
                    return next((globals_.get(key, 0) for key, value in nq.N.GLOBAL_OFFSETS.items()
                                 if value == offset), 0)
                if offset in (r.CP_HQD_ACTIVE_OFFSET, r.CP_HQD_PQ_DOORBELL_OFFSET,
                              r.CP_RB_ACTIVE_OFFSET, nq.N.CP_RB1_ACTIVE_OFFSET,
                              r.CP_RB_DOORBELL_CONTROL_OFFSET): return 0
                return 0
        def self_globals():
            return {"cp_stat": 0, "cpc_busy": 0,
                    "me_cntl": r.CP_ME_HALT_MASK, "mec_cntl": r.CP_MEC_HALT_MASK,
                    "rb0_active": 0, "rb1_active": 0, "rb_doorbell_control": 0,
                    "sdma0_cntl": 0, "sdma0_f32_cntl": r.SDMA_HALT_MASK,
                    "pq_wptr_poll_cntl": 0, "pq_status": 0,
                    "c2pmsg_64": 0x80030000, "sdma0_gfx_rb_cntl": 0,
                    "sdma0_gfx_ib_cntl": 0, "sdma0_page_rb_cntl": 0,
                    "sdma0_page_ib_cntl": 0, "sdma0_rlc0_rb_cntl": 0,
                    "sdma0_rlc0_ib_cntl": 0, "sdma0_rlc1_rb_cntl": 0,
                    "sdma0_rlc1_ib_cntl": 0, "sdma0_status": r.SDMA_STATUS_IDLE_MASK}
        with tempfile.TemporaryDirectory() as directory:
            vm = Path(directory); prior = vm / "prior"; prior.mkdir()
            prior.joinpath("manifest.json").write_text(json.dumps({"run_id": "prior", "boot_id": "boot-A"}))
            prior.joinpath("verdict.json").write_text(json.dumps(
                {"verdict": "INVALID", "earliest_failure": "launcher"}))
            prior.joinpath("serial.txt").write_bytes(b""); prior.joinpath("critical.txt").write_bytes(b"")
            used = vm / "run/used-gpu-boots"; used.mkdir(parents=True)
            ledger = used / "boot-A.json"; ledger.write_text(json.dumps(
                {"schema": 2, "boot_id": "boot-A", "max_launches": 3,
                 "launches": [{"run_id": "prior"}]}))
            manifest = {"boot_id": "boot-A", "run_id": "next"}
            manifest_path = vm / "manifest.json"; manifest_path.write_text(json.dumps(manifest))
            good_host = {"boot_id": "boot-A", "active_vm": False, "driver": "vfio-pci",
                         "device": "1002:13c0", "iommu_group": r.GROUP,
                         "pci_command": 0, "reset_methods": []}
            original_read_text = Path.read_text
            with mock.patch.object(r, "host_state", return_value=good_host), \
                 mock.patch.object(r, "kernel_updates", side_effect=[("cursor", [], []), ("cursor", [], [])]), \
                 mock.patch.object(r, "LegacyVfio", FakeVfio), \
                 mock.patch.object(nq.subprocess, "run", return_value=mock.Mock(stdout="")), \
                 mock.patch.object(Path, "read_text", autospec=True) as read_text:
                read_text.side_effect = lambda self, *a, **k: "on" if str(self).endswith("power/control") else ("active" if str(self).endswith("runtime_status") else original_read_text(self, *a, **k))
                proof = nq.authorize(vm, prior, manifest, manifest_path, {"run_id": "prior"}, r, nq.N)
            self.assertTrue(proof["authorizes_launch"], proof)
            self.assertEqual(nq.validate_proof(proof, "boot-A", "next", ledger.read_bytes(),
                                               nq.sha(manifest_path.read_bytes())), [])

    def test_noqueue_admission_accepts_mocked_valid_proof_after_identity_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            vm = Path(directory); used = vm / "run/used-gpu-boots"; used.mkdir(parents=True)
            (used / "boot-A.json").write_text(json.dumps(
                {"schema": 2, "boot_id": "boot-A", "max_launches": 3,
                 "launches": [{"run_id": "prior"}]}))
            prior = vm / "prior"; prior.mkdir()
            (prior / "manifest.json").write_text(json.dumps({"run_id": "prior"}))
            manifest = {"boot_id": "boot-A", "run_id": "next"}
            manifest_path = vm / "manifest.json"; manifest_path.write_text(json.dumps(manifest))
            proof = {"schema": 8, "kind": "same-boot-noqueue-qualification",
                     "authorizes_launch": True, "run_id": "next", "prior_run_id": "prior"}
            fake_nq = mock.Mock(); fake_nq.authorize.return_value = proof
            fake_nq.validate_proof.return_value = []
            with mock.patch.object(self.experiment, "admit", return_value=[]), \
                 mock.patch.object(self.experiment, "helper", return_value=fake_nq):
                result, errors = self.experiment.noqueue_admission(
                    vm, {"boot_id": "boot-A"}, manifest, manifest_path, prior, [])
            self.assertEqual(errors, [])
            self.assertIs(result, proof)
            fake_nq.authorize.assert_called_once()


if __name__ == "__main__":
    unittest.main()
