import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('handoff_console',ROOT/'tools/libvirt-console-handoff.py')
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.modules={}
        for name in mod.MODULES:
            (self.root/name).write_text(name);self.modules[name]=mod.sha(name.encode())
        manifest=dict(run_id='a'*32,boot_id='boot',image_id='image',max_seconds=120,
                      launch_options={'VM_MANAGER':'libvirt'})
        self.path,self.digest=mod.prepare(self.root,manifest,json.dumps(manifest).encode(),{'test':'network'},self.modules)
        self.data=json.loads((self.path/'admission.json').read_text())
        self.paused=dict(run_id='a'*32,paused=True,plan_sha256='b'*64,
                         identity={'pid':45,'start_ticks':123},scope={'init_start_ticks':100})
        self.state=dict(cid='c'*64,started_at='start',deadline_epoch=self.data['deadline_epoch']+2)
    def tearDown(self):self.tmp.cleanup()
    def test_admission_modules_and_exclusive_publication(self):
        self.assertTrue(mod.validate_admission(self.data,'a'*32,self.digest,self.root,'boot'))
        self.assertEqual((self.path/'admission.json').stat().st_mode&0o777,0o600)
        with self.assertRaises(FileExistsError):mod.write_once(self.path/'admission.json',{})
        (self.root/mod.MODULES[0]).write_text('changed')
        with self.assertRaisesRegex(ValueError,'module'):mod.validate_admission(self.data,'a'*32,self.digest,self.root,'boot')
    def test_stale_run_boot_and_expired_admission_refuse(self):
        for run,boot,now in [('b'*32,'boot',time.time()),('a'*32,'other',time.time()),('a'*32,'boot',self.data['deadline_epoch']+1)]:
            with self.assertRaises(ValueError):mod.validate_admission(self.data,run,self.digest,self.root,boot,now)
    def test_permit_binds_exact_inspected_identity_and_original_deadline(self):
        permit=mod.permit(self.data,self.digest,self.paused,copy.deepcopy(self.paused),self.state)
        self.assertTrue(mod.validate_permit(permit,self.data,self.digest,self.paused))
        for field in ['cid','started_at','deadline_epoch','paused']:
            self.assertIn(field,permit)
        permit['deadline_epoch']+=1
        with self.assertRaisesRegex(ValueError,'extended'):mod.validate_permit(permit,self.data,self.digest,self.paused)
    def test_different_process_or_unpaused_observation_refuses_release(self):
        bad=copy.deepcopy(self.paused);bad['identity']['start_ticks']+=1
        with self.assertRaisesRegex(ValueError,'paused identity'):mod.permit(self.data,self.digest,self.paused,bad,self.state)
        bad=copy.deepcopy(self.paused);bad['paused']=False
        with self.assertRaises(ValueError):mod.permit(self.data,self.digest,bad,bad,self.state)
    def test_outer_deadline_may_not_be_extended(self):
        state=dict(self.state,deadline_epoch=self.data['deadline_epoch']-1)
        with self.assertRaisesRegex(ValueError,'outer deadline'):mod.permit(self.data,self.digest,self.paused,self.paused,state)
    def test_run_directory_refuses_path_escape(self):
        with self.assertRaises(ValueError):mod.run_directory(self.root,'../other')

