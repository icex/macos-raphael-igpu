#!/usr/bin/env python3
"""Real libvirt/QEMU failure tests. Hard restricted to a device-free TCG container.

This research adapter is not a hardware launcher or a production configuration
verifier. The only accepted network FD is deliberately invalid for TAP creation.
"""
import importlib.util
import json
import os
from pathlib import Path
import secrets
import subprocess
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
RUN = Path.home()/'macos-vm/run/c341-runtime-smoke'
CONTAINER = 'rgpu-c341-runtime-smoke'
URI = 'qemu+unix:///session?socket='+str(RUN/'runtime/libvirt/libvirt-sock')
spec = importlib.util.spec_from_file_location('runtime', ROOT/'tools/libvirt-console-runtime.py')
runtime = importlib.util.module_from_spec(spec); spec.loader.exec_module(runtime)


def command(args, **kwargs):
    return subprocess.check_output(args, text=True, timeout=20, **kwargs)


def process(pid):
    try:
        stat = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        argv = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
        return {'pid':pid, 'start_ticks':int(stat[19]), 'argv':[x.decode() for x in argv if x]}
    except FileNotFoundError:
        return None


class SoftwareBackend:
    def __init__(self):
        self.expected = self.container_identity()
        self.inject = None
        self.created = False
        self.plan = None
        self.failures = []

    def container_identity(self):
        item = json.loads(command(['docker','inspect',CONTAINER]))[0]
        assert item['State']['Running']
        assert not item['HostConfig']['Privileged'] and not item['HostConfig']['Devices']
        assert item['HostConfig']['NetworkMode']=='none'
        return {'cid':item['Id'],'started_at':item['State']['StartedAt']}

    def guard(self):
        assert self.container_identity()==self.expected

    def virsh(self, *args, **kwargs):
        self.guard()
        return command(['virsh','-c',URI,*args], **kwargs)

    def domains(self):
        return self.virsh('list','--all','--name').split()

    def processes(self):
        self.guard()
        rows = command(['docker','top',CONTAINER,'-eo','pid,comm']).splitlines()[1:]
        return [int(row.split()[0]) for row in rows if row.split()[1].startswith('qemu-system')]

    def create_paused(self, xml):
        assert not self.domains() and not self.processes()
        (RUN/'domain.xml').write_text(xml)
        self.virsh('create','--paused',str(RUN/'domain.xml'))
        self.created = True
        if self.inject=='create-reply':
            self.inject=None
            raise TimeoutError('injected loss of successful real create reply')

    def qmp(self,name,cmd,args,fd=None):
        argv=['qemu-monitor-command',name]
        if fd is not None:argv+=['--pass-fds',str(fd)]
        argv += [json.dumps({'execute':cmd,'arguments':args})]
        response=json.loads(self.virsh(*argv,pass_fds=() if fd is None else (fd,)))
        if 'error' in response:
            self.failures.append(response['error'])
            raise RuntimeError(json.dumps(response['error']))
        return response['return']

    def snapshot(self,name):
        if self.inject=='first-snapshot':
            self.inject=None
            raise TimeoutError('injected first snapshot loss')
        xml=ET.fromstring(self.virsh('dumpxml',name))
        pids=self.processes();assert len(pids)==1
        proc=process(pids[0]);assert proc is not None
        assert any(arg.startswith('guest='+name+',') for arg in proc['argv'])
        assert not any('vfio' in arg for arg in proc['argv'])
        assert '-accel' in proc['argv'] and proc['argv'][proc['argv'].index('-accel')+1]=='tcg'
        status=self.qmp(name,'query-status',{})
        assert self.qmp(name,'query-name',{})['name']==name
        return dict(name=xml.findtext('name'),uuid=xml.findtext('uuid'),
                    run_id=xml.find('metadata/{urn:raphaelgpu:experiment}run').get('id'),
                    persistent=name in self.virsh('list','--all','--persistent','--name').split(),
                    pid=proc['pid'],start_ticks=proc['start_ticks'],argv=proc['argv'],**status)

    def reconcile_creation(self,plan):
        # This adapter only injects loss after an observed successful create reply.
        # It does not claim to reconcile an arbitrary production timeout.
        assert self.created and self.plan==plan
        state=self.snapshot(plan['domain_name'])
        return dict(outcome='created',identity={k:state[k] for k in ('name','uuid','run_id','pid','start_ticks')})

    def process_gone(self,identity):
        current=process(identity['pid'])
        return current is None or current['start_ticks']!=identity['start_ticks']

    def session_processes_gone(self):
        return not self.processes()

    def destroy_owned(self,identity):
        state=self.snapshot(identity['name'])
        assert all(state[k]==v for k,v in identity.items())
        self.virsh('destroy',identity['name'])
        deadline=time.monotonic()+5
        while not self.process_gone(identity) and time.monotonic()<deadline:time.sleep(.05)
        assert self.process_gone(identity)

    def network_attached(self,name,hub):
        raise AssertionError('invalid TAP descriptor must never reach network-ready')

    def record(self,event):
        with (RUN/'events.jsonl').open('a') as f:
            f.write(json.dumps(event)+'\n');f.flush();os.fsync(f.fileno())


