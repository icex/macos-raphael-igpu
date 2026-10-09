#!/usr/bin/env python3
"""Container-side native libvirt controller; invoked only by the admitted profile.

Host supervisor owns exact CID/start, original deadline, serial drains and GPU
recovery. This process owns the private session and one transient paused domain.
"""
from contextlib import contextmanager
import importlib.util
import json
import math
import stat
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


def start_daemon(deadline):
    # The native launcher reached us through a PATH shim named like QEMU.
    # libvirt discovers emulator capabilities through PATH too: never let it
    # probe that controller shim. Keep private session XDG and other environment.
    environment=dict(os.environ)
    environment['PATH']='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
    subprocess.run(['libvirtd','--daemon'],env=environment,check=True,
                   timeout=min(10,max(.1,deadline-time.monotonic())))


def context():
    run_id=os.environ['RGPU_LIBVIRT_RUN_ID'];expected=os.environ['RGPU_LIBVIRT_ADMISSION_SHA256']
    directory=handoff.run_directory('/run/vm',run_id)
    admission=json.loads((directory/'admission.json').read_text())
    handoff.validate_admission(admission,run_id,expected,ROOT,
                              Path('/proc/sys/kernel/random/boot_id').read_text().strip())
    return directory,admission,expected


def validate_plan_refresh(plan,admission):
    expected=handoff.validate_refresh(admission.get('console_refresh','default'))
    planner=native.configuration.planner
    spice=planner.one(planner.pairs(plan['native_argv']),'-spice')
    wanted=planner.SPICE+(',max-refresh-rate=60' if expected=='60' else '')
    handoff.require(spice==wanted,'plan console refresh differs from admission')
    full=handoff.validate_full_refresh(admission.get('console_full_refresh','off'))
    bochs=[d for d in planner.values(planner.pairs(plan['native_argv']),'-device')
           if d.split(',')[0]=='bochs-display']
    snapshot=handoff.validate_snapshot(admission.get('console_snapshot','off'))
    handoff.require(snapshot == 'off' or (full == 'on' and expected == '60'),
                    'snapshot requires explicit SPICE60 full refresh')
    wanted_bochs=planner.BOCHS+(',x-debug-full-refresh=on' if full=='on' else '')
    if snapshot=='on': wanted_bochs+=',x-debug-snapshot=on'
    handoff.require(bochs==[wanted_bochs], 'plan console full refresh differs from admission')


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
    validate_plan_refresh(plan,admission)
    # Inspection never adopts, creates, resumes or destroys. Local snapshot reads
    # the independently addressed private domain in this exact docker exec CID.
    backend=native.local.LocalBackend('qemu:///session',directory/'inspection-events.jsonl')
    try:
        state=backend.snapshot(plan['domain_name'])
        state['audio_runtime_dir']=native.audio_environment(state['pid'])
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


class ExitProofRefusal(ValueError):
    def __init__(self,stage,code,**details):
        self.report=dict(stage=stage,code=code,**details)
        super().__init__(stage+': '+code)


@contextmanager
def exit_check(stage,**details):
    try:yield
    except ExitProofRefusal:raise
    except FileNotFoundError:
        if stage=='proc-scan':raise # Preserve disappearing-process handling.
        raise ExitProofRefusal(stage,'missing-file',**details) from None
    except Exception as error:
        code=('permission-denied' if isinstance(error,PermissionError) else
              'malformed-json' if isinstance(error,json.JSONDecodeError) else
              'missing-field' if isinstance(error,KeyError) else
              'validation-refused' if isinstance(error,ValueError) else 'inspection-error')
        if isinstance(error,OSError) and type(error.errno) is int:details['errno']=error.errno
        if code=='permission-denied' and 'pid' in details:
            try:
                uid=next(row for row in Path(f"/proc/{details['pid']}/status").read_text().splitlines() if row.startswith('Uid:'))
                details['process_uid']=int(uid.split()[1])
                details['process_euid']=int(uid.split()[2])
            except (OSError,ValueError,StopIteration):pass
        raise ExitProofRefusal(stage,code,**details) from None


