#!/usr/bin/env python3
"""Package exact guest helper sources; does not compile, install or launch them."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

ROOT=Path(__file__).resolve().parents[1]
FILES=('tools/install-console-desktop.sh','tools/console-presenter.m',
       'tools/console-display-layout.m','tools/virtual-display-server.m',
       'docs/console-helper-install.md','tools/console-install-transaction.py')


def package(root,output):
    root=Path(root);output=Path(output)
    if output.exists():raise ValueError('output already exists')
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
    clean=not subprocess.check_output(['git','status','--porcelain'],cwd=root,text=True).strip()
    payload={}
    for name in FILES:
        path=root/name
        if path.is_symlink() or not path.is_file():raise ValueError('missing or symlinked input: '+name)
        payload[path.name]=path.read_bytes()
    manifest=dict(schema=1,kind='console-helper-source-package',source_commit=commit,
                  source_clean=clean,app_identifier='org.raphaelgpu.console',
                  compiler_optimization='-O2',guest_build_required=True,
                  files={n:dict(bytes=len(b),sha256=hashlib.sha256(b).hexdigest()) for n,b in payload.items()})
    payload['console-helper-manifest.json']=(json.dumps(manifest,sort_keys=True,indent=2)+'\n').encode()
    output.parent.mkdir(parents=True,exist_ok=True)
    # Exclusive creation prevents overwriting a prior qualified package.
    with output.open('xb') as stream,zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,data in sorted(payload.items()):
            info=zipfile.ZipInfo(name,(1980,1,1,0,0,0))
            info.external_attr=(0o100755 if name.endswith('.sh') else 0o100644)<<16
            info.compress_type=zipfile.ZIP_DEFLATED
            archive.writestr(info,data)
    return manifest


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();package(ROOT,a.output)
    print(json.dumps(dict(archive=str(a.output),sha256=hashlib.sha256(a.output.read_bytes()).hexdigest())))
