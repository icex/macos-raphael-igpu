import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / 'tools/startup-noqueue-recover.py'
INSPECTION_PATH = (ROOT / 'findings/recovery-tests/startup-noqueue-174/'
                   'inspection.json')


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeTransport:
    def __init__(self, tool, pinned):
        self.tool = tool
        self.inspector = tool.INSPECTOR
        self.recovery = tool.RECOVERY
        self.selector = 0
        self.descriptor = bytes.fromhex(pinned['device']['reservation_before_hex'])
        self.registers = {}
        for name, offset in self.inspector.GLOBAL_OFFSETS.items():
            self.registers[offset] = pinned['device']['globals_after'][name]
        self.registers[self.tool.SDMA0_STATUS_REG_OFFSET] = self.tool.SDMA_STATUS_IDLE_MASK
        for offset in self.tool.SDMA_AUX_OFFSETS.values():
            self.registers.setdefault(offset, 0)
        self.registers[self.recovery.NBIO_CONFIG_MEMSIZE_OFFSET] = \
            self.recovery.EXPECTED_CONFIG_MEMSIZE
        self.registers[self.recovery.C2PMSG_64_OFFSET] = 0
        self.writes = []
        self.vram_writes = []
        self.flushes = []
        self.freeze_f32 = False
        self.fail_psp = False
        self.psp_status = 0
        self.hqd_doorbell_after_halt = 0
        self.fail_hqd_read = False
        self.fail_final_scan = False
        self.fail_default_after_read = False
        self._hqd_reads = 0
        self.f32_allones_before_write = False
        self.status_allones_after_halt = False
        self.late_sdma_input = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read32(self, offset):
        late_masks = {
            self.recovery.SDMA0_CNTL_OFFSET:
                self.recovery.SDMA_AUTO_CTXSW_ENABLE_MASK,
            self.recovery.SDMA0_GFX_RB_CNTL_OFFSET:
                self.recovery.SDMA_RB_ENABLE_MASK,
            self.recovery.SDMA0_GFX_IB_CNTL_OFFSET:
                self.recovery.SDMA_IB_ENABLE_MASK,
        }
        if (offset == self.late_sdma_input and self._hqd_reads >= 192 and
                self.registers[self.recovery.CP_ME_CNTL_OFFSET] &
                self.recovery.CP_ME_HALT_MASK):
            return self.registers[offset] | late_masks[offset]
        if (offset == self.recovery.SDMA0_F32_CNTL_OFFSET and
                self.f32_allones_before_write and
                self.registers[self.recovery.CP_ME_CNTL_OFFSET] &
                self.recovery.CP_ME_HALT_MASK):
            return 0xffffffff
        if (offset == self.tool.SDMA0_STATUS_REG_OFFSET and
                self.status_allones_after_halt and
                self.registers[self.recovery.SDMA0_F32_CNTL_OFFSET] & 1):
            return 0xffffffff
        if offset == self.recovery.CP_HQD_ACTIVE_OFFSET:
            self._hqd_reads += 1
            if self.fail_hqd_read and self._hqd_reads > 130:
                self.fail_default_after_read = True
                raise OSError('injected HQD read failure')
            if self.fail_final_scan and self._hqd_reads > 194:
                self.fail_default_after_read = True
                raise OSError('injected final scan read failure')
        if offset == self.recovery.CP_HQD_PQ_DOORBELL_OFFSET:
            if (self.registers[self.recovery.CP_ME_CNTL_OFFSET] &
                    self.recovery.CP_ME_HALT_MASK):
                return self.hqd_doorbell_after_halt
            return 0
        if offset in (self.recovery.CP_HQD_ACTIVE_OFFSET,
                      self.recovery.CP_RB_ACTIVE_OFFSET,
                      self.tool.INSPECTOR.CP_RB1_ACTIVE_OFFSET,
                      self.recovery.CP_RB_DOORBELL_CONTROL_OFFSET):
            return 0
        return self.registers[offset]

    def write32(self, offset, value):
        self.writes.append((offset, value))
        if offset == self.recovery.GRBM_GFX_CNTL_OFFSET:
            if value == 0 and self.fail_default_after_read:
                raise OSError('injected final selector failure')
            self.selector = value
            return
        if offset == self.recovery.C2PMSG_64_OFFSET:
            if self.fail_psp:
                self.registers[offset] = value
            else:
                self.registers[offset] = 0x80000000 | value | self.psp_status
            return
        if offset == self.recovery.SDMA0_F32_CNTL_OFFSET and self.freeze_f32:
            return
        self.registers[offset] = value

    def read_vram32(self, offset):
        start = offset - self.recovery.HOST_KIQ_RESERVATION_OFFSET
        return int.from_bytes(self.descriptor[start:start + 4], 'little')

    def write_vram(self, offset, data):
        self.vram_writes.append((offset, bytes(data)))
        self.descriptor = bytes(data)

    def flush_hdp(self):
        value = {'remap': self.recovery.HDP_MEM_FLUSH_NATIVE_OFFSET,
                 'posted_read': self.recovery.EXPECTED_CONFIG_MEMSIZE}
        self.flushes.append(value)
        return value

    def metadata(self):
        return {'index': 5, 'size': 524288, 'offset': 5497558138880,
                'read': True, 'write': True, 'mmap': True,
                'regions': {
                    '0': {'index': 0, 'size': 268435456, 'offset': 0,
                          'read': True, 'write': True, 'mmap': True},
                    '2': {'index': 2, 'size': 2097152, 'offset': 2199023255552,
                          'read': True, 'write': True, 'mmap': True},
                    '5': {'index': 5, 'size': 524288, 'offset': 5497558138880,
                          'read': True, 'write': True, 'mmap': True}}}


class StartupNoQueueRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tool = load(TOOL_PATH, 'startup_noqueue_recover')
        cls.tool.RECOVERY.EXPECTED_CONFIG_MEMSIZE = 0x200
        cls.inspection_bytes = INSPECTION_PATH.read_bytes()
        cls.inspection = json.loads(cls.inspection_bytes)
        archive = ROOT / 'findings/experiments/metal-007-174-prelaunch-continuation'
        cls.archive_sha, cls.archive_files = cls.tool.archive_digest(archive)

    def test_only_exact_failed_inspection_with_f32_zero_is_eligible(self):
        self.assertEqual(self.tool.validate_pinned_inspection(self.inspection_bytes), [])

        for mutate, message in (
                (lambda row: row.__setitem__('status', 'observed-idle'), 'status'),
                (lambda row: row['device']['globals_after'].__setitem__(
                    'sdma0_f32_cntl', 1), 'inspection hash'),
                (lambda row: row['device']['compute_passes'][0][0].__setitem__(
                    'active', 1), 'inspection hash')):
            with self.subTest(message=message):
                changed = json.loads(self.inspection_bytes)
                mutate(changed)
                raw = json.dumps(changed, sort_keys=True).encode()
                self.assertIn(message, ','.join(
                    self.tool.validate_pinned_inspection(raw)))

    def test_fresh_scan_must_match_pinned_unhalted_state_before_cleanup(self):
        fake = FakeTransport(self.tool, self.inspection)
        fake.registers[self.tool.RECOVERY.CP_PQ_STATUS_OFFSET] ^= 1
        with self.assertRaisesRegex(self.tool.StartupRecoveryError,
                                    'fresh scan differs') as raised:
            self.tool.execute_transaction(
                fake, self.inspection, sleep=lambda _: None, polls=2)
        nonselectors = [(offset, value) for offset, value in fake.writes
                        if offset != self.tool.RECOVERY.GRBM_GFX_CNTL_OFFSET]
        self.assertEqual(nonselectors, [])
        self.assertTrue(raised.exception.evidence['pre_scan']['final_default']['completed'])

    def test_transaction_orders_only_source_backed_writes_and_consumes_pending_last(self):
        fake = FakeTransport(self.tool, self.inspection)
        evidence = self.tool.execute_transaction(
            fake, self.inspection, sleep=lambda _: None, polls=2)
        self.assertEqual(evidence['status'], 'recovered')
        self.assertFalse(evidence['authorizes_launch'])
        self.assertEqual(evidence['sdma_status_before_halt'] & 1, 1)
        self.assertEqual(evidence['sdma_status_after_halt'] & 1, 1)
        self.assertEqual(evidence['final_scan']['globals_after']['sdma0_f32_cntl'] & 1, 1)
        self.assertTrue(evidence['final_scan']['final_default']['completed'])
        self.assertEqual(evidence['reservation']['before_hex'],
                         self.inspection['device']['reservation_before_hex'])
        self.assertEqual(evidence['reservation']['after_hex'], '00' * 72)

        nonselectors = [(row['offset'], row['value']) for row in evidence['writes']
                        if row['region'] == 'BAR5' and
                        row.get('offset') != self.tool.RECOVERY.GRBM_GFX_CNTL_OFFSET and
                        row['operation'] == 'write32']
        self.assertEqual(nonselectors, [
            (self.tool.RECOVERY.CP_ME_CNTL_OFFSET,
             self.tool.RECOVERY.CP_ME_HALT_MASK),
            (self.tool.RECOVERY.CP_MEC_CNTL_OFFSET,
             self.tool.RECOVERY.CP_MEC_HALT_MASK),
            (self.tool.RECOVERY.SDMA0_F32_CNTL_OFFSET, 1),
            (self.tool.RECOVERY.C2PMSG_64_OFFSET, self.tool.RECOVERY.DESTROY_RINGS),
            (self.tool.RECOVERY.C2PMSG_64_OFFSET,
             self.tool.RECOVERY.DESTROY_GPCOM_RING),
        ])
        self.assertEqual(evidence['writes'][-2]['region'], 'BAR0')
        self.assertEqual(evidence['writes'][-1]['operation'], 'flush_hdp')
        self.assertEqual(len(fake.vram_writes), 1)

    def test_sdma_must_be_idle_before_halt_or_psp(self):
        fake = FakeTransport(self.tool, self.inspection)
        fake.registers[self.tool.SDMA0_STATUS_REG_OFFSET] = 0
        with self.assertRaisesRegex(self.tool.StartupRecoveryError,
                                    'SDMA0 status is not idle'):
            self.tool.execute_transaction(
                fake, self.inspection, sleep=lambda _: None, polls=2)
        nonselectors = [(offset, value) for offset, value in fake.writes
                        if offset != self.tool.RECOVERY.GRBM_GFX_CNTL_OFFSET]
        self.assertEqual(nonselectors, [])

    def test_page_and_rlc_inputs_must_be_disabled_accessible_and_stable(self):
        for name, raw in (('page_rb_cntl', 1), ('page_ib_cntl', 0xffffffff),
                          ('rlc0_rb_cntl', 1), ('rlc0_ib_cntl', 1),
                          ('rlc1_rb_cntl', 1), ('rlc1_ib_cntl', 1)):
            with self.subTest(name=name, raw=raw):
                fake = FakeTransport(self.tool, self.inspection)
                fake.registers[self.tool.SDMA_AUX_OFFSETS[name]] = raw
                with self.assertRaises(self.tool.StartupRecoveryError):
                    self.tool.execute_transaction(
                        fake, self.inspection, sleep=lambda _: None, polls=2)
                self.assertEqual([(offset, value) for offset, value in fake.writes
                                  if offset != self.tool.RECOVERY.GRBM_GFX_CNTL_OFFSET], [])

        fake = FakeTransport(self.tool, self.inspection)
        original = fake.read32
        count = [0]
        def changing(offset):
            value = original(offset)
            if offset == self.tool.SDMA_AUX_OFFSETS['rlc1_ib_cntl']:
                count[0] += 1
                if count[0] == 2:
                    return value | 2
            return value
        fake.read32 = changing
        with self.assertRaisesRegex(self.tool.StartupRecoveryError,
                                    'observations changed'):
            self.tool.execute_transaction(
                fake, self.inspection, sleep=lambda _: None, polls=2)
        self.assertEqual([(offset, value) for offset, value in fake.writes
                          if offset != self.tool.RECOVERY.GRBM_GFX_CNTL_OFFSET], [])

    def test_failed_halt_never_reaches_psp_or_descriptor_consume(self):
        fake = FakeTransport(self.tool, self.inspection)
        fake.freeze_f32 = True
        with self.assertRaisesRegex(self.tool.StartupRecoveryError,
                                    'SDMA0 halt did not persist'):
            self.tool.execute_transaction(
                fake, self.inspection, sleep=lambda _: None, polls=2)
        self.assertFalse(any(offset == self.tool.RECOVERY.C2PMSG_64_OFFSET
                             for offset, _ in fake.writes))
        self.assertEqual(fake.vram_writes, [])

        for mode in ('f32', 'status'):
            with self.subTest(mode=mode):
                fake = FakeTransport(self.tool, self.inspection)
                if mode == 'f32':
                    fake.f32_allones_before_write = True
                else:
                    fake.status_allones_after_halt = True
                with self.assertRaises(self.tool.StartupRecoveryError):
                    self.tool.execute_transaction(
                        fake, self.inspection, sleep=lambda _: None, polls=2)
                self.assertFalse(any(offset == self.tool.RECOVERY.C2PMSG_64_OFFSET
                                     for offset, _ in fake.writes))
                self.assertEqual(fake.vram_writes, [])

    def test_each_gfx_or_context_input_is_rechecked_before_f32_write(self):
        cases = (
            (self.tool.RECOVERY.SDMA0_CNTL_OFFSET, 'auto_ctxsw',
             self.tool.RECOVERY.SDMA_AUTO_CTXSW_ENABLE_MASK),
            (self.tool.RECOVERY.SDMA0_GFX_RB_CNTL_OFFSET, 'gfx_rb',
             self.tool.RECOVERY.SDMA_RB_ENABLE_MASK),
            (self.tool.RECOVERY.SDMA0_GFX_IB_CNTL_OFFSET, 'gfx_ib',
             self.tool.RECOVERY.SDMA_IB_ENABLE_MASK),
        )
        for offset, name, mask in cases:
            with self.subTest(offset=offset, name=name):
                fake = FakeTransport(self.tool, self.inspection)
                fake.late_sdma_input = offset
                with self.assertRaisesRegex(self.tool.StartupRecoveryError,
                                            'GFX/context input') as raised:
                    self.tool.execute_transaction(
                        fake, self.inspection, sleep=lambda _: None, polls=2)
                immediate = raised.exception.evidence[
                    'sdma_inputs_immediate_before_halt']
                self.assertEqual(immediate[name] & mask, mask)
                self.assertFalse(any(written ==
                                     self.tool.RECOVERY.SDMA0_F32_CNTL_OFFSET
                                     for written, _ in fake.writes))
                self.assertFalse(any(written == self.tool.RECOVERY.C2PMSG_64_OFFSET
                                     for written, _ in fake.writes))
                self.assertEqual(fake.vram_writes, [])

    def test_post_halt_hqd_doorbell_change_aborts_without_clear_or_psp(self):
        fake = FakeTransport(self.tool, self.inspection)
        fake.hqd_doorbell_after_halt = 2
        with self.assertRaisesRegex(self.tool.StartupRecoveryError,
                                    'HQD doorbell changed'):
            self.tool.execute_transaction(
                fake, self.inspection, sleep=lambda _: None, polls=2)
        self.assertFalse(any(offset == self.tool.RECOVERY.CP_HQD_PQ_DOORBELL_OFFSET
                             for offset, _ in fake.writes))
        self.assertFalse(any(offset == self.tool.RECOVERY.C2PMSG_64_OFFSET
                             for offset, _ in fake.writes))
        self.assertEqual(fake.vram_writes, [])

    def test_psp_failure_preserves_pending_and_default_selector_evidence(self):
        fake = FakeTransport(self.tool, self.inspection)
        fake.fail_psp = True
        with self.assertRaises(self.tool.StartupRecoveryError) as raised:
            self.tool.execute_transaction(
                fake, self.inspection, sleep=lambda _: None, polls=2)
        self.assertEqual(fake.vram_writes, [])
        selectors = [row for row in raised.exception.evidence['writes']
                     if row.get('offset') == self.tool.RECOVERY.GRBM_GFX_CNTL_OFFSET]
        self.assertTrue(selectors[-1]['completed'])
        self.assertEqual(selectors[-1]['value'], 0)

    def test_psp_nonzero_low_status_never_consumes_pending(self):
        fake = FakeTransport(self.tool, self.inspection)
        fake.psp_status = 1
        with self.assertRaises(self.tool.StartupRecoveryError):
            self.tool.execute_transaction(
                fake, self.inspection, sleep=lambda _: None, polls=2)
        self.assertEqual(fake.vram_writes, [])

    def test_hqd_read_and_final_default_failures_preserve_both(self):
        fake = FakeTransport(self.tool, self.inspection)
        fake.fail_hqd_read = True
        with self.assertRaises(self.tool.StartupRecoveryError) as raised:
            self.tool.execute_transaction(
                fake, self.inspection, sleep=lambda _: None, polls=2)
        scan = raised.exception.evidence['hqd_after_cp_halt']
        self.assertGreater(len(scan['rows']), 0)
        self.assertFalse(scan['final_default']['completed'])
        self.assertIn('HQD read failure', scan['primary_error'])
        self.assertEqual(fake.vram_writes, [])

    def test_final_scan_read_and_default_failures_preserve_both(self):
        fake = FakeTransport(self.tool, self.inspection)
        fake.fail_final_scan = True
        with self.assertRaises(self.tool.StartupRecoveryError) as raised:
            self.tool.execute_transaction(
                fake, self.inspection, sleep=lambda _: None, polls=2)
        scan = raised.exception.evidence['final_scan']
        self.assertGreater(len(scan['compute_passes'][0]), 0)
        self.assertFalse(scan['final_default']['completed'])
        self.assertIn('final selector failure', scan['final_default']['error'])
        self.assertEqual(fake.vram_writes, [])

    def test_guard_rejects_unlisted_writes_and_bar2_access(self):
        fake = FakeTransport(self.tool, self.inspection)
        guard = self.tool.TransactionTransport(fake)
        with self.assertRaisesRegex(self.tool.StartupRecoveryError, 'write is forbidden'):
            guard.write32(self.tool.RECOVERY.CP_HQD_ACTIVE_OFFSET, 0)
        with self.assertRaisesRegex(self.tool.StartupRecoveryError, 'BAR2'):
            guard.ring_doorbell64(0, 0)
        self.assertEqual(fake.writes, [])

    def test_attempt_is_create_once_before_explicit_transport_factory(self):
        with tempfile.TemporaryDirectory() as temp:
            vm = Path(temp)
            (vm / 'run').mkdir()
            opened = []
            preflight = {'inspection': self.inspection,
                         'inspection_bytes': self.inspection_bytes,
                         'inspection_sha256': self.tool.INSPECTION_SHA256,
                         'host_proof': self.inspection['postflight'],
                         'journal_cursor': 'cursor',
                         'archive_sha256': self.archive_sha,
                         'archive_files': self.archive_files,
                         'origin_archive_sha256': self.archive_sha,
                         'origin_archive_files': self.archive_files,
                         'source_hashes': self.tool.source_hashes()}
            with self.assertRaisesRegex(self.tool.StartupRecoveryError,
                                        'injected open failure'):
                self.tool.recover_once(
                    vm, Path(temp) / 'evidence', INSPECTION_PATH,
                    vm / 'run/startup-noqueue-results/result.json',
                    preflight_reader=lambda: preflight,
                    postflight_reader=lambda cursor: preflight,
                    transport_factory=lambda: opened.append(True) or
                        (_ for _ in ()).throw(OSError('injected open failure')))
            attempt = vm / 'run/startup-noqueue-attempts' / self.tool.BOOT_ID / \
                (self.tool.RUN_ID + '.json')
            self.assertTrue(attempt.exists())
            self.assertEqual(opened, [True])
            with self.assertRaisesRegex(self.tool.StartupRecoveryError,
                                        'attempt already exists'):
                self.tool.recover_once(
                    vm, Path(temp) / 'evidence', INSPECTION_PATH,
                    vm / 'run/startup-noqueue-results/second.json',
                    preflight_reader=lambda: preflight,
                    postflight_reader=lambda cursor: preflight,
                    transport_factory=lambda: self.fail('must not reopen'))

    def test_preflight_and_postflight_failures_are_durable_and_nonauthorizing(self):
        with tempfile.TemporaryDirectory() as temp:
            vm = Path(temp); (vm / 'run').mkdir()
            output = vm / 'run/startup-noqueue-results/preflight.json'
            with self.assertRaises(self.tool.StartupRecoveryError):
                self.tool.recover_once(
                    vm, ROOT, INSPECTION_PATH, output,
                    preflight_reader=lambda: (_ for _ in ()).throw(
                        OSError('collector failed')),
                    postflight_reader=lambda _: self.fail('no postflight'),
                    transport_factory=lambda: self.fail('no transport'))
            result = json.loads(output.read_text())
            self.assertEqual(result['status'], 'failed')
            self.assertFalse(result['authorizes_launch'])
            self.assertFalse((vm / 'run/startup-noqueue-attempts').exists())

        with tempfile.TemporaryDirectory() as temp:
            vm = Path(temp); (vm / 'run').mkdir()
            preflight = self.valid_preflight()
            output = vm / 'run/startup-noqueue-results/postflight.json'
            fake = FakeTransport(self.tool, self.inspection)
            with self.assertRaises(self.tool.StartupRecoveryError):
                self.tool.recover_once(
                    vm, ROOT, INSPECTION_PATH, output,
                    preflight_reader=lambda: preflight,
                    postflight_reader=lambda _: (_ for _ in ()).throw(
                        OSError('post collector failed')),
                    transport_factory=lambda: fake)
            result = json.loads(output.read_text())
            self.assertEqual(result['status'], 'failed')
            self.assertFalse(result['authorizes_launch'])
            self.assertIn('postflight collection', result['postflight_errors'])
            self.assertFalse((vm / 'run/startup-noqueue-recovery').exists())

    def valid_preflight(self):
        return {'inspection': self.inspection,
                'inspection_bytes': self.inspection_bytes,
                'inspection_sha256': self.tool.INSPECTION_SHA256,
                'host_proof': self.inspection['postflight'],
                'journal_cursor': 'cursor',
                'archive_sha256': self.archive_sha,
                'archive_files': dict(self.archive_files),
                'origin_archive_sha256': self.archive_sha,
                'origin_archive_files': dict(self.archive_files),
                'source_hashes': self.tool.source_hashes()}

    def test_schema4_receipt_validator_is_exact_and_binds_attempt(self):
        fake = FakeTransport(self.tool, self.inspection)
        transaction = self.tool.execute_transaction(
            fake, self.inspection, sleep=lambda _: None, polls=2)
        attempt = {
            'schema': 1, 'kind': 'startup-noqueue-attempt',
            'boot_id': self.tool.BOOT_ID, 'prior_run_id': self.tool.RUN_ID,
            'build_id': self.tool.BUILD_ID, 'attempt_id': 'a' * 32,
            'recovery_id': 'b' * 32,
            'inspection_sha256': self.tool.INSPECTION_SHA256,
            'ledger_sha256': self.tool.LEDGER_SHA256,
            'archive_sha256': self.tool.ARCHIVE_SHA256,
            'guest_source_commit': self.inspection['preflight']['manifest']['source_commit'],
            'guest_source_sha256': self.inspection['preflight']['manifest']['source_sha256'],
            'source_hashes': self.tool.source_hashes(),
            'created_epoch': 1.0,
        }
        attempt_raw = (json.dumps(attempt, indent=2, sort_keys=True) + '\n').encode()
        receipt = self.tool.build_receipt(
            transaction, attempt, hashlib.sha256(attempt_raw).hexdigest(),
            self.inspection['postflight'], self.inspection['postflight'])
        self.assertEqual(self.tool.validate_receipt(
            receipt, self.tool.BOOT_ID, self.tool.RUN_ID), [])
        for path, value in (
                (('schema',), 3),
                (('inspection_sha256',), '0' * 64),
                (('transaction', 'final_scan', 'globals_after', 'sdma0_f32_cntl'), 0),
                (('transaction', 'reservation', 'after_hex'), '01' + '00' * 71),
                (('transaction', 'commands', 0, 'response'), 0x80030001),
                (('transaction', 'writes', -1, 'completed'), False),
                (('transaction', 'final_scan', 'compute_passes', 1), []),
                (('source_hashes', 'experiment.py'), '0' * 64)):
            with self.subTest(path=path):
                changed = json.loads(json.dumps(receipt))
                target = changed
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
                self.assertIn('startup_noqueue_receipt',
                              self.tool.validate_receipt(
                                  changed, self.tool.BOOT_ID, self.tool.RUN_ID))

        changed = json.loads(json.dumps(receipt))
        changed['transaction']['writes'][0], changed['transaction']['writes'][1] = \
            changed['transaction']['writes'][1], changed['transaction']['writes'][0]
        self.assertIn('startup_noqueue_receipt', self.tool.validate_receipt(
            changed, self.tool.BOOT_ID, self.tool.RUN_ID))

        changed = json.loads(json.dumps(receipt))
        writes = changed['transaction']['writes']
        mutations = writes[135:137]
        del writes[135:137]
        writes[0:0] = mutations
        for sequence, row in enumerate(writes):
            row['sequence'] = sequence
        self.assertIn('startup_noqueue_receipt', self.tool.validate_receipt(
            changed, self.tool.BOOT_ID, self.tool.RUN_ID))
        self.assertIn('startup_noqueue_receipt', self.tool.validate_receipt(
            receipt, 'wrong-boot', self.tool.RUN_ID))

        with tempfile.TemporaryDirectory() as temp:
            vm = Path(temp)
            attempt_path = vm / 'run/startup-noqueue-attempts' / self.tool.BOOT_ID / \
                (self.tool.RUN_ID + '.json')
            attempt_path.parent.mkdir(parents=True)
            attempt_path.write_bytes(attempt_raw)
            ledger_path = vm / 'run/used-gpu-boots' / (self.tool.BOOT_ID + '.json')
            ledger_path.parent.mkdir(parents=True)
            ledger_path.write_bytes((ROOT / 'findings/recovery-tests/'
                                     'startup-noqueue-174/ledger.json').read_bytes())
            self.assertEqual(self.tool.validate_receipt(
                receipt, self.tool.BOOT_ID, self.tool.RUN_ID, vm=vm), [])
            attempt_path.write_text('{}')
            self.assertIn('startup_noqueue_receipt', self.tool.validate_receipt(
                receipt, self.tool.BOOT_ID, self.tool.RUN_ID, vm=vm))

    def test_receipt_construction_failure_after_transaction_is_durable(self):
        with tempfile.TemporaryDirectory() as temp:
            vm = Path(temp); (vm / 'run').mkdir()
            output = vm / 'run/startup-noqueue-results/receipt-failure.json'
            preflight = self.valid_preflight()
            fake = FakeTransport(self.tool, self.inspection)
            with patch.object(self.tool, 'build_receipt', side_effect=ValueError('bad receipt')):
                with self.assertRaises(self.tool.StartupRecoveryError):
                    self.tool.recover_once(
                        vm, ROOT, INSPECTION_PATH, output,
                        preflight_reader=lambda: preflight,
                        postflight_reader=lambda _: preflight,
                        transport_factory=lambda: fake)
            result = json.loads(output.read_text())
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(result['transaction']['status'], 'recovered')
            self.assertFalse(result['authorizes_launch'])
            self.assertIn('bad receipt', result['error'])
            self.assertFalse((vm / 'run/startup-noqueue-recovery').exists())

    def test_success_writes_exact_receipt_after_result_and_binds_ledger(self):
        with tempfile.TemporaryDirectory() as temp:
            vm = Path(temp); (vm / 'run').mkdir()
            ledger = vm / 'run/used-gpu-boots' / (self.tool.BOOT_ID + '.json')
            ledger.parent.mkdir(parents=True)
            ledger.write_bytes((ROOT / 'findings/recovery-tests/'
                                'startup-noqueue-174/ledger.json').read_bytes())
            output = vm / 'run/startup-noqueue-results/success.json'
            preflight = self.valid_preflight()
            receipt = self.tool.recover_once(
                vm, ROOT, INSPECTION_PATH, output,
                preflight_reader=lambda: preflight,
                postflight_reader=lambda _: preflight,
                transport_factory=lambda: FakeTransport(self.tool, self.inspection))
            receipt_path = (vm / 'run/startup-noqueue-recovery' / self.tool.BOOT_ID /
                            (self.tool.RUN_ID + '.json'))
            self.assertEqual(json.loads(receipt_path.read_text()), receipt)
            self.assertEqual(self.tool.validate_receipt(
                receipt, self.tool.BOOT_ID, self.tool.RUN_ID, vm=vm), [])
            result = json.loads(output.read_text())
            self.assertEqual(result['status'], 'recovered')
            self.assertFalse(result['authorizes_launch'])
            ledger.write_text('{}')
            self.assertIn('startup_noqueue_receipt', self.tool.validate_receipt(
                receipt, self.tool.BOOT_ID, self.tool.RUN_ID, vm=vm))

    def test_canonical_archive_digest_detects_any_origin_or_archive_change(self):
        self.assertEqual(self.archive_sha, self.tool.ARCHIVE_SHA256)
        proof = {'inspection': self.inspection,
                 'inspection_bytes': self.inspection_bytes,
                 'inspection_sha256': self.tool.INSPECTION_SHA256,
                 'host_proof': self.inspection['postflight'],
                 'journal_cursor': 'cursor',
                 'archive_sha256': self.archive_sha,
                 'archive_files': dict(self.archive_files),
                 'origin_archive_sha256': self.archive_sha,
                 'origin_archive_files': dict(self.archive_files),
                 'source_hashes': self.tool.source_hashes()}
        self.assertEqual(self.tool._preflight_errors(proof), [])
        proof['archive_files']['serial.txt'] = '0' * 64
        self.assertIn('archive digest', self.tool._preflight_errors(proof))


if __name__ == '__main__':
    unittest.main()
