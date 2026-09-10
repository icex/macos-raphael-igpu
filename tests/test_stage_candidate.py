import hashlib
import importlib.util
import json
from pathlib import Path
import re
import unittest


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

    def test_staging_defaults_select_candidate184(self):
        tool = load_tool()
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

    def test_staging_metadata_preserves_new_launch_contract(self):
        source = TOOL.read_text()
        self.assertIn('staging["launch_options"] = card["launch_options"]', source)


if __name__ == "__main__":
    unittest.main()
