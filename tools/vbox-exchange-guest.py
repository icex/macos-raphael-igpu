#!/usr/bin/env python3
"""Bounded read-only guest inventory; writes only this exchange volume's new out/."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import stat
import subprocess
import time

HELPER_SHA='b975a17bc3bf1eb191d221e264b23e54509be394d16f9cbb6378dafb25a68acd'
LIMIT=8*1024*1024

def main():
    base=Path(__file__).resolve().parent
    if base != Path('/Volumes/RGPU410'):raise RuntimeError('unexpected exchange volume path')
    helper=base/'inventory.py'
    if hashlib.sha256(helper.read_bytes()).hexdigest()!=HELPER_SHA:raise RuntimeError('helper identity mismatch')
    out=base/'out';out.mkdir()  # Never overwrite previous result.
    receipt={'scope':'read-only registry and original409 artifacts; no mapping/exclusive ownership proof','started':time.time(),'files':{},'uid':os.getuid()}
    def save(name,raw):
        if len(raw)>LIMIT:raise RuntimeError('bounded inventory exceeded8MiB')
        (out/name).write_bytes(raw)
        receipt['files'][name]={'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
    for name in ('c409-ioreg.plist','c409-framebuffer.txt','c409-display-inventory.json'):
        p=Path('/tmp')/name
        try:
            st=p.lstat()
            if not stat.S_ISREG(st.st_mode) or st.st_size>LIMIT or st.st_uid!=os.getuid():raise RuntimeError('original file ownership/type/size refused')
            save(name,p.read_bytes())
        except (OSError,RuntimeError) as e:receipt['files'][name]={'unavailable':str(e)}
    commands=[('c410-ioreg.plist',['/usr/sbin/ioreg','-a','-l','-p','IOService']),
              ('c410-framebuffer.txt',['/usr/sbin/ioreg','-r','-c','IOFramebuffer','-l']),
              ('c410-os.txt',['/usr/bin/sw_vers']),('c410-cpus.txt',['/usr/sbin/sysctl','hw.ncpu'])]
    try:
        for name,argv in commands:
            p=subprocess.run(argv,capture_output=True,timeout=10)
            save(name,p.stdout);save(name+'.stderr',p.stderr)
            receipt['files'][name]['returncode']=p.returncode
            if p.returncode:raise RuntimeError('inventory command failed')
        spec=importlib.util.spec_from_file_location('inventory',helper);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
        for name in ('c409-ioreg.plist','c410-ioreg.plist'):
            if (out/name).exists():save(name+'.inventory.json',json.dumps(mod.inventory(plistlib.loads((out/name).read_bytes())),indent=2).encode())
        receipt['passed']=True
    except Exception as e:
        receipt.update(passed=False,error=type(e).__name__+': '+str(e))
    finally:
        receipt['finished']=time.time();(out/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n');os.sync()
    print(json.dumps(receipt));return 0 if receipt.get('passed') else 1

if __name__=='__main__':raise SystemExit(main())
