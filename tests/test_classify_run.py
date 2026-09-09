import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ClassifyTests(unittest.TestCase):
    def classifier(self):
        path = ROOT / 'tools/classify-run.py'
        self.assertTrue(path.exists(), 'missing fail-closed run classifier')
        spec = importlib.util.spec_from_file_location('classify_run', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def events(self, available=1, status=4, started=0):
        rows = [('build', {}), ('route', {'ok': True}),
                ('kiq', {'stamp': 1, 'result': 1}),
                ('hybrid_enter', {'available': available}),
                ('hybrid_exit', {'available': available, 'result': status}),
                ('engine_start', {'result': started})]
        return [dict(kind=k, build='abc', seq=i, **v) for i, (k, v) in enumerate(rows)]

    def candidate175_startup(self, classifier):
        spec = json.loads((ROOT / 'experiments/metal-008.json').read_text())
        captured = [json.loads(line) for line in
                    (ROOT / 'tests/fixtures/metal-008-175-events.jsonl').read_text().splitlines()]
        serial = ''.join(
            f"RGPU_EVENT build={row['build']} seq={row['seq']} {row['raw']}\n"
            for row in captured)
        serial += (f"RGPU_RECORDS build={captured[0]['build']} "
                   f"count={len(captured)} dropped=0 truncated=0\n")
        events = classifier.parse_serial(serial)
        return {
            'build_id':'693734a021524bd29dd71df774d917a3',
            'run_id':'1a065e4f5f674cc0a26d4e9dbdf59649',
            'spec':spec,
        }, events

    def test_candidate175_capture_is_probe_ready_but_final_verdict_remains_strict(self):
        classifier = self.classifier()
        manifest, events = self.candidate175_startup(classifier)

        incomplete = classifier.classify_probe_readiness(manifest, events[:50])
        self.assertEqual(incomplete['verdict'], 'INCONCLUSIVE')
        self.assertEqual(incomplete['earliest_failure'], 'accelerator_start_missing')

        for startup in (events[:51], events):
            readiness = classifier.classify_probe_readiness(manifest, startup)
            self.assertEqual(readiness['verdict'], 'PROBE_NOT_RUN')
            self.assertTrue(readiness['valid'])

        final = classifier.classify(manifest, events, None)
        self.assertEqual(final['verdict'], 'INCONCLUSIVE')
        self.assertEqual(final['earliest_failure'], 'sdma_vm_program_missing')

    def test_probe_readiness_keeps_preworkload_safety_gates(self):
        classifier = self.classifier()
        manifest, captured = self.candidate175_startup(classifier)

        mutations = []
        wrong_build = [dict(row) for row in captured]
        wrong_build[0]['build'] = 'wrong'
        mutations.append((wrong_build, 'INVALID', 'loaded_build'))
        bad_route = [dict(row) for row in captured]
        next(row for row in bad_route if row['kind'] == 'route')['ok'] = False
        mutations.append((bad_route, 'INVALID', 'route_guards'))
        bad_vm_route = [dict(row) for row in captured]
        next(row for row in bad_vm_route if row['kind'] == 'vm_program_route')['ok'] = False
        mutations.append((bad_vm_route, 'INVALID', 'sdma_vm_program_route_guard'))
        bad_topology_count = [dict(row) for row in captured]
        next(row for row in bad_topology_count
             if row['kind'] == 'sdma_topology_route')['count'] = 6
        mutations.append((bad_topology_count, 'INVALID', 'sdma_channel_route_guard'))
        failed_kiq = [dict(row) for row in captured]
        next(row for row in reversed(failed_kiq)
             if row['kind'] == 'kiq_submit')['result'] = 0
        mutations.append((failed_kiq, 'BASELINE_BLOCKED', 'kiq'))
        late_kiq = [dict(row) for row in captured[:51]] + [
            {'kind':'kiq_submit', 'build':manifest['build_id'], 'seq':51,
             'result':0}]
        mutations.append((late_kiq, 'BASELINE_BLOCKED', 'kiq'))
        failed_start = [dict(row) for row in captured]
        next(row for row in failed_start if row['kind'] == 'engine_start')['result'] = 0
        mutations.append((failed_start, 'STARTUP_FAILED_LATER', 'engine_start'))
        failed_accelerator = [dict(row) for row in captured]
        next(row for row in failed_accelerator
             if row['kind'] == 'accelerator_start')['result'] = 0
        mutations.append((failed_accelerator, 'STARTUP_FAILED_LATER',
                          'accelerator_start'))
        capture_loss = [dict(row) for row in captured] + [
            {'kind':'capture_loss', 'build':manifest['build_id'], 'reason':'overflow'}]
        mutations.append((capture_loss, 'INCONCLUSIVE', 'capture_loss'))
        page_timeout = [dict(row) for row in captured[:51]] + [
            {'kind':'sdma_page_timeout', 'build':manifest['build_id'], 'seq':51}]
        mutations.append((page_timeout, 'SDMA_PAGE_TIMEOUT', 'sdma0_page'))
        panic = [dict(row) for row in captured[:51]] + [
            {'kind':'guest_panic', 'build':manifest['build_id'], 'seq':51,
             'symbol':'panic'}]
        mutations.append((panic, 'GUEST_PANIC', 'guest_panic:panic'))

        for events, verdict, stage in mutations:
            with self.subTest(stage=stage):
                result = classifier.classify_probe_readiness(manifest, events)
                self.assertEqual(result['verdict'], verdict)
                self.assertEqual(result['earliest_failure'], stage)

    def test_probe_readiness_rejects_partial_or_refused_workload_evidence(self):
        classifier = self.classifier()
        manifest, captured = self.candidate175_startup(classifier)
        base = [dict(row) for row in captured]
        build = manifest['build_id']

        submit_only = base + [
            {'kind':'sdma_submit', 'build':build, 'seq':52, 'vmid':2,
             'valid':True, 'ib0':0x400100000, 'ib1':0, 'vm_sequence':7}]
        result = classifier.classify_probe_readiness(manifest, submit_only)
        self.assertEqual(result['earliest_failure'], 'sdma_vm_program_missing')

        for kind in ('vm_context', 'sdma_ib_repair'):
            with self.subTest(standalone_workload_kind=kind):
                observed = base + [{'kind':kind, 'build':build, 'seq':52}]
                result = classifier.classify_probe_readiness(manifest, observed)
                self.assertEqual(result['earliest_failure'],
                                 'sdma_vm_program_missing')

        program = {'kind':'vm_program', 'build':build, 'seq':52, 'hub':0, 'vmid':2,
                   'start':0x400000000, 'end':0x400ffffff,
                   'root':0x840abc000, 'reprogram':True,
                   'info_words':list(range(10)), 'words':list(range(21))}
        submit = {'kind':'sdma_submit', 'build':build, 'seq':53, 'vmid':2,
                  'valid':True, 'ib0':0x400100000, 'ib1':0, 'vm_sequence':7}
        refusal = {'kind':'vm_root_repair', 'build':build, 'seq':54,
                   'vm_sequence':7, 'vmid':2, 'repaired':False,
                   'reason':'system-root', 'prepared_match':True}
        result = classifier.classify_probe_readiness(
            manifest, base + [program, submit, refusal])
        self.assertEqual(result['earliest_failure'],
                         'vmid2_root_repair_refused:system-root')

        mismatch = dict(refusal, repaired=True, reason='repaired',
                        prepared_match=False)
        result = classifier.classify_probe_readiness(
            manifest, base + [program, submit, mismatch])
        self.assertEqual(result['verdict'], 'INVALID')
        self.assertEqual(result['earliest_failure'], 'vmid2_root_prepared_mismatch')

    def test_submission_trace_readiness_requires_routes_and_worker_not_workload_calls(self):
        classifier = self.classifier()
        manifest = {'build_id':'abc', 'spec':{'required_observations':[
                    'submission_trace']}}
        base = self.events(available=1, status=0, started=1) + [
            {'kind':'accelerator_start', 'build':'abc', 'seq':6, 'result':1}]

        missing = classifier.classify_probe_readiness(manifest, base)
        self.assertEqual(missing['verdict'], 'INCONCLUSIVE')
        self.assertEqual(missing['earliest_failure'], 'submission_trace_route_missing')

        failed = base + [
            {'kind':'submission_trace_route', 'build':'abc', 'seq':7, 'ok':False}]
        result = classifier.classify_probe_readiness(manifest, failed)
        self.assertEqual(result['verdict'], 'INVALID')
        self.assertEqual(result['earliest_failure'], 'submission_trace_route_guard')

        malformed = base + [
            {'kind':'submission_trace_route', 'build':'abc', 'seq':7,
             'ok':False, 'malformed':True}]
        result = classifier.classify_probe_readiness(manifest, malformed)
        self.assertEqual(result['verdict'], 'INVALID')
        self.assertEqual(result['earliest_failure'], 'submission_trace_route_guard')

        route = {'kind':'submission_trace_route', 'build':'abc', 'seq':7, 'ok':True}
        worker_missing = classifier.classify_probe_readiness(manifest, base + [route])
        self.assertEqual(worker_missing['earliest_failure'],
                         'submission_trace_worker_missing')

        malformed_worker = base + [route,
            {'kind':'submission_trace_summary', 'build':'abc', 'seq':8,
             'ok':False, 'malformed':True}]
        result = classifier.classify_probe_readiness(manifest, malformed_worker)
        self.assertEqual(result['verdict'], 'INVALID')
        self.assertEqual(result['earliest_failure'],
                         'submission_trace_worker_malformed')

        ready = base + [route,
            {'kind':'submission_trace_summary', 'build':'abc', 'seq':8,
             'ok':True, 'counts':[[0, 0, 0]] * 5, 'dropped':[0, 0]}]
        result = classifier.classify_probe_readiness(manifest, ready)
        self.assertTrue(result['valid'])
        self.assertEqual(result['verdict'], 'PROBE_NOT_RUN')

    def test_submission_trace_records_parse_strict_route_and_worker_readiness(self):
        rows = self.classifier().parse_serial(
            'RGPU_RECORDS build=abc count=4 dropped=0 truncated=0\n'
            'RGPU_EVENT build=abc seq=0 BUILD: identity=abc\n'
            'RGPU_EVENT build=abc seq=1 SUB: routes=ok count=5 entries-match=1 '
            'capture=armed\n'
            'RGPU_EVENT build=abc seq=2 SUB: summary process=0/0/0 '
            'mappings=0/0/0 prepare=0/0/0 map=0/0/0 submit=0/0/0 '
            'dropped=0/0\n'
            'RGPU_EVENT build=abc seq=3 SUB: routes=ok count=five entries-match=1 '
            'capture=armed\n')
        self.assertEqual(rows[1]['kind'], 'submission_trace_route')
        self.assertTrue(rows[1]['ok'])
        self.assertEqual(rows[2]['kind'], 'submission_trace_summary')
        self.assertTrue(rows[2]['ok'])
        self.assertEqual(rows[2]['counts'], [[0, 0, 0]] * 5)
        self.assertEqual(rows[3]['kind'], 'submission_trace_route')
        self.assertTrue(rows[3]['malformed'])
        self.assertFalse(rows[3]['ok'])

    def test_missing_build_or_route_never_valid(self):
        c = self.classifier().classify
        events = self.events()
        self.assertEqual(c({'build_id': 'wrong'}, events, None)['verdict'], 'INVALID')
        events[1]['ok'] = False
        self.assertFalse(c({'build_id': 'abc'}, events, None)['valid'])

    def test_missing_or_lost_hybrid_is_inconclusive(self):
        c = self.classifier().classify
        events = self.events()
        self.assertEqual(c({'build_id': 'abc'}, events[:3], None)['verdict'], 'INCONCLUSIVE')
        events.append(dict(kind='capture_loss', build='abc', seq=6))
        self.assertEqual(c({'build_id': 'abc'}, events, None)['verdict'], 'INCONCLUSIVE')

    def test_earliest_kiq_failure_precedes_hybrid(self):
        c = self.classifier().classify
        events = self.events()
        events[2]['result'] = 0
        self.assertEqual(c({'build_id': 'abc'}, events, None)['verdict'], 'BASELINE_BLOCKED')

    def test_hybrid_snapshot_does_not_prove_cause(self):
        c = self.classifier().classify
        for available, want in [(0, 'HYBRID_UNAVAILABLE_SUSPECTED'),
                                (1, 'HYBRID_QUEUE_SUSPECTED')]:
            self.assertEqual(c({'build_id': 'abc'}, self.events(available), None)['verdict'], want)
        self.assertEqual(c({'build_id': 'abc'}, self.events(1, 0), None)['verdict'],
                         'STARTUP_FAILED_LATER')

    def test_enumeration_and_partial_probe_cannot_pass(self):
        c = self.classifier().classify
        for probe in [{'passed': True}, {'device': 'AMD Radeon Navi23', 'metal3': True}]:
            self.assertEqual(c({'build_id': 'abc'}, self.events(1, 0, 1), probe)['verdict'],
                             'INCONCLUSIVE')
        self.assertEqual(c({'build_id': 'abc'}, self.events(1, 0, 1), None)['verdict'],
                         'PROBE_NOT_RUN')

    def test_probe_requires_nonce_exit_and_actual_checked_results(self):
        import json
        c = self.classifier().classify
        result = dict(run_id='nonce', passed=True, metal3=True, device='AMD Radeon Navi23',
                      registry_id=1, compute_rounds=3, compute_values_checked=196608,
                      render_pixels_checked=4096, completed_command_buffers=4)
        probe = {'run_id': 'nonce', 'output': 'RGPU_METAL_RESULT '+json.dumps(result)+
                 '\nRGPU_EXIT nonce 0\n'}
        self.assertEqual(c({'build_id': 'abc', 'run_id': 'nonce'}, self.events(1, 0, 1), probe)['verdict'], 'CORE_PROBE_PASS')
        self.assertNotEqual(c({'build_id': 'abc', 'run_id': 'new'}, self.events(1, 0, 1), probe)['verdict'], 'CORE_PROBE_PASS')
        self.assertEqual(c({'build_id': 'abc', 'run_id': 'new'}, self.events(1, 0, 1), probe)['verdict'], 'INVALID')
        probe['run_id'] = 'stale'
        self.assertNotEqual(c({'build_id': 'abc'}, self.events(1, 0, 1), probe)['verdict'], 'CORE_PROBE_PASS')

    def test_replay_is_deduplicated_and_conflicts_are_capture_loss(self):
        parse = self.classifier().parse_serial
        line = 'rgpu: RGPU_EVENT build=abc seq=0 BUILD: identity=abc\n'
        summary = 'RGPU_RECORDS build=abc count=1 dropped=0 truncated=0\n'
        rows = parse(summary+line+line)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['kind'], 'build')
        rows = parse(summary+line+line.replace('identity=abc', 'identity=def'))
        self.assertTrue(any(r['kind'] == 'capture_loss' for r in rows))

    def test_unterminated_replay_tail_is_ignored_until_complete(self):
        parse = self.classifier().parse_serial
        serial = ''.join([
            'RGPU_RECORDS build=abc count=2 dropped=0 truncated=0\n',
            'RGPU_EVENT build=abc seq=0 BUILD: identity=abc\n',
            'RGPU_EVENT build=abc seq=1 HY: HWLibs hybrid trace route=ok entries-match=1\n',
            'RGPU_EVENT build=abc seq=1 HY: HWLibs hybrid trace route='])
        rows = parse(serial)
        self.assertFalse(any(row['kind'] == 'capture_loss' for row in rows))
        self.assertEqual([row['kind'] for row in rows], ['build', 'route'])

    def test_snapshot_missing_last_record_is_not_complete_capture(self):
        parse = self.classifier().parse_serial
        rows = parse('RGPU_RECORDS build=abc count=2 dropped=0 truncated=0\n'
                     'RGPU_EVENT build=abc seq=0 BUILD: identity=abc\n')
        self.assertTrue(any(r['kind'] == 'capture_loss' for r in rows))

    def test_uppercase_native_dequeue_timeout_is_an_earlier_failure(self):
        parse = self.classifier().parse_serial
        rows = parse('RGPU_EVENT build=abc seq=0 XQ2: dequeue TIMEOUT after 50000 us; descriptor unchanged, startKIQ blocked\n')
        self.assertEqual(rows[0]['kind'], 'kiq')
        self.assertEqual(rows[0]['result'], 0)

    def test_absent_overflow_summary_is_capture_loss(self):
        rows = self.classifier().parse_serial('RGPU_EVENT build=abc seq=0 BUILD: identity=abc\n')
        self.assertTrue(any(r['kind'] == 'capture_loss' for r in rows))

    def test_early_raw_records_and_symbolicated_guest_panic_are_decisive(self):
        classifier = self.classifier()
        serial = '''
RaphaelGPU      rgpu: @ BUILD: identity=abc
RaphaelGPU      rgpu: @ HY: HWLibs hybrid trace route=ok entries-match=1 (max 8 calls)
RaphaelGPU      rgpu: @ SD: topology routes=ok count=5 entries-match=1
RaphaelGPU      rgpu: @ SD: topology applied: discovered=1 kept=SDMA0 removed=SDMA1 before initialize
RaphaelGPU      rgpu: @ SD: AMDHardware::initializeHWEngines -> 1 (topology-applied=1)
Debugger: Unexpected kernel trap number: 0xe, RIP: 0xffffff7f94b246f0, CR2: 0x0
0xffffffcb349c3a60 : 0xffffff7f94b246f0 com.apple.kext.AMDRadeonX6000 : __ZN37AMDRadeonX6000_AMDGraphicsAccelerator19createAccelChannelsEb + 0x278
0xffffffcb349c3c20 : 0xffffff7f94b257f8 com.apple.kext.AMDRadeonX6000 : __ZN37AMDRadeonX6000_AMDGraphicsAccelerator19populateAccelConfigEP13IOAccelConfig + 0x2ba
'''
        events = classifier.parse_serial(serial)
        panic = next(row for row in events if row['kind'] == 'guest_panic')
        self.assertEqual(panic['symbol'],
                         '__ZN37AMDRadeonX6000_AMDGraphicsAccelerator19createAccelChannelsEb')
        self.assertEqual(panic['offset'], 0x278)
        verdict = classifier.classify(
            {'build_id': 'abc', 'spec': {'required_observations': ['sdma_topology']}},
            events, None)
        self.assertTrue(verdict['valid'])
        self.assertEqual(verdict['verdict'], 'GUEST_PANIC')
        self.assertEqual(verdict['earliest_failure'],
                         'guest_panic:createAccelChannels+0x278')

    def test_raw_panic_without_exact_build_and_route_stays_inconclusive(self):
        classifier = self.classifier()
        serial = ('Debugger: Unexpected kernel trap number: 0xe, RIP: 0xffffff7f94b246f0, CR2: 0x0\n'
                  'frame com.apple.kext.AMDRadeonX6000 : createAccelChannels + 0x278\n')
        verdict = classifier.classify({'build_id': 'abc'},
                                      classifier.parse_serial(serial), None)
        self.assertFalse(verdict['valid'])
        self.assertEqual(verdict['verdict'], 'INCONCLUSIVE')

    def test_old_summary_cannot_cover_newer_records(self):
        rows = self.classifier().parse_serial(
            'RGPU_RECORDS build=abc count=1 dropped=0 truncated=0\n'
            'RGPU_EVENT build=abc seq=0 BUILD: identity=abc\n'
            'RGPU_EVENT build=abc seq=1 HY: HWLibs hybrid trace route=ok entries-match=1\n')
        self.assertTrue(any(r['kind'] == 'capture_loss' for r in rows))

    def test_complete_snapshot_is_not_invalidated_by_later_unsequenced_live_log(self):
        c = self.classifier()
        serial = ''.join([
            'RGPU_RECORDS build=abc count=6 dropped=0 truncated=0\n',
            'RGPU_EVENT build=abc seq=0 BUILD: identity=abc\n',
            'RGPU_EVENT build=abc seq=1 HY: HWLibs hybrid trace route=ok entries-match=1\n',
            'RGPU_EVENT build=abc seq=2 XJ: waitForHwStamp(1) -> 1\n',
            'RGPU_EVENT build=abc seq=3 HY: createHybridEngine enter: engine=10 available=1\n',
            'RGPU_EVENT build=abc seq=4 HY: createHybridEngine exit: engine=10 valid=1 available-before=1 status=0\n',
            'RGPU_EVENT build=abc seq=5 XJ: AMDHardware::startHWEngines -> 1\n',
            'RaphaelGPU      rgpu: @ XJ:   waitForHwStamp(20) -> 1\n'])
        events = c.parse_serial(serial)
        self.assertFalse(any(row['kind'] == 'capture_loss' for row in events))
        self.assertEqual(c.classify({'build_id':'abc'}, events, None)['verdict'],
                         'PROBE_NOT_RUN')

    def test_terminal_live_kiq_failure_precedes_following_panic(self):
        c = self.classifier()
        serial = ''.join([
            'RGPU_RECORDS build=abc count=6 dropped=0 truncated=0\n',
            'RGPU_EVENT build=abc seq=0 BUILD: identity=abc\n',
            'RGPU_EVENT build=abc seq=1 HY: HWLibs hybrid trace route=ok entries-match=1\n',
            'RGPU_EVENT build=abc seq=2 XJ: waitForHwStamp(1) -> 1\n',
            'RGPU_EVENT build=abc seq=3 HY: createHybridEngine enter: engine=10 available=1\n',
            'RGPU_EVENT build=abc seq=4 HY: createHybridEngine exit: engine=10 valid=1 available-before=1 status=0\n',
            'RGPU_EVENT build=abc seq=5 XJ: AMDHardware::startHWEngines -> 1\n',
            'RaphaelGPU      rgpu: @ XJ:   waitForHwStamp(1) -> 0\n',
            'Debugger: Unexpected kernel trap number: 0xe, RIP: 0xffffff8004fee210, CR2: 0xffffff8004fee210\n'])
        events = c.parse_serial(serial)
        failure = next(row for row in events if row['kind'] == 'kiq' and row['result'] == 0)
        self.assertEqual(failure['source'], 'live-terminal')
        verdict = c.classify({'build_id':'abc'}, events, None)
        self.assertTrue(verdict['valid'])
        self.assertEqual(verdict['verdict'], 'BASELINE_BLOCKED')
        self.assertEqual(verdict['earliest_failure'], 'kiq')

    def test_later_success_recovers_an_earlier_kiq_timeout(self):
        c = self.classifier().classify
        events = self.events()
        events[2]['result'] = 0
        for row in events[3:]:
            row['seq'] += 1
        events.insert(3, dict(kind='kiq', build='abc', seq=3, stamp=4, result=1))
        self.assertEqual(c({'build_id':'abc'}, events, None)['verdict'],
                         'HYBRID_QUEUE_SUSPECTED')

    def test_last_kiq_failure_remains_decisive(self):
        c = self.classifier().classify
        events = self.events()
        for row in events[3:]:
            row['seq'] += 1
        events.insert(3, dict(kind='kiq', build='abc', seq=3, stamp=4, result=0))
        self.assertEqual(c({'build_id':'abc'}, events, None)['verdict'],
                         'BASELINE_BLOCKED')

    def test_explicit_kiq_submit_result_outranks_generic_stamp_wait(self):
        c = self.classifier()
        events = self.events()
        events[2]['result'] = 0
        for row in events[3:]:
            row['seq'] += 1
        events.insert(3, dict(kind='kiq_submit', build='abc', seq=3, result=1))
        self.assertEqual(c.classify({'build_id':'abc'}, events, None)['verdict'],
                         'HYBRID_QUEUE_SUSPECTED')
        events[3]['result'] = 0
        self.assertEqual(c.classify({'build_id':'abc'}, events, None)['verdict'],
                         'BASELINE_BLOCKED')

    def test_submit_kiq_frame_is_a_structured_classifier_event(self):
        rows = self.classifier().parse_serial(
            'RGPU_RECORDS build=abc count=1 dropped=0 truncated=0\n'
            'RGPU_EVENT build=abc seq=0 XJ:   submitKIQFrame -> 1 caller=x6+0x683ef\n')
        self.assertEqual(rows[0]['kind'], 'kiq_submit')
        self.assertEqual(rows[0]['result'], 1)
        self.assertEqual(rows[0]['caller'], 0x683ef)

    def test_wait_stamp_retains_call_site_for_channel_attribution(self):
        rows = self.classifier().parse_serial(
            'RGPU_RECORDS build=abc count=1 dropped=0 truncated=0\n'
            'RGPU_EVENT build=abc seq=0 XJ:   waitForHwStamp(1) -> 0 caller=x6+0x5a5f0\n')
        self.assertEqual(rows[0]['kind'], 'kiq')
        self.assertEqual(rows[0]['stamp'], 1)
        self.assertEqual(rows[0]['result'], 0)
        self.assertEqual(rows[0]['caller'], 0x5a5f0)

    def test_live_terminal_kiq_failure_after_submit_still_precedes_panic(self):
        c = self.classifier()
        events = self.events()
        for row in events[3:]:
            row['seq'] += 1
        events.insert(3, dict(kind='kiq_submit', build='abc', seq=3, result=1))
        events.extend([
            dict(kind='kiq', build='abc', seq=20, result=0, source='live-terminal'),
            dict(kind='guest_panic', build='abc', seq=21, raw='panic')])
        self.assertEqual(c.classify({'build_id':'abc'}, events, None)['verdict'],
                         'BASELINE_BLOCKED')

    def test_required_sdma_observation_cannot_silently_fall_back(self):
        c = self.classifier().classify
        manifest = {'build_id':'abc', 'spec':{'required_observations':['sdma_selection'],
                    'sdma_selection_target':{'index':1, 'queue_type':0}}}
        events = self.events()
        self.assertEqual(c(manifest, events, None)['verdict'], 'INCONCLUSIVE')
        events.append(dict(kind='sdma_route', build='abc', seq=6, ok=False))
        self.assertEqual(c(manifest, events, None)['verdict'], 'INVALID')
        events[-1]['ok'] = True
        self.assertEqual(c(manifest, events, None)['verdict'], 'INCONCLUSIVE')
        events.append(dict(kind='sdma_select', build='abc', seq=7, index=1, queue_type=0,
                           found=False, counts=[1,0,0,0]))
        self.assertEqual(c(manifest, events, None)['verdict'], 'HYBRID_QUEUE_SUSPECTED')
        events[-1]['index'] = 0
        events[-1]['found'] = True
        self.assertEqual(c(manifest, events, None)['verdict'], 'INCONCLUSIVE')

    def test_sdma_lookup_preserves_index_type_and_missing_instance(self):
        rows = self.classifier().parse_serial(
            'RGPU_RECORDS build=abc count=2 dropped=0 truncated=0\n'
            'RGPU_EVENT build=abc seq=0 HY: SDMA selector trace route=ok entries-match=1\n'
            'RGPU_EVENT build=abc seq=1 HY: SDMA select index=1 queue-type=0 found=0 counts=1,0,0,0 queues=0,0,0 occupied=0 callback=0xffffffffffffffff\n')
        self.assertEqual(rows[0]['kind'], 'sdma_route')
        self.assertTrue(rows[0]['ok'])
        self.assertEqual(rows[1]['kind'], 'sdma_select')
        self.assertEqual(rows[1]['index'], 1)
        self.assertEqual(rows[1]['queue_type'], 0)
        self.assertFalse(rows[1]['found'])
        self.assertEqual(rows[1]['counts'], [1,0,0,0])

    def test_required_topology_repair_must_route_and_apply_before_start(self):
        c = self.classifier()
        manifest = {'build_id':'abc', 'spec':{'required_observations':['sdma_topology']}}
        baseline = self.events(1, 0, 1)
        self.assertEqual(c.classify(manifest, baseline, None)['verdict'], 'INCONCLUSIVE')

        serial = ''.join([
            'RGPU_EVENT build=abc seq=0 BUILD: identity=abc\n',
            'RGPU_EVENT build=abc seq=1 HY: HWLibs hybrid trace route=ok entries-match=1 (max 8 calls)\n',
            'RGPU_EVENT build=abc seq=2 SD: topology routes=ok count=5 entries-match=1\n',
            'RGPU_EVENT build=abc seq=3 SD: topology applied: discovered=1 kept=SDMA0 removed=SDMA1 before initialize\n',
            'RGPU_EVENT build=abc seq=4 SD: AMDHardware::initializeHWEngines -> 1 (topology-applied=1)\n',
            'RGPU_EVENT build=abc seq=5 XJ: waitForHwStamp(1) -> 1\n',
            'RGPU_EVENT build=abc seq=6 HY: createHybridEngine enter: engine=10 available=1\n',
            'RGPU_EVENT build=abc seq=7 HY: SDMA select index=0 queue-type=0 found=1 counts=1,0,0,0 queues=2,0,0 occupied=0 callback=0xffffff8000000000\n',
            'RGPU_EVENT build=abc seq=8 HY: createHybridEngine exit: engine=10 valid=1 available-before=1 status=0\n',
            'RGPU_EVENT build=abc seq=9 HY: createHybridEngine enter: engine=11 available=1\n',
            'RGPU_EVENT build=abc seq=10 HY: SDMA select index=0 queue-type=1 found=1 counts=1,0,0,0 queues=2,0,0 occupied=0 callback=0xffffff8000000000\n',
            'RGPU_EVENT build=abc seq=11 HY: createHybridEngine exit: engine=11 valid=1 available-before=1 status=0\n',
            'RGPU_EVENT build=abc seq=12 SD: one-instance start -> 1 (SDMA0=0xffffff8000001000 SDMA1=0)\n',
            'RGPU_EVENT build=abc seq=13 XJ: AMDHardware::startHWEngines -> 1\n',
            'RGPU_RECORDS build=abc count=14 dropped=0 truncated=0\n'])
        events = c.parse_serial(serial)
        self.assertEqual(c.classify(manifest, events, None)['verdict'], 'PROBE_NOT_RUN')

        missing_apply = [dict(row) for row in events if row['kind'] != 'sdma_topology']
        for seq, row in enumerate(missing_apply): row['seq'] = seq
        self.assertEqual(c.classify(manifest, missing_apply, None)['verdict'], 'INCONCLUSIVE')
        bad_route = [dict(row) for row in events]
        next(row for row in bad_route if row['kind'] == 'sdma_topology_route')['ok'] = False
        self.assertEqual(c.classify(manifest, bad_route, None)['verdict'], 'INVALID')

        late = [dict(row) for row in events]
        apply = next(row for row in late if row['kind'] == 'sdma_topology')
        start = next(row for row in late if row['kind'] == 'engine_start')
        apply['seq'], start['seq'] = start['seq'], apply['seq']
        late.sort(key=lambda row: row['seq'])
        self.assertEqual(c.classify(manifest, late, None)['verdict'], 'INCONCLUSIVE')

        arbitrary = serial.replace(
            'SD: topology applied: discovered=1 kept=SDMA0 removed=SDMA1 before initialize',
            'SD: topology applied: arbitrary text')
        self.assertEqual(c.classify(manifest, c.parse_serial(arbitrary), None)['verdict'],
                         'INCONCLUSIVE')
        no_replacement_start = serial.replace(
            'SD: one-instance start -> 1 (SDMA0=0xffffff8000001000 SDMA1=0)',
            'SD: replacement start record absent')
        self.assertEqual(c.classify(manifest, c.parse_serial(no_replacement_start), None)['verdict'],
                         'INCONCLUSIVE')
        init_failed = serial.replace(
            'SD: AMDHardware::initializeHWEngines -> 1 (topology-applied=1)',
            'SD: AMDHardware::initializeHWEngines -> 0 (topology-applied=1)')
        self.assertEqual(c.classify(manifest, c.parse_serial(init_failed), None)['verdict'],
                         'STARTUP_FAILED_LATER')
        missing_queue_one = serial.replace(
            'HY: SDMA select index=0 queue-type=1 found=1 counts=1,0,0,0 queues=2,0,0 occupied=0 callback=0xffffff8000000000',
            'HY: SDMA queue-one record absent')
        self.assertEqual(c.classify(manifest, c.parse_serial(missing_queue_one), None)['verdict'],
                         'INCONCLUSIVE')
        false_second = serial.replace(
            'HY: SDMA select index=0 queue-type=1 found=1 counts=1,0,0,0 queues=2,0,0 occupied=0 callback=0xffffff8000000000',
            'HY: SDMA select index=1 queue-type=0 found=0 counts=1,0,0,0 queues=0,0,0 occupied=0 callback=0xffffffffffffffff')
        self.assertEqual(c.classify(manifest, c.parse_serial(false_second), None)['verdict'],
                         'STARTUP_FAILED_LATER')

        queue_after_replacement = [dict(row) for row in events]
        queue_one = next(row for row in queue_after_replacement
                         if row['kind'] == 'sdma_select' and row['queue_type'] == 1)
        replacement = next(row for row in queue_after_replacement
                           if row['kind'] == 'sdma_one_start')
        queue_one['seq'], replacement['seq'] = replacement['seq'], queue_one['seq']
        queue_after_replacement.sort(key=lambda row: row['seq'])
        self.assertEqual(c.classify(manifest, queue_after_replacement, None)['verdict'],
                         'INCONCLUSIVE')

        reversed_exits = [dict(row) for row in events]
        exit_zero = next(row for row in reversed_exits
                         if row['kind'] == 'hybrid_exit' and row['engine'] == 10)
        exit_one = next(row for row in reversed_exits
                        if row['kind'] == 'hybrid_exit' and row['engine'] == 11)
        exit_zero['seq'], exit_one['seq'] = exit_one['seq'], exit_zero['seq']
        reversed_exits.sort(key=lambda row: row['seq'])
        self.assertEqual(c.classify(manifest, reversed_exits, None)['verdict'],
                         'INCONCLUSIVE')

        missing_correlated_enter = [dict(row) for row in events
                                    if not (row['kind'] == 'hybrid_enter' and
                                            row['engine'] == 10)]
        for seq, row in enumerate(missing_correlated_enter): row['seq'] = seq
        self.assertEqual(c.classify(manifest, missing_correlated_enter, None)['verdict'],
                         'INCONCLUSIVE')

        duplicate_selection = [dict(row) for row in events]
        duplicate = dict(next(row for row in duplicate_selection
                              if row['kind'] == 'sdma_select' and row['queue_type'] == 0))
        for row in duplicate_selection:
            if row['seq'] >= 8: row['seq'] += 1
        duplicate['seq'] = 8
        duplicate_selection.append(duplicate)
        duplicate_selection.sort(key=lambda row: row['seq'])
        self.assertEqual(c.classify(manifest, duplicate_selection, None)['verdict'],
                         'INCONCLUSIVE')

    def test_candidate_166_requires_the_sdma1_channel_remap(self):
        c = self.classifier()
        manifest = {'build_id': 'abc', 'spec': {'required_observations': [
                    'sdma_topology', 'sdma_channel_remap']}}
        serial = ''.join([
            'RGPU_EVENT build=abc seq=0 BUILD: identity=abc\n',
            'RGPU_EVENT build=abc seq=1 HY: HWLibs hybrid trace route=ok entries-match=1\n',
            'RGPU_EVENT build=abc seq=2 SD: topology routes=ok count=6 entries-match=1\n',
            'RGPU_EVENT build=abc seq=3 SD: topology applied: discovered=1 kept=SDMA0 removed=SDMA1 before initialize\n',
            'RGPU_EVENT build=abc seq=4 SD: AMDHardware::initializeHWEngines -> 1 (topology-applied=1)\n',
            'RGPU_EVENT build=abc seq=5 SD: channel engine remap 2 -> 1 ring=3\n',
            'RGPU_EVENT build=abc seq=6 XJ: waitForHwStamp(1) -> 1\n',
            'RGPU_EVENT build=abc seq=7 HY: createHybridEngine enter: engine=10 available=1\n',
            'RGPU_EVENT build=abc seq=8 HY: SDMA select index=0 queue-type=0 found=1 counts=1,0,0,0 queues=2,0,0 occupied=0 callback=0xffffff8000000000\n',
            'RGPU_EVENT build=abc seq=9 HY: createHybridEngine exit: engine=10 valid=1 available-before=1 status=0\n',
            'RGPU_EVENT build=abc seq=10 HY: createHybridEngine enter: engine=11 available=1\n',
            'RGPU_EVENT build=abc seq=11 HY: SDMA select index=0 queue-type=1 found=1 counts=1,0,0,0 queues=2,0,0 occupied=0 callback=0xffffff8000000000\n',
            'RGPU_EVENT build=abc seq=12 HY: createHybridEngine exit: engine=11 valid=1 available-before=1 status=0\n',
            'RGPU_EVENT build=abc seq=13 SD: one-instance start -> 1 (SDMA0=0xffffff8000001000 SDMA1=0)\n',
            'RGPU_EVENT build=abc seq=14 XJ: AMDHardware::startHWEngines -> 1\n',
            'RGPU_RECORDS build=abc count=15 dropped=0 truncated=0\n'])
        events = c.parse_serial(serial)
        self.assertEqual(c.classify(manifest, events, None)['verdict'], 'PROBE_NOT_RUN')
        missing = [row for row in events if row['kind'] != 'sdma_engine_remap']
        for seq, row in enumerate(missing):
            if 'seq' in row: row['seq'] = seq
        self.assertEqual(c.classify(manifest, missing, None)['earliest_failure'],
                         'sdma_channel_remap_missing')

    def test_sdma_vm_observation_and_page_timeout_are_decisive(self):
        c = self.classifier()
        manifest = {'build_id': 'abc', 'spec': {'required_observations': [
                    'sdma_topology', 'sdma_channel_remap', 'sdma_vm_context']}}
        serial = ''.join([
            'RGPU_EVENT build=abc seq=0 BUILD: identity=abc\n',
            'RGPU_EVENT build=abc seq=1 HY: HWLibs hybrid trace route=ok entries-match=1\n',
            'RGPU_EVENT build=abc seq=2 SD: topology routes=ok count=7 entries-match=1\n',
            'RGPU_EVENT build=abc seq=3 SD: topology applied: discovered=1 kept=SDMA0 removed=SDMA1 before initialize\n',
            'RGPU_EVENT build=abc seq=4 SD: AMDHardware::initializeHWEngines -> 1 (topology-applied=1)\n',
            'RGPU_EVENT build=abc seq=5 SD: channel engine remap 2 -> 1 ring=3\n',
            'RGPU_EVENT build=abc seq=6 XJ: waitForHwStamp(1) -> 1\n',
            'RGPU_EVENT build=abc seq=7 HY: createHybridEngine enter: engine=10 available=1\n',
            'RGPU_EVENT build=abc seq=8 HY: SDMA select index=0 queue-type=0 found=1 counts=1,0,0,0 queues=2,0,0 occupied=0 callback=0xffffff8000000000\n',
            'RGPU_EVENT build=abc seq=9 HY: createHybridEngine exit: engine=10 valid=1 available-before=1 status=0\n',
            'RGPU_EVENT build=abc seq=10 HY: createHybridEngine enter: engine=11 available=1\n',
            'RGPU_EVENT build=abc seq=11 HY: SDMA select index=0 queue-type=1 found=1 counts=1,0,0,0 queues=2,0,0 occupied=0 callback=0xffffff8000000000\n',
            'RGPU_EVENT build=abc seq=12 HY: createHybridEngine exit: engine=11 valid=1 available-before=1 status=0\n',
            'RGPU_EVENT build=abc seq=13 SD: one-instance start -> 1 (SDMA0=0xffffff8000001000 SDMA1=0)\n',
            'RGPU_EVENT build=abc seq=14 XJ: AMDHardware::startHWEngines -> 1\n',
            'RGPU_EVENT build=abc seq=15 VM: invalidate hub=0 vmid=2 start=0x400000000 end=0x400ffffff root=0x840abc000 flags=0x3 reprogram=1\n',
            'RGPU_EVENT build=abc seq=16 VM: context-snapshot vmid=2 root=0x840abc000 ctl=0x80101 start=0x400000000 end=0x400ffffff\n',
            'RGPU_EVENT build=abc seq=17 SD: submit vmid=2 flags=0x123 entries=1 valid=1 IB0=0x400100020 IB1=0\n',
            'RGPU_RECORDS build=abc count=18 dropped=0 truncated=0\n',
            '[0:6:0]: HW Channel 12 SDMA0_PAGE is occupied by channel 34 stamp 1\n'])
        events = c.parse_serial(serial)
        result = c.classify(manifest, events, None)
        self.assertTrue(result['valid'])
        self.assertEqual(result['verdict'], 'SDMA_PAGE_TIMEOUT')
        self.assertEqual(result['earliest_failure'], 'sdma0_page')

        missing = serial.replace(
            'RGPU_EVENT build=abc seq=17 SD: submit vmid=2 flags=0x123 entries=1 valid=1 IB0=0x400100020 IB1=0\n', '')
        missing = missing.replace('count=18', 'count=17')
        result = c.classify(manifest, c.parse_serial(missing), None)
        self.assertEqual(result['verdict'], 'INCONCLUSIVE')
        self.assertEqual(result['earliest_failure'], 'sdma_vm_context_missing')

        mismatched = serial.replace('root=0x840abc000 ctl=0x80101',
                                    'root=0x840def000 ctl=0x80101')
        result = c.classify(manifest, c.parse_serial(mismatched), None)
        self.assertEqual(result['verdict'], 'INCONCLUSIVE')
        self.assertEqual(result['earliest_failure'], 'sdma_vm_context_mismatch')

        outside = serial.replace('IB0=0x400100020', 'IB0=0x500100020')
        result = c.classify(manifest, c.parse_serial(outside), None)
        self.assertEqual(result['verdict'], 'INCONCLUSIVE')
        self.assertEqual(result['earliest_failure'], 'sdma_vm_context_mismatch')

    def test_raw_terminal_order_outranks_later_structured_kiq_failure(self):
        c = self.classifier()
        manifest = {'build_id': 'abc', 'spec': {'required_observations': [
                    'sdma_topology', 'sdma_channel_remap', 'sdma_vm_context']}}
        serial = ''.join([
            'RGPU_EVENT build=abc seq=0 BUILD: identity=abc\n',
            'RGPU_EVENT build=abc seq=1 HY: HWLibs hybrid trace route=ok entries-match=1\n',
            'RGPU_EVENT build=abc seq=2 SD: topology routes=ok count=7 entries-match=1\n',
            'RGPU_EVENT build=abc seq=3 SD: topology applied: discovered=1 kept=SDMA0 removed=SDMA1 before initialize\n',
            'RGPU_EVENT build=abc seq=4 SD: AMDHardware::initializeHWEngines -> 1 (topology-applied=1)\n',
            'RGPU_EVENT build=abc seq=5 SD: channel engine remap 2 -> 1 ring=3\n',
            'RGPU_EVENT build=abc seq=6 XJ: waitForHwStamp(1) -> 1\n',
            'RGPU_EVENT build=abc seq=7 HY: createHybridEngine enter: engine=10 available=1\n',
            'RGPU_EVENT build=abc seq=8 HY: SDMA select index=0 queue-type=0 found=1 counts=1,0,0,0 queues=2,0,0 occupied=0 callback=0xffffff8000000000\n',
            'RGPU_EVENT build=abc seq=9 HY: createHybridEngine exit: engine=10 valid=1 available-before=1 status=0\n',
            'RGPU_EVENT build=abc seq=10 HY: createHybridEngine enter: engine=11 available=1\n',
            'RGPU_EVENT build=abc seq=11 HY: SDMA select index=0 queue-type=1 found=1 counts=1,0,0,0 queues=2,0,0 occupied=0 callback=0xffffff8000000000\n',
            'RGPU_EVENT build=abc seq=12 HY: createHybridEngine exit: engine=11 valid=1 available-before=1 status=0\n',
            'RGPU_EVENT build=abc seq=13 SD: one-instance start -> 1 (SDMA0=0xffffff8000001000 SDMA1=0)\n',
            'RGPU_EVENT build=abc seq=14 XJ: AMDHardware::startHWEngines -> 1\n',
            'RGPU_EVENT build=abc seq=15 SD: submit vmid=2 flags=0 entries=1 valid=1 IB0=0x400100000 IB1=0\n',
            'RGPU_EVENT build=abc seq=16 XJ: waitForHwStamp(28) -> 0\n',
            'RGPU_EVENT build=abc seq=17 XJ: submitKIQFrame -> 0\n',
            'RGPU_RECORDS build=abc count=18 dropped=0 truncated=0\n',
            '[0:6:0]: HW Channel 12 SDMA0_PAGE is occupied by channel 34 stamp 1\n',
            'RaphaelGPU rgpu: @ XJ:   waitForHwStamp(28) -> 0\n'])
        events = c.parse_serial(serial)
        result = c.classify(manifest, events, None)
        self.assertEqual(result['verdict'], 'INCONCLUSIVE')
        self.assertEqual(result['earliest_failure'], 'sdma_vm_context_missing')

    def test_submit_and_vm_context_records_parse(self):
        rows = self.classifier().parse_serial(
            'RGPU_RECORDS build=abc count=3 dropped=0 truncated=0\n'
            'RGPU_EVENT build=abc seq=0 VM: invalidate hub=0 vmid=2 start=0x400000000 end=0x400ffffff root=0x840abc000 flags=0x3 reprogram=1\n'
            'RGPU_EVENT build=abc seq=1 VM: context-snapshot vmid=2 root=0x840abc000 ctl=0x80101 start=0x400000000 end=0x400ffffff\n'
            'RGPU_EVENT build=abc seq=2 SD: submit vmid=2 flags=0x123 entries=3 valid=1 IB0=0x400900000 IB1=0x401180000\n')
        self.assertEqual(rows[0]['kind'], 'vm_invalidate')
        self.assertEqual(rows[0]['vmid'], 2)
        self.assertEqual(rows[0]['root'], 0x840abc000)
        self.assertEqual(rows[1]['kind'], 'vm_context')
        self.assertEqual(rows[1]['control'], 0x80101)
        self.assertEqual(rows[2]['kind'], 'sdma_submit')
        self.assertEqual(rows[2]['vmid'], 2)
        self.assertEqual(rows[2]['ib0'], 0x400900000)
        self.assertEqual(rows[2]['ib1'], 0x401180000)

    def test_prepared_vm_program_record_parses_all_native_words(self):
        words = ','.join(f'{0x1000 + i:08x}' for i in range(21))
        info = ','.join(f'{0x2000 + i:08x}' for i in range(10))
        rows = self.classifier().parse_serial(
            'RGPU_RECORDS build=abc count=1 dropped=0 truncated=0\n'
            'RGPU_EVENT build=abc seq=0 VM: prepared hub=0 vmid=2 '
            'start=0x400000000 end=0x400ffffff root=0x840abc000 flags=0x3 '
            f'reprogram=1 alternate=1 info={info} words={words}\n')
        self.assertEqual(rows[0]['kind'], 'vm_program')
        self.assertEqual(rows[0]['vmid'], 2)
        self.assertEqual(rows[0]['root'], 0x840abc000)
        self.assertEqual(rows[0]['info_words'], list(range(0x2000, 0x200a)))
        self.assertEqual(rows[0]['words'], list(range(0x1000, 0x1015)))

        route = self.classifier().parse_serial(
            'RGPU_RECORDS build=abc count=1 dropped=0 truncated=0\n'
            'RGPU_EVENT build=abc seq=0 VM: route '
            'AMDGFX10VMM::prepareVMInvalidateRequest -> ok (org=0xffffff800006249c)\n')
        self.assertEqual(route[0]['kind'], 'vm_program_route')
        self.assertTrue(route[0]['ok'])

    def test_late_prepared_vm_program_survives_after_structured_snapshot(self):
        words = ','.join(f'{0x1000 + i:08x}' for i in range(21))
        info = ','.join(f'{0x2000 + i:08x}' for i in range(10))
        rows = self.classifier().parse_serial(
            'RGPU_RECORDS build=abc count=1 dropped=0 truncated=0\n'
            'RGPU_EVENT build=abc seq=0 BUILD: identity=abc\n'
            'RaphaelGPU rgpu: @ VM: prepared hub=0 vmid=2 '
            'start=0x400000000 end=0x400ffffff root=0x840abc000 flags=0x3 '
            f'reprogram=1 alternate=1 info={info} words={words}\n')
        programs = [row for row in rows if row['kind'] == 'vm_program']
        self.assertEqual(len(programs), 1)
        self.assertEqual(programs[0]['source'], 'live-observation')
        self.assertEqual(programs[0]['words'][20], 0x1014)

    def test_candidate173_root_repair_and_walk_are_structured(self):
        rows = self.classifier().parse_serial(
            'RGPU_RECORDS build=abc count=3 dropped=0 truncated=0\n'
            'RGPU_EVENT build=abc seq=0 VM: root-repair seq=7 vmid=2 '
            'original=0xf401234001 native=0x841234001 repaired=1 reason=repaired '
            'prepared-match=1\n'
            'RGPU_EVENT build=abc seq=1 VM: state seq=7 phase=dispatch+0ms vmid=2 '
            'ctl=0x49 root=0x841234001 start=0x400000000 end=0x400ffffff '
            'requested=0xf401234001 native=0x841234001 prepared=0x841234001 '
            'repaired=1 reason=repaired prepared-match=1 live-match=1\n'
            'RGPU_EVENT build=abc seq=2 VM: walk seq=7 va=0x400100000 '
            'root=0x841234001 valid=1 complete=1 count=3\n')
        self.assertEqual([row['kind'] for row in rows],
                         ['vm_root_repair', 'vm_state', 'vm_walk'])
        self.assertEqual(rows[0]['vm_sequence'], 7)
        self.assertTrue(rows[0]['repaired'] and rows[0]['prepared_match'])
        self.assertTrue(rows[1]['live_match'])
        self.assertEqual(rows[2]['va'], 0x400100000)

    def test_sdma_submit_carries_vm_program_sequence(self):
        rows = self.classifier().parse_serial(
            'RGPU_RECORDS build=abc count=1 dropped=0 truncated=0\n'
            'RGPU_EVENT build=abc seq=0 SD: submit vmid=2 flags=0 entries=1 '
            'valid=1 IB0=0x400100000 IB1=0 seq=9\n')
        self.assertEqual(rows[0]['kind'], 'sdma_submit')
        self.assertEqual(rows[0]['vm_sequence'], 9)

    def test_candidate173_parses_walk_entries_and_actual_invalidate_engine(self):
        rows = self.classifier().parse_serial(
            'RGPU_RECORDS build=abc count=8 dropped=0 truncated=0\n'
            'RGPU_EVENT build=abc seq=0 VM: walk-entry seq=7 va=0x400100000 '
            'n=1 level=1 index=2 table=0x841000000 raw=0xf401200001 '
            'addr=0xf401200000 V=1 S=0 C=0 X=0 R=0 W=0 P=0 TF=0 '
            'child-mc2pa=1\n'
            'RGPU_EVENT build=abc seq=1 VM: invalidate-live seq=7 phase=dispatch+0ms '
            'reg=0x286f kind=sem engine=2 value=unread\n'
            'RGPU_EVENT build=abc seq=2 VM: invalidate-live seq=7 phase=dispatch+0ms '
            'reg=0x287f kind=req engine=7 value=0x4 bit2=1\n'
            'RGPU_EVENT build=abc seq=3 VM: pre-clear-fault seq=7 cntl=0x801 '
            'status=0xdead addr=0x400100000\n'
            'RGPU_EVENT build=abc seq=4 VM: fault seq=7 phase=dispatch+0ms '
            'cntl=0x801 status=0xdead addr=0x400100000 | invalidate-order=0x2 '
            'eng0-sem=unread req=0x4 ack=0 bit2=1/0 prepared-mask=0x4/0x4\n'
            'RGPU_EVENT build=abc seq=5 SD: runtime seq=7 phase=dispatch+0ms '
            'cntl=0x1 ucode=0x22 f32=0x33 status=0x2/0x3/0x4/0x5 '
            'utcl-cntl=0x6 page=0x7 rd=0x8 wr=0x9\n'
            'RGPU_EVENT build=abc seq=6 SD: xnack seq=7 phase=dispatch+0ms '
            'rd=0xa/0xb wr=0xc/0xd\n'
            'RGPU_EVENT build=abc seq=7 SD: page seq=7 phase=dispatch+0ms '
            'status=0xe context=0xf ib-cntl=0x10 rptr=0x11 offset=0x12 '
            'base=0x13_00000014 size=0x15\n')
        self.assertEqual([row['kind'] for row in rows],
                         ['vm_walk_entry', 'vm_invalidate_live', 'vm_invalidate_live',
                          'vm_pre_clear_fault',
                          'vm_fault', 'sdma_runtime', 'sdma_xnack', 'sdma_page_state'])
        self.assertEqual(rows[0]['address'], 0xf401200000)
        self.assertTrue(rows[0]['child_converted'])
        self.assertEqual(rows[1]['register_kind'], 'sem')
        self.assertIsNone(rows[1]['value'])
        self.assertIsNone(rows[1]['vmid2_bit'])
        self.assertEqual(rows[2]['engine'], 7)
        self.assertTrue(rows[2]['vmid2_bit'])
        self.assertEqual(rows[3]['fault_status'], 0xdead)
        self.assertIsNone(rows[4]['semaphore0'])
        self.assertEqual(rows[4]['request_vmid2_bit'], 1)
        self.assertEqual(rows[5]['utcl_page'], 7)
        self.assertEqual(rows[5]['ucode_checksum'], 0x22)
        self.assertEqual(rows[5]['f32_control'], 0x33)
        self.assertEqual(rows[6]['write_xnack1'], 0xd)
        self.assertEqual(rows[7]['ib_base'], 0x1300000014)

    def test_candidate173_required_root_repair_fails_closed_and_correlates(self):
        classify = self.classifier().classify
        manifest = {'build_id': 'abc', 'spec': {'required_observations': [
                    'vmid2_root_repair']}}
        base = [dict(kind='build', build='abc', seq=0),
                dict(kind='route', build='abc', seq=1, ok=True)]

        result = classify(manifest, list(base), None)
        self.assertEqual(result['earliest_failure'], 'vmid2_root_repair_missing')

        refused = base + [dict(kind='vm_root_repair', build='abc', seq=2,
                               vm_sequence=7, vmid=2, repaired=False,
                               reason='system-root', prepared_match=True)]
        result = classify(manifest, refused, None)
        self.assertEqual(result['earliest_failure'],
                         'vmid2_root_repair_refused:system-root')

        mismatch = base + [dict(kind='vm_root_repair', build='abc', seq=2,
                                vm_sequence=7, vmid=2, repaired=True,
                                reason='repaired', prepared_match=False)]
        result = classify(manifest, mismatch, None)
        self.assertEqual(result['verdict'], 'INVALID')
        self.assertEqual(result['earliest_failure'], 'vmid2_root_prepared_mismatch')

        repaired = base + [
            dict(kind='vm_root_repair', build='abc', seq=2, vm_sequence=7,
                 vmid=2, repaired=True, reason='repaired', prepared_match=True),
            dict(kind='vm_state', build='abc', seq=3, vm_sequence=7,
                 vmid=2, phase='dispatch+0ms'),
            dict(kind='vm_walk', build='abc', seq=4, vm_sequence=7,
                 va=0x400100000, valid=True, complete=True),
            dict(kind='vm_walk', build='abc', seq=5, vm_sequence=7,
                 va=0x4000c0000, valid=True, complete=True),
            dict(kind='vm_walk', build='abc', seq=6, vm_sequence=7,
                 va=0x400200000, valid=True, complete=True),
            dict(kind='sdma_submit', build='abc', seq=7, vm_sequence=7,
                 vmid=2, valid=True, ib0=0x400100000, ib1=0),
        ]
        result = classify(manifest, repaired, None)
        self.assertEqual(result['earliest_failure'], 'required_native_record_missing')

        wrong_submit = [dict(row) for row in repaired]
        wrong_submit[-1]['vm_sequence'] = 8
        result = classify(manifest, wrong_submit, None)
        self.assertEqual(result['earliest_failure'], 'vmid2_root_submit_mismatch')

        missing_walk = repaired[:-2] + repaired[-1:]
        for seq, row in enumerate(missing_walk):
            row['seq'] = seq
        result = classify(manifest, missing_walk, None)
        self.assertEqual(result['earliest_failure'], 'vmid2_root_walk_missing')

    def test_required_vm_program_correlates_with_the_stalled_sdma_submit(self):
        c = self.classifier().classify
        manifest = {'build_id': 'abc', 'spec': {'required_observations': [
                    'sdma_topology', 'sdma_channel_remap', 'sdma_vm_program']}}
        rows = [
            dict(kind='build'), dict(kind='route', ok=True),
            dict(kind='vm_program_route', ok=True),
            dict(kind='sdma_topology_route', ok=True, count=7),
            dict(kind='sdma_topology', applied=True),
            dict(kind='sdma_initialize', applied=True, result=1),
            dict(kind='sdma_engine_remap', requested=2, selected=1),
            dict(kind='kiq', stamp=1, result=1),
            dict(kind='hybrid_enter', engine=10, available=1),
            dict(kind='sdma_select', index=0, queue_type=0, found=True,
                 counts=[1, 0, 0, 0]),
            dict(kind='hybrid_exit', engine=10, available=1, result=0),
            dict(kind='hybrid_enter', engine=11, available=1),
            dict(kind='sdma_select', index=0, queue_type=1, found=True,
                 counts=[1, 0, 0, 0]),
            dict(kind='hybrid_exit', engine=11, available=1, result=0),
            dict(kind='sdma_one_start', result=1),
            dict(kind='engine_start', result=1),
            dict(kind='vm_program', hub=0, vmid=2, start=0x400000000,
                 end=0x400ffffff, root=0x840abc000, reprogram=True,
                 info_words=list(range(10)), words=list(range(21))),
            dict(kind='sdma_submit', vmid=2, valid=True, ib0=0x400100020, ib1=0),
        ]
        events = [dict(row, build='abc', seq=i) for i, row in enumerate(rows)]
        events.append(dict(kind='sdma_page_timeout', build='abc', seq=100,
                           source='raw-terminal'))
        result = c(manifest, events, None)
        self.assertEqual(result['verdict'], 'SDMA_PAGE_TIMEOUT')
        self.assertEqual(result['earliest_failure'], 'sdma0_page')

        no_program = [row for row in events if row['kind'] != 'vm_program']
        for seq, row in enumerate(row for row in no_program
                                  if row.get('source') != 'raw-terminal'):
            row['seq'] = seq
        result = c(manifest, no_program, None)
        self.assertEqual(result['earliest_failure'], 'sdma_vm_program_missing')

    def test_required_vm_program_fails_closed_before_terminal_verdicts(self):
        c = self.classifier().classify
        manifest = {'build_id': 'abc', 'spec': {'required_observations': [
                    'sdma_topology', 'sdma_channel_remap', 'sdma_vm_program']}}
        base = [dict(kind='build', build='abc', seq=0),
                dict(kind='route', build='abc', seq=1, ok=True)]
        kiq = base + [dict(kind='kiq', build='abc', seq=2, result=0)]
        result = c(manifest, kiq, None)
        self.assertFalse(result['valid'])
        self.assertEqual(result['earliest_failure'], 'sdma_vm_program_route_guard')

        panic = base + [dict(kind='vm_program_route', build='abc', seq=2, ok=True),
                        dict(kind='guest_panic', build='abc', seq=3)]
        result = c(manifest, panic, None)
        self.assertFalse(result['valid'])
        self.assertEqual(result['earliest_failure'], 'sdma_vm_program_missing')

    def test_live_vm_observations_survive_until_the_next_structured_snapshot(self):
        rows = self.classifier().parse_serial(
            'RGPU_EVENT build=abc seq=0 BUILD: identity=abc\n'
            'RGPU_RECORDS build=abc count=1 dropped=0 truncated=0\n'
            'RaphaelGPU rgpu: @ VM: invalidate hub=0 vmid=2 start=0x400000000 end=0x400ffffff root=0x840abc000 flags=0x3 reprogram=1\n'
            'RaphaelGPU rgpu: @ VM: context-snapshot vmid=2 root=0x840abc000 ctl=0x80101 start=0x400000000 end=0x400ffffff\n'
            'RaphaelGPU rgpu: @ SD: submit vmid=2 flags=0x123 entries=1 valid=1 IB0=0x400100020 IB1=0\n')
        live = [row for row in rows if row.get('source') == 'live-observation']
        self.assertEqual([row['kind'] for row in live],
                         ['vm_invalidate', 'vm_context', 'sdma_submit'])
        self.assertFalse(any(row['kind'] == 'capture_loss' for row in rows))


if __name__ == '__main__':
    unittest.main()
