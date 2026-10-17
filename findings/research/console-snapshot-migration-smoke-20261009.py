#!/usr/bin/env python3
"""Bounded software check: ordinary migration passes, snapshot opt-in refuses."""
import argparse, importlib.util, json, subprocess, time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--qemu',type=Path,required=True);p.add_argument('--bios-dir',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
a.output.mkdir(parents=True,exist_ok=False)
s=importlib.util.spec_from_file_location('smoke',Path(__file__).resolve().parents[2]/'tools/qemu-console-smoke.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
results=[]
for enabled in (False,True):
    root=a.output/('on' if enabled else 'default');root.mkdir()
    argv=[str(a.qemu.resolve()),'-L',str(a.bios_dir.resolve()),'-machine','q35,accel=tcg','-nodefaults','-S','-m','32M','-vga','none','-display','none','-nic','none','-device','bochs-display'+(',x-debug-snapshot=on' if enabled else ''),'-qmp',f'unix:{root.resolve()}/qmp,server=on,wait=off']
    (root/'argv.json').write_text(json.dumps(argv,indent=2)+'\n')
    with (root/'qemu.log').open('w') as log:
        proc=subprocess.Popen(argv,stdout=log,stderr=log);channel=None
        try:
            channel=m.Channel(root/'qmp',proc);assert 'QMP' in json.loads(channel.file.readline())
            def qmp(name,args=None):
                channel.file.write(json.dumps({'execute':name,'arguments':args or {}}).encode()+b'\n')
                while True:
                    reply=json.loads(channel.file.readline())
                    if 'error' in reply:raise RuntimeError(reply['error'])
                    if 'return' in reply:return reply['return']
            qmp('qmp_capabilities');qmp('migrate',{'uri':f'file:{root.resolve()}/migration.bin'})
            until=time.monotonic()+15
            while True:
                info=qmp('query-migrate')
                if info.get('status') in ('completed','failed'):break
                if time.monotonic()>=until:raise TimeoutError('migration check elapsed')
                time.sleep(.02)
            assert info['status']==('failed' if enabled else 'completed'),info
            qmp('quit');proc.wait(timeout=5);assert proc.returncode==0
            results.append(dict(snapshot=enabled,migration=info,qemu_exit=proc.returncode))
        finally:
            if channel:channel.close()
            if proc.poll() is None:
                proc.terminate()
                try:proc.wait(timeout=5)
                except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=5)
(a.output/'result.json').write_text(json.dumps(results,indent=2)+'\n')
print(json.dumps(results,indent=2))
