import importlib.util
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
            'RGPU_EVENT build=abc seq=0 XJ:   submitKIQFrame -> 1\n')
        self.assertEqual(rows[0]['kind'], 'kiq_submit')
        self.assertEqual(rows[0]['result'], 1)

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
