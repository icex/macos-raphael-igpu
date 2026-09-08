from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class GpuBindSafetyTests(unittest.TestCase):
    def test_disables_all_pci_reset_methods_before_vfio_becomes_user_accessible(self):
        source = (ROOT / 'tools/gpu-bind.sh').read_text()
        disable = source.index('printf \'\\n\' > "${DEVICE_SYSFS}/reset_method"')
        verify = source.index('PCI reset methods disabled')
        chown = source.index('chown "${OWNER}" "${VFIO_GROUP}"')
        self.assertLess(disable, verify)
        self.assertLess(verify, chown)

    def test_refuses_handoff_if_reset_method_attribute_is_missing(self):
        source = (ROOT / 'tools/gpu-bind.sh').read_text()
        self.assertIn('[[ -w "${DEVICE_SYSFS}/reset_method" ]]', source)
        self.assertIn('refusing unsafe VFIO handoff', source)

    def test_never_guesses_the_unprivileged_owner(self):
        source = (ROOT / 'tools/gpu-bind.sh').read_text()
        self.assertNotIn('SUDO_UID:-1000', source)
        self.assertIn('RGPU_OWNER_UID', source)
        self.assertIn('cannot identify the invoking user', source)

    def test_direct_vm_launcher_refuses_enabled_reset_method_before_qemu(self):
        source = (ROOT / 'tools/macos-vm.sh').read_text()
        reset_gate = source.index('PCI reset methods are still enabled')
        vfio_device = source.index('vf="-device vfio-pci')
        docker_run = source.index('docker run')
        self.assertLess(reset_gate, vfio_device)
        self.assertLess(reset_gate, docker_run)

    def test_emergency_recovery_also_disables_resets_before_chown(self):
        source = (ROOT / 'tools/recover-igpu.sh').read_text()
        self.assertNotIn('SUDO_UID:-1000', source)
        disable = source.index('"$S/reset_method"')
        chown = source.index('chown "$OWNER"')
        self.assertLess(disable, chown)


if __name__ == '__main__':
    unittest.main()
