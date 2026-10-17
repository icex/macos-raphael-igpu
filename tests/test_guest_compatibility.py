import importlib.util
from pathlib import Path
import tempfile
import unittest
import os

ROOT = Path(__file__).resolve().parents[1]


class GuestCompatibilityProofTests(unittest.TestCase):
    def module(self):
        spec = importlib.util.spec_from_file_location('guest_compat',ROOT/'tools/guest-compatibility.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_saved_build_and_unsealed_observation_do_not_admit_launch(self):
        module=self.module()
        with tempfile.TemporaryDirectory() as directory:
            vm=Path(directory)
            (vm/'mac_hdd_ng.img').write_bytes(b'disk')
            with self.assertRaisesRegex(ValueError,'fresh GPU-less'):
                module.validate(vm,dict(guest_build='24G830'))
            guest=dict(guest_build='24H32',compatibility=dict(policy='dynamic-sites-v1',guest_version='15.8.1'))
            with self.assertRaisesRegex(ValueError,'not been sealed'):
                module.validate(vm,guest)

    def test_any_disk_write_requires_fresh_inspection(self):
        module=self.module()
        with tempfile.TemporaryDirectory() as directory:
            vm=Path(directory);disk=vm/'mac_hdd_ng.img'
            disk.write_bytes(b'disk')
            stamp=module.disk_identity(disk)
            proof=dict(policy='dynamic-sites-v1',guest_version='26.7.1',sealed=True,disk_identity=stamp,plain_shutdown={'exit_code':0})
            guest=dict(guest_build='25G241',compatibility=proof)
            stat=disk.stat();os.utime(disk,ns=(stat.st_atime_ns,stat.st_mtime_ns+1))
            with self.assertRaisesRegex(ValueError,'disk changed'):
                module.validate(vm,guest)

    def test_os_label_cannot_override_kernel_generation(self):
        module=self.module()
        guest=dict(guest_build='24H32',compatibility=dict(policy='dynamic-sites-v1',guest_version='26.7.1'))
        with self.assertRaisesRegex(ValueError,'outside macOS 15/26'):
            module.validate(Path('/unused'),guest)
