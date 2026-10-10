import importlib.util
from pathlib import Path
import unittest
from test_libvirt_console_plan import native_fixture, plan
from test_libvirt_console_entry import mod as entry

ROOT=Path(__file__).resolve().parents[1]
def load(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'tools'/name)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

class UsbRedirectionTests(unittest.TestCase):
    def args(self):
        a=native_fixture()
        for value in plan.USBREDIR_GLOBALS:a += ['-global',value]
        for ch,dev in zip(plan.USBREDIR_CHARS,plan.USBREDIR_DEVICES):a+=['-chardev',ch,'-device',dev]
        return a
    def test_exact_slots_preserved_and_admission_both_directions(self):
        baseline=plan.build_plan(native_fixture(),'1'*32)
        selected=plan.build_plan(self.args(),'1'*32)
        entry.validate_plan_refresh(selected,{'console_usbredir':'on'})
        entry.validate_plan_refresh(baseline,{})
        for p,a in [(selected,{}),(baseline,{'console_usbredir':'on'})]:
            with self.assertRaises(ValueError):entry.validate_plan_refresh(p,a)
        for value in plan.USBREDIR_CHARS+plan.USBREDIR_DEVICES:self.assertIn(value,selected['xml'])
    def test_partial_duplicate_foreign_bus_host_device_refused(self):
        a=self.args()
        cases=[a[:-4],a+['-device',plan.USBREDIR_DEVICES[0]],
               [x.replace('bus=xhci.0','bus=foreign.0') if x.startswith('usb-redir,') else x for x in a],
               a+['-device','usb-host,vendorid=1,productid=2']]
        for args in cases:
            with self.subTest(args=args[-4:]),self.assertRaises(ValueError):plan.build_plan(args,'1'*32)
    def test_direct_port_count_is_exact_and_not_allowed_without_usb(self):
        for globals_ in ([], ['qemu-xhci.p2=4','qemu-xhci.p3=8'], ['qemu-xhci.p2=8'], plan.USBREDIR_GLOBALS*2):
            args=self.args()[0:]
            rows=list(zip(args[::2],args[1::2]))
            args=[x for row in rows if row[0]!='-global' for x in row]
            for value in globals_:args+=['-global',value]
            with self.assertRaises(ValueError):plan.build_plan(args,'1'*32)
        with self.assertRaises(ValueError):plan.build_plan(native_fixture()+['-global','qemu-xhci.p2=8'],'1'*32)

    def test_manual_policy_disables_both_automatic_routes(self):
        mod=load('console-manager-usbredir.py')
        class Properties:
            def __init__(self,**values):self.values=values
            def set_property(self,key,value):self.values[key]=value
            def get_property(self,key):return self.values.get(key)
        class Viewer:pass
        v=Viewer();v._usbdev_manager=Properties(**{'auto-connect':True,'redirect-on-connect':'-1,-1,-1,-1,1'})
        gtk=Properties(**{'auto-usbredir':True})
        mod.manual_only(v,gtk)
        self.assertFalse(gtk.get_property('auto-usbredir'))
        self.assertFalse(v._usbdev_manager.get_property('auto-connect'))
        self.assertIsNone(v._usbdev_manager.get_property('redirect-on-connect'))
        v._usbdev_manager=None
        with self.assertRaises(RuntimeError):mod.manual_only(v,gtk)
    def test_launch_contract_opt_in_and_bad_profile_refusal(self):
        ex=load('experiment.py')
        # Obtain canonical base from a reviewed card rather than assume omitted fields.
        import json
        card=json.loads((ROOT/'experiments/metal-213.json').read_text())
        base=card['launch_options'];base['CONSOLE_USBREDIR']='on'
        self.assertEqual(ex.launch_options({'launch_options':base}),base)
        for change in [{'VM_MANAGER':'direct'},{'CONSOLE_USBREDIR':'yes'},{'GENERIC_GRAPHICS':'on'}]:
            bad=dict(base,**change)
            with self.assertRaises(ValueError):ex.launch_options({'launch_options':bad})
    def test_complete_generated_argv_binds_every_usb_argument(self):
        from test_libvirt_console_verify import fixture, mod as verifier
        import copy
        baseline,state=fixture()
        active=plan.build_plan(self.args(),'1'*32)
        # Planner places raw devices before the existing CPU global properties.
        # Find the retained raw CPU globals rather than libvirt's earlier global.
        idx=state['argv'].index('Haswell-noTSX-x86_64-cpu.kvm=on')-1
        extra=[]
        for value in plan.USBREDIR_GLOBALS:extra += ['-global',value]
        for ch,dev in zip(plan.USBREDIR_CHARS,plan.USBREDIR_DEVICES):extra+=['-chardev',ch,'-device',dev]
        state['argv'][idx:idx]=extra
        self.assertTrue(verifier.verify(active,state))
        with self.assertRaises(ValueError):verifier.verify(baseline,state)
        for offset in range(len(extra)):
            bad=copy.deepcopy(state);bad['argv'][idx+offset]+='unexpected'
            with self.assertRaises(ValueError):verifier.verify(active,bad)
    def test_actual_shell_emits_only_empty_slots_after_existing_devices(self):
        import os,subprocess
        source=(ROOT/'tools/vm-entry.sh').read_text()
        begin=source.index('# Empty SPICE USB slots only;')
        end=source.index('case "${VM_MANAGER:-direct}" in',begin)
        for value,count in [('off',0),('on',2)]:
            result=subprocess.run(['bash','-c',source[begin:end]+'\nprintf "%s" "$EXTRA"'],
                env=dict(os.environ,CONSOLE_USBREDIR=value,EXTRA='-device existing'),capture_output=True,text=True,check=True)
            self.assertTrue(result.stdout.startswith('-device existing'))
            self.assertEqual(result.stdout.count(' -device usb-redir,'),count)
            self.assertNotIn('usb-host',result.stdout)
            if count:
                for val in plan.USBREDIR_CHARS+plan.USBREDIR_DEVICES:self.assertIn(val,result.stdout)
    def test_private_bus_reexec_precedes_any_manager_import(self):
        from unittest.mock import patch
        import os
        m=load('console-manager-usbredir.py')
        with patch.dict(os.environ,{},clear=True),patch.object(m.os,'execvpe',side_effect=RuntimeError('intercept')) as execute:
            with self.assertRaisesRegex(RuntimeError,'intercept'):m.main()
            self.assertEqual(execute.call_args.args[0],'dbus-run-session')
            self.assertEqual(execute.call_args.args[2]['RGPU_USBREDIR_PRIVATE_BUS'],'1')
    def test_stage_only_new_reviewed_pair_requires_usb_redirection(self):
        stage=load('stage-candidate.py')
        base={'VM_MANAGER':'libvirt','VM_CONSOLE':'bochs-spice','GENERIC_GRAPHICS':'off'}
        selected=dict(base,CONSOLE_USBREDIR='on')
        stage.validate_usbredir_card_option(('1.0.421','metal-223'),selected)
        self.assertEqual(selected,base)
        for pair,value in [(('1.0.421','metal-223'),'off'),(('1.0.402','metal-222'),'on'),(('1.0.421','metal-222'),'on')]:
            with self.assertRaises(RuntimeError):stage.validate_usbredir_card_option(pair,dict(base,CONSOLE_USBREDIR=value))
        with self.assertRaises(RuntimeError):stage.validate_usbredir_card_option(('1.0.421','metal-223'),dict(base,VM_MANAGER='direct',CONSOLE_USBREDIR='on'))
        old=dict(base);stage.validate_usbredir_card_option(('1.0.402','metal-222'),old)
        self.assertEqual(old,base)
    def test_stock_import_finishes_before_guard_and_preserves_result(self):
        from types import SimpleNamespace
        mod=load('console-manager-usbredir.py');events=[];callback=object()
        def original(args):
            events.append(('stock',args));return ['remaining']
        def install(value):events.append(('guard',value))
        manager=SimpleNamespace(_import_gtk=original)
        mod.install_startup_hook(manager,callback,install)
        self.assertEqual(events,[])
        self.assertEqual(manager._import_gtk(['first']),['remaining'])
        self.assertEqual(events,[('stock',['first']),('guard',callback)])
        def fail(args):raise RuntimeError('stock initialization failed')
        events.clear();manager._import_gtk=fail
        mod.install_startup_hook(manager,callback,install)
        with self.assertRaisesRegex(RuntimeError,'stock initialization failed'):manager._import_gtk([])
        self.assertEqual(events,[])
