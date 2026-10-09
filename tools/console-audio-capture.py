#!/usr/bin/env python3
"""Explicit opt-in VM-only Pulse capture. No guest commands/default-route writes.

Run capture only under the hardware owner's coordination. Wait for ready.json,
then run the exact-device guest probe. Analysis is separate from route cleanup.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import time
import wave


def require(value,message):
    if not value:raise RuntimeError(message)


def unique(rows,predicate,label):
    found=[r for r in rows if predicate(r)]
    require(len(found)==1,'ambiguous or missing '+label);return found[0]


def serial(row):return str(row.get('properties',{}).get('object.serial',''))
def stream_id(row):
    return dict(index=row['index'],serial=serial(row),client=str(row['client']),properties={
        k:row['properties'].get(k) for k in ('application.name','application.process.id',
        'application.process.host','application.process.binary','media.name')})


def select_stream(snapshot,identity):
    i=identity['identity'];cid=identity['cid'];run=identity['run_id']
    require(re.fullmatch('[0-9a-f]{64}',cid) and re.fullmatch('[0-9a-f]{32}',run), 'invalid run identity')
    require(i['name']=='rgpu-'+run and i['run_id']==run and type(i['pid']) is int,'invalid process identity')
    def matches(r):
        p=r.get('properties',{})
        return (p.get('application.name')==i['name'] and p.get('application.process.id')==str(i['pid']) and
                p.get('application.process.host')==cid[:12] and p.get('application.process.binary')=='qemu-system-x86_64' and p.get('media.name')=='hda')
    stream=unique(snapshot['inputs'],matches,'VM audio stream')
    require(serial(stream),'missing stream serial')
    client=unique(snapshot['clients'],lambda c:str(c['index'])==str(stream['client']),'Pulse client')
    require(matches(dict(properties=dict(client.get('properties',{}),**{'media.name':'hda'}))), 'Pulse client identity mismatch')
    return stream


class Backend:
    def command(self,args):
        return subprocess.check_output(args,text=True,timeout=2).strip()
    def pulse(self,*args):return self.command(['pactl',*map(str,args)])
    def snapshot(self):
        return dict(inputs=json.loads(self.pulse('-f','json','list','sink-inputs')),
                    sinks=json.loads(self.pulse('-f','json','list','sinks')),
                    clients=json.loads(self.pulse('-f','json','list','clients')),
                    modules=json.loads(self.pulse('-f','json','list','modules')),
                    defaults=[self.pulse('get-default-sink'),self.pulse('get-default-source')])
    def verify_vm(self,identity):
        cid=identity['cid'];i=identity['identity']
        require(isinstance(cid,str) and re.fullmatch('[0-9a-f]{64}',cid) and
                type(i['pid']) is int and i['pid']>1 and type(i['start_ticks']) is int and i['start_ticks']>0,
                'invalid exact container/process identity')
        state=json.loads(self.command(['docker','inspect','--format','{{json .State}}',cid]))
        require(state['Running'] is True and state['StartedAt']==identity['started_at'],'container lifetime changed')
        # Only selected proc facts, never command line/environment/SMC key.
        code="""import json,os,sys
