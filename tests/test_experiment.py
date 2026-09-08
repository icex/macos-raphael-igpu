import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import subprocess
import plistlib
import hashlib

ROOT = Path(__file__).resolve().parents[1]


class ExperimentTests(unittest.TestCase):
    def module(self):
        path = ROOT / 'tools/experiment.py'
        self.assertTrue(path.exists(), 'missing experiment admission tool')
        spec = importlib.util.spec_from_file_location('experiment', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_identity_mismatches_and_missing_values_fail_closed(self):
        validate = self.module().validate_identity
        expected = dict(binary_sha256='a'*64, info_sha256='b'*64, boot_args='rgpu=1',
                        kdk_sha256={'HWLibs': 'c'*64}, build_id='candidate')
        self.assertEqual(validate(expected, dict(expected)), [])
        for key in expected:
            for value in (None, 'stale'):
                observed = dict(expected, **{key: value})
                self.assertIn(key, validate(expected, observed))

    def host(self):
        return dict(boot_id='boot-A', amdgpu_initialized=True, capture_ready=True,
                    watchdogs_verified=True, device_pinned_awake=True, active_vm=False,
                    driver='vfio-pci', device='1002:13c0', iommu_group='31',
                    device_accessible=True)

    def test_unknown_or_failed_host_gate_refuses_admission(self):
        admit = self.module().admit
        manifest = dict(max_seconds=180, boot_id='boot-A', source_clean=True,
                        vfio_device='0000:7b:00.0')
        self.assertEqual(admit(manifest, self.host(), set()), [])
        for key in ('amdgpu_initialized', 'capture_ready', 'watchdogs_verified',
                    'device_pinned_awake', 'device_accessible'):
            for value in (False, None):
                host = dict(self.host(), **{key: value})
                self.assertIn(key, admit(manifest, host, set()))
        for field, value in [('source_clean', False), ('vfio_device', None), ('max_seconds', 0)]:
            self.assertIn(field, admit(dict(manifest, **{field: value}), self.host(), set()))
        self.assertIn('boot_already_used', admit(manifest, self.host(), {'boot-A'}))
        self.assertIn('active_vm', admit(manifest, dict(self.host(), active_vm=True), set()))

    def test_boot_reservation_survives_failure_and_cannot_be_replaced(self):
        reserve = self.module().reserve_boot
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            reserve(root, 'boot-A', 'first')
            with self.assertRaises(FileExistsError): reserve(root, 'boot-A', 'second')
            self.assertEqual(json.loads((root / 'boot-A.json').read_text())['experiment'], 'first')

    def test_remaining_budget_uses_earlier_launch_cap(self):
        eligible = self.module().probe_fits
        self.assertFalse(eligible(now=100, launch_deadline=150, container_deadline=190))
        self.assertTrue(eligible(now=100, launch_deadline=180, container_deadline=190))
        self.assertFalse(eligible(now=100, launch_deadline=None, container_deadline=190))

    def test_immutable_json_never_overwrites_prepared_identity(self):
        write = self.module().write_once
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'manifest.json'
            write(path, {'candidate': 'first'})
            with self.assertRaises(FileExistsError): write(path, {'candidate': 'second'})
            self.assertEqual(json.loads(path.read_text()), {'candidate': 'first'})

    def test_transactional_esp_staging_preserves_backup_and_reads_back(self):
        stage = getattr(self.module(), 'stage_image', None)
        self.assertIsNotNone(stage, 'transactional image staging missing')
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); image = root / 'esp.img'
            subprocess.run(['mformat', '-i', str(image), '-C', '-T', '16384', '::'], check=True)
            for directory in ('::/EFI', '::/EFI/OC', '::/EFI/OC/Kexts'):
                subprocess.run(['mmd', '-i', str(image), directory], check=True)
            before = image.read_bytes()
            bundle = root / 'RaphaelGPU.kext'
            (bundle / 'Contents/MacOS').mkdir(parents=True)
            (bundle / 'Contents/MacOS/RaphaelGPU').write_bytes(b'new-executable')
            (bundle / 'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleVersion': '1.0.163'}))
            config = plistlib.dumps({'test': 'new-config'})
            result = stage(image, bundle, config, offset=0)
            self.assertEqual(Path(result['backup']).read_bytes(), before)
            self.assertEqual(result['binary_sha256'], hashlib.sha256(b'new-executable').hexdigest())
            got = subprocess.check_output(['mtype', '-i', str(image), '::/EFI/OC/config.plist'])
            self.assertEqual(got, config)
            good = image.read_bytes()
            (bundle / 'Contents/MacOS/RaphaelGPU').unlink()
            with self.assertRaises((ValueError, FileNotFoundError)):
                stage(image, bundle, config, offset=0)
            self.assertEqual(image.read_bytes(), good)


if __name__ == '__main__': unittest.main()
