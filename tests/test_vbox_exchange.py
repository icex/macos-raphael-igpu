import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
def module():
    s=importlib.util.spec_from_file_location('vbox_exchange_boot',ROOT/'tools/vbox-clone-boot.py')
    m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

class ExchangeTests(unittest.TestCase):
    def test_bounded_independent_format_and_hash(self):
        m=module()
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp);p=d/'exchange.vdi';p.write_bytes(b'x'*1024);p.chmod(0o600)
            def info(value):return type('Result',(),{'stdout':json.dumps(value).encode()})()
            good={'format':'vdi','virtual-size':m.EXCHANGE_SIZE}
            with patch.object(m,'EXCHANGE_DIR',d),patch.object(m.subprocess,'run',return_value=info(good)) as run:
                r=m.exchange_input(p);self.assertEqual(r['port'],5);self.assertEqual(r['virtual_size'],32*1024*1024)
                self.assertEqual(run.call_args.kwargs['timeout'],10)
                for value in [dict(good,format='qcow2'),dict(good,**{'virtual-size':1}),dict(good,**{'backing-filename':'foreign'})]:
                    run.return_value=info(value)
                    with self.assertRaises(ValueError):m.exchange_input(p)
                run.return_value=info(good)
                p.chmod(0o644)
                with self.assertRaises(ValueError):m.exchange_input(p)
                p.chmod(0o600);alias=d/'alias';os.link(p,alias)
                with self.assertRaises(ValueError):m.exchange_input(p)
                alias.unlink();p.unlink();p.symlink_to(alias)
                with self.assertRaises(ValueError):m.exchange_input(p)
    def test_size_and_containment_refuse_before_tool(self):
        m=module()
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp);p=d/'exchange.vdi';p.write_bytes(b'x'*100);p.chmod(0o600)
            with patch.object(m.subprocess,'run',side_effect=AssertionError('must not inspect refused path')):
                with self.assertRaises(ValueError):m.exchange_input(p)
                with p.open('wb') as f:f.truncate(41*1024*1024)
                with patch.object(m,'EXCHANGE_DIR',d):
                    with self.assertRaises(ValueError):m.exchange_input(p)
    def test_medium_uuid_path_format_and_duplicate_guards(self):
        m=module();ident='12345678-1234-5678-9012-123456789abc';e={'path':'/owned/exchange.vdi','uuid':ident}
        good=f'UUID: {ident}\nLocation: /owned/exchange.vdi\nStorage format: VDI\n'
        with patch.object(m,'call',return_value=good) as call:
            self.assertEqual(m.exchange_medium(Path('/private'),e),ident)
            for raw in [good+'UUID: '+ident,good.replace('VDI','RAW'),good.replace('/owned','/foreign'),good.replace(ident,'aaaaaaaa-1234-5678-9012-123456789abc')]:
                call.return_value=raw
                with self.assertRaises(RuntimeError):m.exchange_medium(Path('/private'),e)
    def test_attachment_requires_exact_slot_and_stopped_owner(self):
        m=module();e={'path':'/owned/exchange.vdi','uuid':'medium'}
        good='UUID="vm"\nCfgFile="/private/vms/owned/owned.vbox"\nVMState="poweroff"\n"SATA-5-0"="/owned/exchange.vdi"\n"SATA-ImageUUID-5-0"="medium"\n'
        with patch.object(m,'state',return_value='poweroff') as state,patch.object(m,'call',return_value=good) as call,patch.object(m,'private_file',return_value=b'{"name":"owned"}'):
            m.verify_exchange_attachment(Path('/private'),'vm',e)
            for raw in [good.replace('UUID="vm"','UUID="foreign"'),good.replace('VMState="poweroff"','VMState="running"'),good.replace('5-0','2-0'),good.replace('medium','foreign'),good.replace('/owned','/foreign')]:
                call.return_value=raw
                with self.assertRaises(RuntimeError):m.verify_exchange_attachment(Path('/private'),'vm',e)
            state.return_value='running';call.reset_mock()
            with self.assertRaises(RuntimeError):m.verify_exchange_attachment(Path('/private'),'vm',e)
            call.assert_not_called()

    def test_close_uses_verified_uuid_never_delete_and_refuses_replacement(self):
        m=module()
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'exchange.vdi';p.write_bytes(b'changed guest output')
            e={'path':str(p),'uuid':'owned'}
            with patch.object(m,'exchange_medium',return_value='owned') as identity,patch.object(m,'call',return_value='') as call:
                self.assertEqual(len(m.close_exchange(Path(tmp),e)),64)
                self.assertEqual(call.call_args.args[1],['closemedium','disk','owned'])
                identity.side_effect=RuntimeError('foreign medium');call.reset_mock()
                with self.assertRaises(RuntimeError):m.close_exchange(Path(tmp),e)
                call.assert_not_called()

    def test_state_retains_exchange_binding_through_cleanup(self):
        m=module()
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp);p=home/'scope.json';p.write_text(json.dumps({'name':'vm','exchange':{'path':'/disk','uuid':'medium'}}));p.chmod(0o600)
            raw=f'UUID="machine"\nCfgFile="{home}/vms/vm/vm.vbox"\nVMState="poweroff"\n"SATA-5-0"="/disk"\n"SATA-ImageUUID-5-0"="medium"\n'
            with patch.object(m,'call',return_value=raw) as call:
                self.assertEqual(m.state(home,'machine'),'poweroff')
                call.return_value=raw.replace('medium','replacement')
                with self.assertRaises(RuntimeError):m.state(home,'machine')

if __name__=='__main__':unittest.main()
