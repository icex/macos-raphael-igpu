#!/usr/bin/env python3
"""Opt-in ordinary clipboard only: bounded UTF-8, no payload logging or files.

SPICE vd_agent.h: types4/7/8/9/14, BY_DEMAND bit5, LF bit8, MAX bit10.
No selection or grab-serial capability is advertised: no optional wire prefixes.
"""
from pathlib import Path
import struct
import os
import select
import subprocess
import time

LIMIT=65536
CAPS=(1<<5)|(1<<8)|(1<<10)
HEADER=struct.Struct('<qI')

def text(data):
    if not isinstance(data,bytes) or len(data)>LIMIT or b'\0' in data:raise ValueError('clipboard text limit/type refused')
    try:data.decode('utf-8',errors='strict')
    except UnicodeDecodeError:raise ValueError('invalid clipboard UTF-8') from None
    return data

def packet(kind,payload=b''):
    if len(payload)>LIMIT+4:raise ValueError('clipboard packet limit')
    message=struct.pack('<IIQI',1,kind,0,len(payload))+payload
    return b''.join(struct.pack('<II',1,len(message[i:i+2048]))+message[i:i+2048] for i in range(0,len(message),2048))

def helper_call(arguments,data,timeout=1):
    """Bound stdout during transport, including a hung/misbehaving helper."""
    deadline=time.monotonic()+timeout;output=bytearray();offset=0;reading=True
    process=subprocess.Popen(arguments,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
    try:
        os.set_blocking(process.stdout.fileno(),False);os.set_blocking(process.stdin.fileno(),False)
        while reading or process.poll() is None:
            left=deadline-time.monotonic()
            if left<=0:raise subprocess.TimeoutExpired(arguments,timeout)
            if not process.stdin.closed and offset==len(data):process.stdin.close()
            r,w,_=select.select([process.stdout] if reading else [],[process.stdin] if not process.stdin.closed else [],[],min(.05,left))
            if w:
                try:offset+=os.write(process.stdin.fileno(),data[offset:])
                except BlockingIOError:pass
                except BrokenPipeError:process.stdin.close()
            if r:
                try:chunk=os.read(process.stdout.fileno(),HEADER.size+LIMIT+1-len(output))
                except BlockingIOError:continue
                if not chunk:reading=False
                output.extend(chunk)
                if len(output)>HEADER.size+LIMIT:raise ValueError('pasteboard helper output limit')
        return process.returncode,bytes(output)
    finally:
        if process.poll() is None:process.kill()
        process.wait(timeout=1)
        process.stdin.close();process.stdout.close()

class Pasteboard:
    def __init__(self,helper):self.helper=Path(helper)
    def call(self,operation,expected,data=None):
        code,output=helper_call([str(self.helper),operation,str(expected)],data or b'')
        if code==3:raise BlockingIOError('pasteboard changed')
        if code or not HEADER.size<=len(output)<=HEADER.size+LIMIT:
            raise RuntimeError('pasteboard helper failed')
        count,status=HEADER.unpack_from(output);payload=output[HEADER.size:]
        if count<0 or status not in (0,1,2) or (status!=1 and payload):raise ValueError('pasteboard helper protocol')
        return count,status,text(payload) if status==1 else None
    def read(self,expected):return self.call('read',expected)
    def write(self,expected,data):
        count,status,payload=self.call('write',expected,text(data))
        if status!=0:raise ValueError('pasteboard write protocol')
        return count

class Clipboard:
    def __init__(self,backend,record,clock=time.monotonic):
        self.backend=backend;self.record=record;self.clock=clock
        self.ready=False;self.count=None;self.local=None;self.owned=False
        self.inflight=None;self.want=False;self.generation=0;self.remote_limit=LIMIT
        self.next_poll=0;self.disabled=False
    def disconnect(self):
        # Keep local contents but don't offer old contents to the next client.
        self.ready=False;self.count=None;self.local=None;self.owned=False
        self.inflight=None;self.want=False;self.generation+=1;self.remote_limit=LIMIT;self.disabled=False
    def announce(self,row):
        if row['port']!=1:return
        enabled=bool(row.get('caps') and row['caps'][0]&(1<<5))
        if not enabled:
            self.local=None;self.owned=False;self.want=False;self.generation+=1
        if enabled and not self.ready and self.inflight is not None:self.disabled=True
        self.ready=enabled
    def poll(self,remaining):
        if not self.ready or self.disabled or remaining<2.2:return b''
        now=self.clock()
        if self.inflight and now-self.inflight[2]>5:
            # No request IDs exist in this negotiated protocol. Never associate a
            # late response with a new request after an ambiguous timeout.
            self.disabled=True;self.local=None;self.owned=False;self.want=False
            self.record(dict(event='clipboard-disabled',reason='response-timeout'));return packet(9)
        if now<self.next_poll:return b''
        self.next_poll=now+.5
        try:count,status,data=self.backend.read(-1 if self.count is None else self.count)
        except BlockingIOError:return b''
        if self.count is None:self.count=count;return b''
        if count==self.count:return b''
        self.count=count;self.generation+=1;self.want=False
        self.local=data if status==1 else None
        had=self.owned;self.owned=self.local is not None and len(self.local)<=self.remote_limit
        self.record(dict(event='clipboard-local-change',text_available=self.owned))
        if self.owned:return packet(7,struct.pack('<I',1))
        return packet(9) if had else b''
    def request(self):
        if not self.want or self.inflight is not None:return b''
        self.inflight=(self.generation,self.count,self.clock())
        return packet(8,struct.pack('<I',1))
    def handle(self,row,remaining):
        if row['port']!=1 or not self.ready or self.disabled or remaining<2.2:return b''
        kind=row['type'];payload=row.get('clipboard_payload',b'')
        if row.get('clipboard_oversize'):
            self.record(dict(event='clipboard-refused',reason='text-limit'))
            if self.inflight is not None:
                generation,expected,started=self.inflight;self.inflight=None
                if generation==self.generation:self.want=False
            return self.request()
        if kind==14:
            if len(payload)!=4:raise ValueError('clipboard maximum length')
            value=struct.unpack('<i',payload)[0]
            if value < -1:raise ValueError('clipboard maximum invalid')
            self.remote_limit=LIMIT if value==-1 else min(LIMIT,value-1)
            return b''
        if kind not in (4,7,8,9):return b''
        # Establish changeCount before requesting remote text, without sharing
        # pre-session contents or forcing a clipboard read on disabled profiles.
        if self.count is None:self.count=self.backend.read(-1)[0]
        if kind==7:
            if len(payload)%4 or len(payload)>256:raise ValueError('clipboard grab shape')
            types=struct.unpack('<'+'I'*(len(payload)//4),payload)
            self.generation+=1;self.local=None;self.owned=False;self.want=1 in types
            return self.request()
        if kind==9:
            if payload:raise ValueError('clipboard release shape')
            self.generation+=1;self.want=False
            # Remote release must never erase the user's current clipboard.
            return b''
        if kind==8:
            if len(payload)!=4:raise ValueError('clipboard request shape')
            requested=struct.unpack('<I',payload)[0]
            # Recheck the owner at request time, not only at the last poll.
            count,status,data=self.backend.read(self.count)
            valid=requested==1 and self.owned and count==self.count and self.local is not None and len(self.local)<=self.remote_limit
            return packet(4,struct.pack('<I',1)+self.local) if valid else packet(4,struct.pack('<I',0))
        if len(payload)<4:raise ValueError('clipboard data shape')
        datatype=struct.unpack_from('<I',payload)[0]
        data=payload[4:]
        if datatype not in (0,1) or (datatype==0 and data):raise ValueError('unsupported clipboard data')
        if datatype==1:text(data)
        if self.inflight is None:return b'' # unsolicited data is never applied
        generation,expected,started=self.inflight;self.inflight=None
        if generation==self.generation and self.want:
            self.want=False
            if datatype==1:
                try:self.count=self.backend.write(expected,data)
                except BlockingIOError:pass
                else:self.record(dict(event='clipboard-remote-applied',bytes=len(data)))
        return self.request() # drain stale response before requesting the newest offer
