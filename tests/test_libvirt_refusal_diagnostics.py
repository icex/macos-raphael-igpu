import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import test_libvirt_capture_exit as fixture
from test_libvirt_capture_exit import entry,sup,CID

class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.base=self.root/'42';self.base.mkdir()
        (self.base/'task').mkdir();(self.base/'fd').mkdir();self.identity=dict(pid=42,start_ticks=123)
        self.stat(self.base/'stat');(self.base/'wchan').write_text('wait_for_completion\n')
    def stat(self,path,state='D',flags=4,ticks=123):
        fields=[state]+['0']*19;fields[6]=str(flags);fields[19]=str(ticks)
        path.write_text('42 (name with ) spaces) '+' '.join(fields))
    def inspect(self):
        with patch.object(entry.time,'monotonic',return_value=1):
            return entry.refusal_diagnostics(self.identity,self.root)
    def test_valid_bounded_flags_symbol_and_tasks(self):
        task=self.base/'task/42';task.mkdir();self.stat(task/'stat')
        r=self.inspect();self.assertEqual(r['diag_flags'],4)
        self.assertEqual(r['diag_wchan'],'wait_for_completion');self.assertEqual(r['diag_task_count'],1)
        self.assertEqual(r['diag_tasks'],[dict(tid=42,state='D',flags=4,start_ticks=123)])
        self.assertEqual(r['diag_errors'],[])
        self.assertNotIn('exited',r);self.assertNotIn('shutdown_wait',r)
    def test_descriptor_names_only_and_second_observation(self):
        task=self.base/'task/42';task.mkdir();self.stat(task/'stat',state='R')
        (self.base/'fd/3').symlink_to('/secret/not-followed')
        with patch.object(entry.os,'readlink',side_effect=AssertionError('no targets')):
            r=self.inspect()
        self.assertEqual(r['diag_fd_count'],1)
        self.assertFalse(r['diag_fds_truncated'])
        self.assertEqual(r['diag_second_task_count'],1)
        self.assertEqual(r['diag_second_tasks'][0]['state'],'R')
        self.assertEqual(r['diag_final_stat'],dict(state='D',flags=4,start_ticks=123))
        self.assertNotIn('secret',json.dumps(r))

    def test_descriptor_limit_and_inaccessible_directory(self):
        for n in range(70):(self.base/'fd'/str(n)).touch()
        r=self.inspect();self.assertEqual(r['diag_fd_count'],64)
        self.assertTrue(r['diag_fds_truncated'])
        original=entry.os.scandir
        def denied(path):
            if path==self.base/'fd':raise PermissionError('secret')
            return original(path)
        with patch.object(entry.os,'scandir',side_effect=denied):r=self.inspect()
        self.assertNotIn('diag_fd_count',r)
        self.assertIn('fd:permission',r['diag_errors'])

    def test_identity_change_during_fd_scan_discards_rechecked_observations(self):
        original=entry.os.scandir
        def changed(path):
            if path==self.base/'fd':self.stat(self.base/'stat',ticks=456)
            return original(path)
        with patch.object(entry.os,'scandir',side_effect=changed):r=self.inspect()
        self.assertNotIn('diag_fd_count',r);self.assertNotIn('diag_final_stat',r)
        self.assertNotIn('diag_second_task_count',r)
        self.assertIn('fd:identity-changed',r['diag_errors'])
        self.assertIn('stat2:identity-changed',r['diag_errors'])

    def test_fd_observation_cannot_restart_original_budget(self):
        original=entry.os.scandir; clock=[1]
        def expires(path):
            if path==self.base/'fd':clock[0]=1.021
            return original(path)
        (self.base/'fd/3').touch()
        with patch.object(entry.os,'scandir',side_effect=expires), patch.object(entry.time,'monotonic',side_effect=lambda:clock[0]):
            r=entry.refusal_diagnostics(self.identity,self.root)
        self.assertTrue(r['diag_budget_exhausted'])
        self.assertNotIn('diag_fd_count',r);self.assertNotIn('diag_final_stat',r)
        self.assertIn('fd:budget',r['diag_errors'])

    def test_malformed_oversized_and_identity_changed_stat(self):
        for data,error in [('bad','malformed'),('x'*4097,'oversized')]:
            (self.base/'stat').write_text(data)
            r=self.inspect();self.assertEqual(r['diag_errors'],['stat:'+error]);self.assertNotIn('diag_flags',r)
        self.stat(self.base/'stat',ticks=456)
        self.assertEqual(self.inspect()['diag_errors'],['stat:identity-changed'])
    def test_permission_and_missing_are_best_effort_without_exception_text(self):
        with patch.object(entry.os,'open',side_effect=PermissionError('secret path')):
            r=self.inspect()
        self.assertEqual(r['diag_errors'],['stat:permission']);self.assertNotIn('secret',json.dumps(r))
        (self.base/'wchan').unlink();r=self.inspect()
        self.assertEqual(r['diag_flags'],4);self.assertEqual(r['diag_errors'],['wchan:missing'])
    def test_wchan_rejects_addresses_paths_and_oversized_strings(self):
        for value in ('0xffff012345','/private/path','x'*129):
            (self.base/'wchan').write_text(value);r=self.inspect()
            self.assertNotIn('diag_wchan',r);self.assertTrue(r['diag_errors'])
    def test_task_sampling_and_count_are_bounded_even_on_read_failure(self):
        for n in range(80):(self.base/'task'/str(n+100)).mkdir()
        r=self.inspect();self.assertEqual(r['diag_task_count'],64)
        self.assertTrue(r['diag_tasks_truncated']);self.assertEqual(len(r['diag_errors']),16)
    def test_time_budget_does_not_delay_or_authorize_completion(self):
        with patch.object(entry.time,'monotonic',side_effect=[1,1.021]):
            r=entry.refusal_diagnostics(self.identity,self.root)
        self.assertTrue(r['diag_budget_exhausted']);self.assertEqual(r['diag_errors'],['stat:budget'])
    def test_symlink_is_not_followed(self):
        (self.base/'wchan').unlink();(self.base/'wchan').symlink_to('/etc/passwd')
        r=self.inspect();self.assertNotIn('diag_wchan',r);self.assertEqual(r['diag_errors'],['wchan:io'])

