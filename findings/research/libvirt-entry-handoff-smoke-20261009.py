#!/usr/bin/env python3
"""Software-only adapter around the actual entry launch/permit/cleanup code.

Replaces native hardware configuration and MAC admission with the already-tested
TCG/TAP fixture. Never accepts VFIO, KVM, host networking or native guest disks.
The production entry controller and handoff logic themselves are not replaced.
"""
import importlib.util
import json
import os
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

ROOT=Path('/candidate')
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result

entry=module('entry',ROOT/'tools/libvirt-console-entry.py')
fixture=module('fixture',ROOT/'findings/research/libvirt-local-lifecycle-smoke-20261009.py')

def plan(argv,run_id):
    assert not argv
    result=fixture.fixture.plan()
    old=result['run_id']
    result['xml']=result['xml'].replace(old,run_id).replace('vmxnet3,id=lan,',
        'vmxnet3,id=lan0,mac=52:54:00:12:34:56,')
    result.update(run_id=run_id,domain_name='rgpu-'+run_id)
    root=ET.fromstring(result['xml'])
    ET.SubElement(ET.SubElement(root,'features'),'acpi')
    cmd=root.find('{http://libvirt.org/schemas/domain/qemu/1.0}commandline')
    for value in ['-device','ich9-ahci,id=sata','-drive',
                  'file=/run/rgpu-libvirt/boot.img,format=raw,if=none,id=testboot,snapshot=on',
                  '-device','ide-hd,drive=testboot,bus=sata.0,bootindex=1',
                  '-chardev','socket,id=testserial,path=/run/rgpu-libvirt/guest.sock,server=on,wait=off',
                  '-device','isa-serial,chardev=testserial,index=0']:
        ET.SubElement(cmd,'{http://libvirt.org/schemas/domain/qemu/1.0}arg',value=value)
    result['xml']=ET.tostring(root,encoding='unicode')
    return result

class Backend(fixture.TestBackend):
    def __init__(self,uri,path,plan,network,fd):
        assert fd==3 and network=={'software_fixture':True}
        super().__init__(uri,path)

entry.native.NativeBackend=Backend
entry.native.verify=fixture.verify
entry.native.configuration.planner.build_plan=plan

if __name__=='__main__':
    assert not Path('/dev/kvm').exists() and not Path('/dev/vfio').exists()
    if sys.argv[1]=='launch':entry.launch([])
    elif sys.argv[1]=='inspect-paused':
        directory,_,_=entry.context()
        os.environ['XDG_RUNTIME_DIR']=str(directory/'runtime')
        p=json.loads((directory/'plan.json').read_text())
        backend=fixture.local.LocalBackend('qemu:///session',directory/'test-inspection.jsonl')
        try:print(json.dumps(entry.paused_observation(backend,p,backend.snapshot(p['domain_name']))))
        finally:backend.close()
    else:raise ValueError('unknown software test action')
