#!/usr/bin/env python3
"""Real libvirt conversion-only check; no domain creation or passed devices."""
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shlex
import signal
import subprocess
import sys

IMAGE='sha256:6a18a413394dfca0f3882b9df722fb9f85b1126b368ffb51eb06f2bc217ffc74'

def command(argv,timeout=40,check=True):
    return subprocess.run(argv,text=True,capture_output=True,timeout=timeout,check=check)

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def inside():
    root=Path('/run/study');runtime=root/'runtime';runtime.mkdir(mode=0o700)
    os.environ['XDG_RUNTIME_DIR']=str(runtime)
    os.environ['PATH']='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
    fixture=load('fixture','/repo/tests/test_libvirt_console_plan.py')
    verifier=load('verifier','/repo/tools/libvirt-console-verify.py')
    pid=None;cases=[]
    try:
        command(['libvirtd','--daemon']);pid=int((runtime/'libvirt/libvirtd.pid').read_text())
        for refresh in ('default','60'):
            argv=fixture.native_fixture()
            if refresh=='60':argv[argv.index(fixture.plan.SPICE)]+=',max-refresh-rate=60'
            plan=fixture.plan.build_plan(argv,'3450'*8)
            (root/(refresh+'-production.xml')).write_text(plan['xml'])
            assert 'type="kvm"' in plan['xml']
            (root/(refresh+'.xml')).write_text(plan['xml'].replace('type="kvm"','type="qemu"',1))
            converted=command(['virsh','-c','qemu:///session','domxml-to-native','qemu-argv','--xml',str(root/(refresh+'.xml'))],timeout=90,check=False)
            (root/(refresh+'-native.txt')).write_text(converted.stdout)
            (root/(refresh+'-error.txt')).write_text(converted.stderr)
            assert converted.returncode==0,converted.stderr
            words=shlex.split(converted.stdout);index=next(i for i,v in enumerate(words) if v=='/usr/sbin/qemu-system-x86_64');native=words[index:]
            original=list(native);monitor=0;private=0
            accelerator=native.index("-accel")+1
            assert native[accelerator]=="tcg"
            native[accelerator]="kvm"
            # Conversion has no live domain ID or connected monitor FD. Project
            # only these two runtime-specific facts to exercise the full verifier.
            for i in range(len(native)):
                if native[i].startswith('socket,id=charmonitor,path='):
                    native[i]='socket,id=charmonitor,fd=27,server=on,wait=off';monitor+=1
                if 'domain--1-' in native[i]:
                    native[i]=native[i].replace('domain--1-','domain-1-');private+=1
            state=dict(name=plan['domain_name'],uuid=plan['uuid'],run_id=plan['run_id'],persistent=False,domain_id=1,argv=native)
            verifier.verify(plan,state)
            spice=[v for k,v in zip(native,native[1:]) if k=='-spice']
            assert len(spice)==(2 if refresh=='60' else 1),spice
            if refresh=='60':assert spice[-1]=='max-refresh-rate=60'
            cases.append(dict(refresh=refresh,verified=True,spice=spice,monitor_projection=monitor,private_path_projection=private,accelerator_projection='tcg to kvm (no KVM exposed)',argv_count=len(native)))
        domains=command(['virsh','-c','qemu:///session','list','--all','--name']).stdout.strip();assert not domains
        (root/'result.json').write_text(json.dumps(dict(passed=True,cases=cases,domains=[],scope='domxml conversion only; no QEMU domain created, no KVM/VFIO'),indent=2)+'\n')
    finally:
        if pid:
            try:os.kill(pid,signal.SIGTERM)
            except ProcessLookupError:pass

