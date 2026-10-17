import importlib.util
import json
import mmap
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT/'findings/recovery-tests/retained-kiq-preparation-175/result.json'


def load_tool():
    path = ROOT/'tools/retained-kiq-doorbell-zero.py'
    spec = importlib.util.spec_from_file_location('retained_kiq_doorbell_zero', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeClock:
    def __init__(self, step=250_000):
        self.value, self.step = 0, step

    def __call__(self):
        self.value += self.step
        return self.value


class FakeTransport:
    def __init__(self, tool, expected, *, latch=True):
        self.tool, self.selector, self.latch = tool, 0, latch
        self.selectors, self.reads = [], []
        self.write_log, self.doorbell_log = [], []
        scan = expected['passes'][0]
        self.values = {}
        for name, offset in tool.SCANNER.GLOBAL_OFFSETS.items():
            self.values[(0, offset)] = scan['globals'][name]
        for row in scan['compute']:
            selector = row['selector']
            self.values[(selector, tool.RECOVERY.CP_HQD_ACTIVE_OFFSET)] = row['active']
            self.values[(selector, tool.RECOVERY.CP_HQD_PQ_DOORBELL_OFFSET)] = \
                row['pq_doorbell_control']
            if selector == tool.RECOVERY.HOST_KIQ_SELECTOR:
                for name, offset in tool.SCANNER.HOST_KIQ_DETAIL_OFFSETS.items():
                    self.values[(selector, offset)] = row['host_kiq'][name]
        for row, descriptor in zip(
                scan['graphics']['pipes'], tool.RECOVERY.GRAPHICS_PIPE_DESCRIPTORS):
            _, selector, _, wptr, wptr_hi, base, base_hi, cntl = descriptor
            for offset, name in (
                    (tool.RECOVERY.CP_RB_DOORBELL_CONTROL_OFFSET, 'doorbell_control'),
                    (tool.RECOVERY.CP_RB_ACTIVE_OFFSET, 'rb0_active'),
                    (tool.RECOVERY.CP_RB1_ACTIVE_OFFSET, 'rb1_active'),
                    (wptr, 'wptr'), (wptr_hi, 'wptr_hi'), (base, 'base'),
                    (base_hi, 'base_hi'), (cntl, 'cntl')):
                self.values[(selector, offset)] = row[name]

    def __enter__(self): return self
    def __exit__(self, kind, value, traceback): return None

    def select(self, value):
        self.selectors.append(value); self.selector = value

    def read32(self, offset):
        self.reads.append((self.selector, offset))
        key = ((0, offset) if offset in self.tool.SCANNER.GLOBAL_OFFSETS.values()
               else (self.selector, offset))
        return self.values[key]

    def write_control(self, operation, offset, value):
        key = ((0, offset) if offset == self.tool.RECOVERY.CP_PQ_STATUS_OFFSET
               else (self.selector, offset))
        before = self.values[key]
        self.values[key] = value
        row = {'operation': operation, 'offset': offset, 'value': value,
               'observed_before': before, 'posted': value,
               'attempted': True, 'store_completed': True, 'completed': True}
        self.write_log.append(row)
        return value

    def ring_doorbell64(self, index, value):
        self.doorbell_log.append({'index': index, 'value': value,
                                  'attempted': True, 'store_completed': True,
                                  'barrier': self.tool.RECOVERY.EXPECTED_CONFIG_MEMSIZE,
                                  'completed': True})
        if self.latch:
            self.values[(9, self.tool.RECOVERY.CP_HQD_PQ_WPTR_LO_OFFSET)] = 0
        return self.tool.RECOVERY.EXPECTED_CONFIG_MEMSIZE

    def metadata(self):
        return {'userspace_mapping': 'BAR2-eight-bytes-and-BAR5-only',
                'userspace_writes': 'fixed-doorbell-zero-transaction-only'}


class RetainedKiqDoorbellZeroTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tool = load_tool()
        cls.tool.RECOVERY.EXPECTED_CONFIG_MEMSIZE = 0x200
        cls.fixture = json.loads(FIXTURE.read_text())['transaction']['after']

    def proof(self):
        return {
            'preparation_proof': {'scanner_proof': {'base': {'journal_cursor': 'c'}}},
            'preparation_errors': [],
            'preparation_result_sha256': self.tool.PREPARATION_RESULT_SHA256,
            'preparation_result_errors': [],
            'tool_source_sha256': 'a'*64,
            'expected_tool_source_sha256': 'a'*64,
            'loaded_preparation_source_sha256': self.tool.PREPARATION_SOURCE_SHA256,
            'current_preparation_source_sha256': self.tool.PREPARATION_SOURCE_SHA256,
            'loaded_ctypes_sha256': self.tool.CTYPES_SHA256,
            'current_ctypes_sha256': self.tool.CTYPES_SHA256,
            'loaded_ctypes_build_id': self.tool.CTYPES_BUILD_ID,
            'current_ctypes_build_id': self.tool.CTYPES_BUILD_ID,
        }

    def test_exact_one_doorbell_store_then_global_first_close_and_full_scan(self):
        tool = self.tool
        fake = FakeTransport(tool, self.fixture)
        result = tool.execute_transaction(fake, self.fixture, FakeClock())
        self.assertEqual([(r['operation'], r['offset'], r['value'])
                          for r in fake.write_log], [
            ('enable-hqd-doorbell', tool.RECOVERY.CP_HQD_PQ_DOORBELL_OFFSET,
             0x40000000),
            ('enable-global-pq-doorbell', tool.RECOVERY.CP_PQ_STATUS_OFFSET, 2),
            ('disable-global-pq-doorbell', tool.RECOVERY.CP_PQ_STATUS_OFFSET, 0),
            ('disable-hqd-doorbell', tool.RECOVERY.CP_HQD_PQ_DOORBELL_OFFSET, 0),
        ])
        self.assertEqual(len(fake.doorbell_log), 1)
        self.assertEqual(fake.doorbell_log[0]['index'], 0)
        self.assertEqual(fake.doorbell_log[0]['value'], 0)
        self.assertEqual(result['interim_samples'][0]['active'], 0)
        self.assertEqual(result['interim_samples'][0]['mec_cntl'],
                         tool.RECOVERY.CP_MEC_HALT_MASK)
        self.assertEqual(result['interim_samples'][0]['wptr_lo'], 0)
        self.assertEqual(result['timing']['observation_budget_ns'], 2_000_000)
        self.assertTrue(result['timing']['started_before_hqd_enable'])
        self.assertEqual(result['gate_open_elapsed_ns'],
                         result['timing']['through_global_close_ns'])
        self.assertEqual(len(result['after']['passes']), 2)
        selector9 = next(row for row in result['after']['passes'][0]['compute']
                         if row['selector'] == 9)
        self.assertEqual(selector9['host_kiq']['wptr_lo'], 0)
        self.assertEqual(selector9['pq_doorbell_control'], 0)
        self.assertEqual(result['status'], 'doorbell-wptr-cleared-nonauthorizing')
        self.assertFalse(result['authorizes_launch'])
        self.assertFalse(result['authorizes_recovery'])
        self.assertFalse(result['authorizes_cleanup'])

    def test_gate_timing_starts_before_first_enable_store(self):
        tool = self.tool; clock = FakeClock()
        class Timed(FakeTransport):
            def write_control(inner, operation, offset, value):
                if operation == 'enable-hqd-doorbell' and clock.value == 0:
                    raise AssertionError('gate timing started too late')
                return super().write_control(operation, offset, value)
        result = tool.execute_transaction(Timed(tool, self.fixture), self.fixture,
                                          clock)
        self.assertGreater(result['gate_open_elapsed_ns'], 0)

    def test_ignored_store_fails_after_bounded_observation_and_full_scan(self):
        fake = FakeTransport(self.tool, self.fixture, latch=False)
        with self.assertRaisesRegex(self.tool.DoorbellZeroError,
                                    'WPTR remained') as raised:
            self.tool.execute_transaction(fake, self.fixture, FakeClock(500_000))
        evidence = raised.exception.evidence
        self.assertEqual(len(fake.doorbell_log), 1)
        self.assertGreaterEqual(len(evidence['interim_samples']), 1)
        self.assertLessEqual(len(evidence['interim_samples']), 5)
        self.assertGreaterEqual(evidence['gate_open_elapsed_ns'], 0)
        self.assertEqual([row['operation'] for row in fake.write_log][-2:],
                         ['disable-global-pq-doorbell', 'disable-hqd-doorbell'])
        self.assertEqual(len(evidence['after']['passes']), 2)
        self.assertFalse(evidence['authorizes_launch'])

    def test_pre_scan_change_refuses_all_nonselector_writes(self):
        fake = FakeTransport(self.tool, self.fixture)
        fake.values[(9, self.tool.RECOVERY.CP_HQD_ACTIVE_OFFSET)] = 1
        with self.assertRaisesRegex(self.tool.DoorbellZeroError,
                                    'pre-scan') as raised:
            self.tool.execute_transaction(fake, self.fixture, FakeClock())
        self.assertEqual(fake.write_log, [])
        self.assertEqual(fake.doorbell_log, [])
        self.assertEqual(len(raised.exception.evidence['before']['passes']), 2)

    def test_each_interim_sample_rejects_active_or_unhalted_before_more_reads(self):
        tool = self.tool
        for offset, value, message in (
                (tool.RECOVERY.CP_HQD_ACTIVE_OFFSET, 1, 'ACTIVE'),
                (tool.RECOVERY.CP_MEC_CNTL_OFFSET, 0, 'MEC halt')):
            fake = FakeTransport(tool, self.fixture)
            original = fake.read32
            def changed(at, original=original, offset=offset, value=value):
                if fake.doorbell_log and at == offset:
                    result = value
                    fake.reads.append((fake.selector, at))
                    return result
                return original(at)
            fake.read32 = changed
            with self.subTest(offset=offset), self.assertRaisesRegex(
                    tool.DoorbellZeroError, message) as raised:
                tool.execute_transaction(fake, self.fixture, FakeClock())
            self.assertEqual(len(fake.doorbell_log), 1)
            self.assertEqual([r['operation'] for r in fake.write_log][-2:],
                             ['disable-global-pq-doorbell', 'disable-hqd-doorbell'])
            self.assertIn('after', raised.exception.evidence)

    def test_interim_read_and_both_close_failures_preserve_all_evidence(self):
        tool = self.tool
        class Broken(FakeTransport):
            def read32(inner, offset):
                if inner.doorbell_log and offset == tool.RECOVERY.CP_HQD_PQ_WPTR_LO_OFFSET:
                    raise OSError('interim read broke')
                return super().read32(offset)
            def write_control(inner, operation, offset, value):
                if operation in ('disable-global-pq-doorbell', 'disable-hqd-doorbell'):
                    inner.write_log.append({'operation': operation, 'offset': offset,
                                            'value': value, 'attempted': True,
                                            'completed': False, 'error': operation+' broke'})
                    raise OSError(operation+' broke')
                return super().write_control(operation, offset, value)
        fake = Broken(tool, self.fixture)
        with self.assertRaisesRegex(tool.DoorbellZeroError,
                                    'interim read broke.*global.*hqd') as raised:
            tool.execute_transaction(fake, self.fixture, FakeClock())
        evidence = raised.exception.evidence
        self.assertIn('wptr_lo', evidence['interim_samples'][0].get('error_field', 'wptr_lo'))
        self.assertEqual([row['operation'] for row in evidence['writes']][-2:],
                         ['disable-global-pq-doorbell', 'disable-hqd-doorbell'])
        self.assertFalse(evidence['gate_close']['global']['completed'])
        self.assertFalse(evidence['gate_close']['hqd']['completed'])
        self.assertTrue(evidence['final_default']['attempted'])
        self.assertIn('after', evidence)

    def test_native_selector_store_posting_failure_still_restores_default(self):
        tool = self.tool
        class Broken(FakeTransport):
            def __init__(inner, *args):
                super().__init__(*args)
                inner.real = tool.DoorbellZeroTransport()
                inner.real.bar0 = bytearray(tool.SCANNER.BAR5_SIZE)
                struct.pack_into('<I', inner.real.bar0,
                                 tool.RECOVERY.NBIO_CONFIG_MEMSIZE_OFFSET,
                                 tool.RECOVERY.EXPECTED_CONFIG_MEMSIZE)
                inner.control_select_failed = False
            def select(inner, value):
                inner.selectors.append(value)
                if len(inner.selectors) == 138 and value == 9:
                    original = inner.real._posting_barrier
                    inner.real._posting_barrier = lambda: (
                        (_ for _ in ()).throw(OSError('selector posting broke')))
                    try:
                        inner.real.select(value)
                    finally:
                        inner.selector = inner.real._selected
                        inner.real._posting_barrier = original
                    return
                inner.real.select(value)
                inner.selector = inner.real._selected
        fake = Broken(tool, self.fixture)
        with self.assertRaisesRegex(tool.DoorbellZeroError,
                                    'selector posting broke') as raised:
            tool.execute_transaction(fake, self.fixture, FakeClock())
        evidence = raised.exception.evidence
        self.assertEqual(fake.selectors[-1], 0)
        self.assertTrue(evidence['final_default']['attempted'])
        self.assertTrue(evidence['final_default']['completed'])
        self.assertEqual(struct.unpack_from(
            '<I', fake.real.bar0, tool.RECOVERY.GRBM_GFX_CNTL_OFFSET)[0], 0)
        self.assertEqual(fake.doorbell_log, [])
        self.assertEqual(fake.write_log, [])

    def test_transport_rejects_wrong_register_value_order_and_repeated_doorbell(self):
        tool = self.tool
        transport = tool.DoorbellZeroTransport()
        transport.bar0 = bytearray(tool.SCANNER.BAR5_SIZE)
        transport.bar2 = bytearray(8)
        transport._selected = 9
        struct.pack_into('<I', transport.bar0,
                         tool.RECOVERY.CP_HQD_PQ_DOORBELL_OFFSET, 0x80000000)
        struct.pack_into('<I', transport.bar0,
                         tool.RECOVERY.NBIO_CONFIG_MEMSIZE_OFFSET,
                         tool.RECOVERY.EXPECTED_CONFIG_MEMSIZE)
        original_raw = transport._raw32
        transport._raw32 = lambda offset: (
            (_ for _ in ()).throw(AssertionError('wrong register was read'))
            if offset == tool.RECOVERY.CP_HQD_ACTIVE_OFFSET else original_raw(offset))
        with self.assertRaisesRegex(tool.DoorbellZeroError, 'forbidden control'):
            transport.write_control('enable-hqd-doorbell',
                                    tool.RECOVERY.CP_HQD_ACTIVE_OFFSET, 1)
        transport._raw32 = original_raw
        with self.assertRaisesRegex(tool.DoorbellZeroError, 'not enabled'):
            transport.ring_doorbell64(0, 0)
        transport.write_control('enable-hqd-doorbell',
                                tool.RECOVERY.CP_HQD_PQ_DOORBELL_OFFSET,
                                0x40000000)
        with self.assertRaisesRegex(tool.DoorbellZeroError, 'forbidden control'):
            transport.write_control('enable-hqd-doorbell',
                                    tool.RECOVERY.CP_HQD_PQ_DOORBELL_OFFSET,
                                    0x40000000)
        with self.assertRaisesRegex(tool.DoorbellZeroError, 'doorbell index/value'):
            transport.ring_doorbell64(1, 0)

    def test_failed_global_close_still_allows_hqd_close_attempt(self):
        tool = self.tool
        transport = tool.DoorbellZeroTransport()
        transport.bar0 = bytearray(tool.SCANNER.BAR5_SIZE)
        transport.bar2 = bytearray(8)
        transport._selected = 9
        struct.pack_into('<I', transport.bar0,
                         tool.RECOVERY.CP_HQD_PQ_DOORBELL_OFFSET, 0x80000000)
        struct.pack_into('<I', transport.bar0,
                         tool.RECOVERY.CP_PQ_STATUS_OFFSET, 0)
        struct.pack_into('<I', transport.bar0,
                         tool.RECOVERY.NBIO_CONFIG_MEMSIZE_OFFSET,
                         tool.RECOVERY.EXPECTED_CONFIG_MEMSIZE)
        transport.write_control('enable-hqd-doorbell',
                                tool.RECOVERY.CP_HQD_PQ_DOORBELL_OFFSET,
                                0x40000000)
        transport.write_control('enable-global-pq-doorbell',
                                tool.RECOVERY.CP_PQ_STATUS_OFFSET, 2)
        transport.ring_doorbell64(0, 0)
        original_raw = transport._raw32
        transport._raw32 = lambda offset: (
            2 if offset == tool.RECOVERY.CP_PQ_STATUS_OFFSET else original_raw(offset))
        with self.assertRaisesRegex(tool.DoorbellZeroError, 'did not read back'):
            transport.write_control('disable-global-pq-doorbell',
                                    tool.RECOVERY.CP_PQ_STATUS_OFFSET, 0)
        transport._raw32 = original_raw
        self.assertEqual(
            transport.write_control('disable-hqd-doorbell',
                                    tool.RECOVERY.CP_HQD_PQ_DOORBELL_OFFSET, 0), 0)

    def test_failed_first_enable_posting_still_allows_both_close_stores(self):
        tool = self.tool
        transport = tool.DoorbellZeroTransport()
        transport.bar0 = bytearray(tool.SCANNER.BAR5_SIZE)
        transport.bar2 = bytearray(8)
        transport._selected = 9
        struct.pack_into('<I', transport.bar0,
                         tool.RECOVERY.CP_HQD_PQ_DOORBELL_OFFSET, 0x80000000)
        struct.pack_into('<I', transport.bar0,
                         tool.RECOVERY.CP_PQ_STATUS_OFFSET, 0)
        struct.pack_into('<I', transport.bar0,
                         tool.RECOVERY.NBIO_CONFIG_MEMSIZE_OFFSET,
                         tool.RECOVERY.EXPECTED_CONFIG_MEMSIZE)
        original_raw = transport._raw32
        hqd_reads = 0
        def fail_posted(offset):
            nonlocal hqd_reads
            if offset == tool.RECOVERY.CP_HQD_PQ_DOORBELL_OFFSET:
                hqd_reads += 1
                if hqd_reads == 2:
                    raise OSError('first enable posting broke')
            return original_raw(offset)
        transport._raw32 = fail_posted
        with self.assertRaisesRegex(OSError, 'first enable posting broke'):
            transport.write_control('enable-hqd-doorbell',
                                    tool.RECOVERY.CP_HQD_PQ_DOORBELL_OFFSET,
                                    0x40000000)
        transport._raw32 = original_raw
        self.assertEqual(
            transport.write_control('disable-global-pq-doorbell',
                                    tool.RECOVERY.CP_PQ_STATUS_OFFSET, 0), 0)
        self.assertEqual(
            transport.write_control('disable-hqd-doorbell',
                                    tool.RECOVERY.CP_HQD_PQ_DOORBELL_OFFSET, 0), 0)
        self.assertEqual([row['operation'] for row in transport.write_log], [
            'enable-hqd-doorbell', 'disable-global-pq-doorbell',
            'disable-hqd-doorbell'])
        self.assertTrue(transport.write_log[0]['store_completed'])
        self.assertFalse(transport.write_log[0]['completed'])

    def test_native_64_store_is_one_aligned_bar2_index_zero_write(self):
        tool = self.tool
        transport = tool.DoorbellZeroTransport()
        transport.bar0 = bytearray(tool.SCANNER.BAR5_SIZE)
        transport.bar2 = bytearray(b'abcdefgh')
        transport._selected = 9
        struct.pack_into('<I', transport.bar0,
                         tool.RECOVERY.CP_HQD_PQ_DOORBELL_OFFSET, 0x80000000)
        struct.pack_into('<I', transport.bar0,
                         tool.RECOVERY.CP_PQ_STATUS_OFFSET, 0)
        struct.pack_into('<I', transport.bar0,
                         tool.RECOVERY.NBIO_CONFIG_MEMSIZE_OFFSET,
                         tool.RECOVERY.EXPECTED_CONFIG_MEMSIZE)
        transport.write_control('enable-hqd-doorbell',
                                tool.RECOVERY.CP_HQD_PQ_DOORBELL_OFFSET,
                                0x40000000)
        transport.write_control('enable-global-pq-doorbell',
                                tool.RECOVERY.CP_PQ_STATUS_OFFSET, 2)
        self.assertEqual(transport.ring_doorbell64(0, 0),
                         tool.RECOVERY.EXPECTED_CONFIG_MEMSIZE)
        self.assertEqual(bytes(transport.bar2), b'\0'*8)
        with self.assertRaisesRegex(tool.DoorbellZeroError, 'already attempted'):
            transport.ring_doorbell64(0, 0)
        self.assertEqual(len(transport.doorbell_log), 1)

    def test_transport_maps_exact_bar5_and_first_eight_bytes_of_bar2_only(self):
        tool = self.tool; opened = iter((10, 11)); indices = []; mappings = []
        class Mapping(bytearray):
            def close(self): pass
        def fake_ioctl(fd, request, argument=0):
            if request == tool.VFIO_GET_API_VERSION: return tool.VFIO_API_VERSION
            if request == tool.VFIO_CHECK_EXTENSION: return 1
            if request == tool.VFIO_GROUP_GET_STATUS:
                argument._obj.flags = tool.VFIO_GROUP_FLAGS_VIABLE; return 0
            if request in (tool.VFIO_GROUP_SET_CONTAINER, tool.VFIO_SET_IOMMU,
                           tool.OBSERVER.VFIO_GROUP_UNSET_CONTAINER): return 0
            if request == tool.VFIO_GROUP_GET_DEVICE_FD: return 12
            if request == tool.VFIO_DEVICE_GET_REGION_INFO:
                index = argument._obj.index; indices.append(index)
                argument._obj.size = (tool.SCANNER.BAR5_SIZE if index == 5
                                      else tool.BAR2_SIZE)
                argument._obj.offset = index << 40
                argument._obj.flags = (tool.VFIO_REGION_INFO_FLAG_READ |
                                       tool.VFIO_REGION_INFO_FLAG_WRITE |
                                       tool.VFIO_REGION_INFO_FLAG_MMAP)
                return 0
            raise AssertionError(hex(request))
        def fake_mmap(fd, length, **kwargs):
            mappings.append((length, kwargs)); return Mapping(length)
        with patch.object(tool.os, 'open', side_effect=lambda *a, **k: next(opened)), \
             patch.object(tool, 'ioctl', side_effect=fake_ioctl), \
             patch.object(tool.mmap, 'mmap', side_effect=fake_mmap), \
             patch.object(tool.os, 'close'):
            transport = tool.DoorbellZeroTransport(); transport.__enter__()
        self.assertEqual(indices, [5, 2])
        self.assertEqual([length for length, _ in mappings],
                         [tool.SCANNER.BAR5_SIZE, 8])
        self.assertTrue(all(kwargs['prot'] == mmap.PROT_READ | mmap.PROT_WRITE
                            for _, kwargs in mappings))
        self.assertNotIn(0, indices)

    def test_invalid_preflight_fails_before_transport_and_consumed_path_refuses(self):
        tool = self.tool
        for key in ('preparation_errors', 'preparation_result_sha256',
                    'preparation_result_errors', 'current_preparation_source_sha256',
                    'loaded_ctypes_sha256', 'current_ctypes_sha256',
                    'loaded_ctypes_build_id', 'current_ctypes_build_id'):
            proof = self.proof(); opened = []
            proof[key] = ['bad'] if key.endswith('errors') else '0'*64
            with tempfile.TemporaryDirectory() as temp, self.assertRaises(
                    tool.DoorbellZeroError):
                tool.run_transaction(
                    lambda proof=proof: proof, lambda: opened.append(True),
                    lambda cursor: self.proof(), Path(temp)/'result.json',
                    self.fixture, FakeClock())
            self.assertEqual(opened, [])
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)/'result.json'; output.write_text('{}')
            with self.assertRaises(FileExistsError):
                tool.run_transaction(self.proof, lambda: None,
                                     lambda cursor: self.proof(), output,
                                     self.fixture, FakeClock())

    def test_capture_close_and_postflight_failures_are_all_durable(self):
        tool = self.tool
        class Broken(FakeTransport):
            def read32(inner, offset):
                if inner.doorbell_log and offset == tool.RECOVERY.CP_HQD_PQ_WPTR_LO_OFFSET:
                    raise OSError('capture broke')
                return super().read32(offset)
            def __exit__(inner, kind, value, traceback):
                raise OSError('close broke')
        fake = Broken(tool, self.fixture)
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)/'result.json'
            with self.assertRaisesRegex(tool.DoorbellZeroError,
                                        'capture broke.*close broke.*postflight'):
                tool.run_transaction(
                    self.proof, lambda: fake,
                    lambda cursor: (_ for _ in ()).throw(OSError('post broke')),
                    output, self.fixture, FakeClock())
            saved = json.loads(output.read_text())
        self.assertIn('capture broke', saved['device_error'])
        self.assertIn('close broke', saved['device_error'])
        self.assertEqual(saved['postflight']['collection_error'], 'OSError: post broke')
        self.assertEqual(len(saved['transaction']['doorbell_writes']), 1)
        self.assertFalse(saved['authorizes_cleanup'])


if __name__ == '__main__': unittest.main()
