"""Optional agent transport topology; no VM, guest agent or resize behavior."""
import copy
import hashlib
import io
from contextlib import redirect_stdout
from unittest.mock import patch
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import unittest
import xml.etree.ElementTree as ET
from test_libvirt_console_plan import native_fixture, plan
from test_libvirt_console_verify import fixture, mod as verify
from test_stage_candidate import load_tool

ROOT=Path(__file__).resolve().parents[1]
CONTROLLER='virtio-serial-pci,id=rgpu_agent_serial,bus=pcie.0,addr=0x10,max_ports=2'
CHAR='spicevmc,id=rgpu_vdagent,name=vdagent'
PORT='virtserialport,id=rgpu_agent_port,bus=rgpu_agent_serial.0,nr=1,chardev=rgpu_vdagent,name=com.redhat.spice.0'
AGENT=['-device',CONTROLLER,'-chardev',CHAR,'-device',PORT]

def agent_fixture(refresh=False):
 argv=native_fixture()
 index=argv.index(plan.SPICE)
 argv[index]+=(',max-refresh-rate=60' if refresh else '')+',agent-mouse=off'
 return argv+AGENT

def experiment():
 spec=importlib.util.spec_from_file_location('vdagent_experiment',ROOT/'tools/experiment.py')
 m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def options():
 return dict(BOOTDISK_MODE='custom',NVRAM='stock',GENERIC_GRAPHICS='off',GDB='on',AUDIO='usb',VM_CONSOLE='bochs-spice',VM_MANAGER='libvirt')

