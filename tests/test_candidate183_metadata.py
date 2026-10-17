import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class Candidate183MetadataTests(unittest.TestCase):
    def test_candidate183_is_the_bounded_real_entry_source_card(self):
        card = json.loads((ROOT / 'experiments/metal-016.json').read_text())
        self.assertEqual(card['id'], 'metal-016')
        self.assertEqual(card['candidate_version'], '1.0.183')
        self.assertEqual(card['critical_replay_schema'], 2)
        self.assertEqual(card['recovery_lease_schema'], 3)
        self.assertEqual(card['functional_boot_arguments'], {'rgpuvmroot': '4'})
        self.assertEqual(card['max_seconds'], 180)
        self.assertEqual(card['guest_picker_timeout_seconds'], 5)
        self.assertTrue(card['run_probe_only_after_native_start'])
        self.assertEqual(card['critical_replay_tolerance'], 'terminal-prefix')
        self.assertEqual(card['recovery_critical_replay_tolerance'],
                         'terminal-prefix-open')
        self.assertIn('real_entry_update_source_operand_offline_validated',
                      card['prerequisites'])
        self.assertIn('vmm_readiness', card['required_observations'])
        self.assertIn('vmid2_entry_gate', card['required_observations'])
        self.assertIn('vmid2_entry_update', card['required_observations'])
        self.assertNotIn('vmid2_entry_conversion', card['required_observations'])
        self.assertNotIn('vmid2_walk_hardware', card['required_observations'])
        self.assertIn('updateContiguousPTEsWithDMAUsingAddr', card['behavior_change'])
        self.assertIn('source operand', card['behavior_change'])
        self.assertIn('preserve destination, template, count, and increment',
                      card['behavior_change'])
        rejected = ('native-only zero-template VMM initialization chain',
                    'remove the obsolete forced early allocator template',
                    'prepared-phase BAR walk')
        rendered = json.dumps(card)
        for phrase in rejected:
            self.assertNotIn(phrase, rendered)
        self.assertIn('current boot ledger has one of three launches consumed',
                      card['repeat_policy'])
        self.assertIn('13c92dcc904742ce8fd4de28a3fb1988',
                      card['repeat_policy'])
        self.assertIn('no budget extension', card['repeat_policy'])
        self.assertIn('no automatic retry', card['repeat_policy'])

    def test_candidate183_compares_the_three_requested_baselines(self):
        card = json.loads((ROOT / 'experiments/metal-016.json').read_text())
        self.assertEqual(card['regression_baselines'], {
            'immediate': 'run/metal-015-182',
            'previous': 'run/metal-014-181',
            'furthest_reached': 'findings/experiments/metal-005-171',
        })

    def test_candidate183_docs_describe_source_operand_without_allocator_claims(self):
        release = (ROOT / 'findings/research/release-notes-1.0.181-183.md').read_text()
        first_candidate = release.split('Experimental RaphaelGPU 1.0.182', 1)[0]
        self.assertIn('updateContiguousPTEsWithDMAUsingAddr', first_candidate)
        self.assertIn('real source operand', first_candidate)
        self.assertNotIn('native-only zero-template VMM initialization chain',
                         first_candidate)
        notes = (ROOT / 'findings/experiments/metal-014-181/notes.md').read_text()
        superseding = notes.split('## Superseding interpretation', 1)[1]
        self.assertIn('separate real address', superseding)
        self.assertIn('updateContiguousPTEsWithDMAUsingAddr', superseding)
        self.assertNotIn('requires the native VMM readiness, allocator state',
                         superseding)
