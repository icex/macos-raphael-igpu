#!/usr/bin/env python3
"""Software-only FD transfer experiment against the isolated c339 libvirt VM."""
import json
import os
from pathlib import Path
import secrets
import subprocess

RUN = Path.home()/'macos-vm/run'
URI = 'qemu+unix:///session?socket=' + str(RUN/'c339-libvirt-smoke/runtime/libvirt/libvirt-sock')
DOMAIN = 'rgpu-console-software-test'
CONTAINER = 'rgpu-console-libvirt-smoke'


def command(args, **kw):
    return subprocess.check_output(args, text=True, timeout=20, **kw)


def qmp(payload, fd=None):
    args = ['virsh', '-c', URI, 'qemu-monitor-command', DOMAIN]
    if fd is not None:
        args += ['--pass-fds', str(fd)]
    args += [json.dumps(payload)]
    result = json.loads(command(args, pass_fds=() if fd is None else (fd,)))
    if 'error' in result:
        raise RuntimeError(result['error'])
    return result['return']


live = json.loads(command(['docker', 'inspect', CONTAINER]))[0]
assert live['State']['Running'] and live['HostConfig']['NetworkMode'] == 'none'
assert not live['HostConfig']['Privileged'] and not live['HostConfig']['Devices']
assert command(['virsh', '-c', URI, 'domstate', DOMAIN]).strip() == 'paused'
# This test must never resolve to a host GPU or accelerated guest.
processes = command(['docker', 'top', CONTAINER, '-eo', 'pid,args'])
assert 'vfio-pci' not in processes and '/dev/kvm' not in processes
assert '-accel tcg' in processes
fd = os.memfd_create('rgpu-libvirt-fd-proof', os.MFD_CLOEXEC)
marker = secrets.token_hex(32)
os.write(fd, marker.encode())
os.lseek(fd, 0, os.SEEK_SET)
added = None
try:
    added = qmp({'execute': 'add-fd', 'arguments': {'opaque': 'rgpu-c341-fd-proof'}}, fd)
    sets = qmp({'execute': 'query-fdsets'})
    assert any(row['fdset-id'] == added['fdset-id'] and
               any(item['fd'] == added['fd'] and item['opaque'] == 'rgpu-c341-fd-proof'
                   for item in row['fds']) for row in sets)
    # Verify actual contents through QEMU's descriptor, independently of its QMP metadata.
    code = '''import json, pathlib, sys
pids=[]
for p in pathlib.Path('/proc').iterdir():
 if p.name.isdigit():
  try:
   cmd=(p/'cmdline').read_bytes().split(b'\\0')
   if cmd[0].endswith(b'/qemu-system-x86_64'):pids.append(p)
  except (OSError,IndexError):pass
assert len(pids)==1,pids
print((pids[0]/'fd'/sys.argv[1]).read_text())
'''
    observed = command(['docker', 'exec', CONTAINER, 'python3', '-c', code, str(added['fd'])]).strip()
    assert observed == marker
finally:
    if added is not None:
        qmp({'execute': 'remove-fd', 'arguments': {'fdset-id': added['fdset-id'], 'fd': added['fd']}})
    os.close(fd)
assert not any(row['fdset-id'] == added['fdset-id'] for row in qmp({'execute': 'query-fdsets'}))
result = {'passed': True, 'container_id': live['Id'], 'domain': DOMAIN,
          'transport': 'virsh qemu-monitor-command --pass-fds over local libvirt Unix socket',
          'exact_marker_bytes': len(marker), 'descriptor_removed': True,
          'physical_gpu_opened': False, 'kvm_opened': False,
          'scope': 'Regular memfd transfer and exact QEMU descriptor contents; not TAP network operation or macOS lifecycle'}
(RUN/'c341-libvirt-fd-result.json').write_text(json.dumps(result, indent=2)+'\n')
print(json.dumps(result))
