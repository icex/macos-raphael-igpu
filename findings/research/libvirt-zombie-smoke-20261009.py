#!/usr/bin/env python3
"""Observe actual unreaped QEMU with candidate exit proof; no CPUs/KVM/GPU."""
import importlib.util
import json
from pathlib import Path
import socket
import subprocess
import time

spec=importlib.util.spec_from_file_location('entry','/candidate/tools/libvirt-console-entry.py')
entry=importlib.util.module_from_spec(spec);spec.loader.exec_module(entry)
root=Path('/run/study');sockpath=root/'qmp.sock'
argv=['/usr/sbin/qemu-system-x86_64','-machine','none,accel=tcg','-nodefaults','-S','-display','none','-qmp',f'unix:{sockpath},server=on,wait=off']
assert not Path('/dev/kvm').exists() and not Path('/dev/vfio').exists()
(root/'argv.json').write_text(json.dumps(argv)+'\n')
with (root/'qemu.log').open('w') as log:
    proc=subprocess.Popen(argv,stdout=log,stderr=log)
    try:
        end=time.monotonic()+10
        while not sockpath.exists():
            if time.monotonic()>end:raise TimeoutError('QMP socket')
            time.sleep(.01)
        identity=entry.native.local.process(proc.pid)
        assert identity and not entry.completed_original_zombie(identity)
        with socket.socket(socket.AF_UNIX) as sock:
            sock.settimeout(5);sock.connect(str(sockpath));stream=sock.makefile('rwb',buffering=0)
            assert 'QMP' in json.loads(stream.readline())
            def qmp(name):
                sock.sendall(json.dumps({'execute':name}).encode()+b'\n')
                while True:
                    data=json.loads(stream.readline())
                    if 'error' in data:raise RuntimeError('QMP refused')
                    if 'return' in data:return data['return']
            qmp('qmp_capabilities');kvm=qmp('query-kvm');cpus=qmp('query-cpus-fast')
            assert kvm['enabled'] is False and cpus==[]
            qmp('quit')
        end=time.monotonic()+5
        while True:
            fields=Path(f'/proc/{proc.pid}/stat').read_text().rsplit(')',1)[1].split()
            if fields[0]=='Z':break
            if time.monotonic()>end:raise TimeoutError('unreaped zombie')
            time.sleep(.01)
        result=dict(pid=proc.pid,start_ticks=identity['start_ticks'],state=fields[0],
                    threads=[p.name for p in Path(f'/proc/{proc.pid}/task').iterdir()],
                    descriptors=[p.name for p in Path(f'/proc/{proc.pid}/fd').iterdir()],
                    completed=entry.completed_original_zombie(identity),kvm=kvm,cpus=cpus)
        assert result['completed'] and result['threads']==[str(proc.pid)] and not result['descriptors']
        result['exit_code']=proc.wait(timeout=5);assert result['exit_code']==0
        (root/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    finally:
        if proc.poll() is None:proc.kill();proc.wait(timeout=5)
