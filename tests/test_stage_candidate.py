import hashlib
import copy
import gzip
import importlib.util
import json
import plistlib
from pathlib import Path
import re
import tempfile
import shutil
import subprocess
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "stage-candidate.py"
TRANSPORT = {
    "kind": "isa-serial", "version": 1, "index": 1,
    "io_base": 760, "baud": 115200,
    "socket": "run/critical.sock", "capture": "critical.txt",
}


def load_tool():
    spec = importlib.util.spec_from_file_location("stage_candidate", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module



class CardManagedBootArgumentKeysTest(unittest.TestCase):
    def test_collects_functional_keys_from_every_card(self):
        import importlib.util, json, tempfile
        spec = importlib.util.spec_from_file_location(
            "stage_candidate_keys", ROOT / "tools/stage-candidate.py")
        tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tool)
        with tempfile.TemporaryDirectory() as directory:
            cards = Path(directory)
            (cards / "metal-001.json").write_text(json.dumps(
                {"functional_boot_arguments": {"rgpuvmroot": "5", "rgpumqdrestore": "3"}}))
            (cards / "metal-002.json").write_text(json.dumps(
                {"functional_boot_arguments": {"rgpuvmroot": "5", "rgpudump": "5000"}}))
            (cards / "metal-003.json").write_text("not json")
            (cards / "other.json").write_text(json.dumps(
                {"functional_boot_arguments": {"rgpuignored": "1"}}))
            self.assertEqual(tool.card_managed_boot_argument_keys(cards),
                             {"rgpuvmroot", "rgpumqdrestore", "rgpudump"})
        # The repository cards include the candidate-209 probe key, so a card
        # without it must not inherit it from the live configuration.
        self.assertIn("rgpumqdrestore", tool.card_managed_boot_argument_keys())

class Candidate180StageTests(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool()
        self.tool.configure("1.0.180", "metal-013")
        self.card = {
            "id": "metal-013",
            "candidate_version": "1.0.180",
            "requested_diagnostic": "rgpusubmit=1",
            "max_seconds": 180,
            "run_probe_only_after_native_start": True,
            "critical_replay_schema": 2,
            "recovery_lease_schema": 3,
        }

    def encoded_card(self, update=None):
        card = dict(self.card)
        if update:
            card.update(update)
        raw = (json.dumps(card, sort_keys=True) + "\n").encode()
        return raw, hashlib.sha256(raw).hexdigest()

    def test_exact_candidate_and_protocol_card_is_accepted(self):
        raw, digest = self.encoded_card()
        self.assertEqual(self.tool.validate_card(raw, digest), self.card)

    def test_future_max_seconds_boundary_accepts_6000_only(self):
        raw, digest = self.encoded_card({"max_seconds": 6000})
        self.assertEqual(self.tool.validate_card(raw, digest)["max_seconds"], 6000)
        raw, digest = self.encoded_card({"max_seconds": 6001})
        with self.assertRaisesRegex(RuntimeError, "1 to 6000"):
            self.tool.validate_card(raw, digest)

    def test_dedicated_transport_requires_exact_object_and_boot_argument(self):
        raw, digest = self.encoded_card({
            "critical_replay_transport": TRANSPORT,
        })
        accepted = self.tool.validate_card(raw, digest)
        self.assertEqual(accepted["critical_replay_transport"], TRANSPORT)
        for mutation in (
                {"baud": 9600}, {"index": 0}, {"socket": "run/serial.sock"},
                {"capture": "serial.txt"}, {"extra": True}, {"version": True},
                {"index": True}, {"baud": 115200.0}):
            bad_transport = dict(TRANSPORT, **mutation)
            bad, bad_digest = self.encoded_card({
                "critical_replay_transport": bad_transport,
            })
            with self.assertRaisesRegex(RuntimeError, "critical replay transport"):
                self.tool.validate_card(bad, bad_digest)

    def test_card_digest_and_exact_numeric_schemas_are_pinned(self):
        raw, digest = self.encoded_card()
        with self.assertRaisesRegex(RuntimeError, "card digest"):
            self.tool.validate_card(raw, "0" * 64)
        for key, value in (
                ("critical_replay_schema", True),
                ("critical_replay_schema", 1),
                ("recovery_lease_schema", True),
                ("recovery_lease_schema", 2),
                ("candidate_version", "1.0.179"),
                ("id", "metal-012")):
            bad, bad_digest = self.encoded_card({key: value})
            with self.assertRaises(RuntimeError, msg=f"accepted {key}={value!r}"):
                self.tool.validate_card(bad, bad_digest)

    def test_publication_flags_are_armed_before_mutation(self):
        flags = {"raw": False, "staging": False}

        def fail(*_):
            raise RuntimeError("injected interruption")

        with self.assertRaisesRegex(RuntimeError, "injected interruption"):
            self.tool.armed_replace("source", "target", flags, "raw", replace=fail)
        self.assertTrue(flags["raw"])
        with self.assertRaisesRegex(RuntimeError, "injected interruption"):
            self.tool.armed_exclusive_link(
                "source", "target", flags, "staging", link=fail)
        self.assertTrue(flags["staging"])

    def test_source_preserves_reviewed_transaction_boundaries(self):
        source = TOOL.read_text()
        stage = source[source.index("def stage("):source.index("def main(")]
        self.assertIn("ROOT.resolve() != WT.resolve()", source)
        self.assertLess(stage.index("verify_worktree_before_import("),
                        stage.index("load_module("))
        self.assertLess(stage.index("select_run_id()"),
                        stage.index("make_staged_config("))
        self.assertEqual(stage.count("active_or_pending_vm()"), 1)
        self.assertGreaterEqual(
            stage.count("live raw ESP changed"), 2)
        self.assertGreaterEqual(
            stage.count("live OpenCore.qcow2 changed"), 2)
        self.assertGreaterEqual(
            stage.count("live config.plist changed"), 2)
        first_replace = stage.index("armed_replace(private_raw")
        last_boundary = stage.rindex(
            "live config.plist changed at publication boundary", 0, first_replace)
        self.assertLess(last_boundary, first_replace)
        metadata_link = stage.index("armed_exclusive_link(")
        for token in ("file_has_sha(staged_config_path, staged_config_sha)",
                      "file_has_sha(pending_record, staging_record_sha)"):
            self.assertLess(stage.index(token), metadata_link)
        self.assertRegex(
            stage,
            re.compile(r"critical_replay_schema=card\["
                       r"['\"]critical_replay_schema['\"]\]"))
        self.assertRegex(
            stage,
            re.compile(r"recovery_lease_schema=card\["
                       r"['\"]recovery_lease_schema['\"]\]"))

    def test_source_pin_requires_real_commit_and_identical_source_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.invalid"], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.name", "test"], check=True)
            (root / "src").mkdir()
            (root / "src" / "driver").write_text("restored\n")
            subprocess.run(["git", "-C", str(root), "add", "src"], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "source"], check=True)
            source = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
            (root / "card.json").write_text("card\n")
            subprocess.run(["git", "-C", str(root), "add", "card.json"], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "coordinator"], check=True)
            self.tool.WT = root
            self.tool.verify_source_commit(source)
            with self.assertRaisesRegex(RuntimeError, "source differs"):
                (root / "src" / "driver").write_text("changed\n")
                self.tool.verify_source_commit(source)
            subprocess.run(["git", "-C", str(root), "add", "src"], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "source drift"], check=True)
            with self.assertRaisesRegex(RuntimeError, "source differs"):
                self.tool.verify_source_commit(source)
            with self.assertRaisesRegex(RuntimeError, "does not exist"):
                self.tool.verify_source_commit("0" * 40)

    def test_optional_picker_timeout_changes_only_open_core_boot_timeout(self):
        config = {
            "Misc": {"Boot": {"ShowPicker": True, "Timeout": 45,
                                "TakeoffDelay": 0}},
            "NVRAM": {"Add": {"unchanged": {"boot-args": "rgpusubmit=1"}}},
        }
        self.tool.apply_guest_picker_timeout(
            config, dict(self.card, guest_picker_timeout_seconds=5))
        self.assertEqual(config["Misc"]["Boot"]["Timeout"], 5)
        self.assertTrue(config["Misc"]["Boot"]["ShowPicker"])
        self.assertEqual(config["Misc"]["Boot"]["TakeoffDelay"], 0)
        self.assertEqual(config["NVRAM"],
                         {"Add": {"unchanged": {"boot-args": "rgpusubmit=1"}}})

    def test_absent_picker_timeout_preserves_historical_config(self):
        config = {"Misc": {"Boot": {"ShowPicker": True, "Timeout": 45}}}
        before = json.loads(json.dumps(config))
        self.tool.apply_guest_picker_timeout(config, self.card)
        self.assertEqual(config, before)

    def test_picker_timeout_rejects_bad_type_range_or_hidden_picker(self):
        for value in (True, 0, 301, "5"):
            with self.assertRaisesRegex(RuntimeError, "guest picker timeout"):
                self.tool.apply_guest_picker_timeout(
                    {"Misc": {"Boot": {"ShowPicker": True}}},
                    dict(self.card, guest_picker_timeout_seconds=value))
            raw, digest = self.encoded_card(
                {"guest_picker_timeout_seconds": value})
            with self.assertRaisesRegex(RuntimeError, "guest picker timeout"):
                self.tool.validate_card(raw, digest)
        with self.assertRaisesRegex(RuntimeError, "ShowPicker=true"):
            self.tool.apply_guest_picker_timeout(
                {"Misc": {"Boot": {"ShowPicker": False}}},
                dict(self.card, guest_picker_timeout_seconds=5))


