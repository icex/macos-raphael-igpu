import copy
import importlib.util
import json
from pathlib import Path
import struct
import unittest
from unittest.mock import patch

from tests.test_vfio_recover import FakeTransport, RUN_ID, load_tool

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/stopped-wptr-clear-schema6-positive.json'


class StoppedWptrRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool()

    def _host_kiq_registers(self):
        tool = self.tool
        return {
            tool.GCMC_VM_FB_LOCATION_BASE_OFFSET: 0xf400,
            tool.GCMC_VM_FB_LOCATION_TOP_OFFSET: 0xf41f,
            tool.GCMC_VM_FB_OFFSET_OFFSET: 0x840,
            tool.CP_RB_ACTIVE_OFFSET: 1,
            tool.CP_RB_DOORBELL_CONTROL_OFFSET: 0xc0000400,
            tool.CP_RB0_WPTR_OFFSET: 0x80,
            tool.CP_RB0_BASE_OFFSET: 0x00bfe000,
            tool.CP_RB0_BASE_HI_OFFSET: 0xf4,
            tool.CP_RB0_CNTL_OFFSET: 0x00a00e10,
        }

    def test_native_bar5_store_avoids_struct_pack_into_prezero(self):
        tool = self.tool
        target = bytearray(b'\xaa\xbb\xcc\xdd')
        observed = []

        class Value:
            def __index__(self):
                observed.append(bytes(target))
                return 0x12345678

        struct.pack_into('<I', target, 0, Value())
        self.assertEqual(observed, [b'\0\0\0\0'])

        transport = tool.LegacyVfio()
        transport.bar = bytearray(0x100)
        events = []
        with patch.object(tool, '_store_mmio_u32',
                          side_effect=lambda bar, offset, value:
                          events.append(('native-store', offset, value))), \
             patch.object(transport, 'posted_barrier',
                          side_effect=lambda: events.append('posted')):
            transport.write32(0x20, 0x12345678)
        self.assertEqual(events, [
            ('native-store', 0x20, 0x12345678), 'posted'])

    def test_hdp_flush_uses_native_bar5_store_before_posting_barrier(self):
        tool = self.tool
        transport = tool.LegacyVfio()
        transport.bar = bytearray(tool.HDP_MEM_FLUSH_REMAP_OFFSET + 4)
        events = []
        with patch.object(transport, 'read32',
                          return_value=tool.HDP_MEM_FLUSH_NATIVE_OFFSET), \
             patch.object(tool, '_store_mmio_u32',
                          side_effect=lambda bar, offset, value:
                          events.append(('native-store', offset, value))), \
             patch.object(transport, 'posted_barrier',
                          side_effect=lambda: events.append('posted') or
                          tool.EXPECTED_CONFIG_MEMSIZE):
            result = transport.flush_hdp()
        self.assertEqual(events, [
            ('native-store', tool.HDP_MEM_FLUSH_NATIVE_OFFSET, 0), 'posted'])
        self.assertEqual(result, {
            'remap': tool.HDP_MEM_FLUSH_NATIVE_OFFSET,
            'posted_read': tool.EXPECTED_CONFIG_MEMSIZE})

    def _failed_host_kiq(self):
        return copy.deepcopy(json.loads(FIXTURE.read_text())[
            'gc_quiesce']['host_kiq'])

    def _stopped_transport(self):
        tool = self.tool

        class StoppedTransport(FakeTransport):
            def __init__(self):
                super().__init__(tool)
                self.selector = 0
                self.queues = {}
                for me in (1, 2):
                    for pipe in range(4):
                        for queue in range(8):
                            selector = tool.queue_selector(me, pipe, queue)
                            self.queues[selector] = {
                                'active': 0, 'doorbell': 0, 'dequeue': 0,
                                'rptr': 0, 'wptr_lo': 0, 'wptr_hi': 0,
                            }
                self.queues[tool.HOST_KIQ_SELECTOR]['wptr_lo'] = \
                    tool.HOST_KIQ_RING_USED_DWORDS
                self.registers.update({
                    tool.CP_STAT_OFFSET: 0,
                    tool.CP_CPC_BUSY_STAT_OFFSET: 0,
                    tool.CP_ME_CNTL_OFFSET: tool.CP_ME_HALT_MASK,
                    tool.CP_MEC_CNTL_OFFSET: tool.CP_MEC_HALT_MASK,
                    tool.CP_PQ_WPTR_POLL_CNTL_OFFSET: 0,
                    tool.CP_PQ_STATUS_OFFSET: 0,
                    tool.CP_MEC_DOORBELL_RANGE_LOWER_OFFSET: 0,
                    tool.CP_MEC_DOORBELL_RANGE_UPPER_OFFSET: 0,
                    tool.SDMA0_CNTL_OFFSET: 0,
                    tool.SDMA0_F32_CNTL_OFFSET: tool.SDMA_HALT_MASK,
                    tool.SDMA0_STATUS_REG_OFFSET: tool.SDMA_STATUS_IDLE_MASK,
                    tool.SDMA0_GFX_RB_CNTL_OFFSET: 0,
                    tool.SDMA0_GFX_IB_CNTL_OFFSET: 0,
                    tool.SDMA0_PAGE_RB_CNTL_OFFSET: 0x80840020,
                    tool.SDMA0_PAGE_IB_CNTL_OFFSET: 0x100,
                })
                for offset in (*tool.SDMA0_RLC_RB_CNTL_OFFSETS,
                               *tool.SDMA0_RLC_IB_CNTL_OFFSETS):
                    self.registers[offset] = 0

            def _queue(self):
                return self.queues.setdefault(self.selector, {
                    'active': 0, 'doorbell': 0, 'dequeue': 0,
                    'rptr': 0, 'wptr_lo': 0, 'wptr_hi': 0})

            def read32(self, offset):
                fields = {
                    tool.CP_HQD_ACTIVE_OFFSET: 'active',
                    tool.CP_HQD_PQ_DOORBELL_OFFSET: 'doorbell',
                    tool.CP_HQD_DEQUEUE_OFFSET: 'dequeue',
                    tool.CP_HQD_PQ_RPTR_OFFSET: 'rptr',
                    tool.CP_HQD_PQ_WPTR_LO_OFFSET: 'wptr_lo',
                    tool.CP_HQD_PQ_WPTR_HI_OFFSET: 'wptr_hi',
                }
                if offset in fields:
                    self.events.append(('read', offset))
                    return self._queue()[fields[offset]]
                return super().read32(offset)

            def write32(self, offset, value):
                if offset == tool.GRBM_GFX_CNTL_OFFSET:
                    self.selector = value
                fields = {
                    tool.CP_HQD_ACTIVE_OFFSET: 'active',
                    tool.CP_HQD_PQ_DOORBELL_OFFSET: 'doorbell',
                    tool.CP_HQD_DEQUEUE_OFFSET: 'dequeue',
                    tool.CP_HQD_PQ_RPTR_OFFSET: 'rptr',
                    tool.CP_HQD_PQ_WPTR_LO_OFFSET: 'wptr_lo',
                    tool.CP_HQD_PQ_WPTR_HI_OFFSET: 'wptr_hi',
                }
                if offset in fields:
                    self._queue()[fields[offset]] = value
                super().write32(offset, value)

            def ring_doorbell64(self, index, value):
                self.events.append(('doorbell64', index, value))
                if (index == 0 and value == 0 and
                        self.selector == tool.HOST_KIQ_SELECTOR and
                        self._queue()['doorbell'] & tool.CP_RB_DOORBELL_ENABLE_MASK and
                        self.registers[tool.CP_PQ_STATUS_OFFSET] &
                            tool.CP_PQ_DOORBELL_ENABLE_MASK):
                    self._queue()['wptr_lo'] = 0
                    self._queue()['doorbell'] |= tool.CP_RB_DOORBELL_HIT_MASK
                    self.registers[tool.CP_PQ_STATUS_OFFSET] |= 1

        return StoppedTransport()

    def _integrated_transport(self, *, fail_postscan=False):
        tool = self.tool
        base = self._stopped_transport()
        owner = self

        class StickyIntegrated(type(base)):
            def __init__(self):
                super().__init__()
                self.executed = False
                self.zero_doorbell_completed = False
                self.postscan_failed = False
                self.registers.update(owner._host_kiq_registers())

            def read32(self, offset):
                if (fail_postscan and self.zero_doorbell_completed and
                        not self.postscan_failed and offset == tool.CP_STAT_OFFSET):
                    self.postscan_failed = True
                    raise tool.RecoveryError('injected post-scan read failure')
                return super().read32(offset)

            def write32(self, offset, value):
                if (self.executed and self.selector == tool.HOST_KIQ_SELECTOR and
                        offset == tool.CP_HQD_PQ_WPTR_LO_OFFSET and value == 0):
                    self.events.append(('write-ignored', offset, value))
                    return
                if (offset == tool.CP_HQD_DEQUEUE_OFFSET and value == 1 and
                        self.selector == tool.HOST_KIQ_SELECTOR):
                    self._queue()['active'] = 0
                super().write32(offset, value)

            def ring_doorbell64(self, index, value):
                self.events.append(('doorbell64', index, value))
                if value == tool.HOST_KIQ_RING_USED_DWORDS:
                    self.executed = True
                    sequence = self.read_vram32(
                        tool.HOST_KIQ_RING_OFFSET +
                        tool.HOST_KIQ_FENCE_SEQUENCE_DWORD * 4)
                    self.write_vram(tool.HOST_KIQ_RPTR_OFFSET,
                                    struct.pack('<I', value))
                    self.write_vram(tool.HOST_KIQ_FENCE_OFFSET,
                                    struct.pack('<I', sequence))
                    self._queue()['rptr'] = value
                    self._queue()['wptr_lo'] = value
                    self.registers[tool.CP_RB_ACTIVE_OFFSET] = 0
                elif value == 0:
                    self.zero_doorbell_completed = True
                    self._queue()['wptr_lo'] = 0
                    self._queue()['doorbell'] |= tool.CP_RB_DOORBELL_HIT_MASK
                    self.registers[tool.CP_PQ_STATUS_OFFSET] |= 1

        return StickyIntegrated()

    def _host_state(self):
        return dict(boot_id='boot-A', active_vm=False,
                    device=self.tool.DEVICE_ID, driver='vfio-pci',
                    iommu_group='31', pci_command=3, reset_methods=[],
                    qemu_processes=[], launch_units=[], watchdog_units=[],
                    watchdog_processes=[])

    def test_successful_retirement_survives_sole_cleanup_wptr_failure(self):
        tool = self.tool

        class StickyCleanupWptr(FakeTransport):
            def __init__(self):
                super().__init__(tool)
                self.selector = 0
                self.hqd_active = 0
                self.wptr_zero_writes = 0

            def read32(self, offset):
                if offset == tool.CP_HQD_ACTIVE_OFFSET:
                    value = self.hqd_active if self.selector == tool.HOST_KIQ_SELECTOR else 0
                    self.events.append(('read', offset))
                    return value
                if (offset == tool.CP_HQD_PQ_RPTR_OFFSET and
                        self.selector == tool.HOST_KIQ_SELECTOR):
                    self.events.append(('read', offset))
                    return 0
                if (offset == tool.CP_HQD_PQ_WPTR_LO_OFFSET and
                        self.selector == tool.HOST_KIQ_SELECTOR and
                        self.wptr_zero_writes >= 2):
                    self.events.append(('read', offset))
                    return tool.HOST_KIQ_RING_USED_DWORDS
                return super().read32(offset)

            def write32(self, offset, value):
                if offset == tool.GRBM_GFX_CNTL_OFFSET:
                    self.selector = value
                if (offset == tool.CP_HQD_ACTIVE_OFFSET and
                        self.selector == tool.HOST_KIQ_SELECTOR):
                    self.hqd_active = value & 1
                if (offset == tool.CP_HQD_DEQUEUE_OFFSET and value == 1 and
                        self.selector == tool.HOST_KIQ_SELECTOR):
                    self.hqd_active = 0
                if (offset == tool.CP_HQD_PQ_WPTR_LO_OFFSET and value == 0 and
                        self.selector == tool.HOST_KIQ_SELECTOR):
                    self.wptr_zero_writes += 1
                super().write32(offset, value)

            def ring_doorbell64(self, index, value):
                self.events.append(('doorbell64', index, value))
                sequence = self.read_vram32(
                    tool.HOST_KIQ_RING_OFFSET +
                    tool.HOST_KIQ_FENCE_SEQUENCE_DWORD * 4)
                self.write_vram(tool.HOST_KIQ_RPTR_OFFSET,
                                struct.pack('<I', value))
                self.write_vram(tool.HOST_KIQ_FENCE_OFFSET,
                                struct.pack('<I', sequence))
                self.registers[tool.CP_RB_ACTIVE_OFFSET] = 0

        fake = StickyCleanupWptr()
        fake.registers.update(self._host_kiq_registers())
        with self.assertRaisesRegex(
                tool.RecoveryError,
                'host KIQ cleanup failed.*wptr did not clear') as raised:
            tool.retire_legacy_gfx_with_host_kiq(
                fake, RUN_ID, sleep=lambda _: None, polls=2)

        evidence = raised.exception.evidence
        retired = evidence['retired_before_cleanup']
        self.assertEqual(retired['status'], 'retired')
        self.assertEqual(retired['packet_dwords'], tool.HOST_KIQ_RING_USED_DWORDS)
        self.assertEqual(retired['fence_after'], retired['fence_sequence'])
        self.assertEqual(retired['graphics_pipes_after_unmap']['pipes'][0]['active'], 0)
        self.assertEqual(evidence['activation_readback'], 1)
        self.assertEqual(evidence['dequeue']['write_value'], 1)
        self.assertTrue(evidence['dequeue']['observed_inactive'])
        self.assertEqual(evidence['dequeue']['active_samples'][-1], 0)
        self.assertEqual(evidence['cleanup']['errors'], [
            'verify host KIQ wptr clear: RecoveryError: '
            'host KIQ wptr did not clear'])

    def test_stopped_proof_uses_one_zero_doorbell_and_closes_ingress(self):
        tool = self.tool
        fake = self._stopped_transport()
        ticks = iter((100, 200, 300, 400))

        result = tool.clear_stopped_host_kiq_wptr(
            fake, self._failed_host_kiq(), forced_inactive=0,
            clock_ns=lambda: next(ticks))

        self.assertEqual(result['status'], 'cleared')
        self.assertTrue(result['eligibility']['eligible'])
        self.assertEqual([event for event in fake.events
                          if isinstance(event, tuple) and
                          event[0] == 'doorbell64'], [('doorbell64', 0, 0)])
        target = result['after']['passes'][0]['host_kiq']
        self.assertEqual((target['wptr_lo'], target['wptr_hi']), (0, 0))
        self.assertEqual(result['before']['passes'][0]['host_kiq']['wptr_lo'],
                         tool.HOST_KIQ_RING_USED_DWORDS)
        self.assertEqual(result['transition']['gate_close']['global']['written'] &
                         tool.CP_PQ_DOORBELL_ENABLE_MASK, 0)
        self.assertEqual(result['transition']['gate_close']['hqd']['written'] &
                         tool.CP_RB_DOORBELL_ENABLE_MASK, 0)
        close_global = fake.events.index(
            ('write', tool.CP_PQ_STATUS_OFFSET, 1))
        close_hqd = fake.events.index(
            ('write', tool.CP_HQD_PQ_DOORBELL_OFFSET,
             tool.CP_RB_DOORBELL_HIT_MASK))
        self.assertLess(close_global, close_hqd)

    def test_missing_original_fence_is_ineligible_without_doorbell_write(self):
        host_kiq = self._failed_host_kiq()
        host_kiq['evidence']['terminal_poll']['fence'] = 0
        fake = self._stopped_transport()

        result = self.tool.clear_stopped_host_kiq_wptr(
            fake, host_kiq, forced_inactive=0)

        self.assertEqual(result['status'], 'ineligible')
        self.assertFalse(result['eligibility']['eligible'])
        self.assertIn('terminal fence', result['eligibility']['errors'])
        self.assertFalse(any(isinstance(event, tuple) and
                             event[0] == 'doorbell64' for event in fake.events))
        self.assertFalse(any(isinstance(event, tuple) and event[:2] in (
            ('write', self.tool.CP_PQ_STATUS_OFFSET),
            ('write', self.tool.CP_HQD_PQ_DOORBELL_OFFSET))
                             for event in fake.events))

    def test_inaccessible_activation_is_ineligible_before_stopped_scan(self):
        host_kiq = self._failed_host_kiq()
        host_kiq['evidence']['activation_readback'] = 0xffffffff
        fake = self._stopped_transport()

        result = self.tool.clear_stopped_host_kiq_wptr(
            fake, host_kiq, forced_inactive=0)

        self.assertEqual(result['status'], 'ineligible')
        self.assertIn('host KIQ activation', result['eligibility']['errors'])
        self.assertEqual(fake.events, [])

    def test_dequeue_other_cleanup_and_forced_paths_never_ring_zero_doorbell(self):
        cases = []
        missing_dequeue = self._failed_host_kiq()
        missing_dequeue['evidence']['dequeue']['observed_inactive'] = False
        cases.append(('dequeue', missing_dequeue, 0))
        other_cleanup = self._failed_host_kiq()
        other_cleanup['evidence']['cleanup']['errors'].append(
            'verify host KIQ inactive: RecoveryError: active did not clear')
        cases.append(('other-cleanup', other_cleanup, 0))
        cases.append(('forced', self._failed_host_kiq(), 1))

        for label, host_kiq, forced in cases:
            with self.subTest(label=label):
                fake = self._stopped_transport()
                result = self.tool.clear_stopped_host_kiq_wptr(
                    fake, host_kiq, forced_inactive=forced)
                self.assertEqual(result['status'], 'ineligible')
                self.assertFalse(any(isinstance(event, tuple) and
                                     event[0] == 'doorbell64'
                                     for event in fake.events))
                self.assertFalse(any(isinstance(event, tuple) and event[:2] in (
                    ('write', self.tool.CP_PQ_STATUS_OFFSET),
                    ('write', self.tool.CP_HQD_PQ_DOORBELL_OFFSET))
                                     for event in fake.events))

    def test_active_stopped_scan_refuses_before_ingress_mutation(self):
        tool = self.tool
        fake = self._stopped_transport()
        fake.queues[tool.queue_selector(1, 2, 3)]['active'] = 1

        result = tool.clear_stopped_host_kiq_wptr(
            fake, self._failed_host_kiq(), forced_inactive=0)

        self.assertEqual(result['status'], 'failed')
        self.assertIn('HQD proof', result['error'])
        self.assertFalse(any(isinstance(event, tuple) and
                             event[0] == 'doorbell64' for event in fake.events))
        self.assertFalse(any(isinstance(event, tuple) and event[:2] in (
            ('write', tool.CP_PQ_STATUS_OFFSET),
            ('write', tool.CP_HQD_PQ_DOORBELL_OFFSET)) for event in fake.events))

    def test_prescan_read_failure_preserves_progressive_hqd_row(self):
        tool = self.tool
        base = self._stopped_transport()

        class ReadFailure(type(base)):
            def __init__(self):
                super().__init__()
                self.doorbell_reads = 0

            def read32(self, offset):
                if offset == tool.CP_HQD_PQ_DOORBELL_OFFSET:
                    self.doorbell_reads += 1
                    if self.doorbell_reads == 5:
                        raise tool.RecoveryError('injected scan read failure')
                return super().read32(offset)

        fake = ReadFailure()
        result = tool.clear_stopped_host_kiq_wptr(
            fake, self._failed_host_kiq(), forced_inactive=0)

        self.assertEqual(result['status'], 'failed')
        rows = result['before']['passes'][0]['compute']
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[-1]['active'], 0)
        self.assertNotIn('doorbell_control', rows[-1])
        self.assertIn('injected scan read failure', result['error'])

    def test_failed_hqd_enable_readback_preserves_row_and_closes_both_gates(self):
        tool = self.tool
        base = self._stopped_transport()

        class FailHqdEnableReadback(type(base)):
            def __init__(self):
                super().__init__()
                self.hqd_reads = 0

            def read32(self, offset):
                if (offset == tool.CP_HQD_PQ_DOORBELL_OFFSET and
                        self.selector == tool.HOST_KIQ_SELECTOR and
                        self._queue()['doorbell'] & tool.CP_RB_DOORBELL_ENABLE_MASK):
                    self.hqd_reads += 1
                    if self.hqd_reads == 1:
                        raise tool.RecoveryError('injected HQD posting failure')
                return super().read32(offset)

        fake = FailHqdEnableReadback()
        result = tool.clear_stopped_host_kiq_wptr(
            fake, self._failed_host_kiq(), forced_inactive=0)

        self.assertEqual(result['status'], 'failed')
        enable = result['transition']['hqd_enable']
        self.assertTrue(enable['attempted'])
        self.assertFalse(enable['completed'])
        self.assertIn('injected HQD posting failure', enable['error'])
        self.assertIsNotNone(result['transition']['gate_close']['global'])
        self.assertIsNotNone(result['transition']['gate_close']['hqd'])
        self.assertEqual(fake._queue()['doorbell'] &
                         tool.CP_RB_DOORBELL_ENABLE_MASK, 0)
        self.assertEqual(fake.registers[tool.CP_PQ_STATUS_OFFSET] &
                         tool.CP_PQ_DOORBELL_ENABLE_MASK, 0)
        self.assertEqual(fake.selector, 0)

    def test_changed_hqd_preimage_refuses_before_enabling_ingress(self):
        tool = self.tool
        base = self._stopped_transport()

        class ChangedPreimage(type(base)):
            def __init__(self):
                super().__init__()
                self.selector_writes = 0

            def write32(self, offset, value):
                if offset == tool.GRBM_GFX_CNTL_OFFSET:
                    self.selector_writes += 1
                super().write32(offset, value)

            def read32(self, offset):
                if (offset == tool.CP_HQD_PQ_DOORBELL_OFFSET and
                        self.selector == tool.HOST_KIQ_SELECTOR and
                        self.selector_writes >= 132):
                    self.events.append(('read', offset))
                    return 4
                return super().read32(offset)

        fake = ChangedPreimage()
        result = tool.clear_stopped_host_kiq_wptr(
            fake, self._failed_host_kiq(), forced_inactive=0)

        self.assertEqual(result['status'], 'failed')
        self.assertIn('preimage changed', result['error'])
        hqd_writes = [event for event in fake.events
                      if isinstance(event, tuple) and
                      event[:2] == ('write', tool.CP_HQD_PQ_DOORBELL_OFFSET)]
        self.assertEqual(hqd_writes, [])
        self.assertFalse(any(isinstance(event, tuple) and event[0] == 'doorbell64'
                             for event in fake.events))
        self.assertEqual(fake.selector, 0)

    def test_global_close_read_failure_still_writes_known_clear_and_closes_hqd(self):
        tool = self.tool
        base = self._stopped_transport()

        class FailGlobalCloseRead(type(base)):
            def __init__(self):
                super().__init__()
                self.pq_reads = 0

            def read32(self, offset):
                if offset == tool.CP_PQ_STATUS_OFFSET:
                    self.pq_reads += 1
                    if self.pq_reads == 5:
                        raise tool.RecoveryError('injected global close read failure')
                return super().read32(offset)

        fake = FailGlobalCloseRead()
        result = tool.clear_stopped_host_kiq_wptr(
            fake, self._failed_host_kiq(), forced_inactive=0)

        self.assertEqual(result['status'], 'failed')
        global_close = result['transition']['gate_close']['global']
        self.assertTrue(global_close['attempted'])
        self.assertIn('injected global close read failure',
                      global_close['anomalies'][0])
        self.assertEqual(global_close['written'] &
                         tool.CP_PQ_DOORBELL_ENABLE_MASK, 0)
        self.assertTrue(global_close['completed'])
        self.assertTrue(result['transition']['gate_close']['hqd']['attempted'])
        self.assertEqual(fake.registers[tool.CP_PQ_STATUS_OFFSET] &
                         tool.CP_PQ_DOORBELL_ENABLE_MASK, 0)
        self.assertEqual(fake._queue()['doorbell'] &
                         tool.CP_RB_DOORBELL_ENABLE_MASK, 0)
        self.assertEqual(fake.selector, 0)

    def test_global_close_posting_failure_does_not_skip_hqd_close_or_default(self):
        tool = self.tool
        base = self._stopped_transport()

        class FailGlobalClosePosting(type(base)):
            def __init__(self):
                super().__init__()
                self.pq_reads = 0

            def read32(self, offset):
                if offset == tool.CP_PQ_STATUS_OFFSET:
                    self.pq_reads += 1
                    if self.pq_reads == 6:
                        raise tool.RecoveryError(
                            'injected global close posting failure')
                return super().read32(offset)

        fake = FailGlobalClosePosting()
        result = tool.clear_stopped_host_kiq_wptr(
            fake, self._failed_host_kiq(), forced_inactive=0)

        self.assertEqual(result['status'], 'failed')
        global_close = result['transition']['gate_close']['global']
        self.assertTrue(global_close['attempted'])
        self.assertFalse(global_close['completed'])
        self.assertIn('injected global close posting failure',
                      global_close['error'])
        self.assertTrue(result['transition']['gate_close']['hqd']['completed'])
        self.assertTrue(result['transition']['final_default']['completed'])
        self.assertEqual(fake.registers[tool.CP_PQ_STATUS_OFFSET] & 2, 0)
        self.assertEqual(fake._queue()['doorbell'] &
                         tool.CP_RB_DOORBELL_ENABLE_MASK, 0)
        self.assertEqual(fake.selector, 0)

    def test_unexpected_global_close_bits_fail_but_clear_both_enable_bits(self):
        tool = self.tool
        base = self._stopped_transport()

        class UnexpectedGlobalBits(type(base)):
            def ring_doorbell64(self, index, value):
                super().ring_doorbell64(index, value)
                self.registers[tool.CP_PQ_STATUS_OFFSET] |= 4

        fake = UnexpectedGlobalBits()
        result = tool.clear_stopped_host_kiq_wptr(
            fake, self._failed_host_kiq(), forced_inactive=0)

        self.assertEqual(result['status'], 'failed')
        global_close = result['transition']['gate_close']['global']
        self.assertEqual(global_close['observed_before'], 7)
        self.assertEqual(global_close['written'], 5)
        self.assertTrue(global_close['anomalies'])
        self.assertEqual(fake.registers[tool.CP_PQ_STATUS_OFFSET] & 2, 0)
        self.assertEqual(fake._queue()['doorbell'] &
                         tool.CP_RB_DOORBELL_ENABLE_MASK, 0)
        self.assertEqual(fake.selector, 0)

    def test_clear_validator_rejects_gate_open_timing_over_two_ms(self):
        tool = self.tool
        fake = self._stopped_transport()
        result = tool.clear_stopped_host_kiq_wptr(
            fake, self._failed_host_kiq(), forced_inactive=0,
            clock_ns=lambda: 0)
        self.assertEqual(result['status'], 'cleared')
        result['transition']['timing']['through_global_close_ns'] = \
            tool.STOPPED_WPTR_OBSERVATION_BUDGET_NS + 1
        self.assertFalse(tool.valid_stopped_host_kiq_wptr_clear(
            result, self._failed_host_kiq(), 0))

    def test_normal_recovery_authorizes_only_after_integrated_stopped_clear(self):
        tool = self.tool
        fake = self._integrated_transport()
        state = self._host_state()
        states = iter((state, dict(state)))

        result = tool.perform_recovery(
            'boot-A', RUN_ID, lambda: next(states), lambda: fake,
            lambda cursor=None: ('cursor-2', [], []),
            sleep=lambda _: None, polls=2)

        self.assertEqual(result['status'], 'recovered')
        self.assertTrue(result['authorizes_launch'])
        gc = result['gc_quiesce']
        self.assertEqual(gc['host_kiq']['status'], 'failed')
        self.assertEqual(gc['stopped_wptr_doorbell_clear']['status'], 'cleared')
        self.assertTrue(gc['gfx_retirement_confirmed'])
        self.assertEqual([event for event in fake.events
                          if isinstance(event, tuple) and
                          event[0] == 'doorbell64'], [
            ('doorbell64', 0, tool.HOST_KIQ_RING_USED_DWORDS),
            ('doorbell64', 0, 0),
        ])
        proof_path = ROOT / 'tools/kiq-recovery-proof.py'
        spec = importlib.util.spec_from_file_location(
            'kiq_recovery_proof_producer_chain', proof_path)
        proof = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(proof)
        derived, errors = proof.derive_effective_host_kiq(result)
        self.assertEqual(errors, [])
        self.assertEqual(derived['source'], 'stopped_wptr_doorbell_clear')
        self.assertEqual(derived['host_kiq']['status'], 'retired')
        self.assertEqual(result['gc_quiesce']['host_kiq']['status'], 'failed')

    def test_postscan_read_failure_survives_full_recovery_and_psp_teardown(self):
        tool = self.tool
        fake = self._integrated_transport(fail_postscan=True)
        state = self._host_state()
        states = iter((state, dict(state)))

        result = tool.perform_recovery(
            'boot-A', RUN_ID, lambda: next(states), lambda: fake,
            lambda cursor=None: ('cursor-2', [], []),
            sleep=lambda _: None, polls=2)

        self.assertEqual(result['status'], 'incomplete')
        self.assertFalse(result['authorizes_launch'])
        proof = result['gc_quiesce']['stopped_wptr_doorbell_clear']
        self.assertEqual(proof['status'], 'failed')
        self.assertIn('injected post-scan read failure', proof['error'])
        self.assertIsInstance(proof['after'], dict)
        self.assertEqual([row['command'] for row in result['commands']], [
            tool.DESTROY_RINGS, tool.DESTROY_GPCOM_RING])
        derived, errors = tool.derive_effective_stopped_host_kiq(
            result['gc_quiesce'], RUN_ID)
        self.assertIsNone(derived)
        self.assertTrue(errors)


if __name__ == '__main__':
    unittest.main()
