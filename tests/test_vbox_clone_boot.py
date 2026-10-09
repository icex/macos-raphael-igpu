import copy
import importlib.util
from pathlib import Path
import tempfile
import json
from unittest.mock import patch
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT/'tools'/name)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

PREP = module('vbox-prepare-loader.py')
BOOT = module('vbox-clone-boot.py')

class CloneTests(unittest.TestCase):
    def config(self):
        return {'Kernel':{'Add':[{'BundlePath':'VirtualSMC.kext','Enabled':True}]},
                'ACPI':{'Patch':[{'Comment':PREP.COMMENT,'Enabled':True,'Find':PREP.FIND,'Replace':PREP.REPLACE,'TableSignature':b'DSDT','Count':1}]},
                'NVRAM':{'Add':{'guid':{'boot-args':'-v vsmcgen=2 serial=3'},'other':{'opaque':b'identity'}}},
                'PlatformInfo':{'opaque':'unchanged'}}
    def test_precise_edit_and_original_immutable(self):
        p=self.config(); before=copy.deepcopy(p); new=PREP.patch(p)
        self.assertEqual(p,before)
        self.assertFalse(new['Kernel']['Add'][0]['Enabled'])
        self.assertFalse(new['ACPI']['Patch'][0]['Enabled'])
        self.assertEqual(new['NVRAM']['Add']['guid']['boot-args'],'-v serial=3 -rgpuoff')
        self.assertEqual(new['PlatformInfo'],p['PlatformInfo'])
        self.assertEqual(new['NVRAM']['Add']['other'],p['NVRAM']['Add']['other'])
    def test_wrong_or_duplicate_patch_refused(self):
        for kind in ('find','duplicate','count','disabled'):
            p=self.config();a=p['ACPI']['Patch']
            if kind=='find':a[0]['Find']=b'other'
            if kind=='duplicate':a.append(copy.deepcopy(a[0]))
            if kind=='count':a[0]['Count']=0
            if kind=='disabled':a[0]['Enabled']=False
            with self.assertRaises(ValueError):PREP.patch(p)
    def test_private_xml_key_not_command_argument(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'machine.vbox';p.write_text('<VirtualBox xmlns="urn:vbox"><Machine uuid="fixture"/></VirtualBox>')
            BOOT.config_key(p,b'x'*64)
            item=ET.parse(p).getroot().find('.//{urn:vbox}ExtraDataItem')
            self.assertEqual(item.attrib,{'name':'VBoxInternal2/SmcDeviceKey','value':'x'*64})
            self.assertEqual(p.stat().st_mode & 0o777,0o600)
            with self.assertRaises(ValueError):BOOT.config_key(p,b'x'*64)
    def test_owned_state_rejects_foreign_config_before_stop(self):
        with tempfile.TemporaryDirectory() as d:
            home=Path(d);scope=home/'scope.json'
            scope.write_text(json.dumps({'uuid':'id','name':'owned'}));scope.chmod(0o600)
            raw='UUID="id"\nCfgFile="/foreign/machine.vbox"\nVMState="running"\n'
            with patch.object(BOOT,'call',return_value=raw) as call:
                with self.assertRaises(RuntimeError):BOOT.stop(home,'id')
                self.assertEqual(call.call_count,1)
    def test_stopped_machine_not_forced_again(self):
        with tempfile.TemporaryDirectory() as d:
            home=Path(d);scope=home/'scope.json'
            scope.write_text(json.dumps({'uuid':'id','name':'owned'}));scope.chmod(0o600)
            cfg=home/'vms'/'owned'/'owned.vbox'
            raw=f'UUID="id"\nCfgFile="{cfg}"\nVMState="poweroff"\n'
            with patch.object(BOOT,'call',return_value=raw) as call:
                self.assertEqual(BOOT.stop(home,'id'),'poweroff')
                self.assertTrue(all(c.args[1][0]=='showvminfo' for c in call.call_args_list))
    def test_bad_key_and_public_keyfile_refused(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'key';p.write_bytes(b'x'*64);p.chmod(0o644)
            with self.assertRaises(ValueError):BOOT.private_file(p)
            with self.assertRaises(ValueError):BOOT.config_key(p,b'short')

if __name__=='__main__':unittest.main()