from pathlib import Path
p=int(sys.argv[1]);f=Path('/proc/%d/stat'%p).read_text().rsplit(')',1)[1].split();n=Path('/proc/self/ns/pid').stat();init=Path('/proc/1/stat').read_text().rsplit(')',1)[1].split()
print(json.dumps(dict(pid=p,start_ticks=int(f[19]),state=f[0],binary=Path(os.readlink('/proc/%d/exe'%p)).name,scope=dict(kind='pid-namespace',device=n.st_dev,inode=n.st_ino,init_start_ticks=int(init[19])))))"""
        i=identity['identity'];value=json.loads(self.command(['docker','exec',cid,'python3','-c',code,str(i['pid'])]))
        require(value['pid']==i['pid'] and value['start_ticks']==i['start_ticks'] and value['scope']==identity['scope'] and value['state']!='Z' and value['binary']=='qemu-system-x86_64','QEMU process identity changed')


class Route:
    def __init__(self,backend,identity,path):
        self.backend=backend;self.identity=identity;self.path=path;self.state=None
    def save(self):
        temp=self.path.with_suffix('.tmp')
        with temp.open('w') as stream:
            stream.write(json.dumps(self.state,indent=2)+'\n');stream.flush();os.fsync(stream.fileno())
        temp.replace(self.path)
        fd=os.open(self.path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)
    def stream(self,snapshot):
        stream=select_stream(snapshot,self.identity)
        require(stream_id(stream)==self.state['stream'],'VM audio stream replaced')
        require(stream['volume']==self.state['volume'] and stream['mute']==self.state['mute'],'VM volume/mute changed')
        return stream
    def sink(self,snapshot,original=False):
        expected=self.state['original_sink'] if original else self.state['owned_sink']
        return unique(snapshot['sinks'],lambda s:s['index']==expected['index'] and s['name']==expected['name'] and serial(s)==expected['serial'],'original sink' if original else 'owned sink')
    def verify_owned(self,snapshot):
        module=unique(snapshot['modules'],lambda m:m['index']==self.state['module'],'owned null module')
        require(module['name']=='module-null-sink' and module.get('argument','')==self.state['module_argument'],'owned module replaced')
        return self.sink(snapshot)
    def start(self):
        self.backend.verify_vm(self.identity);snap=self.backend.snapshot();stream=select_stream(snap,self.identity)
        original=unique(snap['sinks'],lambda s:s['index']==stream['sink'],'original sink')
        require(serial(original),'missing original sink serial')
        name='rgpu_audio_'+secrets.token_hex(8)
        require(not any(s['name']==name for s in snap['sinks']),'sink name collision')
        self.state=dict(schema=1,identity=self.identity,stream=stream_id(stream),volume=stream['volume'],mute=stream['mute'],
            original_sink=dict(index=original['index'],name=original['name'],serial=serial(original)),defaults=snap['defaults'],
            name=name,module=None,owned_sink=None,moved=False,restored=False,prior_modules=[m['index'] for m in snap['modules']],create_attempted=True)
        self.save()
        # Record identity immediately after module creation, before stream mutation.
        module=int(self.backend.pulse('load-module','module-null-sink','sink_name='+name,'format=s16le','rate=48000','channels=2','channel_map=front-left,front-right'))
        self.state['module']=module;self.save()
        snap=self.backend.snapshot();m=unique(snap['modules'],lambda r:r['index']==module,'new module')
        require(m['name']=='module-null-sink' and 'sink_name='+name in m.get('argument','').split(),'new module identity mismatch')
        self.state['module_argument']=m['argument'];sink=unique(snap['sinks'],lambda s:s['name']==name,'new null sink')
        require(serial(sink),'missing sink serial')
        self.state['owned_sink']=dict(index=sink['index'],name=name,serial=serial(sink));self.save()
        self.backend.verify_vm(self.identity);self.stream(snap)
        require(not any(r['sink']==sink['index'] for r in snap['inputs']),'new sink is not exclusive')
        self.state['move_attempted']=True;self.save()
        self.backend.pulse('move-sink-input',stream['index'],name)
        self.state['moved']=True;self.save();self.check()
        return name+'.monitor'
    def check(self):
        self.backend.verify_vm(self.identity);snap=self.backend.snapshot();stream=self.stream(snap);sink=self.verify_owned(snap)
        require(stream['sink']==sink['index'],'VM route changed')
        require([r['index'] for r in snap['inputs'] if r['sink']==sink['index']]==[stream['index']],'foreign stream joined monitor')
        require(snap['defaults']==self.state['defaults'],'global defaults changed')
    def restore(self):
        if not self.state or self.state.get('restored'):return
        module=self.state.get('module')
        snap=self.backend.snapshot()
        if module is None:
            matches=[m for m in snap['modules'] if m['name']=='module-null-sink' and
                     ('sink_name='+self.state['name']) in m.get('argument','').split() and
                     m['index'] not in self.state['prior_modules']]
            require(len(matches)<=1,'ambiguous owned module after failed create')
            if not matches:return
            module=matches[0]['index'];self.state['module']=module
        if not self.state.get('owned_sink') or not self.state.get('module_argument'):
            owned=unique(snap['modules'],lambda m:m['index']==module,'created module')
            require(owned['name']=='module-null-sink' and ('sink_name='+self.state['name']) in owned.get('argument','').split() and module not in self.state['prior_modules'],'created module ownership mismatch')
            sink=unique(snap['sinks'],lambda r:r['name']==self.state['name'] and str(r.get('owner_module'))==str(module),'created sink')
            require(serial(sink),'created sink serial missing')
            self.state['module_argument']=owned['argument']
            self.state['owned_sink']=dict(index=sink['index'],name=sink['name'],serial=serial(sink));self.save()
        sink=self.verify_owned(snap)
        occupants=[r for r in snap['inputs'] if r['sink']==sink['index']]
        require(all(stream_id(r)==self.state['stream'] for r in occupants),'refuse to move foreign audio')
        if occupants:
            self.backend.verify_vm(self.identity);stream=self.stream(snap);original=self.sink(snap,True)
            self.backend.pulse('move-sink-input',stream['index'],original['name'])
        snap=self.backend.snapshot();self.verify_owned(snap)
        require(not any(r['sink']==sink['index'] for r in snap['inputs']),'owned sink still occupied')
        # A vanished VM stream requires no recreation or move of any replacement.
        remaining=[r for r in snap['inputs'] if r['index']==self.state['stream']['index']]
        if remaining:
            stream=self.stream(snap);require(stream['sink']==self.state['original_sink']['index'],'original route not restored')
        require(snap['defaults']==self.state['defaults'],'global defaults changed; no default writes authorized')
        self.backend.pulse('unload-module',module)
        final=self.backend.snapshot()
        require(not any(m['index']==module for m in final['modules']),'owned module remains')
        require(final['defaults']==self.state['defaults'],'defaults changed during module cleanup')
        self.state['restored']=True;self.save()


def analyze(path):
    import numpy as np
    with wave.open(str(path),'rb') as w:
        require(w.getnchannels()==2 and w.getsampwidth()==2,'need stereo16-bit WAV');rate=w.getframerate()
        require(32000<=rate<=96000 and w.getnframes()<=25*rate,'unbounded capture format/duration')
        x=np.frombuffer(w.readframes(w.getnframes()),dtype='<i2').reshape(-1,2)/32768
    require(len(x)>rate*6 and np.max(np.abs(x))<.95,'short or clipped audio')
    # Detect first tone, then qualify interiors of each phase; no latency claim.
    energy=np.max(np.abs(x),axis=1);hits=np.flatnonzero(energy>.002)
    require(len(hits)>0,'no signal');onset=hits[0]/rate;start=onset-1
    require(start>=-.1,'missing initial silence')
    evidence=[]
    for label,lo,hi,wanted in [('left',1.15,1.85,[997,None]),('right',2.65,3.35,[None,1499]),('both',4.15,4.85,[997,1499])]:
        block=x[int((start+lo)*rate):int((start+hi)*rate)];require(len(block)>rate*.6,'missing tone phase')
        rms=np.sqrt(np.mean(block*block,axis=0));peaks=[]
        for channel,hz in enumerate(wanted):
            if hz is None:require(rms[channel]<.0002,'channel leakage')
            else:
                spectrum=np.abs(np.fft.rfft(block[:,channel]*np.hanning(len(block))))
                peak=float(np.fft.rfftfreq(len(block),1/rate)[np.argmax(spectrum)])
                require(abs(peak-hz)<5 and .004<rms[channel]<.04,'wrong tone frequency or level');peaks.append(peak)
        evidence.append(dict(phase=label,rms=rms.tolist(),peaks=peaks))
    for lo,hi in [(.2,.8),(2.15,2.35),(3.65,3.85),(5.2,5.8)]:
        block=x[max(0,int((start+lo)*rate)):int((start+hi)*rate)]
        require(len(block)>rate*(hi-lo)-3 and float(np.sqrt(np.mean(block*block)))<.0002,'silence check failed')
    return dict(passed=True,rate=rate,phases=evidence,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),scope='VM USB/QEMU/Pulse sample delivery, not endpoint audibility')


def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['capture','restore','analyze']);p.add_argument('--running',type=Path);p.add_argument('--output',type=Path,required=True);p.add_argument('--seconds',type=float,default=12);args=p.parse_args()
    if args.action=='analyze':print(json.dumps(analyze(args.output)));return
    backend=Backend()
    if args.action=='restore':
        state=json.loads((args.output/'route.json').read_text());route=Route(backend,state['identity'],args.output/'route.json');route.state=state;route.restore();return
    require(args.running and 8<=args.seconds<=20,'running receipt and8..20 seconds required')
    identity=json.loads(args.running.read_text());args.output.mkdir(mode=0o700,parents=True,exist_ok=False)
    route=Route(backend,identity,args.output/'route.json');recorder=None
    def expire(signum,frame):raise TimeoutError('audio capture wall deadline')
    signal.signal(signal.SIGALRM,expire);signal.signal(signal.SIGTERM,expire);signal.signal(signal.SIGINT,expire);signal.alarm(40)
    try:
        monitor=route.start();raw=args.output/'capture.pcm'
        with raw.open('xb') as stream,(args.output/'recorder.stderr').open('xb') as errors:
            recorder=subprocess.Popen(['parec','--raw','--format=s16le','--rate=48000','--channels=2','--channel-map=front-left,front-right','--device='+monitor,'--monitor-stream='+str(route.state['stream']['index']),'--client-name='+route.state['name'],'--stream-name='+route.state['name']],stdout=stream,stderr=errors)
            until=time.monotonic()+args.seconds
            # Wait for actual samples before telling the caller to start tone.
            ready_until=min(until,time.monotonic()+3)
            while raw.stat().st_size<4800:
                require(recorder.poll() is None and time.monotonic()<ready_until,'monitor recorder not ready');time.sleep(.05)
            route.check();(args.output/'ready.json').write_text(json.dumps(dict(ready=True,monitor=monitor,run_id=identity['run_id'],seconds=args.seconds)))
            while time.monotonic()<until:
                require(recorder.poll() is None,'recorder exited early');route.check();time.sleep(.2)
    finally:
        signal.alarm(15) # Cleanup is bounded too; retained route.json supports recovery.
        if recorder and recorder.poll() is None:
            recorder.terminate()
            try:recorder.wait(timeout=2)
            except subprocess.TimeoutExpired:recorder.kill();recorder.wait(timeout=2)
        route.restore()
        signal.alarm(0)
    with wave.open(str(args.output/'capture.wav'),'wb') as w:
        w.setnchannels(2);w.setsampwidth(2);w.setframerate(48000);w.writeframes(raw.read_bytes())
    print(json.dumps(dict(restored=route.state['restored'],capture=str(args.output/'capture.wav'))))
if __name__=='__main__':main()
