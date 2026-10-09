#!/usr/bin/env python3
"""Read-only raw-case analysis. Writes only an exclusive derived JSON output."""
import argparse
import hashlib
import json
import math
from pathlib import Path

BASE=Path('/home/bogdan/macos-vm/run/c380-server-study')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def lines(p):
    raw=p.read_bytes()
    if raw and not raw.endswith(b'\n'):raise ValueError('incomplete JSONL: '+str(p))
    return [json.loads(x) for x in raw.splitlines() if x.strip()]
def finite(x):return type(x) in (int,float) and math.isfinite(x)
def load_case(path):
    path=path.resolve();artifacts={}
    for name in ('result.json','cleanup.json','argv.json','producer.jsonl','samples.jsonl','display-events.jsonl','qemu.log'):
        p=path/name
        if not p.is_file():raise ValueError('case incomplete: '+str(p))
        artifacts[name]=sha(p)
    result=json.loads((path/'result.json').read_text());cleanup=json.loads((path/'cleanup.json').read_text())
    if result.get('qemu_exit')!=0 or cleanup.get('stopped') is not True or cleanup.get('exit')!=0:
        raise ValueError('case cleanup not passing')
    if result.get('passed') is not True:raise ValueError('case not passing')
    argv=json.loads((path/'argv.json').read_text());wrapper=Path(argv[0])
    if wrapper.parent!=BASE or wrapper.name not in ('base-qemu','instrumented-qemu'):
        raise ValueError('unexpected selected wrapper')
    mode=wrapper.name.removesuffix('-qemu')
    config=json.loads((BASE/(mode+'-wrapper.json')).read_text())
    for k in ('qemu','library'):
        if sha(Path(config[k]))!=config[k+'_sha256']:raise ValueError('current binary identity drift')
    reports=[]
    for line in (path/'qemu.log').read_text().splitlines():
        if 'RGPU_SPICE_STUDY' not in line:continue
        if not line.startswith('RGPU_SPICE_STUDY {'):raise ValueError('invalid or interleaved diagnostic line')
        reports.append(json.loads(line.removeprefix('RGPU_SPICE_STUDY ')))
    if mode=='instrumented' and len(reports)!=1:raise ValueError('missing/duplicate study report')
    if mode=='base' and reports:raise ValueError('unexpected base study report')
    report=reports[0] if reports else None
    if report:
        required={'start_us','end_us','reported_us','draw_consumed','pending_pipe_removals','draw_copy_marshal_completed','display_write_bytes'}
        if not required.issubset(report):raise ValueError('missing report counters')
        if report.get('complete') is not True or report.get('schema')!=1:raise ValueError('incomplete study window')
        for key,value in report.items():
            if key in ('complete','schema'):continue
            if type(value) is not int or value<0:raise ValueError('invalid report counter')
        if not 0<report['start_us']<report['end_us']<=report['reported_us'] or report['end_us']-report['start_us']>120000000:
            raise ValueError('invalid report timestamps')
    producer=lines(path/'producer.jsonl');samples=lines(path/'samples.jsonl');events=lines(path/'display-events.jsonl')
    if not producer:raise ValueError('empty producer')
    for i,row in enumerate(producer):
        if row.get('sequence')!=i+1 or not finite(row.get('start')) or not finite(row.get('ack')) or row['ack']<row['start']:
            raise ValueError('producer sequence/timing invalid')
        if i and row['start']<producer[i-1]['ack']:raise ValueError('producer overlap')
    summary=dict(path=str(path),mode=mode,raw_sha256=artifacts,
        configured_identity=config,identity_scope='selected wrapper and current pinned binary hashes; not a retained per-run process-maps attestation',
        whole_run={k:result.get(k) for k in ('seconds','width','height','scale','damage','compact_band','producer_count','producer_per_second','unique','unique_per_second','invalid_after_start','snapshot_counters','widget_geometry','widget_draw_timing')},
        server_report=report)
    if report:
        start,end=report['start_us']/1e6,report['end_us']/1e6;seconds=end-start
        # Linux GLib and Python process monotonic timestamps share the host clock.
        if start<producer[0]['start'] or end>producer[-1]['ack']:
            raise ValueError('study not strictly covered by producer span')
        ack=[r for r in producer if start<=r['ack']<end]
        observed=[r for r in samples if finite(r.get('time')) and start<=r['time']<end]
        valid=[r for r in observed if r.get('valid') is True]
        invalid=[r for r in observed if r.get('valid') is not True]
        begin=[r for r in events if r.get('event')=='display-invalidate' and start<=r['host_monotonic']<end]
        complete=[r for r in events if r.get('event')=='invalidate-complete' and start<=r['host_monotonic']<end]
        unique=len({r['sequence'] for r in valid})
        summary['aligned_window']=dict(start=start,end=end,seconds=seconds,
            producer_acks=len(ack),producer_ack_rate=len(ack)/seconds,
            first_ack_sequence=ack[0]['sequence'] if ack else None,last_ack_sequence=ack[-1]['sequence'] if ack else None,
            client_valid_samples=len(valid),client_unique=unique,client_unique_rate=unique/seconds,
            first_client_sequence=valid[0]['sequence'] if valid else None,last_client_sequence=valid[-1]['sequence'] if valid else None,
            client_invalid=len(invalid),invalid_errors=[r.get('error') for r in invalid],
            invalidate_entries=len(begin),invalidate_completions=len(complete),
            server_draw_rate=report['draw_consumed']/seconds,
            server_pipe_removal_rate=report['pending_pipe_removals']/seconds,
            server_copy_marshal_rate=report['draw_copy_marshal_completed']/seconds,
            display_write_bytes_per_second=report['display_write_bytes']/seconds,
            approximate_draw_minus_removals_minus_marshals=report['draw_consumed']-report['pending_pipe_removals']-report['draw_copy_marshal_completed'],
            marshal_minus_client_samples=report['draw_copy_marshal_completed']-len(valid),
            boundary_scope='half-open host-monotonic interval; command lifecycle crosses edges, report loads/adds race; arithmetic residual is approximate, never conservation proof')
    return summary

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('cases',nargs='+',type=Path);a=p.parse_args()
    summaries=[load_case(path) for path in a.cases]
    data=dict(schema=1,fixture_sha256=sha(BASE/'fixture-used.py'),analysis_sha256=sha(Path(__file__)),scope='software TCG/qtest same-host study; counters identify observed stages, not GPU/native equivalence, scanout or root cause; GTK timing is whole-run only',cases=summaries)
    with a.output.open('x') as f:json.dump(data,f,indent=2);f.write('\n')
    for row in summaries:print(row['path'],json.dumps(row.get('aligned_window',row['whole_run']),sort_keys=True))
if __name__=='__main__':main()
