#!/usr/bin/env python3
"""Authorize one same-boot launch after a fresh, read-only stopped scan."""
import hashlib, importlib.util, json, subprocess, time
from pathlib import Path

SCHEMA = 8

def _load(name):
    p = Path(__file__).with_name(name + '.py')
    s = importlib.util.spec_from_file_location(name.replace('-', '_'), p)
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m

R = _load('vfio-recover'); N = _load('inspect-noqueue')

def sha(data): return hashlib.sha256(data).hexdigest()

def validate_snapshot(e):
    """Pure validator for the complete selector scan; returns error labels."""
    bad=[]; g=e.get('globals_before',{}); a=e.get('globals_after',{})
    if not e.get('vfio_opened') or e.get('errors'): bad.append('scan_error')
    if e.get('kernel_faults_before') or e.get('kernel_faults_after'): bad.append('kernel_faults')
    if e.get('kernel_cursor_before') != e.get('kernel_cursor_after'): bad.append('kernel_cursor')
    if not isinstance(g,dict) or not isinstance(a,dict): bad.append('globals_malformed')
    if not isinstance(g,dict) or not isinstance(a,dict): return sorted(set(bad))
    if g != a: bad.append('globals_unstable')
    if isinstance(g,dict) and any(type(v) is not int or v == 0xffffffff for v in g.values()): bad.append('global_all_ones')
    if g.get('c2pmsg_64') != 0x80030000: bad.append('psp_mailbox')
    if (g.get('cp_stat') != 0 or g.get('cpc_busy') != 0 or
        g.get('me_cntl',0) & R.CP_ME_HALT_MASK != R.CP_ME_HALT_MASK or
        g.get('mec_cntl',0) & R.CP_MEC_HALT_MASK != R.CP_MEC_HALT_MASK or
        g.get('pq_wptr_poll_cntl') != 0 or g.get('pq_status') != 0 or
        g.get('rb_doorbell_control',0) & 0xc0000000): bad.append('global_not_idle')
    for k in ('sdma0_gfx_rb_cntl','sdma0_gfx_ib_cntl','sdma0_page_rb_cntl','sdma0_page_ib_cntl','sdma0_rlc0_rb_cntl','sdma0_rlc0_ib_cntl','sdma0_rlc1_rb_cntl','sdma0_rlc1_ib_cntl'):
        if g.get(k,0xffffffff) & (R.SDMA_RB_ENABLE_MASK if 'rb' in k else R.SDMA_IB_ENABLE_MASK): bad.append('sdma_enabled')
    if g.get('sdma0_cntl',0xffffffff) & R.SDMA_AUTO_CTXSW_ENABLE_MASK or not g.get('sdma0_f32_cntl',0) & R.SDMA_HALT_MASK or not g.get('sdma0_status',0) & R.SDMA_STATUS_IDLE_MASK: bad.append('sdma_not_idle')
    passes=e.get('passes',[])
    if len(passes)!=2: bad.append('pass_count')
    expected={(m,p,q) for m in (1,2) for p in range(4) for q in range(8)}
    for x in passes:
        if not isinstance(x,dict) or x.get('globals') != g: bad.append('pass_globals')
        if not isinstance(x,dict): continue
        rows=x.get('hqd',[])
        keys={(r[0],r[1],r[2]) for r in rows if isinstance(r,list) and len(r)==5 and all(type(v) is int for v in r)}
        if len(rows)!=64 or keys != expected: bad.append('hqd_coverage')
        if any(not isinstance(r,list) or len(r)!=5 or any(type(v) is not int for v in r) or r[3] != 0 or r[4] != 0 for r in rows): bad.append('hqd_active')
        gr=x.get('graphics',[])
        valid_gr=[r for r in gr if isinstance(r,list) and len(r)==4 and all(type(v) is int for v in r)]
        if len(gr)!=2 or len(valid_gr)!=2 or {r[0] for r in valid_gr}!={0,1} or any(r[1] or r[2] or r[3] for r in valid_gr): bad.append('graphics_active')
    if len(passes)==2 and passes[0] != passes[1]: bad.append('scan_unstable')
    if e.get('selector_final') != 0: bad.append('selector_restore')
    return sorted(set(bad))

