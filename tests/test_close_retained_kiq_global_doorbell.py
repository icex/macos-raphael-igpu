import copy
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest

from tests.test_retained_kiq_doorbell_zero import FakeTransport


ROOT = Path(__file__).resolve().parents[1]
PREPARATION = ROOT/'findings/recovery-tests/retained-kiq-preparation-175/result.json'


def load_tool():
    path = ROOT/'tools/close-retained-kiq-global-doorbell.py'
    spec = importlib.util.spec_from_file_location('close_retained_kiq_global', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.RECOVERY.EXPECTED_CONFIG_MEMSIZE = 0x200
    return module


def current_fixture():
    value = json.loads(PREPARATION.read_text())['transaction']['after']
    value = copy.deepcopy(value)
    for scan in value['passes']:
        scan['globals']['pq_status'] = 3
        row = next(row for row in scan['compute'] if row['selector'] == 9)
        row['host_kiq']['wptr_lo'] = 0
    return value


class CloseFake(FakeTransport):
    def __init__(self, tool, expected, posted=1):
        super().__init__(tool, expected)
        self.posted = posted
        self.close_writes = []

    def write_global_close(self, offset, before, value):
        observed = self.values[(0, offset)]
        self.values[(0, offset)] = self.posted
        row = {'offset': offset, 'before': before, 'value': value,
               'observed_before': observed, 'posted': self.posted,
               'attempted': True, 'store_completed': True,
               'completed': self.posted in (0, 1)}
        self.close_writes.append(row)
        return self.posted

    def metadata(self):
        return {'userspace_mapping': 'BAR5-only',
                'userspace_writes': 'selectors-and-one-fixed-PQ-gate-close'}


class CloseRetainedGlobalDoorbellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tool = load_tool()
        cls.fixture = current_fixture()

    def proof(self):
        return {
            'doorbell_proof': {'preparation_proof': {
                'scanner_proof': {'base': {'journal_cursor': 'c'}}}},
            'doorbell_errors': [],
            'doorbell_result_sha256': self.tool.DOORBELL_RESULT_SHA256,
            'doorbell_result_errors': [],
            'tool_source_sha256': 'a'*64,
            'expected_tool_source_sha256': 'a'*64,
            'loaded_doorbell_source_sha256': self.tool.DOORBELL_SOURCE_SHA256,
            'current_doorbell_source_sha256': self.tool.DOORBELL_SOURCE_SHA256,
        }

    def test_exact_single_native_close_and_full_stable_after_scan(self):
        tool = self.tool; fake = CloseFake(tool, self.fixture, posted=1)
        result = tool.execute_transaction(fake, self.fixture)
        self.assertEqual(fake.close_writes, result['writes'])
        self.assertEqual(len(fake.close_writes), 1)
        self.assertEqual(fake.close_writes[0]['observed_before'], 3)
        self.assertEqual(fake.close_writes[0]['value'], 1)
        self.assertEqual(fake.close_writes[0]['posted'], 1)
        self.assertEqual(len(result['after']['passes']), 2)
        self.assertEqual(result['after']['passes'][0]['globals']['pq_status'], 1)
        target = next(row for row in result['after']['passes'][0]['compute']
                      if row['selector'] == 9)
        self.assertEqual(target['host_kiq']['wptr_lo'], 0)
        self.assertEqual(target['host_kiq']['wptr_hi'], 0)
        self.assertEqual(result['status'], 'global-doorbell-gate-closed-nonauthorizing')
        self.assertFalse(result['authorizes_launch'])
        self.assertFalse(result['authorizes_recovery'])
        self.assertFalse(result['authorizes_cleanup'])

    def test_updated_bit_may_self_clear_to_zero(self):
        fake = CloseFake(self.tool, self.fixture, posted=0)
        result = self.tool.execute_transaction(fake, self.fixture)
        self.assertEqual(result['writes'][0]['posted'], 0)
        self.assertEqual(result['after']['passes'][0]['globals']['pq_status'], 0)

    def test_pre_scan_change_refuses_the_only_nonselector_write(self):
        fake = CloseFake(self.tool, self.fixture)
        fake.values[(9, self.tool.RECOVERY.CP_HQD_ACTIVE_OFFSET)] = 1
        with self.assertRaisesRegex(self.tool.GlobalCloseError,
                                    'pre-scan') as raised:
            self.tool.execute_transaction(fake, self.fixture)
        self.assertEqual(fake.close_writes, [])
        self.assertEqual(len(raised.exception.evidence['before']['passes']), 2)

    def test_posted_enable_bit_is_failure_but_full_after_is_preserved(self):
        fake = CloseFake(self.tool, self.fixture, posted=3)
        with self.assertRaisesRegex(self.tool.GlobalCloseError,
                                    'did not close') as raised:
            self.tool.execute_transaction(fake, self.fixture)
        self.assertEqual(len(fake.close_writes), 1)
        self.assertTrue(fake.close_writes[0]['store_completed'])
        self.assertEqual(len(raised.exception.evidence['after']['passes']), 2)
        self.assertFalse(raised.exception.evidence['authorizes_cleanup'])

    def test_real_transport_allows_only_one_native_dword_3_to_1(self):
        tool = self.tool; transport = tool.GlobalCloseTransport()
        transport.bar0 = bytearray(tool.SCANNER.BAR5_SIZE)
        struct.pack_into('<I', transport.bar0, tool.RECOVERY.CP_PQ_STATUS_OFFSET, 3)
        self.assertEqual(transport.write_global_close(
            tool.RECOVERY.CP_PQ_STATUS_OFFSET, 3, 1), 1)
        self.assertEqual(struct.unpack_from(
            '<I', transport.bar0, tool.RECOVERY.CP_PQ_STATUS_OFFSET)[0], 1)
        with self.assertRaisesRegex(tool.GlobalCloseError, 'already attempted'):
            transport.write_global_close(tool.RECOVERY.CP_PQ_STATUS_OFFSET, 3, 1)
        other = tool.GlobalCloseTransport(); other.bar0 = bytearray(tool.SCANNER.BAR5_SIZE)
        with self.assertRaisesRegex(tool.GlobalCloseError, 'forbidden global close'):
            other.write_global_close(tool.RECOVERY.CP_MEC_CNTL_OFFSET, 3, 1)
        self.assertFalse(hasattr(transport, 'ring_doorbell64'))
        self.assertFalse(hasattr(transport, 'bar2'))

    def test_invalid_live_result_or_source_fails_before_transport(self):
        tool = self.tool
        for key in ('doorbell_errors', 'doorbell_result_sha256',
                    'doorbell_result_errors', 'current_doorbell_source_sha256'):
            proof = self.proof(); opened = []
            proof[key] = ['bad'] if key.endswith('errors') else '0'*64
            with tempfile.TemporaryDirectory() as temp, self.assertRaises(
                    tool.GlobalCloseError):
                tool.run_transaction(
                    lambda proof=proof: proof, lambda: opened.append(True),
                    lambda cursor: self.proof(), Path(temp)/'result.json',
                    self.fixture)
            self.assertEqual(opened, [])

    def test_write_and_close_failure_plus_postflight_are_durable(self):
        tool = self.tool
        class Broken(CloseFake):
            def write_global_close(inner, offset, before, value):
                inner.close_writes.append({'attempted': True,
                                           'store_completed': True,
                                           'completed': False,
                                           'error': 'posting broke'})
                raise OSError('posting broke')
            def __exit__(inner, kind, value, traceback):
                raise OSError('close broke')
        fake = Broken(tool, self.fixture)
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)/'result.json'
            with self.assertRaisesRegex(tool.GlobalCloseError,
                                        'posting broke.*close broke.*postflight'):
                tool.run_transaction(
                    self.proof, lambda: fake,
                    lambda cursor: (_ for _ in ()).throw(OSError('post broke')),
                    output, self.fixture)
            saved = json.loads(output.read_text())
        self.assertIn('posting broke', saved['device_error'])
        self.assertIn('close broke', saved['device_error'])
        self.assertEqual(saved['postflight']['collection_error'], 'OSError: post broke')
        self.assertEqual(len(saved['transaction']['writes']), 1)
        self.assertFalse(saved['authorizes_launch'])


if __name__ == '__main__': unittest.main()
