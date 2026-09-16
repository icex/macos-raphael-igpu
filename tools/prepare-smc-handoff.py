#!/usr/bin/env python3
"""Prepare a private OpenCore config for VirtualSMC ownership on QEMU.

Does not install a kext, modify the source config, or launch a VM. The exact QEMU
SMC device prefix must occur once in a supplied DSDT. Keep QEMU isa-applesmc for
boot-time key access; suppress its ACPI enumeration so VirtualSMC owns AppleSMC.
Native boot, provider identity and enumeration must still be verified.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import plistlib
import struct

BOOT_GUID = '7C436110-AB2A-4BBB-A880-FE41995C9F82'
# NameSeg SMC_; Name(_HID, EisaId("APP0001")); Name(_STA, Byte(0x0b)).
FIND = bytes.fromhex('534d435f085f4849440c06100001085f5354410a0b')
REPLACE = FIND[:-1] + b'\x00'
COMMENT = 'Raphael: QEMU SMC ACPI handoff to VirtualSMC'


def prepare(config, dsdt):
    if len(dsdt) < 36 or dsdt[:4] != b'DSDT':
        raise ValueError('input must be one DSDT table')
    if struct.unpack_from('<I', dsdt, 4)[0] != len(dsdt):
        raise ValueError('DSDT length does not match header')
    if dsdt[36:].count(FIND) != 1:
        raise ValueError('expected exactly one reviewed QEMU SMC device prefix')
    result = copy.deepcopy(config)
    additions = result['Kernel']['Add']
    smc = [item for item in additions if item.get('BundlePath') == 'VirtualSMC.kext']
    lilu = [item for item in additions if item.get('BundlePath') == 'Lilu.kext' and item.get('Enabled')]
    if len(smc) != 1 or len(lilu) != 1 or additions.index(lilu[0]) >= additions.index(smc[0]):
        raise ValueError('one VirtualSMC entry must follow enabled Lilu')
    if smc[0].get('ExecutablePath') != 'Contents/MacOS/VirtualSMC':
        raise ValueError('unexpected VirtualSMC executable path')
    words = result['NVRAM']['Add'][BOOT_GUID]['boot-args'].split()
    if any(word in ('-vsmcoff', '-vsmccomp') for word in words):
        raise ValueError('VirtualSMC disabled or hardware preference requested')
    if any(word.startswith('vsmcgen=') and word != 'vsmcgen=2' for word in words):
        raise ValueError('conflicting VirtualSMC generation')
    patches = result['ACPI']['Patch']
    if any(item.get('Comment') == COMMENT or item.get('Find') in (FIND, REPLACE) for item in patches):
        raise ValueError('SMC handoff already configured')
    smc[0]['Enabled'] = True
    if 'vsmcgen=2' not in words:
        words.append('vsmcgen=2')
    result['NVRAM']['Add'][BOOT_GUID]['boot-args'] = ' '.join(words)
    patches.append(dict(Base='', BaseSkip=0, Comment=COMMENT, Count=1, Enabled=True,
                        Find=FIND, Limit=0, Mask=b'', OemTableId=b'', Replace=REPLACE,
                        ReplaceMask=b'', Skip=0, TableLength=0, TableSignature=b'DSDT'))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--dsdt', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raw = args.config.read_bytes()
    if args.output.resolve() == args.config.resolve():
        parser.error('output must differ from source config')
    start = raw.index(b'<?xml') if not raw.startswith(b'bplist') else 0
    dsdt = args.dsdt.read_bytes()
    result = prepare(plistlib.loads(raw[start:]), dsdt)
    # Refuse overwrite and protect platform identifiers in the private output.
    import os
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(plistlib.dumps(result))
    print(json.dumps({'source_config_sha256': hashlib.sha256(raw).hexdigest(),
                      'dsdt_sha256': hashlib.sha256(dsdt).hexdigest(),
                      'output_config_sha256': hashlib.sha256(args.output.read_bytes()).hexdigest(),
                      'patch_matches': 1, 'virtualsmc_generation': 2,
                      'native_validation': 'pending'}))


if __name__ == '__main__':
    main()