def completed_original_zombie(identity, diagnostic=None):
    """Only a stable, exact, sole-thread zombie with no descriptors is complete.

    A zombie group leader alone is insufficient: surviving threads can retain
    the shared file table and VFIO ownership. Unknown proc visibility refuses.
    """
    pid=identity['pid'];root=Path(f'/proc/{pid}')
    def state():
        fields=(root/'stat').read_text().rsplit(')',1)[1].split()
        return int(fields[19]),fields[0]
    expected=(identity['start_ticks'],'Z')
    def refused(reason, **details):
        if diagnostic is not None:diagnostic.update(completion_reason=reason, **details)
        return False
    try:
        if state()!=expected:return refused('initial-state-changed')
        tasks={p.name for p in (root/'task').iterdir()}
        if tasks!={str(pid)}:
            # Bounded diagnostics only. Unknown/disappearing task details cannot
            # turn a non-sole leader into completion or delay the fatal path.
            samples=[]
            if diagnostic is not None:
                for tid in sorted(tasks)[:8]:
                    item=dict(tid=int(tid)) if tid.isdigit() else dict(tid=-1)
                    try:
                        fields=(root/'task'/tid/'stat').read_text().rsplit(')',1)[1].split()
                        item.update(state=fields[0],start_ticks=int(fields[19]))
                    except (OSError,ValueError,IndexError):item['state']='unknown'
                    samples.append(item)
            return refused('not-sole-task',completion_task_count=len(tasks),
                           completion_tasks=samples,completion_tasks_truncated=len(tasks)>8)
        if any((root/'fd').iterdir()):return refused('descriptors-present')
        if state()!=expected:return refused('final-state-changed')
        return True
    except FileNotFoundError:
        # Reaping during the check is also completion, but a reused PID is not.
        try:root.stat()
        except FileNotFoundError:return True
        return refused('incomplete-proc-view')


