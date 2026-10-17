#!/usr/bin/env python3
"""Paired PulseAudio initialization check: isolated TCG, no GPU/KVM/host NIC."""
import argparse
import json
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

IMAGE = 'sha256:3a3c82c79bc4e73531f819ccdfa4053b3084efd7c1f645678dbf8b4b3a24369c'
NS = 'http://libvirt.org/schemas/domain/qemu/1.0'
ET.register_namespace('qemu', NS)


def command(argv, timeout=20, check=True, **kwargs):
    return subprocess.run(argv, text=True, capture_output=True, timeout=timeout,
                          check=check, **kwargs)


def qemu_processes():
    found = []
    for path in Path('/proc').iterdir():
        if not path.name.isdigit():
            continue
        try:
            args = (path / 'cmdline').read_bytes().split(b'\0')
            if args and Path(os.fsdecode(args[0])).name.startswith('qemu-system'):
                stat = (path / 'stat').read_text().rsplit(')', 1)[1].split()
                found.append(dict(pid=int(path.name), start_ticks=int(stat[19])))
        except FileNotFoundError:
            pass
    return found


def xml_for(name, explicit_env):
    root = ET.fromstring(f'''<domain type="qemu" xmlns:qemu="{NS}">
<name>{name}</name><memory unit="MiB">128</memory><vcpu>1</vcpu>
<os><type arch="x86_64" machine="pc-q35-10.1">hvm</type></os>
<on_poweroff>destroy</on_poweroff><on_reboot>destroy</on_reboot><on_crash>destroy</on_crash>
<devices><emulator>/usr/sbin/qemu-system-x86_64</emulator>
<controller type="usb" model="none"/><memballoon model="none"/>
<video><model type="none"/></video><audio id="1" type="none"/>
<watchdog model="itco" action="none"/>
<graphics type="spice"><listen type="socket" socket="/run/rgpu-study/{name}.spice"/>
<image compression="off"/><gl enable="no"/></graphics></devices>
<qemu:commandline/></domain>''')
    cmd = root.find('{' + NS + '}commandline')
    for arg in ['-vga', 'none', '-display', 'none', '-device', 'qemu-xhci,id=xhci',
                '-device', 'usb-audio,audiodev=hda,bus=xhci.0', '-audiodev', 'pa,id=hda']:
        ET.SubElement(cmd, '{' + NS + '}arg', value=arg)
    if explicit_env:
        ET.SubElement(cmd, '{' + NS + '}env', name='XDG_RUNTIME_DIR', value='/xdgrt')
    return ET.tostring(root, encoding='unicode')


