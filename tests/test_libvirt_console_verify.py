import copy
import importlib.util
import json
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET
from test_libvirt_console_plan import native_fixture

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('verify_console',ROOT/'tools/libvirt-console-verify.py')
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)


def fixture():
    plan=mod.planner.build_plan(native_fixture(),'1'*32)
    root=ET.fromstring(plan['xml'])
    custom=[n.attrib['value'] for n in root.findall('./{'+mod.planner.NS+'}commandline/{'+mod.planner.NS+'}arg')]
    # Independent reviewed libvirt11.9 conversion prefix, with runtime monitor FD.
    argv=['/usr/sbin/qemu-system-x86_64','-name','guest=rgpu-'+('1'*32)+',debug-threads=on','-S',
          '-object',json.dumps({'qom-type':'secret','id':'masterKey0','format':'raw',
                              'file':'/home/arch/.config/libvirt/qemu/lib/domain-1-rgpu-'+('1'*15)+'/master-key.aes'}),
          '-machine','pc-q35-10.1,usb=off,dump-guest-core=off,memory-backend=pc.ram,acpi=on',
          '-accel','kvm','-cpu','Haswell-noTSX,vendor=GenuineIntel,invtsc=on','-m','size=4096000k',
          '-object','{"qom-type":"memory-backend-ram","id":"pc.ram","size":4194304000}',
          '-overcommit','mem-lock=off','-smp','4,sockets=1,dies=1,clusters=1,cores=4,threads=1',
          '-uuid',plan['uuid'],'-no-user-config','-nodefaults','-chardev',
          'socket,id=charmonitor,fd=22,server=on,wait=off','-mon','chardev=charmonitor,id=monitor,mode=control',
          '-rtc','base=utc','-no-shutdown','-boot','strict=on','-audiodev','{"id":"audio1","driver":"none"}',
          '-spice','unix=on,addr=/run/vm/console-spice.sock,disable-ticketing=on,image-compression=off,seamless-migration=on',
          '-global','ICH9-LPC.noreboot=off','-watchdog-action','none']+custom+[
          '-sandbox','on,obsolete=deny,elevateprivileges=deny,spawn=deny,resourcecontrol=deny','-msg','timestamp=on']
    state=dict(name=plan['domain_name'],uuid=plan['uuid'],run_id=plan['run_id'],persistent=False,
               domain_id=1,argv=argv)
    return plan,state


class VerifyTests(unittest.TestCase):
    def test_complete_profile(self):
        plan,state=fixture();self.assertTrue(mod.verify(plan,state))
    def test_rejects_changes_to_every_observed_argument(self):
        plan,state=fixture()
        for index in range(len(state['argv'])):
            altered=copy.deepcopy(state);altered['argv'][index]+='UNREVIEWED'
            with self.subTest(index=index),self.assertRaises(ValueError):mod.verify(plan,altered)
    def test_rejects_injected_options_or_missing_option(self):
        plan,state=fixture()
        for argv in [state['argv']+['-device','virtio-vga'],state['argv'][1:]]:
            with self.assertRaises(ValueError):mod.verify(plan,dict(state,argv=argv))
    def test_plan_xml_cannot_change_independently_of_native_intent(self):
        plan,state=fixture();plan['xml']=plan['xml'].replace('on_poweroff>destroy','on_poweroff>restart')
        with self.assertRaisesRegex(ValueError,'intent'):mod.verify(plan,state)
    def test_private_path_bound_to_actual_domain_id(self):
        plan,state=fixture();state['domain_id']=2
        with self.assertRaises(ValueError):mod.verify(plan,state)
    def test_json_duplicates_rejected(self):
        plan,state=fixture();i=state['argv'].index('{"id":"audio1","driver":"none"}')
        state['argv'][i]='{"id":"audio1","driver":"spice","driver":"none"}'
        with self.assertRaises(ValueError):mod.verify(plan,state)
    def test_live_cpu_properties_not_inferred_from_argv(self):
        plan,_=fixture();cpus=[{'cpu-index':i,'qom-path':'/cpu/'+str(i),
                              'props':{'socket-id':0,'core-id':i,'thread-id':0}} for i in range(4)]
        props={cpu['qom-path']:dict(vendor='GenuineIntel',kvm=True,invtsc=True,**{'vmware-cpuid-freq':True}) for cpu in cpus}
        self.assertTrue(mod.verify_cpu_observations(plan,dict(enabled=True,present=True),cpus,props))
        for key in props["/cpu/0"]:
            bad=copy.deepcopy(props);bad['/cpu/0'][key]=False
            with self.assertRaises(ValueError):mod.verify_cpu_observations(plan,dict(enabled=True,present=True),cpus,bad)

if __name__=='__main__':unittest.main()
