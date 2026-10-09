#!/usr/bin/env python3
"""Container-side native libvirt controller; invoked only by the admitted profile.

Host supervisor owns exact CID/start, original deadline, serial drains and GPU
recovery. This process owns the private session and one transient paused domain.
"""
import importlib.util
import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parent

def module(name):
    spec=importlib.util.spec_from_file_location('console_'+name,ROOT/('libvirt-console-'+name+'.py'))
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result

handoff=module('handoff');runtime=module('runtime');native=module('native')


def dependency_check():
    import libvirt
    import libvirt_qemu
    handoff.require(libvirt.getVersion()==11009000 and
                    callable(getattr(libvirt_qemu,'qemuMonitorCommandWithFiles',None)),
                    'unreviewed libvirt runtime or missing descriptor API')
    for name in ('libvirtd','virtlogd'):
        handoff.require(shutil.which(name) is not None,'missing libvirt service dependency')
    version=subprocess.check_output(['/usr/sbin/qemu-system-x86_64','--version'],text=True,timeout=3)
    handoff.require(version.startswith('QEMU emulator version 10.1.2'),'unreviewed QEMU runtime')


def context():
    run_id=os.environ['RGPU_LIBVIRT_RUN_ID'];expected=os.environ['RGPU_LIBVIRT_ADMISSION_SHA256']
    directory=handoff.run_directory('/run/vm',run_id)
    admission=json.loads((directory/'admission.json').read_text())
    handoff.validate_admission(admission,run_id,expected,ROOT,
                              Path('/proc/sys/kernel/random/boot_id').read_text().strip())
    return directory,admission,expected


def paused_observation(backend,plan,state):
    native.verify(plan,state)
    handoff.require(state['running'] is False and state['status'] in ('paused','prelaunch'),
                    'guest executed before host release')
    identity={key:state[key] for key in ('name','uuid','run_id','pid','start_ticks')}
    return dict(run_id=plan['run_id'],plan_sha256=runtime.digest(plan),paused=True,
                identity=identity,scope=backend.container_identity(),domain_id=state['domain_id'],
                argv_sha256=handoff.sha(('\0'.join(state['argv'])+'\0').encode()))


def inspect_domain(paused=True):
    directory,admission,_=context()
    os.environ['XDG_RUNTIME_DIR']=str(directory/'runtime')
    plan=json.loads((directory/'plan.json').read_text())
    # Inspection never adopts, creates, resumes or destroys. Local snapshot reads
    # the independently addressed private domain in this exact docker exec CID.
    backend=native.local.LocalBackend('qemu:///session',directory/'inspection-events.jsonl')
    try:
        state=backend.snapshot(plan['domain_name'])
        state['kvm']=backend.qmp(plan['domain_name'],'query-kvm',{})
        state['cpus']=backend.qmp(plan['domain_name'],'query-cpus-fast',{})
        state['cpu_properties']={cpu['qom-path']:{prop:backend.qmp(plan['domain_name'],'qom-get',
            dict(path=cpu['qom-path'],property=prop)) for prop in
            ('vendor','kvm','invtsc','vmware-cpuid-freq')} for cpu in state['cpus']}
        if paused:
            result=paused_observation(backend,plan,state)
        else:
            native.verify(plan,state)
            running=json.loads((directory/'running.json').read_text())
            identity={key:state[key] for key in ('name','uuid','run_id','pid','start_ticks')}
            handoff.require(running['identity']==identity and running['scope']==backend.container_identity() and
                            running['plan_sha256']==runtime.digest(plan) and state['running'] is True,
                            'running domain differs from admitted owner')
            result=dict(verified=True,run_id=plan['run_id'],identity=identity,
                        plan_sha256=runtime.digest(plan),cid=running['cid'],started_at=running['started_at'],
                        argv_sha256=handoff.sha(('\0'.join(state['argv'])+'\0').encode()))
        print(json.dumps(result))
    finally:backend.close()


def launch(argv):
    directory,admission,admission_digest=context()
    dependency_check()
    handoff.require(os.getppid()==1 and Path('/proc/1/comm').read_text().strip() in ('docker-init','tini'),
                    'libvirt profile requires container init reaping')
    deadline=time.monotonic()+admission['deadline_epoch']-time.time()
    plan=native.configuration.planner.build_plan(argv,admission['run_id'])
    handoff.write_once(directory/'plan.json',plan)
    os.environ['XDG_RUNTIME_DIR']=str(directory/'runtime')
    (directory/'runtime').mkdir(mode=0o700)
    stopped=[]
    def stop(signum,frame):stopped.append(signum)
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    backend=owner=None
    subprocess.run(['libvirtd','--daemon'],check=True,timeout=min(10,max(.1,deadline-time.monotonic())))
    daemon_pid=int((directory/'runtime/libvirt/libvirtd.pid').read_text())
    daemon=native.local.process(daemon_pid)
    handoff.require(daemon is not None,'libvirt daemon ownership missing')
    try:
        backend=native.NativeBackend('qemu:///session',directory/'events.jsonl',plan,admission['network'],3)
        owner=runtime.PausedDomain(backend,plan,runtime.digest(plan),native.local.namespace_identity(),native.verify)
        state=owner.prepare(3)
        paused=paused_observation(backend,plan,state)
        handoff.write_once(directory/'paused.json',paused)
        until=min(deadline,time.monotonic()+120)
        while not (directory/'resume.json').exists():
            handoff.require(not stopped and time.monotonic()<until,'host resume handoff stopped or expired')
            time.sleep(.1)
        permit=json.loads((directory/'resume.json').read_text())
        handoff.validate_permit(permit,admission,admission_digest,paused)
        handoff.require(not stopped and time.monotonic()<deadline,'launch deadline reached before resume')
        owner.resume()
        handoff.write_once(directory/'running.json',dict(run_id=plan['run_id'],
                           identity=owner.identity,scope=backend.container_identity(),
                           plan_sha256=runtime.digest(plan),cid=permit['cid'],started_at=permit['started_at']))
        reason=runtime.monitor(owner,deadline,lambda:bool(stopped))
        handoff.write_once(directory/'terminal.json',dict(run_id=plan['run_id'],reason=reason,
                           identity=owner.identity,scope=backend.container_identity(),
                           process_exited=backend.process_gone(owner.identity),
                           cid=permit['cid'],started_at=permit['started_at']))
    finally:
        if owner is not None and not owner.finished:owner.cleanup('controller-finally')
        if backend is not None:backend.close()
        current=native.local.process(daemon_pid)
        if current is not None and current['start_ticks']==daemon['start_ticks']:
            try:os.kill(daemon_pid,signal.SIGTERM)
            except ProcessLookupError:pass
        # The container exits with this process; no daemon keeps the VM alive.


def main():
    command=sys.argv[1] if len(sys.argv)>1 else ''
    if command=='preflight':
        context();dependency_check()
    elif command=='inspect-paused':inspect_domain()
    elif command=='inspect-running':inspect_domain(paused=False)
    elif command=='launch':launch(sys.argv[2:])
    else:raise ValueError('invalid controller command')

if __name__=='__main__':main()
