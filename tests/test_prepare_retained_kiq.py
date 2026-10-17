import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT/'findings/recovery-tests/retained-idle-175/result.json'


def load_tool():
    path = ROOT/'tools/prepare-retained-kiq.py'
    spec = importlib.util.spec_from_file_location('prepare_retained_kiq', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeTransport:
    def __init__(self, tool, expected):
        self.tool, self.selector = tool, 0
        self.selectors, self.write_log, self.reads = [], [], []
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
        return self.values[(self.selector, offset)]

    def write_fixed(self, offset, before, after):
        current = self.values[(self.selector, offset)]
        if current != before:
            raise self.tool.PageDisableError('unexpected fake preimage')
        self.values[(self.selector, offset)] = after
        row = {'offset': offset, 'before': before, 'value': after,
               'posted': after}
        self.write_log.append(row)
        return after

    def metadata(self):
        return {'index': 5, 'userspace_mapping': 'BAR5-only',
                'userspace_writes': 'GRBM-selector-and-two-fixed-PAGE-bits-only'}


class PrepareRetainedKiqTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tool = load_tool()
        cls.fixture = json.loads(FIXTURE.read_text())['device']

    def proof(self):
        return {
            'scanner_proof': {'base': {'journal_cursor': 'cursor'}},
            'scanner_errors': [],
            'idle_result_sha256': self.tool.IDLE_RESULT_SHA256,
            'idle_result_errors': [],
            'tool_source_sha256': 'a'*64,
            'expected_tool_source_sha256': 'a'*64,
            'loaded_scanner_source_sha256': self.tool.SCANNER_SOURCE_SHA256,
            'scanner_source_sha256': self.tool.SCANNER_SOURCE_SHA256,
        }

    def test_exact_page_then_halted_kiq_wptr_order_and_full_postscan(self):
        tool = self.tool; fake = FakeTransport(tool, self.fixture)
        result = tool.execute_transaction(fake, self.fixture)
        self.assertEqual([(row['offset'], row['before'], row['value'])
                          for row in result['writes']], [
            (tool.PAGE_IB_OFFSET, 0x101, 0x100),
            (tool.PAGE_RB_OFFSET, 0x80840021, 0x80840020),
            (tool.RECOVERY.CP_HQD_PQ_WPTR_LO_OFFSET, 0x100, 0),
        ])
        self.assertEqual(result['writes'], fake.write_log)
        self.assertEqual(len(result['before']['passes']), 2)
        self.assertEqual(len(result['after']['passes']), 2)
        self.assertEqual(result['before']['passes'], self.fixture['passes'])
        expected_after = tool.expected_after_passes(self.fixture['passes'])
        self.assertEqual(result['after']['passes'], expected_after)
        self.assertEqual(fake.selectors[137:139], [9, 0])
        self.assertEqual(len(fake.selectors), 276)
        self.assertEqual(result['status'],
                         'page-inputs-disabled-and-kiq-wptr-cleared')
        self.assertFalse(result['authorizes_launch'])
        self.assertFalse(result['authorizes_recovery'])
        self.assertFalse(result['authorizes_cleanup'])

    def test_pre_scan_mismatch_refuses_both_page_writes(self):
        tool = self.tool; fake = FakeTransport(tool, self.fixture)
        fake.values[(9, tool.RECOVERY.CP_HQD_ACTIVE_OFFSET)] = 1
        with self.assertRaisesRegex(tool.PageDisableError,
                                    'pre-scan does not match') as raised:
            tool.execute_transaction(fake, self.fixture)
        self.assertEqual(fake.write_log, [])
        self.assertEqual(len(raised.exception.evidence['before']['passes']), 2)

    def test_halt_or_idle_change_immediately_before_first_write_refuses(self):
        tool = self.tool
        for offset, value, message in (
                (tool.RECOVERY.SDMA0_F32_CNTL_OFFSET, 0, 'halt'),
                (tool.SCANNER.SDMA0_STATUS_REG_OFFSET, 0, 'idle')):
            fake = FakeTransport(tool, self.fixture)
            original = fake.read32
            full_scan_reads = len(tool.full_scan_read_trace())
            def changed(at, original=original, offset=offset, value=value):
                if len(fake.reads) >= full_scan_reads and at == offset:
                    fake.reads.append((fake.selector, at)); return value
                return original(at)
            fake.read32 = changed
            with self.subTest(offset=offset), self.assertRaisesRegex(
                    tool.PageDisableError, message):
                tool.execute_transaction(fake, self.fixture)
            self.assertEqual(fake.write_log, [])

    def test_posting_failure_preserves_first_attempt_and_skips_later_writes(self):
        tool = self.tool
        class Broken(FakeTransport):
            def write_fixed(inner, offset, before, after):
                posted = super().write_fixed(offset, before, after)
                inner.write_log[-1]['posted'] = posted ^ 1
                raise OSError('posting read broke')
        fake = Broken(tool, self.fixture)
        with self.assertRaisesRegex(tool.PageDisableError,
                                    'posting read broke') as raised:
            tool.execute_transaction(fake, self.fixture)
        self.assertEqual(len(fake.write_log), 1)
        self.assertEqual(raised.exception.evidence['writes'], fake.write_log)
        self.assertFalse(raised.exception.evidence['authorizes_cleanup'])

    def test_post_scan_drift_is_failed_and_nonauthorizing(self):
        tool = self.tool
        class Drift(FakeTransport):
            def read32(inner, offset):
                value = super().read32(offset)
                if (len(inner.write_log) == 3 and inner.selector == 9 and
                        offset == tool.RECOVERY.CP_HQD_PQ_WPTR_LO_OFFSET):
                    return value + 4
                return value
        with self.assertRaisesRegex(tool.PageDisableError, 'post-scan') as raised:
            tool.execute_transaction(Drift(tool, self.fixture), self.fixture)
        self.assertEqual(len(raised.exception.evidence['after']['passes']), 2)
        self.assertFalse(raised.exception.evidence['authorizes_launch'])

    def test_transport_rejects_any_other_page_value_or_register(self):
        tool = self.tool; transport = tool.PageDisableTransport()
        with self.assertRaisesRegex(tool.PageDisableError, 'forbidden PAGE write'):
            transport.write_fixed(tool.PAGE_IB_OFFSET, 0x101, 0x102)
        with self.assertRaisesRegex(tool.PageDisableError, 'forbidden PAGE write'):
            transport.write_fixed(tool.RECOVERY.SDMA0_GFX_IB_CNTL_OFFSET, 0x101, 0x100)

    def test_real_transport_performs_only_exact_native_dword_sequence(self):
        tool = self.tool; transport = tool.PageDisableTransport()
        transport.bar0 = bytearray(tool.SCANNER.BAR5_SIZE)
        transport._selected = 0
        import struct
        for offset, before, value, selector in tool.EXPECTED_FIXED_WRITES:
            transport._selected = selector
            struct.pack_into('<I', transport.bar0, offset, before)
            self.assertEqual(transport.write_fixed(offset, before, value), value)
            self.assertEqual(struct.unpack_from('<I', transport.bar0, offset)[0], value)
        self.assertEqual([(row['offset'], row['value'], row['selector'])
                          for row in transport.write_log], [
            (tool.PAGE_IB_OFFSET, 0x100, 0),
            (tool.PAGE_RB_OFFSET, 0x80840020, 0),
            (tool.RECOVERY.CP_HQD_PQ_WPTR_LO_OFFSET, 0, 9),
        ])
        transport.region = type('Region', (), {'index': 5, 'size': tool.SCANNER.BAR5_SIZE,
                                               'offset': 0x500000})()
        metadata = transport.metadata()
        self.assertFalse(metadata['userspace_selector_writes_only'])
        self.assertEqual(metadata['userspace_fixed_dword_writes'], [
            {'offset': tool.PAGE_IB_OFFSET, 'before': 0x101, 'value': 0x100,
             'selector': 0},
            {'offset': tool.PAGE_RB_OFFSET, 'before': 0x80840021,
             'value': 0x80840020, 'selector': 0},
            {'offset': tool.RECOVERY.CP_HQD_PQ_WPTR_LO_OFFSET,
             'before': 0x100, 'value': 0, 'selector': 9},
        ])

    def test_all_pre_wptr_gates_are_checked_after_page_writes(self):
        tool = self.tool
        cases = (
            (tool.RECOVERY.CP_HQD_ACTIVE_OFFSET, 1, 'ACTIVE'),
            (tool.RECOVERY.CP_HQD_DEQUEUE_OFFSET, 1, 'DEQUEUE'),
            (tool.RECOVERY.CP_HQD_PQ_RPTR_OFFSET, 1, 'RPTR'),
            (tool.RECOVERY.CP_HQD_PQ_WPTR_HI_OFFSET, 1, 'WPTR_HI'),
            (tool.RECOVERY.CP_HQD_PQ_DOORBELL_OFFSET, 0xc0000000, 'DB_EN'),
        )
        for offset, value, message in cases:
            fake = FakeTransport(tool, self.fixture); original = fake.read32
            def changed(at, original=original, offset=offset, value=value):
                if len(fake.write_log) == 2 and fake.selector == 9 and at == offset:
                    fake.reads.append((fake.selector, at)); return value
                return original(at)
            fake.read32 = changed
            with self.subTest(offset=offset), self.assertRaisesRegex(
                    tool.PageDisableError, message):
                tool.execute_transaction(fake, self.fixture)
            self.assertEqual(len(fake.write_log), 2)
            self.assertEqual(fake.selector, 0)

    def test_ignored_wptr_write_still_captures_full_after_scan(self):
        tool = self.tool
        class Ignored(FakeTransport):
            def write_fixed(inner, offset, before, after):
                if offset != tool.RECOVERY.CP_HQD_PQ_WPTR_LO_OFFSET:
                    return super().write_fixed(offset, before, after)
                row = {'offset': offset, 'before': before, 'value': after,
                       'posted': before}
                inner.write_log.append(row)
                return before
        with self.assertRaisesRegex(tool.PageDisableError,
                                    'WPTR posting/readback') as raised:
            tool.execute_transaction(Ignored(tool, self.fixture), self.fixture)
        evidence = raised.exception.evidence
        self.assertEqual(len(evidence['after']['passes']), 2)
        row = next(r for r in evidence['after']['passes'][0]['compute']
                   if r['selector'] == 9)
        self.assertEqual(row['host_kiq']['wptr_lo'], 0x100)
        self.assertFalse(evidence['authorizes_cleanup'])

    def test_invalid_proof_fails_before_transport(self):
        tool = self.tool
        for key in ('scanner_errors', 'idle_result_sha256',
                    'idle_result_errors', 'scanner_source_sha256'):
            proof = self.proof()
            proof[key] = ['bad'] if key.endswith('errors') else '0'*64
            opened = []
            with tempfile.TemporaryDirectory() as temp, self.assertRaises(
                    tool.PageDisableError):
                tool.run_transaction(
                    lambda: proof, lambda: opened.append(True),
                    lambda cursor: self.proof(), Path(temp)/'result.json',
                    self.fixture)
            self.assertEqual(opened, [])

    def test_device_and_close_failure_preserve_partial_writes_and_postflight(self):
        tool = self.tool; postflight = []
        class Broken(FakeTransport):
            def write_fixed(inner, offset, before, after):
                super().write_fixed(offset, before, after)
                raise OSError('device broke')
            def __exit__(inner, kind, value, traceback):
                raise OSError('close broke')
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)/'result.json'
            with self.assertRaisesRegex(tool.PageDisableError,
                                        'device broke.*close broke'):
                tool.run_transaction(
                    self.proof, lambda: Broken(tool, self.fixture),
                    lambda cursor: postflight.append(cursor) or self.proof(),
                    output, self.fixture)
            saved = json.loads(output.read_text())
        self.assertEqual(postflight, ['cursor'])
        self.assertEqual(len(saved['transaction']['writes']), 1)
        self.assertIn('close broke', saved['device_error'])
        self.assertFalse(saved['authorizes_cleanup'])


if __name__ == '__main__': unittest.main()
