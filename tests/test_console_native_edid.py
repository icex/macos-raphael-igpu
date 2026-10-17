import copy
import hashlib
import importlib.util
import json
import os
import subprocess
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
def load(name):
    spec=importlib.util.spec_from_file_location(name.replace('-','_'),ROOT/'tools'/f'{name}.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod

class NativeEdidTests(unittest.TestCase):
    def test_real_card_binds_native_edid_and_rejects_drift(self):
        stage=load('stage-candidate');stage.configure('1.0.432','metal-226')
        experiment=load('experiment');card=json.loads((ROOT/'experiments/metal-226.json').read_text())
        raw=json.dumps(card).encode();stage.validate_card(raw,hashlib.sha256(raw).hexdigest())
        experiment.launch_options(card)
        for key,value in [('CONSOLE_EDID','default'),('CONSOLE_EDID','4k120'),('CONSOLE_EDID',True),('CONSOLE_REFRESH','60'),('CONSOLE_SNAPSHOT','restart'),('CONSOLE_VDAGENT','off'),('CONSOLE_USBREDIR','off')]:
            altered=copy.deepcopy(card);altered['launch_options'][key]=value;raw=json.dumps(altered).encode()
            with self.subTest(key=key,value=value),self.assertRaises(RuntimeError):stage.validate_card(raw,hashlib.sha256(raw).hexdigest())
        for key,value in [('CONSOLE_EDID','4k120'),('CONSOLE_EDID',True),('CONSOLE_REFRESH','60'),('CONSOLE_SNAPSHOT','restart')]:
            options=dict(card['launch_options']);options[key]=value
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):experiment.launch_options({'launch_options':options})

    def test_plan_and_admission_preserve_exact_native_device(self):
        from test_libvirt_console_plan import native_fixture
        plan=load('libvirt-console-plan');handoff=load('libvirt-console-handoff');entry=load('libvirt-console-entry')
        args=native_fixture();args[args.index(plan.SPICE)]+=",max-refresh-rate=120"
        idx=args.index(plan.BOCHS);args[idx]+=",x-debug-full-refresh=on,x-debug-snapshot=on,x-debug-snapshot-restart=on,x-debug-snapshot-timing=on,x-debug-snapshot-pool=on,xres=2560,yres=1440,refresh_rate=120000"
        result=plan.build_plan(args,'a'*32)
        self.assertEqual(result['native_argv'],args)
        admission=dict(console_refresh='120',console_full_refresh='on',console_snapshot='restart-timing-pool',console_edid='1440p120')
        entry.validate_plan_refresh(result,admission)
        with self.assertRaises(ValueError):entry.validate_plan_refresh(result,dict(admission,console_edid='default'))
        for text in ('refresh_rate=120','xres=3840','yres=2160','xres=2560,xres=2560'):
            bad=list(args);bad[idx]=args[idx].replace('refresh_rate=120000',text) if text.startswith('refresh') else args[idx].replace('xres=2560',text)
            with self.subTest(text=text),self.assertRaises(ValueError):plan.build_plan(bad,'a'*32)
        with tempfile.TemporaryDirectory() as tmp:
            manifest=dict(run_id='a'*32,boot_id='boot',image_id='image',max_seconds=120,launch_options=dict(VM_MANAGER='libvirt',VM_CONSOLE='bochs-spice',GENERIC_GRAPHICS='off',CONSOLE_REFRESH='120',CONSOLE_FULL_REFRESH='on',CONSOLE_SNAPSHOT='restart-timing-pool',CONSOLE_EDID='1440p120'))
            path,_=handoff.prepare(tmp,manifest,b'manifest',{},dict.fromkeys(handoff.MODULES,'hash'))
            self.assertEqual(json.loads((path/'admission.json').read_text())['console_edid'],'1440p120')

    def test_outer_and_inner_shell_reject_unreviewed_edid(self):
        outer=(ROOT/'tools/macos-vm.sh').read_text()
        outer=outer[outer.index('case "${CONSOLE_EDID:-default}"'):outer.index('case "${CONSOLE_REFRESH}"')]
        inner=(ROOT/'tools/vm-entry.sh').read_text()
        inner=inner[inner.index('# Explicit presentation-only console:'):inner.index('if [[ -n "${LAN_TAP_NODE:-}" ]]')]
        base=dict(os.environ,CONSOLE_EDID='1440p120',CONSOLE_REFRESH='120',CONSOLE_FULL_REFRESH='on',CONSOLE_SNAPSHOT='restart-timing-pool',VM_MANAGER='libvirt',VM_CONSOLE='bochs-spice',GENERIC_GRAPHICS='off',EXTRA='-display none')
        for change,ok in [({},True),({'CONSOLE_EDID':'default'},True),({'CONSOLE_EDID':'4k120'},False),({'CONSOLE_REFRESH':'60'},False),({'CONSOLE_SNAPSHOT':'restart'},False),({'VM_MANAGER':'direct'},False)]:
            for name,block in [('outer',outer),('inner',inner)]:
                with self.subTest(change=change,name=name):
                    result=subprocess.run(['bash','-c','die(){ exit 1; };\n'+block+'\nprintf "%s" "$EXTRA"'],env=dict(base,**change),capture_output=True,text=True,timeout=3)
                    self.assertEqual(result.returncode==0,ok,result.stderr)
                    if ok and name=='inner':self.assertEqual(',xres=2560,yres=1440,refresh_rate=120000' in result.stdout,change.get('CONSOLE_EDID')!='default')
