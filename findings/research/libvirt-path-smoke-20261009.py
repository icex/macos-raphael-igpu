#!/usr/bin/env python3
"""Paired real libvirt discovery test; no domain creation or host devices."""
import importlib.util
import json
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
IMAGE='sha256:3a3c82c79bc4e73531f819ccdfa4053b3084efd7c1f645678dbf8b4b3a24369c'

def command(argv,timeout=30,check=True):
    return subprocess.run(argv,text=True,capture_output=True,timeout=timeout,check=check)

def inside(case):
    root=Path('/run/study');runtime=root/'runtime';runtime.mkdir(mode=0o700)
    shim=root/'shim';shim.mkdir()
    binary=shim/'qemu-system-x86_64'
    binary.write_text('#!/bin/sh\necho invoked >> /run/study/shim-invoked\nexit 97\n');binary.chmod(0o755)
    os.environ['XDG_RUNTIME_DIR']=str(runtime)
    os.environ['PATH']=str(shim)+':/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
    pid=None
    try:
        if case=='original':command(['libvirtd','--daemon'])
        else:
            spec=importlib.util.spec_from_file_location('entry','/tools/libvirt-console-entry.py')
            entry=importlib.util.module_from_spec(spec);spec.loader.exec_module(entry)
            entry.start_daemon(time.monotonic()+60)
        pid=int((runtime/'libvirt/libvirtd.pid').read_text())
        raw=Path(f'/proc/{pid}/environ').read_bytes().split(b'\0')
        paths=[v.decode() for v in raw if v.startswith(b'PATH=')]
        result=command(['virsh','-c','qemu:///session','capabilities'],timeout=60)
        (root/'capabilities.xml').write_text(result.stdout)
        guests={g.find('arch').get('name'):g.findtext('arch/emulator') for g in ET.fromstring(result.stdout).findall('guest')}
        invoked=(root/'shim-invoked').exists()
        if case=='original':assert invoked and 'x86_64' not in guests,(invoked,guests)
        else:assert not invoked and guests.get('x86_64') in ('/usr/sbin/qemu-system-x86_64','/usr/bin/qemu-system-x86_64'),(invoked,guests)
        domains=command(['virsh','-c','qemu:///session','list','--all','--name']).stdout.strip()
        assert not domains
        qemu=[]
        for p in Path('/proc').iterdir():
            if not p.name.isdigit():continue
            try:
                argv=(p/'cmdline').read_bytes().split(b'\0')
                if argv and os.path.basename(os.fsdecode(argv[0])).startswith('qemu-system'):qemu.append(p.name)
            except FileNotFoundError:pass
        assert not qemu,qemu
        (root/'result.json').write_text(json.dumps(dict(passed=True,case=case,guests=guests,shim_invoked=invoked,daemon_path=paths,domains=[],qemu_processes=[],scope='Global capabilities discovery only; no domain creation, KVM, VFIO or host devices.'),indent=2)+'\n')
    finally:
        if pid:
            try:os.kill(pid,signal.SIGTERM)
            except ProcessLookupError:pass

def host():
    base=Path.home()/'macos-vm/run'/('c342-path-'+secrets.token_hex(4));base.mkdir(mode=0o700)
    records=[]
    for case in ('original','sanitized'):
        root=base/case;root.mkdir(mode=0o700);cid=None
        try:
            cid=command(['docker','run','-d','--init','--name','rgpu-'+base.name+'-'+case,'--network','none','--cap-drop','ALL','--user',f'{os.getuid()}:{os.getgid()}','-v',str(root)+':/run/study','-v',str(Path(__file__).resolve())+':/study.py:ro','-v',str(Path(__file__).resolve().parents[2]/'tools')+':/tools:ro','--entrypoint','python3',IMAGE,'-B','/study.py',case]).stdout.strip()
            first=json.loads(command(['docker','inspect',cid]).stdout)[0]
            assert first['Image']==IMAGE and not first['HostConfig']['Devices'] and not first['HostConfig']['Privileged'] and first['HostConfig']['NetworkMode']=='none'
            code=int(command(['docker','wait',cid],timeout=90).stdout.strip())
            logs=command(['docker','logs',cid]);(root/'stdout.txt').write_text(logs.stdout);(root/'stderr.txt').write_text(logs.stderr)
            final=json.loads(command(['docker','inspect',cid]).stdout)[0]
            receipt=dict(case=case,cid=cid,image=first['Image'],started_at=final['State']['StartedAt'],finished_at=final['State']['FinishedAt'],exit_code=code,running=final['State']['Running'],devices=first['HostConfig']['Devices'],network=first['HostConfig']['NetworkMode'])
            (root/'container.json').write_text(json.dumps(receipt,indent=2)+'\n')
            assert code==0 and not final['State']['Running'],(case,logs.stderr)
            records.append(dict(receipt=receipt,result=json.loads((root/'result.json').read_text())))
        finally:
            if cid:command(['docker','stop','--time','5',cid],timeout=15,check=False)
    (base/'result.json').write_text(json.dumps(dict(passed=True,cases=records),indent=2)+'\n');print(base)

if __name__=='__main__':
    inside(sys.argv[1]) if len(sys.argv)>1 else host()
