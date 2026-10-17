#!/usr/bin/env python3
"""Container-local libvirt backend; caller owns admission, daemon and outer timer.

No launch CLI. Full native-profile argv verification is supplied to PausedDomain
by its admitted caller. This backend must only run in a dedicated PID namespace
and private libvirt session. It never opens a GPU or changes PCI bindings itself.
"""
from collections import deque
import json
import os
from pathlib import Path
import re
import threading
import time
import xml.etree.ElementTree as ET


def process(pid):
    try:
        stat=Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()
        argv=Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
        return dict(pid=pid,start_ticks=int(stat[19]),argv=[x.decode() for x in argv if x])
    except FileNotFoundError:
        return None


def namespace_identity():
    ns=Path('/proc/self/ns/pid').stat()
    return dict(kind='pid-namespace',device=ns.st_dev,inode=ns.st_ino,
                init_start_ticks=process(1)['start_ticks'])


class DomainExited(RuntimeError):
    pass


class MissingProcess(RuntimeError):
    pass


class LocalBackend:
    def __init__(self, uri, event_path):
        import libvirt
        import libvirt_qemu
        self.lv=libvirt;self.lq=libvirt_qemu
        self.scope=namespace_identity()
        self.event_path=Path(event_path)
        self.record_lock=threading.Lock()
        self.pending=deque()
        self.attempt=None
        self.known_identity=None
        self.event_error=None
        libvirt.virEventRegisterDefaultImpl()
        self.conn=libvirt.open(uri)
        if self.conn is None:raise RuntimeError('private libvirt session unavailable')
        self.callback=self.conn.domainEventRegisterAny(None,libvirt.VIR_DOMAIN_EVENT_ID_LIFECYCLE,
                                                      self.lifecycle,None)
        # Register synchronously before creation; dispatch callbacks concurrently
        # so a short-lived guest's terminal event is not lost between RPCs.
        self.thread=threading.Thread(target=self.dispatch,daemon=True)
        self.thread.start()

    def dispatch(self):
        try:
            while True:self.lv.virEventRunDefaultImpl()
        except BaseException as error:
            self.event_error=error

    def lifecycle(self,conn,domain,event,detail,opaque):
        observed=dict(name=domain.name(),uuid=domain.UUIDString(),
                      event=event,detail=detail)
        # Persist at callback arrival, not only after domain disappearance. This
        # is observation, never authorization to ignore capture loss or workers.
        try:
            identity=dict(self.known_identity) if self.known_identity else None
            bound=bool(identity and self.attempt and
                       all(identity.get(k)==v for k,v in self.attempt.items()) and
                       observed['name']==identity['name'] and observed['uuid']==identity['uuid'])
            self.record(dict(phase='libvirt-lifecycle-observed',**observed,
                observed_epoch=time.time(),observed_monotonic=time.monotonic(),
                identity_bound=bound,identity=identity if bound else None,
                scope=dict(self.scope),
                guest_shutdown=bool(bound and event==self.lv.VIR_DOMAIN_EVENT_SHUTDOWN and
                                    detail==self.lv.VIR_DOMAIN_EVENT_SHUTDOWN_GUEST)))
        except BaseException as error:
            self.event_error=error
        self.pending.append(observed)

    def container_identity(self):return namespace_identity()

    def guard(self):
        if namespace_identity()!=self.scope:raise RuntimeError('container namespace changed')

    def health_check(self):
        if self.event_error is not None:raise RuntimeError('libvirt event dispatcher failed') from self.event_error

    def domains(self):
        self.guard()
        return [d.name() for d in self.conn.listAllDomains()]

    def processes(self):
        self.guard()
        result=[]
        for path in Path('/proc').iterdir():
            if not path.name.isdigit():continue
            proc=process(int(path.name))
            if proc and proc['argv'] and Path(proc['argv'][0]).name.startswith('qemu-system'):
                result.append(proc)
        return result

    def create_paused(self, xml):
        self.guard()
        if self.attempt is not None or self.domains() or self.processes():
            raise RuntimeError('private session is not unused')
        root=ET.fromstring(xml)
        self.attempt=dict(name=root.findtext('name'),uuid=root.findtext('uuid'),
                          run_id=root.find('metadata/{urn:raphaelgpu:experiment}run').get('id'))
        self.conn.createXML(xml,self.lv.VIR_DOMAIN_START_PAUSED)

    def qmp(self,name,cmd,args,fd=None):
        self.guard();domain=self.conn.lookupByName(name)
        # Resume is a libvirt-owned state transition. Keep its state tracking intact.
        if cmd=='cont':
            self.health_check()
            if fd is not None or args:raise ValueError('invalid resume request')
            domain.resume();return {}
        payload=json.dumps(dict(execute=cmd,arguments=args))
        if fd is None:
            raw=self.lq.qemuMonitorCommand(domain,payload,0)
        else:
            raw,files=self.lq.qemuMonitorCommandWithFiles(domain,payload,[fd],0)
            if files:
                for file in files:file.close()
                raise RuntimeError('unexpected returned QMP descriptors')
        response=json.loads(raw)
        if 'error' in response:raise RuntimeError(json.dumps(response['error']))
        return response['return']

    def snapshot(self,name):
        try:
            return self._snapshot(name)
        except (self.lv.libvirtError, MissingProcess) as error:
            identity=self.known_identity
            if identity is None or identity['name']!=name:
                raise
            until=time.monotonic()+0.5
            while time.monotonic()<until:
                if name not in self.domains() and self.process_gone(identity):
                    raise DomainExited(name) from error
                time.sleep(0.02)
            raise

    def _snapshot(self,name):
        self.guard();domain=self.conn.lookupByName(name)
        root=ET.fromstring(domain.XMLDesc(0))
        selected=[p for p in self.processes() if any(a.startswith('guest='+name+',') for a in p['argv'])]
        if not selected:raise MissingProcess('domain process disappeared')
        if len(selected)!=1:raise RuntimeError('domain process is not unique')
        proc=selected[0]
        result=dict(name=root.findtext('name'),uuid=root.findtext('uuid'),
                    run_id=root.find('metadata/{urn:raphaelgpu:experiment}run').get('id'),
                    persistent=bool(domain.isPersistent()),domain_id=domain.ID(),**proc,
                    **self.qmp(name,'query-status',{}))
        identity={k:result[k] for k in ('name','uuid','run_id','pid','start_ticks')}
        if self.attempt and all(identity[k]==v for k,v in self.attempt.items()):
            if self.known_identity is None:self.known_identity=identity
        return result

    def reconcile_creation(self,plan):
        if self.attempt != {k:plan[v] for k,v in (('name','domain_name'),('uuid','uuid'),('run_id','run_id'))}:
            raise RuntimeError('unowned create transaction')
        if plan['domain_name'] in self.domains():
            state=self.snapshot(plan['domain_name'])
            identity={k:state[k] for k in ('name','uuid','run_id','pid','start_ticks')}
            if self.known_identity is not None and identity!=self.known_identity:
                raise RuntimeError('created process replaced')
            return dict(outcome='created',identity=identity)
        # No arbitrary timeout can be called settled from one empty observation.
        raise RuntimeError('create outcome cannot be reconciled from domain absence')

    def session_processes_gone(self):return not self.processes()

    def process_gone(self,identity):
        self.guard();current=process(identity['pid'])
        return current is None or current['start_ticks']!=identity['start_ticks']

    def destroy_owned(self,identity):
        state=self.snapshot(identity['name'])
        if any(state[k]!=v for k,v in identity.items()):raise RuntimeError('domain process replaced')
        self.guard();self.conn.lookupByName(identity['name']).destroy()
        deadline=time.monotonic()+5
        while not self.process_gone(identity) and time.monotonic()<deadline:time.sleep(.05)
        if not self.process_gone(identity):raise RuntimeError('QEMU survived domain destruction')

    def network_attached(self,name,hub):
        # Return evidence to an explicit profile-specific verifier, never make a
        # production claim from substring presence or requested XML alone.
        raise NotImplementedError('admitted TAP provenance/topology verifier required')

    def record(self,event):
        with self.record_lock:
            with self.event_path.open('a') as stream:
                stream.write(json.dumps(event)+'\n');stream.flush();os.fsync(stream.fileno())

    def is_missing_domain_error(self,error):
        return (isinstance(error,DomainExited) or
                isinstance(error,self.lv.libvirtError) and error.get_error_code()==self.lv.VIR_ERR_NO_DOMAIN)

    def exit_reason(self,name,deadline):
        self.guard();reason='domain-exited-unknown'
        drain_until=min(deadline,time.monotonic()+0.5)
        while self.pending or time.monotonic()<drain_until:
            if not self.pending:
                time.sleep(min(0.02,max(0,drain_until-time.monotonic())))
                continue
            event=self.pending.popleft();self.record(dict(phase='libvirt-lifecycle',**event))
            if event['name']!=name or event['uuid']!=self.attempt['uuid']:continue
            if event['event']==self.lv.VIR_DOMAIN_EVENT_STOPPED:
                reason={self.lv.VIR_DOMAIN_EVENT_STOPPED_SHUTDOWN:'guest-shutdown',
                        self.lv.VIR_DOMAIN_EVENT_STOPPED_DESTROYED:'manager-destroyed',
                        self.lv.VIR_DOMAIN_EVENT_STOPPED_CRASHED:'domain-crashed'}.get(event['detail'],reason)
                break
        return reason

    def close(self):
        self.conn.domainEventDeregisterAny(self.callback)
        self.conn.close()
