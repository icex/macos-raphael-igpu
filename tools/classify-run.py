#!/usr/bin/env python3
"""Classify sequenced critical records; never infer execution from enumeration."""
import argparse
import importlib.util
import json
from pathlib import Path
import re


def _decode_payload(build, seq, payload):
    row = dict(build=build, seq=seq, kind='other', raw=payload)
    if payload == 'BUILD: identity='+str(build):
        row['kind'] = 'build'
    elif 'HY: HWLibs hybrid trace' in payload:
        row.update(kind='route', ok='route=ok entries-match=1' in payload)
    elif 'HY: SDMA selector trace' in payload:
        row.update(kind='sdma_route', ok='route=ok entries-match=1' in payload)
    elif payload.startswith('SD: topology routes='):
        m = re.fullmatch(r'SD: topology routes=(ok|FAILED) count=(\d+) entries-match=([01])',
                         payload)
        row.update(kind='sdma_topology_route', count=int(m[2]) if m else 0,
                   ok=bool(m and m[1] == 'ok' and m[3] == '1'))
    elif payload == 'SD: topology applied: discovered=1 kept=SDMA0 removed=SDMA1 before initialize':
        row.update(kind='sdma_topology', applied=True)
    elif payload.startswith('SD: topology NOT applied:'):
        row.update(kind='sdma_topology', applied=False)
    elif m := re.fullmatch(r'SD: AMDHardware::initializeHWEngines -> (\d+) \(topology-applied=([01])\)', payload):
        row.update(kind='sdma_initialize', result=int(m[1]), applied=bool(int(m[2])))
    elif m := re.match(r'SD: one-instance start -> (\d+) \(SDMA0=\S+ SDMA1=\S+\)$', payload):
        row.update(kind='sdma_one_start', result=int(m[1]))
    elif m := re.search(r'HY: SDMA select index=(\d+) queue-type=(\d+) found=([01]) counts=(\d+),(\d+),(\d+),(\d+)', payload):
        row.update(kind='sdma_select', index=int(m[1]), queue_type=int(m[2]),
                   found=bool(int(m[3])), counts=[int(m[i]) for i in range(4,8)])
    elif m := re.search(r'submitKIQFrame -> (\d+)', payload):
        row.update(kind='kiq_submit', result=int(m[1]))
    elif m := re.search(r'waitForHwStamp\((\d+)\) -> (\d+)', payload):
        row.update(kind='kiq', stamp=int(m[1]), result=int(m[2]))
    elif m := re.search(r'HY: createHybridEngine enter: engine=(\d+) available=(\d+)', payload):
        row.update(kind='hybrid_enter', engine=int(m[1]), available=int(m[2]))
    elif m := re.search(r'HY: createHybridEngine exit: engine=(\d+) valid=(\d+) available-before=(\d+) status=(\d+)', payload):
        row.update(kind='hybrid_exit', engine=int(m[1]), arguments_valid=int(m[2]),
                   available=int(m[3]), result=int(m[4]))
    elif m := re.search(r'AMDHardware::startHWEngines -> (\d+)', payload):
        row.update(kind='engine_start', result=int(m[1]))
    elif m := re.search(r'SD: channel engine remap (\d+) -> (\d+)', payload):
        row.update(kind='sdma_engine_remap', requested=int(m[1]), selected=int(m[2]))
    elif m := re.fullmatch(r'SD: submit IB\[(\d+)\] (0x[0-9a-fA-F]+) -> (0x[0-9a-fA-F]+) recognized=([01]) entries=(\d+) changed-total=(\d+)', payload):
        row.update(kind='sdma_ib_repair', index=int(m[1]), before=int(m[2], 16),
                   after=int(m[3], 16), valid=bool(int(m[4])), entries=int(m[5]),
                   changed_total=int(m[6]), changed=int(m[6]) > 0)
    elif m := re.fullmatch(r'SD: submit vmid=(\d+) flags=(0x[0-9a-fA-F]+) entries=(\d+) valid=([01]) IB0=(0x[0-9a-fA-F]+|0) IB1=(0x[0-9a-fA-F]+|0)', payload):
        row.update(kind='sdma_submit', vmid=int(m[1]), flags=int(m[2], 16),
                   entries=int(m[3]), valid=bool(int(m[4])), ib0=int(m[5], 16),
                   ib1=int(m[6], 16))
    elif m := re.fullmatch(r'VM: invalidate hub=(\d+) vmid=(\d+) start=(0x[0-9a-fA-F]+|0) end=(0x[0-9a-fA-F]+|0) root=(0x[0-9a-fA-F]+|0) flags=(0x[0-9a-fA-F]+|0) reprogram=([01])', payload):
        row.update(kind='vm_invalidate', hub=int(m[1]), vmid=int(m[2]),
                   start=int(m[3], 16), end=int(m[4], 16), root=int(m[5], 16),
                   flags=int(m[6], 16), reprogram=bool(int(m[7])))
    elif m := re.fullmatch(r'VM: context-snapshot vmid=(\d+) root=(0x[0-9a-fA-F]+|0) ctl=(0x[0-9a-fA-F]+|0) start=(0x[0-9a-fA-F]+|0) end=(0x[0-9a-fA-F]+|0)', payload):
        row.update(kind='vm_context', vmid=int(m[1]), root=int(m[2], 16),
                   control=int(m[3], 16), start=int(m[4], 16), end=int(m[5], 16))
    elif m := re.fullmatch(r'SD: IB template (0x[0-9a-fA-F]+) -> (0x[0-9a-fA-F]+) valid=([01]) changed=([01])', payload):
        row.update(kind='sdma_ib_repair', before=int(m[1], 16), after=int(m[2], 16),
                   valid=bool(int(m[3])), changed=bool(int(m[4])))
    elif payload.startswith('XQ2: dequeue') and ('refused' in payload or 'timeout' in payload.lower()):
        row.update(kind='kiq', result=0)
    return row


