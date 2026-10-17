import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location('mn', ROOT/'tools/mode2-noqueue-recover.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class MMIO:
    def __init__(self):
        self.selector = 0
        self.writes = []
        self.fail = False
        self.active = False
        self.values = {v: 0 for v in m.OFFSETS.values()}
        self.values.update({m.R.CP_ME_CNTL_OFFSET: m.R.CP_ME_HALT_MASK,
            m.R.CP_MEC_CNTL_OFFSET: m.R.CP_MEC_HALT_MASK,
            m.R.SDMA0_F32_CNTL_OFFSET: m.R.SDMA_HALT_MASK,
            m.R.SDMA0_STATUS_REG_OFFSET: m.R.SDMA_STATUS_IDLE_MASK,
            m.R.C2PMSG_64_OFFSET: 0x800c0000})

    def read32(self, offset):
        if offset == m.R.CP_HQD_ACTIVE_OFFSET:
            if self.fail:
                raise RuntimeError('read failure')
            return int(self.active and self.selector == m.R.queue_selector(2, 3, 7))
        return self.values.get(offset, 0)

    def write32(self, offset, value):
        if offset != m.R.GRBM_GFX_CNTL_OFFSET:
            raise AssertionError('scan wrote outside selector')
        self.selector = value
        self.writes.append(value)


class RecoveryTests(unittest.TestCase):
    def test_complete_scan_and_no_memory_writes(self):
        raw = MMIO()
        scan = m.scan(raw)
        self.assertEqual(m.scan_errors(scan, final=True), [])
        self.assertEqual(len(scan['passes'][0]['hqd']), 64)
        self.assertEqual(raw.selector, 0)
        self.assertEqual(len(raw.writes), 136)

    def test_exception_restores_default(self):
        raw = MMIO(); raw.fail = True
        with self.assertRaises(RuntimeError): m.scan(raw)
        self.assertEqual(raw.writes[-1], 0)

    def test_every_queue_checked(self):
        raw = MMIO(); raw.active = True
        self.assertIn('hqd_active', m.scan_errors(m.scan(raw)))

    def test_rejects_psp_sdma_poll_allones_missing_global(self):
        for offset, value in ((m.R.C2PMSG_64_OFFSET, 0),
                (m.R.SDMA0_PAGE_RB_CNTL_OFFSET, 1),
                (m.R.SDMA0_RLC_IB_CNTL_OFFSETS[1], 1),
                (m.R.CP_PQ_WPTR_POLL_CNTL_OFFSET, 1),
                (m.R.CP_STAT_OFFSET, 0xffffffff)):
            raw = MMIO(); raw.values[offset] = value
            self.assertTrue(m.scan_errors(m.scan(raw)))
        scan = m.scan(MMIO()); del scan['globals_before']['cp_stat']
        self.assertTrue(m.scan_errors(scan))

    def test_no_psp_writes_on_bad_scan_or_inspection(self):
        raw = MMIO(); raw.active = True
        with patch.object(m.R, 'run_command') as command:
            with self.assertRaises(ValueError): m.teardown(raw, {}, True)
            command.assert_not_called()
            m.teardown(MMIO(), {}, False)
            command.assert_not_called()

    def test_psp_failure_stops_sequence(self):
        with patch.object(m.R, 'run_command', side_effect=RuntimeError('timeout')) as command:
            with self.assertRaises(RuntimeError): m.teardown(MMIO(), {}, True)
            self.assertEqual(command.call_count, 1)

    def test_consumer_reserves_once_and_rejects_replay(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(m.R,'resolve_expected_config_memsize',return_value=2048):
            root = Path(tmp); run, value = self.fixture(root)
            e = m.load('experiment')
            # The helper loaded by the coordinator must receive the real VM path.
            with patch.object(e, 'helper', return_value=m):
                e.reserve_boot(root/'run/used-gpu-boots', 'boot', 'c'*32, recovery=value)
                rows = json.loads((root/'run/used-gpu-boots/boot.json').read_text())['launches']
                self.assertEqual(rows[-1]['recovery_id'], value['recovery_id'])
                with self.assertRaises(ValueError):
                    e.reserve_boot(root/'run/used-gpu-boots', 'boot', 'd'*32, recovery=value)

    def reset(self):
        return dict(boot_id='boot', device=m.R.DEVICE, mode='execute',
            version_probe=dict(message=2, argument=0, response=1, ok=True),
            reset=dict(message=10, argument=2, response=1, ok=True),
            gc_after=dict(CP_STAT=0, RLC_CNTL=0), pci_config_changed_dwords=[],
            pci_command_before=3, pci_command_after=3, memsize_before=2048, memsize_after=2048)

    def test_reset_rejects_timeout_wrong_boot_and_dirty_state(self):
        with patch.object(m.R, 'resolve_expected_config_memsize', return_value=2048):
            self.assertEqual(m.reset_errors(self.reset(), 'boot'), [])
            for key, value in [('boot_id','other'), ('pci_command_after',7),
                               ('memsize_after',0xffffffff), ('pci_config_changed_dwords',[16])]:
                row = self.reset(); row[key] = value
                self.assertTrue(m.reset_errors(row, 'boot'))
            row = self.reset(); row['reset']['response'] = 0
            self.assertTrue(m.reset_errors(row, 'boot'))

    def fixture(self, root):
        run = 'a'*32
        prior = root/'prior'; prior.mkdir()
        for name in m.ARTIFACTS: (prior/name).write_text('{}')
        (prior/'manifest.json').write_text(json.dumps(dict(run_id=run,boot_id='boot')))
        (prior/'shutdown.json').write_text(json.dumps(dict(cid='cid',outcome='already-stopped')))
        (prior/'supervision.json').write_text(json.dumps(dict(cid='cid')))
        (prior/'recovery.json').write_text(json.dumps(dict(status='failed')))
        ledger = root/'run/used-gpu-boots/boot.json'; ledger.parent.mkdir(parents=True)
        ledger.write_text(json.dumps(dict(boot_id='boot',launches=[dict(run_id=run)])))
        _, ledger_sha, hashes = m.input_evidence(root, prior, 'boot')
        host = dict(boot_id='boot',active_vm=False,driver='vfio-pci',device=m.R.DEVICE_ID,
                    iommu_group=m.R.GROUP,pci_command=3,reset_methods=[])
        value = dict(schema=9,kind=m.KIND,status='recovered',authorizes_launch=True,
            boot_id='boot',prior_run_id=run,recovery_id='b'*32,helper_sha256=m.source_hashes(),
            run_directory=str(prior),ledger_sha256=ledger_sha,artifact_sha256=hashes,
            host_before=host,host_after=host,reset=self.reset(),before_teardown=m.scan(MMIO()),
            after_teardown=m.scan(MMIO()),commands=[dict(command=c,confirmed=True,response=c|m.R.READY_FLAG)
                for c in (m.R.DESTROY_RINGS,m.R.DESTROY_GPCOM_RING)],
            kernel_faults=[],kernel_messages=[],kernel_cursor_before='x',kernel_cursor_after='y',errors=[])
        return run, value

    def test_receipt_rejects_stale_artifacts_ledger_helpers_and_commands(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(m.R,'resolve_expected_config_memsize',return_value=2048):
            root = Path(tmp); run, value = self.fixture(root)
            self.assertEqual(m.validate_receipt(value,root,'boot',run), [])
            for key, change in [('authorizes_launch',False),('commands',[]),('helper_sha256',{}),
                    ('ledger_sha256','0'*64),('artifact_sha256',{}),('kernel_messages',['vfio-pci device: reset done']),
                    ('host_after',{}),('after_teardown',{})]:
                bad = copy.deepcopy(value); bad[key] = change
                self.assertTrue(m.validate_receipt(bad,root,'boot',run), key)
            (root/'prior/serial.txt').write_text('changed')
            self.assertTrue(m.validate_receipt(value,root,'boot',run))

    def test_incomplete_teardown_requalification_requires_explicit_denial(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);run,_=self.fixture(root);prior=root/'prior'
            for value in ({'status':'incomplete','authorizes_launch':False},
                          {'status':'failed','authorizes_launch':False}):
                (prior/'recovery.json').write_text(json.dumps(value))
                self.assertEqual(m.input_evidence(root,prior,'boot')[0],run)
            for value in ({'status':'incomplete'},
                          {'status':'incomplete','authorizes_launch':True},
                          {'status':'failed','authorizes_launch':True},
                          {'status':'recovered','authorizes_launch':False}):
                (prior/'recovery.json').write_text(json.dumps(value))
                with self.assertRaises(ValueError):m.input_evidence(root,prior,'boot')
            (prior/'recovery.json').write_text(json.dumps({'status':'incomplete','authorizes_launch':False}))
            # Prior outcome never overrides latest-run or confirmed-shutdown checks.
            (prior/'shutdown.json').write_text(json.dumps({'cid':'other','outcome':'forced'}))
            with self.assertRaises(ValueError):m.input_evidence(root,prior,'boot')

    def test_authorizing_receipt_upgrade_requires_canonical_and_original_full_proof(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            vm = Path(tmp); run, _ = self.fixture(vm); prior = vm/'prior'
            receipt = dict(schema=6, status='recovered', authorizes_launch=True,
                           boot_id='boot', prior_run_id=run)
            (prior/'recovery.json').write_text(json.dumps(receipt))
            canonical = vm/'run/vfio-recovery/boot'/(run+'.json')
            canonical.parent.mkdir(parents=True)
            with self.assertRaises(ValueError):
                m.input_evidence(vm, prior, 'boot')
            canonical.write_text(json.dumps(receipt))
            validator = SimpleNamespace(validate_recovery_receipt_v6=lambda *_: ['bad-old-proof'])
            with patch.object(m, 'load', return_value=validator):
                with self.assertRaises(ValueError):
                    m.input_evidence(vm, prior, 'boot')
            validator.validate_recovery_receipt_v6 = lambda *_: []
            with patch.object(m, 'load', return_value=validator):
                self.assertEqual(m.input_evidence(vm, prior, 'boot')[0], run)
                canonical.write_text(json.dumps(dict(receipt, prior_run_id='b'*32)))
                with self.assertRaises(ValueError):
                    m.input_evidence(vm, prior, 'boot')

    def test_uncaptured_cancellation_binds_failure_and_rejects_ambiguous_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); run, _ = self.fixture(root); prior = root/'prior'
            (prior/'recovery.json').unlink(); (prior/'supervision.json').unlink()
            (prior/'serial.txt').write_bytes(b''); (prior/'critical.txt').write_bytes(b'')
            (prior/'shutdown.json').write_text('null')
            error = 'RuntimeError: experiment cancelled'
            (prior/'verdict.json').write_text(json.dumps(dict(error=error)))
            (prior/'wrapper-result.json').write_text(json.dumps(dict(run_id=run,valid=False,error=error)))
            host = dict(boot_id='boot',active_vm=False,driver='vfio-pci',device=m.R.DEVICE_ID,iommu_group=m.R.GROUP)
            (prior/'host-after.json').write_text(json.dumps(host))
            (prior/'host-kernel-messages.json').write_text('[]')
            self.assertEqual(m.input_evidence(root,prior,'boot')[0],run)
            for name, content in [('serial.txt',b'guest booted'),('critical.txt',b'CR2'),
                                  ('shutdown.json',b'{}'),('supervision.json',b'{}')]:
                path = prior/name; old = path.read_bytes() if path.exists() else None
                path.write_bytes(content)
                with self.assertRaises(ValueError):m.input_evidence(root,prior,'boot')
                path.unlink() if old is None else path.write_bytes(old)
            host['active_vm'] = True; (prior/'host-after.json').write_text(json.dumps(host))
            with self.assertRaises(ValueError):m.input_evidence(root,prior,'boot')

    def test_consumer_routes_schema9_and_requires_vm(self):
        e = m.load('experiment')
        self.assertEqual(e.validate_reuse_receipt({'schema':9},'b','p'), ['mode2_noqueue_receipt'])


    def test_requalification_preserves_original_and_latest_never_falls_back(self):
        import os
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);registry=root/'run/vfio-recovery'/'boot'
            registry.mkdir(parents=True)
            original=registry/'prior.json';original.write_text('original evidence')
            self.assertEqual(m.receipt_path(root,'boot','prior'),original)
            first=registry/'prior.requalified.first.json';first.write_text('qualification 1')
            second=registry/'prior.requalified.second.json';second.write_text('invalid latest')
            os.utime(first,ns=(1,1));os.utime(second,ns=(2,2))
            self.assertEqual(m.receipt_path(root,'boot','prior'),second)
            self.assertEqual(original.read_text(),'original evidence')



    def test_fresh_recovery_publishes_separate_receipt_without_overwriting_original(self):
        import contextlib
        import hashlib
        with tempfile.TemporaryDirectory() as directory:
            vm=Path(directory);(vm/'run').mkdir()
            boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
            run='a'*32
            original=vm/'run/vfio-recovery'/boot/(run+'.json')
            original.parent.mkdir(parents=True);original.write_bytes(b'original receipt')
            output=vm/'fresh.json';raw=MMIO()
            def command(mmio, value, label):
                return {'command':value,'response':value|m.R.READY_FLAG,'confirmed':True}
            with patch.object(m,'input_evidence',return_value=(run,'ledger',{})), \
                 patch.object(m,'host_gate',return_value={}), \
                 patch.object(m.M,'run',return_value={}), \
                 patch.object(m,'reset_errors',return_value=[]), \
                 patch.object(m.R,'LegacyVfio',return_value=contextlib.nullcontext(raw)), \
                 patch.object(m.R,'kernel_updates',return_value=('cursor',[],[])), \
                 patch.object(m.R,'run_command',side_effect=command), \
                 patch.object(m,'validate_receipt',return_value=[]):
                value=m.recover(vm,vm/'prior',output,execute=True)
            self.assertTrue(value['authorizes_launch'])
            self.assertEqual(original.read_bytes(),b'original receipt')
            self.assertEqual(value['prior_receipt_sha256'],hashlib.sha256(b'original receipt').hexdigest())
            qualified=list(original.parent.glob(run+'.requalified.*.json'))
            self.assertEqual(len(qualified),1)
            self.assertEqual(json.loads(qualified[0].read_text()),json.loads(output.read_text()))



    def test_requalified_receipt_binds_immutable_original(self):
        import hashlib
        with tempfile.TemporaryDirectory() as directory, patch.object(m.R,'resolve_expected_config_memsize',return_value=2048):
            root=Path(directory);run,value=self.fixture(root)
            original=root/'run/vfio-recovery'/'boot'/(run+'.json')
            original.parent.mkdir(parents=True);original.write_bytes(b'original')
            value['prior_receipt_sha256']=hashlib.sha256(b'original').hexdigest()
            self.assertEqual(m.validate_receipt(value,root,'boot',run),[])
            original.write_bytes(b'mutated')
            self.assertEqual(m.validate_receipt(value,root,'boot',run),['mode2_noqueue_prior_receipt'])



if __name__ == '__main__': unittest.main()
