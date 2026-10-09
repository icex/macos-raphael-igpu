#!/usr/bin/env python3
"""Build research-only QEMU refresh A/B binaries; never edits/installs a VM image."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--archive',type=Path,required=True,help='pristine qemu-10.1.2.tar.xz')
p.add_argument('--output',type=Path,required=True,help='new research build directory')
p.add_argument('--jobs',type=int,default=4)
a=p.parse_args()
if not 1<=a.jobs<=8:p.error('jobs must be1..8')
a.output.mkdir(parents=True,exist_ok=False);root=a.output.resolve()
archive=a.archive.resolve();patch=Path(__file__).resolve().parents[1]/'findings/research/patches/qemu-10.1.2-spice-explicit-nongl-refresh.patch'
with tarfile.open(archive) as tar:tar.extractall(root,filter='data')
source=root/'qemu-10.1.2';build=root/'build';build.mkdir()
commands=[]
def run(cmd,cwd,name):
    commands.append(dict(argv=cmd,cwd=str(cwd)))
    with (root/name).open('w') as log:subprocess.run(cmd,cwd=cwd,stdout=log,stderr=log,check=True)
run([str(source/'configure'),'--target-list=x86_64-softmmu','--enable-spice','--enable-tcg','--disable-kvm','--disable-docs','--disable-guest-agent','--disable-download','--disable-werror'],build,'configure.log')
ninja=shutil.which('ninja')
if not ninja:raise RuntimeError('ninja must be available in PATH')
run([ninja,f'-j{a.jobs}','qemu-system-x86_64'],build,'build-original.log')
shutil.copy2(build/'qemu-system-x86_64',root/'qemu-original')
run(['patch','-p1','-i',str(patch)],source,'patch.log')
run([ninja,f'-j{a.jobs}','qemu-system-x86_64'],build,'build-patched.log')
shutil.copy2(build/'qemu-system-x86_64',root/'qemu-patched')
def digest(path):return hashlib.file_digest(path.open('rb'),'sha256').hexdigest()
(root/'build-receipt.json').write_text(json.dumps(dict(commands=commands,archive_sha256=digest(archive),patch_sha256=digest(patch),binaries={name:digest(root/name) for name in ['qemu-original','qemu-patched']}),indent=2)+'\n')
