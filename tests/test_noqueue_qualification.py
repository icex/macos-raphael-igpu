import copy, importlib.util, unittest
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

if __name__=='__main__': unittest.main()
