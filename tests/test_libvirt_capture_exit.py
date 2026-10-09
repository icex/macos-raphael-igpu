import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
def load(name,file):
    spec=importlib.util.spec_from_file_location(name,ROOT/'tools'/file)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result
sup=load('capture_supervision','vm-supervision.py');entry=load('capture_entry','libvirt-console-entry.py')
CID='a'*64;RUN='b'*32;ADMIT='c'*64;START='2026-10-09T01:00:00Z'

class CaptureExitTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.vm=Path(self.tmp.name);(self.vm/'run').mkdir();self.clock=0;self.live=[True,False]
        self.proof=dict(exited=True,cid=CID,started_at=START,run_id=RUN,admission_sha256=ADMIT,deadline_epoch=110)
        self.calls=[]
    def command(self,args,**kwargs):
        self.calls.append(args)
        if args[1]=='inspect':
            value=self.live.pop(0) if len(self.live)>1 else self.live[0]
            return json.dumps(dict(Id=CID,StartedAt=START,Running=value))
        if args[1]=='exec':return json.dumps(self.proof)
        raise AssertionError(args)
    def invoke(self):
        def sleep(seconds):self.clock+=seconds
        with patch.object(sup,'run',side_effect=self.command),patch.object(sup,'binary',side_effect=lambda x:x),\
             patch.object(sup,'stop_exact') as stop,patch.object(sup.time,'monotonic',side_effect=lambda:self.clock),\
             patch.object(sup.time,'time',side_effect=lambda:100+self.clock),patch.object(sup.time,'sleep',side_effect=sleep):
            result=sup.capture_exit(self.vm,CID,START,110,RUN,ADMIT)
        return result,stop
    def test_bound_exited_qemu_allows_natural_exit_without_signal(self):
        result,stop=self.invoke();self.assertEqual(result['outcome'],'natural-container-exit');stop.assert_not_called()
    def test_alive_or_error_proof_stops_immediately(self):
        self.proof['exited']=False
        result,stop=self.invoke();self.assertFalse(result['deferred']);stop.assert_called_once_with(CID);self.assertEqual(self.clock,0)
    def test_foreign_run_cid_or_admission_is_never_deferred(self):
        for field in ('cid','run_id','admission_sha256','started_at'):
            old=self.proof[field];self.proof[field]='wrong';self.live=[True]
            result,stop=self.invoke();self.assertFalse(result['deferred']);stop.assert_called_once_with(CID)
            self.proof[field]=old
    def test_controller_hang_gets_only_two_seconds(self):
        self.live=[True];result,stop=self.invoke();self.assertTrue(result['deferred']);self.assertLessEqual(self.clock,2.001);stop.assert_called_once_with(CID)
    def test_original_deadline_shortens_grace(self):
        self.proof['deadline_epoch']=101;self.live=[True]
        result,stop=self.invoke();self.assertTrue(result['deferred']);self.assertLessEqual(self.clock,1.001);stop.assert_called_once_with(CID)
    def test_evidence_persistence_happens_only_after_immediate_stop(self):
        self.proof['exited']=False;order=[]
        with patch.object(sup,'run',side_effect=self.command),patch.object(sup,'binary',side_effect=lambda x:x),\
             patch.object(sup,'stop_exact',side_effect=lambda cid:order.append('stop')),\
             patch.object(sup,'_durable_json',side_effect=lambda *a:order.append('receipt')),\
             patch.object(sup.time,'monotonic',return_value=0),patch.object(sup.time,'time',return_value=100):
            sup.capture_exit(self.vm,CID,START,110,RUN,ADMIT)
        self.assertEqual(order,['stop','receipt'])

    def test_probe_failure_stops_without_grace(self):
        original=self.command
        def command(args,**kw):
            if args[1]=='exec':raise RuntimeError('probe timed out')
            return original(args,**kw)
        self.command=command;result,stop=self.invoke();self.assertFalse(result['deferred']);stop.assert_called_once_with(CID)

class ExitedIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.path=Path(self.tmp.name)
        self.scope=dict(kind='pid-namespace',device=1,inode=2,init_start_ticks=3)
        self.identity=dict(name='rgpu-'+RUN,uuid='zero',run_id=RUN,pid=42,start_ticks=43)
        self.plan=dict(domain_name=self.identity['name'],uuid='zero',run_id=RUN,
                       native_argv=['-spice',entry.native.configuration.planner.SPICE])
        self.admission=dict(schema=1,run_id=RUN,manifest_sha256='d'*64,deadline_epoch=200)
        digest=entry.runtime.digest(self.plan)
        self.paused=dict(paused=True,run_id=RUN,identity=self.identity,scope=self.scope,plan_sha256=digest)
        self.permit=dict(schema=1,run_id=RUN,manifest_sha256='d'*64,admission_sha256=ADMIT,paused=self.paused,cid=CID,started_at=START,deadline_epoch=200)
        self.running=dict(run_id=RUN,identity=self.identity,scope=self.scope,plan_sha256=digest,cid=CID,started_at=START)
        self.save()
    def save(self):
        for name,value in [('plan',self.plan),('paused',self.paused),('resume',self.permit),('running',self.running)]:
            (self.path/(name+'.json')).write_text(json.dumps(value))
    def inspect(self,current=None,scope=None):
        with patch.object(entry,'context',return_value=(self.path,self.admission,ADMIT)),\
             patch.object(entry.native.local,'namespace_identity',return_value=scope or self.scope),\
             patch.object(entry.native.local,'process',return_value=current),patch.object(entry.Path,'iterdir',return_value=[]),\
             patch.object(entry.handoff.time,'time',return_value=100):return entry.inspect_exited()
    def test_absent_exact_process_and_bound_receipts_pass(self):self.assertTrue(self.inspect()['exited'])
    def test_live_pinned_process_refuses(self):
        with self.assertRaisesRegex(ValueError,'original-pid-present'):self.inspect(dict(start_ticks=43))
    def test_forged_pid_only_in_running_refuses(self):
        self.running['identity']=dict(self.identity,pid=999);self.save()
        with self.assertRaisesRegex(ValueError,'binding'):self.inspect()
    def test_forged_pid_in_paused_and_running_but_not_permit_refuses(self):
        self.paused['identity']=dict(self.identity,pid=999);self.running['identity']=self.paused['identity']
        # Permit is already persisted with original PID.
        for name,value in [('paused',self.paused),('running',self.running)]:
            (self.path/(name+'.json')).write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError,'permit'):self.inspect()
    def test_reused_namespace_refuses(self):
        with self.assertRaisesRegex(ValueError,'namespace'):self.inspect(scope=dict(self.scope,init_start_ticks=99))
    def test_other_qemu_executable_refuses(self):
        path=self.path/'99';path.mkdir();(path/'comm').write_text('renamed');(path/'exe').symlink_to('/usr/bin/qemu-system-x86_64')
        with patch.object(entry,'context',return_value=(self.path,self.admission,ADMIT)),\
             patch.object(entry.native.local,'namespace_identity',return_value=self.scope),\
             patch.object(entry.native.local,'process',return_value=None),patch.object(entry.Path,'iterdir',return_value=[path]),\
             patch.object(entry.handoff.time,'time',return_value=100):
            with self.assertRaisesRegex(ValueError,'other-qemu'):entry.inspect_exited()

class CaptureWiringTests(unittest.TestCase):
    def test_only_libvirt_collectors_use_guard_deadline_stays_immediate(self):
        import os
        with tempfile.TemporaryDirectory() as tmp:
            vm=Path(tmp);(vm/'run').mkdir();(vm/'sercat.py').write_text('')
            for manager in ('direct','libvirt'):
                calls=[]
                def command(argv,**kw):
                    calls.append(argv)
                    for arg in argv:
                        if arg.startswith('--setenv=VM_SERIAL_READY='):
                            Path(arg.split('=',2)[2]).write_text('ready')
                    return ''
                with patch.dict(os.environ,dict(VM_MANAGER=manager,GENERIC_GRAPHICS='on',RGPU_LIBVIRT_RUN_ID=RUN,RGPU_LIBVIRT_ADMISSION_SHA256=ADMIT)),\
                     patch.object(sup,'inspect',return_value=(START,100)),patch.object(sup,'binary',side_effect=lambda x:x),\
                     patch.object(sup,'verify'),patch.object(sup,'run',side_effect=command),\
                     patch.object(sup.time,'time',return_value=101):
                    sup.arm(vm,CID,100,critical_enabled=True)
                self.assertEqual(calls[0][-5:],['docker','stop','--time','0',CID])
                stops=[arg for call in calls[1:] for arg in call if arg.startswith('--property=ExecStopPost=')]
                self.assertEqual(len(stops),2)
                for stop in stops:
                    self.assertIn(CID,stop)
                    if manager=='libvirt':self.assertIn('capture-exit',stop);self.assertIn(ADMIT,stop)
                    else:self.assertEqual(stop,'--property=ExecStopPost=docker stop --time 0 '+CID)