class VdagentTests(unittest.TestCase):
 def test_option_default_off_and_exact_profile(self):
  m=experiment();base=options()
  for value in (None,'off','on'):
   selected=dict(base)
   if value is not None:selected['CONSOLE_VDAGENT']=value
   self.assertEqual(m.launch_options(dict(launch_options=selected)),selected)
  for changes in ({'VM_MANAGER':'direct'},{'VM_CONSOLE':'bochs'},{'GENERIC_GRAPHICS':'on'},{'CONSOLE_VDAGENT':True},{'CONSOLE_VDAGENT':'yes'}):
   with self.subTest(changes=changes),self.assertRaises(ValueError):
    m.launch_options(dict(launch_options=dict(base,CONSOLE_VDAGENT='on',**{})|changes))
  historical=dict(BOOTDISK_MODE='custom',NVRAM='stock',CONSOLE_VDAGENT='off')
  self.assertEqual(m.launch_options(dict(launch_options=historical)),historical)

 def test_plan_preserves_default_and_existing_device_order(self):
  baseline=native_fixture();before=plan.build_plan(baseline,'1'*32)
  after=plan.build_plan(agent_fixture(),'1'*32)
  root=ET.fromstring(after['xml']);args=[n.attrib['value'] for n in root.findall('./{'+plan.NS+'}commandline/{'+plan.NS+'}arg')]
  start=args.index(CONTROLLER)-1
  self.assertEqual(args[start:start+6],AGENT)
  without=list(after['native_argv'][:-6]);without[without.index(plan.SPICE+',agent-mouse=off')]=plan.SPICE
  self.assertEqual(without,before['native_argv'])
  for name in ('console','critical'):
   self.assertEqual(sum('isa-serial,chardev=rgpu_'+name in x for x in args),1)
  self.assertEqual(plan.build_plan(baseline,'1'*32),before)

 def test_plan_refuses_partial_duplicate_or_changed_topology(self):
  cases=[AGENT[:-2],AGENT[2:],AGENT+AGENT]
  for old,new in [('addr=0x10','addr=0x7'),('nr=1','nr=0'),('max_ports=2','max_ports=16'),('com.redhat.spice.0','other'),('chardev=rgpu_vdagent','chardev=rgpu_console'),('name=vdagent','name=usbredir')]:
   cases.append([x.replace(old,new) for x in AGENT])
  for agent in cases:
   with self.subTest(agent=agent),self.assertRaises(ValueError):plan.build_plan(agent_fixture()[:-6]+agent,'1'*32)

 def test_private_argv_verification_binds_channel(self):
  baseline,state=fixture();new=plan.build_plan(agent_fixture(),'1'*32)
  # Custom arguments precede CPU-global suffix in the reviewed libvirt command.
  index=state['argv'].index('-global',state['argv'].index(CONTROLLER) if CONTROLLER in state['argv'] else state['argv'].index('hubport,id=lan0,hubid=0'))
  state['argv'][index:index]=AGENT
  index=state['argv'].index('-sandbox');state['argv'][index:index]=['-spice','agent-mouse=off']
  self.assertTrue(verify.verify(new,state))
  with self.assertRaises(ValueError):verify.verify(baseline,state)
  state['argv'][state['argv'].index(PORT)]=PORT.replace('nr=1','nr=0')
  with self.assertRaises(ValueError):verify.verify(new,state)

 def test_running_identity_channel_separate_from_uart(self):
  m=experiment();opts=options();manifest=dict(image_id='img',gpu=False,run_id='a'*32,launch_options=opts)
  obs=dict(image_id='img',vfio_args=[],serial_args=[],pci_topology=[dict(model='usb-audio',bus='xhci.0')],
   graphics_args=['-spice','unix=on,addr=/run/vm/console-spice.sock,disable-ticketing=on,image-compression=off,seamless-migration=on','-vga','none','-display','none','-device',plan.BOCHS],cid='c'*64,argv_sha256='d'*64,
   libvirt=dict(verified=True,run_id='a'*32,cid='c'*64,argv_sha256='d'*64))
  self.assertEqual(m.validate_running(manifest,obs),[])
  obs['agent_args']=AGENT
  self.assertIn('vdagent_topology',m.validate_running(manifest,obs))
  opts['CONSOLE_VDAGENT']='on'
  self.assertIn('generic_graphics',m.validate_running(manifest,obs))
  obs['graphics_args']+=['-spice','agent-mouse=off']
  self.assertEqual(m.validate_running(manifest,obs),[])
  obs['agent_args']=AGENT[:-2]
  self.assertIn('vdagent_topology',m.validate_running(manifest,obs))
  self.assertEqual(obs['serial_args'],[])

 def test_agent_mouse_route_exact_profile_and_reject_unsafe_variants(self):
  for refresh in (False,True):
   argv=agent_fixture(refresh);new=plan.build_plan(argv,'1'*32)
   root=ET.fromstring(new['xml']);args=[n.attrib['value'] for n in root.findall('./{'+plan.NS+'}commandline/{'+plan.NS+'}arg')]
   self.assertEqual(args[-2:],['-spice',('max-refresh-rate=60,' if refresh else '')+'agent-mouse=off'])
   for replacement in ('','agent-mouse=on','agent-mouse=off,agent-mouse=off','agent-mouse=off,port=5905'):
    bad=[x.replace(',agent-mouse=off',(','+replacement if replacement else '')) for x in argv]
    with self.subTest(refresh=refresh,replacement=replacement),self.assertRaises(ValueError):plan.build_plan(bad,'1'*32)
  with self.assertRaises(ValueError):plan.build_plan(agent_fixture()[:-6],'1'*32)

 def test_entry_console_builder_binds_agent_mouse_only_when_enabled(self):
  source=(ROOT/'tools/vm-entry.sh').read_text()
  start=source.index('case "${VM_CONSOLE:-none}"') if 'case "${VM_CONSOLE:-none}"' in source else source.index('case "${VM_CONSOLE:-off}"')
  end=source.index('if [[ -n "${LAN_TAP_NODE:-}"')
  for value in ('off','on'):
   env=dict(os.environ,VM_CONSOLE='bochs-spice',VM_MANAGER='libvirt',GENERIC_GRAPHICS='off',CONSOLE_VDAGENT=value,CONSOLE_REFRESH='60',CONSOLE_FULL_REFRESH='off',CONSOLE_SNAPSHOT='off',EXTRA='')
   result=subprocess.run(['bash','-c',source[start:end]+'\nprintf "%s" "$EXTRA"'],env=env,text=True,capture_output=True,check=True,timeout=3)
   self.assertEqual('agent-mouse=off' in result.stdout,value=='on')
   self.assertEqual(result.stdout.count('agent-mouse='),int(value=='on'))

 def test_proc_observer_collects_agent_and_capture_independently(self):
  m=experiment()
  code=next(c for c in m.running_identity.__code__.co_consts if isinstance(c,str) and "os.listdir('/proc')" in c)
  uart=['-chardev','socket,id=rgpu_console,path=/run/vm/serial.sock,server=on,wait=off',
        '-device','isa-serial,chardev=rgpu_console,index=0']
  raw=('\0'.join(['/usr/sbin/qemu-system-x86_64']+uart+AGENT)+'\0').encode()
  output=io.StringIO()
  with patch('os.listdir',return_value=['123']),patch('builtins.open',return_value=io.BytesIO(raw)),redirect_stdout(output):
   exec(code,{})
  observed=json.loads(output.getvalue())
  self.assertEqual(observed['agent_args'],AGENT)
  self.assertEqual(observed['serial_args'],[uart[1],uart[3]])
  self.assertEqual(observed['argv_sha256'],hashlib.sha256(raw).hexdigest())

 def test_stage_validates_optional_transport_without_card_rewrite(self):
  tool=load_tool();tool.configure('1.0.381','metal-209')
  base=json.loads((ROOT/'experiments/metal-209.json').read_text())
  for value in ('off','on',True,'yes'):
   card=copy.deepcopy(base);card['launch_options']['CONSOLE_VDAGENT']=value
   raw=json.dumps(card).encode()
   if value in ('off','on'):tool.validate_card(raw,hashlib.sha256(raw).hexdigest())
   else:
    with self.assertRaises(RuntimeError):tool.validate_card(raw,hashlib.sha256(raw).hexdigest())

 def test_entry_shell_builds_exact_suffix_and_rejects_other_profiles(self):
  source=(ROOT/'tools/vm-entry.sh').read_text()
  guards=source[source.index('case "${CONSOLE_VDAGENT:-off}"'):source.index('case "${CONSOLE_SNAPSHOT:-off}"')]
  append=source[source.index('# Keep the new explicit PCI slot'):source.index('case "${VM_MANAGER:-direct}" in')]
  base=dict(os.environ,VM_MANAGER='libvirt',VM_CONSOLE='bochs-spice',GENERIC_GRAPHICS='off',EXTRA='existing-device-arguments')
  base.pop('CONSOLE_VDAGENT',None)
  for value in (None,'off','on','bad'):
   env=dict(base)
   if value is not None:env['CONSOLE_VDAGENT']=value
   p=subprocess.run(['bash','-c',guards+append+'\nprintf "%s" "$EXTRA"'],env=env,text=True,capture_output=True,timeout=3)
   self.assertEqual(p.returncode==0,value!='bad')
   if value!='bad':self.assertEqual(p.stdout,'existing-device-arguments'+(' '+' '.join(AGENT) if value=='on' else ''))
  for key,value in [('VM_MANAGER','direct'),('VM_CONSOLE','bochs'),('GENERIC_GRAPHICS','on')]:
   env=dict(base,CONSOLE_VDAGENT='on');env[key]=value
   p=subprocess.run(['bash','-c',guards+append],env=env,capture_output=True,timeout=3)
   self.assertNotEqual(p.returncode,0)

if __name__=='__main__':unittest.main()
