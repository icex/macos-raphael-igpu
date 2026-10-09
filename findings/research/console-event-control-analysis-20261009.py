#!/usr/bin/env python3
"""Offline common producer-interior analysis for retained candidate378 controls."""
import argparse,hashlib,json,statistics
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--run-dir',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();rows=[]
for case in ('count','roi','split'):
 d=a.run_dir/f'c378-oracle-{case}'
 def read(name):return [json.loads(x) for x in (d/name).read_text().splitlines()]
 producer=read('producer.jsonl');events=read('display-events.jsonl');samples=read('samples.jsonl')
 lo=producer[0]['ack']+.5;hi=producer[-1]['ack']-.5;assert hi>lo
 ev=[x for x in events if x['event']=='display-invalidate' and lo<=x['host_monotonic']<=hi]
 indices={x['index'] for x in ev};ends=[x for x in events if x['event']=='invalidate-complete' and x['index'] in indices]
 assert len(ends)==len(ev)
 ss=[x for x in samples if lo<=x['time']<=hi];good=[x for x in ss if x['valid']];unique={x['sequence'] for x in good}
 result=json.loads((d/'result.json').read_text());assert result['passed'] and result['qemu_exit']==0
 rows.append(dict(case=case,geometry=[640,480],producer_interior_host=[lo,hi],span=hi-lo,producer_ack_count=sum(lo<=x['ack']<=hi for x in producer),invalidations=len(ev),invalidation_per_second=len(ev)/(hi-lo),decoded_valid=len(good),unique_ids=len(unique),invalid_samples=len(ss)-len(good),unique_per_second=len(unique)/(hi-lo) if case!='count' else None,callback_mean_ms=1000*statistics.mean(x['callback_seconds'] for x in ends),callback_max_ms=1000*max(x['callback_seconds'] for x in ends),result=result,hashes={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in d.iterdir() if f.is_file()}))
value=dict(scope='Sequential640x480 TCG controls. Same relative producer interval excluding first/last0.5s, not identical walltime. Startup token0 excluded. Split mode intentionally changes producer cadence; no native throughput/FPS claim.',rows=rows)
with a.output.open('x') as f:json.dump(value,f,indent=2);f.write('\n')
for x in rows:print(x['case'],x['span'],x['invalidation_per_second'],x['unique_ids'],x['invalid_samples'],x['callback_mean_ms'])
