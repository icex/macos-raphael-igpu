import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
RUN_ID = 'a' * 32


def load_tool():
    path = ROOT / 'tools/vfio-recover.py'
    spec = importlib.util.spec_from_file_location('vfio_recover', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeTransport:
    def __init__(self, tool, *, fail_command=None, run_id=RUN_ID):
        self.tool = tool
        self.fail_command = fail_command
        self.events = []
        self.value = 0x80050000
        self.registers = {}
        self.vram = {}
        regions = {
            '0': {'index':0, 'size':0x10000000, 'offset':0 << 40,
                  'read':True, 'write':True, 'mmap':True},
            '2': {'index':2, 'size':0x00200000, 'offset':2 << 40,
                  'read':True, 'write':True, 'mmap':True},
            '5': {'index':5, 'size':0x00080000, 'offset':5 << 40,
                  'read':True, 'write':True, 'mmap':True},
        }
        self.region = dict(regions['5'], regions=regions)
        self.install_reservation(run_id)

    def install_reservation(self, run_id=RUN_ID):
        descriptor = self.tool.host_kiq_reservation_descriptor(
            run_id, self.tool.HOST_KIQ_RESERVATION_ACTIVE)
        self.vram.update((self.tool.HOST_KIQ_RESERVATION_OFFSET+n, value)
                         for n, value in enumerate(descriptor))

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

    def flush_hdp(self):
        self.events.append('hdp-flush')
        return {'remap':self.tool.HDP_MEM_FLUSH_REMAP_OFFSET,
                'posted_read':self.registers.get(
                    self.tool.NBIO_CONFIG_MEMSIZE_OFFSET, 0)}

    def metadata(self):
        return dict(self.region)

    def read_vram32(self, offset):
        return int.from_bytes(bytes(self.vram.get(offset+n, 0) for n in range(4)), 'little')

    def write_vram(self, offset, data):
        self.events.append(('write-vram', offset, len(data)))
        self.vram.update((offset+n, value) for n, value in enumerate(data))

    def ring_doorbell64(self, index, value):
        self.events.append(('doorbell64', index, value))
        sequence = self.read_vram32(
            self.tool.HOST_KIQ_RING_OFFSET + self.tool.HOST_KIQ_FENCE_SEQUENCE_DWORD * 4)
        self.write_vram(self.tool.HOST_KIQ_FENCE_OFFSET,
                        struct.pack('<I', sequence))
        self.registers[self.tool.CP_HQD_PQ_RPTR_OFFSET] = value
        self.registers[self.tool.CP_RB_ACTIVE_OFFSET] = 0


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

    def test_wptr_poll_enable_is_bit_31_and_period_bit_is_preserved(self):
        tool = self.tool
        self.assertEqual(tool.CP_PQ_WPTR_POLL_ENABLE_MASK, 0x80000000)
        fake = FakeTransport(tool)
        fake.registers[tool.CP_PQ_WPTR_POLL_CNTL_OFFSET] = 0x80000001
        result = tool.quiesce_gc(fake, sleep=lambda _:None, polls=2)
        self.assertEqual(result['host_kiq'], {'status':'not-needed'})
        self.assertIn(('write', tool.CP_PQ_WPTR_POLL_CNTL_OFFSET, 1), fake.events)
        self.assertEqual(fake.registers[tool.CP_PQ_WPTR_POLL_CNTL_OFFSET], 1)

    def test_gc_final_state_disables_all_global_compute_queue_gates(self):
        tool = self.tool
        fake = FakeTransport(tool)
        fake.registers.update({
            tool.CP_PQ_WPTR_POLL_CNTL_OFFSET: 0x80000001,
            tool.CP_PQ_STATUS_OFFSET: 0x2,
            tool.CP_MEC_DOORBELL_RANGE_LOWER_OFFSET: 0x11223344,
            tool.CP_MEC_DOORBELL_RANGE_UPPER_OFFSET: 0x55667788,
        })
        result = tool.quiesce_gc(fake, sleep=lambda _:None, polls=2)
        self.assertEqual(result['pq_wptr_poll_after'], 1)
        self.assertEqual(result['pq_status_after'] & tool.CP_PQ_DOORBELL_ENABLE_MASK, 0)
        self.assertEqual(result['doorbell_range_lower_after'], 0)
        self.assertEqual(result['doorbell_range_upper_after'], 0)

    def test_hdp_flush_validates_remap_and_uses_safe_posted_read(self):
        tool = self.tool
        self.assertEqual(tool.HDP_MEM_FLUSH_REMAP_OFFSET, 0x7f000)
        self.assertEqual(tool.NBIO_REMAP_HDP_MEM_FLUSH_OFFSET,
                         (0xd20 + 0x12d) * 4)
        self.assertEqual(tool.NBIO_CONFIG_MEMSIZE_OFFSET, (0xd20 + 0xc3) * 4)
        transport = tool.LegacyVfio()
        transport.bar = bytearray(0x80000)
        struct.pack_into('<I', transport.bar,
                         tool.NBIO_REMAP_HDP_MEM_FLUSH_OFFSET,
                         tool.HDP_MEM_FLUSH_REMAP_OFFSET)
        struct.pack_into('<I', transport.bar, tool.NBIO_CONFIG_MEMSIZE_OFFSET, 0x200)
        evidence = transport.flush_hdp()
        self.assertEqual(evidence, {'remap':0x7f000, 'posted_read':0x200})
        self.assertEqual(struct.unpack_from('<I', transport.bar, 0x7f000)[0], 0)
        struct.pack_into('<I', transport.bar,
                         tool.NBIO_REMAP_HDP_MEM_FLUSH_OFFSET, 0)
        with self.assertRaisesRegex(tool.RecoveryError, 'HDP.*remap'):
            transport.flush_hdp()

    def test_bar2_doorbell_uses_aligned_atomic_u64_store(self):
        tool = self.tool
        storage = bytearray(16)
        tool._store_mmio_u64(storage, 0, 0x1122334455667788)
        self.assertEqual(struct.unpack_from('<Q', storage)[0], 0x1122334455667788)
        with self.assertRaisesRegex(tool.RecoveryError, 'aligned'):
            tool._store_mmio_u64(storage, 4, 1)

    def test_write32_uses_safe_posted_barrier_not_target_register_read(self):
        tool = self.tool
        transport = tool.LegacyVfio()
        transport.bar = bytearray(0x80000)
        struct.pack_into('<I', transport.bar, tool.NBIO_CONFIG_MEMSIZE_OFFSET, 0x200)
        target = tool.CP_HQD_DEQUEUE_OFFSET
        reads = []
        original = transport.read32
        transport.read32 = lambda offset:(reads.append(offset), original(offset))[1]
        transport.write32(target, 1)
        self.assertEqual(reads, [tool.NBIO_CONFIG_MEMSIZE_OFFSET])

    def test_host_kiq_uses_vram_only_and_exact_graphics_unmap_packet(self):
        tool = self.tool
        self.assertEqual(tool.HOST_KIQ_UNMAP_GFX,
                         (0xc004a300, 0x30000000, 0x00000400, 0, 0, 0))
        self.assertEqual(tool.HOST_KIQ_RING_OFFSET, 0x0f100000)
        self.assertEqual(tool.HOST_KIQ_RING_SIZE, 0x10000)
        self.assertGreaterEqual(tool.HOST_KIQ_MQD_OFFSET,
                                tool.HOST_KIQ_RING_OFFSET + tool.HOST_KIQ_RING_SIZE)
        self.assertLessEqual(tool.HOST_KIQ_EOP_OFFSET + tool.HOST_KIQ_EOP_SIZE,
                             tool.VRAM_BAR_SIZE)
        gart_start = 0x0fdfc000
        gart_end = gart_start + 0x200000
        for start, size in tool.host_kiq_scratch_ranges():
            self.assertTrue(start + size <= gart_start or start >= gart_end)
        self.assertNotIn('VFIO_IOMMU_MAP_DMA', vars(tool))

        sequence = 0x13579bdf
        ring, mqd, addresses = tool._host_kiq_image(
            0xf400000000, sequence, 0x400)
        self.assertEqual(struct.unpack_from('<6I', ring), tool.HOST_KIQ_UNMAP_GFX)
        self.assertEqual(struct.unpack_from('<5I', ring, 24),
                         (0xc0033700, 0x00100500,
                          addresses['fence'] & 0xffffffff,
                          addresses['fence'] >> 32, sequence))
        self.assertEqual(struct.unpack_from('<I', ring, 44)[0], tool.HOST_KIQ_NOP)
        self.assertEqual(struct.unpack_from(
            '<I', ring, (tool.HOST_KIQ_RING_USED_DWORDS - 1) * 4)[0],
            tool.HOST_KIQ_NOP)
        self.assertEqual(len(mqd), 0x800)
        self.assertEqual(struct.unpack_from('<I', mqd, 0x200)[0],
                         addresses['mqd'] & 0xfffffffc)
        self.assertEqual(struct.unpack_from('<I', mqd, 0x204)[0],
                         addresses['mqd'] >> 32)
        self.assertEqual(struct.unpack_from('<I', mqd, 0x220)[0],
                         (addresses['ring'] >> 8) & 0xffffffff)
        self.assertEqual(struct.unpack_from('<I', mqd, 0x224)[0],
                         addresses['ring'] >> 40)
        self.assertEqual(struct.unpack_from('<I', mqd, 0x23c)[0], 0x40000000)
        self.assertEqual(struct.unpack_from('<I', mqd, 0x244)[0], 0xd130060d)
        self.assertEqual(tool.CP_PQ_DOORBELL_ENABLE_MASK, 0x2)

    def test_host_kiq_requires_and_consumes_guest_lifetime_reservation(self):
        tool = self.tool
        fake = FakeTransport(tool)
        proof = tool.consume_host_kiq_reservation(fake, RUN_ID)
        self.assertEqual(proof['heap_limit'], tool.HOST_KIQ_HEAP_LIMIT)
        self.assertEqual(proof['scratch_start'], tool.HOST_KIQ_RING_OFFSET)
        self.assertTrue(all(fake.read_vram32(
            tool.HOST_KIQ_RESERVATION_OFFSET+n) == 0
            for n in range(0, tool.HOST_KIQ_RESERVATION_SIZE, 4)))
        with self.assertRaisesRegex(tool.RecoveryError, 'reservation'):
            tool.consume_host_kiq_reservation(fake, RUN_ID)

    def test_stale_reservation_from_another_launch_is_rejected(self):
        tool = self.tool
        fake = FakeTransport(tool, run_id='b' * 32)
        fake.registers.update({
            tool.GCMC_VM_FB_LOCATION_BASE_OFFSET: 0xf400,
            tool.GCMC_VM_FB_LOCATION_TOP_OFFSET: 0xf41f,
            tool.GCMC_VM_FB_OFFSET_OFFSET: 0x840,
            tool.CP_RB_DOORBELL_CONTROL_OFFSET: 0xc0000400,
        })
        with self.assertRaisesRegex(tool.RecoveryError, 'launch nonce'):
            tool.retire_legacy_gfx_with_host_kiq(
                fake, RUN_ID, sleep=lambda _:None, polls=2)
        self.assertFalse(any(isinstance(event, tuple) and event[0] == 'doorbell64'
                             for event in fake.events))

    def test_prelaunch_challenge_is_pending_and_bound_to_run(self):
        tool = self.tool
        fake = FakeTransport(tool)
        evidence = tool.prepare_host_kiq_reservation(fake, RUN_ID)
        expected = tool.host_kiq_reservation_descriptor(
            RUN_ID, tool.HOST_KIQ_RESERVATION_PENDING)
        actual = b''.join(struct.pack('<I', fake.read_vram32(
            tool.HOST_KIQ_RESERVATION_OFFSET+n))
            for n in range(0, tool.HOST_KIQ_RESERVATION_SIZE, 4))
        self.assertEqual(actual, expected)
        self.assertEqual(evidence['run_id'], RUN_ID)
        self.assertEqual(evidence['state'], 'pending')

    def test_forced_allocator_enable_runs_recovery_reservation_wrapper(self):
        source = (ROOT/'src/RaphaelGPU.cpp').read_text()
        start = source.index('static uint32_t wrapHwMemSetVSReady')
        end = source.index('static uint32_t wrapVmmSetVSReady', start)
        body = source[start:end]
        self.assertIn('wrapHwMemEnable(self);', body)
        self.assertNotIn('reinterpret_cast<uint32_t (*)(void *)>(orgHwMemEnable)(self)',
                         body)

    def test_prepare_launch_checks_host_before_and_after_vfio_challenge(self):
        tool = self.tool
        fake = FakeTransport(tool)
        states = iter([self.state(), self.state()])
        evidence = tool.prepare_launch(
            'boot-A', RUN_ID, lambda:next(states), lambda:fake)
        self.assertEqual(evidence['boot_id'], 'boot-A')
        self.assertEqual(evidence['run_id'], RUN_ID)
        self.assertEqual(fake.events[0], 'open')
        self.assertEqual(fake.events[-1], 'close')

    def test_prepare_launch_rejects_post_write_bus_master_enable(self):
        tool = self.tool
        fake = FakeTransport(tool)
        states = iter([self.state(), self.state(pci_command=7)])
        with self.assertRaisesRegex(tool.RecoveryError, 'post-challenge.*bus_master'):
            tool.prepare_launch('boot-A', RUN_ID, lambda:next(states), lambda:fake)

    def test_host_kiq_refuses_absent_or_corrupt_guest_reservation_before_scratch(self):
        tool = self.tool
        for corrupt in (None, 0):
            with self.subTest(corrupt=corrupt):
                fake = FakeTransport(tool)
                fake.vram.clear()
                if corrupt is not None:
                    fake.vram[tool.HOST_KIQ_RESERVATION_OFFSET] = corrupt
                fake.registers.update({
                    tool.GCMC_VM_FB_LOCATION_BASE_OFFSET: 0xf400,
                    tool.GCMC_VM_FB_LOCATION_TOP_OFFSET: 0xf41f,
                })
                with self.assertRaisesRegex(tool.RecoveryError, 'reservation'):
                    tool.retire_legacy_gfx_with_host_kiq(
                        fake, RUN_ID, sleep=lambda _:None, polls=2)
                self.assertFalse(any(isinstance(event, tuple) and event[0] == 'write-vram' and
                                     event[1] >= tool.HOST_KIQ_RING_OFFSET
                                     for event in fake.events))

    def test_host_kiq_rejects_framebuffer_aperture_smaller_than_scratch(self):
        fake = FakeTransport(self.tool)
        fake.registers[self.tool.GCMC_VM_FB_LOCATION_BASE_OFFSET] = 0xf400
        fake.registers[self.tool.GCMC_VM_FB_LOCATION_TOP_OFFSET] = 0xf400
        with self.assertRaisesRegex(self.tool.RecoveryError, 'scratch.*aperture'):
            self.tool.retire_legacy_gfx_with_host_kiq(
                fake, RUN_ID, sleep=lambda _:None, polls=2)

    def test_host_kiq_rejects_runtime_gart_overlap_before_writing_vram(self):
        tool = self.tool
        fake = FakeTransport(tool)
        physical_fb = 0x840000000
        fake.registers.update({
            tool.GCMC_VM_FB_LOCATION_BASE_OFFSET: 0xf400,
            tool.GCMC_VM_FB_LOCATION_TOP_OFFSET: 0xf41f,
            tool.GCMC_VM_FB_OFFSET_OFFSET: physical_fb >> 24,
            tool.GCVM_CONTEXT0_CNTL_OFFSET: 1,
            tool.GCVM_CONTEXT0_PTB_LO_OFFSET:
                (physical_fb + tool.HOST_KIQ_RING_OFFSET) & 0xffffffff | 1,
            tool.GCVM_CONTEXT0_PTB_HI_OFFSET:
                (physical_fb + tool.HOST_KIQ_RING_OFFSET) >> 32,
            tool.GCVM_CONTEXT0_START_LO_OFFSET: 0,
            tool.GCVM_CONTEXT0_END_LO_OFFSET: 0,
        })
        with self.assertRaisesRegex(tool.RecoveryError, 'GART page table'):
            tool.retire_legacy_gfx_with_host_kiq(fake, RUN_ID, sleep=lambda _:None, polls=2)
        self.assertFalse(any(isinstance(event, tuple) and event[0] == 'write-vram' and
                             event[1] >= tool.HOST_KIQ_RING_OFFSET
                             for event in fake.events))

    def test_host_kiq_rejects_untranslatable_enabled_gart_root(self):
        tool = self.tool
        fake = FakeTransport(tool)
        fake.registers.update({
            tool.GCMC_VM_FB_LOCATION_BASE_OFFSET: 0xf400,
            tool.GCMC_VM_FB_LOCATION_TOP_OFFSET: 0xf41f,
            tool.GCMC_VM_FB_OFFSET_OFFSET: 0x840,
            tool.GCVM_CONTEXT0_CNTL_OFFSET: 1,
            tool.GCVM_CONTEXT0_PTB_LO_OFFSET: 0x12345001,
            tool.GCVM_CONTEXT0_PTB_HI_OFFSET: 0x2,
            tool.GCVM_CONTEXT0_START_LO_OFFSET: 0xffbfa00,
            tool.GCVM_CONTEXT0_END_LO_OFFSET: 0xffffe00,
        })
        with self.assertRaisesRegex(tool.RecoveryError, 'translate.*GART'):
            tool.retire_legacy_gfx_with_host_kiq(fake, RUN_ID, sleep=lambda _:None, polls=2)
        self.assertFalse(any(isinstance(event, tuple) and event[0] == 'write-vram' and
                             event[1] >= tool.HOST_KIQ_RING_OFFSET
                             for event in fake.events))

    def test_host_kiq_rejects_nonflat_or_malformed_enabled_gart(self):
        tool = self.tool
        physical_fb = 0x840000000
        cases = (
            ('depth', {tool.GCVM_CONTEXT0_CNTL_OFFSET: 2}),
            ('flags', {tool.GCVM_CONTEXT0_PTB_LO_OFFSET: 3}),
            ('range', {tool.GCVM_CONTEXT0_START_HI_OFFSET: 0x10}),
        )
        for label, change in cases:
            with self.subTest(label=label):
                fake = FakeTransport(tool)
                fake.registers.update({
                    tool.GCMC_VM_FB_LOCATION_BASE_OFFSET: 0xf400,
                    tool.GCMC_VM_FB_LOCATION_TOP_OFFSET: 0xf41f,
                    tool.GCMC_VM_FB_OFFSET_OFFSET: physical_fb >> 24,
                    tool.GCVM_CONTEXT0_CNTL_OFFSET: 1,
                    tool.GCVM_CONTEXT0_PTB_LO_OFFSET: 1,
                    tool.GCVM_CONTEXT0_PTB_HI_OFFSET: physical_fb >> 32,
                    tool.GCVM_CONTEXT0_START_LO_OFFSET: 0,
                    tool.GCVM_CONTEXT0_END_LO_OFFSET: 0,
                })
                fake.registers.update(change)
                with self.assertRaisesRegex(tool.RecoveryError, 'GART'):
                    tool.retire_legacy_gfx_with_host_kiq(
                        fake, RUN_ID, sleep=lambda _:None, polls=2)

    def test_framebuffer_register_fields_are_masked_to_24_bits(self):
        tool = self.tool
        fake = FakeTransport(tool)
        fake.registers.update({
            tool.GCMC_VM_FB_LOCATION_BASE_OFFSET: 0xab00f400,
            tool.GCMC_VM_FB_LOCATION_TOP_OFFSET: 0xcd00f41f,
        })
        self.assertEqual(tool._framebuffer_aperture(fake),
                         (0xf400000000, 0x20000000))

    def test_host_kiq_requires_the_measured_graphics_doorbell_offset(self):
        tool = self.tool
        fake = FakeTransport(tool)
        fake.registers.update({
            tool.GCMC_VM_FB_LOCATION_BASE_OFFSET: 0xf400,
            tool.GCMC_VM_FB_LOCATION_TOP_OFFSET: 0xf41f,
            tool.CP_RB_DOORBELL_CONTROL_OFFSET: 0x40000800,
        })
        with self.assertRaisesRegex(tool.RecoveryError, 'graphics doorbell offset'):
            tool.retire_legacy_gfx_with_host_kiq(fake, RUN_ID, sleep=lambda _:None, polls=2)
        self.assertFalse(any(isinstance(event, tuple) and event[0] == 'doorbell64'
                             for event in fake.events))

    def test_hdp_flush_failure_never_unhalts_or_rings_host_kiq(self):
        tool = self.tool
        fake = FakeTransport(tool)
        fake.registers.update({
            tool.GCMC_VM_FB_LOCATION_BASE_OFFSET: 0xf400,
            tool.GCMC_VM_FB_LOCATION_TOP_OFFSET: 0xf41f,
            tool.CP_RB_DOORBELL_CONTROL_OFFSET: 0xc0000400,
        })
        fake.flush_hdp = lambda:(_ for _ in ()).throw(tool.RecoveryError('bad HDP'))
        with self.assertRaisesRegex(tool.RecoveryError, 'bad HDP'):
            tool.retire_legacy_gfx_with_host_kiq(fake, RUN_ID, sleep=lambda _:None, polls=2)
        self.assertFalse(any(isinstance(event, tuple) and event[0] == 'doorbell64'
                             for event in fake.events))
        mec_writes = [event[2] for event in fake.events if isinstance(event, tuple) and
                      event[:2] == ('write', tool.CP_MEC_CNTL_OFFSET)]
        self.assertTrue(all(value & tool.CP_MEC_HALT_MASK == tool.CP_MEC_HALT_MASK
                            for value in mec_writes))

    def test_fence_must_complete_even_when_ring_read_pointer_advances(self):
        tool = self.tool

        class MissingFence(FakeTransport):
            def ring_doorbell64(self, index, value):
                self.events.append(('doorbell64', index, value))
                self.registers[tool.CP_HQD_PQ_RPTR_OFFSET] = value
                self.registers[tool.CP_RB_ACTIVE_OFFSET] = 0

        fake = MissingFence(tool)
        fake.registers.update({
            tool.GCMC_VM_FB_LOCATION_BASE_OFFSET: 0xf400,
            tool.GCMC_VM_FB_LOCATION_TOP_OFFSET: 0xf41f,
            tool.CP_RB_DOORBELL_CONTROL_OFFSET: 0xc0000400,
        })
        with self.assertRaisesRegex(tool.RecoveryError, 'completion fence'):
            tool.retire_legacy_gfx_with_host_kiq(fake, RUN_ID, sleep=lambda _:None, polls=2)

    def test_stale_graphics_ring_is_unmapped_by_temporary_host_kiq(self):
        tool = self.tool

        class HostKiqTransport(FakeTransport):
            def __init__(self):
                super().__init__(tool)
                self.selector = 0
                self.hqd_active = 0

            def read32(self, offset):
                if offset == tool.CP_HQD_ACTIVE_OFFSET:
                    return self.hqd_active if self.selector == tool.HOST_KIQ_SELECTOR else 0
                if offset == tool.CP_HQD_PQ_RPTR_OFFSET and self.selector == tool.HOST_KIQ_SELECTOR:
                    if self.hqd_active and ('doorbell64', 0,
                                            tool.HOST_KIQ_RING_USED_DWORDS) in self.events:
                        return tool.HOST_KIQ_RING_USED_DWORDS
                    return super().read32(offset)
                return super().read32(offset)

            def write32(self, offset, value):
                if offset == tool.GRBM_GFX_CNTL_OFFSET:
                    self.selector = value
                if offset == tool.CP_HQD_ACTIVE_OFFSET and self.selector == tool.HOST_KIQ_SELECTOR:
                    self.hqd_active = value & 1
                if (offset == tool.CP_HQD_DEQUEUE_OFFSET and value == 1 and
                        self.selector == tool.HOST_KIQ_SELECTOR):
                    self.hqd_active = 0
                super().write32(offset, value)

            def ring_doorbell64(self, index, value):
                self.registers[tool.CP_RB_ACTIVE_OFFSET] = 0
                super().ring_doorbell64(index, value)

        fake = HostKiqTransport()
        fake.registers[tool.GCMC_VM_FB_LOCATION_BASE_OFFSET] = 0xf400
        fake.registers[tool.GCMC_VM_FB_LOCATION_TOP_OFFSET] = 0xf41f
        fake.registers[tool.CP_RB_DOORBELL_CONTROL_OFFSET] = 0xc0000400
        fake.registers[tool.CP_MEC_CNTL_OFFSET] = tool.CP_MEC_HALT_MASK
        result = tool.retire_legacy_gfx_with_host_kiq(fake, RUN_ID, sleep=lambda _:None, polls=3)
        self.assertEqual(tuple(fake.read_vram32(tool.HOST_KIQ_RING_OFFSET+n)
                               for n in range(0, 24, 4)), tool.HOST_KIQ_UNMAP_GFX)
        self.assertEqual(result['status'], 'retired')
        self.assertEqual(result['rptr_after'], tool.HOST_KIQ_RING_USED_DWORDS)
        self.assertEqual(result['fence_after'], result['fence_sequence'])
        self.assertTrue(result['cleanup_confirmed'])
        self.assertEqual(result['gfx_active_after_unmap'], 0)
        self.assertIn(('doorbell64', 0, tool.HOST_KIQ_RING_USED_DWORDS), fake.events)
        halt = fake.events.index(('write', tool.CP_MEC_CNTL_OFFSET,
                                  tool.CP_MEC_HALT_MASK))
        reservation_consume = fake.events.index(
            ('write-vram', tool.HOST_KIQ_RESERVATION_OFFSET,
             tool.HOST_KIQ_RESERVATION_SIZE))
        first_scratch_write = next(index for index, event in enumerate(fake.events)
                                   if isinstance(event, tuple) and
                                   event[0] == 'write-vram' and
                                   event[1] != tool.HOST_KIQ_RESERVATION_OFFSET)
        self.assertLess(reservation_consume, halt)
        self.assertLess(halt, first_scratch_write)
        last_vram = max(index for index, event in enumerate(fake.events)
                        if isinstance(event, tuple) and event[0] == 'write-vram')
        unhalt = next(index for index, event in enumerate(fake.events)
                      if isinstance(event, tuple) and event[:2] ==
                      ('write', tool.CP_MEC_CNTL_OFFSET) and
                      event[2] & tool.CP_MEC2_HALT_MASK == 0)
        hdp_flush = max(index for index, event in enumerate(fake.events)
                        if event == 'hdp-flush' and index < unhalt)
        doorbell = fake.events.index(
            ('doorbell64', 0, tool.HOST_KIQ_RING_USED_DWORDS))
        setup_vram = max(index for index, event in enumerate(fake.events[:unhalt])
                         if isinstance(event, tuple) and event[0] == 'write-vram')
        self.assertLess(setup_vram, hdp_flush)
        self.assertLess(hdp_flush, unhalt)
        self.assertLess(unhalt, doorbell)
        self.assertIn(('write', tool.CP_PQ_STATUS_OFFSET,
                       tool.CP_PQ_DOORBELL_ENABLE_MASK), fake.events)
        self.assertEqual(fake.selector, 0)
        self.assertEqual(fake.registers[tool.CP_MEC_CNTL_OFFSET] & tool.CP_MEC_HALT_MASK,
                         tool.CP_MEC_HALT_MASK)
        self.assertEqual(fake.hqd_active, 0)
        self.assertEqual(fake.registers[tool.CP_PQ_STATUS_OFFSET] &
                         tool.CP_PQ_DOORBELL_ENABLE_MASK, 0)
        self.assertEqual(fake.registers[tool.CP_MEC_DOORBELL_RANGE_LOWER_OFFSET], 0)
        self.assertEqual(fake.registers[tool.CP_MEC_DOORBELL_RANGE_UPPER_OFFSET], 0)
        self.assertEqual(fake.registers[tool.CP_PQ_WPTR_POLL_CNTL_OFFSET] &
                         tool.CP_PQ_WPTR_POLL_ENABLE_MASK, 0)

    def test_host_kiq_timeout_fails_closed_and_rehalts_mec(self):
        tool = self.tool

        class WedgedKiq(FakeTransport):
            def __init__(self):
                super().__init__(tool)
                self.selector = 0
                self.hqd_active = 0

            def read32(self, offset):
                if offset == tool.CP_HQD_ACTIVE_OFFSET:
                    return self.hqd_active if self.selector == tool.HOST_KIQ_SELECTOR else 0
                if offset == tool.CP_HQD_PQ_RPTR_OFFSET:
                    return 0
                return super().read32(offset)

            def write32(self, offset, value):
                if offset == tool.GRBM_GFX_CNTL_OFFSET:
                    self.selector = value
                if (offset == tool.CP_HQD_ACTIVE_OFFSET and value == 1 and
                        self.selector == tool.HOST_KIQ_SELECTOR):
                    self.hqd_active = 1
                super().write32(offset, value)

        fake = WedgedKiq()
        fake.registers[tool.GCMC_VM_FB_LOCATION_BASE_OFFSET] = 0xf400
        fake.registers[tool.GCMC_VM_FB_LOCATION_TOP_OFFSET] = 0xf41f
        fake.registers[tool.CP_RB_DOORBELL_CONTROL_OFFSET] = 0xc0000400
        fake.registers[tool.CP_MEC_CNTL_OFFSET] = tool.CP_MEC_HALT_MASK
        with self.assertRaisesRegex(tool.RecoveryError, 'host KIQ did not consume'):
            tool.retire_legacy_gfx_with_host_kiq(fake, RUN_ID, sleep=lambda _:None, polls=2)
        self.assertEqual(fake.selector, 0)
        self.assertEqual(fake.registers[tool.CP_MEC_CNTL_OFFSET] & tool.CP_MEC_HALT_MASK,
                         tool.CP_MEC_HALT_MASK)
        self.assertIn(('write', tool.CP_HQD_PQ_DOORBELL_OFFSET, 0), fake.events)

    def test_packet_fetch_does_not_prove_graphics_unmap_completed(self):
        tool = self.tool

        class StickyGraphicsActive(FakeTransport):
            def __init__(self):
                super().__init__(tool)
                self.selector = 0
                self.hqd_active = 0
                self.registers[tool.CP_RB_ACTIVE_OFFSET] = 1

            def read32(self, offset):
                if offset == tool.CP_HQD_ACTIVE_OFFSET:
                    return self.hqd_active if self.selector == tool.HOST_KIQ_SELECTOR else 0
                if (offset == tool.CP_HQD_PQ_RPTR_OFFSET and
                        self.selector == tool.HOST_KIQ_SELECTOR):
                    if self.hqd_active and ('doorbell64', 0,
                                            tool.HOST_KIQ_RING_USED_DWORDS) in self.events:
                        return tool.HOST_KIQ_RING_USED_DWORDS
                    return super().read32(offset)
                return super().read32(offset)

            def write32(self, offset, value):
                if offset == tool.GRBM_GFX_CNTL_OFFSET:
                    self.selector = value
                if (offset == tool.CP_HQD_ACTIVE_OFFSET and
                        self.selector == tool.HOST_KIQ_SELECTOR):
                    self.hqd_active = value & 1
                super().write32(offset, value)

        fake = StickyGraphicsActive()
        fake.registers[tool.GCMC_VM_FB_LOCATION_BASE_OFFSET] = 0xf400
        fake.registers[tool.GCMC_VM_FB_LOCATION_TOP_OFFSET] = 0xf41f
        fake.registers[tool.CP_RB_DOORBELL_CONTROL_OFFSET] = 0xc0000400
        def keep_active(index, value):
            FakeTransport.ring_doorbell64(fake, index, value)
            fake.registers[tool.CP_RB_ACTIVE_OFFSET] = 1
        fake.ring_doorbell64 = keep_active
        with self.assertRaisesRegex(tool.RecoveryError, 'graphics.*active.*UNMAP'):
            tool.retire_legacy_gfx_with_host_kiq(fake, RUN_ID, sleep=lambda _:None, polls=2)
        self.assertEqual(fake.registers[tool.CP_RB_ACTIVE_OFFSET], 1)

    def test_full_recovery_uses_host_kiq_for_stale_graphics_ring(self):
        tool = self.tool

        class StaleGraphicsTransport(FakeTransport):
            def __init__(self):
                super().__init__(tool)
                self.selector = 0
                self.hqd_active = 0

            def read32(self, offset):
                if offset == tool.CP_HQD_ACTIVE_OFFSET:
                    return self.hqd_active if self.selector == tool.HOST_KIQ_SELECTOR else 0
                if (offset == tool.CP_HQD_PQ_RPTR_OFFSET and
                        self.selector == tool.HOST_KIQ_SELECTOR):
                    if self.hqd_active and ('doorbell64', 0,
                                            tool.HOST_KIQ_RING_USED_DWORDS) in self.events:
                        return tool.HOST_KIQ_RING_USED_DWORDS
                    return super().read32(offset)
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
                super().write32(offset, value)

            def ring_doorbell64(self, index, value):
                self.registers[tool.CP_RB_ACTIVE_OFFSET] = 0
                super().ring_doorbell64(index, value)

        fake = StaleGraphicsTransport()
        fake.registers.update({
            tool.GCMC_VM_FB_LOCATION_BASE_OFFSET: 0xf400,
            tool.GCMC_VM_FB_LOCATION_TOP_OFFSET: 0xf41f,
            tool.GCMC_VM_FB_OFFSET_OFFSET: 0x840,
            tool.CP_RB_ACTIVE_OFFSET: 1,
            tool.CP_RB_DOORBELL_CONTROL_OFFSET: 0xc0000400,
            tool.CP_RB0_WPTR_OFFSET: 0x80,
            tool.CP_RB0_BASE_OFFSET: 0x00bfe000,
            tool.CP_RB0_BASE_HI_OFFSET: 0xf4,
            tool.CP_RB0_CNTL_OFFSET: 0x00a00e10,
        })
        states = iter([self.state(), self.state()])
        evidence = tool.perform_recovery(
            'boot-A', 'a'*32, lambda:next(states), lambda:fake,
            lambda cursor=None:('cursor-2', [], []), sleep=lambda _:None, polls=3)
        self.assertEqual(evidence['status'], 'recovered')
        self.assertTrue(evidence['authorizes_launch'])
        gc = evidence['gc_quiesce']
        self.assertEqual(gc['host_kiq']['status'], 'retired')
        self.assertTrue(gc['gfx_retirement_confirmed'])
        self.assertTrue(gc['gfx_ring_clean'])
        self.assertEqual(gc['gfx_rb_base_after'], 0)
        self.assertEqual(gc['gfx_rb_base_hi_after'], 0)
        self.assertEqual(gc['gfx_rb_cntl_after'], 0)
        self.assertEqual(sum(event == (
            'write-vram', tool.HOST_KIQ_RESERVATION_OFFSET,
            tool.HOST_KIQ_RESERVATION_SIZE) for event in fake.events), 1)
        evidence['recovery_id'] = 'b'*32
        experiment_path = ROOT/'tools/experiment.py'
        spec = importlib.util.spec_from_file_location(
            'experiment_host_kiq_integration', experiment_path)
        experiment = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(experiment)
        self.assertEqual(experiment.validate_recovery_receipt(
            evidence, 'boot-A', RUN_ID), [])

    def test_clean_graphics_ring_does_not_build_or_ring_host_kiq(self):
        fake = FakeTransport(self.tool)
        result = self.tool.quiesce_gc(fake, sleep=lambda _:None, polls=2)
        self.assertEqual(result['host_kiq'], {'status':'not-needed'})
        self.assertFalse(any(event[0] == 'doorbell64' for event in fake.events
                             if isinstance(event, tuple)))

    def test_recovery_consumes_exact_active_reservation_before_clean_gc_path(self):
        tool = self.tool
        fake = FakeTransport(tool)
        states = iter([self.state(), self.state()])
        evidence = tool.perform_recovery(
            'boot-A', RUN_ID, lambda:next(states), lambda:fake,
            lambda cursor=None:('cursor-2', [], []), sleep=lambda _:None, polls=2)
        proof = evidence['gc_quiesce']['reservation']
        self.assertTrue(proof['consumed'])
        self.assertEqual(proof['run_id'], RUN_ID)
        self.assertEqual(proof['state'], tool.HOST_KIQ_RESERVATION_ACTIVE)
        consume = fake.events.index(('write-vram', tool.HOST_KIQ_RESERVATION_OFFSET,
                                     tool.HOST_KIQ_RESERVATION_SIZE))
        first_gc_write = next(index for index, event in enumerate(fake.events)
                              if isinstance(event, tuple) and event[0] == 'write' and
                              event[1] != tool.C2PMSG_64_OFFSET)
        self.assertLess(consume, first_gc_write)
        self.assertEqual(sum(event == ('write-vram', tool.HOST_KIQ_RESERVATION_OFFSET,
                                      tool.HOST_KIQ_RESERVATION_SIZE)
                             for event in fake.events), 1)

    def test_clean_recovery_rejects_absent_pending_corrupt_wrong_nonce_and_replay(self):
        tool = self.tool
        cases = {}
        absent = FakeTransport(tool); absent.vram.clear(); cases['absent'] = absent
        pending = FakeTransport(tool)
        pending.write_vram(tool.HOST_KIQ_RESERVATION_OFFSET,
                           tool.host_kiq_reservation_descriptor(
                               RUN_ID, tool.HOST_KIQ_RESERVATION_PENDING))
        pending.events.clear(); cases['pending'] = pending
        corrupt = FakeTransport(tool)
        corrupt.vram[tool.HOST_KIQ_RESERVATION_OFFSET +
                     tool.HOST_KIQ_RESERVATION_SIZE - 1] ^= 1
        cases['corrupt'] = corrupt
        wrong = FakeTransport(tool, run_id='b'*32); cases['wrong-nonce'] = wrong
        for name, fake in cases.items():
            with self.subTest(name=name), self.assertRaisesRegex(
                    tool.RecoveryError, 'reservation'):
                tool.perform_recovery(
                    'boot-A', RUN_ID, lambda:self.state(), lambda:fake,
                    lambda cursor=None:('cursor-2', [], []),
                    sleep=lambda _:None, polls=2)
            self.assertFalse(any(isinstance(event, tuple) and event[0] == 'write'
                                 for event in fake.events),
                             'reservation rejection happened after GC/PSP mutation')

        replay = FakeTransport(tool)
        states = iter([self.state(), self.state()])
        tool.perform_recovery(
            'boot-A', RUN_ID, lambda:next(states), lambda:replay,
            lambda cursor=None:('cursor-2', [], []), sleep=lambda _:None, polls=2)
        replay.events.clear()
        with self.assertRaisesRegex(tool.RecoveryError, 'reservation'):
            tool.perform_recovery(
                'boot-A', RUN_ID, lambda:self.state(), lambda:replay,
                lambda cursor=None:('cursor-2', [], []), sleep=lambda _:None, polls=2)
        self.assertFalse(any(isinstance(event, tuple) and event[0] == 'write'
                             for event in replay.events))

    def test_residual_graphics_programming_without_active_or_doorbell_does_not_trigger_kiq(self):
        tool = self.tool
        fake = FakeTransport(tool)
        fake.registers.update({
            tool.CP_RB0_WPTR_OFFSET: 0x80,
            tool.CP_RB0_BASE_OFFSET: 0x00bfe000,
            tool.CP_RB0_CNTL_OFFSET: 0x00a00e10,
        })
        result = tool.quiesce_gc(fake, sleep=lambda _:None, polls=2)
        self.assertEqual(result['host_kiq'], {'status':'not-needed'})
        self.assertFalse(result['gfx_needs_unmap'])
        self.assertFalse(any(isinstance(event, tuple) and event[0] == 'doorbell64'
                             for event in fake.events))

    def test_stuck_compute_hqd_blocks_host_kiq_unhalt(self):
        tool = self.tool

        class StuckBeforeKiq(FakeTransport):
            def __init__(self):
                super().__init__(tool)
                self.selector = 0
                self.target = tool.queue_selector(1, 0, 0)
                self.active = 1

            def read32(self, offset):
                if offset == tool.CP_HQD_ACTIVE_OFFSET:
                    return self.active if self.selector == self.target else 0
                return super().read32(offset)

            def write32(self, offset, value):
                if offset == tool.GRBM_GFX_CNTL_OFFSET:
                    self.selector = value
                if (offset == tool.CP_HQD_ACTIVE_OFFSET and value == 0 and
                        self.selector == self.target):
                    self.active = 0
                super().write32(offset, value)

        fake = StuckBeforeKiq()
        fake.registers.update({
            tool.GCMC_VM_FB_LOCATION_BASE_OFFSET: 0xf400,
            tool.GCMC_VM_FB_LOCATION_TOP_OFFSET: 0xf41f,
            tool.CP_RB_ACTIVE_OFFSET: 1,
        })
        result = tool.quiesce_gc(fake, sleep=lambda _:None, polls=2)
        self.assertEqual(result['host_kiq']['status'], 'blocked-active-hqd')
        self.assertFalse(any(event[0] == 'doorbell64' for event in fake.events
                             if isinstance(event, tuple)))
        self.assertEqual(result['dequeue_timeouts'], 1)
        self.assertEqual(result['forced_inactive'], 1)
        mec_writes = [event[2] for event in fake.events if isinstance(event, tuple) and
                      event[:2] == ('write', tool.CP_MEC_CNTL_OFFSET)]
        self.assertTrue(mec_writes)
        self.assertTrue(all(value & tool.CP_MEC_HALT_MASK == tool.CP_MEC_HALT_MASK
                            for value in mec_writes))

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
        self.assertEqual(evidence['gc_quiesce']['host_kiq'], {'status':'not-needed'})
        self.assertTrue(evidence['authorizes_launch'])
        self.assertEqual(evidence['schema'], 3)
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
        gfx_halt = fake.events.index(('write', tool.CP_ME_CNTL_OFFSET,
                                      tool.CP_ME_HALT_MASK))
        gfx_clear = fake.events.index(('write', tool.CP_RB_DOORBELL_CONTROL_OFFSET, 0))
        self.assertLess(gfx_halt, gfx_clear)
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
        self.assertEqual(result['gfx_rb_active_after'], 0)
        self.assertEqual(result['gfx_rb_doorbell_after'] & tool.CP_RB_DOORBELL_ENABLE_MASK, 0)
        self.assertEqual(result['gfx_rb_wptr_after'], 0)
        self.assertEqual(result['gfx_rb_base_after'], 0)
        self.assertEqual(result['gfx_rb_base_hi_after'], 0)
        self.assertEqual(result['gfx_rb_cntl_after'], 0)
        self.assertTrue(result['gfx_ring_clean'])

    def test_nonzero_legacy_graphics_ring_cannot_authorize_reuse(self):
        tool = self.tool

        class StickyGraphicsRing(FakeTransport):
            def write32(self, offset, value):
                if offset == tool.CP_RB_ACTIVE_OFFSET:
                    self.events.append(('ignored-write', offset, value))
                    return
                super().write32(offset, value)

        fake = StickyGraphicsRing(tool)
        fake.registers[tool.CP_RB_ACTIVE_OFFSET] = 1
        states = iter([self.state(), self.state()])
        result = tool.perform_recovery(
            'boot-A', 'a'*32, lambda:next(states), lambda:fake,
            lambda cursor=None:('cursor-2', [], []), sleep=lambda _:None)
        self.assertEqual(result['status'], 'incomplete')
        self.assertFalse(result['authorizes_launch'])
        self.assertFalse(result['gc_quiesce']['gfx_ring_clean'])
        self.assertTrue(all(row['confirmed'] for row in result['commands']))

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
        fake = FakeTransport(self.tool, fail_command=self.tool.DESTROY_RINGS,
                             run_id='b'*32)
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
                fake = FakeTransport(self.tool, run_id='c'*32)
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
        fake = FakeTransport(self.tool, run_id='c'*32)
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
            fake = FakeTransport(self.tool, run_id='d'*32)
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
            experiment_path = ROOT/'tools/experiment.py'
            spec = importlib.util.spec_from_file_location(
                'experiment_receipt_integration', experiment_path)
            experiment = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(experiment)
            self.assertEqual(experiment.validate_recovery_receipt(
                receipt, 'boot-A', 'd'*32), [])
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
            fake = FakeTransport(self.tool, run_id=prior)
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
