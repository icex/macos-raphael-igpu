#!/usr/bin/env python3
"""Prepare a transient libvirt console domain; never launch or open a GPU.

Input is the fully expanded, reviewed QEMU argument vector (without executable).
The caller must still perform normal experiment admission before creating this
transient domain paused, transfer the LAN descriptor, validate it, and resume.
"""
import argparse
import json
import os
from pathlib import Path
import re
import xml.etree.ElementTree as ET

NS = 'http://libvirt.org/schemas/domain/qemu/1.0'
ET.register_namespace('qemu', NS)
CPU = 'Haswell-noTSX,kvm=on,vendor=GenuineIntel,+invtsc,vmware-cpuid-freq=on'
SPICE = 'unix=on,addr=/run/vm/console-spice.sock,disable-ticketing=on,image-compression=off,gl=off'
VFIO = 'vfio-pci,host=0000:7b:00.0,bus=pcie.0,addr=0x6,x-pci-vendor-id=0x1002,x-pci-device-id=0x73ff,romfile=/run/vm/gpu.rom'
BOCHS = 'bochs-display,id=rgpu_present,bus=pcie.0,addr=0x7,vgamem=64M'
PAIR_OPTIONS = {'-m', '-cpu', '-machine', '-smp', '-device', '-drive', '-smbios',
                '-audiodev', '-netdev', '-monitor', '-boot', '-vga', '-display',
                '-chardev', '-gdb', '-spice', '-mon'}
OWNED = {'-m', '-cpu', '-machine', '-smp', '-spice'}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def pairs(argv):
    require(type(argv) is list and len(argv) % 2 == 0, 'expected paired QEMU arguments')
    result = []
    for option, value in zip(argv[::2], argv[1::2]):
        require(option in PAIR_OPTIONS and isinstance(value, str) and value and
                not any(c in value for c in '\x00\n\r'), 'unknown or malformed QEMU option')
        result.append((option, value))
    return result


def values(rows, option):
    return [value for key, value in rows if key == option]


def one(rows, option):
    selected = values(rows, option)
    require(len(selected) == 1, f'expected exactly one {option}')
    return selected[0]


