import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / 'tools/functional-regression.py'


class FunctionalRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('functional_regression', TOOL)
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def test_preserved_171_to_178_stage_regression_is_reported_separately(self):
        baseline = self.module.analyze_run(
            ROOT / 'findings/experiments/metal-005-171')
        current = self.module.analyze_run(
            ROOT / 'findings/experiments/metal-011-178-a')
        comparison = self.module.compare_runs(baseline, current)
        repeated = self.module.analyze_run(
            ROOT / 'findings/experiments/metal-011-178-b')

        self.assertEqual(baseline['stages']['native_engine_start']['state'],
                         'observed')
        self.assertEqual(current['stages']['native_engine_start']['state'],
                         'observed')
        self.assertEqual(baseline['stages']['client_channel_activity']['state'],
                         'observed')
        self.assertEqual(current['stages']['client_channel_activity']['state'],
                         'not_observed')
        self.assertEqual(baseline['stages']['submission_entry']['state'], 'unknown')
        self.assertEqual(current['stages']['submission_entry']['state'],
                         'not_observed')
        self.assertEqual(current['stages']['compute_acceptance']['state'],
                         'not_observed')
        self.assertEqual(current['stages']['render_acceptance']['state'],
                         'not_observed')
        self.assertEqual(baseline['stages']['cleanup']['state'], 'observed')
        self.assertEqual(current['stages']['cleanup']['state'], 'observed')
        self.assertEqual(comparison['lost_stages'], ['client_channel_activity'])
        self.assertEqual(
            self.module.compare_runs(current, repeated)['lost_stages'], [])
        self.assertEqual(
            self.module.compare_runs(baseline, repeated)['lost_stages'],
            ['client_channel_activity'])
        self.assertEqual(baseline['native_allocator_error_line_count'], 14)
        self.assertEqual(current['native_allocator_error_line_count'], 0)
        self.assertTrue(baseline['raw_verdict']['sha256'])
        self.assertTrue(current['raw_verdict']['sha256'])

    def test_absence_without_stage_specific_capture_is_unknown_not_regression(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            (run / 'manifest.json').write_text(json.dumps({
                'build_id':'abc', 'spec':{'required_observations':['engine_start']}}))
            (run / 'events.jsonl').write_text(
                json.dumps({'kind':'build', 'build':'abc', 'seq':0}) + '\n' +
                json.dumps({'kind':'route', 'build':'abc', 'seq':1, 'ok':True}) + '\n' +
                json.dumps({'kind':'engine_start', 'build':'abc', 'seq':2,
                            'result':1}) + '\n')
            (run / 'verdict.json').write_text(json.dumps({'verdict':'PROBE_NOT_RUN'}))
            (run / 'serial.txt').write_text('')
            analyzed = self.module.analyze_run(run)
            self.assertEqual(analyzed['stages']['client_channel_activity']['state'],
                             'unknown')
            self.assertEqual(analyzed['stages']['submission_entry']['state'],
                             'unknown')
            comparison = self.module.compare_runs(
                {'run': 'prior', 'stages': {
                    'client_channel_activity': {'state':'observed'}}}, analyzed)
            self.assertEqual(comparison['lost_stages'], [])

    def test_capture_loss_makes_negative_stage_evidence_unknown(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            (run / 'manifest.json').write_text(json.dumps({
                'build_id':'abc', 'spec':{'required_observations':[
                    'submission_trace', 'sdma_vm_program']}}))
            rows = [
                {'kind':'build', 'build':'abc', 'seq':0},
                {'kind':'route', 'build':'abc', 'seq':1, 'ok':True},
                {'kind':'submission_trace_route', 'build':'abc', 'seq':2,
                 'ok':True, 'count':6},
                {'kind':'submission_trace_summary', 'build':'abc', 'seq':3,
                 'ok':True, 'counts':[[0, 0, 0]] * 5, 'dropped':[0, 0]},
                {'kind':'vm_program_route', 'build':'abc', 'seq':4, 'ok':True},
                {'kind':'capture_loss', 'build':'abc', 'reason':'overflow'},
            ]
            (run / 'events.jsonl').write_text(
                ''.join(json.dumps(row) + '\n' for row in rows))
            (run / 'verdict.json').write_text(json.dumps({'verdict':'INCONCLUSIVE'}))
            (run / 'serial.txt').write_text('')
            analyzed = self.module.analyze_run(run)
            self.assertEqual(analyzed['stages']['client_channel_activity']['state'],
                             'unknown')
            self.assertEqual(analyzed['stages']['submission_entry']['state'],
                             'unknown')

    def test_mismatched_build_probe_and_recovery_cannot_supply_stage_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            (run / 'manifest.json').write_text(json.dumps({
                'run_id':'wanted', 'build_id':'abc',
                'spec':{'required_observations':['engine_start']}}))
            (run / 'events.jsonl').write_text(
                json.dumps({'kind':'build', 'build':'other', 'seq':0}) + '\n' +
                json.dumps({'kind':'engine_start', 'build':'other', 'seq':1,
                            'result':1}) + '\n')
            result = {'passed':True, 'run_id':'other',
                      'completed_command_buffers':2, 'compute_rounds':1,
                      'compute_values_checked':10, 'render_pixels_checked':10}
            (run / 'probe.json').write_text(json.dumps({
                'run_id':'other',
                'output':'RGPU_METAL_RESULT ' + json.dumps(result) + '\n'}))
            (run / 'recovery.json').write_text(json.dumps({
                'status':'recovered', 'authorizes_launch':True,
                'prior_run_id':'other'}))
            (run / 'verdict.json').write_text(json.dumps({'verdict':'PASS'}))
            (run / 'serial.txt').write_text('')
            analyzed = self.module.analyze_run(run)
            self.assertEqual(analyzed['stages']['native_engine_start']['state'],
                             'unknown')
            self.assertEqual(analyzed['stages']['compute_acceptance']['state'],
                             'unknown')
            self.assertEqual(analyzed['stages']['render_acceptance']['state'],
                             'unknown')
            self.assertEqual(analyzed['stages']['cleanup']['state'], 'unknown')

    def test_partial_failed_probe_counters_do_not_claim_acceptance(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            run_id = '1' * 32
            (run / 'manifest.json').write_text(json.dumps({
                'run_id':run_id, 'build_id':'abc',
                'probe_source_sha256':
                    'f0fc0ced81fe70732c3491cff1557a83d85c9ccb8c18a6303f9070ae1f969d77',
                'probe_binary_sha256':
                    '1637e4b31bca0a1bdc400f96e34b344a823de1b408a8d1677d6bcca475c8c787',
                'spec':{'required_observations':[]}}))
            (run / 'events.jsonl').write_text(
                json.dumps({'kind':'build', 'build':'abc', 'seq':0}) + '\n')
            result = {
                'passed':False, 'run_id':run_id, 'device':'AMD Radeon Navi23',
                'registry_id':1, 'metal3':True, 'completed_command_buffers':2,
                'compute_rounds':1, 'compute_values_checked':65536,
                'render_pixels_checked':True, 'error':'compute mismatch',
            }
            (run / 'probe.json').write_text(json.dumps({
                'run_id':run_id, 'transport_exit':0,
                'output':('RGPU_METAL_RESULT ' + json.dumps(result) + '\n' +
                          f'RGPU_EXIT {run_id} 1\n')}))
            analyzed = self.module.analyze_run(run)
            self.assertEqual(analyzed['stages']['compute_acceptance']['state'],
                             'not_observed')
            self.assertEqual(analyzed['stages']['render_acceptance']['state'],
                             'not_observed')

    def test_probe_stages_require_driver_and_probe_artifact_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            run_id = '2' * 32
            manifest = {
                'run_id':run_id, 'build_id':'abc',
                'probe_source_sha256':'0' * 64,
                'probe_binary_sha256':
                    '1637e4b31bca0a1bdc400f96e34b344a823de1b408a8d1677d6bcca475c8c787',
                'spec':{'required_observations':[]},
            }
            (run / 'manifest.json').write_text(json.dumps(manifest))
            (run / 'events.jsonl').write_text(
                json.dumps({'kind':'build', 'build':'other', 'seq':0}) + '\n')
            result = {
                'passed':True, 'run_id':run_id, 'device':'AMD Radeon Navi23',
                'registry_id':1, 'metal3':True, 'completed_command_buffers':4,
                'compute_rounds':3, 'compute_values_checked':196608,
                'render_pixels_checked':4096,
            }
            (run / 'probe.json').write_text(json.dumps({
                'run_id':run_id, 'transport_exit':0,
                'output':('RGPU_METAL_RESULT ' + json.dumps(result) + '\n' +
                          f'RGPU_EXIT {run_id} 0\n')}))

            analyzed = self.module.analyze_run(run)
            self.assertEqual(analyzed['stages']['compute_acceptance']['state'], 'unknown')
            self.assertEqual(analyzed['stages']['render_acceptance']['state'], 'unknown')

            (run / 'events.jsonl').write_text(
                json.dumps({'kind':'build', 'build':'abc', 'seq':0}) + '\n')
            analyzed = self.module.analyze_run(run)
            self.assertEqual(analyzed['stages']['compute_acceptance']['state'], 'unknown')
            self.assertEqual(analyzed['stages']['render_acceptance']['state'], 'unknown')

    def test_startup_only_zero_summary_is_not_negative_submission_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            run_id = '3' * 32
            (run / 'manifest.json').write_text(json.dumps({
                'run_id':run_id, 'build_id':'abc',
                'probe_source_sha256':
                    'f0fc0ced81fe70732c3491cff1557a83d85c9ccb8c18a6303f9070ae1f969d77',
                'probe_binary_sha256':
                    '1637e4b31bca0a1bdc400f96e34b344a823de1b408a8d1677d6bcca475c8c787',
                'spec':{'required_observations':['submission_trace']}}))
            rows = [
                {'kind':'build', 'build':'abc', 'seq':0},
                {'kind':'submission_trace_route', 'build':'abc', 'seq':1,
                 'ok':True, 'count':6},
                {'kind':'submission_trace_summary', 'build':'abc', 'seq':2,
                 'ok':True, 'counts':[[0, 0, 0]] * 5, 'dropped':[0, 0]},
            ]
            (run / 'events.jsonl').write_text(
                ''.join(json.dumps(row) + '\n' for row in rows))
            result = {
                'passed':False, 'run_id':run_id, 'device':'AMD Radeon Navi23',
                'registry_id':1, 'metal3':True, 'completed_command_buffers':0,
                'compute_rounds':0, 'compute_values_checked':0,
                'render_pixels_checked':0, 'error':'command failed',
            }
            (run / 'probe.json').write_text(json.dumps({
                'run_id':run_id, 'transport_exit':0,
                'output':('RGPU_METAL_RESULT ' + json.dumps(result) + '\n' +
                          f'RGPU_EXIT {run_id} 1\n')}))
            analyzed = self.module.analyze_run(run)
            self.assertEqual(analyzed['stages']['submission_entry']['state'], 'unknown')


if __name__ == '__main__':
    unittest.main()
