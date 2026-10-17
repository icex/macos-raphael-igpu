import errno
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch
from test_libvirt_capture_exit import entry


class ZombieProofTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'42';self.root.mkdir()
        (self.root/'task'/'42').mkdir(parents=True);(self.root/'fd').mkdir()
        self.identity=dict(pid=42,start_ticks=43);self.write_stat()
    def write_stat(self,state='Z',ticks=43):
        (self.root/'stat').write_text('42 (qemu-system-x86) '+' '.join([state]+['0']*18+[str(ticks)]))
    def proof(self, diagnostic=None):
        with patch.object(entry,'Path',side_effect=lambda value:self.root if str(value)=='/proc/42' else Path(value)):
            return entry.completed_original_zombie(self.identity,diagnostic)
    def test_exact_zombie_with_no_worker_or_descriptor_passes(self):self.assertTrue(self.proof())
    def test_live_states_reused_pid_workers_and_fds_refuse(self):
        for state in ('R','S','D','T','X'):
            self.write_stat(state);self.assertFalse(self.proof())
        self.write_stat(ticks=44);self.assertFalse(self.proof());self.write_stat()
        (self.root/'task'/'99').mkdir();self.assertFalse(self.proof());(self.root/'task'/'99').rmdir()
        (self.root/'fd'/'7').touch();self.assertFalse(self.proof())
    def test_refusal_identifies_failed_predicate_without_weakening_result(self):
        report={};(self.root/'task'/'99').mkdir()
        self.assertFalse(self.proof(report))
        self.assertEqual(report,dict(completion_reason='not-sole-task',completion_task_count=2,
                                    completion_tasks=[dict(tid=42,state='unknown'),dict(tid=99,state='unknown')],
                                    completion_tasks_truncated=False))
        (self.root/'task'/'99').rmdir();(self.root/'fd'/'7').touch();report={}
        self.assertFalse(self.proof(report));self.assertEqual(report,dict(completion_reason='descriptors-present'))
        (self.root/'fd'/'7').unlink();self.write_stat(ticks=44);report={}
        self.assertFalse(self.proof(report));self.assertEqual(report,dict(completion_reason='initial-state-changed'))
    def test_partial_missing_proc_data_is_not_reaping(self):
        (self.root/'stat').unlink();self.assertFalse(self.proof())
        shutil.rmtree(self.root);self.assertTrue(self.proof())
    def test_permission_failure_is_not_absence(self):
        with patch.object(entry.Path,'read_text',side_effect=PermissionError(13,'private')):
            with self.assertRaises(PermissionError):self.proof()
    def test_descriptor_permission_failure_is_not_completion(self):
        original=Path.iterdir
        def scan(path):
            if path==self.root/'fd':
                raise PermissionError(errno.EACCES,'private',str(path))
            return original(path)
        with patch.object(entry.Path,'iterdir',new=scan):
            with self.assertRaises(PermissionError) as caught:self.proof()
        self.assertEqual(caught.exception.errno,errno.EACCES)
        self.assertEqual(caught.exception.filename,str(self.root/'fd'))
    def test_worker_diagnostics_do_not_authorize_completion(self):
        (self.root/'task'/'99').mkdir()
        (self.root/'task'/'99'/'stat').write_text('99 (worker) '+' '.join(['S']+['0']*18+['77']))
        details={}
        with patch.object(entry,'Path',side_effect=lambda value:self.root if str(value)=='/proc/42' else Path(value)):
            self.assertFalse(entry.completed_original_zombie(self.identity,details))
        self.assertEqual(details['completion_reason'],'not-sole-task')
        self.assertEqual(details['completion_task_count'],2)
        self.assertIn({'tid':99,'state':'S','start_ticks':77},details['completion_tasks'])
        self.assertIn({'tid':42,'state':'unknown'},details['completion_tasks'])

    def test_changed_state_during_inspection_refuses(self):
        original=Path.read_text;calls=0
        def read(path,*a,**kw):
            nonlocal calls
            if path==self.root/'stat':
                calls+=1
                if calls==2:self.write_stat(ticks=44)
            return original(path,*a,**kw)
        with patch.object(entry.Path,'read_text',new=read):self.assertFalse(self.proof())


@unittest.skipUnless(Path('/proc/self/stat').exists() and shutil.which('cc'),'Linux proc and C compiler required')
class RealZombieTests(unittest.TestCase):
    def test_zombie_leader_refuses_then_completed_child_obeys_descriptor_visibility(self):
        # pthread_exit leaves a zombie group leader while the worker owns files.
        source=r'''
#include <pthread.h>
#include <unistd.h>
static void *worker(void *p){(void)p;for(;;)pause();return 0;}
int main(void){pthread_t t;if(pthread_create(&t,0,worker,0))return 2;pthread_exit(0);}
'''
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'worker.c').write_text(source)
            subprocess.run(['cc','-pthread',str(root/'worker.c'),'-o',str(root/'worker')],check=True,capture_output=True)
            proc=subprocess.Popen([str(root/'worker')])
            try:
                deadline=time.monotonic()+3
                while time.monotonic()<deadline:
                    raw=Path(f'/proc/{proc.pid}/stat').read_text().rsplit(')',1)[1].split()
                    if raw[0]=='Z':break
                    time.sleep(.01)
                self.assertEqual(raw[0],'Z')
                identity=dict(pid=proc.pid,start_ticks=int(raw[19]))
                self.assertGreater(len(list(Path(f'/proc/{proc.pid}/task').iterdir())),1)
                self.assertFalse(entry.completed_original_zombie(identity))
                os.kill(proc.pid,signal.SIGKILL)
                deadline=time.monotonic()+3
                tasks=Path(f'/proc/{proc.pid}/task')
                while time.monotonic()<deadline and {p.name for p in tasks.iterdir()}!={str(proc.pid)}:
                    time.sleep(.01)
                self.assertEqual({p.name for p in tasks.iterdir()},{str(proc.pid)})
                # Some hosted kernels deny even the parent's fd-directory scan
                # once this pthread leader is fully dead. That is an expected
                # conservative refusal, not evidence of completed ownership.
                fd=Path(f'/proc/{proc.pid}/fd')
                try:
                    descriptors=list(fd.iterdir())
                except PermissionError as denied:
                    self.assertIn(denied.errno,(errno.EACCES,errno.EPERM))
                    self.assertEqual(denied.filename,str(fd))
                    with self.assertRaises(PermissionError) as caught:
                        entry.completed_original_zombie(identity)
                    self.assertEqual(caught.exception.errno,denied.errno)
                    self.assertEqual(caught.exception.filename,str(fd))
                else:
                    self.assertEqual(descriptors,[])
                    self.assertTrue(entry.completed_original_zombie(identity))
            finally:
                proc.kill();proc.wait(timeout=3)
