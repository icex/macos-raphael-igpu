#!/usr/bin/env python3
"""Bounded diagnostic agent: default records only; applying requires explicit flag.

Wire ABI: spice-protocol/spice/vd_agent.h (VDAgentMonitorsConfig,
VDAgentMonConfig, VDAgentReply, capability bits1/2); local reviewed header SHA256
9b23ba83958e6117bec7a0c8b6b4dc946dded8cdf9a23316ca35636442bce542.
Primary definitions: https://gitlab.freedesktop.org/spice/spice-protocol/-/blob/master/spice/vd_agent.h
Prior-owner inventory and qualified tty exclusivity are external prerequisites.
No endpoint provenance or consent is inferred from successfully opening a path.
"""
import argparse
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import select
import signal
import struct
import subprocess
import termios
import time

spec=importlib.util.spec_from_file_location('transport',Path(__file__).with_name('console-vdagent-handshake.py'))
transport=importlib.util.module_from_spec(spec);spec.loader.exec_module(transport)


def packet(kind,payload,port=1):
    message=transport.MESSAGE.pack(1,kind,0,len(payload))+payload
    return transport.CHUNK.pack(port,len(message))+message


def capabilities(request,enabled):
    # vd_agent.h: MONITORS_CONFIG bit1, REPLY bit2. No POSITION/clipboard/mouse.
    return packet(6,struct.pack('<II',request,6 if enabled else 0))


def configuration_header(payload):
    """Bounded numeric metadata, including malformed/unsupported requests."""
    result=dict(payload_bytes=len(payload))
    if len(payload)>=8:
        result.update(zip(('count','flags'),struct.unpack_from('<II',payload)))
    if len(payload)>=28:
        result.update(zip(('height','width','depth','x','y'),struct.unpack_from('<IIIii',payload,8)))
    return result


def configuration(payload):
    result=configuration_header(payload)
    if len(payload)<8:raise ValueError('missing monitor header')
    count,flags=result['count'],result['flags']
    if count!=1 or flags & ~3:raise ValueError('unsupported monitor count/flags')
    if len(payload)!=(32 if flags & 2 else 28):raise ValueError('one-monitor exact payload required')
    if result['depth']!=32 or result['x']!=0 or result['y']!=0:raise ValueError('unsupported depth/layout')
    if not 320<=result['width']<=3840 or not 200<=result['height']<=2160:raise ValueError('unsupported physical geometry')
    if flags & 2:
        height_mm,width_mm=struct.unpack_from('<HH',payload,28)
        result.update(height_mm=height_mm,width_mm=width_mm)
    result['physical_mm_scope']='advisory hints retained but ignored; no DPI change'
    return result


class MonitorParser:
    """Reuse strict wire validator, then extract ONLY validated monitor payloads.

    The second bounded assembly preserves the zero-feature parser's deliberate
    no-feature-payload API. Unknown payload bytes never leave this class.
    """
    def __init__(self):
        self.validator=transport.Parser();self.wire=bytearray();self.ports={1:bytearray(),2:bytearray()}
    def feed(self,data):
        validated=self.validator.feed(data);self.wire.extend(data);rows=[]
        while len(self.wire)>=8:
            port,size=transport.CHUNK.unpack_from(self.wire)
            if len(self.wire)<8+size:break
            body=self.ports[port];body.extend(self.wire[8:8+size]);del self.wire[:8+size]
            while len(body)>=20:
                protocol,kind,opaque,length=transport.MESSAGE.unpack_from(body)
                if len(body)<20+length:break
                row=validated[len(rows)]
                if kind==2:
                    row['configuration_header']=configuration_header(body[20:20+length])
                    try:row.update(configuration=configuration(body[20:20+length]))
                    except ValueError as error:row.update(configuration_error=str(error))
                rows.append(row);del body[:20+length]
        if len(rows)!=len(validated):raise ValueError('parser assembly disagreement')
        return rows


def apply_mode(helper,config,timeout):
    run=subprocess.run([str(helper),'--set',str(config['width']),str(config['height'])],
                       capture_output=True,text=True,timeout=min(5,timeout))
    if len(run.stdout)>16384 or len(run.stderr)>16384:raise ValueError('helper output limit')
    value=json.loads(run.stdout)
    actual=value.get('actual',{})
    passed=run.returncode==0 and value.get('passed') is True and (actual.get('pixel_width'),actual.get('pixel_height'))==(config['width'],config['height']) and actual.get('origin_x')==0 and actual.get('origin_y')==0
    return dict(passed=passed,exit=run.returncode,result=value)


