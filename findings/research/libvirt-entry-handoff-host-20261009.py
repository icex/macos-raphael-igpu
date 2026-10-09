#!/usr/bin/env python3
"""Bounded, no-GPU real-controller handoff tests; see companion smoke adapter."""
import datetime
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import time

ROOT=Path(__file__).resolve().parents[2]
BASE=Path.home()/'macos-vm/run'
IMAGE='sha256:3a3c82c79bc4e73531f819ccdfa4053b3084efd7c1f645678dbf8b4b3a24369c'
spec=importlib.util.spec_from_file_location('handoff',ROOT/'tools/libvirt-console-handoff.py')
h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)
def command(args):return subprocess.check_output(args,text=True,timeout=20).strip()
def inspect(cid):return json.loads(command(['docker','inspect',cid]))[0]
def wait_file(path,cid):
    until=time.monotonic()+35
    while not path.exists():
        assert inspect(cid)['State']['Running'],'container exited before '+path.name
        assert time.monotonic()<until,'deadline waiting for '+path.name
        time.sleep(.1)

def run(case):
    run_id=secrets.token_hex(16)
    base=BASE/('c341-entry-'+case+'-'+run_id[:8]);base.mkdir(mode=0o700)
    shutil.copyfile(BASE/'c341-native-network-shape-c/boot.img',base/'boot.img')
    bootstrap=(ROOT/'findings/research/libvirt-local-lifecycle-bootstrap-20261009.py').read_text()
    bootstrap=bootstrap.replace("libvirt-local-lifecycle-smoke-20261009.py']",
                                "libvirt-entry-handoff-smoke-20261009.py','launch']")
    (base/'bootstrap.py').write_text(bootstrap)
    manifest=dict(run_id=run_id,boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                  max_seconds=120,image_id=IMAGE,launch_options={'VM_MANAGER':'libvirt'})
    directory,digest=h.prepare(base,manifest,json.dumps(manifest).encode(),{'software_fixture':True},
                              {name:h.sha((ROOT/'tools'/name).read_bytes()) for name in h.MODULES})
    name='rgpu-c341-entry-'+run_id[:8]
    cid=command(['docker','run','-d','--init','--name',name,'--network','none','--user','0',
        '--device','/dev/net/tun','--cap-add','NET_ADMIN','-e','HOME=/home/arch',
        '-e','RGPU_LIBVIRT_RUN_ID='+run_id,'-e','RGPU_LIBVIRT_ADMISSION_SHA256='+digest,
        '-v',str(ROOT)+':/candidate:ro','-v',str(base)+':/run/vm',
        '-v',str(base)+':/run/rgpu-libvirt','--entrypoint','python3',IMAGE,
        '/run/rgpu-libvirt/bootstrap.py'])
    console=None
    try:
        host=inspect(cid)
        assert host['HostConfig']['NetworkMode']=='none' and not host['HostConfig']['Privileged']
        assert [d['PathOnHost'] for d in host['HostConfig']['Devices']]==['/dev/net/tun']
        wait_file(directory/'paused.json',cid)
        console=socket.socket(socket.AF_UNIX);console.settimeout(1)
        console.connect(str(base/'guest.sock'))
        try:
            data=console.recv(1)
            raise AssertionError('software guest executed without permit: '+repr(data))
        except socket.timeout:pass
        observed=json.loads(command(['docker','exec','--user','1000',cid,'python3','-B',
            '/candidate/findings/research/libvirt-entry-handoff-smoke-20261009.py','inspect-paused']))
        paused=json.loads((directory/'paused.json').read_text())
        started=host['State']['StartedAt']
        state=dict(cid=cid,started_at=started,deadline_epoch=datetime.datetime.fromisoformat(
            started.replace('Z','+00:00')).timestamp()+120)
        permit=h.permit(json.loads((directory/'admission.json').read_text()),digest,paused,observed,state)
        if case=='wrong-permit':permit['paused']['identity']['start_ticks']+=1
        h.write_once(directory/'resume.json',permit)
        if case=='valid':
            wait_file(directory/'running.json',cid)
            running=json.loads((directory/'running.json').read_text())
            assert running['identity']==observed['identity'] and running['scope']==observed['scope']
            assert running['cid']==cid and running['started_at']==started
            console.settimeout(10);assert console.recv(1)==b'R'
            console.sendall(b'x')
        code=int(command(['docker','wait',cid]))
        events=[json.loads(row) for row in (directory/'events.jsonl').read_text().splitlines()]
        if case=='valid':
            terminal=json.loads((directory/'terminal.json').read_text())
            assert code==0 and terminal['reason']=='guest-shutdown' and terminal['process_exited']
        else:
            assert code!=0 and not (directory/'running.json').exists()
            assert not any(row['phase']=='running' for row in events)
            assert events[-1]['phase']=='stopped'
        result=dict(passed=True,case=case,run_id=run_id,cid=cid,state=inspect(cid)['State'],
                    paused=observed,no_guest_byte_before_permit=True,events=events,
                    scope='actual entry launch and handoff; software TCG/TAP configuration adapter')
        (base/'result.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(dict(case=case,passed=True,evidence=str(base/'result.json'))),flush=True)
    finally:
        if console:console.close()
        if inspect(cid)['State']['Running']:
            subprocess.run(['docker','stop','-t','5',cid],check=True,timeout=10)
        (base/'container.log').write_text(subprocess.check_output(['docker','logs',cid],
            stderr=subprocess.STDOUT,text=True,timeout=5))

if __name__=='__main__':
    run('valid');run('wrong-permit')
