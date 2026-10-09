#!/usr/bin/env python3
"""Software-only Bochs snapshot protocol oracle: qtest writes, QMP full pixels.
No KVM, guest disks, networking, physical device, or SPICE client is opened.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import time


def run(qemu, out, bios):
    out.mkdir(parents=True, exist_ok=False)
    spec = importlib.util.spec_from_file_location('console_smoke', Path(__file__).with_name('qemu-console-smoke.py'))
    smoke = importlib.util.module_from_spec(spec); spec.loader.exec_module(smoke)
    command = [str(qemu), '-L', str(bios), '-machine', 'q35,accel=tcg', '-nodefaults', '-S',
               '-m', '128M', '-vga', 'none', '-display', 'none',
               '-device', 'bochs-display,id=console,addr=02.0,vgamem=64M,x-debug-snapshot=on',
               '-qtest', f'unix:{out}/qt,server=on,wait=off',
               '-qmp', f'unix:{out}/qm,server=on,wait=off']
    (out/'argv.json').write_text(json.dumps(command, indent=2)+'\n')
    with (out/'qemu.log').open('w') as log:
        process = subprocess.Popen(command, stdout=log, stderr=log)
        channels = []; checks = []
        try:
            qt = smoke.Channel(out/'qt', process); channels.append(qt)
            qm = smoke.Channel(out/'qm', process); channels.append(qm)
            assert 'QMP' in json.loads(qm.file.readline())
            def qmp(name, args=None):
                qm.file.write(json.dumps({'execute':name,'arguments':args or {}}).encode()+b'\n')
                while True:
                    reply = json.loads(qm.file.readline())
                    if 'error' in reply: raise RuntimeError(reply['error'])
                    if 'return' in reply: return reply['return']
            def qtcall(line):
                reply = qt.line(line)
                if not reply.startswith('OK'): raise RuntimeError(reply)
                return reply
            def pci(offset, value=None):
                qtcall(f'outl 0xcf8 {0x80001000+offset:#x}')
                if value is None: return int(qtcall('inl 0xcfc').split()[1],0)
                qtcall(f'outl 0xcfc {value:#x}')
            def reg(offset, value=None):
                addr = 0xf0000700+offset
                if value is None: return int(qtcall(f'readl {addr:#x}').split()[1],0)
                qtcall(f'writel {addr:#x} {value:#x}')
            def vbe(i,v): qtcall(f'writew {0xf0000500+2*i:#x} {v:#x}')
            def mode(w,h):
                vbe(4,0)
                for i,v in [(1,w),(2,h),(3,32),(6,w),(8,0),(9,0)]: vbe(i,v)
                vbe(4,0x41)
            def fill(addr,size,byte): qtcall(f'memset {addr:#x} {size:#x} {byte:#x}')
            def image(name,w,h,byte):
                path=out/f'{name}.ppm'; qmp('screendump', {'filename':str(path)})
                expected=f'P6\n{w} {h}\n255\n'.encode()+bytes([byte])*(w*h*3)
                data=path.read_bytes()
                if data != expected: raise RuntimeError(f'{name}: full pixel mismatch')
                checks.append(dict(name=name,width=w,height=h,pixels=w*h,
                                   sha256=hashlib.sha256(data).hexdigest()))
            def commit(seq,w,h):
                reg(0x10,w);reg(0x14,h)
                t=time.monotonic();reg(0x18,seq);elapsed=time.monotonic()-t
                assert reg(0x1c)==seq and reg(0x0c)==0
                return elapsed
            qmp('qmp_capabilities')
            assert pci(0)==0x11111234
            pci(0x10,0xe0000000);pci(0x14,0xd0000000);pci(0x18,0xf0000000);pci(4,2)
            assert reg(0)==0x52534731 and reg(4)==32*1024*1024 and reg(8)==0
            mode(640,480);fill(0xe0000000,640*480*4,31)
            image('legacy-before-arm',640,480,31)
            reg(8,1);assert reg(8)==1
            seq=0; timings=[]
            for w,h in [(640,480),(1920,1080),(3840,2160),(800,600)]:
                seq+=1;byte=40+seq
                fill(0xd0000000,w*h*4,byte)
                timings.append(dict(width=w,height=h,seconds=commit(seq,w,h)))
                # ACK was read before both independent guest-memory mutations.
                fill(0xd0000000,w*h*4,219)
                fill(0xe0000000,640*480*4,7);mode(640,480)
                image(f'ack-overwrite-{seq}',w,h,byte)
                image(f'immutable-repeat-{seq}',w,h,byte)
            reg(0x18,seq);assert reg(0x0c)==3 and reg(0x1c)==seq
            reg(0x10,4096);reg(0x14,2160);reg(0x18,seq+1)
            assert reg(0x0c)==4 and reg(0x1c)==seq
            # Two complete snapshots before any screen update: only latest wins.
            for byte in (91,92):
                fill(0xd0000000,640*480*4,byte);seq+=1;commit(seq,640,480)
            fill(0xd0000000,640*480*4,213)
            image('latest-completed-pending',640,480,92)
            counters=dict(last_published_sequence=reg(0x20),pending_replaced=reg(0x24),published=reg(0x28),pending_sequence=reg(0x2c))
            assert counters==dict(last_published_sequence=seq,pending_replaced=1,published=5,pending_sequence=0)
            reg(8,2);assert reg(8)==2
            image('legacy-after-disarm',640,480,7)
            reg(8,1);assert reg(8)==2 and reg(0x0c)==1
            reg(0x18,seq+1);assert reg(0x1c)==seq
            qmp('quit');process.wait(timeout=10)
            assert process.returncode==0
            result=dict(passed=True,scope='serialized qtest staging ownership and immutable QEMU full pixels; no guest fences, SPICE delivery, or native qualification',
                        checks=checks,counters=counters,commit_roundtrip_timings=timings,qemu_exit_code=process.returncode,
                        qemu_sha256=hashlib.sha256(qemu.read_bytes()).hexdigest(),
                        no_kvm=True,no_physical_gpu=True,one_shot_rearm_refused=True,
                        duplicate_and_oversize_refused=True)
            (out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
            return result
        finally:
            for c in channels: c.close()
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: process.kill();process.wait(timeout=5)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qemu',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--bios-dir',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(run(args.qemu.resolve(),args.output.resolve(),args.bios_dir.resolve()),indent=2))
