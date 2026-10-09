#!/usr/bin/env python3
"""Offline398 preparation; only approved independent clone paths."""
import copy
import hashlib
import json
import os
from pathlib import Path
import plistlib
import subprocess

COMMENT = 'Raphael: QEMU SMC ACPI handoff to VirtualSMC'
FIND = bytes.fromhex('534d435f085f4849440c06100001085f5354410a0b')
REPLACE = bytes.fromhex('534d435f085f4849440c06100001085f5354410a00')


def patch(original):
    new = copy.deepcopy(original)
    smc = [v for v in new['Kernel']['Add'] if v['BundlePath'] == 'VirtualSMC.kext']
    acpi = [v for v in new['ACPI']['Patch'] if v['Comment'] == COMMENT]
    if len(smc) != 1 or not smc[0]['Enabled'] or len(acpi) != 1:
        raise ValueError('unexpected SMC entries')
    item = acpi[0]
    if not item['Enabled'] or item['Find'] != FIND or item['Replace'] != REPLACE or item['TableSignature'] != b'DSDT' or item['Count'] != 1:
        raise ValueError('unexpected ACPI patch')
    smc[0]['Enabled'] = False
    item['Enabled'] = False
    entries = [v for v in new['NVRAM']['Add'].values() if 'boot-args' in v]
    if len(entries) != 1 or not isinstance(entries[0]['boot-args'], str):
        raise ValueError('ambiguous boot arguments')
    tokens = entries[0]['boot-args'].split()
    if tokens.count('vsmcgen=2') != 1 or '-rgpuoff' in tokens:
        raise ValueError('unexpected original boot arguments')
    entries[0]['boot-args'] = ' '.join([t for t in tokens if t != 'vsmcgen=2'] + ['-rgpuoff'])
    # Compare reconstructed reverse edit: all identity and unrelated values retained.
    check = copy.deepcopy(new)
    next(v for v in check['Kernel']['Add'] if v['BundlePath'] == 'VirtualSMC.kext')['Enabled'] = True
    next(v for v in check['ACPI']['Patch'] if v['Comment'] == COMMENT)['Enabled'] = True
    for key, val in original['NVRAM']['Add'].items():
        if 'boot-args' in val:
            check['NVRAM']['Add'][key]['boot-args'] = val['boot-args']
    if check != original:
        raise ValueError('unapproved configuration change')
    return new


def main():
    os.umask(0o077)
    r = Path('/home/bogdan/macos-vm/run/c398-vbox-clones')
    receipt = json.loads((r / 'conversion.json').read_text())
    if len(receipt) != 2 or any(not x['source_unchanged'] or x['compare_returncode'] for x in receipt):
        raise ValueError('baseline conversion unverified')
    for name in ('OpenCore', 'mac_hdd_ng'):
        if (r/(name+'-boot.vdi')).exists():
            raise ValueError('derivative already exists')
    for name in ('OpenCore', 'mac_hdd_ng'):
        subprocess.run(['cp', '--reflink=always', '--no-clobber', str(r/(name+'.vdi')), str(r/(name+'-boot.vdi'))], check=True)
        # Refuse an earlier derivative rather than overwriting it.
    private = r/'config-private.plist'
    new = patch(plistlib.loads(private.read_bytes()))
    target = r/'config-boot-private.plist'
    with target.open('xb') as f:
        plistlib.dump(new, f, sort_keys=False)
    raw = r/'OpenCore-boot.raw'
    if raw.exists():
        raise ValueError('derivative already exists')
    subprocess.run(['cp','--reflink=always',str(r/'OpenCore-inspect.raw'),str(raw)],check=True)
    subprocess.run(['mcopy','-o','-i',str(raw)+'@@1048576',str(target),'::/EFI/OC/config.plist'],check=True)
    subprocess.run(['qemu-io','-f','vdi','-c',f'write -q -s {raw} 0 {raw.stat().st_size}',str(r/'OpenCore-boot.vdi')],check=True,capture_output=True)
    subprocess.run(['qemu-img','compare','-f','raw','-F','vdi',str(raw),str(r/'OpenCore-boot.vdi')],check=True,capture_output=True)
    result = {'changes':['VirtualSMC Enabled false','exact QEMU SMC ACPI patch Enabled false','remove vsmcgen=2; append -rgpuoff'],
              'original_config_sha256':hashlib.sha256(private.read_bytes()).hexdigest(),
              'derivative_config_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
              'identity_and_other_fields_unchanged':True,'original_baselines_written':False}
    (r/'loader-preparation.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
