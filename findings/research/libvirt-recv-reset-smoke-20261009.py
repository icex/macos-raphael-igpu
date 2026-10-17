#!/usr/bin/env python3
"""Actual entry handoff + serial EOF guard, software TCG/TAP only."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import time

ROOT=Path(__file__).resolve().parents[2]
IMAGE='sha256:3a3c82c79bc4e73531f819ccdfa4053b3084efd7c1f645678dbf8b4b3a24369c'
def module(name,file):
    spec=importlib.util.spec_from_file_location(name,ROOT/'tools'/file)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result
handoff=module('handoff','libvirt-console-handoff.py');supervisor=module('supervisor','vm-supervision.py')
def command(argv,timeout=20,check=True):return subprocess.run(argv,text=True,capture_output=True,timeout=timeout,check=check)
def wait_file(path):
    until=time.monotonic()+30
    while not path.exists():
        if time.monotonic()>until:raise RuntimeError('fixture file deadline: '+path.name)
        time.sleep(.03)
    return json.loads(path.read_text())

def main():
    base=Path.home()/'macos-vm/run'/('c356-reset-'+secrets.token_hex(4));base.mkdir(mode=0o700);records=[]
    for case in ('guest-s5-reset','live-qemu-reset'):
        vm=base/case;vm.mkdir();run=vm/'run';run.mkdir();rid=secrets.token_hex(16)
        shutil.copyfile(Path.home()/'macos-vm/run/c341-entry-valid-2ac1ff25/boot.img',run/'boot.img')
        bootstrap=Path.home()/'macos-vm/run/c341-entry-valid-2ac1ff25/bootstrap.py'
        shutil.copyfile(bootstrap,run/'bootstrap.py')
        manifest=dict(run_id=rid,boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),image_id=IMAGE,max_seconds=120,launch_options=dict(VM_MANAGER='libvirt'))
        hashes={name:handoff.sha((ROOT/'tools'/name).read_bytes()) for name in handoff.MODULES}
        directory,digest=handoff.prepare(run,manifest,json.dumps(manifest).encode(),{'software_fixture':True},hashes)
        cid=None;console=None;collector=None;reset_peer=None;reset_client=None
        try:
            cid=command(['docker','run','-d','--init','--name','rgpu-'+case+'-'+rid[:8],'--network','none','--user','0:0','--cap-drop','ALL','--cap-add','NET_ADMIN','--cap-add','SETUID','--cap-add','SETGID','--device','/dev/net/tun','-v',str(run)+':/run/vm','-v',str(run)+':/run/rgpu-libvirt','-v',str(ROOT)+':/candidate:ro','-v',str(ROOT/'tools')+':/run/rgpu-tools:ro','-e','HOME=/home/arch','-e','RGPU_LIBVIRT_RUN_ID='+rid,'-e','RGPU_LIBVIRT_ADMISSION_SHA256='+digest,'--entrypoint','python3',IMAGE,'-B','/run/vm/bootstrap.py']).stdout.strip()
            initial=json.loads(command(['docker','inspect',cid]).stdout)[0]
            assert initial['Image']==IMAGE and initial['HostConfig']['NetworkMode']=='none' and not initial['HostConfig']['Privileged']
            assert [d['PathOnHost'] for d in initial['HostConfig']['Devices']]==['/dev/net/tun']
            paused=wait_file(directory/'paused.json');state=dict(cid=cid,started_at=initial['State']['StartedAt'],deadline_epoch=time.time()+125)
            observed=json.loads(command(['docker','exec','--user','1000:1000',cid,'python3','-B','/candidate/findings/research/libvirt-entry-handoff-smoke-20261009.py','inspect-paused']).stdout)
            admission=json.loads((directory/'admission.json').read_text())
            console=socket.socket(socket.AF_UNIX);console.settimeout(20);console.connect(str(run/'guest.sock'))
            permit=handoff.permit(admission,digest,paused,observed,state);handoff.write_once(directory/'resume.json',permit)
            wait_file(directory/'running.json');assert console.recv(1)==b'R'
            # Reuse the already-connected socket in the real collector; only its
            # connect call is adapted. recv/fsync/EOF publication are production.
            adapter=run/'collector.py'
            adapter.write_text("import os,runpy,socket\noriginal=socket.socket\ns=original(fileno=int(os.environ['FIXTURE_FD']))\nclass Connected:\n def connect(self,path):pass\n def __getattr__(self,name):return getattr(s,name)\nsocket.socket=lambda *a,**k:Connected()\nrunpy.run_path(os.environ['FIXTURE_SERCAT'],run_name='__main__')\n")
            eof_path=run/f'capture-eof-{cid}-console.json'
            reset_path=run/f'capture-reset-{cid}-console.json'
            collector_socket=console
            if case=='live-qemu-reset':
                reset_client,reset_peer=socket.socketpair()
                reset_client.sendall(b'RGPUQ2\n')
                collector_socket=reset_client
            ready=run/'collector.ready'
            environment=dict(os.environ,FIXTURE_FD=str(collector_socket.fileno()),FIXTURE_SERCAT=str(ROOT/'tools/sercat.py'),
                VM_SERIAL_SOCKET=str(run/'guest.sock'),VM_SERIAL_OUTPUT=str(run/'serial.log'),
                VM_SERIAL_READY=str(ready),VM_SERIAL_CID=cid,VM_SERIAL_CHANNEL='console',
                VM_SERIAL_EOF=str(eof_path),VM_SERIAL_RESET=str(reset_path),VM_SERIAL_STARTED_AT=state['started_at'],
                VM_SERIAL_RUN_ID=rid,VM_SERIAL_ADMISSION_SHA256=digest)
            collector=subprocess.Popen(['python3','-B',str(adapter)],env=environment,pass_fds=(collector_socket.fileno(),),
                stdout=(run/'collector.stdout').open('w'),stderr=(run/'collector.stderr').open('w'))
            ready_until=time.monotonic()+3
            while not ready.exists():
                if time.monotonic()>ready_until:raise RuntimeError('collector not ready')
                time.sleep(.005)
            if case=='guest-s5-reset':console.sendall(b'x'+b'RGPUQ2\n'*32)
            else:reset_peer.close() # Deliberately lose capture with guest still alive.
            assert collector.wait(timeout=12)==1
            assert not eof_path.exists()
            reset_record=json.loads(reset_path.read_text())
            assert reset_record['kind']=='recv-reset' and reset_record['errno']==104
            transport_end_monotonic=reset_record['reset_monotonic']
            observed_events=[json.loads(line) for line in (directory/'events.jsonl').read_text().splitlines()]
            guest_before_end=any(e.get('phase')=='libvirt-lifecycle-observed' and e.get('guest_shutdown') is True and e['observed_monotonic']<=transport_end_monotonic for e in observed_events)
            # Fixture alone bootstraps TAP as root, then drops controller uid.
            # Match the production image's arch user for this read-only exec.
            real_run=supervisor.run
            def fixture_run(argv,**kwargs):
                if len(argv)>1 and argv[1]=='exec':argv=argv[:2]+['--user','1000:1000']+argv[2:]
                return real_run(argv,**kwargs)
            supervisor.run=fixture_run
            try:result=supervisor.capture_exit(vm,cid,state['started_at'],int(state['deadline_epoch']),rid,digest,'console')
            finally:supervisor.run=real_run
            code=int(command(['docker','wait',cid],timeout=10).stdout.strip())
            terminal=json.loads((directory/'terminal.json').read_text()) if (directory/'terminal.json').exists() else None
            if case=='guest-s5-reset':
                assert result['outcome'] in ('natural-container-exit','already-stopped','container-stopped-during-shutdown-wait'),result
                assert code==0 and terminal and terminal['reason']=='guest-shutdown' and terminal['process_exited'] is True,(code,terminal)
            else:
                assert result['outcome']=='immediate-stop' and not result['deferred'],result
            final=json.loads(command(['docker','inspect',cid]).stdout)[0];assert not final['State']['Running']
            records.append(dict(case=case,cid=cid,image=IMAGE,started_at=initial['State']['StartedAt'],finished_at=final['State']['FinishedAt'],exit_code=code,gate=result,terminal=terminal,transport_end_monotonic=transport_end_monotonic,guest_shutdown_observed_before_transport_end=guest_before_end))
        finally:
            if collector and collector.poll() is None:
                collector.terminate();collector.wait(timeout=3)
            if reset_client:reset_client.close()
            if reset_peer:reset_peer.close()
            if console:console.close()
            if cid:
                command(['docker','stop','--time','5',cid],timeout=15,check=False)
                stopped=json.loads(command(['docker','inspect',cid]).stdout)[0]
                (run/'container-cleanup.json').write_text(json.dumps(dict(cid=cid,image=stopped['Image'],state=stopped['State']),indent=2)+'\n')
                assert not stopped['State']['Running']
                logs=command(['docker','logs',cid],check=False);(run/'container.stdout').write_text(logs.stdout);(run/'container.stderr').write_text(logs.stderr)
    summary=dict(passed=True,cases=records,scope='Real TCG S5 closes QEMU serial with unread reverse bytes and production collector records recv-reset104/exit1, never clean EOF. Live TCG negative uses a separate socketpair peer close with unread reverse data to produce actual RST while QEMU remains running. No KVM/GPU/host network; isolated TAP only. Connect-only collector adapter; systemd wiring remains separately tested.')
    (base/'result.json').write_text(json.dumps(summary,indent=2)+'\n');print(base)
if __name__=='__main__':main()
