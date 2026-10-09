import json
import os
from pathlib import Path
import runpy
import socket
import tempfile
import unittest
from unittest.mock import patch
import test_libvirt_shutdown_wait as old
from test_libvirt_capture_exit import CID, RUN, ADMIT, START
from test_sercat import TOOL

class ActualUnixResetTests(unittest.TestCase):
    def test_unread_reverse_data_is_reset_and_never_clean_eof(self):
        self.run_reset(False)
    def test_reset_plus_failed_sync_never_publishes_observation(self):
        self.run_reset(True)
    def run_reset(self,fail):
        with tempfile.TemporaryDirectory() as td:
            base=Path(td);reset=base/'reset.json';eof=base/'eof.json'
            left,right=socket.socketpair();self.addCleanup(left.close)
            left.sendall(b'RGPUQ2\n');right.sendall(b'captured bytes');right.close()
            class Connected:
                def connect(self,path):pass
                def __getattr__(self,name):return getattr(left,name)
            env=dict(VM_SERIAL_SOCKET=td+'/socket',VM_SERIAL_OUTPUT=td+'/serial.log',
                VM_SERIAL_CID=CID,VM_SERIAL_CHANNEL='console',VM_SERIAL_EOF=str(eof),
                VM_SERIAL_RESET=str(reset),VM_SERIAL_STARTED_AT=START,
                VM_SERIAL_RUN_ID=RUN,VM_SERIAL_ADMISSION_SHA256=ADMIT)
            real_sync=os.fsync
            def sync(fd):
                if fail:raise OSError('sync failed')
                return real_sync(fd)
            with patch.dict(os.environ,env,clear=True),patch.object(socket,'socket',return_value=Connected()),patch('os.fsync',side_effect=sync),self.assertRaises((SystemExit,OSError)) as caught:
                runpy.run_path(str(TOOL),run_name='__main__')
            self.assertFalse(eof.exists());self.assertEqual(reset.exists(),not fail)
            if not fail:
                self.assertIn('ConnectionResetError errno=104',str(caught.exception))
                d=json.loads(reset.read_text());self.assertEqual(d['kind'],'recv-reset')
                self.assertEqual(d['operation'],'recv');self.assertEqual(d['errno'],104)
                self.assertNotIn('eof_monotonic',d)

class RejectedCollectorErrorTests(unittest.TestCase):
    def test_send_reset_and_other_receive_error_never_publish(self):
        for operation in ('send','recv'):
            with self.subTest(operation=operation),tempfile.TemporaryDirectory() as td:
                base=Path(td);reset=base/'reset.json';eof=base/'eof.json'
                env=dict(VM_SERIAL_SOCKET=td+'/socket',VM_SERIAL_OUTPUT=td+'/serial.log',
                    VM_SERIAL_CID=CID,VM_SERIAL_CHANNEL='critical',VM_SERIAL_EOF=str(eof),
                    VM_SERIAL_RESET=str(reset),VM_SERIAL_STARTED_AT=START,
                    VM_SERIAL_RUN_ID=RUN,VM_SERIAL_ADMISSION_SHA256=ADMIT)
                class Broken:
                    def connect(self,path):pass
                    def settimeout(self,seconds):pass
                    def sendall(self,data):raise ConnectionResetError(104,'reset')
                    def recv(self,n):raise OSError(5,'io')
                if operation=='send':
                    (base/f'critical-quiesce-{CID}.request').write_text(f'RGPUQ2 v=1 cid={CID} b={"d"*32} run={RUN}\n')
                with patch.dict(os.environ,env,clear=True),patch.object(socket,'socket',return_value=Broken()),self.assertRaises(SystemExit):
                    runpy.run_path(str(TOOL),run_name='__main__')
                self.assertFalse(reset.exists());self.assertFalse(eof.exists())

class ResetHostTests(unittest.TestCase):
    command=old.ShutdownWaitHostTests.command
    invoke_channel=old.ShutdownWaitHostTests.invoke_channel
    def setUp(self):
        old.ShutdownWaitHostTests.setUp(self)
        self.reset=dict(self.eof,kind='recv-reset',operation='recv',errno=104,
            reset_monotonic=self.eof['eof_monotonic'],reset_epoch=self.eof['eof_epoch'])
        self.reset.pop('eof_monotonic');self.reset.pop('eof_epoch')
    def marker(self):
        (self.vm/'run'/f'capture-reset-{CID}-console.json').write_text(json.dumps(self.reset))
    def test_reset_event_overlap_then_completion(self):
        self.marker();complete=self.proof;self.proof=self.waiting;original=self.command
        def command(args,**kwargs):
            if args[1]=='exec' and self.clock>10:self.proof=complete
            return original(args,**kwargs)
        self.command=command
        result,stop=self.invoke_channel(False);stop.assert_not_called()
        self.assertEqual(result['transport_end_kind'],'recv-reset');self.assertTrue(result['shutdown_event_wait'])
    def test_live_reset_is_immediate(self):
        self.marker();self.proof={'exited':False}
        result,stop=self.invoke_channel(False);stop.assert_called_once_with(CID);self.assertFalse(result['deferred'])
    def test_dual_or_dangling_eof_does_not_select_reset(self):
        self.marker();self.proof=self.waiting;self.live=[True]
        eof=self.vm/'run'/f'capture-eof-{CID}-console.json'
        eof.write_text(json.dumps(self.eof))
        result,stop=self.invoke_channel(False);stop.assert_called_once_with(CID);self.assertFalse(result['deferred'])
        eof.unlink();eof.symlink_to(self.vm/'missing')
        result,stop=self.invoke_channel(False);stop.assert_called_once_with(CID);self.assertFalse(result['deferred'])
    def test_send_other_errno_wrong_identity_or_late_event_refuse(self):
        self.proof=self.waiting;self.live=[True]
        for key,bad in [('operation','send-control'),('errno',32),('kind','clean-eof'),('cid','wrong'),('reset_monotonic',float('nan'))]:
            with self.subTest(key=key):
                old_value=self.reset[key];self.reset[key]=bad;self.marker()
                result,stop=self.invoke_channel(False);stop.assert_called_once_with(CID);self.assertFalse(result['deferred'])
                self.reset[key]=old_value
