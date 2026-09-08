import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load_tool():
    path = ROOT / 'tools/vfio-recover.py'
    spec = importlib.util.spec_from_file_location('vfio_recover', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeTransport:
    def __init__(self, tool, *, fail_command=None):
        self.tool = tool
        self.fail_command = fail_command
        self.events = []
        self.value = 0x80050000
        self.region = {'index': 5, 'size': 0x80000, 'offset': 0x120000,
                       'read': True, 'write': True, 'mmap': True}

    def __enter__(self):
        self.events.append('open')
        return self

    def __exit__(self, kind, error, trace):
        self.events.append('close')

    def read32(self, offset):
        self.events.append(('read', offset))
        return self.value

    def write32(self, offset, value):
        self.events.append(('write', offset, value))
        if value != self.fail_command:
            self.value = self.tool.READY_FLAG | value

    def metadata(self):
        return dict(self.region)


class VfioRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool()

    def state(self, **changes):
        state = dict(boot_id='boot-A', active_vm=False, driver='vfio-pci',
                     device='1002:13c0', iommu_group='31', pci_command=0x0003)
        state.update(changes)
        return state

    def test_uapi_ioctl_numbers_match_linux_legacy_vfio_abi(self):
        self.assertEqual(self.tool.VFIO_GET_API_VERSION, 0x3b64)
        self.assertEqual(self.tool.VFIO_CHECK_EXTENSION, 0x3b65)
        self.assertEqual(self.tool.VFIO_SET_IOMMU, 0x3b66)
        self.assertEqual(self.tool.VFIO_GROUP_GET_STATUS, 0x3b67)
        self.assertEqual(self.tool.VFIO_GROUP_SET_CONTAINER, 0x3b68)
        self.assertEqual(self.tool.VFIO_GROUP_GET_DEVICE_FD, 0x3b6a)
        self.assertEqual(self.tool.VFIO_DEVICE_GET_REGION_INFO, 0x3b6c)

    def test_host_gate_requires_exact_idle_vfio_device_and_bus_master_off(self):
        check = self.tool.validate_host_state
        self.assertEqual(check(self.state(), 'boot-A'), [])
        cases = [('active_vm', True), ('driver', 'amdgpu'), ('device', '1002:ffff'),
                 ('iommu_group', '30'), ('pci_command', 0x0007), ('boot_id', 'boot-B')]
        for field, value in cases:
            with self.subTest(field=field):
                self.assertIn(field if field != 'pci_command' else 'bus_master',
                              check(self.state(**{field:value}), 'boot-A'))

    def test_recovery_destroys_both_rings_and_closes_transport(self):
        fake = FakeTransport(self.tool)
        states = iter([self.state(), self.state()])
        evidence = self.tool.perform_recovery(
            'boot-A', 'a'*32, lambda:next(states), lambda:fake,
            lambda cursor=None: ('cursor-2', [], []), sleep=lambda _:None)
        writes = [event for event in fake.events if event[0] == 'write']
        self.assertEqual(writes, [
            ('write', self.tool.C2PMSG_64_OFFSET, self.tool.DESTROY_RINGS),
            ('write', self.tool.C2PMSG_64_OFFSET, self.tool.DESTROY_GPCOM_RING)])
        self.assertEqual(fake.events[-1], 'close')
        self.assertEqual([row['command'] for row in evidence['commands']],
                         [self.tool.DESTROY_RINGS, self.tool.DESTROY_GPCOM_RING])
        self.assertTrue(all(row['confirmed'] for row in evidence['commands']))

    def test_mailbox_timeout_closes_transport_and_never_reports_success(self):
        fake = FakeTransport(self.tool, fail_command=self.tool.DESTROY_RINGS)
        states = iter([self.state(), self.state()])
        with self.assertRaisesRegex(self.tool.RecoveryError, 'destroy all rings'):
            self.tool.perform_recovery(
                'boot-A', 'b'*32, lambda:next(states), lambda:fake,
                lambda cursor=None: ('cursor-2', [], []),
                sleep=lambda _:None, polls=3)
        self.assertEqual(fake.events[-1], 'close')
        self.assertNotIn(('write', self.tool.C2PMSG_64_OFFSET,
                          self.tool.DESTROY_GPCOM_RING), fake.events)

    def test_post_transaction_bus_master_or_kernel_fault_fails(self):
        for mode in ('bus-master', 'fault'):
            with self.subTest(mode=mode):
                fake = FakeTransport(self.tool)
                states = iter([self.state(), self.state(pci_command=7) if mode == 'bus-master'
                               else self.state()])
                kernel = ((lambda cursor=None: ('cursor-2', ['IO_PAGE_FAULT'], ['IO_PAGE_FAULT']))
                          if mode == 'fault' else
                          (lambda cursor=None: ('cursor-2', [], [])))
                with self.assertRaises(self.tool.RecoveryError):
                    self.tool.perform_recovery('boot-A', 'c'*32, lambda:next(states),
                                               lambda:fake, kernel, sleep=lambda _:None)

    def test_receipt_is_created_once_only_after_complete_recovery(self):
        with tempfile.TemporaryDirectory() as temp:
            vm = Path(temp); (vm/'run/used-gpu-boots').mkdir(parents=True)
            ledger = {'boot_id':'boot-A', 'launches':[{'run_id':'d'*32}]}
            (vm/'run/used-gpu-boots/boot-A.json').write_text(json.dumps(ledger))
            fake = FakeTransport(self.tool)
            states = iter([self.state(), self.state(), self.state()])
            with patch.object(self.tool, 'host_state', side_effect=lambda:next(states)), \
                 patch.object(self.tool, 'LegacyVfio', return_value=fake), \
                 patch.object(self.tool, 'kernel_updates', side_effect=[
                     ('cursor-1', [], []), ('cursor-2', [], [])]):
                receipt = self.tool.recover(vm, 'd'*32)
            path = vm/'run/vfio-recovery/boot-A'/('d'*32+'.json')
            self.assertTrue(path.exists())
            self.assertEqual(json.loads(path.read_text())['recovery_id'], receipt['recovery_id'])
            self.assertEqual(receipt['status'], 'recovered')
            with self.assertRaises(FileExistsError):
                self.tool.write_once(path, receipt)

    def test_receipt_refuses_wrong_or_nonlatest_prior_run(self):
        with tempfile.TemporaryDirectory() as temp:
            vm = Path(temp); (vm/'run/used-gpu-boots').mkdir(parents=True)
            ledger = {'boot_id':'boot-A', 'launches':[{'run_id':'e'*32}, {'run_id':'f'*32}]}
            (vm/'run/used-gpu-boots/boot-A.json').write_text(json.dumps(ledger))
            with patch.object(self.tool, 'host_state', return_value=self.state()):
                with self.assertRaisesRegex(self.tool.RecoveryError, 'latest launch'):
                    self.tool.recover(vm, 'e'*32)


if __name__ == '__main__':
    unittest.main()
