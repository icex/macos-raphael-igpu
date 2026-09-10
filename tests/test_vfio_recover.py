import importlib.util
import hashlib
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


def load_lease_tool():
    path = ROOT / 'tools/recovery_lease_v2.py'
    spec = importlib.util.spec_from_file_location('recovery_lease_v2_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_v3_evidence(tool, fake):
    wire = load_lease_tool()
    nonce = struct.unpack('<QQ', bytes.fromhex(RUN_ID))
    descriptor = wire.make_ownership_descriptor(0x08000000, *nonce)
    pool = wire.make_pool_status(
        descriptor, state=wire.POOL_ACTIVE,
        pool0_before=0x0e000000, pool0_after=0x0dfeb000,
        pool1_before=0x0c000000, pool1_after=0x0bfeb000, reason=0)
    evidence = tool.parse_v2_lease_records([
        wire.format_owned_record(descriptor), wire.format_pool_record(pool),
    ], RUN_ID)
    owned_raw = descriptor.pack()
    pool_raw = pool.pack()
    lifetime = tool._recovery_lifetime_v3().make_valid_marker(owned_raw, pool_raw).pack()
    for offset, raw in (
            (descriptor.lease_offset, owned_raw),
            (descriptor.lease_offset + wire.POOL_STATUS_OFFSET, pool_raw),
            (descriptor.lease_offset + tool._recovery_lifetime_v3().LIFETIME_OFFSET,
             lifetime)):
        fake.vram.update((offset + index, value) for index, value in enumerate(raw))
    return evidence, descriptor, pool, lifetime


class FakeTransport:
    def __init__(self, tool, *, fail_command=None, run_id=RUN_ID):
        self.tool = tool
        self.fail_command = fail_command
        self.events = []
        self.value = 0x80050000
        self.gfx_selector = 0
        self.pipe1_doorbell = 0
        self.pipe1_rb0_active = 0
        self.registers = {
            tool.NBIO_CONFIG_MEMSIZE_OFFSET: tool.EXPECTED_CONFIG_MEMSIZE,
            tool.SDMA0_STATUS_REG_OFFSET: tool.SDMA_STATUS_IDLE_MASK,
            tool.GCMC_VM_FB_LOCATION_BASE_OFFSET: 0xf400,
            tool.GCMC_VM_FB_LOCATION_TOP_OFFSET: 0xf41f,
            tool.GCMC_VM_FB_OFFSET_OFFSET: 0x840,
        }
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
        if (offset == self.tool.CP_RB_DOORBELL_CONTROL_OFFSET and
                self.gfx_selector & 0x3 == 1):
            return self.pipe1_doorbell
        if (offset == self.tool.CP_RB_ACTIVE_OFFSET and
                self.gfx_selector & 0x3 == 1):
            return self.pipe1_rb0_active
        return self.value if offset == self.tool.C2PMSG_64_OFFSET else self.registers.get(offset, 0)

    def write32(self, offset, value):
        self.events.append(('write', offset, value))
        if offset == self.tool.GRBM_GFX_CNTL_OFFSET:
            self.gfx_selector = value
        if (offset == self.tool.CP_RB_DOORBELL_CONTROL_OFFSET and
                self.gfx_selector & 0x3 == 1):
            self.pipe1_doorbell = value
        elif offset != self.tool.C2PMSG_64_OFFSET:
            self.registers[offset] = value
        elif value != self.fail_command:
            self.value = self.tool.READY_FLAG | value

    def flush_hdp(self):
        self.events.append('hdp-flush')
        return {'remap':self.tool.HDP_MEM_FLUSH_REMAP_OFFSET,
                'posted_read':self.registers.get(
                    self.tool.NBIO_CONFIG_MEMSIZE_OFFSET, 0)}

    def invalidate_hdp_read_cache(self):
        self.events.append('hdp-read-invalidate')
        return {'register': self.tool.HDP_READ_CACHE_INVALIDATE_OFFSET,
                'trigger': 1, 'posted_read': 1}

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
        self.assertEqual(tool.SDMA0_STATUS_REG_OFFSET,
                         (tool.GC_SEG0 + 0x25) * 4)
        self.assertEqual(tool.SDMA0_PAGE_RB_CNTL_OFFSET,
                         (tool.GC_SEG0 + 0xD8) * 4)
        self.assertEqual(tool.SDMA0_PAGE_IB_CNTL_OFFSET,
                         (tool.GC_SEG0 + 0xE2) * 4)
        self.assertEqual(tool.SDMA0_RLC_RB_CNTL_OFFSETS,
                         tuple((tool.GC_SEG0 + 0x130 + 0x58 * index) * 4
                               for index in range(2)))
        self.assertEqual(tool.SDMA0_RLC_IB_CNTL_OFFSETS,
                         tuple((tool.GC_SEG0 + 0x13A + 0x58 * index) * 4
                               for index in range(2)))

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
        self.assertEqual(tool.HDP_MEM_FLUSH_NATIVE_OFFSET, 0x385c)
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

        struct.pack_into('<I', transport.bar, tool.NBIO_REMAP_HDP_MEM_FLUSH_OFFSET,
                         tool.HDP_MEM_FLUSH_NATIVE_OFFSET)
        struct.pack_into('<I', transport.bar, tool.HDP_MEM_FLUSH_NATIVE_OFFSET, 0xfeed)
        evidence = transport.flush_hdp()
        self.assertEqual(evidence, {'remap':0x385c, 'posted_read':0x200})
        self.assertEqual(struct.unpack_from(
            '<I', transport.bar, tool.HDP_MEM_FLUSH_NATIVE_OFFSET)[0], 0)
        struct.pack_into('<I', transport.bar,
                         tool.NBIO_REMAP_HDP_MEM_FLUSH_OFFSET, 0)
        with self.assertRaisesRegex(tool.RecoveryError, 'HDP flush target'):
            transport.flush_hdp()

        struct.pack_into('<I', transport.bar, tool.NBIO_REMAP_HDP_MEM_FLUSH_OFFSET,
                         tool.HDP_MEM_FLUSH_NATIVE_OFFSET)
        struct.pack_into('<I', transport.bar, tool.NBIO_CONFIG_MEMSIZE_OFFSET, 0x201)
        with self.assertRaisesRegex(tool.RecoveryError, 'CONFIG_MEMSIZE'):
            transport.flush_hdp()

    def test_hdp_read_invalidate_uses_discovery_base_and_native_u32_access(self):
        tool = self.tool
        self.assertEqual(tool.HDP_SEG0, 0xf20)
        self.assertEqual(tool.HDP_READ_CACHE_INVALIDATE_OFFSET,
                         (0xf20 + 0xd1) * 4)
        self.assertEqual(tool.HDP_READ_CACHE_INVALIDATE_OFFSET, 0x3fc4)

        storage = bytearray(0x4000)
        tool._store_mmio_u32(storage, tool.HDP_READ_CACHE_INVALIDATE_OFFSET, 1)
        self.assertEqual(tool._load_mmio_u32(
            storage, tool.HDP_READ_CACHE_INVALIDATE_OFFSET), 1)
        with self.assertRaisesRegex(tool.RecoveryError, 'aligned'):
            tool._store_mmio_u32(storage, 2, 1)
        with self.assertRaisesRegex(tool.RecoveryError, 'aligned'):
            tool._load_mmio_u32(storage, len(storage) - 2)

    def test_hdp_read_invalidate_orders_native_store_posting_read_and_full_fence(self):
        tool = self.tool
        events = []
        transport = tool.LegacyVfio(thread_fence=lambda:events.append('fence'))
        transport.bar = bytearray(0x80000)

        def store(buffer, offset, value):
            events.append(('store', offset, value))
            struct.pack_into('=I', buffer, offset, value)

        def load(buffer, offset):
            events.append(('load', offset))
            return struct.unpack_from('=I', buffer, offset)[0]

        with patch.object(tool, '_store_mmio_u32', side_effect=store), \
             patch.object(tool, '_load_mmio_u32', side_effect=load):
            proof = transport.invalidate_hdp_read_cache()
        self.assertEqual(events, [
            ('store', tool.HDP_READ_CACHE_INVALIDATE_OFFSET, 1),
            ('load', tool.HDP_READ_CACHE_INVALIDATE_OFFSET),
            'fence',
        ])
        self.assertEqual(proof, {
            'register': tool.HDP_READ_CACHE_INVALIDATE_OFFSET,
            'trigger': 1,
            'posted_read': 1,
        })

    def test_hdp_read_invalidate_fails_closed_on_inaccessible_posting_read(self):
        tool = self.tool
        fenced = []
        transport = tool.LegacyVfio(thread_fence=lambda:fenced.append(True))
        transport.bar = bytearray(0x80000)
        with patch.object(tool, '_load_mmio_u32', return_value=0xffffffff), \
             self.assertRaisesRegex(tool.RecoveryError, 'inaccessible/all-ones'):
            transport.invalidate_hdp_read_cache()
        self.assertEqual(fenced, [])

    def test_hdp_fence_dependency_is_resolved_before_vfio_device_open(self):
        tool = self.tool
        with patch.object(tool, '_resolve_thread_fence',
                          side_effect=tool.RecoveryError('full fence unavailable')), \
             patch.object(tool.os, 'open') as opened, \
             self.assertRaisesRegex(tool.RecoveryError, 'full fence unavailable'):
            tool.LegacyVfio().__enter__()
        opened.assert_not_called()

    def test_vram_publication_uses_hdp_instead_of_msync(self):
        tool = self.tool

        class VfioBar(bytearray):
            def __init__(self, size):
                super().__init__(size)
                self.flush_calls = 0

            def flush(self, offset, size):
                self.flush_calls += 1
                raise OSError(22, 'Invalid argument')

        with patch.object(tool, 'VRAM_BAR_SIZE', 0x1000), \
             patch.object(tool, 'HOST_KIQ_RESERVATION_OFFSET', 0):
            transport = tool.LegacyVfio()
            bar0 = VfioBar(tool.VRAM_BAR_SIZE)
            bar5 = bytearray(0x80000)
            transport.bars[tool.VFIO_PCI_BAR0_REGION_INDEX] = bar0
            transport.bar = bar5
            struct.pack_into('<I', bar5, tool.NBIO_REMAP_HDP_MEM_FLUSH_OFFSET,
                             tool.HDP_MEM_FLUSH_REMAP_OFFSET)
            struct.pack_into('<I', bar5, tool.NBIO_CONFIG_MEMSIZE_OFFSET, 0x200)

            result = tool.prepare_host_kiq_reservation(transport, RUN_ID)
            expected = tool.host_kiq_reservation_descriptor(
                RUN_ID, tool.HOST_KIQ_RESERVATION_PENDING)
            observed = bytes(bar0[:len(expected)])
        self.assertEqual(observed, expected)
        self.assertEqual(bar0.flush_calls, 0)
        self.assertEqual(result['hdp_flush'], {'remap': 0x7f000, 'posted_read': 0x200})

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
        self.assertTrue(tool.valid_consumed_reservation(proof, RUN_ID))
        for key in ('remap', 'posted_read'):
            broken = dict(proof)
            broken['consume_hdp_flush'] = dict(proof['consume_hdp_flush'])
            broken['consume_hdp_flush'][key] = float(broken['consume_hdp_flush'][key])
            self.assertFalse(tool.valid_consumed_reservation(broken, RUN_ID))
        self.assertEqual(proof['heap_limit'], tool.HOST_KIQ_HEAP_LIMIT)
        self.assertEqual(proof['scratch_start'], tool.HOST_KIQ_RING_OFFSET)
        self.assertTrue(all(fake.read_vram32(
            tool.HOST_KIQ_RESERVATION_OFFSET+n) == 0
            for n in range(0, tool.HOST_KIQ_RESERVATION_SIZE, 4)))
        with self.assertRaisesRegex(tool.RecoveryError, 'reservation'):
            tool.consume_host_kiq_reservation(fake, RUN_ID)

    def test_v2_lease_authentication_derives_dynamic_kiq_image_without_writes(self):
        tool = self.tool
        wire = load_lease_tool()
        nonce = struct.unpack('<QQ', bytes.fromhex(RUN_ID))
        descriptor = wire.make_ownership_descriptor(0x0a000000, *nonce)
        status = wire.make_pool_status(
            descriptor, state=wire.POOL_ACTIVE,
            pool0_before=0x0e000000, pool0_after=0x0dfeb000,
            pool1_before=0x0c000000, pool1_after=0x0bfeb000, reason=0)
        evidence = tool.parse_v2_lease_records([
            wire.format_owned_record(descriptor), wire.format_pool_record(status),
        ], RUN_ID)
        fake = FakeTransport(tool)
        fake.vram.update((descriptor.lease_offset + offset, value)
                         for offset, value in enumerate(descriptor.pack()))
        fake.vram.update((descriptor.lease_offset + wire.POOL_STATUS_OFFSET + offset, value)
                         for offset, value in enumerate(status.pack()))

        authenticated = tool.authenticate_v2_host_kiq_lease(fake, evidence, RUN_ID)
        layout = authenticated.layout
        self.assertEqual(tool.host_kiq_scratch_ranges(layout), (
            (0x0a001000, 0x10000), (0x0a011000, 0x800),
            (0x0a012000, 4), (0x0a012008, 8),
            (0x0a013000, 0x1000), (0x0a014000, 4),
        ))
        ring, mqd, addresses = tool._host_kiq_image(
            0xf400000000, 0x13579bdf, 0x400, layout)
        self.assertEqual(addresses, {
            'ring':0xf40a001000, 'mqd':0xf40a011000,
            'rptr':0xf40a012000, 'wptr':0xf40a012008,
            'eop':0xf40a013000, 'fence':0xf40a014000,
        })
        self.assertEqual(len(ring), 0x10000)
        self.assertEqual(len(mqd), 0x800)
        self.assertEqual(authenticated.proof['pool_readback'], 'committed')
        self.assertFalse(any(isinstance(event, tuple) and event[0] == 'write-vram'
                             for event in fake.events))

    def test_v2_lease_accepts_commit_before_log_but_rejects_corrupt_readback(self):
        tool = self.tool
        wire = load_lease_tool()
        nonce = struct.unpack('<QQ', bytes.fromhex(RUN_ID))
        descriptor = wire.make_ownership_descriptor(0x09000000, *nonce)
        status = wire.make_pool_status(
            descriptor, state=wire.POOL_ACTIVE,
            pool0_before=0x0e000000, pool0_after=0x0dfeb000,
            pool1_before=0x0c000000, pool1_after=0x0bfeb000, reason=0)
        owned_only = tool.parse_v2_lease_records(
            [wire.format_owned_record(descriptor)], RUN_ID)
        fake = FakeTransport(tool)
        fake.vram.update((descriptor.lease_offset + offset, value)
                         for offset, value in enumerate(descriptor.pack()))
        fake.vram.update((descriptor.lease_offset + wire.POOL_STATUS_OFFSET + offset, value)
                         for offset, value in enumerate(status.pack()))

        authenticated = tool.authenticate_v2_host_kiq_lease(fake, owned_only, RUN_ID)
        self.assertEqual(authenticated.proof['pool_readback'], 'committed')
        self.assertEqual(authenticated.proof['pool_status']['state'], wire.POOL_ACTIVE)
        self.assertFalse(any(isinstance(event, tuple) and event[0] == 'write-vram'
                             for event in fake.events))

        fake.vram[descriptor.lease_offset] ^= 1
        with self.assertRaisesRegex(tool.RecoveryError, 'OWNED readback'):
            tool.authenticate_v2_host_kiq_lease(fake, owned_only, RUN_ID)
        self.assertFalse(any(isinstance(event, tuple) and event[0] == 'write-vram'
                             for event in fake.events))

    def test_v2_explicit_invalid_pool_status_refuses_host_kiq(self):
        tool = self.tool
        wire = load_lease_tool()
        nonce = struct.unpack('<QQ', bytes.fromhex(RUN_ID))
        descriptor = wire.make_ownership_descriptor(0x09000000, *nonce)
        status = wire.make_pool_status(
            descriptor, state=wire.POOL_INVALID,
            pool0_before=0x0e000000, pool0_after=0x0e000000,
            pool1_before=0x0c000000, pool1_after=0x0c000000, reason=2)
        evidence = tool.parse_v2_lease_records([
            wire.format_owned_record(descriptor), wire.format_pool_record(status),
        ], RUN_ID)
        fake = FakeTransport(tool)
        fake.vram.update((descriptor.lease_offset + offset, value)
                         for offset, value in enumerate(descriptor.pack()))
        fake.vram.update((descriptor.lease_offset + wire.POOL_STATUS_OFFSET + offset, value)
                         for offset, value in enumerate(status.pack()))

        with self.assertRaisesRegex(tool.RecoveryError, 'INVALID'):
            tool.authenticate_v2_host_kiq_lease(fake, evidence, RUN_ID)
        self.assertFalse(any(isinstance(event, tuple) and event[0] == 'write-vram'
                             for event in fake.events))

    def test_v2_owned_only_early_crash_keeps_descriptor_immutable(self):
        tool = self.tool
        wire = load_lease_tool()
        nonce = struct.unpack('<QQ', bytes.fromhex(RUN_ID))
        descriptor = wire.make_ownership_descriptor(0x08000000, *nonce)
        evidence = tool.parse_v2_lease_records(
            [wire.format_owned_record(descriptor)], RUN_ID)
        fake = FakeTransport(tool)
        fake.vram.update((descriptor.lease_offset + offset, value)
                         for offset, value in enumerate(descriptor.pack()))

        authenticated = tool.authenticate_v2_host_kiq_lease(fake, evidence, RUN_ID)
        before = bytes(fake.vram.get(descriptor.lease_offset + offset, 0)
                       for offset in range(wire.OWNERSHIP_STRUCT.size))
        proof = tool.prepare_v2_host_kiq_recovery(fake, authenticated, RUN_ID)
        after = bytes(fake.vram.get(descriptor.lease_offset + offset, 0)
                      for offset in range(wire.OWNERSHIP_STRUCT.size))
        self.assertEqual(before, after)
        self.assertEqual(proof, authenticated.proof)
        self.assertEqual(proof['pool_readback'], 'absent')
        self.assertFalse(any(isinstance(event, tuple) and event[0] == 'write-vram'
                             for event in fake.events))

        forged = tool.AuthenticatedV2Lease(
            authenticated.layout._replace(ring_offset=0x1000),
            authenticated.proof, authenticated.evidence)
        with self.assertRaisesRegex(tool.RecoveryError, 'layout'):
            tool.prepare_v2_host_kiq_recovery(fake, forged, RUN_ID)

        forged_proof = dict(authenticated.proof, scratch_start=0x1000)
        forged = tool.AuthenticatedV2Lease(
            authenticated.layout, forged_proof, authenticated.evidence)
        with self.assertRaisesRegex(tool.RecoveryError, 'proof'):
            tool.prepare_v2_host_kiq_recovery(fake, forged, RUN_ID)

    def test_v2_host_kiq_retirement_writes_only_dynamic_authenticated_scratch(self):
        tool = self.tool
        wire = load_lease_tool()
        nonce = struct.unpack('<QQ', bytes.fromhex(RUN_ID))
        descriptor = wire.make_ownership_descriptor(0x08000000, *nonce)
        evidence = tool.parse_v2_lease_records(
            [wire.format_owned_record(descriptor)], RUN_ID)

        class DynamicHostKiqTransport(FakeTransport):
            def __init__(self):
                super().__init__(tool)
                self.selector = 0
                self.hqd_active = 0
                self.dynamic_layout = None

            def read32(self, offset):
                if offset == tool.CP_HQD_ACTIVE_OFFSET:
                    return self.hqd_active if self.selector == tool.HOST_KIQ_SELECTOR else 0
                if (offset == tool.CP_HQD_PQ_RPTR_OFFSET and
                        self.selector == tool.HOST_KIQ_SELECTOR and self.hqd_active and
                        ('doorbell64', 0, tool.HOST_KIQ_RING_USED_DWORDS) in self.events):
                    return tool.HOST_KIQ_RING_USED_DWORDS
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
                self.events.append(('doorbell64', index, value))
                sequence = self.read_vram32(
                    self.dynamic_layout.ring_offset +
                    tool.HOST_KIQ_FENCE_SEQUENCE_DWORD * 4)
                self.write_vram(
                    self.dynamic_layout.fence_offset, struct.pack('<I', sequence))
                self.registers[tool.CP_HQD_PQ_RPTR_OFFSET] = value
                self.registers[tool.CP_RB_ACTIVE_OFFSET] = 0

        fake = DynamicHostKiqTransport()
        fake.vram.update((descriptor.lease_offset + offset, value)
                         for offset, value in enumerate(descriptor.pack()))
        fake.registers[tool.GCMC_VM_FB_LOCATION_BASE_OFFSET] = 0xf400
        fake.registers[tool.GCMC_VM_FB_LOCATION_TOP_OFFSET] = 0xf41f
        fake.registers[tool.CP_RB_DOORBELL_CONTROL_OFFSET] = 0xc0000400
        fake.registers[tool.CP_MEC_CNTL_OFFSET] = tool.CP_MEC_HALT_MASK
        authenticated = tool.authenticate_v2_host_kiq_lease(fake, evidence, RUN_ID)
        fake.dynamic_layout = authenticated.layout
        descriptor_before = descriptor.pack()

        result = tool.retire_legacy_gfx_with_host_kiq(
            fake, RUN_ID, sleep=lambda _:None, polls=3,
            authenticated_lease=authenticated)

        dynamic_ranges = tool.host_kiq_scratch_ranges(authenticated.layout)
        scratch_writes = [event for event in fake.events
                          if isinstance(event, tuple) and event[0] == 'write-vram']
        self.assertTrue(scratch_writes)
        self.assertTrue(all(any(start == event[1] and size == event[2]
                                for start, size in dynamic_ranges)
                            for event in scratch_writes))
        self.assertFalse(any(event[1] in {tool.HOST_KIQ_RING_OFFSET,
                                         tool.HOST_KIQ_MQD_OFFSET,
                                         tool.HOST_KIQ_FENCE_OFFSET}
                             for event in scratch_writes))
        self.assertEqual(
            bytes(fake.vram.get(descriptor.lease_offset + offset, 0)
                  for offset in range(len(descriptor_before))), descriptor_before)
        self.assertEqual(result['addresses']['ring'], 0xf408001000)
        self.assertEqual(result['reservation'], authenticated.proof)

    def test_v2_perform_recovery_authenticates_before_clean_quiesce(self):
        tool = self.tool
        wire = load_lease_tool()
        nonce = struct.unpack('<QQ', bytes.fromhex(RUN_ID))
        descriptor = wire.make_ownership_descriptor(0x08000000, *nonce)
        evidence = tool.parse_v2_lease_records(
            [wire.format_owned_record(descriptor)], RUN_ID)
        fake = FakeTransport(tool)
        fake.vram.update((descriptor.lease_offset + offset, value)
                         for offset, value in enumerate(descriptor.pack()))
        states = iter([self.state(), self.state()])

        result = tool.perform_recovery(
            'boot-A', RUN_ID, lambda:next(states), lambda:fake,
            lambda cursor=None:('cursor-2', [], []), sleep=lambda _:None, polls=2,
            lease_evidence=evidence)

        self.assertEqual(result['status'], 'recovered')
        self.assertTrue(result['authorizes_launch'])
        self.assertEqual(result['gc_quiesce']['reservation']['schema'], 2)
        self.assertTrue(result['gc_quiesce']['reservation']['immutable'])
        self.assertFalse(any(isinstance(event, tuple) and event[0] == 'write-vram'
                             for event in fake.events))

        corrupt = FakeTransport(tool)
        corrupt.vram.update((descriptor.lease_offset + offset, value)
                            for offset, value in enumerate(descriptor.pack()))
        corrupt.vram[descriptor.lease_offset] ^= 1
        with self.assertRaisesRegex(tool.RecoveryError, 'OWNED readback'):
            tool.perform_recovery(
                'boot-A', RUN_ID, lambda:self.state(), lambda:corrupt,
                lambda cursor=None:('cursor-2', [], []), sleep=lambda _:None, polls=2,
                lease_evidence=evidence)
        self.assertFalse(any(isinstance(event, tuple) and event[0] in {
            'write', 'write-vram', 'doorbell64'} for event in corrupt.events))

    def test_v2_recover_requires_exact_helper_hashes_before_host_access(self):
        expected = self.tool.current_recovery_helpers_sha256()
        self.assertEqual(set(expected), {
            'tools/vfio-recover.py',
            'tools/recovery_lease_v2.py',
            'tools/kiq-recovery-proof.py',
        })
        for relative, digest in expected.items():
            self.assertEqual(
                digest, hashlib.sha256((ROOT / relative).read_bytes()).hexdigest())

        with tempfile.TemporaryDirectory() as temp, \
             patch.object(self.tool, 'host_state') as host_state:
            with self.assertRaisesRegex(
                    self.tool.RecoveryError, 'recovery helper hashes'):
                self.tool.recover(
                    Path(temp), RUN_ID, lease_evidence=object(),
                    recovery_helpers_sha256=dict(expected,
                        **{'tools/recovery_lease_v2.py':'0' * 64}))
            host_state.assert_not_called()

    def test_schema3_helper_identity_adds_capture_and_lifetime_without_changing_v2(self):
        tool = self.tool
        self.assertEqual(set(tool.current_recovery_helpers_sha256(2)), {
            'tools/vfio-recover.py',
            'tools/recovery_lease_v2.py',
            'tools/kiq-recovery-proof.py',
        })
        expected_v3 = {
            'tools/vfio-recover.py',
            'tools/recovery_lease_v2.py',
            'tools/kiq-recovery-proof.py',
            'tools/critical-replay.py',
            'tools/recovery_lifetime_v3.py',
        }
        helpers = tool.current_recovery_helpers_sha256(3)
        self.assertEqual(set(helpers), expected_v3)
        self.assertEqual(tool.require_recovery_helpers_sha256(helpers, 3), helpers)
        with self.assertRaisesRegex(tool.RecoveryError, 'recovery helper hashes'):
            tool.require_recovery_helpers_sha256(
                tool.current_recovery_helpers_sha256(2), 3)

    def test_schema3_authentication_requires_active_pool_and_exact_valid_lifetime(self):
        tool = self.tool
        fake = FakeTransport(tool)
        evidence, descriptor, pool, valid_raw = make_v3_evidence(tool, fake)
        authenticated = tool.authenticate_v3_host_kiq_lease(fake, evidence, RUN_ID)
        self.assertEqual(authenticated.lifetime_raw, valid_raw)
        self.assertEqual(authenticated.proof['schema'], 3)
        self.assertEqual(authenticated.proof['lease_version'], 2)
        self.assertEqual(authenticated.proof['lifetime_version'], 3)
        self.assertIsNone(authenticated.proof['lifetime_readbacks']['pre_scratch'])

        for label, raw in (
                ('absent', bytes(len(valid_raw))),
                ('ABORT', tool._recovery_lifetime_v3().make_abort_marker(
                    tool._recovery_lifetime_v3().make_valid_marker(
                        descriptor.pack(), pool.pack()),
                    tool._recovery_lifetime_v3().REASON_POOL_OWNER).pack())):
            with self.subTest(label=label):
                broken = FakeTransport(tool)
                broken_evidence, broken_descriptor, _, _ = make_v3_evidence(tool, broken)
                lifetime_offset = (broken_descriptor.lease_offset +
                                   tool._recovery_lifetime_v3().LIFETIME_OFFSET)
                broken.vram.update((lifetime_offset + index, value)
                                   for index, value in enumerate(raw))
                with self.assertRaisesRegex(tool.RecoveryError, 'lifetime marker'):
                    tool.authenticate_v3_host_kiq_lease(
                        broken, broken_evidence, RUN_ID)
                self.assertFalse(any(isinstance(event, tuple) and event[0] in {
                    'write', 'write-vram', 'doorbell64'} for event in broken.events))

        owned_only = tool.parse_v2_lease_records(
            [tool.RECOVERY_LEASE_V2.format_owned_record(evidence.descriptor)], RUN_ID)
        with self.assertRaisesRegex(tool.RecoveryError, 'ACTIVE pool'):
            tool.authenticate_v3_host_kiq_lease(fake, owned_only, RUN_ID)

    def test_schema3_lifetime_is_rechecked_immediately_before_first_scratch_write(self):
        tool = self.tool

        class AbortOnMecHalt(FakeTransport):
            def __init__(self):
                super().__init__(tool)
                self.abort_raw = None
                self.lifetime_offset = None

            def write32(self, offset, value):
                super().write32(offset, value)
                if (offset == tool.CP_MEC_CNTL_OFFSET and self.abort_raw is not None):
                    self.vram.update((self.lifetime_offset + index, byte)
                                     for index, byte in enumerate(self.abort_raw))

        fake = AbortOnMecHalt()
        evidence, descriptor, pool, _ = make_v3_evidence(tool, fake)
        authenticated = tool.authenticate_v3_host_kiq_lease(fake, evidence, RUN_ID)
        valid = tool._recovery_lifetime_v3().make_valid_marker(
            descriptor.pack(), pool.pack())
        fake.abort_raw = tool._recovery_lifetime_v3().make_abort_marker(
            valid, tool._recovery_lifetime_v3().REASON_DUPLICATE_READY).pack()
        fake.lifetime_offset = (descriptor.lease_offset +
                                tool._recovery_lifetime_v3().LIFETIME_OFFSET)
        fake.registers[tool.CP_RB_DOORBELL_CONTROL_OFFSET] = 0xc0000400
        fake.registers[tool.CP_MEC_CNTL_OFFSET] = tool.CP_MEC_HALT_MASK

        with self.assertRaisesRegex(tool.RecoveryError, 'lifetime marker'):
            tool.retire_legacy_gfx_with_host_kiq(
                fake, RUN_ID, sleep=lambda _:None, polls=2,
                authenticated_lease=authenticated)
        self.assertFalse(any(isinstance(event, tuple) and event[0] == 'write-vram'
                             for event in fake.events))

    def test_schema3_perform_recovery_records_two_exact_lifetime_observations(self):
        tool = self.tool
        fake = FakeTransport(tool)
        evidence, _, _, lifetime_raw = make_v3_evidence(tool, fake)
        states = iter([self.state(), self.state()])
        result = tool.perform_recovery(
            'boot-A', RUN_ID, lambda:next(states), lambda:fake,
            lambda cursor=None:('cursor-2', [], []), sleep=lambda _:None, polls=2,
            lease_evidence=evidence, recovery_lease_schema=3)

        proof = result['gc_quiesce']['reservation']
        self.assertEqual(result['recovery_lease_schema'], 3)
        self.assertTrue(tool.valid_v3_lease_proof(proof, RUN_ID))
        self.assertEqual(proof['lifetime_readbacks'], {
            'authenticated': lifetime_raw.hex(),
            'pre_scratch': lifetime_raw.hex(),
        })
        for path in (
                ('lifetime_readbacks', 'authenticated'),
                ('lifetime_readbacks', 'pre_scratch'),
                ('lifetime_status', 'checksum'),
                ('lifetime_status', 'reason')):
            with self.subTest(path=path):
                changed = json.loads(json.dumps(proof))
                container = changed[path[0]]
                container[path[1]] = (False if path == ('lifetime_status', 'reason')
                                       else container[path[1]] ^ 1
                                       if isinstance(container[path[1]], int)
                                       else '0' * 176)
                self.assertFalse(tool.valid_v3_lease_proof(changed, RUN_ID))

    def test_schema3_recover_rejects_schema2_helper_map_before_host_access(self):
        tool = self.tool
        with tempfile.TemporaryDirectory() as temp, patch.object(
                tool, 'host_state') as host_state:
            with self.assertRaisesRegex(tool.RecoveryError, 'recovery helper hashes'):
                tool.recover(
                    Path(temp), RUN_ID, lease_evidence=object(),
                    recovery_helpers_sha256=tool.current_recovery_helpers_sha256(2),
                    recovery_lease_schema=3)
            host_state.assert_not_called()

    def test_native_schema_zero_and_boolean_refuse_before_transport_access(self):
        tool = self.tool
        for schema in (0, False, True, 4):
            with self.subTest(schema=schema):
                opens = []
                with self.assertRaisesRegex(
                        tool.RecoveryError, 'recovery lease schema must be 2 or 3'):
                    tool.perform_recovery(
                        'boot-A', RUN_ID, lambda:self.state(),
                        lambda:opens.append(True),
                        lambda cursor=None:('cursor-2', [], []),
                        lease_evidence=object(), recovery_lease_schema=schema)
                self.assertEqual(opens, [])

    def test_v2_recover_receipt_preserves_validated_helper_hashes(self):
        tool = self.tool
        helpers = tool.current_recovery_helpers_sha256()
        lease_evidence = object()
        with tempfile.TemporaryDirectory() as temp:
            vm = Path(temp)
            (vm / 'run/used-gpu-boots').mkdir(parents=True)
            (vm / 'run/used-gpu-boots/boot-A.json').write_text(json.dumps({
                'boot_id':'boot-A', 'launches':[{'run_id':RUN_ID}],
            }))
            recovered = {
                'schema':6, 'status':'recovered', 'authorizes_launch':True,
                'boot_id':'boot-A', 'prior_run_id':RUN_ID,
            }
            with patch.object(tool, 'host_state', return_value=self.state()), \
                 patch.object(tool, 'perform_recovery', return_value=recovered) as perform:
                receipt = tool.recover(
                    vm, RUN_ID, lease_evidence=lease_evidence,
                    recovery_helpers_sha256=helpers)

            self.assertEqual(receipt['recovery_helpers_sha256'], helpers)
            self.assertEqual(perform.call_args.kwargs, {
                'lease_evidence':lease_evidence,
                'recovery_helpers_sha256':helpers,
            })

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

    def test_allocator_uses_one_native_enable_and_no_six_byte_ready_route(self):
        source = (ROOT/'src/RaphaelGPU.cpp').read_text()
        self.assertNotIn('wrapHwMemSetVSReady', source)
        self.assertNotIn('kOffHwMemSetVSReady', source)
        self.assertNotIn('orgHwMemSetVSReady', source)
        start = source.index('static bool wrapHwMemEnable(void *self) {')
        end = source.index('\n}\n', start) + 2
        body = source[start:end]
        self.assertEqual(body.count(
            'FunctionCast(wrapHwMemEnable, orgHwMemEnable)(self)'), 3)
        self.assertNotIn('wrapHwMemEnable(self);', source)
        self.assertIn('RaphaelRecoveryV2::establishPools(', body)
        self.assertIn('publishRecoveryPoolStatus(status)', body)

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

    def test_prepare_launch_resume_requires_exact_pending_before_republication(self):
        tool = self.tool
        fake = FakeTransport(tool)
        fake.vram.clear()
        pending = tool.host_kiq_reservation_descriptor(
            RUN_ID, tool.HOST_KIQ_RESERVATION_PENDING)
        fake.vram.update((tool.HOST_KIQ_RESERVATION_OFFSET+n, value)
                         for n, value in enumerate(pending))
        states = iter([self.state(), self.state()])
        evidence = tool.prepare_launch(
            'boot-A', RUN_ID, lambda:next(states), lambda:fake,
            expected_pending=True)
        self.assertEqual(evidence['prior_pending']['run_id'], RUN_ID)
        self.assertEqual(evidence['prior_pending']['state'],
                         tool.HOST_KIQ_RESERVATION_PENDING)
        writes = [event for event in fake.events if isinstance(event, tuple) and
                  event[0] == 'write-vram']
        self.assertEqual(writes, [('write-vram', tool.HOST_KIQ_RESERVATION_OFFSET,
                                  tool.HOST_KIQ_RESERVATION_SIZE)])

        absent = FakeTransport(tool); absent.vram.clear()
        with self.assertRaisesRegex(tool.RecoveryError, 'reservation launch nonce'):
            tool.prepare_launch('boot-A', RUN_ID, lambda:self.state(), lambda:absent,
                                expected_pending=True)
        self.assertFalse(any(isinstance(event, tuple) and event[0] == 'write-vram'
                             for event in absent.events))

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

    def test_host_kiq_rejects_runtime_gart_overlap_before_any_vram_write(self):
        tool = self.tool
        physical_fb = 0x840000000
        for label, offset in (
                ('descriptor', tool.HOST_KIQ_RESERVATION_OFFSET),
                ('scratch', tool.HOST_KIQ_RING_OFFSET)):
            with self.subTest(label=label):
                fake = FakeTransport(tool)
                root = physical_fb + offset
                fake.registers.update({
                    tool.GCMC_VM_FB_LOCATION_BASE_OFFSET: 0xf400,
                    tool.GCMC_VM_FB_LOCATION_TOP_OFFSET: 0xf41f,
                    tool.GCMC_VM_FB_OFFSET_OFFSET: physical_fb >> 24,
                    tool.GCVM_CONTEXT0_CNTL_OFFSET: 1,
                    tool.GCVM_CONTEXT0_PTB_LO_OFFSET: (root & 0xffffffff) | 1,
                    tool.GCVM_CONTEXT0_PTB_HI_OFFSET: root >> 32,
                    tool.GCVM_CONTEXT0_START_LO_OFFSET: 0,
                    tool.GCVM_CONTEXT0_END_LO_OFFSET: 0,
                })
                with self.assertRaisesRegex(tool.RecoveryError, 'GART page table'):
                    tool.retire_legacy_gfx_with_host_kiq(
                        fake, RUN_ID, sleep=lambda _:None, polls=2)
                self.assertFalse(any(isinstance(event, tuple) and
                                     event[0] == 'write-vram'
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
        self.assertFalse(any(isinstance(event, tuple) and event[0] == 'write-vram'
                             for event in fake.events))

    def test_recovery_preflights_gart_before_consuming_reservation(self):
        tool = self.tool
        physical_fb = 0x840000000
        cases = (
            ('descriptor-overlap', {
                tool.GCVM_CONTEXT0_PTB_LO_OFFSET:
                    (physical_fb + tool.HOST_KIQ_RESERVATION_OFFSET) & 0xffffffff | 1,
                tool.GCVM_CONTEXT0_PTB_HI_OFFSET:
                    (physical_fb + tool.HOST_KIQ_RESERVATION_OFFSET) >> 32,
            }),
            ('scratch-overlap', {
                tool.GCVM_CONTEXT0_PTB_LO_OFFSET:
                    (physical_fb + tool.HOST_KIQ_RING_OFFSET) & 0xffffffff | 1,
                tool.GCVM_CONTEXT0_PTB_HI_OFFSET:
                    (physical_fb + tool.HOST_KIQ_RING_OFFSET) >> 32,
            }),
            ('malformed-root', {
                tool.GCVM_CONTEXT0_PTB_LO_OFFSET: 0x12345001,
                tool.GCVM_CONTEXT0_PTB_HI_OFFSET: 0x2,
            }),
        )
        for label, root in cases:
            with self.subTest(label=label):
                fake = FakeTransport(tool)
                fake.registers.update({
                    tool.GCMC_VM_FB_LOCATION_BASE_OFFSET: 0xf400,
                    tool.GCMC_VM_FB_LOCATION_TOP_OFFSET: 0xf41f,
                    tool.GCMC_VM_FB_OFFSET_OFFSET: physical_fb >> 24,
                    tool.GCVM_CONTEXT0_CNTL_OFFSET: 1,
                    tool.GCVM_CONTEXT0_START_LO_OFFSET: 0,
                    tool.GCVM_CONTEXT0_END_LO_OFFSET: 0,
                    tool.CP_RB_ACTIVE_OFFSET: 1,
                    tool.CP_RB_DOORBELL_CONTROL_OFFSET: 0xc0000400,
                })
                fake.registers.update(root)
                with self.assertRaisesRegex(tool.RecoveryError, 'GART'):
                    tool.perform_recovery(
                        'boot-A', RUN_ID, lambda:self.state(), lambda:fake,
                        lambda cursor=None:('cursor-2', [], []),
                        sleep=lambda _:None, polls=2)
                self.assertFalse(any(isinstance(event, tuple) and
                                     event[0] == 'write-vram'
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
        reservation = tool.consume_host_kiq_reservation(fake, RUN_ID)
        fake.flush_hdp = lambda:(_ for _ in ()).throw(tool.RecoveryError('bad HDP'))
        with self.assertRaisesRegex(tool.RecoveryError, 'bad HDP') as raised:
            tool.retire_legacy_gfx_with_host_kiq(
                fake, RUN_ID, sleep=lambda _:None, polls=2,
                reservation_proof=reservation)
        self.assertIsNone(raised.exception.evidence['terminal_poll'])
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

    def test_host_kiq_clean_failure_preserves_terminal_and_cleanup_evidence(self):
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
            tool.GCMC_VM_FB_OFFSET_OFFSET: 0x840,
            tool.CP_RB_DOORBELL_CONTROL_OFFSET: 0xc0000400,
        })
        with self.assertRaisesRegex(tool.RecoveryError, 'completion fence') as raised:
            tool.retire_legacy_gfx_with_host_kiq(
                fake, RUN_ID, sleep=lambda _:None, polls=2)

        evidence = raised.exception.evidence
        self.assertEqual(evidence['aperture'], {
            'base': 0xf400000000, 'size': 0x20000000})
        self.assertEqual(evidence['addresses']['ring'], 0xf40f100000)
        self.assertEqual(evidence['addresses']['mqd'], 0xf40f110000)
        self.assertEqual(evidence['addresses']['fence'], 0xf40f113000)
        self.assertEqual(evidence['packet'], {
            'unmap': list(tool.HOST_KIQ_UNMAP_GFX),
            'write_fence': list(tool.HOST_KIQ_WRITE_FENCE),
            'ring_used_dwords': tool.HOST_KIQ_RING_USED_DWORDS,
        })
        self.assertEqual(evidence['terminal_poll'], {
            'polls': 2,
            'rptr': tool.HOST_KIQ_RING_USED_DWORDS,
            'report': 0,
            'fence': 0,
        })
        self.assertEqual(evidence['hdp_read_invalidate'], {
            'count': 2,
            'last': {
                'register': tool.HDP_READ_CACHE_INVALIDATE_OFFSET,
                'trigger': 1,
                'posted_read': 1,
            },
        })
        self.assertIsInstance(evidence['fence_sequence'], int)
        self.assertNotEqual(evidence['fence_sequence'], 0)
        self.assertEqual(evidence['cleanup']['errors'], [])
        self.assertEqual(evidence['cleanup']['readbacks'], {
            'mec_cntl': tool.CP_MEC_HALT_MASK,
            'hqd_active': 0,
            'hqd_doorbell': 0,
            'hqd_rptr': 0,
            'hqd_wptr_lo': 0,
            'hqd_wptr_hi': 0,
            'pq_status': 0,
            'doorbell_range_lower': 0,
            'doorbell_range_upper': 0,
            'wptr_poll_cntl': 0,
        })

    def test_host_kiq_combined_failure_preserves_wptr_readback_and_error(self):
        tool = self.tool

        class MissingFenceAndStickyWptr(FakeTransport):
            def __init__(self):
                super().__init__(tool)
                self.wptr_zero_writes = 0

            def ring_doorbell64(self, index, value):
                self.events.append(('doorbell64', index, value))
                self.registers[tool.CP_HQD_PQ_RPTR_OFFSET] = value
                self.registers[tool.CP_RB_ACTIVE_OFFSET] = 0

            def write32(self, offset, value):
                if offset == tool.CP_HQD_PQ_WPTR_LO_OFFSET and value == 0:
                    self.wptr_zero_writes += 1
                super().write32(offset, value)

            def read32(self, offset):
                if (offset == tool.CP_HQD_PQ_WPTR_LO_OFFSET and
                        self.wptr_zero_writes >= 2):
                    self.events.append(('read', offset))
                    return tool.HOST_KIQ_RING_USED_DWORDS
                return super().read32(offset)

        fake = MissingFenceAndStickyWptr()
        fake.registers.update({
            tool.GCMC_VM_FB_LOCATION_BASE_OFFSET: 0xf400,
            tool.GCMC_VM_FB_LOCATION_TOP_OFFSET: 0xf41f,
            tool.GCMC_VM_FB_OFFSET_OFFSET: 0x840,
            tool.CP_RB_DOORBELL_CONTROL_OFFSET: 0xc0000400,
        })
        with self.assertRaisesRegex(
                tool.RecoveryError,
                'completion fence.*host KIQ cleanup failed.*wptr did not clear') as raised:
            tool.retire_legacy_gfx_with_host_kiq(
                fake, RUN_ID, sleep=lambda _:None, polls=2)

        evidence = raised.exception.evidence
        self.assertEqual(evidence['terminal_poll']['rptr'],
                         tool.HOST_KIQ_RING_USED_DWORDS)
        self.assertEqual(evidence['terminal_poll']['report'], 0)
        self.assertEqual(evidence['terminal_poll']['fence'], 0)
        self.assertEqual(evidence['cleanup']['readbacks']['hqd_wptr_lo'],
                         tool.HOST_KIQ_RING_USED_DWORDS)
        self.assertIsNone(evidence['cleanup']['readbacks']['hqd_wptr_hi'])
        self.assertEqual(evidence['cleanup']['errors'], [
            'verify host KIQ wptr clear: RecoveryError: '
            'host KIQ wptr did not clear'])

    def test_host_kiq_failure_keeps_raw_rptr_when_only_report_completed(self):
        tool = self.tool

        class ReportOnlyAndStickyWptr(FakeTransport):
            def __init__(self):
                super().__init__(tool)
                self.selector = 0
                self.hqd_active = 0
                self.wptr_zero_writes = 0

            def read32(self, offset):
                if offset == tool.CP_HQD_ACTIVE_OFFSET:
                    return self.hqd_active if self.selector == tool.HOST_KIQ_SELECTOR else 0
                if offset == tool.CP_HQD_PQ_RPTR_OFFSET:
                    self.events.append(('read', offset))
                    return 0
                if (offset == tool.CP_HQD_PQ_WPTR_LO_OFFSET and
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
                if offset == tool.CP_HQD_PQ_WPTR_LO_OFFSET and value == 0:
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

        fake = ReportOnlyAndStickyWptr()
        fake.registers.update({
            tool.GCMC_VM_FB_LOCATION_BASE_OFFSET: 0xf400,
            tool.GCMC_VM_FB_LOCATION_TOP_OFFSET: 0xf41f,
            tool.GCMC_VM_FB_OFFSET_OFFSET: 0x840,
            tool.CP_RB_DOORBELL_CONTROL_OFFSET: 0xc0000400,
        })
        with self.assertRaisesRegex(
                tool.RecoveryError, 'host KIQ cleanup failed.*wptr did not clear') as raised:
            tool.retire_legacy_gfx_with_host_kiq(
                fake, RUN_ID, sleep=lambda _:None, polls=2)

        terminal = raised.exception.evidence['terminal_poll']
        self.assertEqual(terminal['rptr'], 0)
        self.assertEqual(terminal['report'], tool.HOST_KIQ_RING_USED_DWORDS)
        self.assertEqual(terminal['fence'],
                         raised.exception.evidence['fence_sequence'])
        self.assertEqual(terminal['polls'], 1)

    def test_host_kiq_failure_evidence_survives_recovery_and_cannot_authorize(self):
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
            tool.GCMC_VM_FB_OFFSET_OFFSET: 0x840,
            tool.CP_RB_ACTIVE_OFFSET: 1,
            tool.CP_RB_DOORBELL_CONTROL_OFFSET: 0xc0000400,
            tool.CP_RB0_WPTR_OFFSET: 0x80,
            tool.CP_RB0_BASE_OFFSET: 0x00bfe000,
            tool.CP_RB0_BASE_HI_OFFSET: 0xf4,
            tool.CP_RB0_CNTL_OFFSET: 0x00a00e10,
        })
        states = iter([self.state(), self.state()])
        result = tool.perform_recovery(
            'boot-A', RUN_ID, lambda:next(states), lambda:fake,
            lambda cursor=None:('cursor-2', [], []), sleep=lambda _:None, polls=2)

        self.assertEqual(result['status'], 'incomplete')
        self.assertFalse(result['authorizes_launch'])
        host_kiq = result['gc_quiesce']['host_kiq']
        self.assertEqual(host_kiq['status'], 'failed')
        self.assertIn('completion fence', host_kiq['error'])
        self.assertEqual(host_kiq['evidence']['terminal_poll']['rptr'],
                         tool.HOST_KIQ_RING_USED_DWORDS)
        self.assertEqual(host_kiq['evidence']['terminal_poll']['fence'], 0)
        self.assertFalse(result['gc_quiesce']['gfx_retirement_confirmed'])

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

    def test_host_kiq_invalidates_stale_hdp_reads_before_completion_values(self):
        tool = self.tool

        class StaleHdpTransport(FakeTransport):
            def __init__(self):
                super().__init__(tool)
                self.selector = 0
                self.hqd_active = 0
                self.gpu_values = {}
                self.hdp_invalidated = False

            def read32(self, offset):
                if offset == tool.CP_HQD_ACTIVE_OFFSET:
                    return self.hqd_active if self.selector == tool.HOST_KIQ_SELECTOR else 0
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
                self.events.append(('doorbell64', index, value))
                sequence = self.read_vram32(
                    tool.HOST_KIQ_RING_OFFSET +
                    tool.HOST_KIQ_FENCE_SEQUENCE_DWORD * 4)
                self.gpu_values[tool.HOST_KIQ_RPTR_OFFSET] = value
                self.gpu_values[tool.HOST_KIQ_FENCE_OFFSET] = sequence
                self.registers[tool.CP_HQD_PQ_RPTR_OFFSET] = value
                self.registers[tool.CP_RB_ACTIVE_OFFSET] = 0

            def invalidate_hdp_read_cache(self):
                self.events.append('hdp-read-invalidate')
                self.hdp_invalidated = True
                return {'register': tool.HDP_READ_CACHE_INVALIDATE_OFFSET,
                        'trigger': 1, 'posted_read': 1}

            def read_vram32(self, offset):
                if offset in (tool.HOST_KIQ_RPTR_OFFSET,
                              tool.HOST_KIQ_FENCE_OFFSET):
                    self.events.append(('read-gpu-vram', offset,
                                        self.hdp_invalidated))
                    if self.hdp_invalidated:
                        return self.gpu_values.get(offset, 0)
                return super().read_vram32(offset)

        fake = StaleHdpTransport()
        fake.registers.update({
            tool.GCMC_VM_FB_LOCATION_BASE_OFFSET: 0xf400,
            tool.GCMC_VM_FB_LOCATION_TOP_OFFSET: 0xf41f,
            tool.CP_RB_DOORBELL_CONTROL_OFFSET: 0xc0000400,
            tool.CP_MEC_CNTL_OFFSET: tool.CP_MEC_HALT_MASK,
        })
        result = tool.retire_legacy_gfx_with_host_kiq(
            fake, RUN_ID, sleep=lambda _:None, polls=2)

        self.assertEqual(result['status'], 'retired')
        self.assertEqual(fake.events.count('hdp-read-invalidate'), 1)
        invalidate = fake.events.index('hdp-read-invalidate')
        report = fake.events.index(
            ('read-gpu-vram', tool.HOST_KIQ_RPTR_OFFSET, True))
        fence = fake.events.index(
            ('read-gpu-vram', tool.HOST_KIQ_FENCE_OFFSET, True))
        self.assertLess(invalidate, report)
        self.assertLess(report, fence)

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
        self.assertTrue(gc['graphics_pipe_proof_complete'])
        self.assertEqual([row['intended_pipe'] for row in
                          gc['graphics_pipe_guard']['snapshot']['pipes']],
                         [0, 1])
        self.assertEqual([row['intended_pipe'] for row in
                          gc['graphics_pipes_before']['pipes']], [0, 1])
        self.assertEqual([row['intended_pipe'] for row in
                          gc['graphics_pipes_after_retirement']['pipes']],
                         [0, 1])
        self.assertEqual([row['intended_pipe'] for row in
                          gc['graphics_pipes_final']['pipes']], [0, 1])
        self.assertEqual(gc['host_kiq']['graphics_pipes_after_unmap'],
                         gc['graphics_pipes_after_retirement'])
        self.assertEqual(gc['graphics_pipes_final']['pipes'][1]['active'], 0)
        self.assertEqual(gc['graphics_pipes_final']['pipes'][1]['doorbell_status'], 0)
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
        self.assertEqual(experiment.validate_reuse_receipt(
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
        writes_before_consume = [event for event in fake.events[:consume]
                                 if isinstance(event, tuple) and event[0] == 'write']
        self.assertTrue(writes_before_consume)
        self.assertTrue(all(event[1] == tool.GRBM_GFX_CNTL_OFFSET
                            for event in writes_before_consume))
        first_engine_write = next(index for index, event in enumerate(fake.events)
                                  if isinstance(event, tuple) and event[0] == 'write' and
                                  event[1] not in (tool.GRBM_GFX_CNTL_OFFSET,
                                                   tool.C2PMSG_64_OFFSET))
        self.assertLess(consume, first_engine_write)
        self.assertEqual(sum(event == ('write-vram', tool.HOST_KIQ_RESERVATION_OFFSET,
                                      tool.HOST_KIQ_RESERVATION_SIZE)
                             for event in fake.events), 1)

    def test_pipe1_guard_rejects_live_state_without_consuming_active_reservation(self):
        tool = self.tool
        for label, active, doorbell in (
                ('active', 1, 0),
                ('enabled', 0, tool.CP_RB_DOORBELL_ENABLE_MASK | 0x408),
                ('hit', 0, tool.CP_RB_DOORBELL_HIT_MASK | 0x408),
                ('bif-drop', 0, tool.CP_RB_DOORBELL_BIF_DROP_MASK | 0x408)):
            with self.subTest(label=label):
                fake = FakeTransport(tool)
                fake.registers[tool.CP_RB1_ACTIVE_OFFSET] = active
                fake.pipe1_doorbell = doorbell
                expected = tool.host_kiq_reservation_descriptor(
                    RUN_ID, tool.HOST_KIQ_RESERVATION_ACTIVE)
                with self.assertRaisesRegex(tool.RecoveryError,
                                             'graphics pipe 1.*unsupported'):
                    tool.perform_recovery(
                        'boot-A', RUN_ID, lambda:self.state(), lambda:fake,
                        lambda cursor=None:('cursor-2', [], []),
                        sleep=lambda _:None, polls=2)
                observed = bytes(fake.vram.get(tool.HOST_KIQ_RESERVATION_OFFSET + n, 0)
                                 for n in range(len(expected)))
                self.assertEqual(observed, expected)
                self.assertFalse(any(isinstance(event, tuple) and
                                     event[0] == 'write-vram'
                                     for event in fake.events))
                writes = [event for event in fake.events
                          if isinstance(event, tuple) and event[0] == 'write']
                self.assertTrue(writes)
                self.assertTrue(all(event[1] == tool.GRBM_GFX_CNTL_OFFSET
                                    for event in writes))
                self.assertEqual(fake.gfx_selector, 0)

    def test_pipe1_guard_records_stale_programming_as_observation_only(self):
        tool = self.tool
        fake = FakeTransport(tool)
        fake.registers.update({
            tool.CP_RB1_WPTR_OFFSET: 0x80,
            tool.CP_RB1_BASE_OFFSET: 0x123400,
            tool.CP_RB1_BASE_HI_OFFSET: 0xf4,
            tool.CP_RB1_CNTL_OFFSET: 0xa00e10,
        })
        guard = tool.guard_apple_graphics_pipes(fake, RUN_ID)
        pipe1 = guard['snapshot']['pipes'][1]
        self.assertTrue(guard['reservation_unchanged'])
        self.assertTrue(guard['pipe1_supported_state'])
        self.assertEqual(pipe1['active'], 0)
        self.assertEqual(pipe1['doorbell_status'], 0)
        self.assertEqual(pipe1['base'], 0x123400)
        self.assertEqual(pipe1['base_hi'], 0xf4)
        self.assertEqual(pipe1['cntl'], 0xa00e10)
        self.assertEqual(fake.gfx_selector, 0)
        self.assertFalse(any(event == ('read', tool.GRBM_GFX_CNTL_OFFSET)
                             for event in fake.events))
        self.assertEqual([event for event in fake.events
                          if isinstance(event, tuple) and event[:2] ==
                          ('write', tool.GRBM_GFX_CNTL_OFFSET)][-1],
                         ('write', tool.GRBM_GFX_CNTL_OFFSET, 0))

    def test_pipe1_guard_records_ambiguous_off_diagonal_active_without_blocking(self):
        tool = self.tool
        fake = FakeTransport(tool)
        fake.pipe1_rb0_active = 1
        guard = tool.guard_apple_graphics_pipes(fake, RUN_ID)
        pipe1 = guard['snapshot']['pipes'][1]
        self.assertEqual(pipe1['rb0_active'], 1)
        self.assertEqual(pipe1['rb1_active'], 0)
        self.assertTrue(guard['pipe1_supported_state'])

        fake = FakeTransport(tool)
        fake.pipe1_rb0_active = 0xffffffff
        guard = tool.guard_apple_graphics_pipes(fake, RUN_ID)
        self.assertEqual(guard['snapshot']['pipes'][1]['rb0_active'], 0xffffffff)
        self.assertTrue(guard['pipe1_supported_state'])

    def test_pipe1_guard_rejects_all_ones_observation_before_consumption(self):
        tool = self.tool
        fake = FakeTransport(tool)
        fake.registers[tool.CP_RB1_WPTR_OFFSET] = 0xffffffff
        expected = tool.host_kiq_reservation_descriptor(
            RUN_ID, tool.HOST_KIQ_RESERVATION_ACTIVE)
        with self.assertRaisesRegex(tool.RecoveryError, 'inaccessible/all-ones'):
            tool.perform_recovery(
                'boot-A', RUN_ID, lambda:self.state(), lambda:fake,
                lambda cursor=None:('cursor-2', [], []),
                sleep=lambda _:None, polls=2)
        observed = bytes(fake.vram.get(tool.HOST_KIQ_RESERVATION_OFFSET + n, 0)
                         for n in range(len(expected)))
        self.assertEqual(observed, expected)
        self.assertFalse(any(isinstance(event, tuple) and event[0] == 'write-vram'
                             for event in fake.events))

    def test_pipe_guard_rechecks_unchanged_active_descriptor_after_selectors(self):
        tool = self.tool

        class ChangingReservation(FakeTransport):
            def write32(self, offset, value):
                super().write32(offset, value)
                selector_writes = sum(event[:2] == ('write', offset)
                                      for event in self.events
                                      if isinstance(event, tuple))
                if (offset == tool.GRBM_GFX_CNTL_OFFSET and value == 0 and
                        selector_writes == 3):
                    self.vram[tool.HOST_KIQ_RESERVATION_OFFSET] ^= 1

        fake = ChangingReservation(tool)
        with self.assertRaisesRegex(tool.RecoveryError, 'reservation'):
            tool.perform_recovery(
                'boot-A', RUN_ID, lambda:self.state(), lambda:fake,
                lambda cursor=None:('cursor-2', [], []),
                sleep=lambda _:None, polls=2)
        self.assertFalse(any(isinstance(event, tuple) and event[0] == 'write-vram'
                             for event in fake.events))

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
        self.assertEqual(evidence['schema'], 6)
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

    def test_sdma_page_inputs_stop_ib_then_rb_before_halt_and_rlc_is_observed(self):
        tool = self.tool
        fake = FakeTransport(tool)
        fake.registers.update({
            tool.SDMA0_CNTL_OFFSET: tool.SDMA_AUTO_CTXSW_ENABLE_MASK | 0x21,
            tool.SDMA0_GFX_RB_CNTL_OFFSET: 0x80840021,
            tool.SDMA0_GFX_IB_CNTL_OFFSET: 0x101,
            tool.SDMA0_PAGE_RB_CNTL_OFFSET: 0x80840021,
            tool.SDMA0_PAGE_IB_CNTL_OFFSET: 0x101,
            tool.SDMA0_F32_CNTL_OFFSET: 0x20,
        })
        for index, (rb, ib) in enumerate(zip(
                tool.SDMA0_RLC_RB_CNTL_OFFSETS,
                tool.SDMA0_RLC_IB_CNTL_OFFSETS)):
            fake.registers[rb] = 0x200 + index * 4
            fake.registers[ib] = 0x100 + index * 4

        result = tool.quiesce_gc(fake, sleep=lambda _:None, polls=2)

        page_ib_write = ('write', tool.SDMA0_PAGE_IB_CNTL_OFFSET, 0x100)
        page_rb_write = ('write', tool.SDMA0_PAGE_RB_CNTL_OFFSET, 0x80840020)
        halt_write = ('write', tool.SDMA0_F32_CNTL_OFFSET, 0x21)
        page_ib_store = fake.events.index(page_ib_write)
        page_ib_readback = fake.events.index(
            ('read', tool.SDMA0_PAGE_IB_CNTL_OFFSET), page_ib_store + 1)
        page_rb_store = fake.events.index(page_rb_write)
        page_rb_readback = fake.events.index(
            ('read', tool.SDMA0_PAGE_RB_CNTL_OFFSET), page_rb_store + 1)
        sdma_halt = fake.events.index(halt_write)
        self.assertLess(page_ib_store, page_ib_readback)
        self.assertLess(page_ib_readback, page_rb_store)
        self.assertLess(page_rb_store, page_rb_readback)
        self.assertLess(page_rb_readback, sdma_halt)
        self.assertEqual(result['sdma0_shutdown_trace'], [
            {'step': 'disable-page-ib',
             'register': tool.SDMA0_PAGE_IB_CNTL_OFFSET,
             'before': 0x101, 'written': 0x100, 'readback': 0x100},
            {'step': 'disable-page-rb',
             'register': tool.SDMA0_PAGE_RB_CNTL_OFFSET,
             'before': 0x80840021, 'written': 0x80840020,
             'readback': 0x80840020},
        ])
        self.assertEqual(result['sdma0_page_ib_before'], 0x101)
        self.assertEqual(result['sdma0_page_ib_after'], 0x100)
        self.assertEqual(result['sdma0_page_rb_before'], 0x80840021)
        self.assertEqual(result['sdma0_page_rb_after'], 0x80840020)
        self.assertEqual(result['sdma0_status_after'], tool.SDMA_STATUS_IDLE_MASK)
        self.assertEqual(result['sdma0_rlc_inputs'], [
            {'index': index,
             'rb_before': 0x200 + index * 4,
             'rb_after': 0x200 + index * 4,
             'ib_before': 0x100 + index * 4,
             'ib_after': 0x100 + index * 4}
            for index in range(2)
        ])
        for offset in (*tool.SDMA0_RLC_RB_CNTL_OFFSETS,
                       *tool.SDMA0_RLC_IB_CNTL_OFFSETS):
            self.assertFalse(any(event[0] == 'write' and event[1] == offset
                                 for event in fake.events if isinstance(event, tuple)))

    def test_sdma_enabled_rlc_or_nonidle_status_cannot_authorize_schema6(self):
        tool = self.tool
        for label, offset, value in (
                ('rlc-rb', tool.SDMA0_RLC_RB_CNTL_OFFSETS[0], 1),
                ('rlc-ib', tool.SDMA0_RLC_IB_CNTL_OFFSETS[1], 1),
                ('not-idle', tool.SDMA0_STATUS_REG_OFFSET, 0)):
            with self.subTest(label=label):
                fake = FakeTransport(tool)
                fake.registers[offset] = value
                states = iter([self.state(), self.state()])
                evidence = tool.perform_recovery(
                    'boot-A', RUN_ID, lambda:next(states), lambda:fake,
                    lambda cursor=None:('cursor-2', [], []),
                    sleep=lambda _:None, polls=2)
                self.assertEqual(evidence['schema'], 6)
                self.assertEqual(evidence['status'], 'incomplete')
                self.assertFalse(evidence['authorizes_launch'])

    def test_sdma_changed_page_or_rlc_bits_cannot_authorize_schema6(self):
        tool = self.tool

        class ChangedPageReadback(FakeTransport):
            def write32(self, offset, value):
                super().write32(offset, value)
                if offset == tool.SDMA0_PAGE_IB_CNTL_OFFSET:
                    self.registers[offset] = value ^ 0x4

        class ChangedRlcObservation(FakeTransport):
            def write32(self, offset, value):
                super().write32(offset, value)
                if offset == tool.SDMA0_F32_CNTL_OFFSET:
                    self.registers[tool.SDMA0_RLC_RB_CNTL_OFFSETS[0]] = 0x4

        for label, fake in (
                ('page-preserved-bit', ChangedPageReadback(tool)),
                ('rlc-observation', ChangedRlcObservation(tool))):
            with self.subTest(label=label):
                if label == 'page-preserved-bit':
                    fake.registers[tool.SDMA0_PAGE_IB_CNTL_OFFSET] = 0x101
                states = iter([self.state(), self.state()])
                evidence = tool.perform_recovery(
                    'boot-A', RUN_ID, lambda:next(states), lambda:fake,
                    lambda cursor=None:('cursor-2', [], []),
                    sleep=lambda _:None, polls=2)
                self.assertEqual(evidence['schema'], 6)
                self.assertEqual(evidence['status'], 'incomplete')
                self.assertFalse(evidence['authorizes_launch'])

    def test_sdma_all_ones_input_observation_fails_closed_before_writes(self):
        tool = self.tool
        for label, offset in (
                ('control', tool.SDMA0_CNTL_OFFSET),
                ('gfx-rb', tool.SDMA0_GFX_RB_CNTL_OFFSET),
                ('gfx-ib', tool.SDMA0_GFX_IB_CNTL_OFFSET),
                ('page-ib', tool.SDMA0_PAGE_IB_CNTL_OFFSET),
                ('page-rb', tool.SDMA0_PAGE_RB_CNTL_OFFSET),
                ('rlc-rb', tool.SDMA0_RLC_RB_CNTL_OFFSETS[0]),
                ('rlc-ib', tool.SDMA0_RLC_IB_CNTL_OFFSETS[1]),
                ('f32', tool.SDMA0_F32_CNTL_OFFSET),
                ('status', tool.SDMA0_STATUS_REG_OFFSET)):
            with self.subTest(label=label):
                fake = FakeTransport(tool)
                fake.registers[offset] = 0xffffffff
                with self.assertRaisesRegex(tool.RecoveryError,
                                            'SDMA0 .* inaccessible/all-ones'):
                    tool.quiesce_gc(fake, sleep=lambda _:None, polls=2)
                sdma_offsets = {
                    tool.SDMA0_CNTL_OFFSET, tool.SDMA0_GFX_RB_CNTL_OFFSET,
                    tool.SDMA0_GFX_IB_CNTL_OFFSET, tool.SDMA0_PAGE_IB_CNTL_OFFSET,
                    tool.SDMA0_PAGE_RB_CNTL_OFFSET, tool.SDMA0_F32_CNTL_OFFSET,
                }
                self.assertFalse(any(event[0] == 'write' and event[1] in sdma_offsets
                                     for event in fake.events
                                     if isinstance(event, tuple)))

    def test_sdma_ignored_page_input_disable_fails_after_halt(self):
        tool = self.tool

        class StickyPageTransport(FakeTransport):
            def write32(self, offset, value):
                if offset == tool.SDMA0_PAGE_IB_CNTL_OFFSET:
                    self.events.append(('ignored-write', offset, value))
                    return
                super().write32(offset, value)

        fake = StickyPageTransport(tool)
        fake.registers[tool.SDMA0_PAGE_IB_CNTL_OFFSET] = 0x101
        with self.assertRaisesRegex(tool.RecoveryError,
                                    'PAGE indirect buffer would not stop'):
            tool.quiesce_gc(fake, sleep=lambda _:None, polls=2)
        self.assertIn(('ignored-write', tool.SDMA0_PAGE_IB_CNTL_OFFSET, 0x100),
                      fake.events)
        self.assertIn(('write', tool.SDMA0_F32_CNTL_OFFSET,
                       tool.SDMA_HALT_MASK), fake.events)

    def test_sdma_late_all_ones_readback_fails_after_halt(self):
        tool = self.tool

        class LateAllOnesTransport(FakeTransport):
            def __init__(self):
                super().__init__(tool)
                self.page_reads = 0

            def read32(self, offset):
                if offset == tool.SDMA0_PAGE_RB_CNTL_OFFSET:
                    self.page_reads += 1
                    if self.page_reads == 2:
                        self.events.append(('read', offset))
                        return 0xffffffff
                return super().read32(offset)

        fake = LateAllOnesTransport()
        with self.assertRaisesRegex(tool.RecoveryError,
                                    'PAGE RB control is inaccessible/all-ones'):
            tool.quiesce_gc(fake, sleep=lambda _:None, polls=2)
        self.assertIn(('write', tool.SDMA0_F32_CNTL_OFFSET,
                       tool.SDMA_HALT_MASK), fake.events)

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

    def test_pipe1_appearance_after_guard_makes_schema6_receipt_incomplete(self):
        tool = self.tool

        class AppearingPipe1(FakeTransport):
            def __init__(self):
                super().__init__(tool)
                self.pipe1_active_reads = 0

            def read32(self, offset):
                if (offset == tool.CP_RB1_ACTIVE_OFFSET and
                        self.gfx_selector & 0x3 == 1):
                    self.pipe1_active_reads += 1
                    self.events.append(('read', offset))
                    return 1 if self.pipe1_active_reads >= 4 else 0
                return super().read32(offset)

        fake = AppearingPipe1()
        states = iter([self.state(), self.state()])
        result = tool.perform_recovery(
            'boot-A', RUN_ID, lambda:next(states), lambda:fake,
            lambda cursor=None:('cursor-2', [], []), sleep=lambda _:None, polls=2)
        self.assertEqual(result['schema'], 6)
        self.assertEqual(result['status'], 'incomplete')
        self.assertFalse(result['authorizes_launch'])
        gc = result['gc_quiesce']
        self.assertFalse(gc['graphics_pipe_proof_complete'])
        self.assertEqual(gc['graphics_pipes_final']['pipes'][1]['active'], 1)
        self.assertEqual(fake.gfx_selector, 0)

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
            self.assertEqual(experiment.validate_reuse_receipt(
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
