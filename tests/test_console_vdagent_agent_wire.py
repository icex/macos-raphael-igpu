"""Real socketpair framing checks; not SPICE-server routing qualification."""
import importlib.util
import inspect
import os
from pathlib import Path
import select
import socket
import struct
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('wire_agent',ROOT/'tools/console-vdagent-agent.py')
agent=importlib.util.module_from_spec(spec);spec.loader.exec_module(agent)


def monitor(width):
    return agent.monitors.packet(2,struct.pack('<IIIIIii',1,0,1440,width,32,0,0))


class AgentWireTests(unittest.TestCase):
    def exercise(self,serve=None,partial_incoming=False):
        """Advance only wait time; every read/write still uses real socket bytes."""
        local,peer=socket.socketpair()
        local.setblocking(False);peer.setblocking(False)
        clock=[0.0];waits=[0];writes=[];wire=bytearray();calls=[];records=[]
        actual_write=os.write;actual_select=select.select
        disconnect=agent.monitors.packet(13,b'',port=2)
        def verified(width,height,timeout):
            calls.append((width,height,clock[0]))
            return dict(passed=True,pixel_width=width,pixel_height=height,display=123)
        def bounded_wait(readable,writable,exceptional,timeout):
            waits[0]+=1
            if waits[0]>600:raise AssertionError('unbounded serve loop')
            clock[0]+=.01
            if waits[0]==2:
                # Exactly one5-byte real write has completed. An output frame
                # is in flight when the disconnect reaches the agent.
                self.assertEqual(writes,[5])
                if partial_incoming:
                    message=agent.monitors.transport.MESSAGE.pack(1,2,0,28)+b'\x01\0\0\0'
                    fragment=agent.monitors.transport.CHUNK.pack(1,len(message))+message
                    peer.sendall(fragment+disconnect)
                else:peer.sendall(disconnect)
            elif waits[0]==3 and not partial_incoming:
                peer.sendall(agent.monitors.capabilities(1,True)+monitor(2560))
            elif waits[0]==4 and not partial_incoming:
                # End the drag with a newer request. No further input follows;
                # the final target must be flushed by the timer path itself.
                peer.sendall(monitor(2600)+monitor(2800))
            return actual_select(readable,writable,exceptional,0)
        def short_write(fd,data):
            self.assertEqual(fd,local.fileno())
            sent=actual_write(fd,data[:5]);writes.append(sent)
            while True:
                try:part=peer.recv(4096)
                except BlockingIOError:break
                if not part:break
                wire.extend(part)
            return sent
        try:
            with patch.object(agent.select,'select',side_effect=bounded_wait),patch.object(agent.os,'write',side_effect=short_write):
                if partial_incoming:
                    with self.assertRaisesRegex(ValueError,'disconnected with incomplete message'):
                        (serve or agent.serve)(local.fileno(),5,verified,records.append,clock=lambda:clock[0])
                    self.assertEqual(calls,[])
                    self.assertFalse(any(r.get('event')=='mode-result' for r in records))
                    return None
                result=(serve or agent.serve)(local.fileno(),5,verified,records.append,clock=lambda:clock[0])
            return bytes(wire),calls,records,result,writes
        finally:
            local.close();peer.close()

    def assert_complete_exchange(self,evidence):
        wire,calls,records,result,writes=evidence
        parser=agent.monitors.transport.Parser()
        rows=parser.feed(wire)
        self.assertEqual(parser.pending(),dict(wire_bytes=0,per_port_message_bytes={'1':0,'2':0}))
        self.assertEqual([row['type'] for row in rows],[6,6,3,3,3])
        self.assertEqual([row['request'] for row in rows[:2]],[1,0])
        self.assertEqual([row['caps'] for row in rows[:2]],[[6],[6]])
        # Parse the actual reply payloads, not just high-level handler counters.
        offset=0;replies=[]
        while offset<len(wire):
            port,size=agent.monitors.transport.CHUNK.unpack_from(wire,offset)
            protocol,kind,opaque,length=agent.monitors.transport.MESSAGE.unpack_from(wire,offset+8)
            self.assertEqual((port,protocol,opaque),(1,1,0))
            self.assertEqual(size,20+length)
            if kind==3:replies.append(struct.unpack_from('<II',wire,offset+28))
            offset+=8+size
        self.assertEqual(replies,[(2,1),(2,2),(2,1)])
        self.assertEqual([row[:2] for row in calls],[(2560,1440),(2800,1440)])
        self.assertGreaterEqual(calls[1][2]-calls[0][2],.25)
        self.assertEqual(sum(r.get('event')=='client-disconnected' for r in records),1)
        self.assertEqual(result['verified_applications'],2)
        self.assertEqual(result['pending_transmit_bytes'],0)
        self.assertEqual(result['pending_parser_bytes'],dict(wire_bytes=0,per_port_message_bytes={'1':0,'2':0}))
        self.assertTrue(writes and max(writes)<=5)

    def test_partial_write_survives_disconnect_and_new_client_exchange(self):
        self.assert_complete_exchange(self.exercise())

    def test_partial_old_client_message_refuses_reconnect(self):
        self.exercise(partial_incoming=True)

    def test_negative_control_discarding_pending_wire_is_detected(self):
        # Reintroduce only the old disconnect bug in an isolated function;
        # repository code stays unchanged. The same wire oracle must reject it.
        source=inspect.getsource(agent.serve)
        needle='                handler.disconnect()'
        self.assertEqual(source.count(needle),1)
        namespace=dict(vars(agent))
        exec(source.replace(needle,'                pending.clear();handler.disconnect()'),namespace)
        evidence=self.exercise(namespace['serve'])
        with self.assertRaises((AssertionError,ValueError,struct.error)):
            self.assert_complete_exchange(evidence)


if __name__=='__main__':unittest.main()
