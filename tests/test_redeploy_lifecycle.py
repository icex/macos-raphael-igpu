"""Run the actual launcher script with controlled command binaries; no VM/device access."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RedeployTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.vm = Path(self.temp.name)
        (self.vm / "run").mkdir()
        shutil.copy(ROOT / "tools/redeploy.sh", self.vm / "redeploy.sh")
        for name in ("config.plist", "run/oc-raw.img", "run/OpenCore-rebuilt.qcow2"):
            (self.vm / name).write_text("fixture")
        (self.vm / "mkrom.py").write_text("pass\n")
        (self.vm / "ocprop.py").write_text("from pathlib import Path\nPath('run/config-new.plist').write_text('fixture')\n")
        (self.vm / "vm-supervision.py").write_text(
            "import json, os, pathlib, sys\n"
            "pathlib.Path('run/supervisor-call.json').write_text(json.dumps(sys.argv[1:]))\n"
            "print('{}')\n"
            "sys.exit(int(os.environ.get('FIXTURE_ARM_EXIT', '0')))\n")
        binaries = self.vm / "bin"
        binaries.mkdir()
        for name, body in {
            "docker": "exit 0",
            "systemd-inhibit": "exit 99",
            "systemd-run": "exit 99",
            "systemctl": "exit 99",
            "mcopy": "exit 0",
            "sleep": "exit 0",
            "readlink": "echo /fixture/vfio-pci",
            "journalctl": "exit 0",
            "askpass": "exit 99",
        }.items():
            command = binaries / name
            command.write_text("#!/bin/sh\n" + body + "\n")
            command.chmod(0o700)
        (self.vm / "milestones.py").write_text("#!/bin/sh\nexit 0\n")
        (self.vm / "milestones.py").chmod(0o700)
        self.env = dict(os.environ, PATH=str(binaries) + os.pathsep + os.environ["PATH"],
                        SUDO_ASKPASS=str(binaries / "askpass"), QUIESCE="0")

    def run_script(self, *args):
        return subprocess.run(["bash", str(self.vm / "redeploy.sh"), *args], cwd=self.vm,
                              env=self.env, text=True, capture_output=True, timeout=5)

    def test_default_launch_uses_supervisor_with_no_gpu_and_no_gpu_deadline(self):
        self.env["GPU"] = "inherited-gpu-must-be-disabled"
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        call = json.loads((self.vm / "run/supervisor-call.json").read_text())
        self.assertEqual(call[0], "start")
        self.assertEqual(call[call.index("--max-seconds") + 1], "0")
        self.assertNotIn("--gpu", call)

    def test_failed_supervisor_cannot_report_success(self):
        self.env["FIXTURE_ARM_EXIT"] = "1"
        result = self.run_script("--no-gpu")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("VM relaunched", result.stdout)

    def test_gpu_cap_zero_and_nonfinite_are_rejected_before_launch(self):
        for cap in ("0", "nan", "-1", "inf", "1.5", "999999999999999999999999"):
            self.env["RGPU_MAX_SECONDS"] = cap
            result = self.run_script("--gpu")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("positive", result.stderr)
            self.assertFalse((self.vm / "run/supervisor-call.json").exists())

    def test_virgin_vfio_refusal_has_no_override(self):
        self.env.update(RGPU_MAX_SECONDS="180", RGPU_ALLOW_VIRGIN_IGPU="1")
        result = self.run_script("--gpu")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("There is deliberately no override", result.stderr)
        self.assertFalse((self.vm / "run/supervisor-call.json").exists())


if __name__ == "__main__":
    unittest.main()
