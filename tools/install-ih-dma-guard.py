#!/usr/bin/env python3
"""Install reviewed DMA lifetime helpers while preserving local launcher edits."""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

TOOLS = Path(__file__).resolve().parent
SUPERVISOR_PREIMAGE = 'c297c0f4f53617064c6de433c474f59f8390e870d91bd1956a1345d0b936fe36'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def launcher_bytes(data):
    text = data.decode()
    for anchor, insertion in (
        ('    vf="-device vfio-pci,host=${GPU},bus=pcie.0,addr=0x6"\n',
         '    [[ "${GPU}" != 0000:7b:00.0 ]] || vf+=",x-rgpu-dma-guard=on"\n'),
        ('    -e "EXTRA=${EXTRA_QEMU}"\n',
         '    -e "RGPU_DMA_GUARD_SOCKET=${RGPU_DMA_GUARD_SOCKET:-}"\n')):
        if text.count(insertion) == 1:
            continue
        if insertion in text or text.count(anchor) != 1:
            raise ValueError('unreviewed launcher layout; merge DMA guard explicitly')
        text = text.replace(anchor, anchor + insertion)
    return text.encode()


def install(vm):
    vm = vm.resolve()
    with (vm/'run/experiment.lock').open('a') as experiment:
        fcntl.flock(experiment, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with (vm/'run/redeploy.lock').open('a') as media:
            fcntl.flock(media, fcntl.LOCK_EX | fcntl.LOCK_NB)
            active = subprocess.check_output(['docker', 'ps', '--format', '{{.Names}}'], text=True).splitlines()
            if any(n == 'macos-sequoia' or n.startswith('rgpu-launch-') for n in active):
                raise ValueError('a VM is active; refuse harness replacement')
            source = (TOOLS/'vm-supervision.py').read_bytes()
            current = (vm/'vm-supervision.py').read_bytes()
            if sha(current) not in (SUPERVISOR_PREIMAGE, sha(source)):
                raise ValueError('local supervisor edits require an explicit merge')
            changes = {name: (TOOLS/name).read_bytes() for name in
                       ('dma-guard.py', 'ih_dma.py', 'ih-vfio-recover.py', 'dma_engines.py')}
            changes['vm-supervision.py'] = source
            changes['macos-vm.sh'] = launcher_bytes((vm/'macos-vm.sh').read_bytes())
            changed = {name: data for name, data in changes.items()
                       if not (vm/name).exists() or (vm/name).read_bytes() != data}
            if not changed:
                return {'status': 'already-installed', 'sha256': {n: sha(d) for n, d in changes.items()}}
            backup = vm/'run'/('ih-harness-install-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ'))
            backup.mkdir(mode=0o700)
            before = {}
            for name in changed:
                if (vm/name).exists():
                    shutil.copy2(vm/name, backup/name)
                    before[name] = sha((vm/name).read_bytes())
                else:
                    before[name] = None
            plan = {'status': 'prepared', 'before': before,
                    'after': {n: sha(d) for n, d in changed.items()}}
            (backup/'receipt.json').write_text(json.dumps(plan, indent=2)+'\n')
            # Publish the capability-requiring launcher last. Old images then
            # refuse the unknown property before opening a VFIO device.
            for name, data in changed.items():
                path = vm/name
                temporary = path.with_name('.'+name+'.ih-install')
                with temporary.open('xb') as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                temporary.chmod(path.stat().st_mode & 0o777 if path.exists() else 0o755)
                temporary.replace(path)
            if any((vm/n).read_bytes() != data for n, data in changes.items()):
                raise ValueError('installed DMA guard bytes differ')
            plan.update(status='installed', backup=str(backup))
            (backup/'receipt.json').write_text(json.dumps(plan, indent=2)+'\n')
            return plan


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vm-dir', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(install(args.vm_dir), indent=2))
