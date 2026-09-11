"""Offline contract tests for the bounded Aqua virtual-display phase."""

import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import re
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "tools" / "desktop-display.py"
SOURCE = ROOT / "tests" / "desktop_display.m"


def load_tool():
    spec = importlib.util.spec_from_file_location("desktop_display", MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DesktopDisplayTests(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.tool = load_tool()
        self.nonce = "0123456789abcdef0123456789abcdef"
        self.source = b"objective-c source\n"
        self.source_sha = hashlib.sha256(self.source).hexdigest()
        self.binary_sha = "b" * 64
        self.guest_binary = (f"/var/tmp/rgpu-desktop-display-v2-{self.source_sha[:16]}"
                             "/desktop-display")

    def runtime_command(self, **overrides):
        values = dict(
            nonce=self.nonce,
            expiry=2_000_000_060,
            hold_seconds=15,
            guest_binary=self.guest_binary,
            source_sha256=self.source_sha,
            binary_sha256=self.binary_sha,
            registry_id=0x1000002ED,
        )
        values.update(overrides)
        return self.tool.guest_command(**values)

    def receipt(self, **overrides):
        result = {
            "schema": 1,
            "nonce": self.nonce,
            "execution_mode": "production",
            "source_sha256": self.source_sha,
            "binary_sha256": self.binary_sha,
            "guest_binary": self.guest_binary,
            "expiry_epoch": 2_000_000_060,
            "started_epoch": 2_000_000_001,
            "finished_epoch": 2_000_000_018,
            "hold_seconds": 15,
            "aqua": {
                "ready": True,
                "console_user": "bogdan",
                "console_uid": 501,
                "session_user": "bogdan",
                "session_uid": 501,
                "login_done": True,
                "on_console": True,
                "launch_domain": "gui/501",
                "launch_domain_environment": True,
                "launchd_job_pid": 701,
            },
            "display": {
                "baseline_ids": [11, 22],
                "created": True,
                "display_id": 33,
                "new_ids": [33],
                "settings_applied": True,
                "added": True,
                "active": True,
                "width": 1280,
                "height": 720,
                "refresh": 60.0,
                "removed": True,
                "final_ids": [11, 22],
                "cleanup_complete": True,
                "termination_signal": 0,
            },
            "stimulus": {
                "registry_id": 0x1000002ED,
                "device_name": "AMD Radeon Navi23",
                "window_visible": True,
                "window_display_id": 33,
                "drawables_acquired": 120,
                "command_buffers_submitted": 120,
                "command_buffers_completed": 120,
                "presented_frames": 120,
                "first_frame": 0,
                "last_frame": 119,
                "distinct_color_tokens": 8,
                "first_color_token": "#ff0000",
                "last_color_token": "#00ffff",
                "classification": "selected_metal_device",
            },
            "remote_observation": {
                "required": True,
                "observed": False,
                "frame_change_observed": False,
                "evidence": "external_capture_required",
            },
        }
        for key, value in overrides.items():
            if "." in key:
                group, field = key.split(".", 1)
                result[group][field] = value
            else:
                result[key] = value
        return result

    def output(self, receipt=None, exit_status=0):
        receipt = self.receipt() if receipt is None else receipt
        return ("RGPU_DESKTOP_RESULT " + json.dumps(receipt, separators=(",", ":")) +
                f"\nRGPU_EXIT {self.nonce} {exit_status}\n")

    def expected(self):
        return {
            "source_sha256": self.source_sha,
            "binary_sha256": self.binary_sha,
            "guest_binary": self.guest_binary,
            "registry_id": 0x1000002ED,
            "expiry_epoch": 2_000_000_060,
            "hold_seconds": 15,
        }

    def test_prepare_command_compiles_once_and_reports_pinned_source_and_binary(self):
        command = self.tool.prepare_guest_command(self.nonce, self.source, 2_000_000_060)
        self.assertIn("/usr/bin/xcrun clang", command)
        self.assertIn(self.source_sha, command)
        self.assertIn("RGPU_DESKTOP_PREPARE", command)
        self.assertIn("shasum -a 256", command)
        self.assertIn("/usr/bin/codesign --force --sign - --timestamp=none", command)
        self.assertIn("/usr/bin/codesign --verify --strict", command)
        self.assertLess(command.index("xcrun clang"), command.index("codesign --force"))
        self.assertLess(command.index("codesign --verify"), command.index("binary_sha="))
        self.assertNotIn("desktop-display 15", command)
        self.assertLess(command.index("curl -fsS"), command.index("/bin/mkdir"))
        self.assertLess(command.index("/bin/date +%s"), command.index("/bin/mkdir"))
        self.assertIn('test ! -L "$dir"', command)
        self.assertIn('stat -f %u "$dir"', command)

    def test_runtime_uses_exact_prepared_binary_in_dynamic_console_gui_domain(self):
        command = self.runtime_command()
        self.assertNotIn("xcrun", command)
        self.assertNotIn("objective-c source", command)
        self.assertIn(self.binary_sha, command)
        self.assertIn("/usr/bin/codesign --verify --strict", command)
        self.assertIn("stat -f %Su /dev/console", command)
        self.assertIn("test \"$uid\" -ge 500", command)
        self.assertIn("launchctl print \"gui/$uid\"", command)
        self.assertIn("launchctl bootstrap \"gui/$uid\"", command)
        self.assertIn("launchctl bootout \"gui/$uid", command)
        self.assertIn("launchctl kill TERM \"gui/$uid/", command)
        self.assertIn(self.guest_binary, command)
        encoded = re.search(r"/usr/bin/printf %s ([A-Za-z0-9+/=]+) \| "
                            r"/usr/bin/base64 -D", command).group(1)
        plist = base64.b64decode(encoded).decode()
        self.assertIn("<string>4294968045</string>", plist)
        self.assertIn("<string>gui/__RGPU_UID__</string>", plist)
        self.assertIn('sed -i \'\' "s/__RGPU_UID__/$uid/g"', command)

    def test_commands_reject_unbounded_or_unsafe_inputs(self):
        bad_calls = (
            lambda: self.runtime_command(nonce="not-a-nonce"),
            lambda: self.runtime_command(hold_seconds=0),
            lambda: self.runtime_command(hold_seconds=31),
            lambda: self.runtime_command(expiry=True),
            lambda: self.runtime_command(binary_sha256="bad"),
            lambda: self.runtime_command(guest_binary="relative/path"),
            lambda: self.runtime_command(guest_binary="/var/tmp/x;touch /tmp/pwn"),
            lambda: self.runtime_command(registry_id=0),
            lambda: self.tool.prepare_guest_command(self.nonce, "not bytes", 123),
        )
        for call in bad_calls:
            with self.subTest(call=call), self.assertRaises(ValueError):
                call()

    def test_gpuless_qualification_is_a_separate_same_binary_command(self):
        command = self.tool.qualification_guest_command(
            self.nonce, 2_000_000_060, 15, guest_binary=self.guest_binary,
            source_sha256=self.source_sha, binary_sha256=self.binary_sha)
        self.assertNotIn("xcrun", command)
        encoded = re.search(r"/usr/bin/printf %s ([A-Za-z0-9+/=]+) \| "
                            r"/usr/bin/base64 -D", command).group(1)
        plist = base64.b64decode(encoded).decode()
        self.assertIn("<string>gpuless-qualification</string>", plist)
        self.assertIn("<string>0</string>", plist)

    def test_gpuless_receipt_proves_only_session_and_display_lifecycle(self):
        receipt = self.receipt(execution_mode="gpuless-qualification")
        receipt["stimulus"].update({
            "registry_id": 0, "device_name": "", "drawables_acquired": 0,
            "command_buffers_submitted": 0, "command_buffers_completed": 0,
            "presented_frames": 0,
            "first_frame": 0, "last_frame": 0, "distinct_color_tokens": 0,
            "first_color_token": "", "last_color_token": "",
            "classification": "non_gpu_qualification",
        })
        receipt["remote_observation"].update({
            "required": False, "evidence": "not_requested_gpuless_qualification",
        })
        result = self.tool.validate_qualification_output(
            self.output(receipt), self.nonce, {
                "source_sha256": self.source_sha,
                "binary_sha256": self.binary_sha,
                "guest_binary": self.guest_binary,
                "expiry_epoch": 2_000_000_060,
                "hold_seconds": 15,
            })
        self.assertEqual(result["stimulus"]["classification"],
                         "non_gpu_qualification")
        with self.assertRaises(ValueError):
            self.tool.validate_output(self.output(receipt), self.nonce, self.expected())

    def test_prepare_validator_requires_exact_hashes_and_successful_exit(self):
        record = {
            "schema": 1,
            "nonce": self.nonce,
            "source_sha256": self.source_sha,
            "binary_sha256": self.binary_sha,
            "guest_binary": self.guest_binary,
            "compiled": True,
        }
        output = ("RGPU_DESKTOP_PREPARE " + json.dumps(record) +
                  f"\nRGPU_EXIT {self.nonce} 0\n")
        self.assertEqual(
            self.tool.validate_prepare_output(output, self.nonce, self.source_sha), record)
        for mutation in ("duplicate", "source", "binary", "exit"):
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                if mutation == "duplicate":
                    self.tool.validate_prepare_output(output + output, self.nonce, self.source_sha)
                elif mutation == "exit":
                    self.tool.validate_prepare_output(output.replace(" 0\n", " 1\n"),
                                                      self.nonce, self.source_sha)
                else:
                    bad = dict(record)
                    bad["source_sha256" if mutation == "source" else "binary_sha256"] = "x"
                    self.tool.validate_prepare_output(
                        "RGPU_DESKTOP_PREPARE " + json.dumps(bad) +
                        f"\nRGPU_EXIT {self.nonce} 0\n", self.nonce, self.source_sha)

    def test_finalize_card_fills_only_null_identity_from_current_source_receipt(self):
        current_source_sha = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
        guest_binary = (f"/var/tmp/rgpu-desktop-display-v2-{current_source_sha[:16]}"
                        "/desktop-display")
        template = {"name": "metal-029", "desktop_phase": {
            "schema": 1, "hold_seconds": 15, "cleanup_reserve_seconds": 25,
            "source_sha256": None, "binary_sha256": None, "guest_binary": None,
            "require_remote_frame_change": True,
        }}
        prepare = {
            "schema": 1, "nonce": self.nonce, "source_sha256": current_source_sha,
            "binary_sha256": self.binary_sha, "guest_binary": guest_binary,
            "compiled": True,
        }
        finalized = self.tool.finalize_card(template, prepare)
        self.assertIsNone(template["desktop_phase"]["source_sha256"])
        self.assertEqual(finalized["desktop_phase"]["source_sha256"], current_source_sha)
        self.assertEqual(finalized["desktop_phase"]["binary_sha256"], self.binary_sha)
        self.assertEqual(finalized["desktop_phase"]["guest_binary"], guest_binary)

        for mutation in ("prefilled", "wrong-source", "wrong-path", "not-compiled"):
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                bad_template = json.loads(json.dumps(template))
                bad_prepare = dict(prepare)
                if mutation == "prefilled":
                    bad_template["desktop_phase"]["binary_sha256"] = self.binary_sha
                elif mutation == "wrong-source":
                    bad_prepare["source_sha256"] = "a" * 64
                elif mutation == "wrong-path":
                    bad_prepare["guest_binary"] = self.guest_binary
                else:
                    bad_prepare["compiled"] = False
                self.tool.finalize_card(bad_template, bad_prepare)

    def test_validator_accepts_aqua_display_stimulus_and_normal_cleanup(self):
        result = self.tool.validate_output(self.output(), self.nonce, self.expected())
        self.assertTrue(result["aqua"]["ready"])
        self.assertEqual(result["display"]["new_ids"], [33])
        self.assertEqual(result["display"]["final_ids"], [11, 22])
        self.assertFalse(result["remote_observation"]["observed"])

    def test_validator_accepts_graceful_signal_only_after_owned_display_removal(self):
        receipt = self.receipt(**{"display.termination_signal": 15})
        result = self.tool.validate_output(self.output(receipt), self.nonce, self.expected())
        self.assertEqual(result["display"]["termination_signal"], 15)
        receipt["display"]["removed"] = False
        with self.assertRaisesRegex(ValueError, "display lifecycle"):
            self.tool.validate_output(self.output(receipt), self.nonce, self.expected())

    def test_validator_rejects_false_aqua_or_root_asuser_claims(self):
        cases = {
            "aqua.ready": False,
            "aqua.console_uid": 0,
            "aqua.session_uid": 502,
            "aqua.login_done": False,
            "aqua.on_console": False,
            "aqua.launch_domain": "user/501",
            "aqua.launch_domain_environment": False,
            "aqua.launchd_job_pid": 0,
        }
        for field, value in cases.items():
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "Aqua"):
                self.tool.validate_output(
                    self.output(self.receipt(**{field: value})), self.nonce, self.expected())

    def test_validator_requires_exactly_one_owned_new_display_and_baseline_restoration(self):
        cases = {
            "display.new_ids": [],
            "display.display_id": 22,
            "display.final_ids": [11],
            "display.cleanup_complete": False,
            "display.active": False,
            "display.width": 1024,
        }
        for field, value in cases.items():
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "display lifecycle"):
                self.tool.validate_output(
                    self.output(self.receipt(**{field: value})), self.nonce, self.expected())

    def test_validator_requires_presented_changing_metal_drawables_on_selected_registry(self):
        cases = {
            "stimulus.registry_id": 123,
            "stimulus.device_name": "Apple Software Renderer",
            "stimulus.window_visible": False,
            "stimulus.window_display_id": 22,
            "stimulus.drawables_acquired": 0,
            "stimulus.command_buffers_submitted": 0,
            "stimulus.command_buffers_completed": 0,
            "stimulus.presented_frames": 0,
            "stimulus.last_frame": 0,
            "stimulus.distinct_color_tokens": 1,
            "stimulus.last_color_token": "#ff0000",
            "stimulus.classification": "non_gpu_qualification",
        }
        for field, value in cases.items():
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "stimulus"):
                self.tool.validate_output(
                    self.output(self.receipt(**{field: value})), self.nonce, self.expected())

    def test_validator_does_not_promote_local_counters_to_remote_frame_evidence(self):
        for changes in (
            {"remote_observation.observed": True},
            {"remote_observation.frame_change_observed": True},
            {"remote_observation.required": False},
            {"remote_observation.evidence": "presented_frames"},
        ):
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, "remote"):
                self.tool.validate_output(
                    self.output(self.receipt(**changes)), self.nonce, self.expected())

    def test_validator_rejects_expired_mismatched_or_duplicate_receipts(self):
        cases = [
            self.output(self.receipt(expiry_epoch=2_000_000_061)),
            self.output(self.receipt(finished_epoch=2_000_000_061)),
            self.output(exit_status=1),
            self.output() + self.output(),
            "RGPU_DESKTOP_RESULT {",
        ]
        for output in cases:
            with self.subTest(output=output), self.assertRaises(ValueError):
                self.tool.validate_output(output, self.nonce, self.expected())

        with self.assertRaises(ValueError):
            self.tool.validate_output(
                self.output(self.receipt(execution_mode="gpuless-qualification")),
                self.nonce, self.expected())

    def test_run_prepared_refuses_to_consume_cleanup_reserve(self):
        manifest = {"desktop_phase": {
            "schema": 1,
            "hold_seconds": 15,
            "cleanup_reserve_seconds": 25,
            "source_sha256": self.source_sha,
            "binary_sha256": self.binary_sha,
            "guest_binary": self.guest_binary,
            "require_remote_frame_change": True,
        }}
        called = []
        with self.assertRaisesRegex(ValueError, "cleanup reserve"):
            self.tool.run_prepared(
                Path("/vm"), manifest, 1040, 0x1000002ED,
                now=lambda: 1000, runner=lambda *a, **k: called.append((a, k)))
        self.assertEqual(called, [])

        with self.assertRaisesRegex(ValueError, "cleanup reserve"):
            self.tool.run_prepared(
                Path("/vm"), manifest, 1048.5, 0x1000002ED,
                now=lambda: 1000.5, runner=lambda *a, **k: called.append((a, k)))
        self.assertEqual(called, [])

    def test_run_prepared_executes_only_pinned_runtime_and_validates_receipt(self):
        manifest = {"desktop_phase": {
            "schema": 1,
            "hold_seconds": 15,
            "cleanup_reserve_seconds": 25,
            "source_sha256": self.source_sha,
            "binary_sha256": self.binary_sha,
            "guest_binary": self.guest_binary,
            "require_remote_frame_change": True,
        }}
        calls = []

        def runner(vm, command, nonce, env, timeout, execution_grace):
            calls.append((vm, command, nonce, env, timeout, execution_grace))
            receipt = self.receipt(nonce=nonce, expiry_epoch=1060,
                                   started_epoch=1001, finished_epoch=1018)
            return SimpleNamespace(
                returncode=0,
                stdout=("RGPU_DESKTOP_RESULT " + json.dumps(receipt) +
                        f"\nRGPU_EXIT {nonce} 0\n"))

        result = self.tool.run_prepared(
            Path("/vm"), manifest, 1085, 0x1000002ED,
            now=lambda: 1000, runner=runner, nonce_factory=lambda: self.nonce)
        self.assertEqual(result["display"]["display_id"], 33)
        self.assertEqual(len(calls), 1)
        self.assertNotIn("xcrun", calls[0][1])
        self.assertEqual(calls[0][4], 38)
        self.assertEqual(calls[0][5], 0)

    def test_run_prepared_clamps_transport_to_absolute_phase_expiry(self):
        manifest = {"desktop_phase": {
            "schema": 1, "hold_seconds": 15, "cleanup_reserve_seconds": 25,
            "source_sha256": self.source_sha, "binary_sha256": self.binary_sha,
            "guest_binary": self.guest_binary, "require_remote_frame_change": True,
        }}
        calls = []

        def runner(vm, command, nonce, env, timeout, execution_grace):
            calls.append((env, timeout, execution_grace))
            receipt = self.receipt(nonce=nonce, expiry_epoch=1024,
                                   started_epoch=1001, finished_epoch=1020)
            return SimpleNamespace(returncode=0, stdout=(
                "RGPU_DESKTOP_RESULT " + json.dumps(receipt) +
                f"\nRGPU_EXIT {nonce} 0\n"))

        self.tool.run_prepared(Path("/vm"), manifest, 1049, 0x1000002ED,
                               now=lambda: 1000, runner=runner,
                               nonce_factory=lambda: self.nonce)
        self.assertEqual(calls, [({**__import__('os').environ, "GX_TIMEOUT": "23"}, 23, 0)])

    def test_receipt_write_uses_supported_atomic_option(self):
        source = Path(__file__).with_name("desktop_display.m").read_text()
        self.assertNotIn("NSDataWritingAtomic | NSDataWritingWithoutOverwriting", source)
        self.assertIn("options:NSDataWritingAtomic", source)


if __name__ == "__main__":
    unittest.main()
