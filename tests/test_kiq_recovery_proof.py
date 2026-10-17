import copy
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/stopped-wptr-clear-schema6-positive.json'


class KiqRecoveryProofTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            'kiq_recovery_proof', ROOT / 'tools/kiq-recovery-proof.py')
        cls.tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.tool)

    def receipt(self):
        return json.loads(FIXTURE.read_bytes())

    def rejected(self, mutate):
        receipt = self.receipt()
        mutate(receipt)
        derived, errors = self.tool.derive_effective_host_kiq(receipt)
        self.assertIsNone(derived)
        self.assertTrue(errors)

    @staticmethod
    def mutate_passes(receipt, phases, mutate):
        proof = receipt['gc_quiesce']['stopped_wptr_doorbell_clear']
        for phase in phases:
            for observed in proof[phase]['passes']:
                mutate(observed)

    def test_derives_complete_effective_host_kiq_without_mutating_raw_failure(self):
        receipt = self.receipt()
        original = copy.deepcopy(receipt)

        derived, errors = self.tool.derive_effective_host_kiq(receipt)

        self.assertEqual(errors, [])
        self.assertEqual(receipt, original)
        self.assertEqual(derived['source'], 'stopped_wptr_doorbell_clear')
        host = derived['host_kiq']
        self.assertEqual(host['status'], 'retired')
        self.assertEqual(host['packet_dwords'], 0x100)
        self.assertEqual(host['rptr_after'], 0x100)
        self.assertEqual(host['fence_sequence'], 123)
        self.assertEqual(host['fence_after'], 123)
        self.assertEqual(host['gfx_active_before_scrub'], 0)
        self.assertIs(host['cleanup_confirmed'], True)
        self.assertEqual(host['cleanup'], {
            'mec_cntl':0x50000000, 'hqd_active':0,
            'hqd_doorbell':0x80000000, 'hqd_rptr':0,
            'hqd_wptr_lo':0, 'hqd_wptr_hi':0, 'pq_status':1,
            'doorbell_range_lower':0, 'doorbell_range_upper':0,
            'wptr_poll_cntl':0,
        })
        self.assertEqual(host['final_gate'], {
            key: receipt['gc_quiesce'][key] for key in (
                'active_after', 'cp_stat_after', 'cp_cpc_busy_after',
                'pq_wptr_poll_after', 'pq_status_after',
                'doorbell_range_lower_after', 'doorbell_range_upper_after',
                'gfx_ring_clean', 'gfx_retirement_confirmed',
                'graphics_pipe_proof_complete')
        })
        self.assertEqual(receipt['gc_quiesce']['host_kiq']['status'], 'failed')

    def test_eligibility_claim_is_ignored_but_raw_status_is_checked(self):
        receipt = self.receipt()
        receipt['gc_quiesce']['stopped_wptr_doorbell_clear']['eligibility'] = {
            'eligible':False, 'errors':['untrusted producer claim']}
        derived, errors = self.tool.derive_effective_host_kiq(receipt)
        self.assertEqual(errors, [])
        self.assertIsNotNone(derived)

        self.rejected(lambda value: value['gc_quiesce'][
            'stopped_wptr_doorbell_clear'].update(status='claimed-only'))

    def test_hdp_posting_read_may_self_clear_but_must_be_accessible(self):
        receipt = self.receipt()
        invalidate = receipt['gc_quiesce']['host_kiq']['evidence'][
            'hdp_read_invalidate']
        invalidate['last']['posted_read'] = 0
        derived, errors = self.tool.derive_effective_host_kiq(receipt)
        self.assertEqual(errors, [])
        self.assertIsNotNone(derived)

        self.rejected(lambda value: value['gc_quiesce']['host_kiq']['evidence'][
            'hdp_read_invalidate']['last'].update(posted_read=0xffffffff))
        self.rejected(lambda value: value['gc_quiesce']['host_kiq']['evidence'][
            'hdp_read_invalidate'].update(count=2))

    def test_activation_accepts_accessible_status_with_active_bit_set(self):
        receipt = self.receipt()
        receipt['gc_quiesce']['host_kiq']['evidence'][
            'activation_readback'] = 3
        derived, errors = self.tool.derive_effective_host_kiq(receipt)
        self.assertEqual(errors, [])
        self.assertIsNotNone(derived)

    def test_rejects_legacy_or_incomplete_host_kiq_evidence(self):
        self.rejected(lambda value: value['gc_quiesce']['host_kiq'].pop('evidence'))
        self.rejected(lambda value: value['gc_quiesce']['host_kiq']['evidence'].pop(
            'retired_before_cleanup'))
        self.rejected(lambda value: value.update(schema=5))
        self.rejected(lambda value: value.update(gc_quiesce=[]))
        self.rejected(lambda value: value['gc_quiesce'].update(host_kiq=[]))
        self.rejected(lambda value: value['gc_quiesce']['host_kiq']['evidence'].update(
            packet=[]))

    def test_schema2_stopped_wptr_is_explicitly_unsupported(self):
        receipt = self.receipt()
        reservation = {'schema':2}
        gc = receipt['gc_quiesce']
        evidence = gc['host_kiq']['evidence']
        gc['reservation'] = copy.deepcopy(reservation)
        evidence['reservation'] = copy.deepcopy(reservation)
        evidence['retired_before_cleanup']['reservation'] = copy.deepcopy(reservation)

        derived, errors = self.tool.derive_effective_host_kiq(receipt)

        self.assertIsNone(derived)
        self.assertEqual(errors, ['unsupported_v2_stopped_wptr'])

    def test_requires_executed_unmap_fence_and_genuine_dequeue(self):
        mutations = [
            lambda v: v['gc_quiesce'].update(forced_inactive=1),
            lambda v: v['gc_quiesce']['host_kiq'].update(status='retired'),
            lambda v: v['gc_quiesce']['host_kiq'].update(error='different failure'),
            lambda v: v['gc_quiesce']['host_kiq']['evidence'].update(
                activation_readback=0),
            lambda v: v['gc_quiesce']['host_kiq']['evidence'].update(
                activation_readback=0xffffffff),
            lambda v: v['gc_quiesce']['host_kiq']['evidence']['dequeue'].update(
                write_value=0),
            lambda v: v['gc_quiesce']['host_kiq']['evidence']['dequeue'].update(
                active_samples=[1]),
            lambda v: v['gc_quiesce']['host_kiq']['evidence']['dequeue'].update(
                active_samples=[0xffffffff]),
            lambda v: v['gc_quiesce']['host_kiq']['evidence']['dequeue'].update(
                observed_inactive=False),
            lambda v: v['gc_quiesce']['host_kiq']['evidence']['packet'][
                'unmap'].__setitem__(0, 0),
            lambda v: v['gc_quiesce']['host_kiq']['evidence'][
                'terminal_poll'].update(fence=0),
            lambda v: v['gc_quiesce']['host_kiq']['evidence'][
                'terminal_poll'].update(report=0xffffffff),
            lambda v: v['gc_quiesce']['host_kiq']['evidence'][
                'terminal_poll'].update(rptr=0, report=0),
            lambda v: v['gc_quiesce']['host_kiq']['evidence'][
                'retired_before_cleanup'].update(fence_after=124),
            lambda v: v['gc_quiesce']['host_kiq']['evidence'][
                'retired_before_cleanup'].update(gfx_active_after_unmap=1),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                self.rejected(mutate)

    def test_requires_sole_original_cleanup_failure_to_be_wptr_clear(self):
        evidence = lambda value: value['gc_quiesce']['host_kiq']['evidence']
        self.rejected(lambda value: evidence(value)['cleanup']['errors'].append(
            'another cleanup failure'))
        self.rejected(lambda value: evidence(value)['cleanup']['errors'].__setitem__(
            0, 'verify host KIQ rptr clear: RecoveryError'))
        self.rejected(lambda value: evidence(value)['cleanup']['readbacks'].update(
            hqd_wptr_lo=0))
        self.rejected(lambda value: evidence(value)['cleanup']['readbacks'].update(
            hqd_wptr_hi=0))
        self.rejected(lambda value: evidence(value)['cleanup']['readbacks'].update(
            hqd_active=1))
        self.rejected(lambda value: evidence(value)['cleanup']['readbacks'].update(
            hqd_active=False))
        self.rejected(lambda value: evidence(value)['cleanup']['readbacks'].update(
            mec_cntl=0xffffffff))
        self.rejected(lambda value: evidence(value)['cleanup']['readbacks'].update(
            pq_status=3))

    def test_requires_two_stable_exact_stopped_scans(self):
        proof = lambda value: value['gc_quiesce']['stopped_wptr_doorbell_clear']
        mutations = [
            lambda v: proof(v)['before']['passes'].pop(),
            lambda v: proof(v)['before']['passes'][1]['globals'].update(cp_stat=1),
            lambda v: self.mutate_passes(
                v, ('before','after'),
                lambda row: row['compute'][0].update(active=1)),
            lambda v: self.mutate_passes(
                v, ('before','after'),
                lambda row: row['compute'][0].update(
                    doorbell_control=0x40000000)),
            lambda v: self.mutate_passes(
                v, ('before','after'),
                lambda row: row['globals'].update(mec_cntl=0)),
            lambda v: self.mutate_passes(
                v, ('before','after'),
                lambda row: row['globals'].update(sdma0_f32_cntl=0)),
            lambda v: self.mutate_passes(
                v, ('before','after'),
                lambda row: row['globals'].update(sdma0_status=0)),
            lambda v: self.mutate_passes(
                v, ('before','after'),
                lambda row: row['globals'].update(sdma0_page_ib_cntl=0x101)),
            lambda v: self.mutate_passes(
                v, ('before','after'),
                lambda row: row['globals'].update(cp_stat=0xffffffff)),
            lambda v: self.mutate_passes(
                v, ('before',), lambda row: row['host_kiq'].update(wptr_lo=0)),
            lambda v: self.mutate_passes(
                v, ('after',), lambda row: row['host_kiq'].update(wptr_lo=1)),
            lambda v: self.mutate_passes(
                v, ('before','after'),
                lambda row: row['globals'].update(sdma0_cntl=0x00040000)),
            lambda v: self.mutate_passes(
                v, ('before','after'),
                lambda row: row['compute'][0].update(selector=9)),
            lambda v: proof(v)['before']['selector_writes'].pop(),
            lambda v: proof(v)['after'].update(final_default={}),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                self.rejected(mutate)

    def test_allows_only_target_pointer_hit_and_updated_status_changes(self):
        proof = lambda value: value['gc_quiesce']['stopped_wptr_doorbell_clear']
        self.rejected(lambda value: self.mutate_passes(
            value, ('after',), lambda row: row['globals'].update(sdma0_status=3)))
        self.rejected(lambda value: self.mutate_passes(
            value, ('after',),
            lambda row: row['compute'][0].update(doorbell_control=0x80000000)))
        self.rejected(lambda value: self.mutate_passes(
            value, ('after',), lambda row: row['host_kiq'].update(rptr=1)))
        self.rejected(lambda value: self.mutate_passes(
            value, ('after',), lambda row: row['globals'].update(pq_status=4)))

    def test_rejects_consistent_unsupported_target_and_global_status_bits(self):
        self.rejected(lambda value: self.mutate_passes(
            value, ('before','after'),
            lambda row: row['globals'].update(pq_status=4)))

        def set_target_mode(row):
            next(item for item in row['compute']
                 if item['selector'] == self.tool.HOST_KIQ_SELECTOR)[
                     'doorbell_control'] = 1

        self.rejected(lambda value: self.mutate_passes(
            value, ('before','after'), set_target_mode))

    def test_binds_enable_prereads_to_the_stable_before_scan(self):
        self.rejected(lambda value: self.mutate_passes(
            value, ('before',),
            lambda row: row['globals'].update(pq_status=0)))

        def clear_target_hit(row):
            next(item for item in row['compute']
                 if item['selector'] == self.tool.HOST_KIQ_SELECTOR)[
                     'doorbell_control'] = 0

        self.rejected(lambda value: self.mutate_passes(
            value, ('before',), clear_target_hit))

    def test_requires_exact_ordered_native64_transition_and_closure(self):
        proof = lambda value: value['gc_quiesce']['stopped_wptr_doorbell_clear']
        transition = lambda value: proof(value)['transition']
        mutations = [
            lambda v: transition(v)['selectors'].reverse(),
            lambda v: transition(v)['hqd_enable'].update(offset=0),
            lambda v: transition(v)['hqd_enable'].update(readback=0x80000000),
            lambda v: transition(v)['global_enable'].update(written=1),
            lambda v: transition(v)['doorbell'].update(index=1),
            lambda v: transition(v)['doorbell'].update(width_bits=32),
            lambda v: transition(v)['doorbell'].update(value=1),
            lambda v: transition(v).update(interim_samples=[]),
            lambda v: transition(v)['interim_samples'][0].update(active=1),
            lambda v: transition(v)['gate_close']['global'].update(readback=3),
            lambda v: transition(v)['gate_close']['hqd'].update(readback=0xc0000000),
            lambda v: transition(v)['gate_close']['global'].update(witness_sequence=5),
            lambda v: transition(v)['gate_close']['global'].update(completed=False),
            lambda v: transition(v)['gate_close']['hqd'].update(attempted=False),
            lambda v: transition(v)['global_enable'].update(observed_before=False),
            lambda v: transition(v)['hqd_enable'].update(readback=0xffffffff),
            lambda v: transition(v)['timing'].update(through_global_close_ns=2000101),
            lambda v: transition(v).update(final_default={}),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                self.rejected(mutate)

    def test_interim_samples_allow_only_old_or_cleared_pointer_values(self):
        receipt = self.receipt()
        samples = receipt['gc_quiesce']['stopped_wptr_doorbell_clear'][
            'transition']['interim_samples']
        samples.insert(0, {'active':0, 'mec_cntl':0x50000000,
                           'wptr_lo':0x100, 'wptr_hi':0})
        derived, errors = self.tool.derive_effective_host_kiq(receipt)
        self.assertEqual(errors, [])
        self.assertIsNotNone(derived)

        self.rejected(lambda value: value['gc_quiesce'][
            'stopped_wptr_doorbell_clear']['transition'][
                'interim_samples'][0].update(wptr_lo=1))
        self.rejected(lambda value: value['gc_quiesce'][
            'stopped_wptr_doorbell_clear']['transition'][
                'interim_samples'][0].update(wptr_hi=1))

    def test_close_readbacks_allow_only_independent_status_bit_changes(self):
        receipt = self.receipt()
        close = receipt['gc_quiesce']['stopped_wptr_doorbell_clear'][
            'transition']['gate_close']
        close['global']['readback'] = 0
        close['hqd']['readback'] = 0
        derived, errors = self.tool.derive_effective_host_kiq(receipt)
        self.assertEqual(errors, [])
        self.assertIsNotNone(derived)

        self.rejected(lambda value: value['gc_quiesce'][
            'stopped_wptr_doorbell_clear']['transition']['gate_close'][
                'global'].update(readback=2))
        self.rejected(lambda value: value['gc_quiesce'][
            'stopped_wptr_doorbell_clear']['transition']['gate_close'][
                'hqd'].update(readback=0x40000000))

    def test_parent_identity_and_effective_view_inputs_must_match_raw_retirement(self):
        self.rejected(lambda value: value['gc_quiesce']['reservation'].update(
            checksum=0))
        self.rejected(lambda value: value['gc_quiesce'].update(
            gfx_retirement_confirmed=False))
        self.rejected(lambda value: value['gc_quiesce'][
            'graphics_pipes_after_retirement']['pipes'][0].update(active=1))
        self.rejected(lambda value: value['gc_quiesce']['host_kiq']['evidence'][
            'addresses'].update(fence=0))


if __name__ == '__main__':
    unittest.main()
