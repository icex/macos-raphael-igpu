#!/usr/bin/env python3
"""Real pthread exit state, synthetic admission/libvirt event and Docker adapter.

No VM, KVM, GPU or network. This isolates the approved wait state machine; it
cannot establish real libvirt event ordering or real container disappearance.
"""
import importlib.util
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import time
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
def module(name,file):
    spec=importlib.util.spec_from_file_location(name,ROOT/'tools'/file)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value
entry=module('entry','libvirt-console-entry.py');sup=module('sup','vm-supervision.py')
SOURCE=r'''
#include <pthread.h>
#include <stdlib.h>
#include <unistd.h>
static long delay;
static void *worker(void *p){(void)p;usleep(delay*1000);return 0;}
int main(int argc,char **argv){if(argc!=2)return 2;delay=strtol(argv[1],0,10);pthread_t t;if(pthread_create(&t,0,worker,0))return 3;pthread_exit(0);}
'''
def main():
    base=Path.home()/'macos-vm/run'/('c355-worker-'+secrets.token_hex(4));base.mkdir(mode=0o700)
    (base/'worker.c').write_text(SOURCE)
    subprocess.run(['cc','-Wall','-Wextra','-Werror','-pthread',str(base/'worker.c'),'-o',str(base/'worker')],check=True)
    results=[]
    for name,delay,event in [('delayed-worker',700,True),('expired-worker',3000,True),('missing-event',700,False)]:
        vm=base/name;directory=vm/'run';directory.mkdir(parents=True)
        proc=subprocess.Popen([str(base/'worker'),str(delay)])
        try:
            until=time.monotonic()+1
            while time.monotonic()<until:
                raw=Path(f'/proc/{proc.pid}/stat').read_text().rsplit(')',1)[1].split()
                if raw[0]=='Z':break
                time.sleep(.005)
            assert raw[0]=='Z'
            rid=secrets.token_hex(16);cid=secrets.token_hex(32);digest='c'*64;start='software-adapter'
            identity=dict(name='rgpu-'+rid,uuid='zero',run_id=rid,pid=proc.pid,start_ticks=int(raw[19]))
            scope=entry.native.local.namespace_identity()
            plan=dict(domain_name=identity['name'],uuid='zero',run_id=rid,native_argv=['-spice',entry.native.configuration.planner.SPICE,'-device',entry.native.configuration.planner.BOCHS])
            deadline=int(time.time()+20)
            admission=dict(schema=1,run_id=rid,manifest_sha256='d'*64,deadline_epoch=deadline)
            paused=dict(paused=True,run_id=rid,identity=identity,scope=scope,plan_sha256=entry.runtime.digest(plan))
            permit=dict(schema=1,run_id=rid,manifest_sha256='d'*64,admission_sha256=digest,paused=paused,cid=cid,started_at=start,deadline_epoch=deadline)
            running=dict(run_id=rid,identity=identity,scope=scope,plan_sha256=paused['plan_sha256'],cid=cid,started_at=start)
            for stem,value in [('plan',plan),('paused',paused),('resume',permit),('running',running)]:
                (directory/(stem+'.json')).write_text(json.dumps(value))
            observed=time.monotonic()
            observation=dict(phase='libvirt-lifecycle-observed',identity_bound=True,guest_shutdown=True,event=6,detail=1,identity=identity,scope=scope,name=identity['name'],uuid=identity['uuid'],observed_monotonic=observed)
            (directory/'events.jsonl').write_text(json.dumps(observation)+'\n' if event else '')
            eof=time.monotonic()
            (directory/f'capture-eof-{cid}-console.json').write_text(json.dumps(dict(schema=1,cid=cid,started_at=start,run_id=rid,admission_sha256=digest,channel='console',eof_monotonic=eof,published_monotonic=time.monotonic(),eof_epoch=time.time())))
            proofs=[];stops=[];completed=False
            original=Path.iterdir
            def scan(path):
                # Explicit synthetic namespace view, only this owned process.
                return iter([Path(f'/proc/{proc.pid}')]) if str(path)=='/proc' else original(path)
            def command(argv,**kwargs):
                nonlocal completed
                if argv[1]=='inspect':return json.dumps(dict(Id=cid,StartedAt=start,Running=not completed))
                assert argv[1]=='exec'
                value=entry.inspect_exited_report(float(argv[-1]));proofs.append(dict(at=time.monotonic(),proof=value))
                if value.get('exited') is True:completed=True
                return json.dumps(value)
            def stop(selected):
                assert selected==cid;stops.append(time.monotonic());proc.kill();proc.wait(timeout=2)
            with patch.object(entry,'context',return_value=(directory,admission,digest)),patch.object(entry.Path,'iterdir',new=scan),patch.object(sup,'run',side_effect=command),patch.object(sup,'binary',side_effect=lambda x:x),patch.object(sup,'stop_exact',side_effect=stop):
                result=sup.capture_exit(vm,cid,start,deadline,rid,digest,'console')
            if name=='delayed-worker':
                assert result['outcome']=='natural-container-exit' and not stops,result
                assert proofs[0]['proof']['exited'] is False and proofs[-1]['proof']['exited'] is True
            elif name=='expired-worker':
                assert result['outcome']=='shutdown-wait-expired' and len(stops)==1,result
                assert 1.8<=stops[0]-eof<=2.2
                assert all(p['proof'].get('exited') is not True for p in proofs)
            else:
                assert result['outcome']=='immediate-stop' and len(stops)==1 and stops[0]-eof<.5,result
            assert not (directory/'terminal.json').exists()
            results.append(dict(case=name,pid=proc.pid,start_ticks=identity['start_ticks'],eof_monotonic=eof,gate=result,proofs=proofs,stops=stops,terminal_synthesized=False))
        finally:
            if proc.poll() is None:proc.kill()
            proc.wait(timeout=2)
    (base/'result.json').write_text(json.dumps(dict(passed=True,scope=__doc__,cases=results),indent=2)+'\n')
    print(base)
if __name__=='__main__':main()
