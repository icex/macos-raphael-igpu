import importlib.util
from pathlib import Path
import socket
import struct
import threading
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('monitors',Path(__file__).resolve().parents[1]/'tools/console-vdagent-monitors.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
def config(w=2560,h=1440,count=1,flags=0,depth=32,x=0,y=0):return struct.pack('<IIIIIii',count,flags,h,w,depth,x,y)

class MonitorTests(unittest.TestCase):
    def test_exact_geometry_and_layout(self):
        self.assertEqual(m.configuration(config())['width'],2560)
        for args in [dict(count=2),dict(flags=1),dict(flags=3),dict(depth=24),dict(x=1),dict(y=-1),dict(w=3841),dict(h=2161),dict(w=0)]:
            with self.subTest(args=args),self.assertRaises(ValueError):m.configuration(config(**args))
        with self.assertRaises(ValueError):m.configuration(config()+b'physical-size')
    def test_fragmented_monitor_and_capability_share_validated_chunk(self):
        packet=m.packet(2,config());p=m.MonitorParser();rows=[]
        for byte in packet:rows.extend(p.feed(bytes([byte])))
        self.assertEqual(rows[0]['configuration']['height'],1440)
        self.assertNotIn('payload',rows[0])
        self.assertEqual(p.feed(m.capabilities(1,True))[0]['caps'],[6])
    def test_bad_config_retains_error_but_no_feature_payload(self):
        row=m.MonitorParser().feed(m.packet(2,config(flags=3)))[0]
        self.assertIn('configuration_error',row);self.assertNotIn('configuration',row)
    def test_helper_false_success_or_wrong_dimensions_refused(self):
        import json,subprocess
        for code,passed,w in [(1,True,2560),(0,False,2560),(0,True,1280)]:
            result=subprocess.CompletedProcess([],code,json.dumps(dict(passed=passed,actual=dict(pixel_width=w,pixel_height=1440))),'')
            with patch.object(m.subprocess,'run',return_value=result):
                self.assertFalse(m.apply_mode(Path('/helper'),m.configuration(config()),5)['passed'])
    def test_success_reply_requires_verified_application(self):
        now=[0.];writes=[];rows=[]
        def write(fd,data):
            writes.append(bytes(data))
            if len(writes)==2:now[0]=6.
            return len(data)
        with patch.object(m.select,'select',side_effect=[([99],[99],[]),([],[99],[])]), \
             patch.object(m.os,'write',side_effect=write), \
             patch.object(m.os,'read',return_value=m.packet(2,config())), \
             patch.object(m,'apply_mode',return_value={'passed':True}) as apply:
            result=m.serve(99,6,True,True,Path('/helper'),rows.append,clock=lambda:now[0])
        self.assertEqual(apply.call_count,1)
        self.assertEqual(writes[1],m.packet(3,struct.pack('<II',2,1)))
        self.assertEqual(result['verified_applications'],1)
    def run_peer(self,enabled,apply=False,payload=None):
        a,b=socket.socketpair();a.setblocking(False);b.settimeout(2);rows=[];errors=[];wire=[]
        def peer():
            try:
                data=b''
                while len(data)<36:data+=b.recv(36-len(data))
                wire.append(data);b.sendall(m.packet(2,payload or config()))
                if enabled:
                    data=b''
                    while len(data)<36:data+=b.recv(36-len(data))
                    wire.append(data)
            except BaseException as e:errors.append(e)
        t=threading.Thread(target=peer);t.start()
        try:
            # Fake only helper application; socket transport, parser and replies are real.
            with patch.object(m,'apply_mode',return_value={'passed':True}) as call:
                result=m.serve(a.fileno(),.05,enabled,apply,Path('/helper'),rows.append)
                self.assertFalse(call.called) # Insufficient bounded helper time prohibits application.
        finally:t.join(3);a.close();b.close()
        self.assertEqual(errors,[]);self.assertFalse(t.is_alive())
        return result,rows,wire
    def test_default_advertises_zero_and_records_without_reply(self):
        result,rows,wire=self.run_peer(False)
        self.assertEqual(wire,[m.capabilities(1,False)])
        self.assertEqual(result['requests'],1);self.assertIsNone(rows[0]['reply_success'])
    def test_observe_replies_error_never_success(self):
        result,rows,wire=self.run_peer(True)
        self.assertEqual(wire[0],m.capabilities(1,True))
        self.assertEqual(wire[1],m.packet(3,struct.pack('<II',2,2)))
        self.assertEqual(result['verified_applications'],0)
    def test_apply_with_insufficient_remaining_time_refuses(self):
        result,rows,wire=self.run_peer(True,True)
        self.assertEqual(rows[0]['apply_error'],'insufficient bounded helper time')
        self.assertEqual(wire[1],m.packet(3,struct.pack('<II',2,2)))

if __name__=='__main__':unittest.main()