def parse_serial(serial):
    records, losses, counts, raw_records, panics, hardware_timeouts = {}, [], {}, [], [], []
    raw_builds = set()
    serial = serial.replace('\r', '')
    # sercat fsyncs every append, so a concurrent reader can legitimately observe
    # the bytes in the middle of one line.  A line has no evidentiary value until
    # its newline is durable; parsing that tail can turn a replay into a conflict.
    if serial and not serial.endswith('\n'):
        serial = serial.rsplit('\n', 1)[0] + ('\n' if '\n' in serial else '')
    for line_number, line in enumerate(serial.splitlines()):
        summary = re.search(r'RGPU_RECORDS build=(\S+) count=(\d+) dropped=(\d+) truncated=(\d+)', line)
        if summary:
            counts[summary[1]] = max(counts.get(summary[1], 0), int(summary[2]))
        if summary and any(int(summary[i]) for i in (3, 4)):
            losses.append(dict(kind='capture_loss', build=summary[1], reason='overflow'))
        match = re.search(r'RGPU_EVENT build=(\S+) seq=(\d+) (.+)$', line)
        if match:
            build, seq, payload = match[1], int(match[2]), match[3]
            key = (build, seq)
            if key in records:
                if records[key]['raw'] != payload:
                    losses.append(dict(kind='capture_loss', build=build, reason='conflicting replay'))
                continue
            records[key] = _decode_payload(build, seq, payload)
            continue
        raw = re.search(r'RaphaelGPU\s+rgpu:\s*@\s+(.*)$', line)
        if raw:
            payload = raw[1]
            if m := re.fullmatch(r'BUILD: identity=(\S+)', payload):
                raw_builds.add(m[1])
            raw_records.append((line_number, payload))
        if m := re.search(r'Unexpected kernel trap number:\s*(\S+), RIP:\s*(0x[0-9a-fA-F]+), CR2:\s*(0x[0-9a-fA-F]+)', line):
            panics.append(dict(kind='guest_panic', build=None, seq=line_number, raw=line.strip(),
                               trap=m[1], rip=int(m[2], 16), cr2=int(m[3], 16)))
        if (panics and 'symbol' not in panics[-1] and
                (m := re.search(r'com\.apple\.kext\.AMDRadeonX6000\s*:\s*(\S+)\s*\+\s*(0x[0-9a-fA-F]+)', line))):
            panics[-1].update(symbol=m[1], offset=int(m[2], 16))
        if (re.search(r'HW Channel \d+ SDMA0_PAGE is occupied by channel \d+ stamp \d+', line) or
                re.search(r'Restart Channel:\s*\d+\s+SDMA0_PAGE', line)):
            hardware_timeouts.append(dict(kind='sdma_page_timeout', build=None,
                                          seq=line_number, source='raw-terminal',
                                          raw=line.strip()))
    raw_build = next(iter(raw_builds)) if len(raw_builds) == 1 else None
    if raw_build is None and len(counts) == 1:
        raw_build = next(iter(counts))
    structured_payloads = {(r['build'], r['raw']) for r in records.values()}
    seen_raw = set()
    decoded_raw = []
    for line_number, payload in raw_records:
        build_match = re.fullmatch(r'BUILD: identity=(\S+)', payload)
        build = build_match[1] if build_match else raw_build
        row = _decode_payload(build, line_number, payload)
        key = (build, payload)
        if row['kind'] == 'other' or key in seen_raw or key in structured_payloads:
            continue
        seen_raw.add(key)
        decoded_raw.append(row)
    for panic in panics:
        panic['build'] = raw_build
    for timeout in hardware_timeouts:
        timeout['build'] = raw_build
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
    # A complete structured snapshot is an immutable, sequenced prefix. Later direct
    # log lines have no record sequence and may race the next snapshot; do not splice
    # their serial line numbers into that prefix. Preserve only a terminal KIQ failure
    # which precedes a panic: it is causal ordering evidence that cannot be replayed in
    # the next snapshot once the kernel has trapped. It remains outside the structured
    # sequence and therefore cannot create synthetic capture gaps.
    terminal_live = []
    for row in decoded_raw:
        if row.get('build') not in counts:
            row['source'] = 'raw-fallback'
            terminal_live.append(row)
        elif row['kind'] in ('vm_invalidate', 'vm_context', 'sdma_submit'):
            # These records are formatted by the dedicated observation thread,
            # outside the driver callbacks. Preserve the exact live line until
            # the next immutable structured snapshot includes it.
            row['source'] = 'live-observation'
            terminal_live.append(row)
        elif (row['kind'] == 'kiq' and row.get('result') == 0 and
              any(panic['seq'] > row['seq'] for panic in panics)):
            row['source'] = 'live-terminal'
            terminal_live.append(row)
    decoded_raw = terminal_live
    if decoded_raw and raw_build not in counts:
        losses.append(dict(kind='capture_loss', build=raw_build, reason='live records only'))
    rows = sorted(list(records.values()) + decoded_raw + panics + hardware_timeouts,
                  key=lambda r: r['seq'])
    return rows + losses


