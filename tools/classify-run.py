#!/usr/bin/env python3
"""Classify sequenced critical records; never infer execution from enumeration."""
import argparse
import importlib.util
import json
from pathlib import Path
import re


def parse_serial(serial):
    records, losses, counts = {}, [], {}
    for line in serial.replace('\r', '').splitlines():
        summary = re.search(r'RGPU_RECORDS build=(\S+) count=(\d+) dropped=(\d+) truncated=(\d+)', line)
        if summary:
            counts[summary[1]] = max(counts.get(summary[1], 0), int(summary[2]))
        if summary and any(int(summary[i]) for i in (3, 4)):
            losses.append(dict(kind='capture_loss', build=summary[1], reason='overflow'))
        match = re.search(r'RGPU_EVENT build=(\S+) seq=(\d+) (.+)$', line)
        if not match:
            continue
        build, seq, payload = match[1], int(match[2]), match[3]
        key = (build, seq)
        if key in records:
            if records[key]['raw'] != payload:
                losses.append(dict(kind='capture_loss', build=build, reason='conflicting replay'))
            continue
        row = dict(build=build, seq=seq, kind='other', raw=payload)
        if payload == 'BUILD: identity='+build:
            row['kind'] = 'build'
        elif 'HY: HWLibs hybrid trace' in payload:
            row.update(kind='route', ok='route=ok entries-match=1' in payload)
        elif 'HY: SDMA selector trace' in payload:
            row.update(kind='sdma_route', ok='route=ok entries-match=1' in payload)
        elif m := re.search(r'HY: SDMA select index=(\d+) queue-type=(\d+) found=([01]) counts=(\d+),(\d+),(\d+),(\d+)', payload):
            row.update(kind='sdma_select', index=int(m[1]), queue_type=int(m[2]),
                       found=bool(int(m[3])), counts=[int(m[i]) for i in range(4,8)])
        elif m := re.search(r'waitForHwStamp\((\d+)\) -> (\d+)', payload):
            row.update(kind='kiq', stamp=int(m[1]), result=int(m[2]))
        elif m := re.search(r'HY: createHybridEngine enter: engine=(\d+) available=(\d+)', payload):
            row.update(kind='hybrid_enter', engine=int(m[1]), available=int(m[2]))
        elif m := re.search(r'HY: createHybridEngine exit: engine=(\d+) valid=(\d+) available-before=(\d+) status=(\d+)', payload):
            row.update(kind='hybrid_exit', engine=int(m[1]), arguments_valid=int(m[2]),
                       available=int(m[3]), result=int(m[4]))
        elif m := re.search(r'AMDHardware::startHWEngines -> (\d+)', payload):
            row.update(kind='engine_start', result=int(m[1]))
        elif payload.startswith('XQ2: dequeue') and ('refused' in payload or 'timeout' in payload.lower()):
            row.update(kind='kiq', result=0)
        records[key] = row
    for build, count in counts.items():
        if any((build, seq) not in records for seq in range(min(count, 129))):
            losses.append(dict(kind='capture_loss', build=build, reason='snapshot incomplete'))
    for build, _ in records:
        if build not in counts:
            losses.append(dict(kind='capture_loss', build=build, reason='overflow summary missing'))
            counts[build] = 0
    for build, seq in records:
        if seq >= counts[build]:
            losses.append(dict(kind='capture_loss', build=build, reason='summary precedes newer records'))
    rows = sorted(records.values(), key=lambda r: r['seq'])
    return rows + losses


