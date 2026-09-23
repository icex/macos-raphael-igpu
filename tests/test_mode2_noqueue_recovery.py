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

    def test_consumer_routes_schema9_and_requires_vm(self):
        e = m.load('experiment')
        self.assertEqual(e.validate_reuse_receipt({'schema':9},'b','p'), ['mode2_noqueue_receipt'])


if __name__ == '__main__': unittest.main()
