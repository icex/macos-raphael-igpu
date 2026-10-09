import json
import math
import os
from pathlib import Path
import runpy
import socket
import tempfile
import time
import unittest
from unittest.mock import patch
import test_libvirt_capture_exit as fixture
from test_libvirt_capture_exit import sup, entry, CID, RUN, ADMIT, START
from test_sercat import FakeSocket, TOOL


class CleanEofCollectorTests(unittest.TestCase):
    def test_clean_eof_is_published_only_after_log_fsync(self):
        self.run_case(False)
    def test_failed_log_sync_never_publishes_clean_eof(self):
        self.run_case(True)
    def test_interrupted_capture_never_publishes_eof(self):
        with tempfile.TemporaryDirectory() as td:
            marker=Path(td)/'eof.json'
            env=dict(VM_SERIAL_SOCKET=td+'/sock',VM_SERIAL_OUTPUT=td+'/out',VM_SERIAL_CID=CID,
                VM_SERIAL_CHANNEL='console',VM_SERIAL_EOF=str(marker),VM_SERIAL_STARTED_AT=START,
                VM_SERIAL_RUN_ID=RUN,VM_SERIAL_ADMISSION_SHA256=ADMIT)
            fake=FakeSocket([])
            with patch.dict(os.environ,env,clear=True),patch.object(socket,'socket',return_value=fake),patch.object(fake,'recv',side_effect=KeyboardInterrupt),self.assertRaises(KeyboardInterrupt):
                runpy.run_path(str(TOOL),run_name='__main__')
            self.assertFalse(marker.exists())
    def run_case(self, fail):
        with tempfile.TemporaryDirectory() as td:
            base=Path(td);marker=base/'eof.json';order=[]
            env=dict(VM_SERIAL_SOCKET=str(base/'sock'),VM_SERIAL_OUTPUT=str(base/'out'),
                VM_SERIAL_CID=CID,VM_SERIAL_CHANNEL='console',VM_SERIAL_EOF=str(marker),
                VM_SERIAL_STARTED_AT=START,VM_SERIAL_RUN_ID=RUN,VM_SERIAL_ADMISSION_SHA256=ADMIT)
            def synced(fd):
                order.append('sync')
                if len(order)<=2:self.assertFalse(marker.exists())
                if fail:raise OSError('failed')
            with patch.dict(os.environ,env,clear=True),patch.object(socket,'socket',return_value=FakeSocket([b'bytes',b''])),patch('os.fsync',side_effect=synced):
                if fail:
                    with self.assertRaises(SystemExit):runpy.run_path(str(TOOL),run_name='__main__')
                else:runpy.run_path(str(TOOL),run_name='__main__')
            self.assertEqual(marker.exists(),not fail)
            if not fail:
                value=json.loads(marker.read_text());self.assertEqual(value['cid'],CID)
                self.assertLessEqual(value['eof_monotonic'],value['published_monotonic'])
                self.assertGreaterEqual(len(order),2)


