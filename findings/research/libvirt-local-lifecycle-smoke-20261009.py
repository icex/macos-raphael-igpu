#!/usr/bin/env python3
"""Container PID1 software-only lifecycle test for the real local backend."""
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import socket
import struct
import subprocess
import time
import xml.etree.ElementTree as ET

ROOT=Path('/candidate')
RUN=Path('/run/rgpu-libvirt')

def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result

runtime=module('runtime',ROOT/'tools/libvirt-console-runtime.py')
local=module('local',ROOT/'tools/libvirt-console-local.py')
fixture=module('fixture',ROOT/'findings/research/libvirt-runtime-failure-smoke-20261009.py')
network=module('network',ROOT/'tools/libvirt-console-network.py')

class TestBackend(local.LocalBackend):
    def network_attached(self,name,hub):
        report=self.qmp(name,'human-monitor-command',{'command-line':'info network'}).replace('\r','')
        (RUN/'network.txt').write_text(report)
        fd=network.verify_network_report(report,'52:54:00:12:34:56',hub)
        state=self.snapshot(name)
        info=Path(f'/proc/{state["pid"]}/fdinfo/{fd}').read_text()
        return re.search(r'^iff:\s+rgpu_tap$',info,re.M) is not None


def verify(plan,state):
    argv=state['argv']
    assert not any('vfio' in a or 'kvm' in a for a in argv)
    assert argv[argv.index('-accel')+1]=='tcg'
    assert '/run/rgpu-libvirt/boot.img' in ' '.join(argv)
    return True


def main():
    assert os.getppid()==1,'controller must be the container init child'
    os.environ['XDG_RUNTIME_DIR']=str(RUN/'runtime')
    Path(os.environ['XDG_RUNTIME_DIR']).mkdir(mode=0o700,exist_ok=True)
    subprocess.run(['libvirtd','--daemon'],check=True,timeout=10)
    backend=TestBackend('qemu:///session',RUN/'events.jsonl')
    plan=fixture.plan()
    plan['xml']=plan['xml'].replace('vmxnet3,id=lan,','vmxnet3,id=lan0,')
    root=ET.fromstring(plan['xml']);ET.SubElement(ET.SubElement(root,'features'),'acpi');cmd=root.find('{http://libvirt.org/schemas/domain/qemu/1.0}commandline')
    for value in ['-netdev','user,id=net0',
                  '-device','vmxnet3,id=net0,netdev=net0,bus=pcie.0,addr=0x8,mac=52:54:00:12:34:57',
                  '-device','ich9-ahci,id=sata','-drive',
                  'file=/run/rgpu-libvirt/boot.img,format=raw,if=none,id=testboot,snapshot=on',
                  '-device','ide-hd,drive=testboot,bus=sata.0,bootindex=1',
                  '-chardev','socket,id=testserial,path=/run/rgpu-libvirt/guest.sock,server=on,wait=off',
                  '-device','isa-serial,chardev=testserial,index=0',
                  '-chardev','file,id=bioslog,path=/run/rgpu-libvirt/bios.log',
                  '-device','isa-debugcon,iobase=0x402,chardev=bioslog']:
        ET.SubElement(cmd,'{http://libvirt.org/schemas/domain/qemu/1.0}arg',value=value)
    plan['xml']=ET.tostring(root,encoding='unicode')
    owner=runtime.PausedDomain(backend,plan,runtime.digest(plan),local.namespace_identity(),verify)
    try:
        info=fcntl.ioctl(3,0x800454d2,bytes(40))
        assert info[:16].rstrip(b'\0')==b'rgpu_tap'
        owner.prepare(3)
        console=socket.socket(socket.AF_UNIX);console.settimeout(15)
        console.connect(str(RUN/'guest.sock'))
        owner.resume()
        try:
            assert console.recv(1)==b'R','software guest not ready'
        except Exception:
            for label,cmdline in [('registers','info registers'),('block','info block'),('bootmem','xp /40bx 0x7c00')]:
                (RUN/(label+'.txt')).write_text(backend.qmp(plan['domain_name'],'human-monitor-command',{'command-line':cmdline}))
            raise
        backend.record(dict(phase='test-guest-ready',identity=owner.identity))
        (RUN/'ready.json').write_text(json.dumps(dict(identity=owner.identity,run_id=plan['run_id'])))
        mode=os.environ['TEST_STOP_MODE']
        if mode=='guest-shutdown':console.sendall(b'x')
        # External destroy is issued through the independent host libvirt client.
        reason=runtime.monitor(owner,time.monotonic()+30)
        assert reason==mode,(reason,mode)
        assert backend.session_processes_gone()
        result=dict(passed=True,reason=reason,identity=owner.identity,scope=backend.scope,
                    process_exited=True,phases=[e['phase'] for e in owner.events])
        (RUN/'result.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result),flush=True)
        console.close()
    finally:
        if not owner.finished:owner.cleanup('controller-finally')
        os.close(3)
        backend.close()
        pid=int((RUN/'runtime/libvirt/libvirtd.pid').read_text())
        os.kill(pid,signal.SIGTERM)
        deadline=time.monotonic()+5
        while Path(f'/proc/{pid}').exists() and time.monotonic()<deadline:time.sleep(.05)

if __name__=='__main__':main()
