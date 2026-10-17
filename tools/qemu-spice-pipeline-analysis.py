#!/usr/bin/env python3
"""Associate opt-in QEMU timing with phase interiors using host token samples.

Trace timestamps and client samples must have verified equal monotonic offsets.
Guest draw times are never subtracted from host times. Counts are command events,
not full frames, integrity or scanout. Trace output adds diagnostic overhead.
Phase bounds are inferred from client IDs with a one-second interior margin;
upstream phase assignment is uncertain if pipeline delay exceeds that margin.
Costs are inclusive wall times, not CPU self-time; create_us overlaps other stages.
No command ID links server events to a specific token or proves frame latency.
"""
import argparse
import bisect
import collections
import hashlib
import json
import math
from pathlib import Path
import re
import statistics

EVENT = re.compile(r'\b(qemu_spice_(?:copy_timing|diff_timing|refresh_timing|command_dequeue))\s+(.*)')
REQUIRED = {
    'copy_timing': ('start_us', 'w', 'h', 'alloc_us', 'mirror_us', 'bitmap_us'),
    'diff_timing': ('start_us', 'w', 'h', 'changed', 'diff_us'),
    'refresh_timing': ('start_us', 'hw_us', 'create_us', 'busy'),
    'command_dequeue': ('at_us', 'w', 'h'),
}


def parse_trace(text):
    rows = []
    for line in text.splitlines():
        match = EVENT.search(line)
        if not match:
            continue
        event = match[1].removeprefix('qemu_spice_')
        fields = dict(re.findall(r'(\w+)=(-?\d+)\b', match[2]))
        if not {'qid', *REQUIRED[event]} <= fields.keys():
            raise ValueError('incomplete timing record')
        value = {key: int(val) for key, val in fields.items()}
        if any(val < 0 for key, val in value.items() if key != 'changed'):
            raise ValueError('negative timing or geometry')
        if event == 'diff_timing' and value['changed'] not in (-1, 0, 1):
            raise ValueError('invalid diff result')
        if event == 'refresh_timing' and value['busy'] not in (0, 1):
            raise ValueError('invalid queue state')
        value.update(event=event, host_seconds=value.get('start_us',value.get('at_us'))/1e6)
        rows.append(value)
    if not rows:
        raise ValueError('no timing records')
    return rows


def distribution(values):
    if not values:
        return None
    values = sorted(values)
    return dict(count=len(values), mean_us=statistics.mean(values),
                median_us=statistics.median(values),
                p95_us=values[min(len(values)-1,math.ceil(.95*len(values))-1)],
                max_us=max(values), total_us=sum(values))


