#!/usr/bin/env python3
"""Software-only socket network transfer experiment against the isolated c339 libvirt VM."""
import json
import os
from pathlib import Path
import secrets
import socket
import struct
import time
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

left, right = socket.socketpair()
net_created = filter_created = False
capture = RUN/'c339-libvirt-smoke/c341-packet.pcap'
try:
    qmp({'execute':'getfd','arguments':{'fdname':'rgpu-net-proof'}}, left.fileno())
    qmp({'execute':'netdev_add','arguments':{'type':'socket','id':'rgpu_net_proof','fd':'rgpu-net-proof'}})
    net_created = True
    qmp({'execute':'netdev_add','arguments':{'type':'hubport','id':'rgpu_host_port','hubid':341,'netdev':'rgpu_net_proof'}})
    qmp({'execute':'object-add','arguments':{'qom-type':'filter-dump','id':'rgpu_dump_proof','netdev':'rgpu_net_proof','file':'/run/rgpu-libvirt/c341-packet.pcap'}})
    filter_created = True
    # Reserved experimental EtherType, local socket pair only, no host NIC access.
    packet = bytes.fromhex('52540034100152540034100288b5') + secrets.token_bytes(46)
    qmp({'execute':'cont'})
    right.sendall(struct.pack('!I',len(packet))+packet)
    deadline = time.monotonic()+5
    while time.monotonic()<deadline:
        data=capture.read_bytes()
        if packet in data:break
        time.sleep(.1)
    assert data[:4] in (bytes.fromhex('d4c3b2a1'),bytes.fromhex('a1b2c3d4'))
    endian = '<' if data[:4] == bytes.fromhex('d4c3b2a1') else '>'
    records=[];offset=24
    while offset+16<=len(data):
        _,_,included,original=struct.unpack_from(endian+'IIII',data,offset)
        records.append(data[offset+16:offset+16+included]);offset+=16+included
    assert packet in records
finally:
    qmp({'execute':'stop'})
    if filter_created:qmp({'execute':'object-del','arguments':{'id':'rgpu_dump_proof'}})
    if net_created:
        qmp({'execute':'netdev_del','arguments':{'id':'rgpu_host_port'}})
        qmp({'execute':'netdev_del','arguments':{'id':'rgpu_net_proof'}})
    left.close();right.close()
result={'passed':True,'container_id':live['Id'],'domain':DOMAIN,'packet_bytes':len(packet),
        'exact_packet_found':True,'packet_sha256':__import__('hashlib').sha256(packet).hexdigest(),
        'backend_removed':True,'scope':'Socket FD passed through libvirt getfd and consumed by QEMU netdev_add; exact frame captured before emulated vmxnet3. No real TAP, external network, KVM, GPU or macOS.'}
(RUN/'c341-libvirt-socket-result.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
