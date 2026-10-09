#!/usr/bin/env python3
"""Session-bounded SPICE resize and optional text clipboard agent.

Clipboard sharing requires --clipboard-text; the default does not read pasteboard.
Owns no display or capture process."""
import argparse
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import select
import signal
import stat
import struct
import subprocess
import termios
import time

def module(name,file):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(file))
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value

monitors=module('monitors','console-vdagent-monitors.py')
control=module('control','console-display-control.py')
clipboard_module=module('clipboard','console-vdagent-clipboard.py')
DEVICE=monitors.transport.DEVICE
CALLOUT='/dev/cu.com.redhat.spice.0'

class Budget:
    """Refilling rate bound rather than a small session-wide message quota."""
    def __init__(self,capacity,rate,clock=time.monotonic):
        self.capacity=capacity;self.rate=rate;self.clock=clock
        self.available=capacity;self.last=clock()
    def consume(self,amount):
        now=self.clock();self.available=min(self.capacity,self.available+max(0,now-self.last)*self.rate);self.last=now
        if amount>self.available:raise ValueError('agent traffic rate exceeded')
        self.available-=amount

def holder_records(result):
    """One exact-node lsof query; p records require numeric f descendants."""
    if result.stderr or result.returncode not in (0,1):raise RuntimeError('port holder inventory unavailable')
    text=result.stdout
    if not isinstance(text,str) or len(text)>65536:raise ValueError('holder inventory size/type refused')
    if not text:
        if result.returncode!=1:raise RuntimeError('empty successful holder inventory')
        return set()
    if result.returncode!=0:raise RuntimeError('nonempty failed single-node holder inventory')
    if not text.endswith('\n'):raise ValueError('truncated holder inventory')
    owners=set();current=None;descriptors=set()
    for row in text.splitlines():
        if len(row)<2 or row[0] not in ('p','f') or not row[1:].isascii() or not row[1:].isdigit() or len(row)>12:
            raise ValueError('invalid holder inventory field')
        number=int(row[1:])
        if row[0]=='p':
            if number<=0 or number in owners or (current is not None and not descriptors):
                raise ValueError('invalid holder process record')
            current=number;owners.add(number);descriptors=set()
        else:
            if current is None or number in descriptors:raise ValueError('orphan/duplicate holder descriptor')
            descriptors.add(number)
    if current is None or not descriptors:raise ValueError('holder process has no descriptor')
    return owners

def holders(allow_self=False):
    # A combined query can return1 solely because the other alias has no match.
    # Keep exit status and visibility evidence separate for each exact node.
    owners=[]
    for node in (DEVICE,CALLOUT):
        result=subprocess.run(['/usr/sbin/lsof','-nP','-F','pf',node],capture_output=True,text=True,timeout=2)
        owners.append(holder_records(result))
    if allow_self:
        if owners[0]!={os.getpid()} or owners[1]-{os.getpid()}:
            raise RuntimeError('port is shared or own tty holder not visible')
    elif any(owners):raise RuntimeError('agent port already held')

def reply(success,port=1):return monitors.packet(3,struct.pack('<II',2,1 if success else 2),port)

