#!/usr/bin/env python3
"""Report observed acceleration stages without rewriting a run's frozen verdict."""
import argparse
import hashlib
import json
from pathlib import Path
import re


STAGES = (
    'native_engine_start',
    'client_channel_activity',
    'submission_entry',
    'compute_acceptance',
    'render_acceptance',
    'cleanup',
)

ACCEPTANCE_PROBE_SOURCE_SHA256 = (
    'f0fc0ced81fe70732c3491cff1557a83d85c9ccb8c18a6303f9070ae1f969d77')
ACCEPTANCE_PROBE_BINARY_SHA256 = (
    '1637e4b31bca0a1bdc400f96e34b344a823de1b408a8d1677d6bcca475c8c787')


def _stage(state, evidence, capture):
    return {'state': state, 'evidence': evidence, 'capture': capture}


def _load_json_lines(path):
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _probe_result(path, expected_run_id):
    if not path.is_file():
        return None
    value = json.loads(path.read_text())
    if (not isinstance(value, dict) or not expected_run_id or
            value.get('run_id') != expected_run_id):
        return None
    output = value.get('output') if isinstance(value, dict) else None
    if (not isinstance(output, str) or type(value.get('transport_exit')) is not int or
            value.get('transport_exit') != 0):
        return None
    matches = re.findall(r'^RGPU_METAL_RESULT (\{.*\})$', output, re.M)
    if len(matches) != 1:
        return None
    try:
        result = json.loads(matches[0])
    except json.JSONDecodeError:
        return None
    if not isinstance(result, dict) or result.get('run_id') != expected_run_id:
        return None
    exits = re.findall(
        r'^RGPU_EXIT ' + re.escape(expected_run_id) + r' (\d+)$', output, re.M)
    if len(exits) != 1:
        return None
    return {'result': result, 'guest_exit': int(exits[0])}


def _acceptance_probe_artifact(manifest):
    return (manifest.get('probe_source_sha256') == ACCEPTANCE_PROBE_SOURCE_SHA256 and
            manifest.get('probe_binary_sha256') == ACCEPTANCE_PROBE_BINARY_SHA256)


def _positive_int_at_least(value, minimum):
    return type(value) is int and value >= minimum


