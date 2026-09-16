#!/usr/bin/env python3
"""Compile and package an experimental x86_64 kext; never deploy or start a VM."""
import argparse
import gzip
import hashlib
import json
import os
import re
from pathlib import Path
import plistlib
import shutil
import struct
import subprocess
import tempfile
import zipfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
RELEASE_DOCUMENTS = (
    'README.md',
    'status.md',
    'docs/ROADMAP.md',
    'docs/releases.md',
    'build-support/LICENSE.amdgpu',
)


def validate_macho(data):
    if len(data) < 32:
        raise ValueError('missing or truncated Mach-O header')
    magic, cpu, subtype, kind = struct.unpack_from('<4I', data)
    if (magic, cpu, kind) != (0xfeedfacf, 0x1000007, 11):
        raise ValueError('release executable must be an x86_64 MH_KEXT_BUNDLE')
    if b'__tlv_bootstrap' in data:
        raise ValueError('unsupported TLV bootstrap reference')
    ncmds, sizeofcmds = struct.unpack_from('<2I', data, 16)
    commands_end = 32 + sizeofcmds
    if commands_end > len(data):
        raise ValueError('truncated Mach-O load commands')
    cursor = 32
    for _ in range(ncmds):
        if cursor + 8 > commands_end:
            raise ValueError('truncated Mach-O load command')
        command, command_size = struct.unpack_from('<2I', data, cursor)
        if command_size < 8 or cursor + command_size > commands_end:
            raise ValueError('invalid Mach-O load command size')
        if command == 0x19:  # LC_SEGMENT_64
            if command_size < 72:
                raise ValueError('truncated Mach-O segment command')
            nsects = struct.unpack_from('<I', data, cursor + 64)[0]
            sections_end = cursor + 72 + nsects * 80
            if sections_end > cursor + command_size:
                raise ValueError('truncated Mach-O section table')
            for section_offset in range(cursor + 72, sections_end, 80):
                section = data[section_offset:section_offset + 16].split(b'\0', 1)[0]
                if section in (b'__thread_vars', b'__thread_bss', b'__thread_data'):
                    raise ValueError('unsupported thread-local section')
        cursor += command_size