class RefusalDiagnosticsTests(unittest.TestCase):
    setUp=CaptureExitTests.setUp
    command=CaptureExitTests.command
    invoke=CaptureExitTests.invoke
    def test_structured_permission_refusal_is_retained_without_text_or_argv(self):
        self.proof=dict(exited=False,refusal=dict(stage='proc-scan',code='permission-denied',pid=77,process_uid=0,errno=13,operation='exe',argv='secret',message='secret'))
        result,stop=self.invoke();stop.assert_called_once_with(CID)
        self.assertEqual(result['refusal_stage'],'exit-proof')
        self.assertEqual(result['proof_refusal'],dict(stage='proc-scan',code='permission-denied',pid=77,process_uid=0,errno=13,operation='exe'))
        self.assertNotIn('secret',json.dumps(result))
    def test_docker_exec_timeout_has_distinct_stage_and_code(self):
        original=self.command
        def command(argv,**kw):
            if argv[1]=='exec':raise sup.CommandTimeout('secret args never retained')
            return original(argv,**kw)
        self.command=command;result,stop=self.invoke();stop.assert_called_once_with(CID)
        self.assertEqual((result['refusal_stage'],result['refusal_code']),('docker-exec','command-timeout'))
        self.assertNotIn('secret',json.dumps(result))
    def test_inspect_failure_has_distinct_stage_and_exit_code(self):
        self.command=lambda *a,**kw:(_ for _ in ()).throw(sup.CommandFailure('secret',7))
        result,stop=self.invoke();stop.assert_called_once_with(CID)
        self.assertEqual((result['refusal_stage'],result['refusal_code'],result['command_exit_code']),('container-inspect','command-failed',7))

class EntryRefusalDiagnosticsTests(unittest.TestCase):
    setUp=ExitedIdentityTests.setUp
    save=ExitedIdentityTests.save
    inspect=ExitedIdentityTests.inspect
    def test_live_zombie_is_still_refused_with_state(self):
        original=entry.Path.read_text
        def read(path,*a,**kw):
            if str(path)=='/proc/42/stat':return '42 (qemu-system-x86) Z 1'
            return original(path,*a,**kw)
        with patch.object(entry.Path,'read_text',new=read):
            with self.assertRaises(entry.ExitProofRefusal) as caught:self.inspect(dict(start_ticks=43))
        self.assertEqual(caught.exception.report,dict(stage='original-process',code='original-pid-present',pid=42,state='Z'))
    def test_permission_exception_text_is_never_returned(self):
        with patch.object(entry,'context',side_effect=PermissionError(13,'secret path')):
            result=entry.inspect_exited_report()
        self.assertEqual(result,dict(exited=False,refusal=dict(stage='admission',code='permission-denied',errno=13)))
        self.assertNotIn('secret',json.dumps(result))
    def test_process_permission_reports_pid_and_operation(self):
        path=self.path/'99';path.mkdir();(path/'comm').write_text('sshd')
        with patch.object(entry,'context',return_value=(self.path,self.admission,ADMIT)),\
             patch.object(entry.native.local,'namespace_identity',return_value=self.scope),\
             patch.object(entry.native.local,'process',return_value=None),patch.object(entry.Path,'iterdir',return_value=[path]),\
             patch.object(entry.os,'readlink',side_effect=PermissionError(13,'secret')),\
             patch.object(entry.handoff.time,'time',return_value=100):
            result=entry.inspect_exited_report()
        self.assertEqual(result['refusal']['stage'],'proc-scan');self.assertEqual(result['refusal']['operation'],'exe')
        self.assertEqual(result['refusal']['pid'],99);self.assertEqual(result['refusal']['code'],'permission-denied')
        self.assertNotIn('secret',json.dumps(result))
