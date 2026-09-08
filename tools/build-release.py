#!/usr/bin/env python3
"""Compile and package an experimental x86_64 kext; never deploy or start a VM."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import struct
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def validate_macho(data):
    if len(data) < 32:
        raise ValueError('missing or truncated Mach-O header')
    magic, cpu, subtype, kind = struct.unpack_from('<4I', data)
    if (magic, cpu, kind) != (0xfeedfacf, 0x1000007, 11):
        raise ValueError('release executable must be an x86_64 MH_KEXT_BUNDLE')


def tree_digest(root):
    if not root.is_dir():
        raise ValueError(f'missing dependency directory: {root.name}')
    digest = hashlib.sha256()
    for path in sorted(root.rglob('*')):
        if path.is_file() and '.git' not in path.parts:
            digest.update(path.relative_to(root).as_posix().encode() + b'\0' +
                          hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def verify_toolchain(toolchain, inputs):
    for key, relative in (('sdk_tree_sha256', 'MacKernelSDK-master'),
                          ('lilu_resources_sha256', 'liludbg/Lilu.kext/Contents/Resources')):
        if tree_digest(toolchain / relative) != inputs[key]:
            raise ValueError(f'{relative} differs from the pinned release inputs')


def build(toolchain, output):
    subprocess.run([os.sys.executable, str(ROOT / 'tools/route-domains.py'),
                    str(ROOT / 'src/RaphaelGPU.cpp')], check=True)
    inputs = json.loads((ROOT / 'build-support/inputs.json').read_text())
    verify_toolchain(toolchain, inputs)
    firmware = gzip.decompress((ROOT / 'build-support/rlc_fw.h.gz').read_bytes())
    if hashlib.sha256(firmware).hexdigest() != inputs['firmware_header_sha256']:
        raise ValueError('firmware build input hash mismatch')
    info = plistlib.loads((ROOT / 'kext/Info.plist').read_bytes())
    version = info['CFBundleVersion']
    with tempfile.TemporaryDirectory(prefix='rgpu-release-') as temporary:
        stage = Path(temporary)
        source = stage / 'src'
        shutil.copytree(ROOT / 'src', source)
        (source / 'rlc_fw.h').write_bytes(firmware)
        # Isolate all outputs from developer builds and the checked-in executable.
        for name in ('MacKernelSDK-master', 'liludbg', 'cctools-inst'):
            path = toolchain / name
            if path.exists(): (stage / name).symlink_to(path, target_is_directory=True)
        subprocess.run(['bash', str(ROOT / 'tools/build-kext.sh'), str(source),
                        'RaphaelGPU', info['CFBundleIdentifier'], version], check=True,
                       env=dict(os.environ, BUILD=str(stage)))
        bundle = stage / 'out/RaphaelGPU/RaphaelGPU.kext'
        executable = bundle / 'Contents/MacOS/RaphaelGPU'
        validate_macho(executable.read_bytes())
        (bundle / 'Contents/Info.plist').write_bytes(plistlib.dumps(info))
        commit = subprocess.check_output(['git','rev-parse','HEAD'], cwd=ROOT, text=True).strip()
        manifest = dict(inputs, version=version, source_commit=commit,
                        executable_sha256=hashlib.sha256(executable.read_bytes()).hexdigest(),
                        metal_execution_verified=False, verified_playable_games=0)
        output.mkdir(parents=True, exist_ok=True)
        archive = output / f'RaphaelGPU-{version}-experimental.zip'
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as package:
            for path in sorted(bundle.rglob('*')):
                if path.is_file(): package.write(path, path.relative_to(bundle.parent))
            for path in ('README.md', 'docs/supported-games.md', 'docs/releases.md',
                         'build-support/LICENSE.amdgpu'):
                package.write(ROOT / path, path)
            package.writestr('build-manifest.json', json.dumps(manifest, indent=2)+'\n')
        (output / 'SHA256SUMS').write_text(hashlib.sha256(archive.read_bytes()).hexdigest()+'  '+archive.name+'\n')
        print(archive)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--toolchain', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    build(args.toolchain.resolve(), args.output.resolve())
