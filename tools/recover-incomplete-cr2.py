#!/usr/bin/env python3
"""Create and, after review, execute a recovery-only incomplete-CR2 proof."""
import argparse, fcntl, hashlib, importlib.util, json, os, re, stat, sys, time, zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PINNED_FILES = ('manifest.json', 'critical.txt', 'serial.txt', 'recovery.json',
                'verdict.json', 'host-after.json', 'shutdown.json', 'supervision.json')

def sha(data): return hashlib.sha256(data).hexdigest()

def load(name):
    path = ROOT/'tools'/(name+'.py')
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module

def recovery_lease_seed(serial, build, replay):
    if len(serial.encode()) > replay.MAX_INPUT_BYTES: raise ValueError('CR2 input bound')
    snapshots={}; ends={}; corrupt=[]; latest_snapshot=-1; last_key={}
    for number,line in enumerate(serial.replace('\r','').splitlines(),1):
        if 'RGPU_CR2' not in line and 'RGPU_END2' not in line: continue
        if len(line.encode()) > replay.MAX_PHYSICAL_LINE_BYTES:
            corrupt.append({'line':number,'reason':'physical line bound'}); continue
        end=replay._END.fullmatch(line)
        if end:
            if end[1] != build: raise ValueError('foreign recovery transport build')
            snap=int(end[2],16); value=tuple(int(end[i],16) for i in range(3,11))
            if snap < latest_snapshot: raise ValueError('stale snapshot in recovery transport')
            latest_snapshot=max(latest_snapshot,snap)
            if value[2] or value[3]: raise ValueError('snapshot END reports loss')
            if snap in ends and ends[snap] != value: raise ValueError('conflicting END')
            ends[snap]=value; continue
        match=replay._CHUNK.fullmatch(line)
        if not match:
            corrupt.append({'line':number,'reason':'malformed transport'}); continue
        if match[1] != build: raise ValueError('foreign recovery transport build')
        snap,record,part,parts,size,checksum=(int(match[i],16) for i in range(2,8))
        if snap < latest_snapshot: raise ValueError('stale snapshot in recovery transport')
        if snap > latest_snapshot: latest_snapshot=snap
        if snap in ends: raise ValueError('recovery chunk appears after snapshot END')
        hx=match[8]
        if (record >= replay.MAX_RECORDS or not 1 <= parts <= replay.MAX_PARTS or
                part >= parts or not 1 <= size <= replay.MAX_CHUNK_BYTES or
                len(hx) != size*2 or (part+1 < parts and size != replay.MAX_CHUNK_BYTES)):
            corrupt.append({'line':number,'reason':'invalid chunk bounds'}); continue
        payload=bytes.fromhex(hx)
        if zlib.crc32(replay._chunk_domain(build,snap,record,part,parts,payload)) & 0xffffffff != checksum:
            corrupt.append({'line':number,'reason':'chunk checksum'}); continue
        row=snapshots.setdefault(snap,{}); key=(record,part); value=(parts,payload)
        prior_key=last_key.get(snap)
        if prior_key is not None and key < prior_key and key not in row:
            raise ValueError('noncanonical recovery chunk order')
        if key in row and row[key] != value: raise ValueError('conflicting chunk')
        if {v[0] for (r,_),v in row.items() if r == record} - {parts}:
            raise ValueError('conflicting part counts')
        row[key]=value
        if prior_key is None or key > prior_key: last_key[snap]=key
    wanted=('XH2 OWNED ','XH2 POOL state=ACTIVE ','XH3 LIFETIME state=VALID ')
    found={prefix:[] for prefix in wanted}; partial=[]; inventory=[]
    for snap,row in sorted(snapshots.items()):
        records={}
        for (record,part),value in row.items(): records.setdefault(record,{})[part]=value
        for record,pieces in sorted(records.items()):
            counts={v[0] for v in pieces.values()}; total=next(iter(counts)) if len(counts)==1 else None
            complete=total is not None and set(pieces)==set(range(total))
            prefix=[]
            for part in range(total or 0):
                if part not in pieces: break
                prefix.append(pieces[part][1])
            beginning=b''.join(prefix)
            inventory.append({'snapshot':snap,'record':record,'parts_present':sorted(pieces),
                              'parts_expected':total,'complete':complete})
            if not complete:
                if beginning.startswith((b'XH2',b'XH3')): partial.append([snap,record])
                continue
            raw=b''.join(pieces[i][1] for i in range(total))
            if len(raw)>replay.MAX_RECORD_BYTES or any(c<0x20 or c>0x7e for c in raw):
                raise ValueError('malformed recovery record bytes')
            text=raw.decode('ascii')
            if text.startswith(('XH2','XH3')):
                if text.startswith(('XH2 ABORT','XH3 LIFETIME state=ABORT')):
                    raise ValueError('recovery seed contains ABORT')
                matches=[p for p in wanted if text.startswith(p)]
                if len(matches)!=1: raise ValueError('malformed recovery-family record')
                found[matches[0]].append((snap,record,text))
    if partial: raise ValueError('partial recovery-family record')
    records=[]; sets=[]
    for prefix in wanted:
        values=found[prefix]
        if not values: raise ValueError('missing '+prefix.strip())
        if len({v[2] for v in values})!=1: raise ValueError('conflicting recovery records')
        if len({v[1] for v in values})!=1: raise ValueError('recovery record index changed')
        records.append(values[0][2]); sets.append({v[0] for v in values})
    shared=sorted(set.intersection(*sets))
    if not shared: raise ValueError('recovery records do not share a snapshot')
    return {'schema':1,'build':build,'records':records,'source_snapshots':shared,
            'corrupt':corrupt,'partial_recovery_records':partial,'record_inventory':inventory,
            'snapshot_ends':{str(k):list(v) for k,v in sorted(ends.items())}}

