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


def band(token,nonce,sequence,second=None,width=640,scale=1):
    # Full-width 96-row band starts at framebuffer y64. Two bordered tokens.
    raw=bytearray(width*96*scale*4)
    for left,seq in [(16,sequence),(176,sequence if second is None else second)]:
        packet=token.packet(nonce,seq)
        for row in range(12):
            for col in range(18):
                if row in (0,11) or col in (0,17):pixel=b'\xff\x00\xff\x00'
                else:
                    bit=(row-1)*16+col-1
                    value=255 if (packet[bit//8]>>(7-bit%8))&1 else 0
                    pixel=bytes((value,value,value,0))
                line=pixel*(8*scale)
                for y in range(row*8*scale,(row*8+8)*scale):
                    off=(y*width+(left+col*8)*scale)*4;raw[off:off+32*scale]=line
    # Unused corner pixels validate B/G/R channel conversion independently of
    # the decoder's grayscale and magenta colors. Never touches sampled points.
    for left in (16,176):
        off=left*scale*4;raw[off:off+4]=bytes((191,73,17,0))
    return raw


def event_control_passed(mode,split,invalidations,unique,invalid_after_start,errors,qemu_exit):
    """A positive token test and deliberate-corruption control have opposite oracles."""
    if errors or qemu_exit!=0 or invalidations<=1:return False
    if mode=='count-only':return True  # No pixel integrity claim.
    if mode!='roi':return False
    if split:return invalid_after_start>0
    return unique>1 and invalid_after_start==0


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--qemu',type=Path,required=True);p.add_argument('--bios-dir',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--seconds',type=int,default=15)
    p.add_argument('--rate',type=int,choices=(60,));p.add_argument('--split',action='store_true')
    p.add_argument('--snapshot',action='store_true',help='isolated experimental staging/ACK producer')
    p.add_argument('--roi-extension',type=Path,help='optional paired observer control, no extra connection')
    p.add_argument('--event-observer',choices=['roi','count-only'],help='exercise production EventObserver synchronously; timer only bounds duration')
    p.add_argument('--manager-wrapper-control',action='store_true',help='also compare actual manager selection function on this isolated widget')
    p.add_argument('--width',type=int,default=640);p.add_argument('--height',type=int,default=480)
    p.add_argument('--scale',type=int,choices=(1,2),default=1)
    p.add_argument('--interval-ms',type=int,default=8)
    args=p.parse_args()
    if not 1<=args.seconds<=30:p.error('seconds must be 1..30')
    if not 8<=args.interval_ms<=1000:p.error('interval must be8..1000ms')
    if not 320*args.scale<=args.width<=3840 or not 160*args.scale<=args.height<=2160:p.error('unsupported geometry')
    roi=None
    if args.roi_extension:
        import sys
        sys.path.insert(0,str(args.roi_extension.resolve()))
        import console_token_roi as roi
    manager=None;extension_identity=None
    if args.event_observer=='roi' and roi is None:p.error('event ROI control requires extension')
    if args.event_observer and args.manager_wrapper_control:p.error('choose paired timer or event control')
    if args.event_observer:
        manager=load('event_manager_wrapper','console-manager-cadence.py')
        if roi is not None:roi,extension_identity=manager.load_roi_extension(Path(roi.__file__))
    if args.manager_wrapper_control:
        if roi is None:p.error('manager wrapper control requires ROI extension')
        manager=load('manager_wrapper','console-manager-cadence.py')
        roi,extension_identity=manager.load_roi_extension(Path(roi.__file__))
    args.output.mkdir(parents=True,exist_ok=False)
    token=load('token','console-token.py');smoke=load('smoke','qemu-console-smoke.py')
    nonce='0344034403440344';root=args.output.resolve()
    command=[str(args.qemu.resolve()),'-L',str(args.bios_dir.resolve()),'-machine','q35,accel=tcg',
             '-nodefaults','-S','-m','128M','-vga','none','-display','none','-nic','none',
             '-device','bochs-display,id=console,addr=02.0,vgamem=64M'+(',x-debug-snapshot=on' if args.snapshot else ''),
             '-qtest',f'unix:{root}/qt,server=on,wait=off','-qtest-log','/dev/null',
             '-qmp',f'unix:{root}/qm,server=on,wait=off',
             '-spice',f'unix=on,addr={root}/spice,disable-ticketing=on,image-compression=off,gl=off'+
             (',max-refresh-rate=60' if args.rate else '')]
    (root/'argv.json').write_text(json.dumps(command,indent=2)+'\n')
    rom=bytearray(b'\xff'*65536);rom[0xfff0:0xfff4]=b'\xfa\xf4\xeb\xfd'
    (root/'idle-rom.bin').write_bytes(rom);command += ['-bios',str(root/'idle-rom.bin')]
    (root/'argv.json').write_text(json.dumps(command,indent=2)+'\n')
    event_control=None
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
        for i,v in [(4,0),(1,args.width),(2,args.height),(3,32),(6,args.width),(8,0),(9,0)]:test(f'writew {0xf0000500+i*2:#x} {v:#x}')
        snapshot_sequence=0
        if args.snapshot:
            pci(0x14,0xd0000000)
            if int(test('readl 0xf0000700').split()[1],0)!=0x52534731:
                raise RuntimeError('snapshot capability absent')
            test('writel 0xf0000708 1')
            test(f'writel 0xf0000710 {args.width}')
            test(f'writel 0xf0000714 {args.height}')
        def write(raw):
            nonlocal snapshot_sequence
            base=0xd0000000 if args.snapshot else 0xe0000000
            test(f'write {base+64*args.scale*args.width*4:#x} {len(raw):#x} 0x{raw.hex()}')
            if args.snapshot:
                snapshot_sequence+=1
                test(f'writel 0xf0000718 {snapshot_sequence}')
                ack=int(test('readl 0xf000071c').split()[1],0)
                error=int(test('readl 0xf000070c').split()[1],0)
                if ack!=snapshot_sequence or error:
                    raise RuntimeError('snapshot ACK mismatch')
        write(band(token,nonce,0,width=args.width,scale=args.scale));test('writew 0xf0000508 0x41')
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
            nonlocal event_control
            if isinstance(channel,SpiceClientGLib.DisplayChannel):
                if args.event_observer:
                    if event_control is not None:raise RuntimeError('duplicate display channel')
                    event_control=manager.EventObserver(display,channel,GObject.Object.connect_after,GObject.Object.disconnect,
                        event_sample if args.event_observer=='roi' else None,
                        lambda row:events.write(json.dumps(row)+'\n'),event_failure)
                GObject.Object.connect(channel,'display-mark',lambda channel,mark:event('mark',mark))
                GObject.Object.connect(channel,'display-invalidate',lambda channel,x,y,w,h:event('invalidate',x,y,w,h))
        GObject.Object.connect(session,'channel-new',channel_new)
        session.connect()
        stream=(root/'samples.jsonl').open('w');producer=(root/'producer.jsonl').open('w')
        began=time.monotonic();started=None;tracker=token.SequenceTracker();unique=invalid=valid=0;last=None;bounds_refused=False
        def produce():
            try:
                start=time.monotonic();sequence=0
                while not stop.is_set() and time.monotonic()-start<args.seconds:
                    sequence+=1;t0=time.monotonic()
                    if args.split:
                        write(band(token,nonce,sequence,sequence-1,width=args.width,scale=args.scale));stop.wait(.020)
                    write(band(token,nonce,sequence,width=args.width,scale=args.scale));t1=time.monotonic()
                    producer.write(json.dumps(dict(sequence=sequence,start=t0,ack=t1,split=args.split))+'\n');producer.flush()
                    stop.wait(max(0,start+sequence/60-time.monotonic()))
            except Exception as error:producer_error.append(repr(error));stop.set()
        def event_failure(error):
            producer_error.append(repr(error));Gtk.main_quit()
        def event_sample(display,trigger):
            nonlocal unique,invalid,valid,last
            begin=time.monotonic();row=dict(time=begin,trigger=trigger)
            try:
                decoded=manager.sample_display(display,token,nonce,roi)
                result=tracker.observe(decoded['sequence']);valid+=1;unique+=int(result['unique']);last=decoded['sequence']
                row.update(valid=True,**decoded,**result)
            except (ValueError,RuntimeError) as error:
                if started is not None:invalid+=1
                row.update(valid=False,error=str(error))
            row['duration']=time.monotonic()-begin;stream.write(json.dumps(row)+'\n');stream.flush()
        def poll():
            nonlocal started,worker,unique,invalid,valid,last,bounds_refused
            now=time.monotonic();sample={'time':now}
            if started is not None and now-started>=args.seconds:
                Gtk.main_quit();return False
            if now-began>args.seconds+15 or producer_error:
                Gtk.main_quit();return False
            if args.event_observer:
                if started is None and event_control is not None and counts['invalidate']:
                    started=now;worker=threading.Thread(target=produce);worker.start()
                return True
            try:
                def full_snapshot():
                    pix=display.get_pixbuf()
                    if pix is None:raise ValueError('no-pixbuf')
                    return dict(pixels=pix.get_pixels(),width=pix.get_width(),height=pix.get_height(),stride=pix.get_rowstride(),channels=pix.get_n_channels())
                if roi:
                    results={};snapshots={}
                    order=('roi','full') if (valid+invalid)%2 else ('full','roi')
                    sample['order']=order
                    for observer in order:
                        begin=time.monotonic()
                        try:
                            snap=roi.snapshot(display,args.scale) if observer=='roi' else full_snapshot()
                            sample[observer+'_snapshot_seconds']=time.monotonic()-begin
                            snapshots[observer]=snap
                            try:
                                seq=token.decode(snap['pixels'],snap['width'],snap['height'],snap['stride'],snap['channels'],nonce,args.scale)
                                results[observer]=dict(valid=True,sequence=seq)
                            except ValueError as error:results[observer]=dict(valid=False,error=str(error))
                        except (ValueError,RuntimeError) as error:results[observer]=dict(valid=False,error=str(error))
                        sample[observer+'_total_seconds']=time.monotonic()-begin
                    sample['observers']=results
                    # Ignore unlike startup availability until both have buffers.
                    if 'roi_snapshot_seconds' in sample and 'full_snapshot_seconds' in sample:
                        full=snapshots['full'];small=snapshots['roi'];pixels_equal=True
                        for y in range(64*args.scale,160*args.scale):
                            for left in (16*args.scale,176*args.scale):
                                length=144*args.scale*3
                                a=y*full['stride']+left*3;b=y*small['stride']+left*3
                                if full['pixels'][a:a+length]!=small['pixels'][b:b+length]:pixels_equal=False
                        sample['roi_pixels_equal']=pixels_equal
                        sample['equivalent']=results['roi']==results['full'] and pixels_equal
                        if manager is not None:
                            wrapper_results={}
                            for name,extension in [('full',None),('roi',roi)]:
                                try:wrapper_results[name]=dict(valid=True,**manager.sample_display(display,token,nonce,extension))
                                except (ValueError,RuntimeError) as error:wrapper_results[name]=dict(valid=False,error=str(error))
                            sample['manager_wrapper']=wrapper_results
                            sample['manager_wrapper_equivalent']=wrapper_results['full']==wrapper_results['roi']
                            sample['equivalent']=sample['equivalent'] and sample['manager_wrapper_equivalent']
                        if not sample['equivalent']:raise RuntimeError('observer disagreement')
                    if not results['full']['valid']:raise ValueError(results['full']['error'])
                    if not results['roi']['valid']:raise ValueError(results['roi']['error'])
                    sequence=results['full']['sequence']
                else:
                    snap=full_snapshot()
                    sequence=token.decode(snap['pixels'],snap['width'],snap['height'],snap['stride'],snap['channels'],nonce,args.scale)
                sample.update(width=args.width,height=args.height,channels=3)
                result=tracker.observe(sequence)
                if started is None:
                    if roi and args.width==320 and args.height==160 and args.scale==1:
                        try:roi.snapshot(display,2)
                        except ValueError as error:
                            if str(error)!='token ROI outside primary':raise
                            bounds_refused=True
                        else:raise RuntimeError('out-of-bounds ROI was accepted')
                    started=now;worker=threading.Thread(target=produce);worker.start()
                valid+=1;unique+=int(result['unique']);last=sequence
                sample.update(valid=True,sequence=sequence,**result)
            except (ValueError,RuntimeError) as error:
                if started is not None:invalid+=1
                sample.update(valid=False,error=str(error))
            sample['duration']=time.monotonic()-now
            stream.write(json.dumps(sample)+'\n');stream.flush();return True
        def guarded_poll():
            try:return poll()
            except Exception as error:event_failure(error);return False
        def watchdog():
            event_failure(TimeoutError('GLib software control deadline'));return False
        GLib.timeout_add_seconds(args.seconds+15,watchdog)
        GLib.timeout_add(args.interval_ms,guarded_poll);Gtk.main();stop.set()
        if worker:worker.join(timeout=15)
        if worker and worker.is_alive():raise RuntimeError('producer did not stop')
        if event_control:event_control.close()
        session.disconnect();window.destroy();stream.close();producer.close();events.close()
        if started is None or producer_error:raise RuntimeError(f'no complete measurement: {producer_error}')
        snapshot_counters=None
        if args.snapshot:
            snapshot_counters={name:int(test(f'readl {0xf0000700+offset:#x}').split()[1],0) for name,offset in [('ack',0x1c),('published_seq',0x20),('pending_replaced',0x24),('published_count',0x28),('pending_seq',0x2c)]}
        qmp('quit');process.wait(timeout=10)
        rows=[json.loads(x) for x in (root/'producer.jsonl').read_text().splitlines()]
        stats=dict(seconds=args.seconds,interval_ms=args.interval_ms,unique=unique,unique_per_second=unique/args.seconds,
                   valid=valid,invalid_after_start=invalid,last_sequence=last,producer_count=len(rows),
                   producer_per_second=(len(rows)-1)/(rows[-1]['ack']-rows[0]['ack']) if len(rows)>1 else None,
                   qemu_exit=process.returncode,split=args.split,snapshot=args.snapshot,snapshot_counters=snapshot_counters,explicit_rate=args.rate,display_events=counts,
                   width=args.width,height=args.height,scale=args.scale,paired_observers=roi is not None and not args.event_observer,roi_bounds_refused=bounds_refused,
                   manager_wrapper_control=manager is not None,roi_extension=extension_identity,
                   scope='TCG qtest producer and offscreen SpiceDisplay buffer only; no guest OS/GPU/manager/scanout FPS')
        if args.event_observer:
            stats.update(event_observer=args.event_observer,**event_control.summary())
            stats['passed']=event_control_passed(args.event_observer,args.split,event_control.invalidations,
                                                       unique,invalid,producer_error,process.returncode)
        if roi and not args.event_observer:
            samples=[json.loads(line) for line in (root/'samples.jsonl').read_text().splitlines()]
            stats['observer_disagreements']=sum(row.get('equivalent') is False for row in samples)
            stats['paired_samples']=sum('equivalent' in row for row in samples)
            stats['passed']=stats['observer_disagreements']==0 and stats['paired_samples']>0
            if manager is not None:
                ids={row['manager_wrapper']['full']['sequence'] for row in samples if row.get('manager_wrapper',{}).get('full',{}).get('valid')}
                stats['manager_wrapper_unique']=len(ids)
                stats['passed']=stats['passed'] and len(ids)>1
        (root/'result.json').write_text(json.dumps(stats,indent=2)+'\n');print(json.dumps(stats))
        if (roi or args.event_observer) and not stats['passed']:raise RuntimeError('paired observer qualification failed')
    finally:
        if event_control:event_control.close()
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
