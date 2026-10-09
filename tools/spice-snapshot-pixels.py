#!/usr/bin/env python3
"""Full-pixel offscreen SPICE oracle for experimental immutable snapshots.
Software TCG only; no guest OS, KVM, network device or physical GPU.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import signal
import subprocess
import time
import hashlib


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--qemu',type=Path,required=True);p.add_argument('--bios-dir',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--expect-noop-suppression',action='store_true')
    a=p.parse_args();root=a.output.resolve();root.mkdir(parents=True,exist_ok=False)
    spec=importlib.util.spec_from_file_location('smoke',Path(__file__).with_name('qemu-console-smoke.py'))
    smoke=importlib.util.module_from_spec(spec);spec.loader.exec_module(smoke)
    import numpy as np
    import gi
    gi.require_version('Gtk','3.0');gi.require_version('SpiceClientGtk','3.0');gi.require_version('SpiceClientGLib','2.0')
    from gi.repository import Gtk,GLib,GObject,SpiceClientGtk,SpiceClientGLib
    if not Gtk.init_check()[0]:raise RuntimeError('GTK backend unavailable')
    command=[str(a.qemu.resolve()),'-L',str(a.bios_dir.resolve()),'-machine','q35,accel=tcg','-nodefaults','-S','-m','128M','-vga','none','-display','none','-nic','none','-device','bochs-display,id=console,addr=02.0,vgamem=64M,x-debug-snapshot=on','-qtest',f'unix:{root}/qt,server=on,wait=off','-qtest-log','/dev/null','-qmp',f'unix:{root}/qm,server=on,wait=off','-spice',f'unix=on,addr={root}/spice,disable-ticketing=on,image-compression=off,gl=off,max-refresh-rate=60']
    rom=bytearray(b'\xff'*65536);rom[0xfff0:0xfff4]=b'\xfa\xf4\xeb\xfd';(root/'idle-rom.bin').write_bytes(rom)
    command+=['-bios',str(root/'idle-rom.bin')];(root/'argv.json').write_text(json.dumps(command,indent=2)+'\n')
    log=(root/'qemu.log').open('w');proc=subprocess.Popen(command,stdout=log,stderr=log);channels=[];session=None;window=None
    results=[];events=[];errors=[]
    def deadline(signum,frame):raise TimeoutError('software pixel oracle deadline')
    signal.signal(signal.SIGALRM,deadline);signal.alarm(90)
    try:
        qt=smoke.Channel(root/'qt',proc);channels.append(qt);qm=smoke.Channel(root/'qm',proc);channels.append(qm)
        assert 'QMP' in json.loads(qm.file.readline())
        def qmp(name):
            qm.file.write(json.dumps({'execute':name}).encode()+b'\n')
            while True:
                r=json.loads(qm.file.readline())
                if 'error' in r:raise RuntimeError(r['error'])
                if 'return' in r:return r['return']
        def test(cmd):
            r=qt.line(cmd)
            if not r.startswith('OK'):raise RuntimeError(r)
            return r
        def pci(off,val):test(f'outl 0xcf8 {0x80001000+off:#x}');test(f'outl 0xcfc {val:#x}')
        def reg(off,val=None):
            if val is None:return int(test(f'readl {0xf0000700+off:#x}').split()[1],0)
            test(f'writel {0xf0000700+off:#x} {val:#x}')
        qmp('qmp_capabilities');qmp('cont');qmp('stop')
        pci(0x10,0xe0000000);pci(0x14,0xd0000000);pci(0x18,0xf0000000);pci(4,2)
        assert reg(0)==0x52534731;reg(8,1)
        phases=[('black-first',640,480,[]),('corners',640,480,[(0,0,255,0,0),(639,0,0,255,0),(0,479,0,0,255),(639,479,193,87,41)]),('sparse-center',640,480,[(17,67,99,151,203),(317,157,255,255,255)]),('black-again',640,480,[]),('identical-black',640,480,[]),('resize-black',800,600,[]),('resize-4k-black',3840,2160,[]),('4k-corners-center',3840,2160,[(0,0,91,37,255),(3839,2159,1,254,65),(1920,1080,99,151,203)])]
        phase=-1;sent=0;expected=None;event_start=0
        def issue():
            nonlocal phase,sent,expected,event_start
            phase+=1
            if phase==len(phases):Gtk.main_quit();return
            name,w,h,points=phases[phase];expected=np.zeros((h,w,3),dtype=np.uint8)
            test(f'memset 0xd0000000 {w*h*4:#x} 0')
            for x,y,r,g,b in points:
                test(f'write {0xd0000000+(y*w+x)*4:#x} 4 0x{bytes((b,g,r,0)).hex()}');expected[y,x]=r,g,b
            reg(0x10,w);reg(0x14,h);event_start=len(events);reg(0x18,phase+1)
            assert reg(0x1c)==phase+1 and reg(0x0c)==0
            sent=time.monotonic()
        issue()
        session=SpiceClientGLib.Session();session.set_property('unix-path',str(root/'spice'))
        display=SpiceClientGtk.Display.new(session,0);window=Gtk.OffscreenWindow();window.add(display);window.show_all()
        def channel_new(session,channel):
            if isinstance(channel,SpiceClientGLib.DisplayChannel):
                GObject.Object.connect(channel,'display-invalidate',lambda ch,x,y,w,h:events.append(dict(time=time.monotonic(),x=x,y=y,width=w,height=h)))
        GObject.Object.connect(session,'channel-new',channel_new);session.connect()
        def poll():
            try:
                if time.monotonic()-sent>8:raise TimeoutError(f'phase not reconstructed: {phases[phase][0]}')
                pix=display.get_pixbuf()
                if pix is None:return True
                name,w,h,points=phases[phase]
                if (pix.get_width(),pix.get_height())!=(w,h):return True
                data=np.frombuffer(pix.get_pixels(),dtype=np.uint8)
                rgb=np.ndarray((h,w,pix.get_n_channels()),dtype=np.uint8,buffer=data,strides=(pix.get_rowstride(),pix.get_n_channels(),1))[:,:,:3]
                if not np.array_equal(rgb,expected) or time.monotonic()-sent<.5:return True
                changes=events[event_start:]
                if name=='identical-black' and a.expect_noop_suppression and changes:raise RuntimeError('unchanged frame emitted update')
                results.append(dict(name=name,width=w,height=h,pixels=w*h,sha256=hashlib.sha256(rgb.tobytes()).hexdigest(),invalidations=changes))
                issue();return phase<len(phases)
            except Exception as error:errors.append(repr(error));Gtk.main_quit();return False
        GLib.timeout_add(20,poll);Gtk.main()
        if errors:raise RuntimeError(errors)
        assert len(results)==len(phases)
        qmp('quit');proc.wait(timeout=10);assert proc.returncode==0
        (root/'result.json').write_text(json.dumps(dict(passed=True,scope='offscreen SPICE complete RGB pixels; no guest/GPU/manager/scanout qualification',cases=results,qemu_exit=proc.returncode,qemu_sha256=hashlib.sha256(a.qemu.read_bytes()).hexdigest()),indent=2)+'\n')
    finally:
        signal.alarm(0)
        if session:session.disconnect()
        if window:window.destroy()
        for c in channels:c.close()
        if proc.poll() is None:
            proc.terminate()
            try:proc.wait(timeout=5)
            except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=5)
        log.close();(root/'events.json').write_text(json.dumps(events,indent=2)+'\n')
        (root/'cleanup.json').write_text(json.dumps(dict(stopped=proc.poll() is not None,qemu_exit=proc.returncode,errors=errors))+'\n')

if __name__=='__main__':main()