class RefreshAdmissionTests(unittest.TestCase):
    def test_snapshot_admission_exact_profile_and_no_side_effect_on_refusal(self):
        base=dict(VM_MANAGER='libvirt',VM_CONSOLE='bochs-spice',GENERIC_GRAPHICS='off',
                  CONSOLE_REFRESH='60',CONSOLE_FULL_REFRESH='on',CONSOLE_SNAPSHOT='on')
        cases=[({},True),({'CONSOLE_SNAPSHOT':'off'},True),({'CONSOLE_SNAPSHOT':True},False),
               ({'VM_CONSOLE':'bochs'},False),({'GENERIC_GRAPHICS':'on'},False),
               ({'CONSOLE_FULL_REFRESH':'off'},False),({'CONSOLE_REFRESH':'default'},False)]
        for change,ok in cases:
            with self.subTest(change=change),tempfile.TemporaryDirectory() as tmp:
                manifest=dict(run_id='a'*32,boot_id='boot',image_id='image',max_seconds=120,
                              launch_options=dict(base,**change))
                if ok:
                    path,_=mod.prepare(tmp,manifest,b'manifest',{},dict.fromkeys(mod.MODULES,'hash'))
                    data=json.loads((path/'admission.json').read_text())
                    self.assertEqual(data['console_snapshot'],manifest['launch_options']['CONSOLE_SNAPSHOT'])
                else:
                    with self.assertRaises(ValueError):mod.prepare(tmp,manifest,b'manifest',{},dict.fromkeys(mod.MODULES,'hash'))
                    self.assertEqual(list(Path(tmp).iterdir()),[])

    def test_new_receipt_binds_default_and_explicit_refresh(self):
        for value in (None,'60'):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as tmp:
                options={'VM_MANAGER':'libvirt'}
                if value is not None:options['CONSOLE_REFRESH']=value
                manifest=dict(run_id='a'*32,boot_id='boot',image_id='image',max_seconds=120,launch_options=options)
                path,_=mod.prepare(tmp,manifest,b'manifest',{},dict.fromkeys(mod.MODULES,'hash'))
                self.assertEqual(json.loads((path/'admission.json').read_text())['console_refresh'],value or 'default')
    def test_full_refresh_receipt_binds_and_rejects_invalid_values(self):
        for value in ('off','on',True,'yes'):
            with self.subTest(value=value),tempfile.TemporaryDirectory() as tmp:
                manifest=dict(run_id='a'*32,boot_id='boot',image_id='image',max_seconds=120,
                              launch_options={'VM_MANAGER':'libvirt','CONSOLE_REFRESH':'60','CONSOLE_FULL_REFRESH':value})
                if value in ('off','on'):
                    path,_=mod.prepare(tmp,manifest,b'manifest',{},dict.fromkeys(mod.MODULES,'hash'))
                    self.assertEqual(json.loads((path/'admission.json').read_text())['console_full_refresh'],value)
                else:
                    with self.assertRaises(ValueError):mod.prepare(tmp,manifest,b'manifest',{},dict.fromkeys(mod.MODULES,'hash'))
                    self.assertEqual(list(Path(tmp).iterdir()),[])

    def test_full_refresh_cannot_use_historical_refresh_or_unknown_admission(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest=dict(launch_options={'VM_MANAGER':'libvirt','CONSOLE_FULL_REFRESH':'on'})
            with self.assertRaisesRegex(ValueError,'requires explicit'):mod.prepare(tmp,manifest,b'',{}, {})
            self.assertEqual(list(Path(tmp).iterdir()),[])
            for value in (None,True,'yes',60):
                data=dict(schema=1,run_id='a'*32,boot_id='boot',console_full_refresh=value)
                with self.assertRaisesRegex(ValueError,'invalid admitted console full'):mod.validate_admission(data,'a'*32,mod.digest(data),tmp,'boot')

    def test_invalid_requested_refresh_cannot_publish_admission(self):
        for value in ('30','120',60,True,None,''):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as tmp:
                manifest=dict(launch_options={'VM_MANAGER':'libvirt','CONSOLE_REFRESH':value})
                with self.assertRaisesRegex(ValueError,'refresh'):mod.prepare(tmp,manifest,b'',{}, {})
                self.assertEqual(list(Path(tmp).iterdir()),[])
    def test_historical_receipt_is_default_and_unknown_values_refuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);hashes={}
            for name in mod.MODULES:
                (root/name).write_text(name);hashes[name]=mod.sha(name.encode())
            old=dict(schema=1,run_id='a'*32,boot_id='boot',manifest_sha256='b'*64,deadline_epoch=200,modules_sha256=hashes)
            self.assertTrue(mod.validate_admission(old,'a'*32,mod.digest(old),root,'boot',100))
            for value in ('default','60'):
                item=dict(old,console_refresh=value)
                self.assertTrue(mod.validate_admission(item,'a'*32,mod.digest(item),root,'boot',100))
            for value in ('30',60,None):
                item=dict(old,console_refresh=value)
                with self.assertRaisesRegex(ValueError,'refresh'):mod.validate_admission(item,'a'*32,mod.digest(item),root,'boot',100)

if __name__=='__main__':unittest.main()