def serve(fd,seconds,enabled,apply,helper,record,clock=time.monotonic):
    start=clock();deadline=start+seconds;pending=bytearray(capabilities(1,enabled));parser=MonitorParser()
    rx=tx=responses=requests=0;traffic=False;last_apply=-1.;applied=0
    while clock()<deadline:
        try:r,w,_=select.select([fd],[fd] if pending else [],[],min(.1,max(0,deadline-clock())))
        except InterruptedError:continue
        # A delayed select wakeup must not start new I/O or a mode application.
        if clock()>=deadline:break
        if w:
            try:n=os.write(fd,pending)
            except (BlockingIOError,InterruptedError):n=0
            del pending[:n];tx+=n
        if r:
            try:data=os.read(fd,min(4096,65536-rx+1))
            except (BlockingIOError,InterruptedError):continue
            if not data:
                if traffic:raise EOFError('agent transport closed')
                time.sleep(min(.02,max(0,deadline-clock())));continue
            traffic=True;rx+=len(data)
            if rx>65536:raise ValueError('receive byte limit')
            for row in parser.feed(data):
                if row['type']==6 and row['request']:
                    responses+=1
                    if responses>16:raise ValueError('capability response limit')
                    pending.extend(capabilities(0,enabled))
                if row['type']==2:
                    requests+=1
                    if requests>64:raise ValueError('monitor request limit')
                    success=False
                    if enabled and apply and row['port']==1 and 'configuration' in row:
                        if clock()-last_apply<.25:
                            row['apply_error']='rate-limited'
                        elif deadline-clock()<5:
                            row['apply_error']='insufficient bounded helper time'
                        else:
                            last_apply=clock()
                            try:
                                row['application']=apply_mode(helper,row['configuration'],deadline-clock())
                                success=row['application']['passed'];applied+=int(success)
                            except (ValueError,subprocess.TimeoutExpired) as error:row['apply_error']=type(error).__name__
                    if enabled:
                        # VD_AGENT_REPLY: original type2, SUCCESS1 or ERROR2.
                        pending.extend(packet(3,struct.pack('<II',2,1 if success else 2),row['port']))
                    row['reply_success']=success if enabled else None
                record(dict(event='message',elapsed=clock()-start,**row))
                if tx+len(pending)>4096:raise ValueError('transmit byte limit')
    return dict(event='finish',reason='bounded-deadline',received_bytes=rx,transmitted_bytes=tx,
                pending_transmit_bytes=len(pending),requests=requests,verified_applications=applied,
                pending_parser_bytes=parser.validator.pending(),scope='existing-mode diagnostic; physical-mm hints ignored, no DPI changes, arbitrary resolution creation or full desktop qualification')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--seconds',type=int,default=30);mode=p.add_mutually_exclusive_group()
    mode.add_argument('--observe-monitors',action='store_true',help='advertise monitor handling but always reply ERROR; no mode change')
    mode.add_argument('--apply-existing',type=Path,metavar='HELPER',help='explicit local compiled mode helper')
    a=p.parse_args()
    if not 1<=a.seconds<=60:p.error('seconds must be1..60')
    if os.geteuid()==0 or os.getuid()!=os.geteuid():raise ValueError('ordinary nonroot uid required')
    helper=a.apply_existing.resolve(strict=True) if a.apply_existing else None
    if helper and (not helper.is_file() or not os.access(helper,os.X_OK)):raise ValueError('helper not executable file')
    def expired(sig,frame):raise TimeoutError('whole-agent deadline')
    cleanup_margin=min(1.,a.seconds/2)
    began=time.monotonic()
    signal.signal(signal.SIGALRM,expired);signal.setitimer(signal.ITIMER_REAL,a.seconds)
    before=transport.identity(os.lstat(transport.DEVICE))
    fd=os.open(transport.DEVICE,os.O_RDWR|os.O_NONBLOCK|os.O_NOCTTY|os.O_CLOEXEC|os.O_NOFOLLOW)
    def record(row):print(json.dumps(row),flush=True)
    try:
        if transport.identity(os.fstat(fd))!=before or transport.identity(os.lstat(transport.DEVICE))!=before:raise ValueError('device identity changed')
        fcntl.ioctl(fd,termios.TIOCEXCL)
        record(dict(event='start',seconds=a.seconds,euid=os.geteuid(),device_identity=before,apply=bool(helper),observe=a.observe_monitors))
        outcome=serve(fd,max(0,a.seconds-(time.monotonic()-began)-cleanup_margin),bool(helper or a.observe_monitors),bool(helper),helper,record)
        if transport.identity(os.fstat(fd))!=before or transport.identity(os.lstat(transport.DEVICE))!=before:raise ValueError('final device identity changed')
    finally:os.close(fd)
    outcome.update(cleanup_margin_seconds=cleanup_margin,total_elapsed_seconds=time.monotonic()-began)
    record(outcome)
    signal.setitimer(signal.ITIMER_REAL,0)

if __name__=='__main__':
    try:main()
    except Exception as error:
        print(json.dumps(dict(event='error',type=type(error).__name__,errno=getattr(error,'errno',None),detail=str(error) if isinstance(error,(ValueError,EOFError,TimeoutError)) else 'system operation failed')),flush=True)
        raise SystemExit(2)