class ShutdownWaitHostTests(unittest.TestCase):
    command=fixture.CaptureExitTests.command
    def setUp(self):
        fixture.CaptureExitTests.setUp(self);self.clock=10
        self.eof=dict(schema=1,cid=CID,started_at=START,run_id=RUN,admission_sha256=ADMIT,
                      channel='console',eof_monotonic=9.7,published_monotonic=9.9,eof_epoch=109.7)
        self.proof['deadline_epoch']=120
        self.waiting=dict(self.proof,exited=False,shutdown_wait=True,transport_end_monotonic=9.7,shutdown_observed_monotonic=9.6)
    def invoke_channel(self, write=True):
        if write:(self.vm/'run'/f'capture-eof-{CID}-console.json').write_text(json.dumps(self.eof))
        def sleep(seconds):self.clock+=seconds
        with patch.object(sup,'run',side_effect=self.command),patch.object(sup,'binary',side_effect=lambda x:x),patch.object(sup,'stop_exact') as stop,patch.object(sup.time,'monotonic',side_effect=lambda:self.clock),patch.object(sup.time,'time',side_effect=lambda:100+self.clock),patch.object(sup.time,'sleep',side_effect=sleep):
            result=sup.capture_exit(self.vm,CID,START,120,RUN,ADMIT,'console')
        return result,stop
    def test_missing_marker_preserves_independent_completed_process(self):
        result,stop=self.invoke_channel(False);stop.assert_not_called()
        self.assertEqual(result['outcome'],'natural-container-exit')
        self.assertEqual(result['budget_origin'],'legacy-hook-completion-only')
    def test_malformed_marker_preserves_independent_completed_process(self):
        (self.vm/'run'/f'capture-eof-{CID}-console.json').write_text('{')
        result,stop=self.invoke_channel(False);stop.assert_not_called()
        self.assertEqual(result['budget_origin'],'legacy-hook-completion-only')
    def test_wait_then_completion_retains_original_eof_budget(self):
        complete=self.proof;self.proof=self.waiting
        original=self.command
        def command(args,**kwargs):
            if args[1]=='exec' and self.clock>10:self.proof=complete
            return original(args,**kwargs)
        self.command=command
        result,stop=self.invoke_channel();stop.assert_not_called()
        self.assertTrue(result['shutdown_event_wait']);self.assertEqual(result['outcome'],'natural-container-exit')
    def test_worker_never_completes_hits_eof_not_hook_plus_two(self):
        self.proof=self.waiting;self.live=[True]
        result,stop=self.invoke_channel();stop.assert_called_once_with(CID)
        self.assertEqual(result['outcome'],'shutdown-wait-expired');self.assertLessEqual(self.clock,11.70001)
    def test_missing_eof_is_immediate(self):
        self.proof={'exited':False}
        result,stop=self.invoke_channel(False);stop.assert_called_once_with(CID)
        self.assertFalse(result['deferred']);self.assertEqual(len(self.calls),2)
    def test_malformed_oversized_and_symlink_eof_refuse(self):
        self.proof={'exited':False};self.live=[True]
        marker=self.vm/'run'/f'capture-eof-{CID}-console.json'
        for data in ('{','x'*4097,'[]'):
            marker.write_text(data);self.calls=[]
            result,stop=self.invoke_channel(False);stop.assert_called_once_with(CID);self.assertFalse(result['deferred'])
        marker.unlink();target=self.vm/'valid.json';target.write_text(json.dumps(self.eof));marker.symlink_to(target)
        result,stop=self.invoke_channel(False);stop.assert_called_once_with(CID);self.assertFalse(result['deferred'])
    def test_invalid_eof_cannot_authorize_worker_wait(self):
        self.proof={'exited':False};self.live=[True]
        for field,bad in [('cid','x'),('channel','critical'),('run_id','x'),('started_at','x'),
                          ('admission_sha256','x'),('eof_monotonic',float('nan')),
                          ('published_monotonic',float('inf')),('eof_monotonic',7),
                          ('eof_monotonic',11),('eof_epoch',float('-inf'))]:
            with self.subTest(field=field,bad=bad):
                old=self.eof[field];self.eof[field]=bad;self.calls=[]
                result,stop=self.invoke_channel();stop.assert_called_once_with(CID)
                self.assertEqual(len(self.calls),2);self.eof[field]=old
    def test_event_after_eof_cannot_authorize_wait(self):
        self.proof=dict(self.waiting,shutdown_observed_monotonic=9.8)
        result,stop=self.invoke_channel();stop.assert_called_once_with(CID);self.assertFalse(result['deferred'])
    def test_container_stops_between_probes_is_not_forged_completion(self):
        self.proof=self.waiting;original=self.command
        def command(args,**kwargs):
            if args[1]=='exec' and self.clock>10:raise sup.CommandFailure('gone',1)
            return original(args,**kwargs)
        self.command=command
        result,stop=self.invoke_channel();stop.assert_not_called()
        self.assertEqual(result['outcome'],'container-stopped-during-shutdown-wait')
        self.assertNotIn('process_exited',result)
    def killed_witness(self, code=137, inspect_after=None):
        self.proof=self.waiting;original=self.command
        def command(args,**kwargs):
            if args[1]=='exec' and self.clock>10:raise sup.CommandFailure('private witness command',code)
            if args[1]=='inspect' and self.clock>10 and inspect_after is not None:
                return inspect_after(args,**kwargs)
            return original(args,**kwargs)
        self.command=command
    def test_killed_witness_waits_for_delayed_container_exit_without_completion_claim(self):
        self.live=[True,True,True,False];self.killed_witness()
        result,stop=self.invoke_channel();stop.assert_not_called()
        self.assertEqual(result['outcome'],'container-stopped-during-shutdown-wait')
        self.assertEqual(result['witness_exit_code'],137)
        self.assertTrue(result['shutdown_event_wait']);self.assertFalse(result['completed_original_zombie'])
        self.assertNotIn('process_exited',result);self.assertLess(self.clock,11.7)
        self.assertNotIn('private',json.dumps(result))
        self.assertEqual(len([a for a in self.calls if a[1]=='exec']),1)
    def test_killed_witness_never_extends_original_transport_budget(self):
        self.live=[True];self.killed_witness()
        result,stop=self.invoke_channel();stop.assert_called_once_with(CID)
        self.assertEqual(result['outcome'],'immediate-stop')
        self.assertEqual(result['command_exit_code'],137)
        self.assertAlmostEqual(self.clock,11.7)
    def test_killed_witness_respects_earlier_admitted_deadline(self):
        self.waiting['deadline_epoch']=111;self.live=[True];self.killed_witness()
        result,stop=self.invoke_channel();stop.assert_called_once_with(CID)
        self.assertAlmostEqual(self.clock,11)
    def test_killed_witness_container_identity_change_or_inspection_error_refuses(self):
        for outcome in ('replacement','malformed','unreachable'):
            with self.subTest(outcome=outcome):
                self.setUp();self.live=[True]
                def inspect_after(*a,**kw):
                    if outcome=='unreachable':raise sup.CommandFailure('private',1)
                    if outcome=='malformed':return '{'
                    return json.dumps(dict(Id=CID,StartedAt='replacement',Running=False))
                self.killed_witness(inspect_after=inspect_after)
                result,stop=self.invoke_channel();stop.assert_called_once_with(CID)
                self.assertEqual(result['outcome'],'immediate-stop');self.assertLess(self.clock,10.1)
    def test_other_failed_witness_gets_no_container_grace(self):
        self.live=[True];self.killed_witness(1)
        result,stop=self.invoke_channel();stop.assert_called_once_with(CID)
        self.assertEqual(result['command_exit_code'],1);self.assertLess(self.clock,10.1)
    def test_initial_killed_witness_has_no_shutdown_wait_authority(self):
        original=self.command
        def command(args,**kwargs):
            if args[1]=='exec':raise sup.CommandFailure('private',137)
            return original(args,**kwargs)
        self.command=command
        result,stop=self.invoke_channel();stop.assert_called_once_with(CID)
        self.assertFalse(result['deferred']);self.assertEqual(self.clock,10)
        self.assertNotIn('witness_exit_code',result)

    def test_changed_identity_during_wait_refuses(self):
        self.proof=self.waiting;original=self.command
        def command(args,**kwargs):
            if args[1]=='exec' and self.clock>10:self.proof=dict(self.waiting,cid='f'*64)
            return original(args,**kwargs)
        self.command=command
        result,stop=self.invoke_channel();stop.assert_called_once_with(CID)
        self.assertEqual(result['outcome'],'immediate-stop')


