import importlib.util
from pathlib import Path
import struct
import unittest

spec = importlib.util.spec_from_file_location('smc_handoff', Path(__file__).resolve().parents[1] / 'tools/prepare-smc-handoff.py')
smc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smc)


class HandoffTests(unittest.TestCase):
    def config(self):
        return {'Kernel': {'Add': [
            {'BundlePath': 'Lilu.kext', 'Enabled': True},
            {'BundlePath': 'VirtualSMC.kext', 'ExecutablePath': 'Contents/MacOS/VirtualSMC', 'Enabled': False}]},
            'ACPI': {'Patch': []}, 'NVRAM': {'Add': {smc.BOOT_GUID: {'boot-args': '-v rgputexdiag=2'}}},
            'DeviceProperties': {'Add': {'fixture': {'preserve': b'yes'}}}}

    def dsdt(self, count=1):
        payload = bytearray(b'DSDT' + bytes(32) + smc.FIND * count)
        struct.pack_into('<I', payload, 4, len(payload))
        return bytes(payload)

    def test_only_intended_changes_and_input_preserved(self):
        before = self.config()
        after = smc.prepare(before, self.dsdt())
        self.assertFalse(before['Kernel']['Add'][1]['Enabled'])
        self.assertTrue(after['Kernel']['Add'][1]['Enabled'])
        self.assertEqual(after['DeviceProperties'], before['DeviceProperties'])
        self.assertEqual(after['NVRAM']['Add'][smc.BOOT_GUID]['boot-args'], '-v rgputexdiag=2 vsmcgen=2')
        patch = after['ACPI']['Patch'][0]
        patched = self.dsdt().replace(patch['Find'], patch['Replace'])
        self.assertEqual(sum(a != b for a, b in zip(self.dsdt(), patched)), 1)
        self.assertEqual(patched[-1], 0)

    def test_missing_duplicate_or_changed_aml_refused(self):
        for data in (self.dsdt(0), self.dsdt(2), self.dsdt()[:-1] + b'\x0f'):
            with self.assertRaises(ValueError): smc.prepare(self.config(), data)

    def test_bad_table_refused(self):
        for data in (b'', b'SSDT' + self.dsdt()[4:], self.dsdt() + b'\x00'):
            with self.assertRaises(ValueError): smc.prepare(self.config(), data)

    def test_conflicting_provider_settings_refused(self):
        for flag in ('-vsmcoff', '-vsmccomp', 'vsmcgen=1'):
            c = self.config(); c['NVRAM']['Add'][smc.BOOT_GUID]['boot-args'] += ' ' + flag
            with self.assertRaises(ValueError): smc.prepare(c, self.dsdt())
        c = self.config(); c['Kernel']['Add'].reverse()
        with self.assertRaises(ValueError): smc.prepare(c, self.dsdt())

    def test_repeat_refused(self):
        c = smc.prepare(self.config(), self.dsdt())
        with self.assertRaises(ValueError): smc.prepare(c, self.dsdt())
