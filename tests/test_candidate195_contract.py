import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class Candidate195ContractTests(unittest.TestCase):
    def test_card_exists_and_is_headless_allocator_diagnostic(self):
        card = json.loads((ROOT / 'experiments/metal-029.json').read_text())
        self.assertEqual(card['id'], 'metal-029')
        self.assertEqual(card['candidate_version'], '1.0.195')
        self.assertEqual(card['critical_replay_schema'], 2)
        self.assertEqual(card['recovery_lease_schema'], 3)
        self.assertEqual(card['max_seconds'], 180)
        self.assertTrue(card['run_probe_only_after_native_start'])
        self.assertEqual(card['launch_options']['GENERIC_GRAPHICS'], 'off')
        self.assertIn('submission_backing_allocation', card['required_observations'])
        self.assertIn('submission_map_phase', card['required_observations'])
        self.assertIn('terminal_kiq_submit_failure', card['abort_on'])

    def test_stage_tool_declares_candidate195_contract(self):
        source = (ROOT / 'tools/stage-candidate.py').read_text()
        self.assertIn('(\"1.0.195\", \"metal-029\")', source)
        self.assertIn('candidate-195', source)


if __name__ == '__main__':
    unittest.main()