class ShutdownEventTests(unittest.TestCase):
    save=fixture.ExitedIdentityTests.save
    def setUp(self):
        fixture.ExitedIdentityTests.setUp(self);self.event=dict(phase='libvirt-lifecycle-observed',identity_bound=True,
            guest_shutdown=True,event=6,detail=1,identity=self.identity,scope=self.scope,
            name=self.identity['name'],uuid=self.identity['uuid'],observed_monotonic=9.5)
    def check_event(self):
        (self.path/'events.jsonl').write_text(json.dumps(self.event)+'\n')
        with patch.object(entry.time,'monotonic',return_value=10.1):
            return entry.guest_shutdown_before_eof(self.path,self.identity,self.scope,10)
    def test_bound_guest_event_before_eof_passes(self):self.assertEqual(self.check_event(),9.5)
    def test_wrong_stale_host_and_nonfinite_events_refuse(self):
        for key,bad in [('event',5),('detail',2),('identity_bound',False),('guest_shutdown',False),
            ('identity',dict(self.identity,start_ticks=44)),('scope',dict(self.scope,inode=5)),
            ('name','foreign'),('observed_monotonic',10.01),('observed_monotonic',7.9),
            ('observed_monotonic',float('nan')),('observed_monotonic',float('inf'))]:
            with self.subTest(key=key,bad=bad):
                old=self.event[key];self.event[key]=bad
                with self.assertRaises(ValueError):self.check_event()
                self.event[key]=old
    def test_partial_oversized_missing_and_malformed_event_file_refuse(self):
        for data in [b'',b'{',b'[]\n',b'x'*1048577]:
            (self.path/'events.jsonl').write_bytes(data)
            with patch.object(entry.time,'monotonic',return_value=10.1),self.assertRaises(ValueError):
                entry.guest_shutdown_before_eof(self.path,self.identity,self.scope,10)
        (self.path/'events.jsonl').unlink()
        with patch.object(entry.time,'monotonic',return_value=10.1),self.assertRaises(FileNotFoundError):
            entry.guest_shutdown_before_eof(self.path,self.identity,self.scope,10)

