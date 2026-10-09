import importlib.util
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('libvirt_console_plan', ROOT/'tools/libvirt-console-plan.py')
plan = importlib.util.module_from_spec(spec); spec.loader.exec_module(plan)


def native_fixture():
    rows = [('-m', '4000'), ('-cpu', plan.CPU), ('-machine', 'q35,accel=kvm:tcg'),
            ('-smp', '4,sockets=1,cores=4,threads=1')]
    devices = ['qemu-xhci,id=xhci', 'usb-kbd,bus=xhci.0', 'usb-tablet,bus=xhci.0',
               'isa-applesmc,osk='+'x'*64, 'usb-audio,audiodev=hda,bus=xhci.0',
               'ich9-ahci,id=sata', 'ide-hd,bus=sata.2,drive=OpenCoreBoot',
               'ide-hd,bus=sata.4,drive=MacHDD', 'vmxnet3,netdev=net0,id=net0,mac=52:54:00:00:00:01',
               plan.VFIO, 'isa-serial,chardev=rgpu_critical,index=1',
               'isa-serial,chardev=rgpu_console,index=0', plan.BOCHS,
               'vmxnet3,netdev=lan0,id=lan0,mac=52:54:00:00:00:02']
    rows += [('-device', value) for value in devices]
    rows += [('-drive', value) for value in [
        'if=pflash,format=raw,readonly=on,file=/home/arch/OSX-KVM/OVMF_CODE.fd',
        'if=pflash,format=raw,file=/home/arch/OSX-KVM/OVMF_VARS.fd',
        'id=OpenCoreBoot,if=none,snapshot=on,format=qcow2,file=/home/arch/OSX-KVM/OpenCore/OpenCore.qcow2',
        'id=MacHDD,if=none,file=/home/arch/OSX-KVM/mac_hdd_ng.img,format=qcow2']]
    rows += [('-chardev', 'socket,id=rgpu_'+name+',path=/run/vm/'+path+'.sock,server=on,wait=off')
             for name, path in [('critical', 'critical'), ('console', 'serial')]]
    rows += [('-netdev', 'user,id=net0,hostfwd=tcp::10022-:22,hostfwd=tcp::5900-:5900,'),
             ('-netdev', 'tap,id=lan0,fd=3'), ('-monitor', 'stdio'),
             ('-chardev', 'socket,id=mon1,path=/run/vm/monitor.sock,server=on,wait=off'),
             ('-mon', 'chardev=mon1,mode=readline'), ('-audiodev', 'pa,id=hda'),
             ('-gdb', 'tcp:0.0.0.0:1234'), ('-boot', 'menu=on'), ('-smbios', 'type=2'),
             ('-spice', plan.SPICE), ('-vga', 'none'), ('-display', 'none')]
    return [word for row in rows for word in row]


