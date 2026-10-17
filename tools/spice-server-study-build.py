#!/usr/bin/env python3
"""Build matched isolated spice0.16.0 libraries; never install or launch a VM."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import urllib.request

ARCHIVE='https://www.spice-space.org/download/releases/spice-server/spice-0.16.0.tar.bz2'
ARCHIVE_SHA='0a6ec9528f05371261bbb2d46ff35e7b5c45ff89bb975a99af95a5f20ff4717d'
ENUMS='https://raw.githubusercontent.com/GNOME/glib/2.88.3/gobject/glib-mkenums.in'
ENUMS_SHA='0de6a9a6d8db2106b30a8626830d87671f271c35df95d357d5d7138d06f3c061'
DEPS={'spice-protocol':'0.14.5','glib-2.0':'2.88.3','pixman-1':'0.46.4',
      'openssl':'3.6.4','libjpeg':'3.2.0','zlib':'1.3.1.zlib-ng','liblz4':'1.10.0'}
PIP=['meson==1.9.1','ninja==1.11.1.4','pyparsing==3.2.3','six==1.17.0']
OPTIONS=['-Dbuildtype=release','-Dtests=false','-Dmanual=false','-Dgstreamer=no',
         '-Dsasl=false','-Dsmartcard=disabled','-Dopus=disabled']
ROOT=Path(__file__).resolve().parent

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def download(url,sha,path):
    with urllib.request.urlopen(url,timeout=30) as stream:data=stream.read(16*1024*1024)
    if hashlib.sha256(data).hexdigest()!=sha:raise ValueError('source hash mismatch')
    with path.open('xb') as f:f.write(data)

def finish(out,qemu):
    exports=[];products={}
    for mode in ('base','instrumented'):
        library=out/(mode+'-build/server/libspice-server.so.1.15.0')
        symbols=subprocess.check_output(['nm','-D','--defined-only',str(library)],text=True)
        names=sorted(row.split()[-1] for row in symbols.splitlines());exports.append(names)
        (out/(mode+'-exports.txt')).write_text('\n'.join(names)+'\n')
        dynamic=subprocess.check_output(['readelf','-d',str(library)],text=True)
        if 'Library soname: [libspice-server.so.1]' not in dynamic:raise ValueError('SONAME changed')
        env=dict(os.environ,LD_LIBRARY_PATH=str(library.parent))
        linked=subprocess.check_output(['ldd',str(qemu)],text=True,env=env)
        if str(library.parent/'libspice-server.so.1') not in linked or 'not found' in linked:
            raise ValueError('isolated library resolution failed')
        (out/(mode+'-ldd.txt')).write_text(linked)
        conf=dict(qemu=str(qemu),qemu_sha256=digest(qemu),library=str(library),library_sha256=digest(library))
        config=out/(mode+'-wrapper.json');config.write_text(json.dumps(conf,indent=2)+'\n')
        wrapper=out/(mode+'-qemu')
        args=[sys.executable,str(ROOT/'spice-study-qemu.py'),str(config)]
        wrapper.write_text('#!'+sys.executable+'\nimport os,sys\nos.execv('+repr(sys.executable)+','+repr(args)+'+sys.argv[1:])\n')
        wrapper.chmod(0o755);products[mode]=conf
    if exports[0]!=exports[1]:raise ValueError('public symbol set changed')
    return dict(products=products,matching_exported_symbols=len(exports[0]))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--qemu',type=Path,required=True)
    parser.add_argument('--jobs',type=int,default=4)
    a=parser.parse_args()
    if not 1<=a.jobs<=4:parser.error('jobs must be1..4')
    deps={key:subprocess.check_output(['pkg-config','--modversion',key],text=True).strip() for key in DEPS}
    if deps!=DEPS:raise ValueError('research dependency versions changed; review a new pin set')
    out=a.output.resolve();out.mkdir(exist_ok=False);qemu=a.qemu.resolve(strict=True)
    commands=[]
    def run(args,name,env=None,cwd=None):
        commands.append(args)
        with (out/(name+'.log')).open('w') as log:
            subprocess.run(args,check=True,stdout=log,stderr=subprocess.STDOUT,env=env,cwd=cwd)
    archive=out/'spice-0.16.0.tar.bz2';download(ARCHIVE,ARCHIVE_SHA,archive)
    with tarfile.open(archive) as source:source.extractall(out,filter='data')
    base=out/'spice-0.16.0';inst=out/'instrumented-source';shutil.copytree(base,inst)
    patch=ROOT/'spice-server-study.patch'
    run(['patch','-p1','--batch','--fuzz=0','-i',str(patch)],'patch',cwd=inst)
    run([sys.executable,'-m','venv',str(out/'build-tools')],'venv')
    bins=out/'build-tools/bin'
    run([str(bins/'pip'),'install',*PIP],'build-tools')
    raw=out/'glib-mkenums.in';download(ENUMS,ENUMS_SHA,raw)
    enum=bins/'glib-mkenums';enum.write_bytes(raw.read_bytes().replace(b'@PYTHON@',str(bins/'python').encode()).replace(b'@VERSION@',b'2.88.3'));enum.chmod(0o755)
    native=out/'native.ini';native.write_text("[binaries]\nglib-mkenums = "+repr(str(enum))+"\n")
    env=dict(os.environ,PATH=str(bins)+os.pathsep+os.environ.get('PATH',''))
    for mode,source in [('base',base),('instrumented',inst)]:
        build=out/(mode+'-build')
        run([str(bins/'meson'),'setup',str(build),str(source),'--native-file',str(native),*OPTIONS],mode+'-configure',env)
        run([str(bins/'ninja'),'-C',str(build),'-j'+str(a.jobs)],mode+'-build',env)
    manifest=dict(schema=1,archive_url=ARCHIVE,archive_sha256=ARCHIVE_SHA,
                  enum_url=ENUMS,enum_sha256=ENUMS_SHA,pip=PIP,deps=deps,
                  options=OPTIONS,patch_sha256=digest(patch),commands=commands,**finish(out,qemu))
    (out/'build-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(manifest['products'],indent=2))

if __name__=='__main__':main()
