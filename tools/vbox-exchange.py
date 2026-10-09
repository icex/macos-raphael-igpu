#!/usr/bin/env python3
"""Prepare a private32MiB FAT exchange VDI; never mounts or starts a VM."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess

ROOT = Path('/home/bogdan/macos-vm/run/c410-exchange')
SIZE = 32 * 1024 * 1024
OFFSET = 1024 * 1024
HELPER_SHA = 'b975a17bc3bf1eb191d221e264b23e54509be394d16f9cbb6378dafb25a68acd'

def run(args):
    return subprocess.run(args, check=True, capture_output=True, timeout=30)

def prepare():
    os.umask(0o077)
    ROOT.mkdir(mode=0o700)  # Fresh namespace only, no reuse/overwrite.
    raw = ROOT/'exchange.raw'
    with raw.open('xb') as f:
        f.truncate(SIZE)
        mbr = bytearray(512)
        mbr[446:462] = struct.pack('<B3sB3sII', 0, b'\xfe\xff\xff', 0x0e,
                                   b'\xfe\xff\xff', OFFSET//512, (SIZE-OFFSET)//512)
        mbr[510:512] = b'\x55\xaa'
        f.seek(0); f.write(mbr)
    run(['mkfs.fat','-F','16','-n','RGPU410','--offset',str(OFFSET//512),str(raw),str((SIZE-OFFSET)//1024)])
    source = Path(__file__).with_name('vbox-display-inventory.py')
    assert hashlib.sha256(source.read_bytes()).hexdigest() == HELPER_SHA
    helper = ROOT/'inventory.py'; helper.write_bytes(source.read_bytes())
    guest = ROOT/'run410.py'; guest.write_bytes(Path(__file__).with_name('vbox-exchange-guest.py').read_bytes())
    shell = ROOT/'run.sh'; shell.write_bytes(Path(__file__).with_name('vbox-exchange-guest.sh').read_bytes())
    for p in (helper,guest,shell):run(['mcopy','-i',str(raw)+'@@'+str(OFFSET),str(p),'::/'+p.name])
    listing = run(['mdir','-i',str(raw)+'@@'+str(OFFSET),'::/']).stdout.decode()
    vdi = ROOT/'exchange.vdi'
    run(['qemu-img','convert','-f','raw','-O','vdi',str(raw),str(vdi)])
    run(['qemu-img','compare','-f','raw','-F','vdi',str(raw),str(vdi)])
    info = json.loads(run(['qemu-img','info','--output=json',str(vdi)]).stdout)
    assert info['format']=='vdi' and info['virtual-size']==SIZE and not info.get('backing-filename')
    record = dict(label='RGPU410',virtual_size=SIZE,partition_offset=OFFSET,listing=listing,
                  files={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (helper,guest,shell,raw,vdi)},
                  scope='offline only; no VM, host mount or guest execution')
    (ROOT/'preparation.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps(record,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--prepare',action='store_true');a=p.parse_args()
    if not a.prepare:p.error('explicit --prepare required')
    prepare()
