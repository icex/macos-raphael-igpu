#!/usr/bin/env python3
"""Inspect the current GPU-less macOS guest; optionally shut it down and seal proof.

Never touches VFIO or permits a GPU launch itself. Root-agent commands are nonce-
revocable; collection uploads cannot replace existing observation artifacts.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]


def helper(name):
    spec = importlib.util.spec_from_file_location(name.replace('-','_'),ROOT/'tools'/f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def inspect_plain(vm):
    raw = subprocess.check_output(['docker','inspect','macos-sequoia'],text=True)
    info = json.loads(raw)[0]
    if not info['State']['Running']:
        raise ValueError('GPU-less guest is not running')
    if any('vfio' in device['PathOnHost'] for device in info['HostConfig'].get('Devices',[])):
        raise ValueError('compatibility inspection requires a GPU-less guest')
    mounted = [row['Source'] for row in info['Mounts']
               if row['Destination']=='/home/arch/OSX-KVM/mac_hdd_ng.img']
    if mounted != [str((vm/'mac_hdd_ng.img').resolve())]:
        raise ValueError('container system disk identity differs')
    script = ('from pathlib import Path; import json; '
              'print(json.dumps([p.read_bytes().decode(errors="replace") '
              'for p in Path("/proc").glob("[0-9]*/cmdline") '
              'if b"qemu-system" in p.read_bytes()]))')
    commands = json.loads(subprocess.check_output(['docker','exec',info['Id'],'python3','-c',script],text=True))
    qemu = [row for row in commands if row.split('\0')[0].endswith('qemu-system-x86_64')]
    if len(qemu)!=1 or 'vfio-pci' in qemu[0]:
        raise ValueError('expected exactly one GPU-less QEMU process')
    return info


def start_plain(vm):
    try:
        info = inspect_plain(vm)
        return info
    except subprocess.CalledProcessError:
        pass
    unit = 'rgpu-compat-plain-'+uuid.uuid4().hex[:12]
    subprocess.run(['systemd-run','--user','--unit='+unit,'--collect',
                    '--property=RuntimeMaxSec=6000','--working-directory='+str(vm),
                    'env','GPU=','GPU_ID=','GPU_ROM=','HDMI_AUDIO=off',
                    'GENERIC_GRAPHICS=on','VM_CONSOLE=off','AUDIO=none','GL=off',
                    'NAME=macos-sequoia',str(vm/'macos-vm.sh'),'run',
                    '--extra','-display none'],check=True)
    until=time.monotonic()+45
    while True:
        try:
            info=inspect_plain(vm)
            break
        except (subprocess.CalledProcessError, ValueError):
            if time.monotonic()>=until:
                raise ValueError('plain container failed to start')
            time.sleep(0.5)
    cid=info['Id']
    subprocess.run(['docker','cp',str(ROOT/'tools/agent-server.py'),cid+':/tmp/rgpu-compat-relay.py'],check=True)
    subprocess.run(['docker','exec','-d',cid,'python3','/tmp/rgpu-compat-relay.py'],check=True)
    subprocess.run(['docker','exec','-d','-w','/run/vm',cid,'python3','-m','http.server','8889'],check=True)
    return info


def capture(vm, stop=False):
    info = inspect_plain(vm)
    cid = info['Id']
    nonce = uuid.uuid4().hex
    permit = vm/'run'/('compat-permit-'+nonce)
    permit.write_text(nonce)
    source = vm/'run'/('compat-'+nonce+'-dump.c')
    probe_source = vm/'run'/('compat-'+nonce+'-probe.m')
    source.write_bytes((ROOT/'tools/dump-user-text.c').read_bytes())
    probe_bytes = (ROOT/'tests/desktop_metal_probe.m').read_bytes()
    probe_source.write_bytes(probe_bytes)
    receiver = '/tmp/rgpu-compat-artifact-'+nonce+'.py'
    subprocess.run(['docker','cp',str(ROOT/'tools/agent-server.py'),cid+':'+receiver],check=True)
    # The receiver's process is part of this exact plain container; never restart
    # the ordinary root-command relay to install an artifact endpoint.
    subprocess.run(['docker','exec','-d','-e','RGPU_AGENT_PORT=8891',
                    '-e','RGPU_ARTIFACT_ONLY=1',cid,'python3',receiver],check=True)
    tool = helper('metal-test')
    probe_digest = hashlib.sha256(probe_bytes).hexdigest()
    directory = '/var/tmp/rgpu-desktop-metal-'+probe_digest[:16]
    guest = '/var/tmp/rgpu-compat-'+nonce
    q = shlex.quote
    commands = [
        f'permit=$(curl -fsS --max-time 3 http://10.0.2.2:8889/compat-permit-{nonce})',
        f'test "$permit" = {q(nonce)}',
        'test "$(id -u)" = 0',
        f'mkdir -p {q(guest)} {q(directory)}',
        f'curl -fsS --max-time 5 http://10.0.2.2:8889/{source.name} > {guest}/dump.c',
        f'xcrun clang -O2 -Wall -Wextra -Werror {guest}/dump.c -o {guest}/dump',
        f'curl -fsS --max-time 5 http://10.0.2.2:8889/{probe_source.name} > {directory}/probe.m',
        f'xcrun clang -fobjc-arc -fblocks -O2 -Wall -Wextra -Werror '
        f'-framework Foundation -framework Metal -framework IOKit -framework CoreGraphics '
        f'-framework QuartzCore -framework AppKit -framework ImageIO '
        f'{directory}/probe.m -o {directory}/probe',
    ]
    for key, name in [('metaltext','AMDRadeonX6000MTLDriver'),('vatext','AMDRadeonVADriver2')]:
        path='/System/Library/Extensions/'+name+'.bundle/Contents/MacOS/'+name
        commands.append(f'{guest}/dump {q(path)} {guest}/{key}')
    paths = {'systemkc':'/System/Library/KernelCollections/SystemKernelExtensions.kc',
             'bootkc':'/System/Library/KernelCollections/BootKernelExtensions.kc',
             'metaltext':guest+'/metaltext','vatext':guest+'/vatext'}
    for key,path in paths.items():
        commands.append(f'curl -fsS --max-time 150 -X POST --data-binary @{q(path)} '
                        f'http://10.0.2.2:8891/artifact-upload/{nonce}/{key} > /dev/null')
    hashes = ' '.join('"$(shasum -a 256 '+q(path)+' | cut -d\" \" -f1)"'
                      for path in list(paths.values())+[directory+'/probe'])
    commands.append(f'printf "RGPU_COMPAT {nonce} %s %s %s %s %s %s %s %s\\n" '
                    f'"$(sw_vers -buildVersion)" "$(sw_vers -productVersion)" '
                    f'"$(sysctl -n kern.bootsessionuuid)" {hashes}')
    command='( '+ ' && '.join(commands)+f'; r=$?; printf "RGPU_EXIT {nonce} %s\\n" "$r" )'
    try:
        result=tool.run_guest_command(vm,command,nonce,dict(os.environ,GX_TIMEOUT='190'),
                                      timeout=195,execution_grace=0)
        (vm/'run'/('compat-'+nonce+'-output.txt')).write_text(result.stdout)
        fields=re.findall(r'^RGPU_COMPAT '+nonce+r' (\S+) (\S+) (\S+) '+
                          r'([a-f0-9]{64}) '*4+r'([a-f0-9]{64})$',result.stdout,re.M)
        if len(fields)!=1 or re.findall(r'^RGPU_EXIT '+nonce+r' (\d+)$',result.stdout,re.M)!=['0']:
            raise ValueError('current guest compatibility observation failed: '+result.stdout[-1000:])
        build,version,boot,system_sha,boot_sha,metal_sha,va_sha,binary_sha=fields[0]
        root = vm/'run/upload'/('compat-'+nonce)
        compatibility=helper('guest-compatibility')
        for key, expected in zip(paths,[system_sha,boot_sha,metal_sha,va_sha]):
            observed = compatibility.sha(root/key)
            if observed != expected:
                raise ValueError('live guest and uploaded image identity mismatch: '
                                 f'{key}, guest={expected}, received={observed}')
        guest_identity=dict(guest_build=build,guest_boot_uuid=boot,guest_uid=0,
                            probe_source_sha256=probe_digest,probe_binary_sha256=binary_sha)
        artifact=lambda key,digest: dict(path=str(root/key),sha256=digest)
        proof=dict(policy='dynamic-sites-v1',guest_version=version,observation_nonce=nonce,
                   kernel_catalog_sha256=compatibility.sha(ROOT/'findings/research/update-portability-20261013/kernel-sites.json'),
                   userspace_catalog_sha256=compatibility.sha(ROOT/'findings/research/update-portability-20261013/userspace-sites.json'),
                   system_collection=artifact('systemkc',system_sha),boot_collection=artifact('bootkc',boot_sha),
                   userspace_images={'AMDRadeonX6000MTLDriver':artifact('metaltext',metal_sha),
                                    'AMDRadeonVADriver2':artifact('vatext',va_sha)},
                   plain_container_id=cid,plain_started_at=info['State']['StartedAt'])
        guest_identity['compatibility']=proof
        if not stop:
            output=vm/'run'/('compat-'+nonce+'-unsealed.json')
            output.write_text(json.dumps(guest_identity,indent=2)+'\n')
            return dict(sealed=False,observation=str(output))
        # Verify image contracts before touching the plain guest's lifecycle.
        proof['disk_identity']=compatibility.disk_identity(vm/'mac_hdd_ng.img')
        compatibility.validate(vm,guest_identity,require_sealed=False)
        current=inspect_plain(vm)
        if current['Id']!=cid or current['State']['StartedAt']!=info['State']['StartedAt']:
            raise ValueError('plain guest container changed before shutdown')
        shutdown=helper('guest-shutdown')
        if shutdown.identify(vm,build)!=boot:
            raise ValueError('guest boot changed before shutdown')
        shutdown_nonce=uuid.uuid4().hex
        shutdown_permit=vm/'run'/('shutdown-permit-'+shutdown_nonce)
        shutdown_permit.write_text(shutdown_nonce)
        try:
            acknowledgement = nonce+' '+boot
            action=shutdown.guarded_action(
                '( printf %s '+q(acknowledgement)+
                f' | curl -fsS --max-time 5 -X POST --data-binary @- '
                f'http://10.0.2.2:8891/artifact-upload/{nonce}/shutdown >/dev/null '
                '&& /sbin/shutdown -h now )',shutdown_nonce,boot)
            try:
                subprocess.run([str(vm/'gx'),action],env=dict(os.environ,GX_TIMEOUT='10'),
                               capture_output=True,text=True,timeout=12,check=False)
            except subprocess.TimeoutExpired:
                pass  # Poweroff may close the relay before its final response.
            if (root/'shutdown').read_text() != acknowledgement:
                raise ValueError('native shutdown admission acknowledgement missing')
        finally:
            shutdown_permit.unlink(missing_ok=True)
        until=time.monotonic()+60
        while subprocess.run(['docker','inspect',cid],capture_output=True).returncode==0:
            if time.monotonic()>=until:
                raise ValueError('plain guest did not exit after native shutdown; proof not sealed')
            time.sleep(0.5)
        exit_code=shutdown.die_event_exit_code(shutdown.load_supervisor(),cid,
                                              {'started_at':info['State']['StartedAt']})
        if exit_code != 0:
            raise ValueError('plain guest exit was not successful; proof not sealed')
        proof['plain_shutdown']={'method':'native-request','exit_code':exit_code,
                                 'acknowledgement':acknowledgement}
        proof['disk_identity']=compatibility.disk_identity(vm/'mac_hdd_ng.img')
        proof['sealed']=True
        compatibility.validate(vm,guest_identity)
        path=vm/'run/guest-identity.json'
        if path.exists():
            (vm/'run'/('guest-identity-before-compat-'+nonce+'.json')).write_bytes(path.read_bytes())
        path.write_text(json.dumps(guest_identity,indent=2)+'\n')
        return dict(sealed=True,guest_build=build,identity=str(path),observation_nonce=nonce)
    finally:
        permit.unlink(missing_ok=True)
        source.unlink(missing_ok=True)
        probe_source.unlink(missing_ok=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vm-dir',type=Path,required=True)
    parser.add_argument('--stop-and-seal',action='store_true')
    parser.add_argument('--start-if-needed',action='store_true')
    args=parser.parse_args()
    vm=args.vm_dir.resolve()
    if args.start_if_needed:
        start_plain(vm)
    print(json.dumps(capture(vm,args.stop_and_seal),indent=2))


if __name__=='__main__':
    main()
