#!/usr/bin/env python3
"""Cross-build a standalone experimental IOKit framebuffer, without Lilu."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('release', ROOT/'tools/build-release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def build(toolchain, output):
    release.verify_toolchain(toolchain, json.loads((ROOT/'build-support/inputs.json').read_text()))
    source = ROOT/'native-framebuffer'
    info = plistlib.loads((source/'Info.plist').read_bytes())
    identity = uuid.uuid4().hex
    digest = release.tree_digest(source)
    with tempfile.TemporaryDirectory(prefix='rgpu-native-fb-') as temporary:
        stage = Path(temporary)
        shutil.copytree(source, stage/'source')
        (stage/'source/NativeBuildIdentity.h').write_text('#define RGPU_NATIVE_BUILD_ID "'+identity+'"\n')
        sdk = toolchain/'MacKernelSDK-master'
        flags = ['-target','x86_64-apple-macos10.15','-nostdinc','-nostdinc++',
                 '-I',str(sdk/'Headers'),'-I',str(stage/'source'),'-DKERNEL=1',
                 '-DAPPLE_KEXT_ASSERTIONS=1','-fapple-kext','-fno-builtin',
                 '-fno-common','-fno-exceptions','-fno-rtti','-fno-asynchronous-unwind-tables',
                 '-fno-c++-static-destructors','-mkernel','-O2','-g','-gdwarf-4',
                 '-mmmx','-msse','-msse2','-msse3','-mssse3','-mfpmath=sse']
        kmod = stage/'kmod_info.c'
        kmod.write_text('''#include <mach/mach_types.h>
extern kern_return_t RaphaelFramebuffer_kern_start(kmod_info_t *,void *);
extern kern_return_t RaphaelFramebuffer_kern_stop(kmod_info_t *,void *);
extern kern_return_t _start(kmod_info_t *,void *);
extern kern_return_t _stop(kmod_info_t *,void *);
__attribute__((visibility("default")))
KMOD_EXPLICIT_DECL(as.rgpu.RaphaelFramebuffer, "'''+info['CFBundleVersion']+'''", _start, _stop)
__private_extern__ kmod_start_func_t *_realmain=RaphaelFramebuffer_kern_start;
__private_extern__ kmod_stop_func_t *_antimain=RaphaelFramebuffer_kern_stop;
__private_extern__ int _kext_apple_cc=__APPLE_CC__;
''')
        objects = []
        for path in [kmod,stage/'source/entry.c',stage/'source/ConsoleFramebuffer.cpp']:
            obj = stage/(path.stem+'.o')
            compiler = 'clang++' if path.suffix=='.cpp' else 'clang'
            standard = '-std=c++17' if path.suffix=='.cpp' else '-std=gnu11'
            subprocess.run([compiler,'-c',str(path),'-o',str(obj),*flags,standard],check=True)
            objects.append(str(obj))
        bundle = stage/'RaphaelFramebuffer.kext'
        binary = bundle/'Contents/MacOS/RaphaelFramebuffer'
        binary.parent.mkdir(parents=True)
        subprocess.run([str(toolchain/'cctools-inst/bin/x86_64-apple-darwin-ld'),
                        '-arch','x86_64','-kext','-static','-o',str(binary),*objects,
                        '-L',str(sdk/'Library/x86_64'),'-lkmod'],check=True)
        if 'kext bundle' not in subprocess.check_output(['file',str(binary)],text=True):
            raise ValueError('not a kext bundle')
        (bundle/'Contents/Info.plist').write_bytes((source/'Info.plist').read_bytes())
        if release.tree_digest(source)!=digest:
            raise ValueError('native source changed during build')
        manifest = dict(schema=1,kind='native-framebuffer-experimental',build_id=identity,
                        bundle_id=info['CFBundleIdentifier'],version=info['CFBundleVersion'],
                        source_sha256=digest,
                        source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                        source_clean=not bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip()),
                        executable_sha256=release.sha256(binary.read_bytes()),
                        info_sha256=release.sha256((source/'Info.plist').read_bytes()),
                        runtime_verified=False,unload_supported=False)
        output.mkdir(parents=True,exist_ok=True)
        archive = output/'RaphaelFramebuffer-0.1.0-experimental.zip'
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as package:
            for path in sorted(bundle.rglob('*')):
                if path.is_file():package.write(path,path.relative_to(stage))
            package.writestr('build-manifest.json',json.dumps(manifest,indent=2)+'\n')
        (output/'SHA256SUMS').write_text(hashlib.sha256(archive.read_bytes()).hexdigest()+'  '+archive.name+'\n')
        print(archive)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--toolchain',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    build(args.toolchain.resolve(),args.output.resolve())