class ShutdownWaitFullScanTests(unittest.TestCase):
    save=fixture.ExitedIdentityTests.save
    def setUp(self):
        fixture.ExitedIdentityTests.setUp(self)
        self.event=dict(phase='libvirt-lifecycle-observed',identity_bound=True,guest_shutdown=True,
            event=6,detail=1,identity=self.identity,scope=self.scope,name=self.identity['name'],
            uuid=self.identity['uuid'],observed_monotonic=9.5)
        (self.path/'events.jsonl').write_text(json.dumps(self.event)+'\n')
    def inspect_wait(self,other=None):
        original=Path.read_text
        def read(path,*a,**kw):
            if str(path)=='/proc/42/stat':return '42 (qemu-system-x86) Z 1'
            if str(path)=='/proc/99/comm':
                if isinstance(other,Exception):raise other
                return other
            return original(path,*a,**kw)
        def complete(identity,details):
            details.update(completion_reason='not-sole-task',completion_task_count=2);return False
        with patch.object(entry,'context',return_value=(self.path,self.admission,ADMIT)),patch.object(entry.native.local,'namespace_identity',return_value=self.scope),patch.object(entry.native.local,'process',return_value=dict(start_ticks=43)),patch.object(entry.Path,'iterdir',return_value=[Path('/proc/42')]+([Path('/proc/99')] if other else [])),patch.object(entry.Path,'read_text',new=read),patch.object(entry,'completed_original_zombie',side_effect=complete),patch.object(entry.time,'time',return_value=100),patch.object(entry.time,'monotonic',return_value=10.1):
            return entry.inspect_exited(10)
    def test_eligible_wait_is_not_completed_process(self):
        value=self.inspect_wait();self.assertFalse(value['exited']);self.assertTrue(value['shutdown_wait'])
        self.assertEqual(value['identity'],self.identity)
    def test_other_qemu_still_refuses(self):
        with self.assertRaisesRegex(ValueError,'other-qemu'):self.inspect_wait('qemu-system-x86')
    def test_unknown_proc_visibility_still_refuses(self):
        with self.assertRaisesRegex(ValueError,'permission-denied'):self.inspect_wait(PermissionError(13,'private'))