def classify(manifest, events, probe):
    def verdict(name, valid=False, stage=None, next_action='repair observation before another experiment'):
        return dict(valid=valid, verdict=name, earliest_failure=stage,
                    evidence=[r.get('raw', r['kind']) for r in events], next_action=next_action)
    expected = manifest.get('build_id')
    if not expected or any(r.get('build') != expected for r in events):
        return verdict('INVALID', stage='loaded_build')
    kinds = {kind: [r for r in events if r['kind'] == kind]
             for kind in ('build', 'route', 'kiq', 'hybrid_enter', 'hybrid_exit', 'engine_start')}
    if any(not r.get('ok') for r in kinds['route']):
        return verdict('INVALID', stage='route_guards')
    if not kinds['build'] or not kinds['route']:
        return verdict('INCONCLUSIVE', stage='identity_or_route_missing')
    seqs = sorted(r['seq'] for r in events if 'seq' in r)
    if (any(r['kind'] == 'capture_loss' for r in events) or
            seqs != list(range(len(seqs)))):
        return verdict('INCONCLUSIVE', stage='capture_loss')
    if any(r.get('result') == 0 for r in kinds['kiq']):
        return verdict('BASELINE_BLOCKED', True, 'kiq', 'analyze the earlier KIQ failure offline; no retry')
    if 'sdma_selection' in manifest.get('spec', {}).get('required_observations', []):
        routes = [r for r in events if r['kind'] == 'sdma_route']
        if any(not r.get('ok') for r in routes):
            return verdict('INVALID', stage='sdma_route_guard')
        target = manifest['spec'].get('sdma_selection_target', {})
        selections = [r for r in events if r['kind'] == 'sdma_select' and
                      r.get('index') == target.get('index') and
                      r.get('queue_type') == target.get('queue_type')]
        if not routes or not selections:
            return verdict('INCONCLUSIVE', stage='sdma_selection_missing')
    if not kinds['kiq'] or not kinds['hybrid_enter'] or not kinds['hybrid_exit']:
        return verdict('INCONCLUSIVE', stage='required_native_record_missing')
    for row in kinds['hybrid_exit']:
        if row['result'] == 4:
            name = 'HYBRID_QUEUE_SUSPECTED' if row['available'] else 'HYBRID_UNAVAILABLE_SUSPECTED'
            return verdict(name, True, 'hybrid', 'locate native rejecting branch; snapshot is not causal proof')
        if row['result'] != 0:
            return verdict('HYBRID_FAILED', True, 'hybrid', 'decode native result and arguments offline')
    if not kinds['engine_start']:
        return verdict('INCONCLUSIVE', stage='engine_start_missing')
    if any(r['result'] == 0 for r in kinds['engine_start']):
        return verdict('STARTUP_FAILED_LATER', True, 'engine_start', 'trace the next native startup failure')
    if probe is None:
        return verdict('PROBE_NOT_RUN', True, next_action='run the prepared probe only if remaining budget permits')
    if not isinstance(probe, dict) or 'run_id' not in probe or 'output' not in probe:
        return verdict('INCONCLUSIVE', stage='probe_evidence_missing')
    if not manifest.get('run_id') or probe['run_id'] != manifest['run_id']:
        return verdict('INVALID', stage='probe_identity')
    if probe:
        path = Path(__file__).with_name('metal-test.py')
        spec = importlib.util.spec_from_file_location('metal_test', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        try:
            if not manifest.get('run_id') or probe['run_id'] != manifest['run_id']:
                raise ValueError('probe nonce differs from the prepared experiment')
            module.validate_output(probe['output'], manifest['run_id'])
        except (KeyError, ValueError, TypeError):
            exits = re.findall(r'^RGPU_EXIT '+re.escape(manifest['run_id'])+r' (\d+)$', probe['output'], re.M)
            if len(exits) != 1:
                return verdict('INCONCLUSIVE', stage='probe_completion_missing')
        else:
            return verdict('CORE_PROBE_PASS', True, next_action='qualify memory, lifecycle and desktop; core probe alone is insufficient')
    return verdict('EXECUTION_FAILED', True, 'first_submission', 'inspect command completion and checked output')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_directory', type=Path)
    args = parser.parse_args()
    run = args.run_directory
    manifest = json.loads((run / 'manifest.json').read_text())
    events = parse_serial((run / 'serial.txt').read_text(errors='replace'))
    probe_path = run / 'probe.json'
    probe = json.loads(probe_path.read_text()) if probe_path.exists() else None
    print(json.dumps(classify(manifest, events, probe), indent=2))
