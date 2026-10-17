import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('install_ih', ROOT/'tools/install-ih-dma-guard.py')
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)
LAUNCHER = (b'local_customization=preserved\n'
    b'    vf="-device vfio-pci,host=${GPU},bus=pcie.0,addr=0x6"\n'
    b'    -e "EXTRA=${EXTRA_QEMU}"\n')


class InstallerTests(unittest.TestCase):
    def test_launcher_edits_preserve_local_settings_and_are_idempotent(self):
        result = tool.launcher_bytes(LAUNCHER)
        self.assertIn(b'local_customization=preserved', result)
        self.assertEqual(result.count(b'x-rgpu-dma-guard=on'), 1)
        self.assertEqual(tool.launcher_bytes(result), result)
        with self.assertRaises(ValueError):
            tool.launcher_bytes(b'unreviewed launcher')

    def test_backups_install_bytes_and_refuses_unknown_local_supervisor(self):
        with tempfile.TemporaryDirectory() as tmp:
            vm = Path(tmp)
            (vm/'run').mkdir()
            (vm/'macos-vm.sh').write_bytes(LAUNCHER)
            (vm/'vm-supervision.py').write_bytes(b'reviewed preimage')
            with patch.object(tool, 'SUPERVISOR_PREIMAGE', tool.sha(b'reviewed preimage')), \
                    patch.object(tool.subprocess, 'check_output', return_value='rgpu-inhibit\n'):
                value = tool.install(vm)
                self.assertEqual(value['status'], 'installed')
                self.assertEqual((Path(value['backup'])/'macos-vm.sh').read_bytes(), LAUNCHER)
                self.assertEqual((vm/'dma-guard.py').read_bytes(), (ROOT/'tools/dma-guard.py').read_bytes())
                self.assertEqual(tool.install(vm)['status'], 'already-installed')
                (vm/'vm-supervision.py').write_bytes(b'unrelated local change')
                with self.assertRaisesRegex(ValueError, 'local supervisor edits'):
                    tool.install(vm)


if __name__ == '__main__':
    unittest.main()