class Handler:
    def __init__(self,apply,record,clock=time.monotonic,*,scale=2,clipboard_caps=0):
        self.clipboard_caps=clipboard_caps
        if type(scale) is not int or scale not in (1,2):raise ValueError("unsupported guest scale")
        self.scale=scale
        self.apply=apply;self.record=record;self.clock=clock
        self.messages=Budget(64,16,clock);self.last_apply=-float('inf')
        self.requests=0;self.applied=0;self.failures=0;self.pending=None
    def refuse(self,row,number,reason):
        self.failures+=1
        self.record(dict(event='mode-refused',request=number,reason=reason,configuration_header=row.get('configuration_header')))
        return reply(False,row['port'])
    def disconnect(self):
        self.messages.consume(1)
        if self.pending:
            row,number=self.pending;self.refuse(row,number,'client disconnected');self.pending=None
    def handle(self,row,remaining):
        self.messages.consume(1)
        if row['type']==6:
            return monitors.packet(6,struct.pack('<II',0,6|self.clipboard_caps),row['port']) if row['request'] else b''
        if row['type']!=2:return b''
        self.requests+=1
        config=row.get('configuration')
        if row['port']!=1 or config is None:
            return self.refuse(row,self.requests,'unsupported monitor request')
        try:control.geometry(config['width'],config['height'],scale=self.scale)
        except ValueError:return self.refuse(row,self.requests,'unsupported geometry')
        if remaining<6:return self.refuse(row,self.requests,'session ending')
        response=b''
        if self.pending:
            previous,number=self.pending;response=self.refuse(previous,number,'superseded')
        self.pending=(row,self.requests)
        return response
    def flush(self,remaining):
        if not self.pending:return b''
        if remaining>=6 and self.clock()-self.last_apply<.25:return b''
        row,number=self.pending;self.pending=None
        if remaining<6:return self.refuse(row,number,'session ending')
        config=row['configuration'];self.last_apply=self.clock();success=False
        try:
            result=self.apply(config['width'],config['height'],min(5,remaining-1))
            success=result.get('passed') is True
            if success and ((result.get('pixel_width'),result.get('pixel_height'))!=(config['width'],config['height']) or
                            (result.get('width'),result.get('height'))!=(config['width']//self.scale,config['height']//self.scale)):
                raise ValueError('holder geometry mismatch')
            error=None if success else 'holder refused'
            self.record(dict(event='mode-result',request=number,configuration=config,result=result))
        except (OSError,ValueError,EOFError) as failure:
            success=False;error=type(failure).__name__
        if not success:return self.refuse(row,number,error)
        self.applied+=1
        return reply(True,row['port'])

def serve(fd,seconds,apply,record,clock=time.monotonic,*,scale=2,clipboard_backend=None):
    clip=clipboard_module.Clipboard(clipboard_backend,record,clock) if clipboard_backend is not None else None
    caps=clipboard_module.CAPS if clip else 0
    deadline=clock()+seconds;parser=monitors.MonitorParser(clipboard_limit=clipboard_module.LIMIT if clip else 0)
    pending=bytearray(monitors.packet(6,struct.pack('<II',1,6|caps)))
    handler=Handler(apply,record,clock,scale=scale,clipboard_caps=caps)
    rx_budget=Budget(17*1024*1024 if clip else 65536,1024*1024 if clip else 16384,clock)
    tx_budget=Budget(262144 if clip else 8192,131072 if clip else 4096,clock)
    backlog=131072 if clip else 8192;clipboard_pending=False
    def clipboard_call(function,*args):
        try:return function(*args)
        except (OSError,RuntimeError,subprocess.TimeoutExpired) as error:
            clip.disabled=True;clip.local=None;clip.owned=False;clip.want=False
            record(dict(event='clipboard-disabled',reason=type(error).__name__))
            return clipboard_module.packet(9) if clip.ready else b''
    rx=tx=0;traffic=False
    while clock()<deadline:
        if clip:
            response=clipboard_call(clip.poll,deadline-clock())
            clipboard_pending=clipboard_pending or bool(response)
            tx_budget.consume(len(response));pending.extend(response)
        response=handler.flush(deadline-clock());tx_budget.consume(len(response));pending.extend(response)
        if len(pending)>backlog:raise ValueError('agent outbound backlog exceeded')
        readable,writable,_=select.select([fd],[fd] if pending else [],[],min(.1,max(0,deadline-clock())))
        if clock()>=deadline:break
        if writable:
            try:sent=os.write(fd,pending)
            except (BlockingIOError,InterruptedError):sent=0
            del pending[:sent];tx+=sent
            if not pending:clipboard_pending=False
        if not readable:continue
        try:data=os.read(fd,4096)
        except (BlockingIOError,InterruptedError):continue
        if not data:
            if traffic:raise EOFError('agent transport closed')
            time.sleep(min(.02,max(0,deadline-clock())));continue
        traffic=True;rx+=len(data);rx_budget.consume(len(data))
        for row in parser.feed(data):
            if row['port']==2 and row['type']==13:
                # Never truncate an already partially written wire frame.
                # Cancel only the not-yet-applied request. Ambiguous partial
                # client assembly refuses reconnect rather than joining clients.
                if clip:
                    if clipboard_pending and pending:
                        raise ValueError('clipboard disconnect with queued bytes; refusing cross-client replay')
                    clip.disconnect()
                handler.disconnect()
                if parser.validator.pending()['per_port_message_bytes']['1']:
                    raise ValueError('client disconnected with incomplete message')
                record(dict(event='client-disconnected'));continue
            if clip and row['type']==6:clip.announce(row)
            if clip and row['type'] in (4,7,8,9,14):
                handler.messages.consume(1)
                response=clipboard_call(clip.handle,row,deadline-clock())
                clipboard_pending=clipboard_pending or bool(response)
            else:response=handler.handle(row,deadline-clock())
            tx_budget.consume(len(response));pending.extend(response)
            if len(pending)>backlog:raise ValueError('agent outbound backlog exceeded')
    return dict(event='finish',reason='session-deadline',received_bytes=rx,transmitted_bytes=tx,
                requests=handler.requests,verified_applications=handler.applied,refusals=handler.failures,
                pending_transmit_bytes=len(pending),pending_parser_bytes=parser.validator.pending())

class StopSession(Exception):pass

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--control-dir',type=Path,required=True)
    parser.add_argument('--seconds',type=int,required=True)
    parser.add_argument('--guest-scale',type=int,choices=(1,2),default=2)
    parser.add_argument('--clipboard-text',action='store_true',help='explicitly share new UTF-8 clipboard text with the connected SPICE client; max64KiB')
    args=parser.parse_args()
    if not 1<=args.seconds<=6000:parser.error('session must be1..6000seconds')
    if os.geteuid()==0 or os.getuid()!=os.geteuid():raise ValueError('ordinary user required')
    directory=args.control_dir
    if not directory.is_absolute() or directory.resolve()!=directory:raise ValueError('unaliased absolute control directory required')
    control.identity(directory,stat.S_ISDIR,0o700)
    lock=os.open(directory/'agent.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW|os.O_CLOEXEC,0o600)
    fd=None;began=time.monotonic()
    def record(row):print(json.dumps(row),flush=True)
    def stop(number,frame):raise StopSession(str(number))
    try:
        info=os.fstat(lock)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid() or stat.S_IMODE(info.st_mode)!=0o600:raise ValueError('agent lock identity refused')
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop);signal.signal(signal.SIGALRM,stop)
        signal.setitimer(signal.ITIMER_REAL,args.seconds)
        holders()
        before=monitors.transport.identity(os.lstat(DEVICE))
        fd=os.open(DEVICE,os.O_RDWR|os.O_NONBLOCK|os.O_NOCTTY|os.O_CLOEXEC|os.O_NOFOLLOW)
        if monitors.transport.identity(os.fstat(fd))!=before or monitors.transport.identity(os.lstat(DEVICE))!=before:raise ValueError('agent device replaced')
        fcntl.ioctl(fd,termios.TIOCEXCL);holders(allow_self=True)
        record(dict(event='start',seconds=args.seconds,euid=os.geteuid(),device_identity=before,guest_scale=args.guest_scale,clipboard_text=args.clipboard_text))
        outcome=serve(fd,max(0,args.seconds-(time.monotonic()-began)-min(1,args.seconds/2)),
                      lambda w,h,timeout:control.request(directory,w,h,timeout,scale=args.guest_scale),record,scale=args.guest_scale,
                      clipboard_backend=clipboard_module.Pasteboard(Path(__file__).with_name('console-clipboard')) if args.clipboard_text else None)
        record(outcome)
    except StopSession as reason:record(dict(event='finish',reason='signal',signal=str(reason)))
    finally:
        if fd is not None:os.close(fd)
        os.close(lock);signal.setitimer(signal.ITIMER_REAL,0)

if __name__=='__main__':main()