def write_once(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True); stream.write('\n')
        stream.flush(); os.fsync(stream.fileno())
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(descriptor)
    finally: os.close(descriptor)

def validate_lifetime(record, evidence):
    match = re.fullmatch(r'XH3 LIFETIME state=VALID nonce=([0-9a-f]{16})_'
                         r'([0-9a-f]{16}) checksum=0x([0-9a-f]{16})', record)
    lifetime = load('recovery_lifetime_v3')
    marker = lifetime.make_valid_marker(evidence.descriptor.pack(),
                                        evidence.pool_status.pack())
    expected = (f'{marker.nonce_lo:016x}', f'{marker.nonce_hi:016x}',
                f'{marker.checksum:016x}')
    if match is None or match.groups() != expected:
        raise ValueError('recovery lifetime record binding or checksum mismatch')

def receipt_errors(experiment, receipt, proof, manifest, vm, manifest_path=None):
    return sorted(set(experiment.validate_recovery_receipt_v6(
        receipt,proof['boot_id'],proof['run_id'],
        proof['current_recovery_helpers_sha256'])+
        experiment.validate_reuse_receipt(
            receipt,proof['boot_id'],proof['run_id'],vm,manifest=manifest,
            manifest_path=manifest_path)))

def build_proof(run_dir):
    run_dir = run_dir.resolve()
    raw={}
    for name in PINNED_FILES:
        path=run_dir/name; mode=path.lstat().st_mode
        if not stat.S_ISREG(mode) or path.is_symlink(): raise ValueError(name+' is not a regular file')
        raw[name]=path.read_bytes()
    manifest = json.loads(raw['manifest.json'])
    recovery = json.loads(raw['recovery.json']); verdict = json.loads(raw['verdict.json'])
    if (manifest.get('critical_replay_schema') != 2 or
            manifest.get('recovery_lease_schema') != 3 or
            manifest.get('recovery_critical_replay_tolerance') != 'terminal-prefix-open'):
        raise ValueError('manifest does not select schema-3 open-prefix recovery')
    experiment=load('experiment'); experiment.validate_manifest_replay_contract(manifest)
    transport=manifest.get('critical_replay_transport')
    if (not isinstance(transport,dict) or transport.get('kind')!='isa-serial' or
            transport.get('version')!=1 or transport.get('index')!=1 or
            transport.get('capture')!='critical.txt'):
        raise ValueError('manifest critical transport is not the dedicated producer')
    if (recovery.get('status') != 'failed' or verdict.get('verdict') != 'INVALID' or
            'capture_loss' not in verdict.get('evidence', [])):
        raise ValueError('run is not a frozen failed-recovery INVALID capture')
    replay = load('critical-replay')
    critical = raw['critical.txt'].decode('utf-8', errors='strict')
    if not experiment.critical_uart_ready(critical,manifest['build_id']):
        raise ValueError('dedicated critical producer readiness is absent or conflicting')
    try: replay.parse(critical, manifest['build_id'])
    except replay.CriticalReplayError as error: strict_error = str(error)
    else: raise ValueError('strict replay unexpectedly succeeds')
    seed = recovery_lease_seed(critical, manifest['build_id'], replay)
    vfio = load('vfio-recover')
    evidence = vfio.parse_v2_lease_records(seed['records'][:2], manifest['run_id'])
    if evidence.pool_status is None:
        raise ValueError('recovery seed lacks ACTIVE pool evidence')
    validate_lifetime(seed['records'][2], evidence)
    helper_hashes = vfio.current_recovery_helpers_sha256(3)
    sources = ('tools/critical-replay.py', 'tools/vfio-recover.py',
               'tools/recovery_lease_v2.py', 'tools/recovery_lifetime_v3.py',
               'tools/kiq-recovery-proof.py', 'tools/experiment.py',
               'tools/recover-incomplete-cr2.py')
    return {'schema':1, 'kind':'incomplete-cr2-recovery-only-proof',
            'run_id':manifest['run_id'], 'boot_id':manifest['boot_id'],
            'build_id':manifest['build_id'], 'run_directory':str(run_dir),
            'frozen_sha256':{name:sha(data) for name,data in raw.items()},
            'source_sha256':{name:sha((ROOT/name).read_bytes()) for name in sources},
            'manifest_recovery_helpers_sha256':manifest['recovery_helpers_sha256'],
            'current_recovery_helpers_sha256':helper_hashes,
            'strict_replay_error':strict_error, 'lease_seed':seed,
            'classification_unchanged':'INVALID', 'authorizes_launch':False}