def tree_digest(root):
    if not root.is_dir():
        raise ValueError(f'missing dependency directory: {root.name}')
    digest = hashlib.sha256()
    for path in sorted(root.rglob('*')):
        if path.is_file() and '.git' not in path.parts:
            digest.update(path.relative_to(root).as_posix().encode() + b'\0' +
                          hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def sha256(value):
    return hashlib.sha256(value).hexdigest()


def debug_build_script(original):
    needle = b'-mkernel -O2\n'
    if original.count(needle) != 1:
        raise ValueError('private debug flag insertion point must occur exactly once')
    return original.replace(needle, b'-mkernel -O2 -g -gdwarf-4\n')


def _dwarfdump_uuid(path):
    output = subprocess.check_output(['llvm-dwarfdump', '--uuid', str(path)], text=True)
    match = re.search(r'UUID:\s*([0-9A-Fa-f-]{36})\s', output)
    if not match:
        raise ValueError(f'UUID absent for {path}')
    return match.group(1).lower().replace('-', '')


def verify_debug_uuids(executable, dsym):
    executable_uuid = _dwarfdump_uuid(executable)
    dsym_uuid = _dwarfdump_uuid(dsym)
    if executable_uuid != dsym_uuid:
        raise ValueError('executable/dSYM UUID mismatch')
    return executable_uuid


def verify_toolchain(toolchain, inputs):
    for key, relative in (('sdk_tree_sha256', 'MacKernelSDK-master'),
                          ('lilu_resources_sha256', 'liludbg/Lilu.kext/Contents/Resources')):
        if tree_digest(toolchain / relative) != inputs[key]:
            raise ValueError(f'{relative} differs from the pinned release inputs')


def build(toolchain, output, debug_symbols=False):
    subprocess.run([os.sys.executable, str(ROOT / 'tools/route-domains.py'),
                    str(ROOT / 'src/RaphaelGPU.cpp')], check=True)
    inputs = json.loads((ROOT / 'build-support/inputs.json').read_text())
    verify_toolchain(toolchain, inputs)
    canonical_script = ROOT / 'tools/build-kext.sh'
    canonical_before = {
        'build_script_sha256': sha256(canonical_script.read_bytes()),
        'tracked_source_sha256': tree_digest(ROOT / 'src'),
        'inputs_sha256': sha256((ROOT / 'build-support/inputs.json').read_bytes()),
    }
    firmware = gzip.decompress((ROOT / 'build-support/rlc_fw.h.gz').read_bytes())
    if hashlib.sha256(firmware).hexdigest() != inputs['firmware_header_sha256']:
        raise ValueError('firmware build input hash mismatch')
    info = plistlib.loads((ROOT / 'kext/Info.plist').read_bytes())
    version = info['CFBundleVersion']
    with tempfile.TemporaryDirectory(prefix='rgpu-release-') as temporary:
        stage = Path(temporary)
        source = stage / 'src'
        shutil.copytree(ROOT / 'src', source)
        source_sha256 = tree_digest(source)
        # One build invocation gets one marker, bound to the final executable hash
        # in its manifest. Rebuilding the same version cannot impersonate it.
        build_id = uuid.uuid4().hex
        (source / 'BuildIdentity.hpp').write_text('#define RGPU_BUILD_ID "'+build_id+'"\n')
        (source / 'rlc_fw.h').write_bytes(firmware)
        # Isolate all outputs from developer builds and the checked-in executable.
        for name in ('MacKernelSDK-master', 'liludbg', 'cctools-inst'):
            path = toolchain / name
            if path.exists(): (stage / name).symlink_to(path, target_is_directory=True)
        build_script = canonical_script
        private_script_sha256 = None
        if debug_symbols:
            build_script = stage / 'build-kext-debug.sh'
            build_script.write_bytes(debug_build_script(canonical_script.read_bytes()))
            private_script_sha256 = sha256(build_script.read_bytes())
        subprocess.run(['bash', str(build_script), str(source),
                        'RaphaelGPU', info['CFBundleIdentifier'], version], check=True,
                       env=dict(os.environ, BUILD=str(stage)))
        bundle = stage / 'out/RaphaelGPU/RaphaelGPU.kext'
        executable = bundle / 'Contents/MacOS/RaphaelGPU'
        validate_macho(executable.read_bytes())
        (bundle / 'Contents/Info.plist').write_bytes(plistlib.dumps(info))
        debug_manifest = None
        if debug_symbols:
            dsym = stage / 'RaphaelGPU.dSYM'
            subprocess.run(['dsymutil', str(executable), '-o', str(dsym)], check=True)
            executable_uuid = verify_debug_uuids(executable, dsym)
            dwarf = dsym / 'Contents/Resources/DWARF/RaphaelGPU'
            debug_manifest = {
                'schema': 1,
                'flags': ['-O2', '-g', '-gdwarf-4'],
                'private_build_script_sha256': private_script_sha256,
                'canonical_inputs_before': canonical_before,
                'executable_uuid': executable_uuid,
                'executable_sha256': sha256(executable.read_bytes()),
                'dsym_uuid': executable_uuid,
                'dsym_dwarf_sha256': sha256(dwarf.read_bytes()),
                'debug_source_sha256': tree_digest(source),
            }
            canonical_after = {
                'build_script_sha256': sha256(canonical_script.read_bytes()),
                'tracked_source_sha256': tree_digest(ROOT / 'src'),
                'inputs_sha256': sha256((ROOT / 'build-support/inputs.json').read_bytes()),
            }
            if canonical_after != canonical_before:
                raise ValueError('canonical build inputs changed during debug build')
            debug_manifest['canonical_inputs_after'] = canonical_after
        commit = subprocess.check_output(['git','rev-parse','HEAD'], cwd=ROOT, text=True).strip()
        manifest = dict(inputs, version=version, source_commit=commit,
                        source_clean=not bool(subprocess.check_output(
                            ['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip()),
                        build_id=build_id, source_sha256=source_sha256,
                        info_sha256=hashlib.sha256((bundle / 'Contents/Info.plist').read_bytes()).hexdigest(),
                        executable_sha256=hashlib.sha256(executable.read_bytes()).hexdigest(),
                        metal_execution_verified=False, verified_playable_games=0)
        if debug_manifest is not None:
            manifest['debug_symbols'] = debug_manifest
        output.mkdir(parents=True, exist_ok=True)
        archive = output / f'RaphaelGPU-{version}-experimental.zip'
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as package:
            for path in sorted(bundle.rglob('*')):
                if path.is_file(): package.write(path, path.relative_to(bundle.parent))
            for path in RELEASE_DOCUMENTS:
                package.write(ROOT / path, path)
            package.writestr('build-manifest.json', json.dumps(manifest, indent=2)+'\n')
        (output / 'SHA256SUMS').write_text(hashlib.sha256(archive.read_bytes()).hexdigest()+'  '+archive.name+'\n')
        if debug_manifest is not None:
            debug_dir = output / 'debug-symbols'
            shutil.copytree(dsym, debug_dir / 'RaphaelGPU.dSYM')
            shutil.copytree(source, debug_dir / 'source')
            shutil.copy2(build_script, debug_dir / 'build-kext-debug.sh')
            (debug_dir / 'debug-manifest.json').write_text(
                json.dumps(debug_manifest, indent=2) + '\n')
        print(archive)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--toolchain', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--debug-symbols', action='store_true',
                        help='build the deployed binary with -O2 -g -gdwarf-4 and retain its matching dSYM')
    args = parser.parse_args()
    build(args.toolchain.resolve(), args.output.resolve(), args.debug_symbols)
