import importlib.util
import hashlib
import mmap
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load_tool():
    path = ROOT/'tools/inspect-retained-idle.py'
    spec = importlib.util.spec_from_file_location('inspect_retained_idle', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.RECOVERY.EXPECTED_CONFIG_MEMSIZE = 0x200
    return module


class FakeTransport:
    def __init__(self, tool):
        self.tool = tool
        self.selector = 0
        self.selectors = []
        self.reads = []
        self.values = {offset: 0 for offset in tool.READ_OFFSETS}
        self.values[tool.RECOVERY.CP_ME_CNTL_OFFSET] = tool.RECOVERY.CP_ME_HALT_MASK
        self.values[tool.RECOVERY.CP_MEC_CNTL_OFFSET] = tool.RECOVERY.CP_MEC_HALT_MASK
        self.values[tool.RECOVERY.SDMA0_F32_CNTL_OFFSET] = tool.RECOVERY.SDMA_HALT_MASK
        self.values[tool.SDMA0_STATUS_REG_OFFSET] = tool.SDMA_STATUS_IDLE_MASK

    def __enter__(self): return self
    def __exit__(self, kind, value, traceback): return None

    def select(self, value):
        self.selectors.append(value)
        self.selector = value

    def read32(self, offset):
        if offset not in self.tool.READ_OFFSETS:
            raise AssertionError(f'forbidden read {offset:#x}')
        self.reads.append((self.selector, offset))
        if (offset == self.tool.RECOVERY.CP_RB0_WPTR_OFFSET and
                self.selector == 0):
            return 0x80
        return self.values[offset]

    def metadata(self):
        return {'index': 5, 'userspace_mapping': 'BAR5-only',
                'userspace_selector_writes_only': True}


class RetainedIdleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.tool = load_tool()

    def proof(self):
        base = {'observer_source_sha256': self.tool.OBSERVER_SOURCE_SHA256,
                'journal_cursor': 'cursor'}
        return {'base': base, 'base_errors': [],
                'baseline_sha256': self.tool.BASELINE_SHA256,
                'baseline_errors': [],
                'scanner_source_sha256': 'a'*64,
                'expected_scanner_source_sha256': 'a'*64,
                'loaded_observer_source_sha256': self.tool.OBSERVER_SOURCE_SHA256,
                'current_observer_source_sha256': self.tool.OBSERVER_SOURCE_SHA256}

    def test_two_complete_passes_and_selector9_detail_are_idle(self):
        fake = FakeTransport(self.tool)
        result = self.tool.scan_device(fake)
        per_pass = [0] + list(self.tool.COMPUTE_SELECTORS) + [0, 1, 0]
        self.assertEqual(fake.selectors, per_pass*2 + [0])
        self.assertEqual(len(result['passes']), 2)
        for scan in result['passes']:
            self.assertEqual(len(scan['compute']), 64)
            row = next(row for row in scan['compute'] if row['selector'] == 9)
            self.assertEqual(row['host_kiq'], {
                'dequeue': 0, 'rptr': 0, 'wptr_lo': 0, 'wptr_hi': 0})
            self.assertEqual(scan['graphics']['pipes'][0]['wptr'], 0x80)
        self.assertEqual(result['status'], 'observed-idle')
        self.assertFalse(result['authorizes_launch'])
        self.assertFalse(result['authorizes_recovery'])
        self.assertFalse(result['authorizes_cleanup'])

    def test_selector9_residual_state_is_rejected_without_mutation(self):
        for offset, message in (
            (self.tool.RECOVERY.CP_HQD_ACTIVE_OFFSET, 'selector 9'),
            (self.tool.RECOVERY.CP_HQD_DEQUEUE_OFFSET, 'selector 9'),
            (self.tool.RECOVERY.CP_HQD_PQ_DOORBELL_OFFSET, 'doorbell'),
            (self.tool.RECOVERY.CP_HQD_PQ_RPTR_OFFSET, 'selector 9'),
            (self.tool.RECOVERY.CP_HQD_PQ_WPTR_LO_OFFSET, 'selector 9'),
            (self.tool.RECOVERY.CP_HQD_PQ_WPTR_HI_OFFSET, 'selector 9')):
            fake = FakeTransport(self.tool)
            original = fake.read32
            fake.read32 = lambda at, original=original, offset=offset: (
                1 if fake.selector == 9 and at == offset else original(at))
            with self.subTest(offset=offset), self.assertRaisesRegex(
                    self.tool.IdleInspectionError, message):
                self.tool.scan_device(fake)
            self.assertTrue(all(value in self.tool.VALID_SELECTORS
                                for value in fake.selectors))

    def test_active_doorbell_inaccessible_and_unhalted_inputs_are_rejected(self):
        cases = (
            (self.tool.RECOVERY.CP_HQD_ACTIVE_OFFSET, 1, 'active'),
            (self.tool.RECOVERY.CP_HQD_PQ_DOORBELL_OFFSET, 2, 'doorbell'),
            (self.tool.RECOVERY.CP_STAT_OFFSET, 1, 'CP_STAT'),
            (self.tool.RECOVERY.CP_CPC_BUSY_STAT_OFFSET, 1, 'CPC_BUSY'),
            (self.tool.RECOVERY.CP_ME_CNTL_OFFSET, 0, 'ME halt'),
            (self.tool.RECOVERY.CP_MEC_CNTL_OFFSET, 0, 'MEC halt'),
            (self.tool.RECOVERY.SDMA0_F32_CNTL_OFFSET, 0, 'SDMA halt'),
            (self.tool.SDMA0_STATUS_REG_OFFSET, 0, 'SDMA idle'),
            (self.tool.SDMA_AUX_OFFSETS['page_rb_cntl'], 1, 'SDMA input'),
            (self.tool.RECOVERY.CP_PQ_STATUS_OFFSET, 0xffffffff, 'all-ones'),
        )
        for offset, value, message in cases:
            fake = FakeTransport(self.tool); fake.values[offset] = value
            with self.subTest(offset=offset), self.assertRaisesRegex(
                    self.tool.IdleInspectionError, message):
                self.tool.scan_device(fake)

    def test_selector_one_graphics_activity_is_rejected(self):
        tool = self.tool

        class Banked(FakeTransport):
            def read32(inner, offset):
                if (inner.selector == 1 and
                        offset == tool.RECOVERY.CP_RB1_ACTIVE_OFFSET):
                    return 1
                return super().read32(offset)

        with self.assertRaisesRegex(tool.IdleInspectionError,
                                    'graphics pipe is active'):
            tool.scan_device(Banked(tool))

    def test_changed_state_and_final_default_failure_preserve_evidence(self):
        class Changing(FakeTransport):
            def read32(inner, offset):
                value = super().read32(offset)
                if offset == inner.tool.RECOVERY.CP_STAT_OFFSET and len(inner.selectors) > 68:
                    return 1
                return value
        with self.assertRaisesRegex(self.tool.IdleInspectionError, 'changed'):
            self.tool.scan_device(Changing(self.tool))

        class Broken(FakeTransport):
            def __init__(inner, tool):
                super().__init__(tool); inner.failed_read = False
            def read32(inner, offset):
                if not inner.failed_read and inner.selector == 9:
                    inner.failed_read = True
                    raise OSError('read broke')
                return super().read32(offset)
            def select(inner, value):
                if inner.failed_read and value == 0:
                    raise OSError('restore broke')
                return super().select(value)
        with self.assertRaisesRegex(self.tool.IdleInspectionError,
                                    'read broke.*restore broke') as raised:
            self.tool.scan_device(Broken(self.tool))
        self.assertFalse(raised.exception.evidence['final_default']['completed'])

    def test_partial_pass_survives_read_and_close_failures(self):
        tool = self.tool

        class Broken(FakeTransport):
            def read32(inner, offset):
                if (inner.selector == tool.COMPUTE_SELECTORS[0] and
                        offset == tool.RECOVERY.CP_HQD_PQ_DOORBELL_OFFSET):
                    raise OSError('capture broke')
                return super().read32(offset)

            def close(inner):
                raise OSError('close broke')

            def __exit__(inner, kind, value, traceback):
                return tool.Bar5SelectorTransport.__exit__(
                    inner, kind, value, traceback)

        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)/'result.json'
            with self.assertRaisesRegex(
                    tool.IdleInspectionError,
                    'capture broke.*close failed.*close broke') as raised:
                tool.run_inspection(
                    self.proof, lambda: Broken(tool),
                    lambda cursor: self.proof(), output)
            saved = __import__('json').loads(output.read_text())
        for value in (raised.exception.evidence['device'], saved['device']):
            self.assertEqual(value['passes'][0]['globals']['cp_stat'], 0)
            self.assertEqual(value['passes'][0]['compute'][0]['active'], 0)
            self.assertIn('capture broke', value['error'])
        self.assertIn('close broke', saved['device_error'])

    def test_postflight_allows_cursor_and_message_advance(self):
        before = self.proof()
        after = self.proof()
        after['base']['journal_cursor'] = 'later'
        after['base']['journal_messages'] = ['harmless message']
        with patch.object(self.tool.OBSERVER, 'postflight_errors', return_value=[]):
            self.assertEqual(self.tool.postflight_errors(before, after), [])

    def test_invalid_baseline_or_source_fails_before_transport(self):
        for mutate, message in (
                (lambda p: p.update(baseline_sha256='0'*64), 'baseline'),
                (lambda p: p.update(base_errors=['host changed']), 'base'),
                (lambda p: p.update(current_observer_source_sha256='0'*64), 'observer'),
                (lambda p: p.update(expected_scanner_source_sha256='0'*64), 'scanner')):
            proof = self.proof(); mutate(proof); opened = []
            with tempfile.TemporaryDirectory() as temp, self.assertRaisesRegex(
                    self.tool.IdleInspectionError, message):
                self.tool.run_inspection(
                    lambda: proof, lambda: opened.append(True),
                    lambda cursor: self.proof(), Path(temp)/'result.json')
            self.assertEqual(opened, [])

    def test_exact_retained_baseline_lifecycle_diff_is_required(self):
        tool = self.tool
        _, mqd = tool.OBSERVER.expected_images(0x667b2f65)
        observed = bytearray(mqd)
        for offset, value in tool.EXPECTED_MQD_DIFF.items():
            struct.pack_into('<I', observed, offset, value)
        self.assertEqual(hashlib.sha256(observed).hexdigest(),
                         '3329c7874b030528c47fb6946858820a5b8847537e065ef17dc40d867460b3c7')
        baseline = {
            'status': 'observed', 'authorizes_launch': False,
            'authorizes_recovery': False, 'authorizes_cleanup': False,
            'device': {
                'analysis': {
                    'ring_exact': True, 'fence_matches_sequence': True,
                    'sequence': 0x667b2f65, 'current_fence': 0x667b2f65,
                    'current_report': 0x100, 'stored_wptr': 0x100,
                },
                'ranges': [{'name': 'mqd', 'stable': True,
                            'passes': [{'data_hex': observed.hex()},
                                       {'data_hex': observed.hex()}]}],
            },
        }
        self.assertEqual(tool.baseline_content_errors(baseline), [])
        broken = bytearray(observed); broken[0x158] ^= 1
        baseline['device']['ranges'][0]['passes'][1]['data_hex'] = broken.hex()
        self.assertIn('baseline exact MQD lifecycle diff',
                      tool.baseline_content_errors(baseline))

    def test_close_failure_is_durable_and_nonauthorizing(self):
        class CloseFailure(FakeTransport):
            def __exit__(inner, kind, value, traceback):
                raise OSError('close broke')
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)/'result.json'
            with self.assertRaisesRegex(self.tool.IdleInspectionError, 'close broke'):
                self.tool.run_inspection(
                    self.proof, lambda: CloseFailure(self.tool),
                    lambda cursor: self.proof(), output)
            saved = __import__('json').loads(output.read_text())
            self.assertFalse(saved['authorizes_launch'])
            self.assertIn('device', saved)
            self.assertTrue(output.with_suffix('.attempt.json').exists())

    def test_transport_maps_only_bar5_and_exposes_only_selector_mutation(self):
        tool = self.tool; opened = iter((10, 11)); indices = []; mapping = object()
        def fake_ioctl(fd, request, argument=0):
            if request == tool.VFIO_GET_API_VERSION: return tool.VFIO_API_VERSION
            if request == tool.VFIO_CHECK_EXTENSION: return 1
            if request == tool.VFIO_GROUP_GET_STATUS:
                argument._obj.flags = tool.VFIO_GROUP_FLAGS_VIABLE; return 0
            if request in (tool.VFIO_GROUP_SET_CONTAINER, tool.VFIO_SET_IOMMU,
                           tool.OBSERVER.VFIO_GROUP_UNSET_CONTAINER): return 0
            if request == tool.VFIO_GROUP_GET_DEVICE_FD: return 12
            if request == tool.VFIO_DEVICE_GET_REGION_INFO:
                indices.append(argument._obj.index); argument._obj.size = tool.BAR5_SIZE
                argument._obj.offset = 0x500000
                argument._obj.flags = (tool.VFIO_REGION_INFO_FLAG_READ |
                                       tool.VFIO_REGION_INFO_FLAG_WRITE |
                                       tool.VFIO_REGION_INFO_FLAG_MMAP); return 0
            raise AssertionError(hex(request))
        with patch.object(tool.os, 'open', side_effect=lambda *a, **k: next(opened)), \
             patch.object(tool, 'ioctl', side_effect=fake_ioctl), \
             patch.object(tool.mmap, 'mmap', return_value=mapping) as mm, \
             patch.object(tool.Bar5SelectorTransport, 'close'):
            transport = tool.Bar5SelectorTransport(); transport.__enter__()
        self.assertEqual(indices, [tool.VFIO_PCI_BAR5_REGION_INDEX])
        self.assertEqual(mm.call_args.kwargs['prot'], mmap.PROT_READ | mmap.PROT_WRITE)
        self.assertFalse(hasattr(transport, 'write32'))
        self.assertFalse(hasattr(transport, 'write_vram'))
        self.assertFalse(hasattr(transport, 'flush_hdp'))

    def test_transport_forbids_unknown_reads_and_selectors(self):
        transport = self.tool.Bar5SelectorTransport(); transport.bar5 = bytes(self.tool.BAR5_SIZE)
        with self.assertRaisesRegex(self.tool.IdleInspectionError, 'forbidden BAR5 read'):
            transport.read32((self.tool.RECOVERY.GC_SEG0 + 0x160d) * 4)
        with self.assertRaisesRegex(self.tool.IdleInspectionError, 'forbidden selector'):
            transport.select(0xdead)


if __name__ == '__main__': unittest.main()
