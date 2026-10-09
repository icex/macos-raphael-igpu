#!/usr/bin/env python3
"""Native console backend composition. No standalone launch/admission bypass."""
import copy
import importlib.util
import time
from pathlib import Path


def module(name):
    path=Path(__file__).with_name('libvirt-console-'+name+'.py')
    spec=importlib.util.spec_from_file_location('console_'+name,path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result

local=module('local');network=module('network');configuration=module('verify')

def audio_environment(pid):
    rows=Path(f'/proc/{pid}/environ').read_bytes().split(b'\0')
    values=[row.split(b'=',1)[1] for row in rows if row.startswith(b'XDG_RUNTIME_DIR=')]
    if values!=[b'/xdgrt']:
        raise ValueError('QEMU audio runtime directory differs from mounted PulseAudio path')
    return '/xdgrt'


class NativeBackend(local.LocalBackend):
    def __init__(self,uri,event_path,plan,network_receipt,inherited_fd):
        if inherited_fd!=3 or plan['required_lan_fd']!=3:
            raise ValueError('native LAN must inherit descriptor3')
        self.lan_fd=inherited_fd
        self.network_receipt=copy.deepcopy(network_receipt)
        self.cpu_cache=None
        devices=configuration.planner.values(configuration.planner.pairs(plan['native_argv']),'-device')
        lan=[d for d in devices if d.startswith('vmxnet3,netdev=lan0,id=lan0,mac=')]
        if len(lan)!=1 or lan[0].split('mac=')[1]!=network_receipt['mac']:
            raise ValueError('planned LAN differs from admitted host MAC')
        self.inherited=network.verify_inherited(inherited_fd,network_receipt)
        super().__init__(uri,event_path)

    def _snapshot(self,name):
        state=super()._snapshot(name)
        state['audio_runtime_dir']=audio_environment(state['pid'])
        key=(state['pid'],state['start_ticks'],state['running'])
        if self.cpu_cache is not None and self.cpu_cache[0]==key and time.monotonic()<self.cpu_cache[1]:
            state.update(copy.deepcopy(self.cpu_cache[2]))
            return state
        state['kvm']=self.qmp(name,'query-kvm',{})
        state['cpus']=self.qmp(name,'query-cpus-fast',{})
        state['cpu_properties']={cpu['qom-path']:{prop:self.qmp(name,'qom-get',
            {'path':cpu['qom-path'],'property':prop}) for prop in
            ('vendor','kvm','invtsc','vmware-cpuid-freq')} for cpu in state['cpus']}
        self.cpu_cache=(key,time.monotonic()+30,copy.deepcopy({k:state[k] for k in ('kvm','cpus','cpu_properties')}))
        return state

    def network_attached(self,name,hub):
        current=network.verify_inherited(self.lan_fd,self.network_receipt)
        if any(current[k]!=self.inherited[k] for k in ('name','mac','character','device','inode')):
            raise ValueError('inherited LAN descriptor changed')
        state=self.snapshot(name)
        report=self.qmp(name,'human-monitor-command',{'command-line':'info network'})
        qemu_fd=network.verify_network_report(report,self.network_receipt['mac'],hub)
        network.verify_qemu_descriptor(state['pid'],qemu_fd,current)
        self.record(dict(phase='network-observed',name=name,pid=state['pid'],
                         start_ticks=state['start_ticks'],qemu_fd=qemu_fd,inherited=current))
        return True


def verify(plan,state):
    if state.get('audio_runtime_dir')!='/xdgrt':
        raise ValueError('QEMU audio environment was not verified')
    configuration.verify(plan,state)
    configuration.verify_cpu_observations(plan,state['kvm'],state['cpus'],state['cpu_properties'])
    return True
