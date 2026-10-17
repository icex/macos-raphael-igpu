#!/usr/bin/env python3
"""Verify the complete reviewed libvirt11.9/QEMU10.1 native console argument vector.

Pure comparison only; no launch CLI, GPU access or logging of AppleSMC arguments.
The profile intentionally rejects unreviewed libvirt-generated configuration.
"""
import importlib.util
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

spec=importlib.util.spec_from_file_location('libvirt_console_plan',Path(__file__).with_name('libvirt-console-plan.py'))
planner=importlib.util.module_from_spec(spec);spec.loader.exec_module(planner)


def require(condition,message):
    if not condition:raise ValueError(message)


def strict_json(value):
    def unique(pairs):
        result={}
        for key,value in pairs:
            require(key not in result,'duplicate generated JSON field')
            result[key]=value
        return result
    try:return json.loads(value,object_pairs_hook=unique)
    except (ValueError,TypeError):raise ValueError('invalid generated JSON option') from None


def verify(plan,state):
    require(planner.build_plan(plan['native_argv'],plan['run_id'])==plan,
            'plan differs from reviewed native intent')
    require(state['name']==plan['domain_name'] and state['uuid']==plan['uuid'] and
            state['run_id']==plan['run_id'] and state['persistent'] is False,
            'domain identity mismatch')
    require(type(state['domain_id']) is int and state['domain_id']>0,'missing live domain id')
    root=ET.fromstring(plan['xml'])
    custom=[node.attrib['value'] for node in root.findall('./{'+planner.NS+'}commandline/{'+planner.NS+'}arg')]
    memory=int(root.findtext('memory'))
    cpus=int(root.findtext('vcpu'))
    private='/home/arch/.config/libvirt/qemu/lib/domain-'+str(state['domain_id'])+'-'+plan['domain_name'][:20]
    secret={'qom-type':'secret','id':'masterKey0','format':'raw','file':private+'/master-key.aes'}
    ram={'qom-type':'memory-backend-ram','id':'pc.ram','size':memory*1024*1024}
    # JSON arguments are compared as typed maps, everything else in exact order.
    prefix=['/usr/sbin/qemu-system-x86_64','-name','guest='+plan['domain_name']+',debug-threads=on',
            '-S','-object',secret,
            '-machine','pc-q35-10.1,usb=off,dump-guest-core=off,memory-backend=pc.ram,acpi=on',
            '-accel','kvm','-cpu','Haswell-noTSX,vendor=GenuineIntel,invtsc=on',
            '-m','size='+str(memory*1024)+'k','-object',ram,'-overcommit','mem-lock=off',
            '-smp',f'{cpus},sockets=1,dies=1,clusters=1,cores={cpus},threads=1',
            '-uuid',plan['uuid'],'-no-user-config','-nodefaults','-chardev',None,
            '-mon','chardev=charmonitor,id=monitor,mode=control','-rtc','base=utc',
            '-no-shutdown','-boot','strict=on','-audiodev',{'id':'audio1','driver':'none'},
            '-spice','unix=on,addr=/run/vm/console-spice.sock,disable-ticketing=on,image-compression=off,seamless-migration=on',
            '-global','ICH9-LPC.noreboot=off','-watchdog-action','none']
    suffix=['-sandbox','on,obsolete=deny,elevateprivileges=deny,spawn=deny,resourcecontrol=deny',
            '-msg','timestamp=on']
    expected=prefix+custom+suffix
    argv=state['argv']
    require(isinstance(argv,list) and all(type(arg) is str for arg in argv) and len(argv)==len(expected),
            'generated command length or type mismatch')
    for index,(wanted,observed) in enumerate(zip(expected,argv)):
        if wanted is None:
            require(re.fullmatch(r'socket,id=charmonitor,fd=([0-9]+),server=on,wait=off',observed) is not None,
                    'unreviewed libvirt monitor endpoint')
            require(int(observed.split('fd=')[1].split(',')[0])>2,'invalid monitor descriptor')
        elif isinstance(wanted,dict):
            require(strict_json(observed)==wanted,'generated JSON configuration mismatch')
        else:
            # Do not include argument text: it may contain the private SMC key.
            require(wanted==observed,'generated command mismatch at argument '+str(index))
    return True


def verify_cpu_observations(plan,kvm,cpus,properties):
    count=int(ET.fromstring(plan['xml']).findtext('vcpu'))
    require(kvm=={'enabled':True,'present':True},'KVM not observed enabled')
    require(len(cpus)==count and sorted(c['cpu-index'] for c in cpus)==list(range(count)),
            'live CPU topology mismatch')
    paths=[cpu['qom-path'] for cpu in cpus]
    require(len(set(paths))==count and set(properties)==set(paths),'live CPU property ownership mismatch')
    expected={'vendor':'GenuineIntel','kvm':True,'invtsc':True,'vmware-cpuid-freq':True}
    require(all(properties[path]==expected for path in paths),'live CPU property mismatch')
    for cpu in cpus:
        props=dict(cpu['props'])
        require(props.pop('socket-id',None)==0 and props.pop('core-id',None)==cpu['cpu-index'] and
                props.pop('thread-id',None)==0 and all(key in ('die-id','cluster-id') and value==0
                                                        for key,value in props.items()),
                'live CPU socket/core/thread mismatch')
    return True
