import importlib.util
from pathlib import Path
import socket
import struct
import threading
import unittest

spec=importlib.util.spec_from_file_location('handshake',Path(__file__).resolve().parents[1]/'tools/console-vdagent-handshake.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def chunk(port,data):return m.CHUNK.pack(port,len(data))+data

def message(kind,payload):return m.MESSAGE.pack(1,kind,0,len(payload))+payload

class HandshakeTests(unittest.TestCase):
    def test_byte_fragmentation_and_interleaved_ports(self):
        a=message(6,struct.pack('<II',0,123));b=message(6,struct.pack('<II',1,456))
        wire=chunk(1,a[:7])+chunk(2,b[:11])+chunk(1,a[7:])+chunk(2,b[11:])
        p=m.Parser();rows=[]
        for byte in wire:rows.extend(p.feed(bytes([byte])))
        self.assertEqual([(x['port'],x['caps']) for x in rows],[(1,[123]),(2,[456])])
    def test_oversize_and_bad_port_refused_before_body(self):
        for head in [m.CHUNK.pack(1,2049),m.CHUNK.pack(3,20),m.CHUNK.pack(1,0)]:
            with self.assertRaises(ValueError):m.Parser().feed(head)
    def test_oversize_message_and_cross_boundary_refused(self):
        for data in [m.MESSAGE.pack(1,6,0,4097),message(6,struct.pack('<I',0))+b'extra']:
            with self.assertRaises(ValueError):m.Parser().feed(chunk(1,data))
    def test_malformed_capabilities_refused(self):
        for payload in [b'',b'12345',struct.pack('<I',2)]:
            with self.assertRaises(ValueError):m.Parser().feed(chunk(1,message(6,payload)))
    def test_unknown_payload_not_exposed(self):
        rows=m.Parser().feed(chunk(1,message(4,b'private clipboard text')))
        self.assertEqual(rows,[{'port':1,'type':4,'size':22}])
    def test_socketpair_request_response_zero_features(self):
        a,b=socket.socketpair();a.setblocking(False);b.settimeout(2);errors=[]
        def peer():
            try:
                first=b''
                while len(first)<36:first+=b.recv(36-len(first))
                self.assertEqual(first,m.announcement(1))
                data=chunk(1,message(6,struct.pack('<II',1,0x1234)))
                for pos in range(0,len(data),3):b.sendall(data[pos:pos+3])
                reply=b''
                while len(reply)<36:reply+=b.recv(36-len(reply))
                self.assertEqual(reply,m.announcement(0))
            except BaseException as e:errors.append(e)
        t=threading.Thread(target=peer);t.start()
        try:
            result=m.exchange(a.fileno(),seconds=2)
            self.assertTrue(result['passed']);self.assertEqual(result['transmitted_bytes'],72)
            self.assertEqual(result['arrivals'][0]['caps'],[0x1234]);self.assertEqual(result['responses'],1)
        finally:t.join(3);a.close();b.close()
        self.assertFalse(t.is_alive());self.assertEqual(errors,[])
    def test_response_flood_refused(self):
        a,b=socket.socketpair();a.setblocking(False)
        # Port2 announcements cannot qualify the required client response.
        b.sendall(m.announcement(1,2)*5)
        try:
            with self.assertRaisesRegex(ValueError,'response limit'):m.exchange(a.fileno(),seconds=.2)
        finally:a.close();b.close()
    def test_initial_zero_is_retried_but_later_eof_is_terminal(self):
        from unittest.mock import patch
        packet=m.announcement(0)
        with patch.object(m.select,'select',return_value=([99],[99],[])), \
             patch.object(m.os,'write',side_effect=lambda fd,data:len(data)), \
             patch.object(m.os,'read',side_effect=[b'',packet]):
            result=m.exchange(99,seconds=.2)
            self.assertEqual(result['initial_zero_reads'],1)
        with patch.object(m.select,'select',return_value=([99],[99],[])), \
             patch.object(m.os,'write',side_effect=lambda fd,data:len(data)), \
             patch.object(m.os,'read',side_effect=[packet[:3],b'']):
            with self.assertRaises(EOFError):m.exchange(99,seconds=.2)
    def test_short_writes_complete_before_success(self):
        from unittest.mock import patch
        writes=[]
        def write(fd,data):
            writes.extend(data[:3]);return min(3,len(data))
        def read(fd,size):
            if len(writes)<36:raise BlockingIOError()
            return m.announcement(0)
        with patch.object(m.select,'select',return_value=([99],[99],[])), \
             patch.object(m.os,'write',side_effect=write),patch.object(m.os,'read',side_effect=read):
            result=m.exchange(99,seconds=.2)
        self.assertEqual(bytes(writes),m.announcement(1));self.assertTrue(result['passed'])
    def test_silent_peer_has_bounded_timeout(self):
        a,b=socket.socketpair();a.setblocking(False)
        try:
            with self.assertRaises(TimeoutError):m.exchange(a.fileno(),seconds=.02)
        finally:a.close();b.close()

if __name__=='__main__':unittest.main()