def guest_shutdown_before_eof(directory, identity, scope, eof_monotonic):
    """Eligibility before a recv transport boundary; never completion proof.

    The historical parameter name also covers separately classified recv reset.
    """
    handoff.require(type(eof_monotonic) in (int, float) and math.isfinite(eof_monotonic)
                    and 0 < eof_monotonic <= time.monotonic() < eof_monotonic + 2,
                    'invalid or expired EOF boundary')
    descriptor=os.open(directory/'events.jsonl', os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        metadata=os.fstat(descriptor)
        handoff.require(stat.S_ISREG(metadata.st_mode) and metadata.st_size <= 1048576,
                        'invalid lifecycle observation file')
        data=os.read(descriptor,1048577)
        handoff.require(len(data)<=1048576 and data.endswith(b'\n'), 'incomplete lifecycle observations')
    finally:os.close(descriptor)
    selected=None
    for line in data.splitlines():
        event=json.loads(line)
        if not isinstance(event,dict):raise ValueError('invalid lifecycle observation')
        if event.get('phase')!='libvirt-lifecycle-observed':continue
        stamp=event.get('observed_monotonic')
        if (event.get('identity_bound') is True and event.get('guest_shutdown') is True and
            event.get('event')==6 and event.get('detail')==1 and
            event.get('identity')==identity and event.get('scope')==scope and
            event.get('name')==identity['name'] and event.get('uuid')==identity['uuid'] and
            type(stamp) in (int,float) and math.isfinite(stamp) and
            0 <= eof_monotonic-stamp <= 2):selected=stamp
    handoff.require(selected is not None,'no bound guest shutdown preceding EOF')
    return selected


def inspect_exited(eof_monotonic=None):
    """Read-only proof; refusal diagnostics never expose argv, paths or exception text."""
    with exit_check('admission'):
        directory,admission,expected=context()
    with exit_check('receipt-read'):
        plan=json.loads((directory/'plan.json').read_text())
        paused=json.loads((directory/'paused.json').read_text())
        permit=json.loads((directory/'resume.json').read_text())
        running=json.loads((directory/'running.json').read_text())
    with exit_check('permit-binding'):
        handoff.validate_permit(permit,admission,expected,paused)
    with exit_check('plan-binding'):
        validate_plan_refresh(plan,admission)
        identity=paused['identity'];scope=paused['scope']
        handoff.require(paused['paused'] is True and paused['run_id']==admission['run_id'] and
                        plan['run_id']==admission['run_id'] and
                        runtime.digest(plan)==paused['plan_sha256'], 'exited plan binding changed')
        handoff.require(identity['name']==plan['domain_name'] and identity['uuid']==plan['uuid'] and
                        identity['run_id']==admission['run_id'] and
                        type(identity['pid']) is int and identity['pid']>1 and
                        type(identity['start_ticks']) is int and identity['start_ticks']>0,
                        'exited process identity invalid')
    with exit_check('running-binding'):
        handoff.require(running['run_id']==admission['run_id'] and running['identity']==identity and
                        running['scope']==scope and running['plan_sha256']==paused['plan_sha256'] and
                        running['cid']==permit['cid'] and running['started_at']==permit['started_at'],
                        'exited running/paused/permit binding changed')
    with exit_check('namespace'):
        handoff.require(native.local.namespace_identity()==scope,'exited PID namespace changed')
    completed_zombie=False
    shutdown_wait=False
    shutdown_observed=None
    with exit_check('original-process',pid=identity['pid']):
        current=native.local.process(identity['pid'])
        if current is not None and current['start_ticks']==identity['start_ticks']:
            state='unknown'
            try:
                raw=Path(f"/proc/{identity['pid']}/stat").read_text().rsplit(')',1)[1].split()[0]
                if raw in tuple('RSDTtZXIPKW'):state=raw
            except (OSError,IndexError):pass
            completion={}
            completed_zombie=state=='Z' and completed_original_zombie(identity,completion)
            if not completed_zombie:
                if (eof_monotonic is not None and state=='Z' and
                    completion.get('completion_reason')=='not-sole-task'):
                    with exit_check('shutdown-event'):
                        shutdown_observed=guest_shutdown_before_eof(directory,identity,scope,eof_monotonic)
                    shutdown_wait=True
                else:
                    raise ExitProofRefusal('original-process','original-pid-present',pid=identity['pid'],state=state,**completion)
    # Only the exact original completed/pending zombie is skipped here and
    # rechecked below. Other QEMU and unknown visibility retain refusal.
    with exit_check('proc-list'):
        paths=list(Path('/proc').iterdir())
    for path in paths:
        if not path.name.isdigit():continue
        pid=int(path.name)
        try:
            if shutdown_wait and pid==identity['pid']:
                continue # Exact original is rechecked after the complete visibility scan.
            if completed_zombie and pid==identity['pid']:
                with exit_check('original-process',pid=pid):
                    completion={}
                    if not completed_original_zombie(identity,completion):
                        raise ExitProofRefusal('original-process','original-pid-present',pid=pid,state='Z',**completion)
                continue
            with exit_check('proc-scan',pid=pid,operation='comm'):
                comm=(path/'comm').read_text().strip()
            if comm.startswith('qemu-system'):
                raise ExitProofRefusal('proc-scan','other-qemu',pid=pid)
            if path.name=='1' and comm in ('docker-init','tini'):
                continue # Scoped namespace/init identity was matched above.
            with exit_check('proc-scan',pid=pid,operation='exe'):
                executable=os.path.basename(os.readlink(path/'exe'))
            if executable.startswith('qemu-system'):
                raise ExitProofRefusal('proc-scan','other-qemu',pid=pid)
        except FileNotFoundError:continue
    if completed_zombie:
        with exit_check('original-process',pid=identity['pid']):
            completion={}
            if not completed_original_zombie(identity,completion):
                raise ExitProofRefusal('original-process','original-pid-present',pid=identity['pid'],state='Z',**completion)
    if shutdown_wait:
        with exit_check('original-process',pid=identity['pid']):
            completion={}
            completed_zombie=completed_original_zombie(identity,completion)
            if completed_zombie:shutdown_wait=False
            elif completion.get('completion_reason')!='not-sole-task':
                raise ExitProofRefusal('original-process','original-pid-present',pid=identity['pid'],**completion)
        with exit_check('shutdown-event'):
            shutdown_observed=guest_shutdown_before_eof(directory,identity,scope,eof_monotonic)
    return dict(exited=not shutdown_wait,shutdown_wait=shutdown_wait,
                shutdown_observed_monotonic=shutdown_observed,transport_end_monotonic=eof_monotonic,
                completed_zombie=completed_zombie,run_id=admission['run_id'],admission_sha256=expected,
                identity=identity,scope=scope,plan_sha256=paused['plan_sha256'],
                cid=permit['cid'],started_at=permit['started_at'],
                deadline_epoch=admission['deadline_epoch'])


def inspect_exited_report(eof_monotonic=None):
    try:return inspect_exited(eof_monotonic)
    except ExitProofRefusal as error:return dict(exited=False,refusal=error.report)


def launch(argv):
    directory,admission,admission_digest=context()
    dependency_check()
    handoff.require(os.getppid()==1 and Path('/proc/1/comm').read_text().strip() in ('docker-init','tini'),
                    'libvirt profile requires container init reaping')
    deadline=time.monotonic()+admission['deadline_epoch']-time.time()
    # Private evidence preserves fully expanded launcher input without printing
    # AppleSMC or machine identity in diagnostics. Planning is still pure.
    handoff.write_once(directory/'native-argv.json',argv)
    try:
        plan=native.configuration.planner.build_plan(argv,admission['run_id'])
        validate_plan_refresh(plan,admission)
    except Exception as error:
        handoff.write_once(directory/'planning-failure.json',dict(
            run_id=admission['run_id'],phase='before-libvirtd-and-qemu',
            error_type=type(error).__name__,error=str(error)))
        raise
    handoff.write_once(directory/'plan.json',plan)
    os.environ['XDG_RUNTIME_DIR']=str(directory/'runtime')
    (directory/'runtime').mkdir(mode=0o700)
    stopped=[]
    def stop(signum,frame):stopped.append(signum)
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    backend=owner=None
    start_daemon(deadline)
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
    elif command=='inspect-exited':
        if len(sys.argv)>3:raise ValueError('invalid exit arguments')
        eof=float(sys.argv[2]) if len(sys.argv)==3 else None
        print(json.dumps(inspect_exited_report(eof)))
    elif command=='launch':launch(sys.argv[2:])
    else:raise ValueError('invalid controller command')

if __name__=='__main__':main()
