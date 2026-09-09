import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / 'tools' / 'inspect-noqueue.py'


def load_tool():
    spec = importlib.util.spec_from_file_location('inspect_noqueue', TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeTransport:
    def __init__(self, tool, run_id=None):
        self.tool = tool
        self.run_id = run_id or tool.RUN_ID
        self.registers = {offset: 0 for offset in tool.OBSERVATION_OFFSETS}
        self.registers[tool.RECOVERY.NBIO_CONFIG_MEMSIZE_OFFSET] = (
            tool.RECOVERY.EXPECTED_CONFIG_MEMSIZE)
        self.registers[tool.RECOVERY.CP_ME_CNTL_OFFSET] = tool.RECOVERY.CP_ME_HALT_MASK
        self.registers[tool.RECOVERY.CP_MEC_CNTL_OFFSET] = tool.RECOVERY.CP_MEC_HALT_MASK
        self.registers[tool.RECOVERY.SDMA0_F32_CNTL_OFFSET] = tool.RECOVERY.SDMA_HALT_MASK
        self.descriptor = tool.RECOVERY.host_kiq_reservation_descriptor(
            self.run_id, tool.RECOVERY.HOST_KIQ_RESERVATION_PENDING)
        self.reads = []
        self.vram_reads = []
        self.writes = []
        self.fail_read_offset = None
        self.fail_write_number = None

    def __enter__(self):
        return self

    def __exit__(self, kind, error, trace):
        return False

    def read32(self, offset):
        self.reads.append(offset)
        if offset == self.fail_read_offset:
            raise OSError('injected read failure')
        return self.registers[offset]

    def write32(self, offset, value):
        self.writes.append((offset, value))
        if len(self.writes) == self.fail_write_number:
            raise OSError('injected posting-read failure')

    def read_vram32(self, offset):
        self.vram_reads.append(offset)
        start = offset - self.tool.RECOVERY.HOST_KIQ_RESERVATION_OFFSET
        return int.from_bytes(self.descriptor[start:start + 4], 'little')

    def metadata(self):
        return {'regions': {'0': {'index': 0}, '5': {'index': 5}}}


class InspectNoQueueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tool = load_tool()

    def valid_proof(self):
        tool = self.tool
        return {
            'boot_id': tool.BOOT_ID,
            'run_id': tool.RUN_ID,
            'host': {
                'boot_id': tool.BOOT_ID, 'active_vm': False,
                'driver': 'vfio-pci', 'device': '1002:13c0',
                'iommu_group': '31', 'pci_command': 3, 'reset_methods': [],
                'watchdogs': {'watchdog': '1', 'nmi_watchdog': '1',
                              'hardlockup_panic': '1'},
            },
            'ledger_sha256': tool.PINNED_HASHES['ledger'],
            'ledger': {'schema': 2, 'boot_id': tool.BOOT_ID, 'max_launches': 3,
                       'launches': [{'run_id': tool.RUN_ID,
                                     'reserved_epoch': 1788934306.1812477}]},
            'artifact_sha256': dict(tool.PINNED_HASHES),
            'manifest': {'boot_id': tool.BOOT_ID, 'run_id': tool.RUN_ID,
                         'build_id': tool.BUILD_ID},
            'artifact_manifest_equal': True,
            'supervision': {'cid': tool.CID, 'max_seconds': 180,
                            'timer_unit': f'rgpu-deadline-{tool.CID}.timer',
                            'serial_unit': f'rgpu-serial-{tool.CID}.service',
                            'launch_unit': 'rgpu-launch-78867607cb944e11967297dce6b21b02.service'},
            'shutdown': {'cid': tool.CID, 'outcome': 'exited-after-guest-request'},
            'recovery': {'status': 'failed', 'error': tool.EXPECTED_RECOVERY_ERROR},
            'recovery_reservation': {'boot_id': tool.BOOT_ID,
                                     'run_id': tool.RUN_ID, 'state': 'pending'},
            'continuation': {'schema': 1, 'kind': 'one-shot-prelaunch-continuation',
                             'boot_id': tool.BOOT_ID, 'run_id': tool.RUN_ID,
                             'kernel_cursor': tool.ACTUAL_KERNEL_CURSOR,
                             'ledger_sha256': tool.PINNED_HASHES['ledger'],
                             'replacement_manifest_sha256': tool.PINNED_HASHES['manifest'],
                             'marker': '/configured/vm/' + str(tool.CONTINUATION_MARKER_RELATIVE)},
            'marker_equal': True,
            'continuation_marker_matches': True,
            'serial_boundary': dict(tool.EXPECTED_SERIAL_BOUNDARY),
            'container_running': False,
            'residual_units': [],
            'journal_cursor': 'cursor-before',
            'journal_messages': [],
            'journal_faults': [],
        }

    def test_guard_refuses_every_write_except_valid_selector(self):
        fake = FakeTransport(self.tool)
        guard = self.tool.GuardedTransport(fake)
        for value in (0, 1, self.tool.RECOVERY.queue_selector(1, 0, 0),
                      self.tool.RECOVERY.queue_selector(2, 3, 7)):
            guard.write32(self.tool.RECOVERY.GRBM_GFX_CNTL_OFFSET, value)
        with self.assertRaisesRegex(self.tool.InspectionError, 'write is forbidden'):
            guard.write32(self.tool.RECOVERY.CP_HQD_ACTIVE_OFFSET, 0)
        with self.assertRaisesRegex(self.tool.InspectionError, 'selector value'):
            guard.write32(self.tool.RECOVERY.GRBM_GFX_CNTL_OFFSET, 0xdeadbeef)
        self.assertEqual({offset for offset, _ in fake.writes},
                         {self.tool.RECOVERY.GRBM_GFX_CNTL_OFFSET})

    def test_guard_refuses_unlisted_and_vram_reads_outside_descriptor(self):
        fake = FakeTransport(self.tool)
        guard = self.tool.GuardedTransport(fake)
        unsafe_sem_offset = (self.tool.RECOVERY.GC_SEG0 + 0x160d) * 4
        with self.assertRaisesRegex(self.tool.InspectionError, 'read is forbidden'):
            guard.read32(unsafe_sem_offset)
        with self.assertRaisesRegex(self.tool.InspectionError, 'VRAM read is forbidden'):
            guard.read_vram32(self.tool.RECOVERY.HOST_KIQ_RESERVATION_OFFSET - 4)
        self.assertEqual(fake.reads, [])
        self.assertEqual(fake.vram_reads, [])

    def test_complete_scan_uses_exact_read_and_write_allowlists(self):
        fake = FakeTransport(self.tool)
        result = self.tool.inspect_device(fake, self.tool.RUN_ID)
        self.assertEqual(len(result['compute_passes']), 2)
        self.assertEqual([len(row) for row in result['compute_passes']], [64, 64])
        self.assertEqual(len(result['graphics_passes']), 2)
        self.assertEqual([len(row) for row in result['graphics_passes']], [2, 2])
        self.assertTrue(result['final_default']['completed'])
        self.assertTrue(all(offset in self.tool.OBSERVATION_OFFSETS |
                            {self.tool.RECOVERY.NBIO_CONFIG_MEMSIZE_OFFSET}
                            for offset in fake.reads))
        self.assertEqual({offset for offset, _ in fake.writes},
                         {self.tool.RECOVERY.GRBM_GFX_CNTL_OFFSET})
        compute = [self.tool.RECOVERY.queue_selector(me, pipe, queue)
                   for me in (1, 2) for pipe in range(4) for queue in range(8)]
        expected_values = [0] + compute + [0, 1] + compute + [0, 1, 0, 0]
        self.assertEqual([value for _, value in fake.writes], expected_values)
        self.assertEqual([row['value'] for row in result['selector_writes']],
                         expected_values)
        self.assertTrue(all(row['attempted'] and row['completed']
                            for row in result['selector_writes']))
        self.assertEqual(fake.writes[-1], (self.tool.RECOVERY.GRBM_GFX_CNTL_OFFSET, 0))
        self.assertEqual(result['status'], 'observed-idle')
        self.assertFalse(result['authorizes_cleanup'])
        self.assertFalse(result['authorizes_launch'])

    def test_all_ones_or_active_compute_queue_is_rejected(self):
        for raw, message in ((0xffffffff, 'inaccessible'), (1, 'active')):
            with self.subTest(raw=raw):
                fake = FakeTransport(self.tool)
                fake.registers[self.tool.RECOVERY.CP_HQD_ACTIVE_OFFSET] = raw
                with self.assertRaisesRegex(self.tool.InspectionError, message) as raised:
                    self.tool.inspect_device(fake, self.tool.RUN_ID)
                self.assertTrue(raised.exception.evidence['final_default']['completed'])

    def test_active_or_inaccessible_graphics_state_is_rejected(self):
        for offset, raw, message in (
                (self.tool.CP_RB1_ACTIVE_OFFSET, 1, 'graphics ring is active'),
                (self.tool.RECOVERY.CP_RB_DOORBELL_CONTROL_OFFSET,
                 0x40000000, 'graphics doorbell is enabled'),
                (self.tool.CP_RB1_ACTIVE_OFFSET, 0xffffffff, 'inaccessible')):
            with self.subTest(offset=offset, raw=raw):
                fake = FakeTransport(self.tool)
                fake.registers[offset] = raw
                with self.assertRaisesRegex(self.tool.InspectionError, message):
                    self.tool.inspect_device(fake, self.tool.RUN_ID)

    def test_selector_aware_pipe1_graphics_activity_is_rejected(self):
        class BankedTransport(FakeTransport):
            def __init__(inner, tool):
                super().__init__(tool)
                inner.selector = None

            def write32(inner, offset, value):
                super().write32(offset, value)
                inner.selector = value

            def read32(inner, offset):
                value = super().read32(offset)
                if (inner.selector == 1 and
                        offset == inner.tool.CP_RB1_ACTIVE_OFFSET):
                    return 1
                return value

        fake = BankedTransport(self.tool)
        with self.assertRaisesRegex(self.tool.InspectionError,
                                    'graphics ring is active') as raised:
            self.tool.inspect_device(fake, self.tool.RUN_ID)
        rows = raised.exception.evidence['graphics_passes']
        self.assertEqual([item['selector'] for item in rows[0]], [0, 1])
        self.assertEqual(rows[0][0]['rb1_active'], 0)
        self.assertEqual(rows[0][1]['rb1_active'], 1)

    def test_nonidle_or_inaccessible_global_is_rejected(self):
        cases = (
            (self.tool.RECOVERY.CP_STAT_OFFSET, 1, 'CP_STAT'),
            (self.tool.RECOVERY.CP_CPC_BUSY_STAT_OFFSET, 1, 'CPC_BUSY'),
            (self.tool.RECOVERY.SDMA0_CNTL_OFFSET,
             self.tool.RECOVERY.SDMA_AUTO_CTXSW_ENABLE_MASK, 'context switching'),
            (self.tool.RECOVERY.SDMA0_GFX_RB_CNTL_OFFSET, 1, 'ring buffer'),
            (self.tool.RECOVERY.SDMA0_GFX_IB_CNTL_OFFSET, 1, 'indirect buffer'),
            (self.tool.RECOVERY.SDMA0_F32_CNTL_OFFSET, 0, 'not halted'),
            (self.tool.RECOVERY.CP_PQ_STATUS_OFFSET, 0xffffffff, 'inaccessible'),
        )
        for offset, raw, message in cases:
            with self.subTest(offset=offset, raw=raw):
                fake = FakeTransport(self.tool)
                fake.registers[offset] = raw
                with self.assertRaisesRegex(self.tool.InspectionError, message):
                    self.tool.inspect_device(fake, self.tool.RUN_ID)

    def test_changing_compute_or_global_state_is_rejected(self):
        class ChangingTransport(FakeTransport):
            def read32(inner, offset):
                value = super(ChangingTransport, inner).read32(offset)
                if offset == inner.tool.RECOVERY.CP_HQD_ACTIVE_OFFSET and \
                        inner.reads.count(offset) == 65:
                    return 2
                return value
        fake = ChangingTransport(self.tool)
        with self.assertRaisesRegex(self.tool.InspectionError, 'compute snapshots changed'):
            self.tool.inspect_device(fake, self.tool.RUN_ID)

        fake = FakeTransport(self.tool)
        original = fake.read32
        count = [0]
        def changing_global(offset):
            value = original(offset)
            if offset == self.tool.RECOVERY.CP_ME_CNTL_OFFSET:
                count[0] += 1
                if count[0] == 2:
                    return value ^ 2
            return value
        fake.read32 = changing_global
        with self.assertRaisesRegex(self.tool.InspectionError, 'global snapshots changed'):
            self.tool.inspect_device(fake, self.tool.RUN_ID)

    def test_hqd_doorbell_is_observed_without_disabled_bit_gate(self):
        fake = FakeTransport(self.tool)
        fake.registers[self.tool.RECOVERY.CP_HQD_PQ_DOORBELL_OFFSET] = 0x40000002
        result = self.tool.inspect_device(fake, self.tool.RUN_ID)
        self.assertEqual(result['compute_passes'][0][0]['pq_doorbell_control'],
                         0x40000002)

        fake = FakeTransport(self.tool)
        fake.registers[self.tool.RECOVERY.CP_HQD_PQ_DOORBELL_OFFSET] = 0xffffffff
        with self.assertRaisesRegex(self.tool.InspectionError,
                                    'pq_doorbell_control is inaccessible'):
            self.tool.inspect_device(fake, self.tool.RUN_ID)

    def test_pending_descriptor_must_match_before_and_after(self):
        fake = FakeTransport(self.tool)
        fake.descriptor = b'\0' * len(fake.descriptor)
        with self.assertRaisesRegex(self.tool.InspectionError, 'PENDING descriptor before'):
            self.tool.inspect_device(fake, self.tool.RUN_ID)
        self.assertEqual(fake.writes, [])

        fake = FakeTransport(self.tool)
        original = fake.read_vram32
        reads = [0]
        def changing_descriptor(offset):
            reads[0] += 1
            return original(offset) if reads[0] <= 18 else 0
        fake.read_vram32 = changing_descriptor
        with self.assertRaisesRegex(self.tool.InspectionError, 'PENDING descriptor after'):
            self.tool.inspect_device(fake, self.tool.RUN_ID)

    def test_final_default_is_attempted_after_read_and_posting_exceptions(self):
        fake = FakeTransport(self.tool)
        fake.fail_read_offset = self.tool.RECOVERY.CP_STAT_OFFSET
        with self.assertRaises(self.tool.InspectionError) as raised:
            self.tool.inspect_device(fake, self.tool.RUN_ID)
        self.assertTrue(raised.exception.evidence['final_default']['completed'])
        self.assertEqual(fake.writes[-1], (self.tool.RECOVERY.GRBM_GFX_CNTL_OFFSET, 0))

        fake = FakeTransport(self.tool)
        fake.fail_write_number = 135
        with self.assertRaisesRegex(self.tool.InspectionError,
                                    'final default selector posting failed') as raised:
            self.tool.inspect_device(fake, self.tool.RUN_ID)
        final = raised.exception.evidence['final_default']
        self.assertTrue(final['attempted'])
        self.assertFalse(final['completed'])
        self.assertNotEqual(raised.exception.evidence['status'], 'observed-idle')

        fake = FakeTransport(self.tool)
        fake.fail_write_number = 2
        with self.assertRaises(self.tool.InspectionError) as raised:
            self.tool.inspect_device(fake, self.tool.RUN_ID)
        writes = raised.exception.evidence['selector_writes']
        self.assertTrue(writes[1]['attempted'])
        self.assertFalse(writes[1]['completed'])
        self.assertTrue(raised.exception.evidence['final_default']['completed'])
        self.assertEqual(fake.writes[-1], (self.tool.RECOVERY.GRBM_GFX_CNTL_OFFSET, 0))

    def test_invalid_static_proof_fails_before_transport_is_opened(self):
        proof = self.valid_proof()
        proof['artifact_sha256']['serial'] = '0' * 64
        opened = []
        with self.assertRaisesRegex(self.tool.InspectionError, 'serial'):
            self.tool.perform_inspection(lambda: proof,
                                         lambda: opened.append(True),
                                         lambda cursor: self.valid_proof())
        self.assertEqual(opened, [])

        opened = []
        def broken_proof():
            raise OSError('pinned file unreadable')
        with self.assertRaisesRegex(self.tool.InspectionError,
                                    'pre-VFIO proof collection failed'):
            self.tool.perform_inspection(broken_proof,
                                         lambda: opened.append(True),
                                         lambda cursor: self.valid_proof())
        self.assertEqual(opened, [])

    def test_removed_exact_container_is_idle_but_other_inspect_errors_fail(self):
        missing = type('Result', (), {
            'returncode': 1, 'stdout': '',
            'stderr': 'error: no such object: ' + self.tool.CID})()
        with patch.object(self.tool.subprocess, 'run', return_value=missing):
            self.assertFalse(self.tool._container_running(self.tool.CID))

        unavailable = type('Result', (), {
            'returncode': 1, 'stdout': '', 'stderr': 'daemon unavailable'})()
        with patch.object(self.tool.subprocess, 'run', return_value=unavailable):
            with self.assertRaisesRegex(self.tool.InspectionError,
                                        'cannot establish exact container state'):
                self.tool._container_running(self.tool.CID)

    def test_actual_archive_proves_split_bar0_refusal_and_complete_critical_records(self):
        evidence = ROOT / 'findings/experiments/metal-007-174-prelaunch-continuation'
        observed = self.tool._serial_boundary(
            (evidence / 'serial.txt').read_text(),
            (evidence / 'events.jsonl').read_text())
        self.assertEqual(observed, self.tool.EXPECTED_SERIAL_BOUNDARY)

    def test_transport_open_and_close_failures_still_run_postflight(self):
        class BrokenEnter:
            def __enter__(inner):
                raise self.tool.RECOVERY.RecoveryError('open failed')

            def __exit__(inner, kind, error, trace):
                return False

        class BrokenExit(FakeTransport):
            def __exit__(inner, kind, error, trace):
                raise OSError('close failed')

        for factory, message in ((lambda: BrokenEnter(), 'open failed'),
                                 (lambda: BrokenExit(self.tool), 'close failed')):
            with self.subTest(message=message):
                post_calls = []
                def post(cursor):
                    post_calls.append(cursor)
                    return self.valid_proof()
                with self.assertRaisesRegex(self.tool.InspectionError, message) as raised:
                    self.tool.perform_inspection(self.valid_proof, factory, post)
                self.assertEqual(post_calls, ['cursor-before'])
                self.assertIn('postflight', raised.exception.evidence)
                self.assertFalse(raised.exception.evidence['authorizes_cleanup'])
                self.assertFalse(raised.exception.evidence['authorizes_launch'])
                if message == 'close failed':
                    self.assertEqual(raised.exception.evidence['device']['status'],
                                     'observed-idle')

    def test_postflight_change_and_kernel_fault_are_rejected(self):
        for mutate, message in (
                (lambda proof: proof['host'].__setitem__('pci_command', 7), 'post-inspection'),
                (lambda proof: proof['journal_faults'].append('IO_PAGE_FAULT'), 'kernel fault'),
                (lambda proof: proof['residual_units'].append('rgpu-launch-x.service'),
                 'residual unit')):
            with self.subTest(message=message):
                pre = self.valid_proof()
                post = self.valid_proof()
                mutate(post)
                fake = FakeTransport(self.tool)
                with self.assertRaisesRegex(self.tool.InspectionError, message):
                    self.tool.perform_inspection(lambda: pre, lambda: fake,
                                                 lambda cursor: post)

    def test_output_is_create_once_and_never_an_authorization(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'inspection.json'
            evidence = {'schema': 1, 'kind': 'stopped-gpu-noqueue-inspection',
                        'status': 'observed-idle', 'authorizes_cleanup': False,
                        'authorizes_launch': False}
            self.tool.write_inspection_once(output, evidence)
            self.assertEqual(json.loads(output.read_text()), evidence)
            with self.assertRaises(FileExistsError):
                self.tool.write_inspection_once(output, evidence)

    def test_live_entrypoint_requires_distinct_pinned_inspection_output(self):
        with tempfile.TemporaryDirectory() as temp:
            vm = Path(temp)
            (vm / 'run').mkdir()
            exact_name = f'{self.tool.BOOT_ID}-{self.tool.RUN_ID}.json'
            wrong = vm / 'run/vfio-recovery' / (self.tool.RUN_ID + '.json')
            with patch.object(self.tool, 'collect_proof',
                              side_effect=AssertionError('must fail before proof')):
                with self.assertRaisesRegex(self.tool.InspectionError,
                                            'distinct noqueue inspection path'):
                    self.tool.inspect_once(vm, Path(temp) / 'evidence', wrong)

            wrong_root_proof = self.valid_proof()
            wrong_root_proof['continuation_marker_matches'] = False
            opened = []
            output = vm / 'run/noqueue-inspections' / exact_name
            with patch.object(self.tool, 'collect_proof', return_value=wrong_root_proof), \
                 patch.object(self.tool.RECOVERY, 'LegacyVfio',
                              side_effect=lambda: opened.append(True)):
                with self.assertRaisesRegex(self.tool.InspectionError,
                                            'consumed continuation marker'):
                    self.tool.inspect_once(vm, Path(temp) / 'evidence', output)
            self.assertEqual(opened, [])
            artifact = json.loads(output.read_text())
            self.assertFalse(artifact['authorizes_cleanup'])
            self.assertFalse(artifact['authorizes_launch'])


if __name__ == '__main__':
    unittest.main()
