#!/usr/bin/env python3
"""Valid TAP and lifecycle proof in a device-isolated TCG container, not macOS."""
import array
import fcntl
import importlib.util
import json
import os
import re
from pathlib import Path
import secrets
import socket
import struct
import subprocess
import time

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('failure_smoke',HERE/'libvirt-runtime-failure-smoke-20261009.py')
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
base.RUN=Path.home()/'macos-vm/run/c341-tap-smoke'
base.CONTAINER='rgpu-c341-tap-smoke'
base.URI='qemu+unix:///session?socket='+str(base.RUN/'runtime/libvirt/libvirt-sock')

TAP_HELPER='''import array,fcntl,os,socket,struct,subprocess
fd=os.open('/dev/net/tun',os.O_RDWR)
ifr=fcntl.ioctl(fd,0x400454ca,struct.pack('16sH',b'rgpu_tap',0x1002))
subprocess.run(['ip','link','set','rgpu_tap','up'],check=True)
s=socket.socket(socket.AF_UNIX);s.connect('/run/rgpu-libvirt/fd.sock')
s.sendmsg([ifr[:16]],[(socket.SOL_SOCKET,socket.SCM_RIGHTS,array.array('i',[fd]))])
os.close(fd);s.close()
'''


class TapBackend(base.SoftwareBackend):
    def container_identity(self):
        item=json.loads(base.command(['docker','inspect',base.CONTAINER]))[0]
        assert item['State']['Running'] and not item['HostConfig']['Privileged']
        assert item['HostConfig']['NetworkMode']=='none'
        assert item['HostConfig']['CapAdd']==['CAP_NET_ADMIN']
        devices=item['HostConfig']['Devices']
        assert len(devices)==1 and devices[0]['PathOnHost']==devices[0]['PathInContainer']=='/dev/net/tun'
        return dict(cid=item['Id'],started_at=item['State']['StartedAt'])

    def network_attached(self,name,hub):
        report=self.qmp(name,'human-monitor-command',{'command-line':'info network'})
        (base.RUN/'network.txt').write_text(report)
        # This exact report is specific to the isolated single-NIC test.
        match=re.fullmatch(r'hub 0\n \\ rgpu_lan_attachment: rgpu_lan_backend: index=0,type=tap,fd=(\d+)\n \\ lan0: lan: index=0,type=nic,model=vmxnet3,macaddr=52:54:00:12:34:56\n',report.replace('\r',''))
        if match is None:return False
        pids=self.processes();assert len(pids)==1
        info=Path(f'/proc/{pids[0]}/fdinfo/{match.group(1)}').read_text()
        (base.RUN/'tap-fdinfo.txt').write_text(info)
        return re.search(r'^iff:\s+rgpu_tap$',info,re.M) is not None


def tap_fd():
    path=base.RUN/'fd.sock';path.unlink(missing_ok=True)
    server=socket.socket(socket.AF_UNIX);server.bind(str(path));server.listen(1);server.settimeout(10)
    helper=subprocess.Popen(['docker','exec','--user','0',base.CONTAINER,'python3','-c',TAP_HELPER],
                             stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    try:
        client,_=server.accept()
        with client:
            data,anc,flags,_=client.recvmsg(16,socket.CMSG_SPACE(array.array('i').itemsize))
        out,err=helper.communicate(timeout=10);assert helper.returncode==0,(out,err)
        assert not flags and data.rstrip(b'\0')==b'rgpu_tap'
        rights=[value for level,kind,value in anc if level==socket.SOL_SOCKET and kind==socket.SCM_RIGHTS]
        assert len(rights)==1
        fds=array.array('i');fds.frombytes(rights[0]);assert len(fds)==1
        fd=fds[0]
        info=fcntl.ioctl(fd,0x800454d2,bytes(40)) # TUNGETIFF
        assert info[:16].rstrip(b'\0')==b'rgpu_tap'
        assert struct.unpack_from('H',info,16)[0]&0x1002==0x1002
        return fd
    finally:
        server.close();path.unlink(missing_ok=True)
        if helper.poll() is None:
            helper.terminate();helper.communicate(timeout=5)


def main():
    backend=TapBackend();plan=base.plan();backend.plan=plan
    owner=base.runtime.PausedDomain(backend,plan,base.runtime.digest(plan),backend.expected,
                                  lambda p,s:s['argv'].count('-accel')==1)
    fd=tap_fd();result=None
    try:
        owner.prepare(fd)
        assert not owner.resume_attempted
        owner.resume()
        backend.qmp(plan['domain_name'],'object-add',{'qom-type':'filter-dump','id':'proof_capture',
                    'netdev':'rgpu_lan_backend','file':'/run/rgpu-libvirt/tap-packet.pcap'})
        packet=bytes.fromhex('ffffffffffff52540034100288b5')+secrets.token_bytes(46)
        sender="import socket;s=socket.socket(socket.AF_PACKET,socket.SOCK_RAW);s.bind(('rgpu_tap',0));assert s.send(bytes.fromhex('"+packet.hex()+"'))==60;s.close()"
        base.command(['docker','exec','--user','0',base.CONTAINER,'python3','-c',sender])
        deadline=time.monotonic()+5;records=[]
        while time.monotonic()<deadline:
            data=(base.RUN/'tap-packet.pcap').read_bytes()
            if len(data)>=24:
                endian='<' if data[:4]==bytes.fromhex('d4c3b2a1') else '>'
                offset=24;records=[]
                while offset+16<=len(data):
                    _,_,size,_=struct.unpack_from(endian+'IIII',data,offset)
                    records.append(data[offset+16:offset+16+size]);offset+=16+size
                if packet in records:break
            time.sleep(.05)
        assert packet in records,'packet not delivered to QEMU TAP backend'
        backend.virsh('destroy',plan['domain_name']) # manager Force Off equivalent
        deadline=time.monotonic()+5
        while not backend.process_gone(owner.identity) and time.monotonic()<deadline:time.sleep(.05)
        owner.cleanup('manager-force-off');owner.cleanup('duplicate-stop')
        assert owner.finished and not backend.domains() and backend.session_processes_gone()
        result=dict(passed=True,container=backend.expected,identity=owner.identity,
                    phases=[e['phase'] for e in owner.events],tap_frame_exact=True,
                    packet_sha256=__import__('hashlib').sha256(packet).hexdigest(),
                    domain_absent=True,process_exited=True,duplicate_stop_safe=True,
                    scope='Isolated TCG TAP injection, backend packet capture and external libvirt destroy; no guest OS, host NIC, KVM or VFIO.')
        (base.RUN/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
    finally:
        if not owner.finished:owner.cleanup('test-finally')
        os.close(fd)

if __name__=='__main__':main()
