"""Reject the false positives that previously hid the dead command processor."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

MODULE = Path(__file__).resolve().parents[1] / "tools" / "metal-test.py"


class MetalResultTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(MODULE.exists(), "the automatic Metal result validator is missing")
        spec = importlib.util.spec_from_file_location("metal_test", MODULE)
        self.tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.tool)
        self.result = {
            "run_id": "fresh-run", "passed": True, "device": "AMD Radeon Navi23",
            "registry_id": 1234, "metal3": True, "compute_rounds": 3,
            "compute_values_checked": 196608, "render_pixels_checked": 4096,
            "completed_command_buffers": 4,
        }

    def output(self):
        return "RGPU_METAL_RESULT " + json.dumps(self.result) + "\nRGPU_EXIT fresh-run 0\n"

    def test_accepts_verified_compute_and_render_for_this_run(self):
        self.assertEqual(self.tool.validate_output(self.output(), "fresh-run"), self.result)

    def test_rejects_enumeration_without_execution(self):
        for field in ("compute_rounds", "compute_values_checked", "render_pixels_checked",
                      "completed_command_buffers"):
            with self.subTest(field=field):
                saved = self.result[field]
                self.result[field] = 0
                with self.assertRaises(ValueError):
                    self.tool.validate_output(self.output(), "fresh-run")
                self.result[field] = saved

    def test_rejects_stale_output_even_when_it_claims_success(self):
        with self.assertRaises(ValueError):
            self.tool.validate_output(self.output(), "different-run")

    def test_requires_probe_exit_status_not_gx_exit_status(self):
        for suffix in ("", "RGPU_EXIT fresh-run 1\n"):
            with self.subTest(suffix=suffix):
                output = self.output().split("RGPU_EXIT")[0] + suffix
                with self.assertRaises(ValueError):
                    self.tool.validate_output(output, "fresh-run")

    def test_rejects_wrong_device_and_failed_probe(self):
        for field, value in (("device", "Apple Software Renderer"), ("passed", False),
                             ("metal3", False), ("registry_id", 0),
                             ("compute_values_checked", 65536)):
            with self.subTest(field=field):
                saved = self.result[field]
                self.result[field] = value
                with self.assertRaises(ValueError):
                    self.tool.validate_output(self.output(), "fresh-run")
                self.result[field] = saved

    def test_rejects_truncated_and_duplicate_results(self):
        for output in ("RGPU_METAL_RESULT {", self.output() + self.output()):
            with self.subTest(output=output):
                with self.assertRaises(ValueError):
                    self.tool.validate_output(output, "fresh-run")

    def test_transport_timeout_revokes_permit_and_removes_own_pending_command(self):
        # A delayed guest must not execute work after its runner has already failed.
        self.assertTrue(hasattr(self.tool, "run_guest_command"), "cancellable transport is missing")
        with tempfile.TemporaryDirectory() as directory:
            vm = Path(directory)
            (vm / "run").mkdir()
            gx = vm / "gx"
            gx.write_text("#!/usr/bin/env python3\nimport pathlib, sys, time\n"
                          "p=pathlib.Path(__file__).parent/'run'\n"
                          "(p/'cmd.txt').write_text(sys.argv[1])\n"
                          "time.sleep(5)\n")
            gx.chmod(0o700)
            started = time.monotonic()
            with self.assertRaises(subprocess.TimeoutExpired):
                self.tool.run_guest_command(vm, "our-command", "token", {}, timeout=0.2,
                                            execution_grace=0.1)
            self.assertGreaterEqual(time.monotonic() - started, 0.3)
            self.assertFalse((vm / "run/cmd.txt").exists())
            self.assertFalse((vm / "run/metal-permit-token").exists())

    def test_transport_cleanup_preserves_another_clients_command(self):
        self.assertTrue(hasattr(self.tool, "run_guest_command"), "cancellable transport is missing")
        with tempfile.TemporaryDirectory() as directory:
            vm = Path(directory)
            (vm / "run").mkdir()
            gx = vm / "gx"
            gx.write_text("#!/usr/bin/env python3\nimport pathlib\n"
                          "p=pathlib.Path(__file__).parent/'run'\n"
                          "(p/'cmd.txt').write_text('someone-else')\n")
            gx.chmod(0o700)
            self.tool.run_guest_command(vm, "our-command", "token", {}, execution_grace=0)
            self.assertEqual((vm / "run/cmd.txt").read_text(), "someone-else")
            self.assertFalse((vm / "run/metal-permit-token").exists())


if __name__ == "__main__":
    unittest.main()
