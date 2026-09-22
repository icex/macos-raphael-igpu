import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "tools/vm-entry.sh"


class VmEntryTests(unittest.TestCase):
    def run_entry(self, launch, mode="off", extra="-display none", audio=None):
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
            if audio is not None:
                env["AUDIO_DRIVER"] = audio
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

    def test_actual_launcher_device_order_keeps_headless_vfio_at_property_slot(self):
        launcher = ROOT / "tools/macos-vm.sh"
        match = re.search(r'^\s*vf="-device ([^"]+)"$', launcher.read_text(), re.M)
        self.assertIsNotNone(match)
        vfio = match.group(1).replace("${GPU}", "0000:7b:00.0")
        launch = """qemu-system-x86_64 -machine q35 \\
-device qemu-xhci,id=xhci \\
-device usb-kbd,bus=xhci.0 -device usb-tablet,bus=xhci.0 \\
-device isa-applesmc,osk=fixture \\
-device ich9-intel-hda -device hda-duplex,audiodev=hda \\
-device ich9-ahci,id=sata \\
-device ide-hd,bus=sata.2,drive=OpenCoreBoot \\
-device ide-hd,bus=sata.4,drive=MacHDD \\
-device vmxnet3,netdev=net0,id=net0 \\
-vga vmware $EXTRA"""
        for mode, extra in (("off", f"-device {vfio} -display none"),
                            ("on", f"-device {vfio}")):
            with self.subTest(mode=mode):
                result, argv = self.run_entry(launch, mode=mode, extra=extra)
                self.assertEqual(result.returncode, 0, result.stderr)
                devices = [argv[index + 1] for index, value in enumerate(argv[:-1])
                           if value == "-device"]
                slot6 = [device for device in devices
                         if "bus=pcie.0" in device and "addr=0x6" in device]
                self.assertEqual(slot6, [vfio])
                if mode == "off":
                    self.assertNotIn("vmware", argv)
                    self.assertNotIn("ramfb", " ".join(argv))
                else:
                    self.assertEqual(argv[argv.index("-vga") + 1], "vmware")

    IMAGE_AUDIO = ("-audiodev ${AUDIO_DRIVER:-alsa},id=hda -device ich9-intel-hda "
                   "-device hda-duplex,audiodev=hda \\")

    def test_usb_audio_replaces_the_image_hda_codec_on_the_pulse_backend(self):
        launch = ("qemu-system-x86_64 -machine q35 \\\n-device qemu-xhci,id=xhci \\\n"
                  "-device usb-kbd,bus=xhci.0 -device usb-tablet,bus=xhci.0 \\\n"
                  + self.IMAGE_AUDIO + "\n-vga vmware $EXTRA")
        result, argv = self.run_entry(launch, audio="usb")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(argv[argv.index("-audiodev") + 1], "pa,id=hda")
        devices = [argv[index + 1] for index, value in enumerate(argv[:-1]) if value == "-device"]
        self.assertEqual([d for d in devices if "audio" in d or "hda" in d],
                         ["usb-audio,audiodev=hda,bus=xhci.0"])
        self.assertEqual(argv.count("-audiodev"), 1)
        # Every other mode leaves the image's codec line alone or strips it.
        result, argv = self.run_entry(launch, audio="pa")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("hda-duplex,audiodev=hda", argv)
        self.assertNotIn("usb-audio,audiodev=hda,bus=xhci.0", argv)
        result, argv = self.run_entry(launch, audio="none")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any("audio" in a or "hda" in a for a in argv))

    def test_usb_audio_refuses_an_image_without_the_codec_or_xhci_shape(self):
        for launch in (
                "qemu-system-x86_64 -vga vmware " + self.IMAGE_AUDIO + "\n$EXTRA",   # no xhci
                "qemu-system-x86_64 -device qemu-xhci,id=xhci -vga vmware $EXTRA",   # no codec
                "qemu-system-x86_64 -device qemu-xhci,id=xhci \\\n" + self.IMAGE_AUDIO
                + "\n-device hda-micro,audiodev=hda -vga vmware $EXTRA"):
            result, argv = self.run_entry(launch, audio="usb")
            self.assertNotEqual(result.returncode, 0, launch)
            self.assertEqual(argv, [])

    def test_headless_launcher_reaches_docker_without_x11_or_host_media_devices(self):
        with tempfile.TemporaryDirectory() as temporary:
            vm = Path(temporary)
            launcher = vm / "macos-vm.sh"
            # Exercise the real preflight against a fixture, without requiring KVM.
            kvm = vm / "kvm"
            kvm.touch()
            source = (ROOT / "tools/macos-vm.sh").read_text()
            self.assertIn("[[ -w /dev/kvm ]]", source)
            launcher.write_text(source.replace("/dev/kvm", str(kvm)))
            launcher.chmod(0o700)
            for name in ("mac_hdd_ng.img", "OpenCore.qcow2", "env", "vm-entry.sh"):
                (vm / name).touch()
            bindir = vm / "bin"; bindir.mkdir()
            capture = vm / "docker-argv.txt"
            docker = bindir / "docker"
            docker.write_text("#!/bin/sh\n"
                              "[ \"$1\" = info ] && exit 0\n"
                              "printf '%s\\n' \"$@\" > \"$DOCKER_CAPTURE\"\n")
            docker.chmod(0o700)
            env = dict(os.environ, PATH=str(bindir) + os.pathsep + os.environ["PATH"],
                       GENERIC_GRAPHICS="off", AUDIO="pa", GL="off",
                       DOCKER_CAPTURE=str(capture), DISPLAY="", XAUTHORITY="",
                       GPU="", GPU_ID="", GPU_ROM="", GPU_SUB="", EXTRA="",
                       SERIAL="off", CRITICAL_SERIAL="off", GDB="off")
            result = subprocess.run([str(launcher), "run"], env=env, text=True,
                                    capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            argv = capture.read_text().splitlines()
            self.assertIn("run", argv)
            self.assertIn("GENERIC_GRAPHICS=off", argv)
            self.assertIn("AUDIO_DRIVER=none", argv)
            joined = "\n".join(argv)
            self.assertIn("-display none", joined)
            for forbidden in ("/tmp/.X11-unix", ".Xauthority", "DISPLAY=", "--ipc=host",
                              "/dev/dri", "/dev/snd", "/pulse"):
                self.assertNotIn(forbidden, joined)

            # AUDIO=usb is the one display-less mode that keeps a host audio path:
            # the pulse socket is mounted and the entry script sees AUDIO_DRIVER=usb.
            pulse = vm / "pulse"; pulse.mkdir()
            import socket
            with socket.socket(socket.AF_UNIX) as native:
                native.bind(str(pulse / "native"))
                capture.unlink()
                source_usb = launcher.read_text().replace(
                    'pulse_dir="/run/user/$(id -u)/pulse"', f'pulse_dir="{pulse}"')
                launcher.write_text(source_usb)
                usb = subprocess.run([str(launcher), "run"], env=dict(env, AUDIO="usb"),
                                     text=True, capture_output=True, timeout=5)
                self.assertEqual(usb.returncode, 0, usb.stderr)
                argv_usb = capture.read_text().splitlines()
                self.assertIn("AUDIO_DRIVER=usb", argv_usb)
                self.assertIn(f"{pulse}:/xdgrt/pulse", argv_usb)
                self.assertNotIn("AUDIO_DRIVER=none", argv_usb)
                for forbidden in ("/tmp/.X11-unix", "/dev/dri", "/dev/snd"):
                    self.assertNotIn(forbidden, "\n".join(argv_usb))
                launcher.write_text(source.replace("/dev/kvm", str(kvm)))

            # Missing KVM must still fail before the mocked Docker invocation.
            kvm.unlink()
            capture.unlink()
            refused = subprocess.run([str(launcher), "run"], env=env, text=True,
                                     capture_output=True, timeout=5)
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn("is not writable", refused.stderr)
            self.assertFalse(capture.exists())


if __name__ == "__main__":
    unittest.main()
