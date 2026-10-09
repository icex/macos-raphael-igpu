import importlib.util
import json
from collections import deque
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('lifecycle_local',Path(__file__).resolve().parents[1]/'tools/libvirt-console-local.py')
local=importlib.util.module_from_spec(spec);spec.loader.exec_module(local)

class LifecycleObservationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.backend=local.LocalBackend.__new__(local.LocalBackend)
        b=self.backend;b.event_path=Path(self.tmp.name)/'events.jsonl';b.record_lock=threading.Lock()
        b.pending=deque();b.event_error=None
        b.lv=SimpleNamespace(VIR_DOMAIN_EVENT_SHUTDOWN=6,VIR_DOMAIN_EVENT_SHUTDOWN_GUEST=1)
        b.scope={'kind':'pid-namespace','device':1,'inode':2,'init_start_ticks':3}
        b.attempt=dict(name='rgpu-owned',uuid='zero',run_id='run')
        b.known_identity=dict(b.attempt,pid=113,start_ticks=100)
        self.domain=SimpleNamespace(name=lambda:'rgpu-owned',UUIDString=lambda:'zero')
    def observe(self,event=6,detail=1):
        self.backend.lifecycle(None,self.domain,event,detail,None)
        return json.loads(self.backend.event_path.read_text().splitlines()[-1])
    def test_guest_event_persisted_before_exit_reason_drain(self):
        row=self.observe();self.assertEqual(len(self.backend.pending),1)
        self.assertTrue(row['guest_shutdown']);self.assertTrue(row['identity_bound'])
        self.assertEqual(row['identity'],self.backend.known_identity)
        self.assertEqual(row['scope'],self.backend.scope)
        self.assertEqual(row['phase'],'libvirt-lifecycle-observed')
    def test_host_unknown_and_stopped_are_not_guest_shutdown(self):
        for event,detail in [(6,0),(6,2),(5,0),(5,1)]:
            self.assertFalse(self.observe(event,detail)['guest_shutdown'])
    def test_unbound_identity_never_qualifies_guest_event(self):
        for field in ['name','uuid','run_id']:
            original=self.backend.known_identity[field];self.backend.known_identity[field]='different'
            row=self.observe();self.assertFalse(row['guest_shutdown']);self.assertIsNone(row['identity'])
            self.backend.known_identity[field]=original
        self.backend.known_identity=None;self.assertFalse(self.observe()['guest_shutdown'])
    def test_different_domain_does_not_borrow_owner(self):
        self.domain.name=lambda:'other'
        self.assertFalse(self.observe()['identity_bound'])
    def test_persistence_error_is_retained_and_event_still_queued(self):
        error=OSError('write failed')
        with patch.object(self.backend,'record',side_effect=error):
            self.backend.lifecycle(None,self.domain,6,1,None)
        self.assertIs(self.backend.event_error,error)
        self.assertEqual(len(self.backend.pending),1)