def classify(manifest, events, probe):
    def verdict(name, valid=False, stage=None, next_action='repair observation before another experiment'):
        return dict(valid=valid, verdict=name, earliest_failure=stage,
                    evidence=[r.get('raw', r['kind']) for r in events], next_action=next_action)
    expected = manifest.get('build_id')
    if not expected or any(r.get('build') not in (None, expected) for r in events):
        return verdict('INVALID', stage='loaded_build')
    kinds = {kind: [r for r in events if r['kind'] == kind]
             for kind in ('build', 'route', 'kiq', 'kiq_submit', 'hybrid_enter',
                          'hybrid_exit', 'engine_start')}
    if any(not r.get('ok') for r in kinds['route']):
        return verdict('INVALID', stage='route_guards')
    if not kinds['build'] or not kinds['route']:
        return verdict('INCONCLUSIVE', stage='identity_or_route_missing')
    panics = [r for r in events if r['kind'] == 'guest_panic']
    explicit_submit = [r for r in kinds['kiq_submit']
                       if not panics or r['seq'] < panics[0]['seq']]
    live_terminal_kiq = [r for r in kinds['kiq']
                         if r.get('source') == 'live-terminal' and
                         (not panics or r['seq'] < panics[0]['seq'])]
    kiq_before_terminal = explicit_submit + live_terminal_kiq
    if not kiq_before_terminal:
        kiq_before_terminal = [
            r for r in kinds['kiq'] if not panics or r['seq'] < panics[0]['seq']]
    terminal_kiq = (max(kiq_before_terminal, key=lambda r:r['seq'])
                    if kiq_before_terminal else None)
    if terminal_kiq and terminal_kiq.get('result') == 0:
        return verdict('BASELINE_BLOCKED', True, 'kiq',
                       'repair stale KIQ/HQD state and remove lock-held diagnostics before another launch')
    if panics:
        panic = panics[0]
        if 'sdma_topology' in manifest.get('spec', {}).get('required_observations', []):
            routes = [r for r in events if r['kind'] == 'sdma_topology_route']
            applied = [r for r in events if r['kind'] == 'sdma_topology']
            initialized = [r for r in events if r['kind'] == 'sdma_initialize']
            if any(not r.get('ok') for r in routes):
                return verdict('INVALID', stage='sdma_topology_route_guard')
            if not (len(routes) == len(applied) == len(initialized) == 1 and
                    applied[0].get('applied') and initialized[0].get('applied') and
                    initialized[0].get('result') == 1 and routes[0]['seq'] < applied[0]['seq'] <
                    initialized[0]['seq'] < panic['seq']):
                return verdict('INCONCLUSIVE', stage='guest_panic_context_missing')
        symbol = panic.get('symbol', 'unknown')
        short = 'createAccelChannels' if 'createAccelChannels' in symbol else symbol
        offset = panic.get('offset')
        stage = f'guest_panic:{short}' + (f'+{offset:#x}' if offset is not None else '')
        return verdict('GUEST_PANIC', True, stage,
                       'decode the symbolicated fault and repair it offline; no retry')
    seqs = sorted(r['seq'] for r in events if 'seq' in r and
                  r.get('source') not in ('raw-terminal', 'live-observation'))
    if (any(r['kind'] == 'capture_loss' for r in events) or
            seqs != list(range(len(seqs)))):
        return verdict('INCONCLUSIVE', stage='capture_loss')
    if 'sdma_topology' in manifest.get('spec', {}).get('required_observations', []):
        routes = [r for r in events if r['kind'] == 'sdma_topology_route']
        applied = [r for r in events if r['kind'] == 'sdma_topology']
        initialized = [r for r in events if r['kind'] == 'sdma_initialize']
        one_starts = [r for r in events if r['kind'] == 'sdma_one_start']
        selections = [r for r in events if r['kind'] == 'sdma_select']
        if any(not r.get('ok') for r in routes):
            return verdict('INVALID', stage='sdma_topology_route_guard')
        if (len(routes) != 1 or len(applied) != 1 or len(initialized) != 1 or
                len(one_starts) != 1 or
                any(not r.get('applied') for r in applied + initialized)):
            return verdict('INCONCLUSIVE', stage='sdma_topology_missing')
        if any(r.get('result') == 0 for r in initialized + one_starts):
            return verdict('STARTUP_FAILED_LATER', True, 'sdma_engine_start',
                           'inspect the preserved native SDMA initialization/start failure')
        if any(r.get('index') != 0 for r in selections):
            return verdict('STARTUP_FAILED_LATER', True, 'sdma_topology_effect',
                           'the removed SDMA instance is still reaching native selection')
        sdma_events = sorted(
            (r for r in events if r['kind'] == 'sdma_select' or
             (r['kind'] in ('hybrid_enter', 'hybrid_exit') and
              r.get('engine') in (10, 11))),
            key=lambda r: r['seq'])
        expected = (
            ('hybrid_enter', 10, None),
            ('sdma_select', None, 0),
            ('hybrid_exit', 10, None),
            ('hybrid_enter', 11, None),
            ('sdma_select', None, 1),
            ('hybrid_exit', 11, None),
        )
        if len(sdma_events) != len(expected):
            return verdict('INCONCLUSIVE', stage='sdma_topology_effect_missing')
        for row, (kind, engine, queue_type) in zip(sdma_events, expected):
            if row['kind'] != kind:
                return verdict('INCONCLUSIVE', stage='sdma_topology_order')
            if engine is not None and row.get('engine') != engine:
                return verdict('INCONCLUSIVE', stage='sdma_topology_effect_missing')
            if kind == 'hybrid_enter' and row.get('available') != 1:
                return verdict('INCONCLUSIVE', stage='sdma_topology_effect_missing')
            if kind == 'hybrid_exit' and row.get('result') != 0:
                return verdict('INCONCLUSIVE', stage='sdma_topology_effect_missing')
            if kind == 'sdma_select' and not (
                    row.get('index') == 0 and row.get('queue_type') == queue_type and
                    row.get('found') and row.get('counts') == [1, 0, 0, 0]):
                return verdict('INCONCLUSIVE', stage='sdma_topology_effect_missing')
        starts = [r for r in events if r['kind'] == 'engine_start']
        if (len(starts) != 1 or not routes[0]['seq'] < applied[0]['seq'] <
                initialized[0]['seq'] < sdma_events[0]['seq'] <
                sdma_events[-1]['seq'] < one_starts[0]['seq'] < starts[0]['seq']):
            return verdict('INCONCLUSIVE', stage='sdma_topology_order')
        if 'sdma_channel_remap' in manifest.get('spec', {}).get('required_observations', []):
            expected_route_count = (7 if any(name in
                                    manifest.get('spec', {}).get('required_observations', [])
                                    for name in ('sdma_ib_address_repair', 'sdma_vm_context')) else 6)
            if routes[0].get('count') != expected_route_count:
                return verdict('INVALID', stage='sdma_channel_route_guard')
            remaps = [r for r in events if r['kind'] == 'sdma_engine_remap']
            if not remaps:
                return verdict('INCONCLUSIVE', stage='sdma_channel_remap_missing')
            if any(r.get('requested') != 2 or r.get('selected') != 1 for r in remaps):
                return verdict('STARTUP_FAILED_LATER', True, 'sdma_channel_remap',
                               'inspect the unexpected SDMA channel mapping')
            if not initialized[0]['seq'] < remaps[0]['seq'] < one_starts[0]['seq']:
                return verdict('INCONCLUSIVE', stage='sdma_channel_remap_order')
        if 'sdma_vm_context' in manifest.get('spec', {}).get('required_observations', []):
            submits = [r for r in events if r['kind'] == 'sdma_submit' and
                       r.get('valid') and r.get('vmid') == 2]
            invalidates = [r for r in events if r['kind'] == 'vm_invalidate' and
                           r.get('hub') == 0 and r.get('vmid') == 2]
            contexts = [r for r in events if r['kind'] == 'vm_context' and
                        r.get('vmid') == 2]
            if not submits or not invalidates or not contexts:
                return verdict('INCONCLUSIVE', stage='sdma_vm_context_missing')
            # The hardware context is read later by a dedicated worker so the
            # driver callback never performs MMIO or serial formatting while a
            # caller lock may be held. Treat it as an asynchronous snapshot:
            # require a coherent request/snapshot chain that actually contains
            # one of the submitted GPU virtual addresses. Mere coexistence of
            # three unrelated records cannot validate this observation.
            coherent = False
            for submit in submits:
                addresses = [submit.get('ib0', 0), submit.get('ib1', 0)]
                for address in (value for value in addresses if value):
                    for request in invalidates:
                        if (not request.get('reprogram') or not request.get('root') or
                                not request.get('start') <= address <= request.get('end')):
                            continue
                        if any(context.get('root') == request.get('root') and
                               context.get('start') <= address <= context.get('end')
                               for context in contexts):
                            coherent = True
                            break
                    if coherent:
                        break
                if coherent:
                    break
            if not coherent:
                return verdict('INCONCLUSIVE', stage='sdma_vm_context_mismatch')
        if any(r['kind'] == 'sdma_page_timeout' for r in events):
            return verdict('SDMA_PAGE_TIMEOUT', True, 'sdma0_page',
                           'inspect the indirect packet and SDMA VM state; do not retry unchanged')
        if 'sdma_ib_address_repair' in manifest.get('spec', {}).get('required_observations', []):
            repairs = [r for r in events if r['kind'] == 'sdma_ib_repair' and
                       r.get('valid') and r.get('changed')]
            if not repairs:
                return verdict('INCONCLUSIVE', stage='sdma_ib_address_repair_missing')
            if any(r['seq'] <= starts[0]['seq'] for r in repairs):
                return verdict('INCONCLUSIVE', stage='sdma_ib_address_repair_order')
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
    if any(r['kind'] == 'sdma_page_timeout' for r in events):
        return verdict('SDMA_PAGE_TIMEOUT', True, 'sdma0_page',
                       'inspect the repaired indirect packet and SDMA VM state; do not retry unchanged')
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
