import json
import plistlib
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class Candidate180MetadataTests(unittest.TestCase):
    def test_card_selects_bounded_cr2_schema3_run(self):
        card = json.loads((ROOT / 'experiments/metal-013.json').read_text())
        self.assertEqual(card['id'], 'metal-013')
        self.assertEqual(card['candidate_version'], '1.0.180')
        self.assertEqual(card['critical_replay_schema'], 2)
        self.assertEqual(card['recovery_lease_schema'], 3)
        self.assertEqual(card['max_seconds'], 180)
        self.assertTrue(card['run_probe_only_after_native_start'])
        self.assertIn('vmid2_root_repair', card['required_observations'])
        self.assertIn('recovery_lifetime_invalid', card['abort_on'])
        self.assertIn('no automatic retry', card['repeat_policy'])

    def test_candidate181_card_extends_root_repair_to_entry_conversion(self):
        previous = json.loads((ROOT / 'experiments/metal-013.json').read_text())
        card = json.loads((ROOT / 'experiments/metal-014.json').read_text())
        self.assertEqual(card['id'], 'metal-014')
        self.assertEqual(card['candidate_version'], '1.0.181')
        self.assertEqual(card['critical_replay_schema'], 2)
        self.assertEqual(card['recovery_lease_schema'], 3)
        self.assertEqual(card['critical_replay_tolerance'], 'terminal-prefix')
        self.assertEqual(card['functional_boot_arguments'], {'rgpuvmroot': '3'})
        self.assertEqual(card['requested_diagnostic'], previous['requested_diagnostic'])
        self.assertEqual(card['max_seconds'], previous['max_seconds'])
        self.assertTrue(card['run_probe_only_after_native_start'])
        self.assertEqual(set(card['required_observations']) - {'vmid2_entry_conversion'},
                         set(previous['required_observations']))
        self.assertIn('vmid2_entry_conversion_route_failure', card['abort_on'])
        self.assertIn('no automatic retry', card['repeat_policy'])
        self.assertEqual(card['regression_baselines']['immediate'], 'run/metal-013-180')

    def test_bundle_and_release_metadata_are_exact_candidate_version(self):
        info = plistlib.loads((ROOT / 'kext/Info.plist').read_bytes())
        self.assertEqual(info['CFBundleShortVersionString'], '1.0.183')
        self.assertEqual(info['CFBundleVersion'], '1.0.183')
        notes = (ROOT / 'docs/release-notes.md').read_text()
        self.assertTrue(notes.startswith('Experimental RaphaelGPU 1.0.183 '))

    def test_candidate182_card_keeps_conversion_and_adds_early_gate(self):
        previous = json.loads((ROOT / 'experiments/metal-014.json').read_text())
        card = json.loads((ROOT / 'experiments/metal-015.json').read_text())
        self.assertEqual(card['id'], 'metal-015')
        self.assertEqual(card['candidate_version'], '1.0.182')
        self.assertEqual(card['functional_boot_arguments'], previous['functional_boot_arguments'])
        self.assertEqual(card['critical_replay_tolerance'], 'terminal-prefix')
        self.assertEqual(card['recovery_critical_replay_tolerance'],
                         'terminal-prefix-open')
        self.assertEqual(set(card['required_observations']) -
                         set(previous['required_observations']),
                         {'vmid2_entry_gate', 'vmid2_walk_hardware'})
        self.assertFalse(any('candidate180' in item
                             for item in card['prerequisites']))
        self.assertIn('candidate182_source_and_artifact_identity_reviewed',
                      card['prerequisites'])
        self.assertIn('AMDHWVMM::init', card['behavior_change'])
        self.assertEqual(card['regression_baselines']['immediate'], 'run/metal-014-181')


if __name__ == '__main__':
    unittest.main()
