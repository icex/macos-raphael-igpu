#!/usr/bin/env python3
"""Read-only host macvtap provenance and inherited-descriptor verification.

Never opens a TAP/macvtap node or reopens a QEMU descriptor. The caller supplies
an already admitted descriptor. Linux reference238650ef: macvtap uses tap_fops,
which lacks generic tun's iff fdinfo, and minor number is not the ifindex.
"""
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import struct
import subprocess

TUNGETIFF=0x800454d2
SIOCGIFHWADDR=0x8927
BASE_FLAGS=0x1002 # IFF_TAP | IFF_NO_PI
ALLOWED_FLAGS=0x5002 # also IFF_VNET_HDR


def require(value,message):
    if not value:raise ValueError(message)


def character_identity(value):
    require(stat.S_ISCHR(value.st_mode),'descriptor is not a character device')
    return dict(major=os.major(value.st_rdev),minor=os.minor(value.st_rdev))


def capture_host(interface,guest_mac):
    require(re.fullmatch(r'[a-zA-Z0-9_.-]{1,15}',interface) is not None,'invalid interface name')
    require(re.fullmatch(r'(?:[0-9a-f]{2}:){5}[0-9a-f]{2}',guest_mac) is not None,'invalid guest MAC')
    rows=json.loads(subprocess.check_output(['ip','-d','-j','link','show','dev',interface],text=True,timeout=5))
    require(len(rows)==1,'host interface is not unique')
    info=rows[0];base=Path('/sys/class/net')/interface
    require(info['ifname']==interface and info['linkinfo']['info_kind']=='macvtap' and
            info['linkinfo']['info_data']['mode']=='bridge','unreviewed LAN interface kind/mode')
    index=int((base/'ifindex').read_text());lower_index=int((base/'iflink').read_text())
    mac=(base/'address').read_text().strip()
    require(index==info['ifindex'] and mac==info['address']==guest_mac,'host/guest LAN identity mismatch')
    require('UP' in info['flags'],'host LAN interface is down')
    lower_name=info['link']
    require(re.fullmatch(r'[a-zA-Z0-9_.-]{1,15}',lower_name) is not None,'invalid lower link')
    lower=Path('/sys/class/net')/lower_name
    require(int((lower/'ifindex').read_text())==lower_index,'lower interface identity mismatch')
    node=Path('/dev')/('tap'+str(index))
    identity=character_identity(node.stat()) # stat only, never open
    sysdev=(base/('tap'+str(index))/'dev').read_text().strip()
    require(sysdev==str(identity['major'])+':'+str(identity['minor']),'macvtap device-node mapping mismatch')
    ns=Path('/proc/self/ns/net').stat()
    return dict(schema=1,kind='macvtap',mode='bridge',name=interface,ifindex=index,mac=mac,
                lower=dict(name=lower_name,ifindex=lower_index,address=(lower/'address').read_text().strip()),
                netns=dict(device=ns.st_dev,inode=ns.st_ino),node=str(node),character=identity)


def verify_inherited(fd,receipt):
    require(receipt['schema']==1 and receipt['kind']=='macvtap' and receipt['mode']=='bridge',
            'unreviewed network receipt')
    value=os.fstat(fd)
    identity=character_identity(value)
    require(identity==receipt['character'],'inherited descriptor device mismatch')
    info=fcntl.ioctl(fd,TUNGETIFF,bytes(40))
    name=info[:16].split(b'\0',1)[0].decode('ascii')
    flags=struct.unpack_from('H',info,16)[0]
    require(name==receipt['name'],'inherited descriptor interface mismatch')
    require(flags&BASE_FLAGS==BASE_FLAGS and flags&~ALLOWED_FLAGS==0,'unreviewed TAP queue flags')
    address=fcntl.ioctl(fd,SIOCGIFHWADDR,bytes(40))
    actual_mac=':'.join(f'{octet:02x}' for octet in address[18:24])
    require(address[:16].split(b'\0',1)[0].decode('ascii')==name and
            struct.unpack_from('H',address,16)[0]==1 and actual_mac==receipt['mac'],
            'attached macvtap MAC mismatch')
    return dict(name=name,mac=actual_mac,flags=flags,character=identity,inode=value.st_ino,device=value.st_dev)


def verify_qemu_descriptor(pid,fd,inherited):
    # stat follows the proc descriptor link for metadata only. Opening it could
    # invoke macvtap open() and create another queue, so do not do that.
    value=Path(f'/proc/{pid}/fd/{fd}').stat()
    require(character_identity(value)==inherited['character'] and
            value.st_ino==inherited['inode'] and value.st_dev==inherited['device'],
            'QEMU descriptor differs from inherited device')
    return True


def verify_network_report(report,mac,hub=0):
    require(hub==0,'unreviewed LAN hub')
    lines=report.replace('\r','').splitlines()
    # Separate user-mode NAT line appears outside the LAN hub. Exact native
    # interface IDs ensure another NIC/backend cannot stand in for either one.
    expected_nic=' \\ lan0: lan0: index=0,type=nic,model=vmxnet3,macaddr='+mac
    starts=[i for i,line in enumerate(lines) if line=='hub 0']
    require(len(starts)==1,'LAN hub absent or duplicated')
    start=starts[0]
    require(start+2<len(lines),'incomplete LAN hub')
    members=lines[start+1:start+3]
    tap=[re.fullmatch(r' \\ rgpu_lan_attachment: rgpu_lan_backend: index=0,type=tap,fd=([0-9]+)',line)
         for line in members]
    selected=[match for match in tap if match is not None]
    require(len(selected)==1 and expected_nic in members,'LAN topology mismatch')
    require(start+3==len(lines) or not lines[start+3].startswith(' \\ '),'unexpected additional hub member')
    require(report.count('rgpu_lan_backend:')==1 and report.count('rgpu_lan_attachment:')==1,
            'duplicate LAN backend')
    return int(selected[0][1])