def analyze(trace, cadence, source, margin=1.0):
    token = re.search(r'^TOKEN nonce=(\w+) duration=\d+ logical=(3840x2160|1920x1080) scale=([12])\.0$',source,re.M)
    if not token:
        raise ValueError('requires actual 4K source')
    scale = int(token[3])
    if (token[2], scale) not in [('3840x2160',1),('1920x1080',2)]:
        raise ValueError('inconsistent logical/backing geometry')
    draws = {int(seq) for seq in re.findall(r'^DRAW (\d+) [0-9.]+$',source,re.M)}
    phases = [dict(re.findall(r'(\w+)=([^ ]+)',line)) for line in source.splitlines()
              if line.startswith('MIXED_PHASE ')]
    starts = [int(row['first_completed_draw']) for row in phases]
    if not starts or starts != sorted(set(starts)):
        raise ValueError('invalid source phases')
    records = [json.loads(line) for line in cadence.splitlines()]
    begin = next(row for row in records if row.get('event') == 'start')
    finish = next(row for row in records if row.get('event') == 'finish')
    if begin['nonce'] != token[1] or finish['nonce'] != token[1] or finish['reason'] != 'completed':
        raise ValueError('nonce mismatch or incomplete observer')
    samples = [row for row in records if row.get('event') == 'sample']
    first_valid = next((i for i,row in enumerate(samples) if row.get('valid')),None)
    if first_valid is None or any(not row.get('valid') for row in samples[first_valid:]):
        raise ValueError('requires zero post-start invalid control')
    groups = collections.defaultdict(list)
    for row in records:
        if row.get('event') != 'sample' or not row.get('valid'):
            continue
        if row['sequence'] not in draws or row['scale'] != scale or (row['width'],row['height']) != (3840,2160):
            raise ValueError('unverified token/source geometry')
        index = bisect.bisect_right(starts,row['sequence'])-1
        if index < 0:
            raise ValueError('token before first completed phase')
        groups[index].append(row)
    rows = parse_trace(trace)
    if any(row['qid'] != 0 for row in rows):
        raise ValueError('requires only expected primary qid=0')
    def end_time(row):
        duration = sum(row.get(key,0) for key in
                       ('alloc_us','mirror_us','bitmap_us','diff_us','hw_us','create_us'))
        return row['host_seconds'] + duration/1e6
    output = []
    for index, samples in sorted(groups.items()):
        lo = samples[0]['host_monotonic']+margin
        hi = samples[-1]['host_monotonic']-margin
        if hi-lo < 10:
            continue  # short final phase is not a throughput control
        selected = [row for row in rows if lo <= row['host_seconds'] <= hi]
        inside = [row for row in selected if end_time(row) <= hi]
        byevent = {event:[row for row in inside if row['event']==event] for event in REQUIRED}
        if any(not values for values in byevent.values()):
            raise ValueError('trace window missing a stage')
        client = [row for row in samples if lo <= row['host_monotonic'] <= hi]
        output.append(dict(index=int(phases[index]['index']),kind=phases[index]['kind'],
                           host_bounds_seconds=[lo,hi],span_seconds=hi-lo,
                           excluded_interval_crossing=len(selected)-len(inside),
                           client_sample_count=len(client),
                           observer_duplicates=finish['duplicates'],
                           client_unique_ids=len({row['sequence'] for row in client}),
                           client_ids_per_second=len({row['sequence'] for row in client})/(hi-lo),
                           event_counts={event:len(v) for event,v in byevent.items()},
                           event_rates={event:len(v)/(hi-lo) for event,v in byevent.items()},
                           queue_busy=sum(row['busy'] for row in byevent['refresh_timing']),
                           diff_results=dict(collections.Counter(row['changed'] for row in byevent['diff_timing'])),
                           update_geometries=dict(collections.Counter(f"{r['w']}x{r['h']}" for r in byevent['copy_timing'])),
                           timings={key:distribution([row[key] for row in inside if key in row])
                                    for key in ('diff_us','alloc_us','mirror_us','bitmap_us','hw_us','create_us')}))
    if not output:
        raise ValueError('no complete phase interiors')
    return output


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('trace','cadence','source','output'):
        p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--shared-host-clock-receipt',type=Path,required=True)
    a=p.parse_args()
    receipt=json.loads(a.shared_host_clock_receipt.read_text())
    if not receipt.get('shared_monotonic_clock') or not receipt.get('run_id') or not receipt.get('cid'):
        p.error('shared host monotonic clock proof required')
    paths=[a.trace,a.cadence,a.source,a.shared_host_clock_receipt]
    hashes={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    rows=analyze(a.trace.read_text(),a.cadence.read_text(),a.source.read_text())
    if hashes!={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}:
        raise ValueError('input changed during analysis')
    with a.output.open('x') as stream:
        json.dump(dict(schema=1,identity=receipt,input_sha256=hashes,phases=rows,
                       scope=__doc__),stream,indent=2);stream.write('\n')
    for row in rows:
        print(row['index'],row['kind'],row['event_rates'],'client',row['client_ids_per_second'],
              'busy',row['queue_busy'],'costs', {k:v['mean_us'] for k,v in row['timings'].items() if v})
if __name__=='__main__':
    main()
