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

    def test_bundle_and_release_metadata_are_exact_candidate_version(self):
        info = plistlib.loads((ROOT / 'kext/Info.plist').read_bytes())
        self.assertEqual(info['CFBundleShortVersionString'], '1.0.180')
        self.assertEqual(info['CFBundleVersion'], '1.0.180')
        notes = (ROOT / 'docs/release-notes.md').read_text()
        self.assertTrue(notes.startswith('Experimental RaphaelGPU 1.0.180 '))


if __name__ == '__main__':
    unittest.main()