def runtime_inside():
    root=Path('/run/study')
    smoke=load('channel','/repo/tools/qemu-console-smoke.py')
    argv=['/usr/sbin/qemu-system-x86_64','-machine','none,accel=tcg','-S',
          '-nodefaults','-display','none','-nic','none',
          '-spice','unix=on,addr=/run/vm/console-spice.sock,disable-ticketing=on,image-compression=off,seamless-migration=on',
          '-spice','max-refresh-rate=60','-qmp','unix:/run/study/qmp.sock,server=on,wait=off']
    (root/'argv.json').write_text(json.dumps(argv,indent=2)+'\n')
    channel=None
    with (root/'qemu.log').open('w') as log:
        process=subprocess.Popen(argv,stdout=log,stderr=log)
        try:
            channel=smoke.Channel(root/'qmp.sock',process)
            assert 'QMP' in json.loads(channel.file.readline())
            def qmp(name):
                channel.socket.sendall(json.dumps({'execute':name}).encode()+b'\n')
                while True:
                    reply=json.loads(channel.file.readline())
                    if 'error' in reply:raise RuntimeError(reply['error'])
                    if 'return' in reply:return reply['return']
            qmp('qmp_capabilities')
            spice=qmp('query-spice');kvm=qmp('query-kvm');status=qmp('query-status');cpus=qmp('query-cpus-fast')
            assert spice['enabled'] is True and spice['host']=='/run/vm/console-spice.sock'
            assert kvm['enabled'] is False and status['running'] is False and cpus==[]
            rows=[line for line in Path('/proc/net/unix').read_text().splitlines() if line.split()[-1:] == ['/run/vm/console-spice.sock']]
            assert len(rows)==1
            observed=[os.fsdecode(v) for v in Path(f'/proc/{process.pid}/cmdline').read_bytes().split(b'\0') if v]
            assert observed==argv
            qmp('quit');process.wait(timeout=10);assert process.returncode==0
            (root/'result.json').write_text(json.dumps(dict(passed=True,spice=spice,kvm=kvm,status=status,cpus=cpus,spice_socket_count=len(rows),unix_socket_rows=rows,qemu_exit=process.returncode,observed_argv=observed,scope='Merged SPICE startup only; machine none, paused TCG, no CPU/device/guest rendering'),indent=2)+'\n')
        finally:
            if channel:channel.close()
            if process.poll() is None:
                process.terminate()
                try:process.wait(timeout=5)
                except subprocess.TimeoutExpired:process.kill();process.wait()
            (root/'qemu-cleanup.json').write_text(json.dumps(dict(pid=process.pid,exit=process.returncode,stopped=process.poll() is not None))+'\n')


def host(mode='inside'):
    repo=Path(__file__).resolve().parents[2]
    root=Path.home()/'macos-vm/run'/('c345-refresh-argv-'+secrets.token_hex(4));root.mkdir(mode=0o700);cid=None
    try:
        cid=command(['docker','run','-d','--init','--network','none','--cap-drop','ALL','--user',f'{os.getuid()}:{os.getgid()}',
                     '-v',str(root)+':/run/study','-v',str(root)+':/run/vm','-v',str(repo)+':/repo:ro','--entrypoint','python3',IMAGE,'-B',
                     '/repo/findings/research/libvirt-refresh-argv-smoke-20261009.py',mode]).stdout.strip()
        first=json.loads(command(['docker','inspect',cid]).stdout)[0]
        assert first['Image']==IMAGE and first['HostConfig']['NetworkMode']=='none' and not first['HostConfig']['Devices'] and not first['HostConfig']['Privileged']
        code=int(command(['docker','wait',cid],timeout=120).stdout.strip())
        logs=command(['docker','logs',cid]);(root/'stdout.txt').write_text(logs.stdout);(root/'stderr.txt').write_text(logs.stderr)
        final=json.loads(command(['docker','inspect',cid]).stdout)[0]
        (root/'container.json').write_text(json.dumps(dict(cid=cid,image=IMAGE,exit=code,running=final['State']['Running'],devices=first['HostConfig']['Devices'],network='none',started_at=final['State']['StartedAt'],finished_at=final['State']['FinishedAt']),indent=2)+'\n')
        print(root,flush=True)
        assert code==0 and not final['State']['Running'],logs.stderr
        print((root/'result.json').read_text())
    finally:
        if cid:command(['docker','stop','--time','5',cid],timeout=15,check=False)

if __name__=='__main__':
    if len(sys.argv)==1:host()
    elif sys.argv[1]=='runtime':host('inside-runtime')
    elif sys.argv[1]=='inside-runtime':runtime_inside()
    else:inside()
