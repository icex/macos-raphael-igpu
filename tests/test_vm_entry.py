import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "tools/vm-entry.sh"


class VmEntryTests(unittest.TestCase):
    def run_entry(self, launch, mode="off", extra="-display none"):
        with tempfile.TemporaryDirectory() as temporary:
            vm = Path(temporary)
            (vm / "Launch.sh").write_text("#!/bin/sh\n" + launch + "\n")
            (vm / "enable-ssh.sh").write_text("#!/bin/sh\nexit 0\n")
            (vm / "enable-ssh.sh").chmod(0o700)
            bindir = vm / "bin"; bindir.mkdir()
            for name, body in {
                "sudo": "exit 0", "qemu-system-x86_64":
                "printf '%s\\n' \"$@\" > \"$VM_ENTRY_CAPTURE\"",
            }.items():
                path = bindir / name
                path.write_text("#!/bin/sh\n" + body + "\n")
                path.chmod(0o700)
            capture = vm / "argv.txt"
            env = dict(os.environ, PATH=str(bindir) + os.pathsep + os.environ["PATH"],
                       VM_ENTRY_ROOT=str(vm), VM_ENTRY_CAPTURE=str(capture),
                       GENERIC_GRAPHICS=mode, EXTRA=extra, NOPICKER="false",
                       DISK_BUS="ahci")
            result = subprocess.run(["bash", str(ENTRY)], env=env, text=True,
                                    capture_output=True, timeout=5)
            return result, capture.read_text().splitlines() if capture.exists() else []

    def test_off_replaces_single_default_and_forces_headless_argv(self):
        result, argv = self.run_entry(
            'qemu-system-x86_64 -m 2G -vga vmware $EXTRA')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(argv.count("-vga"), 1)
        self.assertEqual(argv[argv.index("-vga") + 1], "none")
        self.assertEqual(argv.count("-display"), 1)
        self.assertEqual(argv[argv.index("-display") + 1], "none")
        forbidden = ("vmware", "VGA", "vmware-svga", "qxl", "virtio-vga",
                     "bochs-display", "ramfb")
        self.assertFalse(any(any(token in arg for token in forbidden) for arg in argv))

    def test_off_refuses_missing_or_multiple_default_vga(self):
        for launch in (
                'qemu-system-x86_64 -m 2G -display gtk',
                'qemu-system-x86_64 -vga vmware -vga vmware',
                'qemu-system-x86_64 -vga vmware -vga none',
                'qemu-system-x86_64 -vga vmware -vga cirrus',
                'qemu-system-x86_64 -vga\tvmware $EXTRA'):
            result, argv = self.run_entry(launch)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(argv, [])

    def test_unknown_mode_and_extra_graphics_injection_are_refused(self):
        result, argv = self.run_entry('qemu-system-x86_64 -vga vmware', mode="maybe")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(argv, [])
        for extra in ("-vga qxl", "-device virtio-vga", "-device VGA",
                      "-device vmware-svga", "-device bochs-display", "-device ramfb",
                      "-device qxl-vga", "-device virtio-vga-gl",
                      "-device virtio-gpu-pci", "-device secondary-vga",
                      "-device virtio-gpu-gl-pci",
                      "-device ati-vga", "-device cirrus-vga", "-display gtk",
                      "-display none -display none", ""):
            result, argv = self.run_entry(
                'qemu-system-x86_64 -vga vmware "$EXTRA"', extra=extra)
            self.assertNotEqual(result.returncode, 0, extra)
            self.assertEqual(argv, [])

    def test_generic_device_already_in_image_launch_is_refused(self):
        for device in ("VGA", "vmware-svga", "qxl", "qxl-vga", "virtio-vga",
                       "virtio-vga-gl", "virtio-gpu-pci", "secondary-vga",
                       "virtio-gpu-gl-pci",
                       "ati-vga", "cirrus-vga", "bochs-display", "ramfb"):
            result, argv = self.run_entry(
                f'qemu-system-x86_64 -vga vmware -device {device} $EXTRA')
            self.assertNotEqual(result.returncode, 0, device)
            self.assertEqual(argv, [])


if __name__ == "__main__":
    unittest.main()