def _raw_verdict(directory):
    candidates = (directory / 'verdict-original.json', directory / 'verdict.json')
    path = next((candidate for candidate in candidates if candidate.is_file()), None)
    if path is None:
        return {'path': None, 'sha256': None}
    return {'path': path.name,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def analyze_run(directory):
    directory = Path(directory)
    manifest = json.loads((directory / 'manifest.json').read_text())
    required = set(manifest.get('spec', {}).get('required_observations', []))
    events = _load_json_lines(directory / 'events.jsonl')
    expected_build = manifest.get('build_id')
    identity_valid = bool(expected_build) and any(
        row.get('kind') == 'build' and row.get('build') == expected_build
        for row in events) and all(
            row.get('build') in (None, expected_build) for row in events)
    capture_complete = identity_valid and not any(
        row.get('kind') == 'capture_loss' for row in events)
    probe_evidence = _probe_result(directory / 'probe.json', manifest.get('run_id'))
    probe_interval_complete = (
        capture_complete and _acceptance_probe_artifact(manifest) and
        probe_evidence is not None)
    stages = {}

    engine = [row for row in events if row.get('kind') == 'engine_start']
    if identity_valid and any(row.get('result') == 1 for row in engine):
        stages['native_engine_start'] = _stage(
            'observed', 'engine_start result=1', True)
    elif capture_complete and 'engine_start' in required:
        stages['native_engine_start'] = _stage(
            'not_observed', 'required engine_start has no successful result', True)
    else:
        stages['native_engine_start'] = _stage(
            'unknown', 'no sufficient engine-start capture', False)

    submits = [row for row in events if row.get('kind') == 'sdma_submit' and
               row.get('valid')]
    if identity_valid and submits:
        stages['client_channel_activity'] = _stage(
            'observed', f'{len(submits)} valid SDMA submission record(s)', True)
    else:
        vm_program_ready = ('sdma_vm_program' in required and
                            any(row.get('kind') == 'vm_program_route' and row.get('ok')
                                for row in events))
        if probe_interval_complete and vm_program_ready:
            stages['client_channel_activity'] = _stage(
                'not_observed', 'armed VM/submission callback saw no valid SDMA submit', True)
        else:
            stages['client_channel_activity'] = _stage(
                'unknown', 'no sufficient client-channel capture', False)

    trace_routes = [row for row in events
                    if row.get('kind') == 'submission_trace_route' and row.get('ok')]
    summaries = [row for row in events
                 if row.get('kind') == 'submission_trace_summary' and row.get('ok')]
    valid_summaries = [row for row in summaries
                       if isinstance(row.get('counts'), list) and
                       len(row['counts']) == 5 and
                       all(isinstance(group, list) and len(group) == 3
                           and all(type(value) is int and value >= 0 for value in group)
                           for group in row['counts'])]
    submit_entries = max((row['counts'][4][0] for row in valid_summaries), default=0)
    final_process = valid_summaries[-1]['counts'][0] if valid_summaries else None
    trace_interval_complete = (
        probe_interval_complete and final_process is not None and
        final_process[0] > 0 and final_process[0] == final_process[1] == final_process[2])
    if identity_valid and submit_entries:
        stages['submission_entry'] = _stage(
            'observed', f'submission trace records {submit_entries} submit entry call(s)', True)
    elif (trace_interval_complete and 'submission_trace' in required and
          len(trace_routes) == 1 and valid_summaries):
        stages['submission_entry'] = _stage(
            'not_observed', 'armed submission trace records zero submit entries', True)
    else:
        stages['submission_entry'] = _stage(
            'unknown', 'no sufficient submission-entry capture', False)

    if not probe_interval_complete:
        stages['compute_acceptance'] = _stage(
            'unknown', 'no identity-bound result from the pinned acceptance probe', False)
        stages['render_acceptance'] = _stage(
            'unknown', 'no identity-bound result from the pinned acceptance probe', False)
    else:
        probe = probe_evidence['result']
        common = (probe.get('device') == 'AMD Radeon Navi23' and
                  probe.get('metal3') is True and
                  _positive_int_at_least(probe.get('registry_id'), 1))
        compute = (common and
                   _positive_int_at_least(probe.get('completed_command_buffers'), 3) and
                   _positive_int_at_least(probe.get('compute_rounds'), 3) and
                   _positive_int_at_least(probe.get('compute_values_checked'), 196608))
        render = (compute and probe.get('passed') is True and
                  probe_evidence['guest_exit'] == 0 and
                  _positive_int_at_least(probe.get('completed_command_buffers'), 4) and
                  _positive_int_at_least(probe.get('render_pixels_checked'), 4096))
        stages['compute_acceptance'] = _stage(
            'observed' if compute else 'not_observed',
            'structured Metal compute counters', True)
        stages['render_acceptance'] = _stage(
            'observed' if render else 'not_observed',
            'structured Metal render counter', True)

    recovery_path = directory / 'recovery.json'
    recovery = json.loads(recovery_path.read_text()) if recovery_path.is_file() else None
    if (isinstance(recovery, dict) and recovery.get('status') == 'recovered' and
            recovery.get('authorizes_launch') is True and manifest.get('run_id') and
            recovery.get('prior_run_id') == manifest.get('run_id')):
        stages['cleanup'] = _stage(
            'observed',
            'recovery record claims recovered/authorizing; receipt not revalidated here',
            True)
    elif (isinstance(recovery, dict) and manifest.get('run_id') and
          recovery.get('prior_run_id') == manifest.get('run_id')):
        stages['cleanup'] = _stage(
            'not_observed', 'recovery record is present but non-authorizing', True)
    else:
        stages['cleanup'] = _stage('unknown', 'no recovery record', False)

    serial_path = directory / 'serial.txt'
    serial = serial_path.read_text(errors='replace') if serial_path.is_file() else ''
    return {
        'run': directory.as_posix(),
        'run_id': manifest.get('run_id'),
        'build_id': manifest.get('build_id'),
        'raw_verdict': _raw_verdict(directory),
        'stages': stages,
        # This is independent evidence. It does not assign the failure to a
        # resource, allocator domain, process, or Metal command.
        'native_allocator_error_line_count':
            serial.count('AMD ERROR! Failed to allocate'),
    }


def compare_runs(baseline, current):
    lost = []
    gained = []
    for name in STAGES:
        before = baseline.get('stages', {}).get(name, {}).get('state', 'unknown')
        after = current.get('stages', {}).get(name, {}).get('state', 'unknown')
        if before == 'observed' and after == 'not_observed':
            lost.append(name)
        if before == 'not_observed' and after == 'observed':
            gained.append(name)
    return {
        'baseline': baseline.get('run'),
        'current': current.get('run'),
        'lost_stages': lost,
        'gained_stages': gained,
        'unknown_is_not_regression': True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('baseline', type=Path)
    parser.add_argument('current', type=Path)
    args = parser.parse_args()
    before = analyze_run(args.baseline)
    after = analyze_run(args.current)
    print(json.dumps({'baseline': before, 'current': after,
                      'comparison': compare_runs(before, after)}, indent=2))


if __name__ == '__main__':
    main()