def plan():
    run_id=secrets.token_hex(16);name='rgpu-'+run_id
    xml=f'''<domain type="qemu" xmlns:qemu="http://libvirt.org/schemas/domain/qemu/1.0">
<name>{name}</name><uuid>00000000-0000-0000-0000-000000000000</uuid>
<metadata><r:run xmlns:r="urn:raphaelgpu:experiment" id="{run_id}"/></metadata>
<memory unit="MiB">128</memory><vcpu>1</vcpu>
<os><type arch="x86_64" machine="q35">hvm</type></os>
<on_poweroff>destroy</on_poweroff><on_reboot>destroy</on_reboot><on_crash>destroy</on_crash>
<devices><emulator>/usr/sbin/qemu-system-x86_64</emulator>
<controller type="usb" model="none"/><memballoon model="none"/><video><model type="none"/></video>
<audio id="1" type="none"/></devices>
<qemu:commandline><qemu:arg value="-netdev"/><qemu:arg value="hubport,id=lan0,hubid=0"/>
<qemu:arg value="-device"/><qemu:arg value="vmxnet3,id=lan,netdev=lan0,bus=pcie.0,addr=0x9"/></qemu:commandline>
</domain>'''
    return dict(run_id=run_id,domain_name=name,uuid='00000000-0000-0000-0000-000000000000',
                xml=xml,required_launch='transient-paused',resume_allowed=False,lan_hub=0)


def main():
    results=[]
    for injection in [None,'create-reply','first-snapshot']:
        backend=SoftwareBackend();intent=plan();backend.plan=intent;backend.inject=injection
        owner=runtime.PausedDomain(backend,intent,runtime.digest(intent),backend.expected,
                                  lambda p,s:s['argv'].count('-accel')==1)
        fd=os.open('/dev/null',os.O_RDWR)
        try:
            try:owner.prepare(fd)
            except (RuntimeError,TimeoutError) as error:failure=str(error)
            else:raise AssertionError('invalid network descriptor unexpectedly succeeded')
            assert owner.finished and not owner.resume_attempted
            assert not backend.domains() and backend.session_processes_gone()
            assert owner.events[-1]['phase']=='stopped'
            if injection is None:
                assert backend.failures and 'TUNGETIFF' in failure
            results.append(dict(injection=injection,error=failure,identity=owner.identity,
                                phases=[e['phase'] for e in owner.events],
                                paused_until_failure=True,process_exited=True))
        finally:
            os.close(fd)
            if not owner.finished:owner.cleanup('test-finally')
    result=dict(passed=True,cases=results,container=backend.expected,
                scope='TCG device-free container; invalid TAP backend and injected observation losses. No valid TAP, KVM, VFIO or macOS.')
    (RUN/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))

if __name__=='__main__':main()
