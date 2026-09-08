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
        self.registers = {}
        self.region = {'index': 5, 'size': 0x80000, 'offset': 0x120000,
                       'read': True, 'write': True, 'mmap': True}

    def __enter__(self):
        self.events.append('open')
        return self

    def __exit__(self, kind, error, trace):
        self.events.append('close')

    def read32(self, offset):
        self.events.append(('read', offset))
        return self.value if offset == self.tool.C2PMSG_64_OFFSET else self.registers.get(offset, 0)

    def write32(self, offset, value):
        self.events.append(('write', offset, value))
        if offset != self.tool.C2PMSG_64_OFFSET:
            self.registers[offset] = value
        elif value != self.fail_command:
            self.value = self.tool.READY_FLAG | value

    def metadata(self):
        return dict(self.region)


class VfioRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool()

    def test_sdma_registers_use_ip_discovery_segment_zero(self):
        tool = self.tool
        self.assertEqual(tool.SDMA0_F32_CNTL_OFFSET,
                         (tool.GC_SEG0 + 0x2A) * 4)
        self.assertEqual(tool.SDMA0_CNTL_OFFSET,
                         (tool.GC_SEG0 + 0x1C) * 4)
        self.assertEqual(tool.SDMA0_GFX_RB_CNTL_OFFSET,
                         (tool.GC_SEG0 + 0x80) * 4)
        self.assertEqual(tool.SDMA0_GFX_IB_CNTL_OFFSET,
                         (tool.GC_SEG0 + 0x8A) * 4)

    def state(self, **changes):
        state = dict(boot_id='boot-A', active_vm=False, driver='vfio-pci',
                     device='1002:13c0', iommu_group='31', pci_command=0x0003,
                     reset_methods=[])
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
                 ('iommu_group', '30'), ('pci_command', 0x0007), ('boot_id', 'boot-B'),
                 ('reset_methods', ['bus'])]
        for field, value in cases:
            with self.subTest(field=field):
                expected = {'pci_command':'bus_master', 'reset_methods':'reset_method'}.get(
                    field, field)
                self.assertIn(expected,
                              check(self.state(**{field:value}), 'boot-A'))

    def test_bus_reset_method_is_rejected_before_vfio_is_opened(self):
        opened = []
        with self.assertRaisesRegex(self.tool.RecoveryError, 'reset_method'):
            self.tool.perform_recovery(
                'boot-A', 'a'*32,
                lambda:self.state(reset_methods=['bus']),
                lambda:opened.append(True),
                lambda cursor=None:('cursor-2', [], []), sleep=lambda _:None)
        self.assertEqual(opened, [])

    def test_recovery_destroys_both_rings_and_closes_transport(self):
        fake = FakeTransport(self.tool)
        states = iter([self.state(), self.state()])
        evidence = self.tool.perform_recovery(
            'boot-A', 'a'*32, lambda:next(states), lambda:fake,
            lambda cursor=None: ('cursor-2', [], []), sleep=lambda _:None)
        writes = [event for event in fake.events if event[0] == 'write' and
                  event[1] == self.tool.C2PMSG_64_OFFSET]
        self.assertEqual(writes, [
            ('write', self.tool.C2PMSG_64_OFFSET, self.tool.DESTROY_RINGS),
            ('write', self.tool.C2PMSG_64_OFFSET, self.tool.DESTROY_GPCOM_RING)])
        self.assertEqual(fake.events[-1], 'close')
        self.assertEqual([row['command'] for row in evidence['commands']],
                         [self.tool.DESTROY_RINGS, self.tool.DESTROY_GPCOM_RING])
        self.assertTrue(all(row['confirmed'] for row in evidence['commands']))
        self.assertEqual(evidence['gc_quiesce']['status'], 'quiesced')
        self.assertTrue(evidence['authorizes_launch'])
        self.assertEqual(evidence['schema'], 2)
        self.assertEqual(evidence['reset_methods_before'], [])
        self.assertEqual(evidence['reset_methods_after'], [])

    def test_gc_quiesce_dequeues_before_halting_engines(self):
        tool = self.tool

        class QueueTransport(FakeTransport):
            def __init__(self):
                super().__init__(tool)
                self.selector = 0
                self.active = {tool.queue_selector(2, 1, 0): 1}

            def read32(self, offset):
                if offset == tool.CP_HQD_ACTIVE_OFFSET:
                    self.events.append(('read-active', self.selector))
                    return self.active.get(self.selector, 0)
                return super().read32(offset)

            def write32(self, offset, value):
                if offset == tool.GRBM_GFX_CNTL_OFFSET:
                    self.selector = value
                if offset == tool.CP_HQD_DEQUEUE_OFFSET and value == 1:
                    self.active[self.selector] = 0
                super().write32(offset, value)

        fake = QueueTransport()
        result = tool.quiesce_gc(fake, sleep=lambda _:None, polls=3)
        self.assertEqual(result['active_before'], 1)
        self.assertEqual(result['dequeued'], 1)
        self.assertEqual(result['forced_inactive'], 0)
        self.assertEqual(result['cp_stat_after'], 0)
        self.assertEqual(result['cp_cpc_busy_after'], 0)
        dequeue = fake.events.index(('write', tool.CP_HQD_DEQUEUE_OFFSET, 1))
        halt = fake.events.index(('write', tool.CP_MEC_CNTL_OFFSET, tool.CP_MEC_HALT_MASK))
        self.assertLess(dequeue, halt)
        rb_stop = fake.events.index(('write', tool.SDMA0_GFX_RB_CNTL_OFFSET, 0))
        ib_stop = fake.events.index(('write', tool.SDMA0_GFX_IB_CNTL_OFFSET, 0))
        sdma_halt = fake.events.index(('write', tool.SDMA0_F32_CNTL_OFFSET,
                                      tool.SDMA_HALT_MASK))
        self.assertLess(dequeue, rb_stop)
        self.assertLess(rb_stop, ib_stop)
        self.assertLess(ib_stop, sdma_halt)
        self.assertLess(sdma_halt, halt)
        self.assertEqual(fake.registers[tool.CP_ME_CNTL_OFFSET] & tool.CP_ME_HALT_MASK,
                         tool.CP_ME_HALT_MASK)
        self.assertEqual(fake.registers[tool.SDMA0_F32_CNTL_OFFSET] & tool.SDMA_HALT_MASK, 1)

    def test_gc_quiesce_force_clears_stuck_hqd_only_after_mec_halt(self):
        tool = self.tool

        class StuckTransport(FakeTransport):
            def __init__(self):
                super().__init__(tool)
                self.selector = 0
                self.target = tool.queue_selector(2, 3, 6)
                self.active = 1

            def read32(self, offset):
                if offset == tool.CP_HQD_ACTIVE_OFFSET and self.selector == self.target:
                    return self.active
                return super().read32(offset)

            def write32(self, offset, value):
                if offset == tool.GRBM_GFX_CNTL_OFFSET:
                    self.selector = value
                if (offset == tool.CP_HQD_ACTIVE_OFFSET and value == 0 and
                        self.selector == self.target):
                    self.active = 0
                super().write32(offset, value)

        fake = StuckTransport()
        result = tool.quiesce_gc(fake, sleep=lambda _:None, polls=2)
        self.assertEqual(result['dequeue_timeouts'], 1)
        self.assertEqual(result['forced_inactive'], 1)
        halt = fake.events.index(('write', tool.CP_MEC_CNTL_OFFSET, tool.CP_MEC_HALT_MASK))
        clear = fake.events.index(('write', tool.CP_HQD_ACTIVE_OFFSET, 0))
        self.assertLess(halt, clear)

    def test_forced_hqd_clear_cannot_authorize_warm_reuse(self):
        tool = self.tool
        receipt = {
            'schema':2, 'status':'recovered', 'authorizes_launch':False,
            'boot_id':'boot-A',
            'prior_run_id':'a'*32, 'recovery_id':'b'*32,
            'device':'0000:7b:00.0', 'iommu_group':'31', 'driver':'vfio-pci',
            'pci_command_before':3, 'pci_command_after':3,
            'reset_methods_before':[], 'reset_methods_after':[], 'kernel_messages':[],
            'gc_quiesce':{'status':'quiesced', 'active_after':0,
                          'dequeue_timeouts':1, 'forced_inactive':1,
                          'cp_stat_after':0, 'cp_cpc_busy_after':0,
                          'cp_me_after':tool.CP_ME_HALT_MASK,
                          'cp_mec_after':tool.CP_MEC_HALT_MASK,
                          'sdma0_after':tool.SDMA_HALT_MASK},
            'commands':[{'command':tool.DESTROY_RINGS,
                         'response':tool.READY_FLAG|tool.DESTROY_RINGS,
                         'confirmed':True},
                        {'command':tool.DESTROY_GPCOM_RING,
                         'response':tool.READY_FLAG|tool.DESTROY_GPCOM_RING,
                         'confirmed':True}]}
        experiment_path = ROOT/'tools/experiment.py'
        spec = importlib.util.spec_from_file_location('experiment_for_recovery', experiment_path)
        experiment = importlib.util.module_from_spec(spec); spec.loader.exec_module(experiment)
        self.assertIn('recovery_receipt', experiment.validate_recovery_receipt(
            receipt, 'boot-A', 'a'*32))

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
        for mode in ('bus-master', 'fault', 'implicit-reset'):
            with self.subTest(mode=mode):
                fake = FakeTransport(self.tool)
                states = iter([self.state(), self.state(pci_command=7) if mode == 'bus-master'
                               else self.state()])
                if mode == 'fault':
                    kernel = lambda cursor=None: ('cursor-2', ['IO_PAGE_FAULT'], ['IO_PAGE_FAULT'])
                elif mode == 'implicit-reset':
                    kernel = lambda cursor=None: (
                        'cursor-2', ['vfio-pci 0000:7b:00.0: resetting',
                                     'vfio-pci 0000:7b:00.0: reset done'], [])
                else:
                    kernel = lambda cursor=None: ('cursor-2', [], [])
                with self.assertRaises(self.tool.RecoveryError):
                    self.tool.perform_recovery('boot-A', 'c'*32, lambda:next(states),
                                               lambda:fake, kernel, sleep=lambda _:None)

    def test_nonidle_cp_is_preserved_as_non_authorizing_evidence(self):
        fake = FakeTransport(self.tool)
        fake.registers[self.tool.CP_STAT_OFFSET] = 0x80008200
        fake.registers[self.tool.CP_CPC_BUSY_STAT_OFFSET] = 0x08080000
        states = iter([self.state(), self.state()])
        evidence = self.tool.perform_recovery(
            'boot-A', 'c'*32, lambda:next(states), lambda:fake,
            lambda cursor=None:('cursor-2', [], []), sleep=lambda _:None)
        self.assertEqual(evidence['status'], 'incomplete')
        self.assertFalse(evidence['authorizes_launch'])
        self.assertEqual(evidence['gc_quiesce']['cp_stat_after'], 0x80008200)
        self.assertEqual(evidence['gc_quiesce']['cp_cpc_busy_after'], 0x08080000)

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

    def test_cleanup_still_runs_at_launch_ceiling(self):
        with tempfile.TemporaryDirectory() as temp:
            vm = Path(temp); (vm/'run/used-gpu-boots').mkdir(parents=True)
            prior = 'c'*32
            ledger = {'boot_id':'boot-A', 'launches':[
                {'run_id':'a'*32}, {'run_id':'b'*32}, {'run_id':prior}]}
            (vm/'run/used-gpu-boots/boot-A.json').write_text(json.dumps(ledger))
            fake = FakeTransport(self.tool)
            states = iter([self.state(), self.state(), self.state()])
            with patch.object(self.tool, 'host_state', side_effect=lambda:next(states)), \
                 patch.object(self.tool, 'LegacyVfio', return_value=fake), \
                 patch.object(self.tool, 'kernel_updates', side_effect=[
                     ('cursor-1', [], []), ('cursor-2', [], [])]):
                receipt = self.tool.recover(vm, prior)
            self.assertEqual(receipt['status'], 'recovered')
            self.assertTrue((vm/'run/vfio-recovery/boot-A'/(prior+'.json')).exists())


if __name__ == '__main__':
    unittest.main()
