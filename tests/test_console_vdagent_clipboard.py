"""Actual wire parser/state machine, simulated pasteboard; no native AppKit claim."""
import importlib.util
from pathlib import Path
import struct
import unittest
import sys
import subprocess
import os
import select
import socket
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('clipboard_agent_test',ROOT/'tools/console-vdagent-agent.py')
agent=importlib.util.module_from_spec(spec);spec.loader.exec_module(agent)
clip=agent.clipboard_module

class Backend:
    def __init__(self):self.count=10;self.data=b'private pre-session';self.reads=0;self.writes=[]
    def read(self,expected):
        self.reads+=1
        return self.count,0 if expected in (-1,self.count) else 1,None if expected in (-1,self.count) else self.data
    def write(self,expected,data):
        if expected!=self.count:raise BlockingIOError()
        self.writes.append(data);self.data=data;self.count+=1;return self.count
    def copy(self,data):self.count+=1;self.data=data

class ClipboardTests(unittest.TestCase):
    def setUp(self):
        self.now=0;self.backend=Backend();self.records=[]
        self.cb=clip.Clipboard(self.backend,self.records.append,lambda:self.now)
    def decode(self,wire):return agent.monitors.MonitorParser(clipboard_limit=clip.LIMIT).feed(wire)
    def incoming(self,kind,payload=b'',port=1):
        row=self.decode(clip.packet(kind,payload))[0];row['port']=port
        return self.cb.handle(row,30)
    def negotiate(self):self.cb.announce(dict(port=1,type=6,request=1,caps=[clip.CAPS]))
    def test_real_socketpair_bidirectional_text_with_partial_writes_and_resize_caps(self):
        local,peer=socket.socketpair();self.addCleanup(local.close);self.addCleanup(peer.close)
        local.setblocking(False);peer.setblocking(False)
        peer_parser=agent.monitors.MonitorParser(clipboard_limit=clip.LIMIT)
        actual_select=select.select;actual_write=os.write;events=[];sent_local=False;began=False
        remote='host Ω'.encode();guest=('guest 🙂'*1500).encode()
        def wait(readable,writable,exceptional,timeout):
            nonlocal began,sent_local
            self.now+=.01
            if not began:
                peer.sendall(agent.monitors.packet(6,struct.pack('<II',1,clip.CAPS))+clip.packet(7,struct.pack('<I',1)))
                began=True
            try:wire=peer.recv(65536)
            except BlockingIOError:wire=b''
            for row in peer_parser.feed(wire):
                events.append(row)
                if row['type']==8:peer.sendall(clip.packet(4,struct.pack('<I',1)+remote))
                if row['type']==7:peer.sendall(clip.packet(8,struct.pack('<I',1)))
            if self.backend.writes and not sent_local:
                self.backend.copy(guest);sent_local=True
            return actual_select(readable,writable,exceptional,0)
        def short_write(fd,data):return actual_write(fd,data[:113])
        with patch.object(agent.select,'select',side_effect=wait),patch.object(agent.os,'write',side_effect=short_write):
            agent.serve(local.fileno(),10,lambda *args:None,self.records.append,clock=lambda:self.now,clipboard_backend=self.backend)
        self.assertEqual(self.backend.writes,[remote])
        self.assertTrue(any(row['type']==6 and row['caps']==[6|clip.CAPS] for row in events))
        self.assertEqual([row['clipboard_payload'][4:] for row in events if row['type']==4],[guest])
        self.assertNotIn('host Ω',str(self.records));self.assertNotIn('guest',str(self.records))

    def test_disconnect_with_clipboard_backlog_refuses_cross_client_replay(self):
        local,peer=socket.socketpair();self.addCleanup(local.close);self.addCleanup(peer.close)
        local.setblocking(False);peer.setblocking(False)
        peer.sendall(agent.monitors.packet(6,struct.pack('<II',1,clip.CAPS))+
                     clip.packet(7,struct.pack('<I',1))+agent.monitors.packet(13,b'',2))
        with self.assertRaisesRegex(ValueError,'cross-client replay'):
            agent.serve(local.fileno(),3,lambda *args:None,self.records.append,clipboard_backend=self.backend)
        self.assertEqual(self.backend.writes,[])

    def test_helper_stdout_is_bounded_during_read_and_timeout_kills_owned_child(self):
        with self.assertRaisesRegex(ValueError,'output limit'):
            clip.helper_call([sys.executable,'-c','import os,time;os.write(1,b"x"*100000);time.sleep(5)'],b'')
        with self.assertRaises(subprocess.TimeoutExpired):
            clip.helper_call([sys.executable,'-c','import time;time.sleep(5)'],b'',timeout=.05)
        code,data=clip.helper_call([sys.executable,'-c','import sys;sys.stdout.buffer.write(sys.stdin.buffer.read())'],b'synthetic')
        self.assertEqual((code,data),(0,b'synthetic'))

    def test_disabled_and_server_port_never_access_pasteboard(self):
        self.incoming(7,struct.pack('<I',1));self.cb.poll(30)
        self.cb.announce(dict(port=2,caps=[clip.CAPS]));self.cb.poll(30)
        self.assertEqual(self.backend.reads,0)
        self.negotiate();self.incoming(7,struct.pack('<I',1),2)
        self.assertEqual(self.backend.reads,0)
    def test_no_initial_clipboard_export_and_demand_only_utf8(self):
        self.negotiate();self.assertEqual(self.cb.poll(30),b'')
        self.backend.copy('A\nΩ🙂'.encode());self.now=.5
        offer=self.decode(self.cb.poll(30));self.assertEqual(offer[0]['type'],7)
        self.assertEqual(offer[0]['clipboard_payload'],struct.pack('<I',1))
        data=self.decode(self.incoming(8,struct.pack('<I',1)))[0]
        self.assertEqual(data['clipboard_payload'],struct.pack('<I',1)+self.backend.data)
        self.assertNotIn('Ω',str(self.records));self.assertNotIn('private',str(self.records))
    def test_remote_text_applies_once_without_echo(self):
        self.negotiate();self.assertEqual(self.decode(self.incoming(7,struct.pack('<I',1)))[0]['type'],8)
        self.incoming(4,struct.pack('<I',1)+'Ω'.encode());self.cb.poll(30)
        self.assertEqual(self.backend.writes,['Ω'.encode()]);self.assertFalse(self.cb.owned)
        self.incoming(4,struct.pack('<I',1)+b'unsolicited')
        self.assertEqual(len(self.backend.writes),1)
    def test_new_local_copy_wins_over_outstanding_remote_response(self):
        self.negotiate();self.incoming(7,struct.pack('<I',1));self.backend.copy(b'new local')
        self.incoming(4,struct.pack('<I',1)+b'old remote');self.assertEqual(self.backend.writes,[])
        self.assertEqual(self.decode(self.cb.poll(30))[0]['type'],7)
    def test_regrab_drains_old_response_before_new_request(self):
        self.negotiate();self.incoming(7,struct.pack('<I',1))
        self.assertEqual(self.incoming(7,struct.pack('<I',1)),b'')
        response=self.incoming(4,struct.pack('<I',1)+b'stale')
        self.assertEqual(self.backend.writes,[]);self.assertEqual(self.decode(response)[0]['type'],8)
        self.incoming(4,struct.pack('<I',1)+b'latest');self.assertEqual(self.backend.writes,[b'latest'])
    def test_release_disconnect_timeout_do_not_clear_or_replay(self):
        self.negotiate();self.incoming(7,struct.pack('<I',1));self.incoming(9)
        self.incoming(4,struct.pack('<I',1)+b'stale');self.assertEqual(self.backend.writes,[])
        self.incoming(7,struct.pack('<I',1));self.now=6
        self.assertEqual(self.decode(self.cb.poll(30))[0]['type'],9);self.assertTrue(self.cb.disabled)
        self.cb.announce(dict(port=1,request=1,caps=[clip.CAPS]));self.assertTrue(self.cb.disabled)
        self.cb.disconnect();self.negotiate();self.assertEqual(self.cb.poll(30),b'')
        self.assertEqual(self.backend.data,b'private pre-session')
    def test_maximum_utf8_fragmented_at_every_boundary_and_limits(self):
        data=b'x'*clip.LIMIT;wire=clip.packet(4,struct.pack('<I',1)+data)
        parser=agent.monitors.MonitorParser(clipboard_limit=clip.LIMIT);rows=[]
        for i in range(0,len(wire),7):rows.extend(parser.feed(wire[i:i+7]))
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['clipboard_payload'][4:],data)
        self.assertEqual(parser.validator.pending()['wire_bytes'],0)
        # Existing monitor-only parser keeps its old 4KiB ceiling.
        with self.assertRaises(ValueError):agent.monitors.MonitorParser().feed(wire)
        oversized=struct.pack('<II',1,20)+struct.pack('<IIQI',1,4,0,16*1024*1024+1)
        with self.assertRaises(ValueError):agent.monitors.MonitorParser(clipboard_limit=clip.LIMIT).feed(oversized)
    def test_oversized_clipboard_stream_is_discarded_and_next_resize_survives(self):
        self.negotiate();self.incoming(7,struct.pack('<I',1))
        payload=struct.pack('<I',1)+b'x'*(2*clip.LIMIT)
        message=struct.pack('<IIQI',1,4,0,len(payload))+payload
        wire=b''.join(struct.pack('<II',1,len(message[i:i+2048]))+message[i:i+2048] for i in range(0,len(message),2048))
        wire+=agent.monitors.packet(2,struct.pack('<IIIIIii',1,0,1440,2560,32,0,0))
        parser=agent.monitors.MonitorParser(clipboard_limit=clip.LIMIT);rows=[]
        for i in range(0,len(wire),4096):
            rows.extend(parser.feed(wire[i:i+4096]))
            self.assertLessEqual(sum(map(len,parser.validator.ports.values())),4096)
        self.assertEqual(len(rows),2);self.assertTrue(rows[0]['clipboard_oversize'])
        self.assertNotIn('clipboard_payload',rows[0]);self.cb.handle(rows[0],30)
        self.assertEqual(self.backend.writes,[]);self.assertIsNone(self.cb.inflight)
        calls=[]
        def apply(w,h,t):
            calls.append((w,h));return dict(passed=True,pixel_width=w,pixel_height=h,width=w//2,height=h//2)
        handler=agent.Handler(apply,self.records.append)
        handler.handle(rows[1],30);handler.flush(30)
        self.assertEqual(calls,[(2560,1440)])

    def test_malformed_text_shapes_and_no_unsupported_selection_prefix(self):
        self.negotiate()
        for kind,data in [(7,b'x'),(8,b''),(9,b'\0'*4),(14,b''),(14,struct.pack('<i',-2)),
                          (4,struct.pack('<I',1)+b'\xff'),(4,struct.pack('<I',1)+b'zero\0'),
                          (4,struct.pack('<I',2)+b'image'),(4,struct.pack('<I',0)+b'bad')]:
            with self.subTest(kind=kind,data=data),self.assertRaises(ValueError):self.incoming(kind,data)
        self.assertEqual(clip.CAPS & ((1<<6)|(1<<17)),0)
    def test_remote_limit_and_changed_local_owner_refuse_data(self):
        self.negotiate();self.cb.poll(30);self.backend.copy(b'abc');self.now=.5;self.cb.poll(30)
        self.incoming(14,struct.pack('<i',3)) # client requires size strictly less than max
        self.assertEqual(self.decode(self.incoming(8,struct.pack('<I',1)))[0]['clipboard_payload'],struct.pack('<I',0))
        self.incoming(14,struct.pack('<i',-1));self.backend.copy(b'other')
        self.assertEqual(self.decode(self.incoming(8,struct.pack('<I',1)))[0]['clipboard_payload'],struct.pack('<I',0))
    def test_deadline_and_no_text_grab_never_write(self):
        self.negotiate();self.assertEqual(self.incoming(7,struct.pack('<I',2)),b'')
        self.assertEqual(self.cb.poll(1),b'')
        self.assertEqual(self.cb.handle(dict(port=1,type=7,clipboard_payload=struct.pack('<I',1)),1),b'')
        self.assertEqual(self.backend.writes,[])

if __name__=='__main__':unittest.main()