def validate_proof(proof, boot_id, run_id, ledger_raw, manifest_sha256):
    """Validate a complete schema-8 proof at reservation time."""
    errors=[]
    if not isinstance(proof, dict): return ['proof_type']
    if proof.get('schema') != SCHEMA or proof.get('kind') != 'same-boot-noqueue-qualification': errors.append('schema_kind')
    if proof.get('authorizes_launch') is not True: errors.append('not_authorized')
    if proof.get('boot_id') != boot_id or proof.get('run_id') != run_id: errors.append('identity')
    rows = []
    try:
        ledger=json.loads(ledger_raw); rows=ledger['launches']; cap=ledger['max_launches']
        if ledger.get('boot_id') != boot_id or not isinstance(rows,list) or not rows or rows[-1].get('run_id') != proof.get('prior_run_id'): errors.append('prior_run')
        if any(isinstance(r,dict) and r.get('run_id') == run_id for r in rows): errors.append('run_id_reused')
        if type(cap) is not int or cap <= 0 or len(rows) >= min(cap,3): errors.append('cap')
    except Exception: errors.append('ledger_malformed')
    if proof.get('prior_run_id') is None or proof.get('prior_run_id') == run_id: errors.append('prior_run')
    if proof.get('ledger_preimage_sha256') != sha(ledger_raw): errors.append('ledger_sha256')
    if proof.get('manifest_sha256') != manifest_sha256: errors.append('manifest_sha256')
    expected={str(p):sha(p.read_bytes()) for p in (Path(__file__),Path(R.__file__),Path(N.__file__))}
    if proof.get('helper_sha256') != expected: errors.append('helper_sha256')
    if not isinstance(proof.get('kernel_cursor_before'),str) or not proof.get('kernel_cursor_before') or not isinstance(proof.get('kernel_cursor_after'),str) or not proof.get('kernel_cursor_after'): errors.append('kernel_cursor')
    for key in ('host_before','host_after'):
        h=proof.get(key)
        if not isinstance(h,dict): errors.append(key)
        else: errors += [key+'_'+x for x in R.validate_host_state(h,boot_id)]
    if proof.get('post_host_gate_errors') not in ([], None): errors.append('post_host_gate_errors')
    if proof.get('power_control') != 'on' or proof.get('runtime_status') != 'active': errors.append('power_state')
    errors += validate_snapshot(proof)
    return sorted(set(errors))