class LibvirtConsolePlanTests(unittest.TestCase):
    def test_refresh_is_an_exact_supplement_to_owned_spice_server(self):
        argv=native_fixture();argv[argv.index(plan.SPICE)]+=",max-refresh-rate=60"
        result=plan.build_plan(argv,'1'*32);root=ET.fromstring(result['xml'])
        args=[n.attrib['value'] for n in root.findall('./{'+plan.NS+'}commandline/{'+plan.NS+'}arg')]
        self.assertEqual(args[-2:],['-spice','max-refresh-rate=60'])
        self.assertEqual(len(root.findall('./devices/graphics')),1)
        for extra in ('max-refresh-rate=120','max-refresh-rate=0','max-refresh-rate=60,port=5905',
                      'max-refresh-rate=60,max-refresh-rate=60'):
            bad=native_fixture();bad[bad.index(plan.SPICE)]+=','+extra
            with self.subTest(extra=extra),self.assertRaises(ValueError):plan.build_plan(bad,'1'*32)

    def test_full_refresh_exact_property_and_profile(self):
        argv=native_fixture();argv[argv.index(plan.SPICE)]+=",max-refresh-rate=60"
        idx=argv.index(plan.BOCHS);argv[idx]+=",x-debug-full-refresh=on"
        result=plan.build_plan(argv,'1'*32)
        self.assertIn(argv[idx],result['xml'])
        for value in [plan.BOCHS+',x-debug-full-refresh=off',argv[idx]+',vgamem=128M',argv[idx]+',x-debug-full-refresh=on']:
            bad=list(argv);bad[idx]=value
            with self.assertRaises(ValueError):plan.build_plan(bad,'1'*32)
        argv[argv.index(plan.SPICE+',max-refresh-rate=60')]=plan.SPICE
        with self.assertRaises(ValueError):plan.build_plan(argv,'1'*32)

    def test_uppercase_native_nat_mac_is_preserved_exactly(self):
        argv=native_fixture()
        index=argv.index('vmxnet3,netdev=net0,id=net0,mac=52:54:00:00:00:01')
        argv[index]='vmxnet3,netdev=net0,id=net0,mac=B0:E5:EF:61:72:21'
        result=plan.build_plan(argv,'1'*32)
        self.assertEqual(result['native_argv'],argv)
        self.assertIn(argv[index],result['xml'])
        argv[index]=argv[index].replace('B0:','G0:')
        with self.assertRaises(ValueError):plan.build_plan(argv,'1'*32)

    def test_single_cpu_owner_and_preserved_native_devices(self):
        argv = native_fixture(); result = plan.build_plan(argv, '1'*32)
        root = ET.fromstring(result['xml'])
        self.assertEqual([n.attrib for n in root.findall('./{'+plan.NS+'}commandline/{'+plan.NS+'}env')],
                         [dict(name='XDG_RUNTIME_DIR',value='/xdgrt')])
        args = [n.attrib['value'] for n in root.findall('./{'+plan.NS+'}commandline/{'+plan.NS+'}arg')]
        self.assertNotIn('-cpu', args)
        self.assertEqual(root.find('cpu/model').text, 'Haswell-noTSX')
        self.assertEqual([v for k,v in zip(args[::2],args[1::2]) if k == '-device'],
                         [v for k,v in zip(argv[::2],argv[1::2]) if k == '-device'])
        self.assertNotIn('tap,id=lan0,fd=3', args)
        self.assertIn('hubport,id=lan0,hubid=0', args)
        self.assertFalse(result['resume_allowed'])
        self.assertEqual(result['required_launch'], 'transient-paused')
        self.assertEqual([root.find(k).text for k in ['on_reboot','on_crash','on_poweroff']], ['destroy']*3)

    def test_changed_contracts_refuse(self):
        for old,new in [(plan.CPU, plan.CPU+',avx2=off'), (plan.VFIO, plan.VFIO.replace('0x6','0x8')),
                        ('tap,id=lan0,fd=3','tap,id=lan0,fd=4'), ('pa,id=hda','spice,id=hda'),
                        (plan.SPICE,plan.SPICE.replace('gl=off','gl=on'))]:
            with self.subTest(old=old):
                argv=native_fixture();argv[argv.index(old)]=new
                with self.assertRaises(ValueError):plan.build_plan(argv,'1'*32)

    def test_device_or_firmware_order_changes_refuse(self):
        for first,second in [('qemu-xhci,id=xhci','ich9-ahci,id=sata'),
                             ('if=pflash,format=raw,readonly=on,file=/home/arch/OSX-KVM/OVMF_CODE.fd',
                              'if=pflash,format=raw,file=/home/arch/OSX-KVM/OVMF_VARS.fd')]:
            argv=native_fixture();a,b=argv.index(first),argv.index(second);argv[a],argv[b]=argv[b],argv[a]
            with self.assertRaises(ValueError):plan.build_plan(argv,'1'*32)

    def test_duplicate_options_and_additional_devices_refuse(self):
        for extra in [['-cpu',plan.CPU],['-device','virtio-vga'],['-incoming','defer']]:
            with self.assertRaises(ValueError):plan.build_plan(native_fixture()+extra,'1'*32)

    def test_transient_identity_is_run_specific(self):
        a=plan.build_plan(native_fixture(),'1'*32);b=plan.build_plan(native_fixture(),'2'*32)
        self.assertNotEqual(a['domain_name'],b['domain_name'])
        self.assertEqual(a['uuid'],b['uuid'])
        self.assertEqual(a['uuid'],'00000000-0000-0000-0000-000000000000')
        self.assertNotEqual(ET.fromstring(a['xml']).find('metadata')[0].attrib['id'],
                            ET.fromstring(b['xml']).find('metadata')[0].attrib['id'])
        with self.assertRaises(ValueError):plan.build_plan(native_fixture(),'../run')


if __name__ == '__main__':unittest.main()
