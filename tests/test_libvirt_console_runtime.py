import importlib.util
import os
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('libvirt_runtime', ROOT/'tools/libvirt-console-runtime.py')
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
PLAN = {'run_id':'a'*32, 'domain_name':'rgpu-'+'a'*32, 'uuid':'0'*32,
        'xml':'fixture', 'required_launch':'transient-paused', 'resume_allowed':False, 'lan_hub':0}
CONTAINER = {'cid':'b'*64,'started_at':'2026-10-09T00:00:00Z'}


class Backend:
    def __init__(self):
        self.live=False;self.process=False;self.calls=[];self.fail=None;self.attached=False
        self.state=dict(name=PLAN['domain_name'],uuid=PLAN['uuid'],run_id=PLAN['run_id'],
                        pid=123,start_ticks=456,persistent=False,running=False,status='prelaunch')
    def container_identity(self):return CONTAINER.copy()
    def domains(self):return [PLAN['domain_name']] if self.live else []
    def create_paused(self, xml):
        self.calls.append('create');self.live=True;self.process=True
        if self.fail=='create-reply':raise TimeoutError('lost create reply')
    def reconcile_creation(self,plan):
        return {'outcome':'created','identity':{k:self.state[k] for k in ('name','uuid','run_id','pid','start_ticks')}}
    def session_processes_gone(self):return not self.process
    def process_gone(self,identity):return not self.process
    def snapshot(self,name):return self.state.copy()
    def qmp(self,name,cmd,args,fd=None):
        self.calls.append(cmd)
        if self.fail==cmd:raise RuntimeError('injected '+cmd+' failure')
        if cmd=='netdev_add' and args['type']=='hubport':self.attached=True
        if cmd=='cont':self.state.update(running=True,status='running')
    def network_attached(self,name,hub):return self.attached
    def destroy_owned(self,identity):self.calls.append('destroy');self.live=False;self.process=False
    def record(self,event):pass


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.fd=os.open('/dev/null',os.O_RDONLY);self.backend=Backend()
    def tearDown(self):
        if self.fd is not None:os.close(self.fd)
    def owner(self,verify=lambda p,s:True):
        return mod.PausedDomain(self.backend,PLAN,mod.digest(PLAN),CONTAINER,verify)
    def test_resume_only_after_observed_attachment_and_cleanup_is_idempotent(self):
        owner=self.owner();owner.prepare(self.fd)
        self.assertNotIn('cont',self.backend.calls)
        owner.resume();self.assertTrue(owner.resumed)
        owner.cleanup('manager-force-off');owner.cleanup('duplicate-stop')
        self.assertEqual(self.backend.calls.count('destroy'),1)
        self.assertFalse(self.backend.live)
    def test_invalid_fd_never_creates_domain(self):
        os.close(self.fd);self.fd=None
        with self.assertRaises(OSError):self.owner().prepare(-1)
        self.assertFalse(self.backend.calls)
    def test_injection_failures_never_resume_and_destroy_owned_domain(self):
        for cmd in ['getfd','netdev_add']:
            with self.subTest(cmd=cmd):
                self.backend=Backend();self.backend.fail=cmd;owner=self.owner()
                with self.assertRaises(RuntimeError):owner.prepare(self.fd)
                self.assertNotIn('cont',self.backend.calls)
                self.assertFalse(self.backend.live)
                self.assertEqual(self.backend.calls[-1],'destroy')
    def test_configuration_failure_still_cleans_proven_owner(self):
        owner=self.owner(lambda p,s:False)
        with self.assertRaisesRegex(mod.Refused,'configuration'):owner.prepare(self.fd)
        self.assertFalse(self.backend.live)
        self.assertNotIn('getfd',self.backend.calls)
    def test_replaced_process_is_not_destroyed(self):
        owner=self.owner();owner.prepare(self.fd);self.backend.state['start_ticks']+=1
        with self.assertRaisesRegex(mod.Refused,'ownership'):owner.cleanup('stop')
        self.assertNotIn('destroy',self.backend.calls)
    def test_existing_domain_is_not_adopted(self):
        self.backend.live=True
        with self.assertRaisesRegex(mod.Refused,'already contains'):self.owner().prepare(self.fd)
        self.assertFalse(self.backend.calls)
    def test_lost_attachment_prevents_resume(self):
        owner=self.owner();owner.prepare(self.fd);self.backend.attached=False
        with self.assertRaisesRegex(mod.Refused,'attachment lost'):owner.resume()
        self.assertNotIn('cont',self.backend.calls);self.assertFalse(self.backend.live)
    def test_changed_plan_rejected_before_backend_action(self):
        with self.assertRaisesRegex(mod.Refused,'digest'):
            mod.PausedDomain(self.backend,PLAN,'0'*64,CONTAINER,lambda p,s:True)
        self.assertFalse(self.backend.calls)
    def test_create_reply_timeout_reconciles_and_destroys_created_process(self):
        self.backend.fail='create-reply';owner=self.owner()
        with self.assertRaises(TimeoutError):owner.prepare(self.fd)
        self.assertFalse(self.backend.process);self.assertTrue(owner.finished)
        self.assertNotIn('cont',self.backend.calls)
    def test_unexpected_running_owned_domain_is_stopped(self):
        self.backend.state.update(running=True,status='running');owner=self.owner()
        with self.assertRaisesRegex(mod.Refused,'CPUs executed'):owner.prepare(self.fd)
        self.assertFalse(self.backend.process)
    def test_missing_domain_but_live_process_is_not_reported_stopped(self):
        owner=self.owner();owner.prepare(self.fd);self.backend.live=False
        with self.assertRaisesRegex(mod.Refused,'does not prove'):owner.cleanup('lost-domain')
        self.assertFalse(owner.finished)
        self.assertFalse(any(e['phase']=='stopped' for e in owner.events))
    def test_failure_receipt_error_does_not_skip_cleanup(self):
        owner=self.owner();self.backend.fail='getfd'
        def record(event):
            if event['phase']=='failure':raise OSError('disk full')
        self.backend.record=record
        with self.assertRaises(RuntimeError):owner.prepare(self.fd)
        self.assertFalse(self.backend.process);self.assertTrue(owner.finished)
    def test_terminal_receipt_can_be_retried_without_second_destroy(self):
        owner=self.owner();owner.prepare(self.fd)
        def record(event):
            if event['phase']=='stopped':raise OSError('disk full')
        self.backend.record=record
        with self.assertRaises(OSError):owner.cleanup('stop')
        self.assertFalse(owner.finished);self.assertFalse(self.backend.process)
        self.backend.record=lambda event:None
        owner.cleanup('retry')
        self.assertTrue(owner.finished);self.assertEqual(self.backend.calls.count('destroy'),1)
        self.assertEqual(owner.events[-1]['reason'],'stop')
    def test_lost_cont_reply_records_possible_execution(self):
        owner=self.owner();owner.prepare(self.fd);self.backend.fail='cont'
        with self.assertRaises(RuntimeError):owner.resume()
        self.assertTrue(owner.events[-1]['resume_attempted'])
        self.assertFalse(owner.events[-1]['resumed']);self.assertFalse(self.backend.process)
    def test_first_snapshot_failure_reconciles_owner_for_cleanup(self):
        owner=self.owner();original=self.backend.snapshot
        calls=[]
        def snapshot(name):
            calls.append(name)
            if len(calls)==1:raise TimeoutError('lost snapshot')
            return original(name)
        self.backend.snapshot=snapshot
        with self.assertRaises(TimeoutError):owner.prepare(self.fd)
        self.assertFalse(self.backend.process);self.assertTrue(owner.finished)
    def test_unresolved_create_cannot_be_retried(self):
        owner=self.owner();self.backend.fail='create-reply'
        self.backend.reconcile_creation=lambda p:dict(outcome='unknown')
        with self.assertRaises(mod.Refused):owner.prepare(self.fd)
        with self.assertRaisesRegex(mod.Refused,'already used'):owner.prepare(self.fd)
        self.assertEqual(self.backend.calls.count('create'),1)
    def test_unresolved_resume_cannot_be_retried(self):
        owner=self.owner();owner.prepare(self.fd);self.backend.fail='cont'
        self.backend.process_gone=lambda identity:False
        with self.assertRaises(mod.Refused):owner.resume()
        with self.assertRaisesRegex(mod.Refused,'invalid resume'):owner.resume()
        self.assertEqual(self.backend.calls.count('cont'),1)
    def test_lost_first_observation_with_proven_process_exit(self):
        owner=self.owner()
        def snapshot(name):
            self.backend.live=False;self.backend.process=False
            raise TimeoutError('guest disappeared')
        self.backend.snapshot=snapshot
        self.backend.reconcile_creation=lambda p:dict(outcome='no-process')
        with self.assertRaises(TimeoutError):owner.prepare(self.fd)
        self.assertTrue(owner.finished);self.assertFalse(self.backend.process)
    def test_external_domain_disappearance_records_stop_without_destroy(self):
        owner=self.owner();owner.prepare(self.fd);owner.resume();self.backend.live=False;self.backend.process=False
        owner.cleanup('domain-disappeared')
        self.assertTrue(owner.finished);self.assertNotIn('destroy',self.backend.calls)


if __name__=='__main__':unittest.main()
