import copy, importlib.util, unittest
import json
import tempfile
from unittest import mock
from pathlib import Path

P=Path(__file__).parents[1]/'tools/noqueue-qualification.py'
s=importlib.util.spec_from_file_location('nq',P); nq=importlib.util.module_from_spec(s); s.loader.exec_module(nq)

class NoQueueTests(unittest.TestCase):
    def base(self):
        g={'cp_stat':0,'cpc_busy':0,'me_cntl':nq.R.CP_ME_HALT_MASK,'mec_cntl':nq.R.CP_MEC_HALT_MASK,'rb_doorbell_control':0,'pq_wptr_poll_cntl':0,'pq_status':0,'c2pmsg_64':0x80030000,'sdma0_cntl':0,'sdma0_f32_cntl':nq.R.SDMA_HALT_MASK,'sdma0_status':nq.R.SDMA_STATUS_IDLE_MASK,'sdma0_gfx_rb_cntl':0,'sdma0_gfx_ib_cntl':0,'sdma0_page_rb_cntl':0,'sdma0_page_ib_cntl':0,'sdma0_rlc0_rb_cntl':0,'sdma0_rlc0_ib_cntl':0,'sdma0_rlc1_rb_cntl':0,'sdma0_rlc1_ib_cntl':0}
        rows=[[m,p,q,0,0] for m in (1,2) for p in range(4) for q in range(8)]
        gr=[[0,0,0,0],[1,0,0,0]]; x={'hqd':rows,'graphics':gr,'globals':dict(g)}
        return {'vfio_opened':True,'errors':[],'kernel_faults_before':[],'kernel_faults_after':[],'kernel_cursor_before':'x','kernel_cursor_after':'x','globals_before':g,'globals_after':dict(g),'passes':[x,{'hqd':list(rows),'graphics':list(gr),'globals':dict(g)}],'selector_final':0}
    def test_positive(self): self.assertEqual(nq.validate_snapshot(self.base()),[])
    def test_rejects_queue_psp_sdma_poll_and_allones(self):
        for key, value in [('c2pmsg_64',0),('pq_status',1),('sdma0_page_rb_cntl',1),('cp_stat',0xffffffff)]:
            e=self.base(); e['globals_before'][key]=value; e['globals_after'][key]=value
            for x in e['passes']: x['globals'][key]=value
            got=nq.validate_snapshot(e)
            self.assertIn({'c2pmsg_64':'psp_mailbox','pq_status':'global_not_idle','sdma0_page_rb_cntl':'sdma_enabled','cp_stat':'global_not_idle'}[key],got)
    def test_rejects_missing_duplicate_and_active_queue(self):
        e=self.base(); e['passes'][0]['hqd'][0][3]=1; e['passes'][1]['hqd'][0][3]=1
        self.assertIn('hqd_active',nq.validate_snapshot(e))
        e=self.base(); e['passes'][0]['hqd']=e['passes'][0]['hqd'][:-1]; e['passes'][1]['hqd']=e['passes'][1]['hqd'][:-1]
        self.assertIn('hqd_coverage',nq.validate_snapshot(e))
    def test_rejects_unstable_and_kernel_error(self):
        e=self.base(); e['passes'][1]['graphics'][0][1]=1; self.assertTrue(nq.validate_snapshot(e)); e=self.base(); e['kernel_faults_after']=['fault']; self.assertTrue(nq.validate_snapshot(e))
    def test_validate_proof_requires_exact_schema_identity_and_hashes(self):
        e=self.base(); h={'boot_id':'b','active_vm':False,'driver':'vfio-pci','device':'1002:13c0','iommu_group':'31','pci_command':0,'reset_methods':[]}; e.update(schema=8, kind='same-boot-noqueue-qualification', authorizes_launch=True, boot_id='b', run_id='n', prior_run_id='p', ledger_preimage_sha256=nq.sha(b'{"boot_id":"b","launches":[{"run_id":"p"}],"max_launches":3}'), manifest_sha256=nq.sha(b'm'), helper_sha256={str(p):nq.sha(p.read_bytes()) for p in (Path(nq.__file__),Path(nq.R.__file__),Path(nq.N.__file__))},host_before=h,host_after=h,power_control='on',runtime_status='active')
        ledger=b'{"boot_id":"b","launches":[{"run_id":"p"}],"max_launches":3}'
        self.assertEqual(nq.validate_proof(e,'b','n',ledger,nq.sha(b'm')),[])
        e['authorizes_launch']=False; self.assertIn('not_authorized',nq.validate_proof(e,'b','n',b'x',nq.sha(b'm')))

    def proof(self, ledger):
        e=self.base()
        host={'boot_id':'b','active_vm':False,'driver':'vfio-pci','device':'1002:13c0',
              'iommu_group':'31','pci_command':0,'reset_methods':[]}
        e.update(schema=8,kind='same-boot-noqueue-qualification',authorizes_launch=True,
                 boot_id='b',run_id='n',prior_run_id='p',ledger_preimage_sha256=nq.sha(ledger),
                 manifest_sha256=nq.sha(b'm'),
                 helper_sha256={str(p):nq.sha(p.read_bytes()) for p in
                                (Path(nq.__file__),Path(nq.R.__file__),Path(nq.N.__file__))},
                 host_before=host,host_after=host,power_control='on',runtime_status='active')
        return e

    def history(self):
        return {'boot_id':'b','max_launches':3,
                'launches':[{'run_id':'old-'+str(i)} for i in range(11)]+[{'run_id':'p'}]}

    def test_more_than_three_rows_passes_proof_without_weakening_bindings(self):
        ledger=json.dumps(self.history()).encode();proof=self.proof(ledger)
        self.assertEqual(nq.validate_proof(proof,'b','n',ledger,nq.sha(b'm')),[])
        cases=[('prior_run_id','old-0','prior_run'),
               ('ledger_preimage_sha256','0'*64,'ledger_sha256'),
               ('manifest_sha256','0'*64,'manifest_sha256')]
        for key,value,error in cases:
            changed=copy.deepcopy(proof);changed[key]=value
            with self.subTest(key=key):
                self.assertIn(error,nq.validate_proof(changed,'b','n',ledger,nq.sha(b'm')))
        history=self.history();history['launches'][0]['run_id']='n'
        reused=json.dumps(history).encode()
        self.assertIn('run_id_reused',nq.validate_proof(self.proof(reused),'b','n',reused,nq.sha(b'm')))

    def test_malformed_or_duplicate_history_still_refuses(self):
        for history in [{'boot_id':'other','launches':[{'run_id':'p'}]},
                        {'boot_id':'b','launches':[]},
                        {'boot_id':'b','launches':['p']},
                        {'boot_id':'b','launches':[{'run_id':1}]},
                        {'boot_id':'b','launches':[{'run_id':'p'},{'run_id':'p'}]}]:
            ledger=json.dumps(history).encode()
            with self.subTest(history=history):
                self.assertIn('ledger_malformed',nq.validate_proof(self.proof(ledger),'b','n',ledger,nq.sha(b'm')))

    def test_authorize_long_history_reaches_unchanged_full_stopped_scan(self):
        # Simulated register transport only: no sysfs/device opens or processes.
        baseline=self.base();host=self.proof(b'')['host_before']
        values=dict(baseline['globals_before'],rb0_active=0,rb1_active=0)
        offsets=dict(nq.N.GLOBAL_OFFSETS,c2pmsg_64=nq.R.C2PMSG_64_OFFSET,
                     sdma0_status=nq.R.SDMA0_STATUS_REG_OFFSET,
                     sdma0_page_rb_cntl=nq.R.SDMA0_PAGE_RB_CNTL_OFFSET,
                     sdma0_page_ib_cntl=nq.R.SDMA0_PAGE_IB_CNTL_OFFSET,
                     sdma0_rlc0_rb_cntl=nq.R.SDMA0_RLC_RB_CNTL_OFFSETS[0],
                     sdma0_rlc0_ib_cntl=nq.R.SDMA0_RLC_IB_CNTL_OFFSETS[0],
                     sdma0_rlc1_rb_cntl=nq.R.SDMA0_RLC_RB_CNTL_OFFSETS[1],
                     sdma0_rlc1_ib_cntl=nq.R.SDMA0_RLC_IB_CNTL_OFFSETS[1])
        registers={offset:values.get(name,0) for name,offset in offsets.items()}
        raw=mock.MagicMock()
        raw.__enter__.return_value=raw
        raw.read32.side_effect=lambda offset: registers.get(offset,0)
        original_read=Path.read_text
        def read_text(path,*args,**kwargs):
            if str(path)=='/sys/bus/pci/devices/0000:7b:00.0/power/control':return 'on'
            if str(path)=='/sys/bus/pci/devices/0000:7b:00.0/power/runtime_status':return 'active'
            return original_read(path,*args,**kwargs)
        with tempfile.TemporaryDirectory() as temp:
            vm=Path(temp);prior=vm/'prior';prior.mkdir()
            used=vm/'run/used-gpu-boots';used.mkdir(parents=True)
            (used/'b.json').write_text(json.dumps(self.history()))
            (prior/'manifest.json').write_text(json.dumps({'run_id':'p','boot_id':'b'}))
            (prior/'verdict.json').write_text(json.dumps({'verdict':'INVALID','earliest_failure':'identity_or_route_missing'}))
            for name in ('serial.txt','critical.txt'):(prior/name).write_bytes(b'')
            mp=vm/'manifest.json';mp.write_bytes(b'm')
            with mock.patch.object(nq.R,'host_state',return_value=host), \
                 mock.patch.object(nq.R,'validate_host_state',return_value=[]), \
                 mock.patch.object(nq.R,'kernel_updates',return_value=('x',[],[])), \
                 mock.patch.object(nq.R,'LegacyVfio',return_value=raw) as transport, \
                 mock.patch.object(nq.N,'GuardedTransport',side_effect=lambda value:value), \
                 mock.patch.object(nq.N,'OBSERVATION_OFFSETS',set(nq.N.OBSERVATION_OFFSETS)), \
                 mock.patch.object(nq.subprocess,'run',return_value=mock.Mock(stdout='')), \
                 mock.patch.object(Path,'read_text',read_text):
                evidence=nq.authorize(vm,prior,{'run_id':'n','boot_id':'b'},mp,{'run_id':'p'},nq.R,nq.N)
                self.assertTrue(evidence['authorizes_launch'],evidence['errors'])
                self.assertEqual(len(evidence['passes']),2)
                self.assertEqual([len(p['hqd']) for p in evidence['passes']],[64,64])
                self.assertEqual([len(p['graphics']) for p in evidence['passes']],[2,2])
                transport.assert_called_once()
                transport.reset_mock()
                evidence=nq.authorize(vm,prior,{'run_id':'old-0','boot_id':'b'},mp,{'run_id':'p'},nq.R,nq.N)
                self.assertIn('run_id_reused',evidence['errors']);transport.assert_not_called()
                history=self.history();history['launches'].append({'run_id':'later'})
                (used/'b.json').write_text(json.dumps(history))
                evidence=nq.authorize(vm,prior,{'run_id':'n','boot_id':'b'},mp,{'run_id':'p'},nq.R,nq.N)
                self.assertIn('prior_run_latest',evidence['errors']);transport.assert_not_called()

if __name__=='__main__': unittest.main()