class HostDiagnosticTests(unittest.TestCase):
    setUp=fixture.CaptureExitTests.setUp
    command=fixture.CaptureExitTests.command
    invoke=fixture.CaptureExitTests.invoke
    def test_diagnostics_never_change_original_live_process_refusal(self):
        self.proof=dict(exited=False,refusal=dict(stage='original-process',code='original-pid-present',pid=42,state='D',
            diag_flags=4,diag_wchan='wait_for_completion',diag_task_count=1,
            diag_tasks_truncated=False,diag_budget_exhausted=False,diag_errors=['task:missing','secret'],
            diag_tasks=[dict(tid=42,state='D',flags=4,start_ticks=123,argv='secret')],
            diag_fd_count=0,diag_fds_truncated=False,diag_second_task_count=1,
            diag_second_tasks=[dict(tid=42,state='R',flags=4,start_ticks=123)],
            diag_final_stat=dict(state='R',flags=4,start_ticks=123,argv='secret')))
        result,stop=self.invoke();stop.assert_called_once_with(CID)
        self.assertFalse(result['deferred']);self.assertEqual(self.clock,0)
        self.assertEqual(result['proof_refusal']['diag_flags'],4)
        self.assertEqual(result['proof_refusal']['diag_fd_count'],0)
        self.assertEqual(result['proof_refusal']['diag_final_stat']['state'],'R')
        self.assertNotIn('secret',json.dumps(result))
    def test_malformed_diagnostic_fields_are_discarded(self):
        self.proof=dict(exited=False,refusal=dict(stage='original-process',code='original-pid-present',pid=42,state='D',
            diag_flags=True,diag_wchan='/secret',diag_task_count=99,diag_tasks_truncated='yes',
            diag_tasks=[dict(tid=42,state='D',flags=-1,start_ticks=123)],
            diag_fd_count=True,diag_fds_truncated='no',diag_second_task_count=99,
            diag_final_stat=dict(state='R',flags=True,start_ticks=123)))
        result,stop=self.invoke();stop.assert_called_once_with(CID)
        self.assertNotIn('diag_flags',result['proof_refusal']);self.assertNotIn('diag_wchan',result['proof_refusal'])
        self.assertEqual(result['proof_refusal']['diag_tasks'],[])
        for key in ('diag_fd_count','diag_fds_truncated','diag_second_task_count','diag_final_stat'):
            self.assertNotIn(key,result['proof_refusal'])