def inside():
    root = Path('/run/rgpu-study')
    runtime = root / 'runtime'
    runtime.mkdir(mode=0o700)
    os.environ['XDG_RUNTIME_DIR'] = str(runtime)
    daemon_pid = None
    active = None
    results = []

    def virsh(*args, **kwargs):
        return command(['virsh', '-c', 'qemu:///session', *args], **kwargs)

    try:
        command(['libvirtd', '--daemon'])
        daemon_pid = int((runtime / 'libvirt/libvirtd.pid').read_text())
        for explicit in (False, True):
            label = 'explicit-env' if explicit else 'missing-env'
            name = 'rgpu-pa-' + label
            path = root / (label + '.xml')
            path.write_text(xml_for(name, explicit))
            active = name
            result = virsh('create', '--paused', str(path), check=False, timeout=60)
            (root / (label + '.stdout')).write_text(result.stdout)
            (root / (label + '.stderr')).write_text(result.stderr)
            if not explicit:
                assert result.returncode != 0 and 'XDG_RUNTIME_DIR not set' in result.stderr
                assert not virsh('list', '--all', '--name').stdout.strip()
                assert not qemu_processes()
                results.append(dict(case=label, refused=True, expected_error='XDG_RUNTIME_DIR not set',
                                    domain_absent=True, qemu_absent=True))
                active = None
                continue
            assert result.returncode == 0, result.stderr
            response = json.loads(virsh('qemu-monitor-command', name,
                                      json.dumps({'execute': 'query-status'})).stdout)
            status = response['return']
            assert status['running'] is False and status['status'] in ('paused', 'prelaunch')
            processes = qemu_processes()
            assert len(processes) == 1
            identity = processes[0]
            raw = Path(f"/proc/{identity['pid']}/environ").read_bytes().split(b'\0')
            selected = [value.decode() for value in raw if value.startswith(b'XDG_RUNTIME_DIR=')]
            assert selected == ['XDG_RUNTIME_DIR=/xdgrt']
            assert os.environ['XDG_RUNTIME_DIR'] == str(runtime)
            virsh('destroy', name)
            until = time.monotonic() + 5
            while qemu_processes() and time.monotonic() < until:
                time.sleep(.05)
            assert not qemu_processes() and not virsh('list', '--all', '--name').stdout.strip()
            active = None
            results.append(dict(case=label, initialized=True, status=status, identity=identity,
                                qemu_runtime='/xdgrt', controller_runtime=str(runtime),
                                qemu_absent_after_destroy=True, domain_absent=True))
        payload = dict(passed=True, cases=results,
                       scope='PulseAudio backend initialization with USB audio and SPICE; TCG paused, '
                             'no guest OS, playback, KVM, VFIO or host NIC.')
        (root / 'result.json').write_text(json.dumps(payload, indent=2) + '\n')
        print(json.dumps(payload))
    finally:
        if active is not None:
            virsh('destroy', active, check=False)
        if daemon_pid is not None:
            try:
                os.kill(daemon_pid, signal.SIGTERM)
            except ProcessLookupError:
                pass


def host():
    suffix = secrets.token_hex(4)
    root = Path.home() / 'macos-vm/run' / ('c341-audio-env-' + suffix)
    root.mkdir(mode=0o700)
    name = 'rgpu-c341-audio-env-' + suffix
    cid = None
    try:
        cid = command(['docker', 'run', '-d', '--init', '--name', name,
                       '--network', 'none', '--cap-drop', 'ALL', '--user', f'{os.getuid()}:{os.getgid()}',
                       '-v', str(root) + ':/run/rgpu-study',
                       '-v', str(Path(__file__).resolve()) + ':/study.py:ro',
                       '-v', str(Path.home() / 'macos-vm/xdg') + ':/xdgrt:ro',
                       '-v', f'/run/user/{os.getuid()}/pulse:/xdgrt/pulse:ro',
                       '--entrypoint', 'python3', IMAGE, '-B', '/study.py', '--inside']).stdout.strip()
        info = json.loads(command(['docker', 'inspect', cid]).stdout)[0]
        assert info['Image'] == IMAGE and not info['HostConfig']['Privileged']
        assert not info['HostConfig']['Devices'] and info['HostConfig']['NetworkMode'] == 'none'
        exit_code = int(command(['docker', 'wait', cid], timeout=100).stdout.strip())
        logs = command(['docker', 'logs', cid])
        (root / 'container.stdout').write_text(logs.stdout)
        (root / 'container.stderr').write_text(logs.stderr)
        final = json.loads(command(['docker', 'inspect', cid]).stdout)[0]
        receipt = dict(cid=cid, image=info['Image'], started_at=final['State']['StartedAt'],
                       finished_at=final['State']['FinishedAt'], exit_code=exit_code,
                       running=final['State']['Running'], name=name)
        (root / 'container.json').write_text(json.dumps(receipt, indent=2) + '\n')
        assert exit_code == 0 and final['State']['Running'] is False
        assert json.loads((root / 'result.json').read_text())['passed'] is True
        print(json.dumps(dict(artifacts=str(root), **receipt)))
    finally:
        if cid:
            command(['docker', 'stop', '--time', '5', cid], timeout=15, check=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inside', action='store_true')
    args = parser.parse_args()
    inside() if args.inside else host()
