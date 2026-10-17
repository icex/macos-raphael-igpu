#!/usr/bin/env python3
"""Offline strict analysis; explicit independent window ranges exclude boot.
No clock alignment is inferred between guest uptime and host monotonic time.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

U64 = (1 << 64) - 1
HOST = 'bochs-snapshot-timing '
GUEST = 'RaphaelConsole:T '


def windows(text):
    if not re.fullmatch(r'[0-9]+:[0-9]+', text):
        raise argparse.ArgumentTypeError('expected inclusive FIRST:LAST')
    lo, hi = map(int, text.split(':'))
    if not 1 <= lo <= hi <= 128:
        raise argparse.ArgumentTypeError('window range must be within1..128')
    return lo, hi


def number(value):
    if not re.fullmatch(r'[0-9]+', value) or not 0 <= int(value) <= U64:
        raise ValueError('invalid uint64')
    return int(value)


def pair(value):
    items = value.split('/')
    if len(items) != 2:
        raise ValueError('expected total/max pair')
    total, maximum = map(number, items)
    if maximum > total:
        raise ValueError('maximum exceeds total')
    return total, maximum


def analyze(text, kind, selected, geometry, minimum):
    marker = HOST if kind == 'host' else GUEST
    window_key = 'window' if kind == 'host' else 'w'
    geometry_key = 'geometry' if kind == 'host' else 'g'
    rows, errors, excluded = {}, [], []
    for lineno, raw in enumerate(text.splitlines(), 1):
        if marker not in raw:
            continue
        tail = raw.split(marker, 1)[1].strip()
        hint = re.search(r'(?:^| )' + window_key + r'=([0-9]+)(?: |$)', tail)
        if hint and not selected[0] <= int(hint[1]) <= selected[1]:
            continue
        try:
            tokens = tail.split()
            fields = {}
            for token in tokens:
                if token.count('=') != 1:
                    raise ValueError('malformed/truncated token')
                key, value = token.split('=')
                if key in fields:
                    raise ValueError('duplicate field')
                fields[key] = value
            win = number(fields[window_key])
            if not selected[0] <= win <= selected[1]:
                continue
            geo = fields[geometry_key]
            if not re.fullmatch(r'[0-9]+x[0-9]+', geo):
                raise ValueError('invalid geometry')
            if geo != geometry:
                excluded.append({'line': lineno, 'window': win, 'reason': 'other geometry', 'geometry': geo})
                continue
            if kind == 'host':
                expected = {'window','start_us','end_us','geometry','commits','alloc_calls','copy_calls',
                            'free_calls','pending_present','pending_null','alloc_us','copy_us','free_us',
                            'dropped_geometry','saturated'}
            else:
                part = number(fields['p'])
                if part not in (1, 2):
                    raise ValueError('invalid guest part')
                expected = {'w','dt','g','n','sat','p'} | ({'l','c','gmm'} if part == 1 else {'d','a','drop'})
            if set(fields) != expected:
                raise ValueError('missing or unexpected fields')
            key = (win, 0 if kind == 'host' else part)
            if key in rows:
                raise ValueError('duplicate row')
            rows[key] = (fields, lineno)
        except (ValueError, KeyError) as exc:
            errors.append({'line': lineno, 'reason': str(exc), 'raw': tail})
    samples = []
    for win in range(selected[0], selected[1] + 1):
        try:
            parts = [rows[(win, p)] for p in ([0] if kind == 'host' else [1, 2])]
            f = parts[0][0]
            lines = [p[1] for p in parts]
            if kind == 'guest':
                second = parts[1][0]
                if any(f[k] != second[k] for k in ('w','dt','g','n','sat')):
                    raise ValueError('guest metadata differs between parts')
                f = dict(f, **{k: second[k] for k in ('d','a','drop')})
                count = number(f['n'])
                if number(f['sat']) != 0 or number(f['drop']) != 0:
                    raise ValueError('saturated or dropped geometry')
                if number(f['dt']) < 5000000000:
                    raise ValueError('short guest report window')
                metrics = {name: pair(f[key]) for name, key in
                           [('lock','l'),('copy_fence','c'),('geometry_mmio','gmm'),('doorbell','d'),('ack_checks','a')]}
                extra = {'elapsed_ns': number(f['dt'])}
            else:
                count = number(f['commits'])
                if number(f['saturated']) != 0 or number(f['dropped_geometry']) != 0:
                    raise ValueError('saturated or dropped geometry')
                if any(number(f[k]) != count for k in ('alloc_calls','copy_calls','free_calls')):
                    raise ValueError('completed stage call counts differ')
                present, null = number(f['pending_present']), number(f['pending_null'])
                if present + null != count:
                    raise ValueError('pending counts do not conserve commits')
                start, end = number(f['start_us']), number(f['end_us'])
                if end < start or end - start < 5000000:
                    raise ValueError('invalid host monotonic window')
                metrics = {name: pair(f[key]) for name, key in
                           [('allocation','alloc_us'),('copy_including_first_touch','copy_us'),('pending_free','free_us')]}
                extra = {'start_us': start, 'end_us': end, 'pending_present': present, 'pending_null': null,
                         'alloc_calls': count, 'copy_calls': count, 'free_calls': count}
            if not count or any(total > maximum * count for total, maximum in metrics.values()):
                raise ValueError('impossible total/max/count')
            if count < minimum:
                excluded.append({'window': win, 'lines': lines, 'count': count, 'reason': 'below minimum count'})
                continue
            samples.append(dict(window=win, lines=lines, count=count, metrics=metrics, **extra))
        except (ValueError, KeyError) as exc:
            errors.append({'window': win, 'reason': 'missing selected row/part' if isinstance(exc, KeyError) else str(exc)})
    if not samples:
        errors.append({'reason': 'no qualifying selected windows'})
    result = dict(valid=not errors, clock='host monotonic microseconds' if kind == 'host' else 'guest uptime nanoseconds',
                  selected_windows=list(selected), geometry=geometry, minimum_count=minimum,
                  errors=errors, excluded=excluded, samples=samples)
    # Fail closed: never emit seemingly usable summary from ambiguous rows.
    if errors:
        return result
    count = sum(s['count'] for s in samples)
    unit_to_ns = 1000 if kind == 'host' else 1
    aggregate = {'commits': count, 'windows': len(samples), 'metrics': {}}
    for name in samples[0]['metrics']:
        total = sum(s['metrics'][name][0] for s in samples) * unit_to_ns
        maximum = max(s['metrics'][name][1] for s in samples) * unit_to_ns
        aggregate['metrics'][name] = dict(total_ns=total, mean_ms=total/count/1e6, maximum_ms=maximum/1e6)
    if kind == 'host':
        for k in ('alloc_calls','copy_calls','free_calls','pending_present','pending_null'):
            aggregate[k] = sum(s[k] for s in samples)
        aggregate['pending_present_ratio'] = aggregate['pending_present']/count
    result['aggregate'] = aggregate
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--host', type=Path, required=True)
    p.add_argument('--guest', type=Path, required=True)
    p.add_argument('--host-windows', type=windows, required=True)
    p.add_argument('--guest-windows', type=windows, required=True)
    p.add_argument('--geometry', default='3840x2160')
    p.add_argument('--min-count', type=int, default=100)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    if a.min_count < 1 or not re.fullmatch(r'[0-9]+x[0-9]+', a.geometry):
        p.error('positive min-count and WIDTHxHEIGHT required')
    result = {'schema': 1, 'scope': 'explicit independent steady-geometry windows; no host/guest clock subtraction', 'inputs': {}}
    for kind in ('host','guest'):
        path = getattr(a, kind)
        before = path.stat()
        data = path.read_bytes()
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise RuntimeError('input changed during read')
        result['inputs'][kind] = {'path': str(path.resolve()), 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
        result[kind] = analyze(data.decode('utf-8', errors='strict'), kind,
                               getattr(a, kind+'_windows'), a.geometry, a.min_count)
    result['valid'] = result['host']['valid'] and result['guest']['valid']
    a.output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({k: result[k] for k in ('valid','inputs')}, indent=2))
    return 0 if result['valid'] else 1

if __name__ == '__main__':
    raise SystemExit(main())
