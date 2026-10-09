import importlib.util
from pathlib import Path
import unittest
R=Path(__file__).resolve().parents[1]
def load(name):
 s=importlib.util.spec_from_file_location(name,R/'tools'/name);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
class InventoryTests(unittest.TestCase):
 def test_filter_and_private_properties(self):
  m=load('vbox-display-inventory.py')
  fb={'IOObjectClass':'AppleBootFramebuffer','private':'secret'}
  pci={'vendor-id':(0x15ad).to_bytes(4,'little'),'class-code':(0x30000).to_bytes(4,'little'),'IORegistryEntryChildren':[fb], 'IODeviceMemory':[{'address':100,'length':200,'secret':'bad'}],'secret':'bad'}
  got=m.inventory([pci,{'vendor-id':b'bad','IOObjectClass':'unrelated'}])
  self.assertEqual(len(got),2);self.assertEqual(got[0]['properties']['IODeviceMemory'],[{'address':100,'length':200}]);self.assertNotIn('secret',str(got));self.assertEqual(got[1]['ancestry'][-1]['class'],'AppleBootFramebuffer')
 def test_framebuffer_outside_pci_is_retained(self):
  m=load('vbox-display-inventory.py')
  rows=m.inventory([{'IORegistryEntryName':'IOResources','IORegistryEntryChildren':[{'IOObjectClass':'AppleBootFramebuffer','secret':'excluded'},{'IOObjectClass':'Unrelated','secret':'excluded'}]}])
  self.assertEqual(len(rows),1)
  self.assertFalse(rows[0]['matching_pci_ancestor'])
  self.assertEqual(rows[0]['ancestry'][0]['name'],'IOResources')
  self.assertNotIn('secret',str(rows))
 def test_dictionary_and_array_roots_equivalent(self):
  m=load('vbox-display-inventory.py')
  tree={'IORegistryEntryName':'IOResources','IORegistryEntryChildren':[{'IOObjectClass':'IONDRVFramebuffer','IORegistryEntryName':'display_boot'}]}
  self.assertEqual(m.inventory(tree),m.inventory([tree]))
  self.assertEqual(len(m.inventory(tree)),1)
  for invalid in ('root',42,[{} ,'bad']):
   with self.assertRaises(ValueError):m.inventory(invalid)
 def test_controller_graphics_choice(self):
  p=load('vbox-clone-boot.py').parser()
  self.assertEqual(p.parse_args([]).graphics_controller,'vboxvga')
  self.assertEqual(p.parse_args(['--graphics-controller','vmsvga']).graphics_controller,'vmsvga')
  with self.assertRaises(SystemExit):p.parse_args(['--graphics-controller','foreign'])
