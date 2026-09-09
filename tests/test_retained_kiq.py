import hashlib
import importlib.util
import json
import mmap
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load_tool():
    path = ROOT / 'tools/inspect-retained-kiq.py'
    spec = importlib.util.spec_from_file_location('inspect_retained_kiq', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeTransport:
    def __init__(self, tool, sequence=0x12345678):
        self.tool = tool
        ring, mqd = tool.expected_images(sequence)
        self.values = {
            'ring': ring, 'mqd': mqd,
            'pointers': (0x100).to_bytes(4, 'little') + b'ABCD' +
                        (0x100).to_bytes(8, 'little'),
            'eop': bytes(tool.RANGES_BY_NAME['eop'][1]),
            'fence': sequence.to_bytes(4, 'little'),
        }
        self.reads = []
        self.entered = self.closed = False

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, kind, value, traceback):
        self.closed = True

    def read_range(self, name, offset, size):
        self.reads.append((name, offset, size))
        expected = self.tool.RANGES_BY_NAME[name]
        if (offset, size) != expected:
            raise AssertionError('out-of-range read')
        return self.values[name]

    def metadata(self):
        return {'index': 0, 'size': self.tool.VRAM_BAR_SIZE,
                'region_read_capable': True, 'region_write_capable': True,
                'region_mmap_capable': True, 'userspace_mapping': 'BAR0-only',
                'userspace_mapping_protection': 'read-only',
                'userspace_mutation_methods': False,
                'kernel_vfio_lifecycle_configuration_activity': True}


class RetainedKiqTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tool = load_tool()

    def host(self):
        return {
            'boot_id': self.tool.BOOT_ID, 'active_vm': False,
            'driver': 'vfio-pci', 'device': '1002:13c0',
            'iommu_group': '31', 'pci_command': 3, 'reset_methods': [],
            'canonical_device': self.tool.CANONICAL_DEVICE,
            'power_control': 'on', 'power_state': 'D0',
            'runtime_status': 'active', 'sleep_inhibited': True,
            'enable_count': '0',
            'watchdogs': {'watchdog': '1', 'nmi_watchdog': '1',
                          'hardlockup_panic': '1'},
            'residual_units': [], 'siblings': self.tool.EXPECTED_SIBLINGS,
            'reset_domain': self.tool.EXPECTED_RESET_DOMAIN,
            'kernel_release': self.tool.KERNEL_RELEASE,
            'vfio_module_sha256': self.tool.VFIO_MODULE_SHA256,
            'vfio_module_build_id': self.tool.VFIO_MODULE_BUILD_ID,
        }

    def proof(self):
        ledger = {'schema': 2, 'boot_id': self.tool.BOOT_ID, 'max_launches': 3,
                  'launches': [{'run_id': 'e583a1b2d97a4ad3b607c1d20a29a812'},
                               {'run_id': self.tool.RUN_ID}]}
        identity = {'schema': 5, 'status': 'incomplete',
                    'authorizes_launch': False,
                    'boot_id': self.tool.BOOT_ID,
                    'prior_run_id': self.tool.RUN_ID,
                    'recovery_id': self.tool.RECOVERY_ID}
        return {
            'boot_id': self.tool.BOOT_ID, 'run_id': self.tool.RUN_ID,
            'host': self.host(), 'ledger': ledger,
            'ledger_sha256': self.tool.PINNED_HASHES['ledger'],
            'artifact_sha256': dict(self.tool.PINNED_HASHES),
            'archive_inventory': list(self.tool.PINNED_ARCHIVE_INVENTORY),
            'archive_digest': self.tool.PINNED_ARCHIVE_DIGEST,
            'manifest': {'boot_id': self.tool.BOOT_ID,
                         'run_id': self.tool.RUN_ID,
                         'build_id': self.tool.BUILD_ID,
                         'source_commit': self.tool.SOURCE_COMMIT},
            'recovery': dict(identity), 'receipt': dict(identity),
            'recovery_receipt_equal': True,
            'historical_source_sha256': self.tool.HISTORICAL_SOURCE_SHA256,
            'loaded_recovery_source_sha256': self.tool.CURRENT_RECOVERY_SOURCE_SHA256,
            'current_recovery_source_sha256': self.tool.CURRENT_RECOVERY_SOURCE_SHA256,
            'observer_source_sha256': 'a' * 64,
            'expected_observer_source_sha256': 'a' * 64,
            'journal_cursor': 'cursor', 'journal_messages': [],
            'journal_faults': [],
        }

    def test_exact_ranges_are_read_twice_and_positive_fence_never_authorizes(self):
        fake = FakeTransport(self.tool)
        result = self.tool.observe_device(fake)
        expected = [(name, offset, size) for name, offset, size in self.tool.READ_RANGES] * 2
        self.assertEqual(fake.reads, expected)
        self.assertEqual(result['analysis']['sequence'], 0x12345678)
        self.assertEqual(result['analysis']['current_report'], 0x100)
        self.assertTrue(result['analysis']['report_is_current_observation_only'])
        self.assertTrue(result['analysis']['fence_matches_sequence'])
        self.assertTrue(result['analysis']['ring_exact'])
        self.assertTrue(result['analysis']['mqd_exact'])
        self.assertFalse(result['authorizes_launch'])
        self.assertFalse(result['authorizes_recovery'])
        self.assertFalse(result['authorizes_cleanup'])
        self.assertEqual(result['interpretation'], 'retained-fence-matches-sequence')
        self.assertTrue(all(row['stable'] for row in result['ranges']))

    def test_mqd_mismatch_is_diagnostic(self):
        fake = FakeTransport(self.tool)
        fake.values['mqd'] = b'\xff' + fake.values['mqd'][1:]
        result = self.tool.observe_device(fake)
        self.assertFalse(result['analysis']['mqd_exact'])
        self.assertFalse(result['authorizes_launch'])
        self.assertEqual(result['interpretation'], 'scratch-identity-inconsistent')

    def test_ring_mismatch_keeps_raw_fence_match_but_not_positive_interpretation(self):
        fake = FakeTransport(self.tool)
        ring = bytearray(fake.values['ring'])
        ring[44:48] = bytes(4)
        fake.values['ring'] = bytes(ring)
        result = self.tool.observe_device(fake)
        self.assertFalse(result['analysis']['ring_exact'])
        self.assertTrue(result['analysis']['fence_matches_sequence'])
        self.assertEqual(result['interpretation'], 'scratch-identity-inconsistent')
        self.assertFalse(result['authorizes_recovery'])

    def test_stored_wptr_mismatch_keeps_fence_fact_but_not_positive_interpretation(self):
        fake = FakeTransport(self.tool)
        fake.values['pointers'] = (0x100).to_bytes(4, 'little') + b'ABCD' + bytes(8)
        result = self.tool.observe_device(fake)
        self.assertTrue(result['analysis']['fence_matches_sequence'])
        self.assertEqual(result['analysis']['stored_wptr'], 0)
        self.assertEqual(result['interpretation'], 'scratch-identity-inconsistent')
        self.assertTrue(result['historical_receipt_unchanged'])

    def test_expected_image_matches_historical_source_builder(self):
        source = subprocess.check_output([
            'git', '-C', str(ROOT), 'show',
            f'{self.tool.SOURCE_COMMIT}:tools/vfio-recover.py'])
        self.assertEqual(hashlib.sha256(source).hexdigest(),
                         self.tool.HISTORICAL_SOURCE_SHA256)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'vfio_recover_historical.py'
            path.write_bytes(source)
            spec = importlib.util.spec_from_file_location('vfio_recover_historical', path)
            historical = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(historical)
            expected = historical._host_kiq_image(
                self.tool.FB_BASE, 0x12345678, 0x400)[:2]
        self.assertEqual(self.tool.expected_images(0x12345678), expected)

    def test_unstable_or_failed_capture_preserves_partial_evidence(self):
        class Changing(FakeTransport):
            def read_range(inner, name, offset, size):
                value = super().read_range(name, offset, size)
                if len(inner.reads) > len(inner.tool.READ_RANGES) and name == 'fence':
                    return b'\0\0\0\0'
                return value
        with self.assertRaisesRegex(self.tool.ObserverError, 'changed') as raised:
            self.tool.observe_device(Changing(self.tool))
        self.assertEqual(len(raised.exception.evidence['ranges']), len(self.tool.READ_RANGES))
        self.assertFalse(raised.exception.evidence['authorizes_launch'])

        class Broken(FakeTransport):
            def read_range(inner, name, offset, size):
                if name == 'mqd':
                    raise OSError('capture broke')
                return super().read_range(name, offset, size)
        with self.assertRaisesRegex(self.tool.ObserverError, 'capture broke') as raised:
            self.tool.observe_device(Broken(self.tool))
        self.assertEqual(raised.exception.evidence['passes'][0][0]['name'], 'ring')

    def test_preflight_identity_and_foreign_sibling_changes_fail(self):
        cases = []
        proof = self.proof(); proof['ledger_sha256'] = '0' * 64
        cases.append((proof, 'ledger'))
        proof = self.proof(); proof['receipt']['status'] = 'recovered'
        cases.append((proof, 'receipt'))
        proof = self.proof(); proof['historical_source_sha256'] = '0' * 64
        cases.append((proof, 'historical source'))
        proof = self.proof(); proof['current_recovery_source_sha256'] = '0' * 64
        cases.append((proof, 'helper source'))
        proof = self.proof(); proof['expected_observer_source_sha256'] = '0' * 64
        cases.append((proof, 'observer source'))
        proof = self.proof(); proof['host']['siblings'] = dict(proof['host']['siblings'])
        proof['host']['siblings']['0000:7b:00.1'] = dict(
            proof['host']['siblings']['0000:7b:00.1'], driver='vfio-pci')
        cases.append((proof, 'siblings'))
        proof = self.proof(); proof['host']['power_state'] = 'D3hot'
        cases.append((proof, 'power'))
        proof = self.proof(); proof['host']['enable_count'] = '1'
        cases.append((proof, 'power'))
        proof = self.proof(); proof['host']['reset_domain'] = {}
        cases.append((proof, 'canonical'))
        proof = self.proof(); proof['host']['vfio_module_sha256'] = '0' * 64
        cases.append((proof, 'module'))
        proof = self.proof(); proof['journal_messages'] = [
            'vfio-pci 0000:7b:00.0: resetting device']
        cases.append((proof, 'reset'))
        for proof, expected in cases:
            with self.subTest(expected=expected):
                self.assertTrue(any(expected in error
                                    for error in self.tool.preflight_errors(proof)))

    def test_invalid_proof_fails_before_transport_and_is_durable(self):
        proof = self.proof(); proof['host']['runtime_status'] = 'suspended'
        opened = []
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'result.json'
            with self.assertRaisesRegex(self.tool.ObserverError, 'pre-VFIO'):
                self.tool.run_observation(
                    lambda: proof, lambda: opened.append(True),
                    lambda cursor: self.proof(), output)
            self.assertEqual(opened, [])
            saved = json.loads(output.read_text())
            self.assertEqual(saved['status'], 'failed')
            self.assertFalse(saved['authorizes_launch'])

    def test_open_and_close_failures_are_durable_and_block_retry(self):
        class CloseFailure(FakeTransport):
            def __exit__(inner, kind, value, traceback):
                inner.closed = True
                raise OSError('close broke')
        for factory, message in (
                (lambda: (_ for _ in ()).throw(OSError('open broke')), 'open broke'),
                (lambda: CloseFailure(self.tool), 'close broke')):
            with self.subTest(message=message), tempfile.TemporaryDirectory() as temp:
                output = Path(temp) / 'result.json'
                marker = output.with_suffix('.attempt.json')
                with self.assertRaisesRegex(self.tool.ObserverError, message):
                    self.tool.run_observation(
                        self.proof, factory, lambda cursor: self.proof(), output)
                self.assertTrue(marker.exists())
                saved = json.loads(output.read_text())
                self.assertIn(message, saved['error'])
                self.assertFalse(saved['authorizes_recovery'])
                with self.assertRaises(FileExistsError):
                    self.tool.run_observation(
                        self.proof, lambda: FakeTransport(self.tool),
                        lambda cursor: self.proof(), output)

    def test_capture_and_close_failures_are_both_preserved(self):
        class BothFail(self.tool.Bar0ReadTransport):
            def __init__(inner):
                inner.fake = FakeTransport(self.tool)

            def __enter__(inner):
                return inner

            def read_range(inner, name, offset, size):
                if name == 'mqd':
                    raise OSError('capture broke')
                return inner.fake.read_range(name, offset, size)

            def close(inner):
                raise OSError('close broke')

            def metadata(inner):
                return inner.fake.metadata()

        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'result.json'
            with self.assertRaisesRegex(self.tool.ObserverError,
                                        'capture broke.*close broke'):
                self.tool.run_observation(
                    self.proof, BothFail,
                    lambda cursor: (_ for _ in ()).throw(
                        OSError('postflight broke')), output)
            saved = json.loads(output.read_text())
            self.assertIn('capture broke', saved['device_error'])
            self.assertIn('close broke', saved['device_error'])
            self.assertEqual(saved['device']['passes'][0][0]['name'], 'ring')
            self.assertEqual(saved['postflight']['collection_error'],
                             'OSError: postflight broke')
            self.assertIn('postflight', saved['error'])

    def test_postflight_change_fails_but_keeps_capture(self):
        post = self.proof(); post['host']['siblings'] = dict(post['host']['siblings'])
        post['host']['siblings']['0000:7b:00.2'] = dict(
            post['host']['siblings']['0000:7b:00.2'], driver=None)
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'result.json'
            with self.assertRaisesRegex(self.tool.ObserverError, 'postflight'):
                self.tool.run_observation(
                    self.proof, lambda: FakeTransport(self.tool),
                    lambda cursor: post, output)
            saved = json.loads(output.read_text())
            self.assertIn('device', saved)
            self.assertFalse(saved['authorizes_launch'])

    def test_transport_maps_only_bar0_with_read_protection(self):
        tool = self.tool
        opened = iter((10, 11, 12))
        region_indices = []
        mapping = object()

        def fake_ioctl(fd, request, argument=0):
            if request == tool.VFIO_GET_API_VERSION:
                return tool.VFIO_API_VERSION
            if request == tool.VFIO_CHECK_EXTENSION:
                return 1
            if request == tool.VFIO_GROUP_GET_STATUS:
                argument._obj.flags = tool.VFIO_GROUP_FLAGS_VIABLE
                return 0
            if request in (tool.VFIO_GROUP_SET_CONTAINER, tool.VFIO_SET_IOMMU,
                           tool.VFIO_GROUP_UNSET_CONTAINER):
                return 0
            if request == tool.VFIO_GROUP_GET_DEVICE_FD:
                return 12
            if request == tool.VFIO_DEVICE_GET_REGION_INFO:
                region_indices.append(argument._obj.index)
                argument._obj.size = tool.VRAM_BAR_SIZE
                argument._obj.offset = 0x100000
                argument._obj.flags = (tool.VFIO_REGION_INFO_FLAG_READ |
                                       tool.VFIO_REGION_INFO_FLAG_WRITE |
                                       tool.VFIO_REGION_INFO_FLAG_MMAP)
                return 0
            raise AssertionError(hex(request))

        with patch.object(tool.os, 'open', side_effect=lambda *a, **k: next(opened)) as op, \
             patch.object(tool, 'ioctl', side_effect=fake_ioctl), \
             patch.object(tool.mmap, 'mmap', return_value=mapping) as mm, \
             patch.object(tool.os, 'close'), \
             patch.object(tool.Bar0ReadTransport, 'close'):
            transport = tool.Bar0ReadTransport()
            transport.__enter__()
        self.assertEqual(region_indices, [tool.VFIO_PCI_BAR0_REGION_INDEX])
        self.assertEqual(len(op.call_args_list), 2)
        self.assertTrue(all(call.args[1] & tool.os.O_RDWR
                            for call in op.call_args_list))
        self.assertEqual(mm.call_args.kwargs['prot'], mmap.PROT_READ)
        self.assertEqual(mm.call_args.kwargs['flags'], mmap.MAP_SHARED)
        self.assertFalse(mm.call_args.kwargs['prot'] & mmap.PROT_WRITE)

    def test_transport_rejects_every_nonexact_range_and_has_no_mutator(self):
        transport = self.tool.Bar0ReadTransport()
        transport.bar0 = bytes(self.tool.VRAM_BAR_SIZE)
        with self.assertRaisesRegex(self.tool.ObserverError, 'forbidden'):
            transport.read_range('ring', self.tool.RANGES_BY_NAME['ring'][0] + 4,
                                 self.tool.RANGES_BY_NAME['ring'][1])
        with self.assertRaisesRegex(self.tool.ObserverError, 'forbidden'):
            transport.read_range('unknown', 0, 4)
        self.assertFalse(hasattr(transport, 'write32'))
        self.assertFalse(hasattr(transport, 'write_vram'))
        self.assertFalse(hasattr(transport, 'ring_doorbell64'))


if __name__ == '__main__':
    unittest.main()
