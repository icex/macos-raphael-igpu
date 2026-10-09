import importlib.util
import os
from pathlib import Path
import struct
import subprocess
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('agent',Path(__file__).resolve().parents[1]/'tools/console-vdagent-agent.py')
agent=importlib.util.module_from_spec(spec);spec.loader.exec_module(agent)

class Clock:
    def __init__(self):self.now=0
    def __call__(self):return self.now

def row(width=2468,height=1484):
    payload=struct.pack('<IIIIIiiHH',1,3,height,width,32,0,0,400,700)
    return agent.monitors.MonitorParser().feed(agent.monitors.packet(2,payload))[0]

class SessionAgentTests(unittest.TestCase):
    def handler(self,apply=None):
        self.clock=Clock();self.records=[];self.calls=[]
        def verified(w,h,timeout):
            self.calls.append((w,h,timeout))
            return dict(passed=True,pixel_width=w,pixel_height=h,display=123)
        return agent.Handler(apply or verified,self.records.append,self.clock)

    def process(self,handler,request,remaining):
        return handler.handle(request,remaining)+handler.flush(remaining)

    def success(self,response):return struct.unpack('<II',response[-8:])==(2,1)

    def test_long_session_is_not_limited_to_diagnostic_quota(self):
        handler=self.handler()
        for index in range(1000):
            self.clock.now=index*.5
            self.assertTrue(self.success(self.process(handler,row(),6000-self.clock())))
        self.assertEqual(handler.applied,1000)

    def test_odd_geometry_never_reaches_holder(self):
        handler=self.handler();self.assertFalse(self.success(self.process(handler,row(2467),100)))
        self.assertEqual(self.calls,[])

    def test_wrong_port_never_reaches_holder(self):
        handler=self.handler();request=row();request['port']=2
        self.assertFalse(self.success(self.process(handler,request,100)));self.assertEqual(self.calls,[])

    def test_success_requires_exact_geometry(self):
        handler=self.handler(lambda *args:dict(passed=True,pixel_width=3840,pixel_height=2160))
        self.assertFalse(self.success(self.process(handler,row(),100)))
        self.assertEqual(handler.applied,0)

    def test_holder_loss_refuses_without_touching_presenter(self):
        def missing(*args):raise ConnectionRefusedError()
        handler=self.handler(missing)
        self.assertFalse(self.success(self.process(handler,row(),100)))
        self.assertEqual(self.records[-1]['reason'],'ConnectionRefusedError')

    def test_deadline_does_not_start_operation(self):
        handler=self.handler();self.assertFalse(self.success(self.process(handler,row(),2.9)))
        self.assertEqual(self.calls,[])

    def test_burst_budget_refills(self):
        clock=Clock();budget=agent.Budget(10,2,clock);budget.consume(10)
        with self.assertRaises(ValueError):budget.consume(1)
        clock.now=1;budget.consume(2)
        with self.assertRaises(ValueError):budget.consume(1)

    def test_last_drag_request_applies_after_interval_without_more_input(self):
        handler=self.handler();self.assertTrue(self.success(self.process(handler,row(),100)))
        self.clock.now=.1;self.assertEqual(handler.handle(row(2500),100),b'')
        self.assertEqual(handler.flush(100),b'')
        self.clock.now=.2;self.assertFalse(self.success(handler.handle(row(2600),100)))
        self.clock.now=.25;self.assertTrue(self.success(handler.flush(100)))
        self.assertEqual([r[0] for r in self.calls],[2468,2600])
        self.assertIsNone(handler.pending)

    def test_disconnect_cancels_only_unapplied_request(self):
        handler=self.handler();handler.handle(row(),100);handler.disconnect()
        self.assertEqual(handler.flush(100),b'');self.assertEqual(self.calls,[])

    def test_pending_request_refused_near_deadline(self):
        handler=self.handler();handler.handle(row(),100)
        self.assertFalse(self.success(handler.flush(2.9)));self.assertEqual(self.calls,[])

    def test_holder_inventory_refuses_foreign_and_missing_self(self):
        for stdout,code,stderr,own in [('p123\n',0,'',False),('',1,'',True),('p123\n',0,'',True),('',1,'warning',False)]:
            with self.subTest(stdout=stdout,code=code,own=own):
                result=subprocess.CompletedProcess([],code,stdout,stderr)
                with patch.object(agent.subprocess,'run',return_value=result),self.assertRaises(RuntimeError):agent.holders(own)

    def test_holder_inventory_accepts_empty_then_only_self(self):
        with patch.object(agent.subprocess,'run',return_value=subprocess.CompletedProcess([],1,'','')):agent.holders()
        with patch.object(agent.subprocess,'run',return_value=subprocess.CompletedProcess([],0,f'p{os.getpid()}\n','')):agent.holders(True)

if __name__=='__main__':unittest.main()
