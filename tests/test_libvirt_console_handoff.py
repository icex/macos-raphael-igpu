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

if __name__=='__main__':unittest.main()
