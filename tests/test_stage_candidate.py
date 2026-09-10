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


if __name__ == "__main__":
    unittest.main()