def authorize(vm, prior_output, manifest, manifest_path, recovery, R, N):
    vm = Path(vm); prior = Path(prior_output); mp = Path(manifest_path)
    errors=[]
    if not prior.is_dir(): errors.append('prior_output')
    try:
        prior_manifest=json.loads((prior/'manifest.json').read_text())
        if prior_manifest.get('run_id') != recovery.get('run_id'): errors.append('prior_manifest_run_id')
        if prior_manifest.get('boot_id') != manifest.get('boot_id'): errors.append('prior_manifest_boot_id')
        if (prior/'probe.json').exists(): errors.append('prior_probe_present')
        evidence_prior_hashes={n:sha((prior/n).read_bytes()) for n in ('manifest.json','verdict.json','serial.txt','critical.txt')}
    except Exception: evidence_prior_hashes={}; errors.append('prior_manifest')
    if manifest.get('run_id') == recovery.get('run_id'): errors.append('run_id_reused')
    if (prior/'serial.txt').read_bytes() if (prior/'serial.txt').exists() else b'X': errors.append('prior_serial_nonempty')
    if (prior/'critical.txt').read_bytes() if (prior/'critical.txt').exists() else b'X': errors.append('prior_critical_nonempty')
    try:
        v=json.loads((prior/'verdict.json').read_text())
        if v.get('verdict') not in ('INVALID','WRAPPER_FAILURE') or v.get('earliest_failure') not in ('identity_or_route_missing','launcher'): errors.append('prior_failure')
    except Exception: errors.append('prior_verdict')
    ledger_path=vm/'run/used-gpu-boots'/(manifest['boot_id']+'.json')
    try:
        ledger_raw=ledger_path.read_bytes(); ledger=json.loads(ledger_raw); rows=ledger['launches']
        if not rows or rows[-1].get('run_id') != recovery.get('run_id'): errors.append('prior_run_latest')
        if ledger.get('boot_id') != manifest['boot_id'] or len(rows)>=ledger.get('max_launches',0): errors.append('ledger')
    except Exception: ledger_raw=b''; ledger={}; errors.append('ledger')
    host=R.host_state(); errors += ['host_'+x for x in R.validate_host_state(host, manifest['boot_id'])]
    pci=Path('/sys/bus/pci/devices/0000:7b:00.0'); power=(pci/'power/control').read_text().strip(); runtime=(pci/'power/runtime_status').read_text().strip()
    if power!='on': errors.append('power_control')
    if runtime!='active': errors.append('runtime_status')
    if host.get('pci_command',0) & 4: errors.append('bus_master')
    if list((vm/'run/launch-pending').iterdir()) if (vm/'run/launch-pending').is_dir() else []: errors.append('pending')
    names=subprocess.run(['docker','ps','-a','--filter','status=running','--filter','status=created','--filter','status=restarting','--filter','status=paused','--format','{{.Names}}'],text=True,capture_output=True,check=True).stdout.splitlines()
    if any(n=='macos-sequoia' or n.startswith('rgpu-launch-') for n in names): errors.append('active_vm')
    units=subprocess.run(['systemctl','--user','list-units','--all','--plain','--no-legend'],text=True,capture_output=True,check=True).stdout.splitlines()
    if any(line.split() and (line.split()[0].startswith(('rgpu-launch-','rgpu-serial-','rgpu-critical-','rgpu-deadline-'))) and line.split()[2] in ('activating','active') for line in units): errors.append('active_launch_unit')
    before=R.kernel_updates();
    if before[2]: errors.append('kernel_faults_before')
    if any(row.get('run_id') == manifest.get('run_id') for row in rows): errors.append('run_id_reused')
    evidence={'schema':SCHEMA,'kind':'same-boot-noqueue-qualification','boot_id':manifest['boot_id'],'prior_run_id':recovery['run_id'],'run_id':manifest['run_id'],'manifest_sha256':sha(mp.read_bytes()),'prior_hashes':evidence_prior_hashes,'ledger_preimage_sha256':sha(ledger_raw),'host_before':host,'kernel_cursor_before':before[0],'kernel_faults_before':before[2],'power_control':power,'runtime_status':runtime,'errors':errors,'authorizes_launch':False,'helper_sha256':{str(p):sha(p.read_bytes()) for p in (Path(__file__),Path(R.__file__),Path(N.__file__))}}
    if errors: return evidence
    offsets=dict(N.GLOBAL_OFFSETS,c2pmsg_64=R.C2PMSG_64_OFFSET,sdma0_status=R.SDMA0_STATUS_REG_OFFSET,sdma0_page_rb_cntl=R.SDMA0_PAGE_RB_CNTL_OFFSET,sdma0_page_ib_cntl=R.SDMA0_PAGE_IB_CNTL_OFFSET,sdma0_rlc0_rb_cntl=R.SDMA0_RLC_RB_CNTL_OFFSETS[0],sdma0_rlc0_ib_cntl=R.SDMA0_RLC_IB_CNTL_OFFSETS[0],sdma0_rlc1_rb_cntl=R.SDMA0_RLC_RB_CNTL_OFFSETS[1],sdma0_rlc1_ib_cntl=R.SDMA0_RLC_IB_CNTL_OFFSETS[1]); N.OBSERVATION_OFFSETS.update(offsets.values())
    evidence['offsets']=offsets; evidence['vfio_opened']=False
    try:
        with R.LegacyVfio() as raw:
            evidence['vfio_opened']=True; mm=N.GuardedTransport(raw)
            def sel(x): mm.write32(R.GRBM_GFX_CNTL_OFFSET,x)
            def glob(): return {k:mm.read32(v) for k,v in offsets.items()}
            g=glob(); evidence['globals_before']=g
            if any(v==0xffffffff for v in g.values()) or g['cp_stat'] or g['cpc_busy'] or g['me_cntl']&R.CP_ME_HALT_MASK != R.CP_ME_HALT_MASK or g['mec_cntl']&R.CP_MEC_HALT_MASK != R.CP_MEC_HALT_MASK or g['rb0_active']&1 or g['rb1_active']&1 or g['rb_doorbell_control']&0xc0000000 or not g['sdma0_f32_cntl']&R.SDMA_HALT_MASK or not g['sdma0_status']&R.SDMA_STATUS_IDLE_MASK: raise RuntimeError('global_quiescence')
            evidence['passes']=[]
            try:
                for _ in (1,2):
                    q=[]
                    for me in (1,2):
                        for pipe in range(4):
                            for queue in range(8):
                                s=R.queue_selector(me,pipe,queue); sel(s); q.append([me,pipe,queue,mm.read32(R.CP_HQD_ACTIVE_OFFSET),mm.read32(R.CP_HQD_PQ_DOORBELL_OFFSET)])
                    gr=[]
                    for pipe in (0,1): sel(pipe); gr.append([pipe,mm.read32(R.CP_RB_ACTIVE_OFFSET),mm.read32(N.CP_RB1_ACTIVE_OFFSET),mm.read32(R.CP_RB_DOORBELL_CONTROL_OFFSET)])
                    evidence['passes'].append({'hqd':q,'graphics':gr,'globals':glob()})
                sel(0); evidence['selector_final']=0
            finally:
                sel(0)
            if evidence['passes'][0]!=evidence['passes'][1]: raise RuntimeError('unstable_scan')
            evidence['globals_after']=glob()
    except Exception as e: evidence['errors'].append(type(e).__name__+': '+str(e))
    try:
        after=R.kernel_updates(); evidence['kernel_cursor_after']=after[0]; evidence['kernel_faults_after']=after[2]
        evidence['host_after']=R.host_state(); evidence['post_host_gate_errors']=R.validate_host_state(evidence['host_after'],manifest['boot_id'])
    except Exception as e:
        evidence['errors'].append('postflight: '+type(e).__name__+': '+str(e)); evidence['postflight_failed']=True
    evidence['errors'] += validate_snapshot(evidence); evidence['authorizes_launch']=not evidence['errors'] and not evidence.get('post_host_gate_errors'); return evidence