class Candidate184StageTests(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool()
        self.tool.configure("1.0.184", "metal-017")
        self.card = {
            "id": "metal-017",
            "candidate_version": "1.0.184",
            "requested_diagnostic": "rgpuvmdiag=1",
            "max_seconds": 180,
            "run_probe_only_after_native_start": True,
            "critical_replay_schema": 2,
            "recovery_lease_schema": 3,
            "critical_replay_transport": TRANSPORT,
            "critical_replay_tolerance": "terminal-prefix",
            "recovery_critical_replay_tolerance": "terminal-prefix-open",
            "functional_boot_arguments": {"rgpuvmroot": "4"},
            "conditional_diagnostic_observations": [
                "vmid1_fault_walk", "vmid1_fault_walk_view",
                "vmid1_fault_walk_entry",
            ],
            "launch_options": {
                "BOOTDISK_MODE": "custom", "NVRAM": "stock",
                "GENERIC_GRAPHICS": "off",
            },
        }

    def encoded(self, card=None):
        raw = (json.dumps(card or self.card, sort_keys=True) + "\n").encode()
        return raw, hashlib.sha256(raw).hexdigest()

    def test_exact_metal017_contract_is_accepted(self):
        raw, digest = self.encoded()
        self.assertEqual(self.tool.validate_card(raw, digest), self.card)

    def test_explicit_candidate184_remains_selectable(self):
        tool = load_tool()
        tool.configure("1.0.184", "metal-017")
        self.assertEqual((tool.CANDIDATE_VERSION, tool.CARD_ID),
                         ("1.0.184", "metal-017"))

    def test_checked_in_metal017_preserves_functional_path_and_bounds_fault_scope(self):
        raw = (ROOT / "experiments/metal-017.json").read_bytes()
        card = self.tool.validate_card(raw, hashlib.sha256(raw).hexdigest())
        for key, value in self.card.items():
            self.assertEqual(card[key], value)
        self.assertIn("rgpusubmit=1", card["behavior_change"])
        self.assertIn("at most two distinct VMID1 fault pairs", card["question"])
        self.assertNotIn("vmid1_fault_walk", card["required_observations"])
        self.assertEqual(card["conditional_diagnostic_observations"], [
            "vmid1_fault_walk", "vmid1_fault_walk_view",
            "vmid1_fault_walk_entry"])
        self.assertIn("absence of a matching VMID1 fault is inconclusive",
                      card["repeat_policy"])
        self.assertNotIn("retry", card.get("launch_options", {}))

    def test_metal017_diagnostic_functional_transport_and_launch_are_exact(self):
        mutations = (
            {"requested_diagnostic": "rgpusubmit=1"},
            {"requested_diagnostic": "rgpuvmdiag=2"},
            {"functional_boot_arguments": {}},
            {"functional_boot_arguments": {"rgpuvmroot": "4", "rgpuvmdiag": "1"}},
            {"critical_replay_transport": dict(TRANSPORT, index=0)},
            {"critical_replay_tolerance": "terminal-prefix-open"},
            {"recovery_critical_replay_tolerance": "terminal-prefix"},
            {"launch_options": {"BOOTDISK_MODE": "custom", "NVRAM": "stock"}},
            {"launch_options": {"BOOTDISK_MODE": "custom", "NVRAM": "stock",
                                "GENERIC_GRAPHICS": "on"}},
        )
        for update in mutations:
            card = dict(self.card, **update)
            raw, digest = self.encoded(card)
            with self.assertRaises(RuntimeError, msg=f"accepted {update!r}"):
                self.tool.validate_card(raw, digest)

    def test_all_supported_historical_card_contracts_remain_accepted(self):
        for number, card_id in ((180, "metal-013"), (181, "metal-014"),
                                (182, "metal-015"), (183, "metal-016")):
            with self.subTest(number=number, card_id=card_id):
                self.tool.configure(f"1.0.{number}", card_id)
                raw = (ROOT / f"experiments/{card_id}.json").read_bytes()
                card = self.tool.validate_card(raw, hashlib.sha256(raw).hexdigest())
                self.assertEqual(card["requested_diagnostic"], "rgpusubmit=1")

    def test_only_reviewed_candidate_card_pairs_are_supported(self):
        self.tool.configure("1.0.184", "metal-016")
        raw, digest = self.encoded(dict(self.card, id="metal-016"))
        with self.assertRaisesRegex(RuntimeError, "supported candidate card"):
            self.tool.validate_card(raw, digest)

    def test_boot_updates_add_requested_diagnostic_once_and_keep_submission_path(self):
        updates = self.tool.candidate_boot_argument_updates(
            self.card, 0x12, 0x34)
        self.assertEqual(updates["rgpuvmdiag"], "1")
        self.assertEqual(updates["rgpusubmit"], "1")
        self.assertEqual(updates["rgpuvmroot"], "4")
        self.assertEqual(updates["rgpucr2uart"], "2")
        self.assertEqual(updates["rgpurnlo"], "0x12")
        self.assertEqual(updates["rgpurnhi"], "0x34")

    def test_boot_updates_add_quiesce_only_when_card_selects_it(self):
        updates = self.tool.candidate_boot_argument_updates(self.card, 0x12, 0x34)
        self.assertNotIn("rgpucr2quiesce", updates)
        quiesced = dict(self.card, critical_replay_quiesce={"version": 1})
        updates = self.tool.candidate_boot_argument_updates(quiesced, 0x12, 0x34)
        self.assertEqual(updates["rgpucr2quiesce"], "1")
        self.assertEqual(updates["rgpucr2uart"], "2")

    def test_staging_metadata_preserves_new_launch_contract(self):
        source = TOOL.read_text()
        self.assertIn('staging["launch_options"] = card["launch_options"]', source)


class Candidate185StageTests(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool()
        self.tool.configure("1.0.185", "metal-018")
        self.card = json.loads((ROOT / "experiments/metal-018.json").read_text())

    def test_exact_metal018_contract_is_accepted(self):
        raw = (json.dumps(self.card, sort_keys=True) + "\n").encode()
        self.assertEqual(
            self.tool.validate_card(raw, hashlib.sha256(raw).hexdigest()), self.card)

    def test_candidate185_remains_explicitly_selectable(self):
        tool = load_tool()
        tool.configure("1.0.185", "metal-018")
        self.assertEqual((tool.CANDIDATE_VERSION, tool.CARD_ID),
                         ("1.0.185", "metal-018"))

    def test_checked_in_metal018_preserves_candidate184_contract(self):
        card = self.tool.validate_card(
            (ROOT / "experiments/metal-018.json").read_bytes(),
            hashlib.sha256((ROOT / "experiments/metal-018.json").read_bytes()).hexdigest())
        self.assertEqual(card["requested_diagnostic"], "rgpuvmdiag=1")
        self.assertEqual(card["functional_boot_arguments"], {"rgpuvmroot": "4"})
        self.assertEqual(card["critical_replay_transport"], TRANSPORT)
        self.assertEqual(card["launch_options"]["GENERIC_GRAPHICS"], "off")
        self.assertEqual(card["conditional_diagnostic_observations"], [
            "vmid1_fault_walk", "vmid1_fault_walk_view", "vmid1_fault_walk_entry"])
        self.assertIn("candidate 184 had no GPU run", card["repeat_policy"])
        self.assertEqual(card["regression_baselines"]["immediate"],
                         "run/metal-016-183-gui-73ad3355")

    def test_historical_candidate184_pair_remains_supported(self):
        self.tool.configure("1.0.184", "metal-017")
        raw = (ROOT / "experiments/metal-017.json").read_bytes()
        card = self.tool.validate_card(raw, hashlib.sha256(raw).hexdigest())
        self.assertEqual(card["requested_diagnostic"], "rgpuvmdiag=1")


class Candidate186StageTests(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool()
        self.tool.configure("1.0.186", "metal-019")
        self.card = json.loads((ROOT / "experiments/metal-019.json").read_text())

    def test_exact_metal019_contract_pins_headless_lilu_and_delay(self):
        raw = (ROOT / "experiments/metal-019.json").read_bytes()
        accepted = self.tool.validate_card(raw, hashlib.sha256(raw).hexdigest())
        self.assertEqual(accepted["candidate_version"], "1.0.186")
        self.assertEqual(accepted["required_boot_flags"], ["-liluheadless"])
        self.assertEqual(accepted["functional_boot_arguments"], {
            "rgpuvmroot": "4", "rgpudump": "5000"})
        self.assertEqual(accepted["raphael_source_sha256"],
                         "db511634c6d292ef3a65285e56bd5cf5f9e03cf4c20680a27b96c46a18f2e9b0")
        self.assertEqual(accepted["max_seconds"], 180)
        self.assertIn("unchanged 45-second Metal probe", accepted["behavior_change"])
        self.assertEqual(accepted["launch_options"]["GENERIC_GRAPHICS"], "off")

    def test_staging_defaults_select_candidate188(self):
        tool = load_tool()
        self.assertEqual((tool.CANDIDATE_VERSION, tool.CARD_ID),
                         ("1.0.188", "metal-021"))

    def test_candidate186_boot_contract_adds_headless_flag_once(self):
        updates = self.tool.candidate_boot_argument_updates(self.card, 0x12, 0x34)
        self.assertEqual(updates["rgpudump"], "5000")
        self.assertEqual(self.tool.candidate_boot_flags(self.card), ["-liluheadless"])

    def test_candidate186_build_validation_requires_version_186_info_plist(self):
        source = TOOL.read_text()
        self.assertIn("CANDIDATE_VERSION, CANDIDATE_VERSION", source)
        self.assertIn("candidate_version=CANDIDATE_VERSION", source)
        self.assertIn('identities["source_sha256"] != card["raphael_source_sha256"]',
                      source)

    def test_staging_metadata_records_lilu_provenance_and_readbacks(self):
        source = TOOL.read_text()
        stage = source[source.index("def stage("):source.index("def main(")]
        self.assertIn("staging.update(lilu)", stage)
        self.assertGreaterEqual(stage.count("candidate_image_files("), 4)
        self.assertLess(stage.index("candidate qcow2 readback failed"),
                        stage.index("armed_replace(private_raw"))
        self.assertLess(stage.index("published qcow2 readback failed"),
                        stage.index("armed_exclusive_link("))

    def test_candidate186_requires_explicit_lilu_pins(self):
        with self.assertRaisesRegex(RuntimeError, "Lilu bundle"):
            self.tool.validate_lilu_inputs(None, None, None, None)

    def test_candidate187_selects_fresh_pci_slot6_card_with_lilu_pins(self):
        self.tool.configure("1.0.187", "metal-020")
        raw = (ROOT / "experiments/metal-020.json").read_bytes()
        card = self.tool.validate_card(raw, hashlib.sha256(raw).hexdigest())
        self.assertEqual(card["candidate_version"], "1.0.187")
        self.assertEqual(card["required_boot_flags"], ["-liluheadless"])
        self.assertEqual(card["functional_boot_arguments"],
                         {"rgpuvmroot": "4", "rgpudump": "5000"})
        self.assertEqual(card["raphael_source_sha256"],
                         "db511634c6d292ef3a65285e56bd5cf5f9e03cf4c20680a27b96c46a18f2e9b0")
        self.assertIn("metal-019-186", card["regression_baselines"]["immediate"])

    def test_candidate187_rejects_missing_headless_flag_or_wrong_source_pin(self):
        self.tool.configure("1.0.187", "metal-020")
        raw = json.loads((ROOT / "experiments/metal-020.json").read_text())
        for mutation in (
                {"required_boot_flags": []},
                {"raphael_source_sha256": "0" * 64}):
            bad = dict(raw, **mutation)
            encoded = (json.dumps(bad) + "\n").encode()
            with self.assertRaisesRegex(RuntimeError, "candidate card contract"):
                self.tool.validate_card(encoded, hashlib.sha256(encoded).hexdigest())

    def test_candidate187_requires_explicit_lilu_pins(self):
        self.tool.configure("1.0.187", "metal-020")
        with self.assertRaisesRegex(RuntimeError, "Lilu bundle"):
            self.tool.validate_lilu_inputs(None, None, None, None)

    def test_candidate188_selects_gdb_mapping_capture_card_with_inherited_pins(self):
        self.tool.configure("1.0.188", "metal-021")
        raw = (ROOT / "experiments/metal-021.json").read_bytes()
        card = self.tool.validate_card(raw, hashlib.sha256(raw).hexdigest())
        self.assertEqual(card["candidate_version"], "1.0.188")
        self.assertIn("gdb_vmid1_wrap_vmm_update_entries_inputs",
                      card["required_observations"])
        self.assertIn("gdb_vmid1_wrap_vmm_update_entries_native_output",
                      card["required_observations"])
        self.assertEqual(card["required_boot_flags"], ["-liluheadless"])
        self.assertEqual(card["raphael_source_sha256"],
                         "db511634c6d292ef3a65285e56bd5cf5f9e03cf4c20680a27b96c46a18f2e9b0")

    def test_candidate188_rejects_missing_debug_capture_prerequisite_or_observation(self):
        self.tool.configure("1.0.188", "metal-021")
        original = json.loads((ROOT / "experiments/metal-021.json").read_text())
        for mutation in (
                {"prerequisites": [p for p in original["prerequisites"]
                                    if p != "gdb_debug_artifact_and_symbol_provenance_pinned"]},
                {"required_observations": [o for o in original["required_observations"]
                                            if o != "gdb_vmid1_wrap_vmm_update_entries_native_output"]},
                {"raphael_source_sha256": "0" * 64}):
            bad = dict(original, **mutation)
            encoded = (json.dumps(bad) + "\n").encode()
            with self.assertRaisesRegex(RuntimeError, "candidate card contract"):
                self.tool.validate_card(encoded, hashlib.sha256(encoded).hexdigest())

    def test_candidate189_selects_corrected_client_root_card(self):
        self.tool.configure("1.0.189", "metal-023")
        raw = (ROOT / "experiments/metal-023.json").read_bytes()
        card = self.tool.validate_card(raw, hashlib.sha256(raw).hexdigest())
        self.assertEqual(card["raphael_source_sha256"],
                         "7515f121230fbd26e32b198bd622e106155708e4108d9def96dcc7daa9d173f3")
        self.assertEqual(card["max_seconds"], 180)
        self.assertTrue(card["run_probe_only_after_native_start"])
        self.assertEqual(card["launch_options"]["GDB"], "on")
        old = dict(card, raphael_source_sha256=
                   "db511634c6d292ef3a65285e56bd5cf5f9e03cf4c20680a27b96c46a18f2e9b0")
        encoded = (json.dumps(old) + "\n").encode()
        with self.assertRaisesRegex(RuntimeError, "candidate card contract"):
            self.tool.validate_card(encoded, hashlib.sha256(encoded).hexdigest())

    def test_candidate190_preserves_candidate189_gpu_source(self):
        self.tool.configure("1.0.190", "metal-024")
        raw = (ROOT / "experiments/metal-024.json").read_bytes()
        card = self.tool.validate_card(raw, hashlib.sha256(raw).hexdigest())
        self.assertEqual(card["raphael_source_sha256"],
                         "7515f121230fbd26e32b198bd622e106155708e4108d9def96dcc7daa9d173f3")
        self.assertIn("strict_logind_sleep_idle_observer_reviewed",
                      card["prerequisites"])
        self.assertEqual(card["launch_options"]["GDB"], "on")

    def test_candidate191_dynamic_gdb_card_is_exact_and_preserves_gpu_source(self):
        self.tool.configure("1.0.191", "metal-025")
        raw = (ROOT / "experiments/metal-025.json").read_bytes()
        card = self.tool.validate_card(raw, hashlib.sha256(raw).hexdigest())
        self.assertEqual(card["raphael_source_sha256"],
                         "7515f121230fbd26e32b198bd622e106155708e4108d9def96dcc7daa9d173f3")
        self.assertEqual(card["launch_options"]["GDB"], "on")
        self.assertNotIn("required_kernel_slide", card)
        self.assertIn("strict unchanged 45-second native Metal probe",
                      card["behavior_change"])
        self.assertIn("primary functional test", card["question"])
        gdb_observations = {item for item in
                            card["conditional_diagnostic_observations"]
                            if item.startswith("gdb_")}
        self.assertEqual(len(gdb_observations), 4)
        self.assertFalse(any(item.startswith("gdb_") for item in
                             card["required_observations"]))

    def test_candidate192_reports_actual_client_vmid_conditionally(self):
        self.tool.configure("1.0.192", "metal-026")
        raw = (ROOT / "experiments/metal-026.json").read_bytes()
        card = self.tool.validate_card(raw, hashlib.sha256(raw).hexdigest())
        self.assertEqual(card["raphael_source_sha256"],
                         "e2eb4769e41af10dcbb48f315446030fdd8af0632fa5f6de8ec8f9abba630526")
        old = dict(card, raphael_source_sha256=
                   "7515f121230fbd26e32b198bd622e106155708e4108d9def96dcc7daa9d173f3")
        encoded = (json.dumps(old) + "\n").encode()
        with self.assertRaisesRegex(RuntimeError, "candidate card contract"):
            self.tool.validate_card(encoded, hashlib.sha256(encoded).hexdigest())
        self.assertEqual(card["launch_options"], {
            "BOOTDISK_MODE": "custom", "NVRAM": "stock",
            "GENERIC_GRAPHICS": "off", "GDB": "on"})
        self.assertEqual(card["conditional_diagnostic_observations"], [
            "vmid1_fault_walk", "vmid1_fault_walk_view", "vmid1_fault_walk_entry",
            "client_fault_walk", "client_fault_walk_view", "client_fault_walk_entry",
            "gdb_vmid1_wrap_vmm_prepare_original_info",
            "gdb_vmid1_wrap_vmm_prepare_native_info", "gdb_vmid1_prepared_root",
            "gdb_hub0_vmid1_reprogram1"])
        self.assertFalse(any(item.startswith("gdb_") for item in
                             card["required_observations"]))
        self.assertIn("worker-time state is not fault-time proof",
                      card["behavior_change"])

    def test_candidate193_requires_mode5_a1_observations_and_source(self):
        self.tool.configure("1.0.193", "metal-027")
        raw = (ROOT / "experiments/metal-027.json").read_bytes()
        card = self.tool.validate_card(raw, hashlib.sha256(raw).hexdigest())
        self.assertEqual(card["functional_boot_arguments"],
                         {"rgpuvmroot": "5", "rgpudump": "5000"})
        self.assertEqual(card["raphael_source_sha256"],
                         "73bbfdcefa406e38d4206e1870b6dcaf96a0f8555f0795e48d83055220157e5e")
        self.assertIn("map_process_route", card["required_observations"])
        self.assertIn("map_process_root", card["required_observations"])
        self.assertIn("map_process_summary", card["conditional_diagnostic_observations"])
        self.assertEqual(card["launch_options"]["GDB"], "on")
        self.assertIn("not fault-time proof", card["behavior_change"])

    def test_candidate194_uses_same_mode5_observation_contract(self):
        self.tool.configure("1.0.194", "metal-028")
        raw = (ROOT / "experiments/metal-028.json").read_bytes()
        card = self.tool.validate_card(raw, hashlib.sha256(raw).hexdigest())
        self.assertEqual(card["candidate_version"], "1.0.194")
        self.assertEqual(card["raphael_source_sha256"],
                         "c798dfd66c14c5d14160141586062ea5624f5314d14604f9d12abb40945e202d")
        self.assertEqual(card["functional_boot_arguments"]["rgpuvmroot"], "5")
        self.assertNotIn("map_process_route", card["required_observations"])
        self.assertIn("map_process_root", card["required_observations"])
        self.assertIn("map_process_summary", card["conditional_diagnostic_observations"])
        self.assertIn("additional_launches=0", card["repeat_policy"])

    def test_candidate188_debug_symbols_require_retained_files_and_matching_provenance(self):
        self.tool.configure("1.0.188", "metal-021")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            debug_dir = root / "debug-symbols"
            dsym = debug_dir / "RaphaelGPU.dSYM/Contents/Resources/DWARF"
            dsym.mkdir(parents=True)
            source = debug_dir / "source"
            shutil.copytree(ROOT / "src", source)
            build_id = "build-identity-test"
            (source / "BuildIdentity.hpp").write_text(
                '#define RGPU_BUILD_ID "' + build_id + '"\n')
            (source / "rlc_fw.h").write_bytes(gzip.decompress(
                (ROOT / "build-support/rlc_fw.h.gz").read_bytes()))
            def digest(path, excluded=()):
                result = hashlib.sha256()
                for item in sorted(path.rglob('*')):
                    if item.is_file() and item.name not in excluded:
                        result.update(item.relative_to(path).as_posix().encode() + b'\0' +
                                     hashlib.sha256(item.read_bytes()).digest())
                return result.hexdigest()
            tracked_source = digest(source, ("BuildIdentity.hpp", "rlc_fw.h"))
            executable = root / "RaphaelGPU"
            executable.write_bytes(b"debug executable")
            dwarf = dsym / "RaphaelGPU"
            dwarf.write_bytes(b"debug dwarf")
            script = debug_dir / "build-kext-debug.sh"
            canonical_script = ROOT / "tools/build-kext.sh"
            script.write_bytes(canonical_script.read_bytes().replace(
                b"-mkernel -O2\n", b"-mkernel -O2 -g -gdwarf-4\n"))
            canonical = {"build_script_sha256": hashlib.sha256(canonical_script.read_bytes()).hexdigest(),
                         "tracked_source_sha256": tracked_source,
                         "inputs_sha256": hashlib.sha256((ROOT / "build-support/inputs.json").read_bytes()).hexdigest()}
            debug = {
                "schema": 1, "flags": ["-O2", "-g", "-gdwarf-4"],
                "private_build_script_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
                "canonical_inputs_before": canonical,
                "canonical_inputs_after": canonical,
                "executable_uuid": "c" * 32, "dsym_uuid": "c" * 32,
                "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
                "dsym_dwarf_sha256": hashlib.sha256(dwarf.read_bytes()).hexdigest(),
                "debug_source_sha256": digest(source),
            }
            manifest = {"debug_symbols": debug, "build_id": build_id}
            (debug_dir / "debug-manifest.json").write_text(json.dumps(debug))
            builder = mock.Mock()
            builder.verify_debug_uuids.return_value = "c" * 32
            builder.tree_digest.side_effect = digest
            builder.debug_build_script.side_effect = lambda data: data.replace(
                b"-mkernel -O2\n", b"-mkernel -O2 -g -gdwarf-4\n")
            accepted = self.tool.validate_debug_symbols(
                manifest, builder, executable, debug_dir, canonical["tracked_source_sha256"])
            self.assertEqual(accepted, debug)
            for mutation, message in (
                    ({"flags": ["-O0", "-g", "-gdwarf-4"]}, "flags mismatch"),
                    ({"dsym_dwarf_sha256": "0" * 64}, "debug DWARF changed"),
                    ({"canonical_inputs_after": dict(canonical, inputs_sha256="0" * 64)},
                     "canonical debug inputs changed")):
                bad = dict(debug, **mutation)
                manifest["debug_symbols"] = bad
                (debug_dir / "debug-manifest.json").write_text(json.dumps(bad))
                with self.subTest(message=message), self.assertRaisesRegex(RuntimeError, message):
                    self.tool.validate_debug_symbols(
                        manifest, builder, executable, debug_dir,
                        canonical["tracked_source_sha256"])

    def test_stage_wires_validated_card_source_pin_into_build_verification(self):
        source = TOOL.read_text()
        call = source[source.index("identities, manifest, archive = verify_build_inputs("):]
        call = call[:call.index("\n    candidate186")]
        self.assertIn("image_id, card.get(\"raphael_source_sha256\")", call)
        self.assertIn("card_source_sha256", source[source.index("def verify_build_inputs"):source.index("def active_or_pending_vm")])

    def test_lilu_bundle_refuses_wrong_executable_or_info_bytes(self):
        durable = Path("/home/bogdan/macos-vm/run/headless-lilu-verified-53b5a19812e6")
        bundle = durable / "Lilu.kext"
        manifest = durable / "build-manifest.json"
        expected = self.tool.validate_lilu_inputs(
            bundle,
            "53b5a19812e66eeea3d3b874fe642f441cbfeccd171fb5ba05dc2e0ced3b8887",
            "6714fee51444238c0540814729767485572441435bcf36a158571cf78317a669",
            "e5d2554d29658699dd9535a9b8dd38ca9aae5aa5a12f65508b083d3c519cf378")
        self.assertEqual(expected["lilu_bundle"], str(bundle.resolve()))
        self.assertEqual(expected["lilu_build_manifest"], str(manifest.resolve()))
        for key in ("lilu_executable_sha256", "lilu_info_sha256"):
            kwargs = {
                "lilu_executable_sha256": expected["lilu_executable_sha256"],
                "lilu_info_sha256": expected["lilu_info_sha256"],
            }
            kwargs[key] = "0" * 64
            with self.subTest(key=key), self.assertRaisesRegex(RuntimeError, "Lilu .* changed"):
                self.tool.validate_lilu_inputs(
                    bundle, kwargs["lilu_executable_sha256"],
                    kwargs["lilu_info_sha256"], expected["lilu_build_manifest_sha256"])

    def test_wrong_lilu_or_config_readback_does_not_replace_private_image(self):
        expected = {
            "binary_sha256": "1" * 64, "info_sha256": "2" * 64,
            "config_sha256": "3" * 64, "lilu_executable_sha256": "4" * 64,
            "lilu_info_sha256": "5" * 64,
        }
        experiment = type("Experiment", (), {"validate_identity": staticmethod(
            lambda wanted, seen: [key for key, value in wanted.items()
                                  if seen.get(key) != value])})()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "private.raw"
            image.write_bytes(b"original-private-image")
            bundle = root / "Lilu.kext"
            (bundle / "Contents/MacOS").mkdir(parents=True)
            (bundle / "Contents/MacOS/Lilu").write_bytes(b"lilu")
            (bundle / "Contents/Info.plist").write_bytes(b"info")
            for key in ("lilu_executable_sha256", "config_sha256"):
                with self.subTest(key=key):
                    observed = dict(expected, **{key: "f" * 64})
                    with mock.patch.object(self.tool.subprocess, "run"), \
                            mock.patch.object(self.tool, "candidate_image_files",
                                              return_value=observed), \
                            self.assertRaisesRegex(RuntimeError, "ESP readback mismatch"):
                        self.tool.stage_lilu_image(
                            experiment, image, bundle, expected)
                    self.assertEqual(image.read_bytes(), b"original-private-image")
                    self.assertEqual(list(root.glob("private.raw.backup-*")), [])

    def test_candidate185_card_and_absent_flags_remain_historical(self):
        self.tool.configure("1.0.185", "metal-018")
        raw = (ROOT / "experiments/metal-018.json").read_bytes()
        historical = self.tool.validate_card(raw, hashlib.sha256(raw).hexdigest())
        self.assertEqual(self.tool.candidate_boot_flags(historical), [])
        self.assertEqual(historical["functional_boot_arguments"], {"rgpuvmroot": "4"})


class Candidate188ResealTests(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool()

    def config(self, run_id):
        lo, hi = self.tool.struct.unpack("<QQ", bytes.fromhex(run_id))
        return {"NVRAM":{"Add":{self.tool.load_module(
            "experiment_fixture", ROOT/"tools/experiment.py").BOOT_GUID:{
                "boot-args":f"keep=1 rgpurnlo=0x{lo:x} rgpurnhi=0x{hi:x}"}}},
                "Misc":{"Boot":{"Timeout":5}}}

    def test_reseal_accepts_only_the_two_fresh_nonce_values(self):
        old = "cb1d0aadd8186205d867a23fe175c336"
        new = "c04e68a9874ba382fd61facb1ad73b61"
        self.tool.validate_nonce_only_reseal(self.config(old), self.config(new), old, new)
        changed = self.config(new); changed["Misc"]["Boot"]["Timeout"] = 6
        with self.assertRaisesRegex(RuntimeError, "nonce-only"):
            self.tool.validate_nonce_only_reseal(self.config(old), changed, old, new)

    def test_reseal_nonce_comparison_accepts_binary_plist_fields(self):
        old = "cb1d0aadd8186205d867a23fe175c336"
        new = "c04e68a9874ba382fd61facb1ad73b61"
        original = self.config(old)
        replacement = self.config(new)
        original["DeviceProperties"] = {"Add": {"PciRoot(0x0)": {
            "ATY,bin_image": b"\x00\xff", "model": b"Raphael\x00"}}}
        replacement["DeviceProperties"] = copy.deepcopy(
            original["DeviceProperties"])
        encoded = plistlib.dumps(original)
        self.assertEqual(plistlib.loads(encoded)["DeviceProperties"],
                         original["DeviceProperties"])
        self.tool.validate_nonce_only_reseal(
            plistlib.loads(encoded), replacement, old, new)

    def test_reseal_preimage_hash_mismatch_refuses_before_publication(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/"media"; path.write_bytes(b"original")
            self.tool.validate_reseal_preimages({"media":path},
                {"media":hashlib.sha256(b"original").hexdigest()})
            with self.assertRaisesRegex(RuntimeError, "preimage"):
                self.tool.validate_reseal_preimages({"media":path}, {"media":"0"*64})

    def test_reseal_rollback_restores_every_published_preimage(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); published = {}
            rows = []
            for name in ("raw", "boot", "config"):
                target=root/name; backup=root/(name+".backup")
                target.write_bytes(b"new"); backup.write_bytes(("old-"+name).encode())
                published[name] = True; rows.append((name,target,backup))
            self.tool.rollback_reseal(rows, published)
            for name,target,backup in rows:
                self.assertEqual(target.read_bytes(), ("old-"+name).encode())
                self.assertFalse(backup.exists())

    def prelaunch_fixture(self, root):
        old_run = "b4a41ca47553618a58bab320b3b0c2fb"
        boot_id = "f828eb26-9cb7-4fac-bff2-bc87515fa2ba"
        candidate = root/"run/candidate-194"
        failed = root/"run/metal-028-194"
        authorities = root/f"run/one-run-qualification-authorities/{boot_id}"
        ledger_path = root/f"run/used-gpu-boots/{boot_id}.json"
        for path in (candidate, failed, authorities, ledger_path.parent):
            path.mkdir(parents=True, exist_ok=True)
        staging = {
            "candidate_version":"1.0.194", "run_id":old_run,
            "source_commit":"5"*40, "source_sha256":"6"*64,
            "build_id":"7"*32, "executable_sha256":"8"*64,
            "info_manifest_sha256":"9"*64,
        }
        build_manifest = {
            "version":"1.0.194", "source_commit":"5"*40,
            "source_sha256":"6"*64, "build_id":"7"*32,
            "executable_sha256":"8"*64,
        }
        manifest = dict(staging, binary_sha256="8"*64, info_sha256="9"*64,
                        source_clean=True,
                        spec={"candidate_version":"1.0.194"})
        verdict = {
            "valid":False, "verdict":"INVALID",
            "termination_reason":"ValueError: admission refused: source_clean",
            "error":"ValueError: admission refused: source_clean",
            "warm_reuse":"not-attempted",
        }
        files = {
            "manifest.json":json.dumps(manifest).encode(),
            "verdict.json":json.dumps(verdict).encode(),
            "serial.txt":b"", "critical.txt":b"",
            "shutdown.json":b"null\n",
        }
        for name, raw in files.items():
            (failed/name).write_bytes(raw)
        build_raw = json.dumps(build_manifest).encode()
        (candidate/"build-manifest.json").write_bytes(build_raw)
        ledger = {"schema":2, "boot_id":boot_id, "max_launches":3,
                  "launches":[{"run_id":"a"*32}]}
        ledger_raw = json.dumps(ledger).encode()
        ledger_path.write_bytes(ledger_raw)
        policy = authorities/(old_run+".policy.json")
        activation = authorities/(old_run+".json")
        policy.write_bytes(b"policy")
        activation.write_bytes(b"activation")
        run_id_file = root/"run/candidate194-qualification-run-id.txt"
        run_id_file.write_text(old_run+"\n")
        profile = {
            "candidate_version":"1.0.194", "card_id":"metal-028",
            "prior_run_id":old_run,
            "build_manifest_sha256":hashlib.sha256(build_raw).hexdigest(),
            "prelaunch_refusal":{
                "boot_id":boot_id, "directory":"run/metal-028-194",
                "files":{name:hashlib.sha256(raw).hexdigest()
                         for name,raw in files.items()},
                "ledger":"run/used-gpu-boots/"+boot_id+".json",
                "ledger_sha256":hashlib.sha256(ledger_raw).hexdigest(),
                "policy":"run/one-run-qualification-authorities/"+boot_id+"/"+
                         old_run+".policy.json",
                "policy_sha256":hashlib.sha256(b"policy").hexdigest(),
                "activation":"run/one-run-qualification-authorities/"+boot_id+"/"+
                             old_run+".json",
                "activation_sha256":hashlib.sha256(b"activation").hexdigest(),
                "run_id_file":"run/candidate194-qualification-run-id.txt",
                "run_id_file_sha256":hashlib.sha256(
                    (old_run+"\n").encode()).hexdigest(),
            },
        }
        return staging, profile

    def test_candidate194_prelaunch_refusal_proves_no_launch_and_same_artifact(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            staging, profile = self.prelaunch_fixture(root)
            with mock.patch.object(self.tool, "VM", root), \
                 mock.patch.object(self.tool, "CANDIDATE", root/"run/candidate-194"):
                proof = self.tool.validate_prelaunch_refusal(profile, staging)
            self.assertEqual(proof["reason"], "source_clean")
            self.assertEqual(proof["prior_run_id"], staging["run_id"])
            self.assertFalse(proof["qemu_started"])
            self.assertFalse(proof["ledger_consumed"])
            self.assertEqual(proof["source_sha256"], staging["source_sha256"])
            self.assertEqual(proof["executable_sha256"],
                             staging["executable_sha256"])

    def test_candidate194_prelaunch_refusal_rejects_supervision_or_ledger_use(self):
        for mutation in ("supervision", "ledger"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                staging, profile = self.prelaunch_fixture(root)
                if mutation == "supervision":
                    (root/"run/metal-028-194/supervision.json").write_text("{}")
                else:
                    proof = profile["prelaunch_refusal"]
                    ledger_path = root/proof["ledger"]
                    ledger = json.loads(ledger_path.read_text())
                    ledger["launches"].append({"run_id":staging["run_id"]})
                    raw = json.dumps(ledger).encode()
                    ledger_path.write_bytes(raw)
                    proof["ledger_sha256"] = hashlib.sha256(raw).hexdigest()
                with mock.patch.object(self.tool, "VM", root), \
                     mock.patch.object(self.tool, "CANDIDATE", root/"run/candidate-194"), \
                     self.assertRaisesRegex(RuntimeError, "prelaunch refusal proof"):
                    self.tool.validate_prelaunch_refusal(profile, staging)

    def test_fresh_reseal_run_id_rejects_ledger_authority_or_record_collision(self):
        new_run = "c04e68a9874ba382fd61facb1ad73b61"
        prior_run = "b4a41ca47553618a58bab320b3b0c2fb"
        for collision in ("prior", "ledger", "policy", "activation", "record"):
            with self.subTest(collision=collision), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                boot = "f828eb26-9cb7-4fac-bff2-bc87515fa2ba"
                record = root/f"run/candidate-194-reseals/{new_run}.json"
                ledger_dir = root/"run/used-gpu-boots"
                authority = root/f"run/one-run-qualification-authorities/{boot}"
                ledger_dir.mkdir(parents=True)
                authority.mkdir(parents=True)
                candidate_run = prior_run if collision == "prior" else new_run
                launches = [{"run_id":candidate_run}] if collision == "ledger" else []
                (ledger_dir/"one.json").write_text(json.dumps({"launches":launches}))
                if collision == "policy":
                    (authority/(new_run+".policy.json")).write_text("{}")
                elif collision == "activation":
                    (authority/(new_run+".json")).write_text("{}")
                elif collision == "record":
                    record.parent.mkdir(parents=True)
                    record.write_text("{}")
                with mock.patch.object(self.tool, "VM", root), \
                     self.assertRaisesRegex(RuntimeError, "fresh run ID"):
                    self.tool.validate_fresh_reseal_run_id(
                        candidate_run, boot, record, prior_run)

    def test_reseal_profiles_preserve_188_and_select_exact_194_refusal(self):
        self.tool.configure("1.0.188", "metal-022")
        historical = self.tool.reseal_profile()
        self.assertEqual(historical["prior_run_id"],
                         "cb1d0aadd8186205d867a23fe175c336")
        self.assertIsNone(historical["prelaunch_refusal"])
        self.tool.configure("1.0.194", "metal-028")
        current = self.tool.reseal_profile()
        self.assertEqual(current["prior_run_id"],
                         "b4a41ca47553618a58bab320b3b0c2fb")
        self.assertEqual(current["prelaunch_refusal"]["ledger_sha256"],
                         "5677d5419592ccf3cead52f834de1f4c412934ea3eaa6c570ee1708f1a35fab2")
        self.tool.configure("1.0.193", "metal-027")
        with self.assertRaisesRegex(RuntimeError, "reseal requires"):
            self.tool.reseal_profile()

    def test_candidate194_reseal_pins_current_card_and_experiment_hashes(self):
        self.tool.configure("1.0.194", "metal-028")
        profile = self.tool.reseal_profile()
        self.assertTrue(profile["allow_cross_boot_reseal"])
        self.assertEqual(
            profile["card_sha256"],
            hashlib.sha256((ROOT / "experiments/metal-028.json").read_bytes()).hexdigest())
        self.assertEqual(
            profile["experiment_sha256"],
            hashlib.sha256(subprocess.check_output([
                "git", "-C", str(ROOT), "show",
                "3f47ab7eca52265a9f294200022213d354651e45:tools/experiment.py"])).hexdigest())

    def test_candidate194_reseal_pins_verified_preimages_and_prior_nonce(self):
        self.tool.configure("1.0.194", "metal-028")
        profile = self.tool.reseal_profile()
        self.assertEqual(profile["preimage_backup_token"],
                         "670e12c05ea14d5cb4936b2b5284d562")
        self.assertEqual(profile["raw_preimage_sha256"],
                         "e372943b5fdd780c7792b8c1915dcfdc655465528d19bbea00b0916e7361608f")
        self.assertEqual(profile["bootdisk_preimage_sha256"],
                         "7191d77d2d72edc78269a804ecbbed12310c13c6565fe2436e15dbec5ec2720f")
        self.assertEqual(profile["config_preimage_sha256"],
                         "6e1269eacd9277f3ac3a0e80cb35824046208371acf96bf8aabadf5b7702ca45")
        nonce = profile["preimage_nonce"]
        self.assertEqual(nonce["run_id"], profile["prior_run_id"])
        lo, hi = self.tool.struct.unpack("<QQ", bytes.fromhex(nonce["run_id"]))
        self.assertEqual(nonce["nonce_lo"], f"0x{lo:x}")
        self.assertEqual(nonce["nonce_hi"], f"0x{hi:x}")

    def test_candidate194_reseal_rejects_unreviewed_preimage_hash(self):
        self.tool.configure("1.0.194", "metal-028")
        profile = self.tool.reseal_profile()
        with self.assertRaisesRegex(RuntimeError, "raw preimage"):
            self.tool.validate_reseal_profile_preimages(
                profile, "0" * 64, profile["bootdisk_preimage_sha256"],
                profile["config_preimage_sha256"])

    def test_candidate194_cross_boot_reseal_requires_current_boot_identity(self):
        self.tool.configure("1.0.194", "metal-028")
        profile = self.tool.reseal_profile()
        historical = profile["prelaunch_refusal"]["boot_id"]
        with mock.patch.object(self.tool.Path, "read_text", return_value="fresh-boot\n"):
            self.tool.validate_reseal_boot_identity(profile, "fresh-boot")
            with self.assertRaisesRegex(RuntimeError, "current host boot"):
                self.tool.validate_reseal_boot_identity(profile, "other-boot")
        with self.assertRaisesRegex(RuntimeError, "fresh cross-boot"):
            self.tool.validate_reseal_boot_identity(profile, historical)

    def test_candidate194_fresh_reseal_authority_separates_historical_refusal(self):
        profile = {
            "allow_cross_boot_reseal": True,
            "prelaunch_refusal": {"boot_id": "historical-boot"},
        }
        refusal = {"reason": "source_clean", "qemu_started": False,
                   "ledger_consumed": False}
        authority = self.tool.reseal_authority(
            profile, "fresh-boot", "a" * 32, refusal)
        self.assertTrue(authority["authorizes_launch"])
        self.assertEqual(authority["authority_boot_id"], "fresh-boot")
        self.assertEqual(authority["authority_run_id"], "a" * 32)
        self.assertEqual(authority["historical_prelaunch_refusal"], refusal)
        self.assertNotEqual(authority["historical_prelaunch_refusal"],
                            authority.get("authority"))

    def test_candidate194_reseal_authority_rejects_historical_boot_or_stale_run(self):
        profile = {
            "allow_cross_boot_reseal": True,
            "prelaunch_refusal": {"boot_id": "historical-boot"},
        }
        refusal = {"reason": "source_clean"}
        for boot_id, run_id, expected in (
                ("historical-boot", "a" * 32, "cross-boot"),
                ("fresh-boot", "b" * 32, "fresh run ID")):
            with self.subTest(boot_id=boot_id, run_id=run_id):
                with self.assertRaisesRegex(RuntimeError, expected):
                    self.tool.reseal_authority(
                        profile, boot_id, run_id, refusal,
                        prior_run_id="b" * 32)

    def test_candidate194_reseal_refuses_bad_proof_before_media_work(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            candidate = root/"run/candidate-194"
            candidate.mkdir(parents=True)
            staging = {"candidate_version":"1.0.194", "run_id":"b"*32}
            staging_raw = json.dumps(staging).encode()
            (candidate/"staging.json").write_bytes(staging_raw)
            profile = {
                "candidate_version":"1.0.194", "card_id":"metal-028",
                "prior_run_id":"b"*32, "record_kind":"candidate194-nonce-reseal",
                "staging_sha256":hashlib.sha256(staging_raw).hexdigest(),
                "card_sha256":"c"*64, "build_manifest_sha256":"d"*64,
                "prelaunch_refusal":{"boot_id":"boot-A"},
            }
            image = "sha256:"+"e"*64
            commit = "f"*40
            def command(argv, timeout=30):
                if argv[:2] == ["git", "-C"] and argv[-2:] == ["rev-parse", "--show-toplevel"]:
                    return str(ROOT)
                if argv[:2] == ["git", "-C"] and argv[-2:] == ["rev-parse", "HEAD"]:
                    return commit
                if argv[:2] == ["git", "-C"] and argv[-2:] == ["status", "--porcelain"]:
                    return ""
                if argv[:3] == ["docker", "image", "inspect"]:
                    return image
                self.fail("unexpected command: "+repr(argv))
            experiment = mock.Mock()
            with mock.patch.object(self.tool, "VM", root), \
                 mock.patch.object(self.tool, "CANDIDATE", candidate), \
                 mock.patch.object(self.tool, "reseal_profile", return_value=profile), \
                 mock.patch.object(self.tool, "command", side_effect=command), \
                 mock.patch.object(self.tool, "validate_card", return_value={}), \
                 mock.patch.object(self.tool, "load_module", return_value=experiment), \
                 mock.patch.object(self.tool, "validate_prelaunch_refusal",
                                   side_effect=RuntimeError("bad prelaunch proof")), \
                 mock.patch.object(self.tool, "qconvert") as qconvert, \
                 self.assertRaisesRegex(RuntimeError, "bad prelaunch proof"):
                self.tool.reseal_candidate(
                    commit, "boot-A", "c"*64, "1"*32, image,
                    profile["staging_sha256"], "2"*64, "3"*64, "4"*64)
            qconvert.assert_not_called()
            experiment.stage_image.assert_not_called()


class WorktreeCleanCheckTests(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.worktree = Path(self.temp.name) / "candidate"
        self.worktree.mkdir()
        subprocess.run(["git", "init", "-q", str(self.worktree)], check=True)
        subprocess.run(["git", "-C", str(self.worktree), "config", "user.email", "test@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(self.worktree), "config", "user.name", "Test"], check=True)
        (self.worktree / "tracked.txt").write_text("original\n")
        subprocess.run(["git", "-C", str(self.worktree), "add", "tracked.txt"], check=True)
        subprocess.run(["git", "-C", str(self.worktree), "commit", "-q", "-m", "initial"], check=True)
        self.commit = subprocess.check_output(["git", "-C", str(self.worktree), "rev-parse", "HEAD"], text=True).strip()
        self.tool.ROOT = self.worktree
        self.tool.WT = self.worktree

    def check_rejected(self, mode):
        path = self.worktree / "tracked.txt"
        path.write_text("changed\n")
        subprocess.run(["git", "-C", str(self.worktree), "update-index", f"--{mode}", "tracked.txt"], check=True)
        with self.assertRaisesRegex(RuntimeError, "dirty|index flag"):
            self.tool.verify_worktree_before_import(self.commit)

    def test_rejects_assume_unchanged_modified_tracked_file(self):
        self.check_rejected("assume-unchanged")

    def test_rejects_skip_worktree_modified_tracked_file(self):
        self.check_rejected("skip-worktree")

    def test_rejects_modified_file_with_both_hidden_index_flags(self):
        path = self.worktree / "tracked.txt"
        path.write_text("changed\n")
        subprocess.run(["git", "-C", str(self.worktree), "update-index", "--assume-unchanged", "tracked.txt"], check=True)
        subprocess.run(["git", "-C", str(self.worktree), "update-index", "--skip-worktree", "tracked.txt"], check=True)
        with self.assertRaisesRegex(RuntimeError, "dirty|index flag"):
            self.tool.verify_worktree_before_import(self.commit)

    def test_rejects_ordinarily_modified_tracked_file(self):
        (self.worktree / "tracked.txt").write_text("changed\n")
        with self.assertRaisesRegex(RuntimeError, "dirty"):
            self.tool.verify_worktree_before_import(self.commit)

    def test_accepts_clean_tracked_worktree(self):
        self.tool.verify_worktree_before_import(self.commit)


class AttemptNamespaceTests(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool()

    def test_attempt_copy_preserves_build_and_excludes_staging_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / "run/candidate-203"
            base.mkdir(parents=True)
            (base / "build-manifest.json").write_text("manifest")
            (base / "staging.json").write_text("old")
            (base / "staged-config.plist").write_text("old")
            identity = {"schema": 1, "extracted_candidate": str(base), "source_sha256": "a" * 64}
            identity_path = root / "run/candidate-203-build-identities.json"
            identity_path.write_text(json.dumps(identity))
            old_identity = identity_path.read_bytes()
            self.tool.VM = root
            self.tool.configure("1.0.203", "metal-037", "retry1")
            self.tool.prepare_attempt_copy("retry1")
            self.assertEqual((self.tool.CANDIDATE / "build-manifest.json").read_text(), "manifest")
            self.assertFalse((self.tool.CANDIDATE / "staging.json").exists())
            copied = json.loads(self.tool.IDENTITIES.read_text())
            self.assertEqual(copied["extracted_candidate"], str(self.tool.CANDIDATE))
            self.assertEqual(copied["source_sha256"], identity["source_sha256"])
            self.assertEqual(identity_path.read_bytes(), old_identity)

    def test_attempt_copy_rejects_missing_identity_without_creating_namespace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); base = root / "run/candidate-203"
            base.mkdir(parents=True); (base / "build-manifest.json").write_text("{}")
            self.tool.VM = root; self.tool.configure("1.0.203", "metal-037", "retry1")
            with self.assertRaisesRegex(RuntimeError, "identity record"):
                self.tool.prepare_attempt_copy("retry1")
            self.assertFalse(self.tool.CANDIDATE.exists())


    def test_candidate207_probe_flag_is_three_and_older_restore_flags_remain(self):
        for name, version, expected in (("metal-039", "205", "1"),
                                        ("metal-040", "206", "2"),
                                        ("metal-041", "207", "3"),
                                        ("metal-042", "208", "3"),
                                        ("metal-043", "209", "3")):
            self.tool.configure("1.0." + version, name)
            raw = (ROOT / ("experiments/" + name + ".json")).read_bytes()
            card = self.tool.validate_card(raw, hashlib.sha256(raw).hexdigest())
            self.assertEqual(card["functional_boot_arguments"]["rgpumqdrestore"], expected)

    def test_candidate205_restore_flag_is_required_by_card_contract(self):
        self.tool.configure("1.0.205", "metal-039")
        raw = (ROOT / "experiments/metal-039.json").read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        accepted = self.tool.validate_card(raw, digest)
        self.assertEqual(accepted["functional_boot_arguments"]["rgpumqdrestore"], "1")
        card = json.loads(raw)
        card["functional_boot_arguments"].pop("rgpumqdrestore")
        bad = (json.dumps(card, sort_keys=True) + "\n").encode()
        with self.assertRaisesRegex(RuntimeError, "card contract"):
            self.tool.validate_card(bad, hashlib.sha256(bad).hexdigest())


if __name__ == "__main__":
    unittest.main()

class Candidate280ContractTest(unittest.TestCase):
    def test_exact_card_and_version_boundary(self):
        tool = load_tool()
        tool.configure("1.0.280", "metal-127")
        raw = (ROOT / "experiments/metal-127.json").read_bytes()
        card = tool.validate_card(raw, hashlib.sha256(raw).hexdigest())
        self.assertEqual(card["candidate_version"], "1.0.280")
        with self.assertRaises(RuntimeError):
            tool.configure("1.0.281", "metal-128")

    def test_closure_pair_preserves_exact_functional_guards(self):
        tool = load_tool()
        tool.configure("1.0.280", "metal-128")
        raw = (ROOT / "experiments/metal-128.json").read_bytes()
        card = tool.validate_card(raw, hashlib.sha256(raw).hexdigest())
        self.assertEqual(card["lifecycle_test"], "supervised-qemu-quit")
        baseline = json.loads((ROOT / "experiments/metal-127.json").read_bytes())
        self.assertEqual(card["functional_boot_arguments"], baseline["functional_boot_arguments"])
        for mutation in ("action", "boot_argument"):
            altered = json.loads(raw)
            if mutation == "action":
                altered["lifecycle_test"] = "unreviewed-action"
            else:
                altered["functional_boot_arguments"]["rgputexdiag"] = "0"
            encoded = json.dumps(altered).encode()
            with self.assertRaises(RuntimeError):
                tool.validate_card(encoded, hashlib.sha256(encoded).hexdigest())
        tool.configure("1.0.280", "metal-129")
        altered = json.loads(raw); altered["id"] = "metal-129"
        encoded = json.dumps(altered).encode()
        with self.assertRaisesRegex(RuntimeError, "unsupported candidate card pair"):
            tool.validate_card(encoded, hashlib.sha256(encoded).hexdigest())
