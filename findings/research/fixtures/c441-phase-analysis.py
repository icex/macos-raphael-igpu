#!/usr/bin/env python3
"""Offline source-overlap phase analysis; preserves original trailing invalids.
No VM control. Decoded IDs only, not GL frame/scanout measurement.
"""
import argparse,bisect,hashlib,json,re
from pathlib import Path
parser=argparse.ArgumentParser();parser.add_argument('--run-dir',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args();report={'scope':'Same-boot sequential native controls; complete phases1..4 with1second hostinterior margin. Trailinginvalids retained; no100second zeroinvalid or scanoutFPS claim.'}
for case in ('a','b'):
 src=args.run_dir/f'c441-fourk-{case}-source.txt';raw=args.run_dir/f'c441-fourk-{case}-cadence.jsonl';paths=(src,raw)
 hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
 source=src.read_text();assert f'TOKEN nonce=441{case}0123456789ab duration=110 logical=1920x1080 scale=2.0' in source
 assert 'TOKEN_DONE' in source and 'MIXED_END' in source
 starts=[int(x) for x in re.findall(r'^MIXED_PHASE .*first_completed_draw=(\d+)',source,re.M)]
 assert starts==sorted(set(starts)) and len(starts)==6
 pairs=[(int(n),float(t)) for n,t in re.findall(r'^DRAW (\d+) ([0-9.]+)$',source,re.M)]
 assert all(a[0]<b[0] and a[1]<=b[1] for a,b in zip(pairs,pairs[1:]));draws=dict(pairs)
 rows=[json.loads(x) for x in raw.read_text().splitlines()];finish=next(x for x in rows if x.get('event')=='finish');assert finish['reason']=='completed'
 samples=[x for x in rows if x.get('event')=='sample'];valid=[x for x in samples if x.get('valid')];bad=[x for x in samples if not x.get('valid')]
 assert all(x['sequence'] in draws and (x['width'],x['height'],x['scale'])==(3840,2160,2) for x in valid)
 assert all(x['host_monotonic']>valid[-1]['host_monotonic'] and x['error']=='missing token border; missing token border' for x in bad)
 phases=[]
 for phase in (1,2,3,4):
  ss=[x for x in valid if bisect.bisect_right(starts,x['sequence'])-1==phase];lo=ss[0]['host_monotonic']+1;hi=ss[-1]['host_monotonic']-1;assert hi-lo>10
  inside=[x for x in ss if lo<=x['host_monotonic']<=hi];ds=[t for n,t in pairs if bisect.bisect_right(starts,n)-1==phase]
  phases.append(dict(index=phase,kind='full-field' if phase%2 else 'localized',decoded_unique_per_second=len({x['sequence'] for x in inside})/(hi-lo),observed_seconds=hi-lo,source_draw_per_second=(len(ds)-1)/(ds[-1]-ds[0])))
 assert hashes=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
 report[case]=dict(renderer='GL' if case=='a' else 'Cairo',phases=phases,trailing_invalid=len(bad),last_valid_id=valid[-1]['sequence'],source_completed_id=max(draws),within_source_invalid=0,input_sha256=hashes)
with args.output.open('x') as stream:json.dump(report,stream,indent=2);stream.write('\n')
