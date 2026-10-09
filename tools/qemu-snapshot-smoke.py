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


def run(qemu, out, bios, restart=False, timing=False):
    out.mkdir(parents=True, exist_ok=False)
    spec = importlib.util.spec_from_file_location('console_smoke', Path(__file__).with_name('qemu-console-smoke.py'))
    smoke = importlib.util.module_from_spec(spec); spec.loader.exec_module(smoke)
    command = [str(qemu), '-L', str(bios), '-machine', 'q35,accel=tcg', '-nodefaults', '-S',
               '-m', '128M', '-vga', 'none', '-display', 'none',
               '-device', 'bochs-display,id=console,addr=02.0,vgamem=64M,x-debug-snapshot=on'+
               (',x-debug-snapshot-restart=on' if restart else '')+
               (',x-debug-snapshot-timing=on' if timing else ''),
               '-qtest', f'unix:{out}/qt,server=on,wait=off',
               '-qmp', f'unix:{out}/qm,server=on,wait=off']
    if restart:
        refused = subprocess.run([str(qemu), '-L', str(bios), '-machine', 'q35,accel=tcg',
            '-nodefaults', '-S', '-m', '128M', '-vga', 'none', '-display', 'none',
            '-device', 'bochs-display,x-debug-snapshot-restart=on'],
            text=True, capture_output=True, timeout=10)
        (out/'missing-snapshot-prerequisite.txt').write_text(refused.stderr)
        assert refused.returncode != 0 and 'snapshot restart requires snapshot' in refused.stderr
    if timing:
        refused = subprocess.run([str(qemu), '-L', str(bios), '-machine', 'q35,accel=tcg',
            '-nodefaults', '-S', '-m', '128M', '-vga', 'none', '-display', 'none',
            '-device', 'bochs-display,x-debug-snapshot-timing=on'],
            text=True, capture_output=True, timeout=10)
        (out/'missing-timing-prerequisite.txt').write_text(refused.stderr)
        assert refused.returncode != 0 and 'snapshot timing requires snapshot' in refused.stderr
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
                data=path.read_bytes()
                # QEMU10.1.2 ppm_save writes pixman's aligned RGB24 stride,
                # including row padding (ui/ui-qmp-cmds.c:299). Check every
                # actual RGB pixel and exact serialized length, not padding.
                header=f'P6\n{w} {h}\n255\n'.encode()
                stride=(w*3+3)&~3
                pixels=data[len(header):]
                if (not data.startswith(header) or len(pixels)!=stride*h or
                    any(pixels[y*stride:y*stride+w*3]!=bytes([byte])*(w*3)
                        for y in range(h))):
                    raise RuntimeError(f'{name}: full pixel mismatch')
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
            assert reg(0)==(0x52534732 if restart else 0x52534731) and reg(4)==32*1024*1024 and reg(8)==0
            if restart:
                assert reg(0x30)==reg(0x34)==0
                reg(8,1);assert reg(8)==0 and reg(0x0c)==5
                for invalid_epoch in (2,0xffffffff):
                    reg(0x30,invalid_epoch);reg(8,1)
                    assert reg(8)==0 and reg(0x34)==0 and reg(0x0c)==5
                reg(0x30,1)
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
            if timing:
                time.sleep(5.05)  # Cross the bounded host-report window, no guest VM.
            if restart:
                assert reg(0x34)==1
                reg(0x34,9);assert reg(0x34)==1 and reg(0x0c)==2
                # An armed lease cannot be replaced, even by its successor epoch.
                reg(0x30,2);reg(8,1)
                assert reg(8)==1 and reg(0x34)==1 and reg(0x1c)==seq
                reg(0x30,1)
                fill(0xd0000000,640*480*4,101);seq+=1;commit(seq,640,480)
                pending=reg(0x2c)
                # Wrong epoch may update error only: not geometry, ACK or pending.
                reg(0x30,0)
                for offset,value in ((0x10,800),(0x14,600),(0x18,seq+1),(8,2)):
                    reg(offset,value)
                    assert reg(0x0c)==5 and reg(8)==1 and reg(0x1c)==seq
                    assert reg(0x2c)==pending and reg(0x10)==640 and reg(0x14)==480
                image('stale-epoch-pending-preserved',640,480,101)
                reg(0x30,1)
                fill(0xd0000000,640*480*4,102);seq+=1;commit(seq,640,480)
                assert reg(0x2c)==seq
            reg(8,2);assert reg(8)==2 and reg(0x2c)==0
            image('legacy-after-disarm',640,480,7)
            if restart:
                # Same epoch cannot rearm; next epoch starts a fresh sequence.
                reg(8,1);assert reg(8)==2 and reg(0x0c)==5
                reg(0x30,3);reg(8,1);assert reg(8)==2 and reg(0x34)==1
                reg(0x30,2);reg(8,1)
                assert reg(8)==1 and reg(0x34)==2
                assert all(reg(offset)==0 for offset in (0x0c,0x10,0x14,0x1c,0x20,0x2c))
                fill(0xd0000000,801*601*4,117);commit(1,801,601)
                fill(0xd0000000,801*601*4,221)
                image('restarted-odd-frame-immutable',801,601,117)
                reg(0x18,1);assert reg(0x0c)==3 and reg(0x1c)==1
                reg(0x30,1);reg(8,2);reg(0x18,2)
                assert reg(8)==1 and reg(0x34)==2 and reg(0x1c)==1
                image('old-epoch-after-restart-refused',801,601,117)
                reg(0x30,2);reg(8,2);assert reg(8)==2
                image('restart-retired-fallback',640,480,7)
            else:
                reg(8,1);assert reg(8)==2 and reg(0x0c)==1
                reg(0x18,seq+1);assert reg(0x1c)==seq
            # Both protocol variants remain explicitly non-migratable.
            qmp('migrate', {'uri':'file:'+str(out/'migration.bin')})
            migration=None
            until=time.monotonic()+5
            while time.monotonic()<until:
                migration=qmp('query-migrate')
                if migration.get('status') in ('failed','completed'):break
                time.sleep(.02)
            assert migration.get('status')=='failed' and 'pre-save failed: bochs-display' in migration.get('error-desc','')
            qmp('quit');process.wait(timeout=10)
            assert process.returncode==0
            timing_rows = [line for line in (out/'qemu.log').read_text().splitlines()
                           if line.startswith('bochs-snapshot-timing ')]
            if timing:
                assert timing_rows, 'enabled timing emitted no bounded window'
                for line in timing_rows:
                    fields=dict(token.split('=',1) for token in line.split()[1:])
                    n=int(fields['commits'])
                    assert all(int(fields[k])==n for k in ('alloc_calls','copy_calls','free_calls'))
                    assert int(fields['pending_null'])+int(fields['pending_present'])==n
                    assert fields['saturated']=='0' and fields['dropped_geometry']=='0'
                    assert int(fields['end_us'])-int(fields['start_us'])>=5000000
            else:
                assert not timing_rows, 'default-off timing unexpectedly logged'
            result=dict(passed=True, host_timing_enabled=timing, host_timing_rows=timing_rows,scope='serialized qtest staging ownership and immutable QEMU full pixels; no guest fences, SPICE delivery, or native qualification',
                        checks=checks,counters=counters,migration=migration,commit_roundtrip_timings=timings,qemu_exit_code=process.returncode,
                        qemu_sha256=hashlib.sha256(qemu.read_bytes()).hexdigest(),
                        no_kvm=True,no_physical_gpu=True,one_shot_rearm_refused=not restart,
                        restart_epoch_protocol=restart,
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
    parser.add_argument('--restart',action='store_true')
    parser.add_argument('--timing',action='store_true')
    args=parser.parse_args()
    print(json.dumps(run(args.qemu.resolve(),args.output.resolve(),args.bios_dir.resolve(),restart=args.restart,timing=args.timing),indent=2))