def execute_once(directory, proof_path, reviewed_hash, recover, validate,
                 canonical_attempt=None):
    if proof_path.is_symlink() or not stat.S_ISREG(proof_path.lstat().st_mode):
        raise ValueError('reviewed proof is not a regular file')
    if not re.fullmatch(r'[0-9a-f]{64}', reviewed_hash or '') or \
            sha(proof_path.read_bytes()) != reviewed_hash:
        raise ValueError('reviewed proof SHA-256 mismatch')
    attempt=directory/'attempt.json'; result_path=directory/'result.json'
    canonical_attempt = attempt if canonical_attempt is None else canonical_attempt
    canonical_attempt.parent.mkdir(parents=True,exist_ok=True)
    if canonical_attempt.exists(): raise FileExistsError(str(canonical_attempt))
    if attempt.exists(): raise FileExistsError(str(attempt))
    if result_path.exists(): raise FileExistsError(str(result_path))
    marker={'schema':1,'kind':'incomplete-cr2-recovery-attempt',
            'proof_sha256':reviewed_hash,'created_epoch':time.time()}
    write_once(canonical_attempt,marker)
    if attempt != canonical_attempt: write_once(attempt,marker)
    receipt=None
    try:
        receipt=recover(); errors=validate(receipt)
        if errors:
            result={'schema':1,'status':'failed','proof_sha256':reviewed_hash,
                    'error':'recovery receipt validation: '+','.join(errors),
                    'recovery':receipt}
        else:
            result={'schema':1, 'status':'complete','proof_sha256':reviewed_hash,
                    'recovery':receipt}
    except BaseException as error:
        result={'schema':1, 'status':'failed', 'proof_sha256':reviewed_hash,
                'error':type(error).__name__+': '+str(error)}
    write_once(result_path,result); return result

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--vm-dir',required=True,type=Path); ap.add_argument('--run-dir',required=True,type=Path)
    ap.add_argument('--evidence-dir',required=True,type=Path); ap.add_argument('--execute',action='store_true')
    ap.add_argument('--reviewed-proof-sha256'); args=ap.parse_args()
    proof=build_proof(args.run_dir); proof_path=args.evidence_dir.resolve()/'proof.json'
    run_resolved=args.run_dir.resolve(); evidence=args.evidence_dir.resolve()
    if evidence == run_resolved or run_resolved in evidence.parents:
        raise SystemExit('evidence directory must not modify the frozen run')
    if not args.execute:
        write_once(proof_path,proof); print(json.dumps(proof,indent=2)); return
    if json.loads(proof_path.read_text()) != proof:
        raise SystemExit('reviewed proof no longer matches current frozen evidence or tools')
    if Path('/proc/sys/kernel/random/boot_id').read_text().strip() != proof['boot_id']:
        raise SystemExit('live host boot does not match reviewed proof')
    if build_proof(run_resolved) != proof:
        raise SystemExit('frozen evidence or recovery sources changed before execution')
    manifest=json.loads((args.run_dir/'manifest.json').read_text())
    vfio=load('vfio-recover'); lease_evidence=vfio.parse_v2_lease_records(
        proof['lease_seed']['records'][:2], manifest['run_id'])
    experiment=load('experiment')
    if build_proof(run_resolved) != proof:
        raise SystemExit('recovery sources changed after module loading')
    canonical=(args.vm_dir.resolve()/'run/incomplete-cr2-recovery-attempts'/
               proof['boot_id']/(proof['run_id']+'.json'))
    validator=lambda receipt: receipt_errors(
        experiment,receipt,proof,manifest,args.vm_dir.resolve(),
        run_resolved/'manifest.json')
    result=execute_once(evidence,proof_path,args.reviewed_proof_sha256,
        lambda: vfio.recover(args.vm_dir.resolve(), manifest['run_id'],
            lease_evidence=lease_evidence,
            recovery_helpers_sha256=proof['current_recovery_helpers_sha256'],
            recovery_lease_schema=3),validator,canonical_attempt=canonical)
    print(json.dumps(result,indent=2)); sys.exit(result['status']!='complete')

if __name__ == '__main__': main()