def build_plan(argv, run_id):
    require(isinstance(run_id, str) and re.fullmatch('[0-9a-f]{32}', run_id), 'invalid run identity')
    rows = pairs(argv)
    require(one(rows, '-cpu') == CPU, 'unreviewed CPU profile')
    require(one(rows, '-machine') in ('q35,accel=kvm:tcg', 'q35,accel=kvm'), 'unreviewed machine')
    memory = one(rows, '-m')
    require(memory.isdigit() and 128 <= int(memory) <= 262144, 'invalid memory size')
    match = re.fullmatch(r'([1-9][0-9]*),sockets=1,cores=\1,threads=1', one(rows, '-smp'))
    require(match is not None and int(match[1]) <= 64, 'unreviewed CPU topology')
    cores = match[1]
    spice = one(rows, '-spice')
    require(spice in (SPICE, SPICE+',max-refresh-rate=60') and one(rows, '-vga') == 'none' and
            one(rows, '-display') == 'none', 'unreviewed console profile')
    require(one(rows, '-audiodev') == 'pa,id=hda', 'unreviewed audio backend')
    require(one(rows, '-smbios') == 'type=2' and one(rows, '-boot') == 'menu=on', 'unreviewed boot profile')
    require(values(rows, '-monitor') == ['stdio'] and
            one(rows, '-mon') == 'chardev=mon1,mode=readline',
            'unreviewed HMP monitor profile')
    require(one(rows, '-gdb') == 'tcp:0.0.0.0:1234', 'unreviewed debugger profile')
    devices = values(rows, '-device')
    bochs = [d for d in devices if d.split(',')[0] == 'bochs-display']
    require(len(bochs) == 1 and bochs[0] in (BOCHS, BOCHS+',x-debug-full-refresh=on',
            BOCHS+',x-debug-full-refresh=on,x-debug-snapshot=on'),
            'unreviewed Bochs full refresh profile')
    require(bochs[0] == BOCHS or spice == SPICE+',max-refresh-rate=60',
            'full refresh requires explicit SPICE60')
    expected = ['qemu-xhci,id=xhci', 'usb-kbd,bus=xhci.0', 'usb-tablet,bus=xhci.0',
                'usb-audio,audiodev=hda,bus=xhci.0', 'ich9-ahci,id=sata',
                'ide-hd,bus=sata.2,drive=OpenCoreBoot', 'ide-hd,bus=sata.4,drive=MacHDD',
                VFIO, bochs[0], 'isa-serial,chardev=rgpu_console,index=0',
                'isa-serial,chardev=rgpu_critical,index=1']
    for device in expected:
        require(devices.count(device) == 1, 'missing or duplicate reviewed device')
    extras = [d for d in devices if d not in expected]
    require(len(extras) == 3, 'unexpected additional devices')
    require(sum(bool(re.fullmatch(r'isa-applesmc,osk=[A-Za-z0-9 ()]{64}', d)) for d in extras) == 1,
            'invalid AppleSMC configuration')
    for net in ('net0', 'lan0'):
        require(sum(bool(re.fullmatch(r'vmxnet3,netdev='+net+',id='+net+r',mac=(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', d))
                    for d in extras) == 1, 'invalid network device')
    ordered_models = ['qemu-xhci', 'usb-kbd', 'usb-tablet', 'isa-applesmc',
                      'usb-audio', 'ich9-ahci', 'ide-hd', 'ide-hd', 'vmxnet3',
                      'vfio-pci', 'isa-serial', 'isa-serial', 'bochs-display', 'vmxnet3']
    require([d.split(',')[0] for d in devices] == ordered_models,
            'device order would change automatic PCI assignment')
    require('netdev=net0,' in devices[8] and 'netdev=lan0,' in devices[13] and
            devices[6] == 'ide-hd,bus=sata.2,drive=OpenCoreBoot' and
            devices[7] == 'ide-hd,bus=sata.4,drive=MacHDD', 'changed device order')
    require(sorted(values(rows, '-chardev')) == sorted([
        'socket,id=rgpu_console,path=/run/vm/serial.sock,server=on,wait=off',
        'socket,id=rgpu_critical,path=/run/vm/critical.sock,server=on,wait=off',
        'socket,id=mon1,path=/run/vm/monitor.sock,server=on,wait=off']), 'invalid capture channels')
    require(sorted(values(rows, '-netdev')) == sorted([
        'user,id=net0,hostfwd=tcp::10022-:22,hostfwd=tcp::5900-:5900,',
        'tap,id=lan0,fd=3']), 'unreviewed network backends')
    drives = values(rows, '-drive')
    require(len(drives) == 4, 'unexpected storage topology')
    expected_drives = [
        'if=pflash,format=raw,readonly=on,file=/home/arch/OSX-KVM/OVMF_CODE.fd',
        'if=pflash,format=raw,file=/home/arch/OSX-KVM/OVMF_VARS.fd',
        'id=OpenCoreBoot,if=none,snapshot=on,format=qcow2,file=/home/arch/OSX-KVM/OpenCore/OpenCore.qcow2',
        'id=MacHDD,if=none,file=/home/arch/OSX-KVM/mac_hdd_ng.img,format=qcow2']
    require(drives == expected_drives, 'unreviewed storage configuration')

    root = ET.Element('domain', {'type': 'kvm'})
    def element(parent, tag, text=None, **attrs):
        node = ET.SubElement(parent, tag, attrs)
        node.text = text
        return node
    element(root, 'name', 'rgpu-'+run_id)
    # libvirt11.9 treats zero hwuuid as absent, so use the native zero UUID
    # for the domain itself. Ownership MUST also bind name, metadata, PID/start
    # and container identity, never UUID alone. A preexisting domain refuses.
    element(root, 'uuid', '00000000-0000-0000-0000-000000000000')
    metadata = element(root, 'metadata')
    element(metadata, '{urn:raphaelgpu:experiment}run', id=run_id)
    element(root, 'memory', memory, unit='MiB')
    element(root, 'vcpu', cores, placement='static')
    os_node = element(root, 'os')
    element(os_node, 'type', 'hvm', arch='x86_64', machine='pc-q35-10.1')
    features = element(root, 'features')
    element(features, 'acpi'); element(features, 'apic')
    cpu = element(root, 'cpu', mode='custom', match='exact', check='none')
    element(cpu, 'model', 'Haswell-noTSX', fallback='forbid', vendor_id='GenuineIntel')
    element(cpu, 'topology', sockets='1', dies='1', cores=cores, threads='1')
    element(cpu, 'feature', policy='require', name='invtsc')
    element(root, 'clock', offset='utc')
    for event in ('on_poweroff', 'on_reboot', 'on_crash'):
        element(root, event, 'destroy')
    dev = element(root, 'devices')
    element(dev, 'emulator', '/usr/sbin/qemu-system-x86_64')
    element(dev, 'controller', type='pci', index='0', model='pcie-root')
    element(dev, 'controller', type='usb', model='none')
    element(dev, 'memballoon', model='none')
    element(element(dev, 'video'), 'model', type='none')
    gfx = element(dev, 'graphics', type='spice')
    element(gfx, 'listen', type='socket', socket='/run/vm/console-spice.sock')
    element(gfx, 'image', compression='off'); element(gfx, 'gl', enable='no')
    element(dev, 'audio', id='1', type='none')
    element(dev, 'watchdog', model='itco', action='none')
    cmd = element(root, '{'+NS+'}commandline')
    # libvirt sanitizes the QEMU environment. The existing PulseAudio socket is
    # mounted here; keep this separate from the controller's private session dir.
    element(cmd, '{'+NS+'}env', name='XDG_RUNTIME_DIR', value='/xdgrt')
    retained = []
    for option, value in rows:
        if option in OWNED or (option == '-monitor' and value == 'stdio'):
            continue
        if option == '-netdev' and value == 'tap,id=lan0,fd=3':
            value = 'hubport,id=lan0,hubid=0'
        retained.extend([option, value])
    for prop in ('kvm', 'vmware-cpuid-freq'):
        retained.extend(['-global', 'Haswell-noTSX-x86_64-cpu.'+prop+'=on'])
    if spice != SPICE:
        # QEMU's spice option group merges this exact supplemental option into
        # libvirt's owned socket configuration; no second server is created.
        retained.extend(['-spice', 'max-refresh-rate=60'])
    for value in retained:
        element(cmd, '{'+NS+'}arg', value=value)
    ET.indent(root)
    return {'schema': 1, 'native_argv': list(argv), 'run_id': run_id, 'domain_name': 'rgpu-'+run_id,
            'uuid': '00000000-0000-0000-0000-000000000000', 'xml': ET.tostring(root, encoding='unicode'),
            'required_launch': 'transient-paused', 'required_lan_fd': 3,
            'lan_hub': 0, 'resume_allowed': False,
            'scope': 'Planning only. Normal admission, paused identity validation, descriptor handoff and supervised cleanup are still required.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--argv-json', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    plan = build_plan(json.loads(args.argv_json.read_text()), args.run_id)
    # The expanded AppleSMC argument belongs in the private artifact, not logs.
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(plan, stream, indent=2); stream.write('\n')
    print(json.dumps({'prepared': True, 'domain_name': plan['domain_name'], 'output': str(args.output)}))


if __name__ == '__main__':
    main()
