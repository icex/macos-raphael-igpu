import importlib.util
import os
from pathlib import Path
import stat
import struct
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('console_network',ROOT/'tools/libvirt-console-network.py')
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
MAC='62:a0:86:89:74:18'
RECEIPT=dict(schema=1,kind='macvtap',mode='bridge',name='rgpu-lan',mac=MAC,
             character=dict(major=511,minor=1),ifindex=6)
STAT=SimpleNamespace(st_mode=stat.S_IFCHR|0o660,st_rdev=os.makedev(511,1),st_ino=12,st_dev=1200)
REPORT='hub 0\n \\ rgpu_lan_attachment: rgpu_lan_backend: index=0,type=tap,fd=14\n \\ lan0: lan0: index=0,type=nic,model=vmxnet3,macaddr='+MAC+'\n'

class NetworkTests(unittest.TestCase):
    def test_macvtap_default_vnet_header_flags_and_independent_minor(self):
        with patch.object(mod.os,'fstat',return_value=STAT),patch.object(mod.fcntl,'ioctl',side_effect=[struct.pack('16sH',b'rgpu-lan',0x5002)+bytes(22),
                struct.pack('16sH',b'rgpu-lan',1)+bytes.fromhex(MAC.replace(':',''))+bytes(16)]):
            result=mod.verify_inherited(3,RECEIPT)
        self.assertEqual(result['flags'],0x5002);self.assertEqual(result['character']['minor'],1)
    def test_wrong_kind_device_name_and_queue_flags_refuse(self):
        for name,flags,rdev in [(b'other',0x5002,os.makedev(511,1)),(b'rgpu-lan',0x5001,os.makedev(511,1)),
                               (b'rgpu-lan',0x5102,os.makedev(511,1)),(b'rgpu-lan',0x5002,os.makedev(511,6))]:
            data=SimpleNamespace(**vars(STAT));data.st_rdev=rdev
            with patch.object(mod.os,'fstat',return_value=data),patch.object(mod.fcntl,'ioctl',return_value=struct.pack('16sH',name,flags)+bytes(22)):
                with self.assertRaises(ValueError):mod.verify_inherited(3,RECEIPT)
    def test_actual_attached_mac_change_refuses(self):
        with patch.object(mod.os,'fstat',return_value=STAT),patch.object(mod.fcntl,'ioctl',side_effect=[
                struct.pack('16sH',b'rgpu-lan',0x5002)+bytes(22),
                struct.pack('16sH',b'rgpu-lan',1)+bytes.fromhex('525400000001')+bytes(16)]):
            with self.assertRaisesRegex(ValueError,'MAC mismatch'):mod.verify_inherited(3,RECEIPT)
    def test_qemu_descriptor_stat_only_never_reopens_queue(self):
        inherited=dict(character=RECEIPT['character'],inode=12,device=1200)
        with patch.object(mod.Path,'stat',return_value=STAT),patch('builtins.open',side_effect=AssertionError('must not open')):
            self.assertTrue(mod.verify_qemu_descriptor(123,14,inherited))
        bad=SimpleNamespace(**vars(STAT));bad.st_ino=13
        with patch.object(mod.Path,'stat',return_value=bad):
            with self.assertRaises(ValueError):mod.verify_qemu_descriptor(123,14,inherited)
    def test_actual_hub_members_and_mac_required(self):
        self.assertEqual(mod.verify_network_report(REPORT,MAC),14)
        for old,new in [('hub 0','hub 1'),('lan0: lan0:','lan0: other:'),(MAC,'52:54:00:00:00:01'),('type=tap','type=socket')]:
            with self.assertRaises(ValueError):mod.verify_network_report(REPORT.replace(old,new),MAC)
    def test_extra_member_and_duplicate_backend_refuse(self):
        for extra in [' \\ surprise: type=nic\n','rgpu_lan_backend: duplicate\n']:
            with self.assertRaises(ValueError):mod.verify_network_report(REPORT+extra,MAC)

if __name__=='__main__':unittest.main()
