#!/usr/bin/env python3
"""Software-only Bochs/SPICE cadence control; no OS, KVM, GPU or network.

A single offscreen SpiceDisplay owns the sole client connection. Qtest writes
are producer transactions, not guest GPU frames. Raw samples and acknowledgements
are retained. --split deliberately exposes mismatched duplicate tokens.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import signal
import threading
import time


def load(name, filename):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(filename))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def band(token,nonce,sequence,second=None):
    # Full-width 96-row band starts at framebuffer y64. Two bordered tokens.
    width=640;raw=bytearray(width*96*4)
    for left,seq in [(16,sequence),(176,sequence if second is None else second)]:
        packet=token.packet(nonce,seq)
        for row in range(12):
            for col in range(18):
                if row in (0,11) or col in (0,17):pixel=b'\xff\x00\xff\x00'
                else:
                    bit=(row-1)*16+col-1
                    value=255 if (packet[bit//8]>>(7-bit%8))&1 else 0
                    pixel=bytes((value,value,value,0))
                line=pixel*8
                for y in range(row*8,row*8+8):
                    off=(y*width+left+col*8)*4;raw[off:off+32]=line
    return raw


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--qemu',type=Path,required=True);p.add_argument('--bios-dir',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--seconds',type=int,default=15)
    p.add_argument('--rate',type=int,choices=(60,));p.add_argument('--split',action='store_true')
    args=p.parse_args()
    if not 1<=args.seconds<=30:p.error('seconds must be 1..30')
    args.output.mkdir(parents=True,exist_ok=False)
    token=load('token','console-token.py');smoke=load('smoke','qemu-console-smoke.py')
    nonce='0344034403440344';root=args.output.resolve()
    command=[str(args.qemu.resolve()),'-L',str(args.bios_dir.resolve()),'-machine','q35,accel=tcg',
             '-nodefaults','-S','-m','128M','-vga','none','-display','none','-nic','none',
             '-device','bochs-display,id=console,addr=02.0,vgamem=64M',
             '-qtest',f'unix:{root}/qt,server=on,wait=off','-qtest-log','/dev/null',
             '-qmp',f'unix:{root}/qm,server=on,wait=off',
             '-spice',f'unix=on,addr={root}/spice,disable-ticketing=on,image-compression=off,gl=off'+
             (',max-refresh-rate=60' if args.rate else '')]
    (root/'argv.json').write_text(json.dumps(command,indent=2)+'\n')
    rom=bytearray(b'\xff'*65536);rom[0xfff0:0xfff4]=b'\xfa\xf4\xeb\xfd'
    (root/'idle-rom.bin').write_bytes(rom);command += ['-bios',str(root/'idle-rom.bin')]
    (root/'argv.json').write_text(json.dumps(command,indent=2)+'\n')
    log=(root/'qemu.log').open('w');process=subprocess.Popen(command,stdout=log,stderr=log)
    channels=[];worker=None;stop=threading.Event();producer_error=[];stats={}
    def expired(signum,frame):raise TimeoutError('bounded smoke deadline elapsed')
    signal.signal(signal.SIGALRM,expired);signal.alarm(args.seconds+30)
    try:
        qt=smoke.Channel(root/'qt',process);channels.append(qt)
        qm=smoke.Channel(root/'qm',process);channels.append(qm)
        assert 'QMP' in json.loads(qm.file.readline())
        def qmp(name):
            qm.file.write(json.dumps({'execute':name}).encode()+b'\n')
            while True:
                reply=json.loads(qm.file.readline())
                if 'error' in reply:raise RuntimeError(reply['error'])
                if 'return' in reply:return reply['return']
        def test(text):
            qt.socket.sendall(text.encode()+b"\n")
            reply=qt.file.readline().decode().strip()
            if not reply.startswith('OK'):raise RuntimeError(reply)
            return reply
        def pci(off,value):test(f'outl 0xcf8 {0x80001000+off:#x}');test(f'outl 0xcfc {value:#x}')
        qmp('qmp_capabilities');qmp('cont');qmp('stop');pci(0x10,0xe0000000);pci(0x18,0xf0000000);pci(4,2)
        for i,v in [(4,0),(1,640),(2,480),(3,32),(6,640),(8,0),(9,0)]:test(f'writew {0xf0000500+i*2:#x} {v:#x}')
        def write(raw):test(f'write {0xe0000000+64*640*4:#x} {len(raw):#x} 0x{raw.hex()}')
        write(band(token,nonce,0));test('writew 0xf0000508 0x41')
        import gi
        gi.require_version('Gtk','3.0');gi.require_version('SpiceClientGtk','3.0');gi.require_version('SpiceClientGLib','2.0')
        from gi.repository import Gtk,GLib,GObject,SpiceClientGtk,SpiceClientGLib
        if not Gtk.init_check()[0]:raise RuntimeError('GTK backend unavailable')
        session=SpiceClientGLib.Session();session.set_property('unix-path',str(root/'spice'))
        display=SpiceClientGtk.Display.new(session,0)
        window=Gtk.OffscreenWindow();window.add(display);window.show_all()
        events=(root/'display-events.jsonl').open('w')
        counts={'mark':0,'invalidate':0}
        def event(kind,*values):
            counts[kind]+=1
            events.write(json.dumps(dict(time=time.monotonic(),event=kind,values=values))+'\n')
        def channel_new(session,channel):
            if isinstance(channel,SpiceClientGLib.DisplayChannel):
                GObject.Object.connect(channel,'display-mark',lambda channel,mark:event('mark',mark))
                GObject.Object.connect(channel,'display-invalidate',lambda channel,x,y,w,h:event('invalidate',x,y,w,h))
        GObject.Object.connect(session,'channel-new',channel_new)
        session.connect()
        stream=(root/'samples.jsonl').open('w');producer=(root/'producer.jsonl').open('w')
        began=time.monotonic();started=None;tracker=token.SequenceTracker();unique=invalid=valid=0;last=None
        def produce():
            try:
                start=time.monotonic();sequence=0
                while not stop.is_set() and time.monotonic()-start<args.seconds:
                    sequence+=1;t0=time.monotonic()
                    if args.split:
                        write(band(token,nonce,sequence,sequence-1));stop.wait(.020)
                    write(band(token,nonce,sequence));t1=time.monotonic()
                    producer.write(json.dumps(dict(sequence=sequence,start=t0,ack=t1,split=args.split))+'\n');producer.flush()
                    stop.wait(max(0,start+sequence/60-time.monotonic()))
            except Exception as error:producer_error.append(repr(error));stop.set()
        def poll():
            nonlocal started,worker,unique,invalid,valid,last
            now=time.monotonic();sample={'time':now}
            if started is not None and now-started>=args.seconds:
                Gtk.main_quit();return False
            if now-began>args.seconds+15 or producer_error:
                Gtk.main_quit();return False
            try:
                pix=display.get_pixbuf()
                if pix is None:raise ValueError('no-pixbuf')
                if not (root/'first.png').exists():pix.savev(str(root/'first.png'),'png',[],[])
                sample.update(width=pix.get_width(),height=pix.get_height(),channels=pix.get_n_channels())
                sequence=token.decode(pix.get_pixels(),pix.get_width(),pix.get_height(),pix.get_rowstride(),pix.get_n_channels(),nonce)
                result=tracker.observe(sequence)
                if started is None:
                    started=now;worker=threading.Thread(target=produce);worker.start()
                valid+=1;unique+=int(result['unique']);last=sequence
                sample.update(valid=True,sequence=sequence,**result)
            except (ValueError,RuntimeError) as error:
                if started is not None:invalid+=1
                sample.update(valid=False,error=str(error))
            sample['duration']=time.monotonic()-now
            stream.write(json.dumps(sample)+'\n');stream.flush();return True
        GLib.timeout_add(8,poll);Gtk.main();stop.set()
        if worker:worker.join(timeout=15)
        if worker and worker.is_alive():raise RuntimeError('producer did not stop')
        session.disconnect();window.destroy();stream.close();producer.close();events.close()
        if started is None or producer_error:raise RuntimeError(f'no complete measurement: {producer_error}')
        qmp('quit');process.wait(timeout=10)
        rows=[json.loads(x) for x in (root/'producer.jsonl').read_text().splitlines()]
        stats=dict(seconds=args.seconds,unique=unique,unique_per_second=unique/args.seconds,
                   valid=valid,invalid_after_start=invalid,last_sequence=last,producer_count=len(rows),
                   producer_per_second=(len(rows)-1)/(rows[-1]['ack']-rows[0]['ack']) if len(rows)>1 else None,
                   qemu_exit=process.returncode,split=args.split,explicit_rate=args.rate,display_events=counts,
                   scope='TCG qtest producer and offscreen SpiceDisplay buffer only; no guest OS/GPU/manager/scanout FPS')
        (root/'result.json').write_text(json.dumps(stats,indent=2)+'\n');print(json.dumps(stats))
    finally:
        signal.alarm(0)
        stop.set()
        if worker:worker.join(timeout=12)
        for channel in channels:channel.close()
        if process.poll() is None:
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait()
        log.close()
        (root/'cleanup.json').write_text(json.dumps(dict(pid=process.pid,exit=process.returncode,stopped=process.poll() is not None))+'\n')

if __name__=='__main__':main()
