"""Offline contract tests for hybrid rendering on an existing QEMU display."""

import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "tools" / "desktop-display.py"
CONTROL_SOURCE = ROOT / "tests" / "desktop_display.m"
HYBRID_SOURCE = ROOT / "tests" / "desktop_existing_display.m"
CONTROL_SHA = "8fde7e567e6e7d492d3ad4d0fb38aa4236849c98e5bd65829f8ced6a2f82e4cb"


def load_tool():
    spec = importlib.util.spec_from_file_location("desktop_display_existing", MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ExistingDisplayTests(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.tool = load_tool()
        self.nonce = "abcdef0123456789abcdef0123456789"
        self.source = HYBRID_SOURCE.read_bytes()
        self.source_sha = hashlib.sha256(self.source).hexdigest()
        self.binary_sha = "c" * 64
        self.guest_binary = (
            f"/var/tmp/rgpu-desktop-existing-v1-{self.source_sha[:16]}/desktop-display")
        self.registry_id = 0x1000002ED

    def expected(self):
        return {
            "source_sha256": self.source_sha,
            "binary_sha256": self.binary_sha,
            "guest_binary": self.guest_binary,
            "registry_id": self.registry_id,
            "expiry_epoch": 2_000_000_060,
            "hold_seconds": 15,
            "expected_width": 1920,
            "expected_height": 1080,
            "expected_refresh": 60.0,
        }

    def receipt(self, **overrides):
        value = {
            "schema": 1,
            "nonce": self.nonce,
            "execution_mode": "existing-display-production",
            "source_sha256": self.source_sha,
            "binary_sha256": self.binary_sha,
            "guest_binary": self.guest_binary,
            "expiry_epoch": 2_000_000_060,
            "started_epoch": 2_000_000_001,
            "finished_epoch": 2_000_000_018,
            "hold_seconds": 15,
            "aqua": {
                "ready": True, "console_user": "bogdan", "console_uid": 501,
                "session_user": "bogdan", "session_uid": 501,
                "login_done": True, "on_console": True,
                "launch_domain": "gui/501", "launch_domain_environment": True,
                "launchd_job_pid": 812,
            },
            "display": {
                "online_ids": [42], "nsscreen_ids": [42], "screen_count": 1,
                "display_id": 42, "main_display_id": 42, "main": True,
                "active": True, "online": True,
                "width": 1920, "height": 1080, "refresh": 60.0,
                "expected_width": 1920, "expected_height": 1080,
                "expected_refresh": 60.0,
                "screen_frame_x": 0.0, "screen_frame_y": 0.0,
                "screen_frame_width": 1920.0, "screen_frame_height": 1080.0,
                "ownership": "preexisting", "created_by_probe": False,
                "removed_by_probe": False,
            },
            "render": {
                "registry_id": self.registry_id,
                "device_name": "AMD Radeon Navi23",
                "window_display_id": 42, "window_visible": True,
                "drawables_acquired": 120, "command_buffers_submitted": 120,
                "completion_callbacks_observed": 120,
                "command_buffers_completed": 120,
                "presentation_callbacks_observed": 120,
                "presented_frames": 120,
                "first_frame": 0, "last_frame": 119,
                "distinct_color_tokens": 2,
                "first_color_token": "#ff0000",
                "last_color_token": "#00ffff",
            },
            "provenance": {
                "existing_display_origin": "qemu-generic-graphics",
                "existing_display_origin_basis": "pinned_launch_profile",
                "render_device_origin": "exact_raphael_registry",
                "render_device_observed": True,
                "compositor_gpu_provenance": "unproven",
                "scanout_gpu_provenance": "unproven",
            },
            "remote_observation": {
                "required": True, "observed": False,
                "frame_change_observed": False,
                "evidence": "external_capture_required",
            },
        }
        for key, replacement in overrides.items():
            if "." in key:
                group, field = key.split(".", 1)
                value[group][field] = replacement
            else:
                value[key] = replacement
        return value

    def output(self, receipt=None, status=0):
        receipt = receipt or self.receipt()
        return ("RGPU_DESKTOP_EXISTING_RESULT " + json.dumps(receipt) +
                f"\nRGPU_EXIT {self.nonce} {status}\n")

    def test_control_source_and_signed_v2_path_semantics_remain_frozen(self):
        self.assertEqual(hashlib.sha256(CONTROL_SOURCE.read_bytes()).hexdigest(), CONTROL_SHA)
        self.assertEqual(
            self.tool._prepared_paths(CONTROL_SHA)[2],
            "/var/tmp/rgpu-desktop-display-v2-8fde7e567e6e7d49/desktop-display")

    def test_new_source_never_uses_virtual_display_spi(self):
        text = self.source.decode()
        self.assertNotIn("CGVirtualDisplay", text)
        self.assertNotIn("applySettings:", text)

    def test_prepare_uses_new_immutable_signed_identity(self):
        command = self.tool.prepare_existing_display_guest_command(
            self.nonce, self.source, 2_000_000_060)
        self.assertIn(self.guest_binary, command)
        self.assertNotIn("rgpu-desktop-display-v2-", command)
        self.assertIn("codesign --force --sign - --timestamp=none", command)
        self.assertIn("codesign --verify --strict", command)
        self.assertLess(command.index("curl -fsS"), command.index("/bin/mkdir"))

    def test_runtime_bootstraps_exact_binary_with_mode_registry_and_geometry(self):
        command = self.tool.existing_display_guest_command(
            self.nonce, 2_000_000_060, 15,
            guest_binary=self.guest_binary, source_sha256=self.source_sha,
            binary_sha256=self.binary_sha, registry_id=self.registry_id,
            expected_width=1920, expected_height=1080, expected_refresh=60.0)
        self.assertNotIn("xcrun", command)
        self.assertIn("launchctl bootstrap \"gui/$uid\"", command)
        self.assertIn("codesign --verify --strict", command)
        encoded = re.search(r"/usr/bin/printf %s ([A-Za-z0-9+/=]+) \| "
                            r"/usr/bin/base64 -D", command).group(1)
        plist = base64.b64decode(encoded).decode()
        for argument in ("existing-display-production", str(self.registry_id),
                         "1920", "1080", "60.0"):
            self.assertIn(f"<string>{argument}</string>", plist)

    def test_validator_accepts_exact_existing_display_and_raphael_presentations(self):
        result = self.tool.validate_existing_display_output(
            self.output(), self.nonce, self.expected())
        self.assertEqual(result["display"]["ownership"], "preexisting")
        self.assertEqual(result["render"]["registry_id"], self.registry_id)
        self.assertEqual(result["provenance"]["compositor_gpu_provenance"], "unproven")

    def test_validator_rejects_non_aqua_or_ambiguous_existing_screen(self):
        cases = {
            "aqua.ready": False,
            "aqua.console_uid": 0,
            "display.online_ids": [42, 43],
            "display.nsscreen_ids": [42, 43],
            "display.screen_count": 2,
            "display.main_display_id": 43,
            "display.main": False,
            "display.active": False,
        }
        for field, value in cases.items():
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.tool.validate_existing_display_output(
                    self.output(self.receipt(**{field: value})), self.nonce,
                    self.expected())

    def test_validator_rejects_wrong_geometry(self):
        for field, value in {
            "display.width": 1280,
            "display.height": 720,
            "display.refresh": 59.0,
            "display.expected_width": 1280,
        }.items():
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "geometry"):
                self.tool.validate_existing_display_output(
                    self.output(self.receipt(**{field: value})), self.nonce,
                    self.expected())

    def test_validator_rejects_fallback_device_and_callback_or_presentation_failures(self):
        cases = {
            "render.registry_id": 99,
            "render.device_name": "Apple Software Renderer",
            "render.window_display_id": 43,
            "render.window_visible": False,
            "render.command_buffers_submitted": 119,
            "render.completion_callbacks_observed": 119,
            "render.command_buffers_completed": 119,
            "render.presentation_callbacks_observed": 119,
            "render.presented_frames": 119,
            "render.distinct_color_tokens": 1,
            "render.last_color_token": "#ff0000",
        }
        for field, value in cases.items():
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "render"):
                self.tool.validate_existing_display_output(
                    self.output(self.receipt(**{field: value})), self.nonce,
                    self.expected())

    def test_validator_never_promotes_compositor_scanout_or_remote_provenance(self):
        cases = {
            "provenance.existing_display_origin_basis": "observed_by_probe",
            "provenance.compositor_gpu_provenance": "Raphael",
            "provenance.scanout_gpu_provenance": "Raphael",
            "remote_observation.observed": True,
            "remote_observation.frame_change_observed": True,
        }
        for field, value in cases.items():
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.tool.validate_existing_display_output(
                    self.output(self.receipt(**{field: value})), self.nonce,
                    self.expected())

    def test_validator_rejects_partial_failure_receipt_for_production(self):
        with self.assertRaises(ValueError):
            self.tool.validate_existing_display_output(
                self.output(self.receipt(**{"render.presented_frames": 0}), status=1),
                self.nonce, self.expected())


if __name__ == "__main__":
    unittest.main()
