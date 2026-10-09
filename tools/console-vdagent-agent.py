#!/usr/bin/env python3
"""Session-bounded SPICE resize agent. Owns no display or capture process."""
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

def holders(allow_self=False):
    result=subprocess.run(['/usr/sbin/lsof','-nP','-F','p',DEVICE,CALLOUT],capture_output=True,text=True,timeout=2)
    if result.stderr or result.returncode not in (0,1):raise RuntimeError('port holder inventory unavailable')
    lines=result.stdout.splitlines()
    if any(not row.startswith('p') or not row[1:].isdigit() for row in lines):raise ValueError('invalid holder inventory')
    owners={int(row[1:]) for row in lines}
    if allow_self:
        if result.returncode!=0 or owners!={os.getpid()}:raise RuntimeError('port is shared or own holder not visible')
    elif result.returncode!=1 or owners:raise RuntimeError('agent port already held')

def reply(success,port=1):return monitors.packet(3,struct.pack('<II',2,1 if success else 2),port)

class Handler:
    def __init__(self,apply,record,clock=time.monotonic):
        self.apply=apply;self.record=record;self.clock=clock
        self.messages=Budget(64,16,clock);self.last_apply=-float('inf')
        self.requests=0;self.applied=0;self.failures=0
    def handle(self,row,remaining):
        self.messages.consume(1)
        if row['type']==6:
            return monitors.capabilities(0,True) if row['request'] else b''
        if row['type']!=2:return b''
        self.requests+=1;success=False
        config=row.get('configuration')
        if row['port']!=1 or config is None:
            error='unsupported monitor request'
        elif self.clock()-self.last_apply<.25:
            error='rate-limited'
        elif remaining<3:
            error='session ending'
        else:
            self.last_apply=self.clock()
            try:
                control.geometry(config['width'],config['height'])
                result=self.apply(config['width'],config['height'],min(2,remaining-1))
                success=result.get('passed') is True
                if success and (result.get('pixel_width'),result.get('pixel_height'))!=(config['width'],config['height']):
                    raise ValueError('holder geometry mismatch')
                error=None if success else 'holder refused'
                self.record(dict(event='mode-result',request=self.requests,configuration=config,result=result))
            except (OSError,ValueError,EOFError) as failure:
                success=False;error=type(failure).__name__
        self.applied+=int(success);self.failures+=int(not success)
        if not success:self.record(dict(event='mode-refused',request=self.requests,reason=error,configuration_header=row.get('configuration_header')))
        return reply(success,row['port'])

def serve(fd,seconds,apply,record,clock=time.monotonic):
    deadline=clock()+seconds;parser=monitors.MonitorParser();pending=bytearray(monitors.capabilities(1,True))
    handler=Handler(apply,record,clock);rx_budget=Budget(65536,16384,clock);tx_budget=Budget(8192,4096,clock)
    rx=tx=0;traffic=False
    while clock()<deadline:
        readable,writable,_=select.select([fd],[fd] if pending else [],[],min(.1,max(0,deadline-clock())))
        if clock()>=deadline:break
        if writable:
            try:sent=os.write(fd,pending)
            except (BlockingIOError,InterruptedError):sent=0
            del pending[:sent];tx+=sent
        if not readable:continue
        try:data=os.read(fd,4096)
        except (BlockingIOError,InterruptedError):continue
        if not data:
            if traffic:raise EOFError('agent transport closed')
            time.sleep(min(.02,max(0,deadline-clock())));continue
        traffic=True;rx+=len(data);rx_budget.consume(len(data))
        for row in parser.feed(data):
            if row['port']==2 and row['type']==13:
                # Server reports client disconnect; do not deliver old replies
                # to a subsequent client. Keep this exclusive tty owner alive.
                pending.clear();record(dict(event='client-disconnected'));continue
            response=handler.handle(row,deadline-clock());tx_budget.consume(len(response));pending.extend(response)
            if len(pending)>8192:raise ValueError('agent outbound backlog exceeded')
    return dict(event='finish',reason='session-deadline',received_bytes=rx,transmitted_bytes=tx,
                requests=handler.requests,verified_applications=handler.applied,refusals=handler.failures,
                pending_transmit_bytes=len(pending),pending_parser_bytes=parser.validator.pending())

class StopSession(Exception):pass

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--control-dir',type=Path,required=True)
    parser.add_argument('--seconds',type=int,required=True)
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
        record(dict(event='start',seconds=args.seconds,euid=os.geteuid(),device_identity=before))
        outcome=serve(fd,max(0,args.seconds-(time.monotonic()-began)-min(1,args.seconds/2)),
                      lambda w,h,timeout:control.request(directory,w,h,timeout),record)
        record(outcome)
    except StopSession as reason:record(dict(event='finish',reason='signal',signal=str(reason)))
    finally:
        if fd is not None:os.close(fd)
        os.close(lock);signal.setitimer(signal.ITIMER_REAL,0)

if __name__=='__main__':main()
