from pathlib import Path
import json
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SubmissionTraceSourceTests(unittest.TestCase):
    def test_inactive_backing_wrapper_forwards_before_snapshot_reads(self):
        source = (ROOT / 'src/RaphaelGPU.cpp').read_text()
        start = source.index('static bool wrapBackingAllocPhysical')
        end = source.index('static void wrapSubmitBuffer', start)
        body = source[start:end]
        gate = body.index('if (!submissionTraceCaptureActive())')
        direct_forward = body.index(
            'return FunctionCast(wrapBackingAllocPhysical, orgBackingAllocPhysical)',
            gate)
        helper = body.index('RaphaelBacking::observe(', direct_forward)
        self.assertLess(gate, direct_forward)
        self.assertLess(direct_forward, helper)
        self.assertNotIn('captureSnapshot', body[:helper])

    def test_backing_route_has_exact_guard_and_participates_in_readiness(self):
        source = (ROOT / 'src/RaphaelGPU.cpp').read_text()
        self.assertIn(
            'kOffBackingAllocPhysical = 0x3aa76; // '
            '__ZN32AMDRadeonX6000_AMDAccelVidMemory13allocPhysicalEv [x6]',
            source)
        self.assertIn(
            'static const uint8_t backingAllocEntry[] = {0x55, 0x48, 0x89, 0xe5, '
            '0x41, 0x57, 0x41, 0x56, 0x41, 0x55, 0x41, 0x54, 0x53, 0x48, 0x83, '
            '0xec, 0x18};',
            source)
        self.assertIn('orgSubmitBuffer && orgBackingAllocPhysical && orgCommitIntoGPUPageTable;', source)
        self.assertIn('orgCommitIntoGPUPageTable;', source)
        self.assertIn('SUB: routes=%s count=7', source)

    def test_commit_route_and_map_window_are_bounded_and_correlated(self):
        source = (ROOT / 'src/RaphaelGPU.cpp').read_text()
        self.assertIn('kOffCommitIntoGPUPageTable = 0x3b4d2;', source)
        self.assertIn('static bool wrapCommitIntoGPUPageTable(void *memoryMap)', source)
        self.assertIn('submissionCommits.append({', source)
        self.assertIn('commitWindow.calls, commitWindow.failures', source)
        self.assertIn('commitWindow.firstSequence, commitWindow.lastSequence', source)

    def test_allocator_diagnostic_avoids_unproven_native_calls(self):
        source = (ROOT / 'src/RaphaelGPU.cpp').read_text()
        start = source.index('static bool wrapBackingAllocPhysical')
        end = source.index('static void wrapSubmitBuffer', start)
        body = source[start:end]
        self.assertNotIn('vtable + 0x1f8', body)
        self.assertNotIn('totalFree', body)
        self.assertIn('counters=%llu/%llu->%llu/%llu', source)

    def test_backing_summary_has_periodic_and_global_bounds(self):
        source = (ROOT / 'src/RaphaelGPU.cpp').read_text()
        start = source.index('static void publishPendingSubmissionTrace()')
        end = source.index('static void publishPendingVmObservations()', start)
        body = source[start:end]
        self.assertIn('backingDirtyPolls >= 600', body)
        self.assertIn('backingSummaryRecords < 32', body)
        self.assertIn('backingTrue + backingFalse', body)
        self.assertNotIn('settledBacking', body)

    def test_inactive_map_wrapper_forwards_before_snapshot_reads(self):
        source = (ROOT / 'src/RaphaelGPU.cpp').read_text()
        start = source.index('static bool wrapBatchMemoryMapPrepare')
        end = source.index('static void wrapSubmitBuffer', start)
        body = source[start:end]
        gate = body.index('if (!submissionTraceCaptureActive())')
        direct_forward = body.index(
            'return FunctionCast(wrapBatchMemoryMapPrepare, orgBatchMemoryMapPrepare)',
            gate)
        first_snapshot = body.index('captureMapSnapshot(accelerator, memoryMap)')
        self.assertLess(gate, direct_forward)
        self.assertLess(direct_forward, first_snapshot)
        self.assertEqual(body[:first_snapshot].count('captureMapSnapshot'), 0)

    def test_candidate178_keeps_probe_arguments_and_requires_phase_worker(self):
        previous = json.loads((ROOT / 'experiments/metal-010.json').read_text())
        current = json.loads((ROOT / 'experiments/metal-011.json').read_text())
        self.assertEqual(current['id'], 'metal-011')
        self.assertEqual(current['candidate_version'], '1.0.178')
        self.assertEqual(current['requested_diagnostic'],
                         previous['requested_diagnostic'])
        self.assertEqual(current['max_seconds'], previous['max_seconds'])
        self.assertEqual(current['run_probe_only_after_native_start'],
                         previous['run_probe_only_after_native_start'])
        self.assertIn('submission_map_phase', current['required_observations'])
        self.assertEqual(
            set(current['required_observations']) - {'submission_map_phase'},
            set(previous['required_observations']))
        policy = current['repeat_policy']
        self.assertIn('178-A', policy)
        self.assertIn('178-B', policy)
        self.assertIn('180 seconds', policy)
        self.assertIn('45-second probe', policy)
        self.assertIn('no automatic retry', policy)
        self.assertIn('must not drift', policy)
        self.assertIn('schema-6 recovery receipt', policy)
        self.assertIn('five-row ledger', policy)


if __name__ == '__main__':
    unittest.main()
