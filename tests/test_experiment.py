import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import subprocess
import plistlib
import hashlib
import threading
from unittest.mock import patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


class ExperimentTests(unittest.TestCase):
    def module(self):
        path = ROOT / 'tools/experiment.py'
        self.assertTrue(path.exists(), 'missing experiment admission tool')
        spec = importlib.util.spec_from_file_location('experiment', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def recovery_receipt(self, tool, prior='a'*32, recovery='b'*32):
        reservation = {
            'version':1, 'state':tool.RECOVERY_RESERVATION_ACTIVE,
            'heap_limit':tool.RECOVERY_HEAP_LIMIT,
            'reservation_start':tool.RECOVERY_RESERVATION_START,
            'scratch_start':tool.RECOVERY_SCRATCH_START,
            'reservation_end':tool.RECOVERY_RESERVATION_END,
            'run_id':prior, 'checksum':tool._recovery_checksum(prior),
            'consumed':True,
            'consume_hdp_flush':{'remap':0x7f000, 'posted_read':0x200},
        }
        active_observation = {key:value for key,value in reservation.items()
                              if key not in ('consumed', 'consume_hdp_flush')}
        def graphics_snapshot():
            def row(pipe):
                doorbell = 0
                return {
                    'intended_pipe':pipe, 'selector':pipe,
                    'rb0_active':0, 'rb1_active':0, 'active':0,
                    'doorbell_control':doorbell,
                    'doorbell_offset':doorbell & 0x0ffffffc,
                    'doorbell_status':doorbell & 0xc0000002,
                    'wptr':0, 'wptr_hi':0, 'base':0, 'base_hi':0, 'cntl':0,
                }
            return {'pipes':[row(0), row(1)],
                    'final_default':{'value':0, 'completed':True}}
        guard_snapshot = graphics_snapshot()
        before_snapshot = graphics_snapshot()
        after_snapshot = graphics_snapshot()
        final_snapshot = graphics_snapshot()
        regions = json.loads(json.dumps(tool.RECOVERY_BAR_REGIONS))
        return {
            'schema':5, 'status':'recovered', 'authorizes_launch':True,
            'boot_id':'boot-A', 'prior_run_id':prior, 'recovery_id':recovery,
            'device':'0000:7b:00.0', 'iommu_group':'31', 'driver':'vfio-pci',
            'pci_command_before':3, 'pci_command_after':3,
            'reset_methods_before':[], 'reset_methods_after':[],
            'bar5':dict(regions['5'], regions=regions), 'kernel_messages':[],
            'gc_quiesce':{
                'status':'quiesced', 'active_after':0,
                'dequeue_timeouts':0, 'forced_inactive':0,
                'cp_stat_after':0, 'cp_cpc_busy_after':0,
                'cp_me_after':0x15000000, 'cp_mec_after':0x50000000,
                'pq_wptr_poll_after':0, 'pq_status_after':0,
                'doorbell_range_lower_after':0, 'doorbell_range_upper_after':0,
                'sdma0_after':1, 'sdma0_cntl_after':0,
                'sdma0_rb_after':0, 'sdma0_ib_after':0,
                'gfx_ring_clean':True, 'gfx_retirement_confirmed':True,
                'graphics_pipe_proof_complete':True,
                'gfx_needs_unmap':False, 'gfx_was_stale':False,
                'host_kiq':{'status':'not-needed'}, 'reservation':reservation,
                'graphics_pipe_guard':{
                    'policy':'x6000-24G830-single-legacy-gfx-pipe-v1',
                    'reservation_before':active_observation,
                    'reservation_after':dict(active_observation),
                    'reservation_unchanged':True,
                    'pipe1_supported_state':True,
                    'snapshot':guard_snapshot,
                },
                'graphics_pipes_before':before_snapshot,
                'graphics_pipes_after_retirement':after_snapshot,
                'graphics_pipes_final':final_snapshot,
                'gfx_rb_active_after':0, 'gfx_rb_doorbell_after':0,
                'gfx_rb_wptr_after':0, 'gfx_rb_wptr_hi_after':0,
                'gfx_rb_base_after':0, 'gfx_rb_base_hi_after':0,
                'gfx_rb_cntl_after':0,
            },
            'commands':[
                {'command':0x00030000, 'response':0x80030000, 'confirmed':True},
                {'command':0x000c0000, 'response':0x800c0000, 'confirmed':True},
            ],
        }

    def host_kiq_receipt(self, tool, prior='a'*32):
        receipt = self.recovery_receipt(tool, prior)
        gc = receipt['gc_quiesce']
        fb = 0xf400000000
        physical_fb = 0x840000000
        gart_offset = 0x0e000000
        gc.update(gfx_needs_unmap=True, gfx_was_stale=True)
        before_pipe0 = gc['graphics_pipes_before']['pipes'][0]
        before_pipe0.update(rb0_active=1, active=1,
                            doorbell_control=0xc0000400,
                            doorbell_offset=0x400,
                            doorbell_status=0xc0000000)
        gc['host_kiq'] = {
            'status':'retired', 'selector':9, 'cleanup_confirmed':True,
            'gfx_active_after_unmap':0, 'gfx_active_before_scrub':0,
            'graphics_pipes_after_unmap':gc['graphics_pipes_after_retirement'],
            'packet_dwords':0x100, 'rptr_after':0x100,
            'fence_sequence':0x12345678, 'fence_after':0x12345678,
            'gfx_doorbell_offset':0x400,
            'hdp_flush':{'remap':0x7f000, 'posted_read':0x200},
            'reservation':gc['reservation'],
            'addresses':{
                'ring':fb+0x0f100000, 'mqd':fb+0x0f110000,
                'rptr':fb+0x0f111000, 'wptr':fb+0x0f111008,
                'eop':fb+0x0f112000, 'fence':fb+0x0f113000},
            'gart':{'control':1, 'root':physical_fb+gart_offset+1,
                    'start_page':0, 'end_page':0xff,
                    'physical_fb':physical_fb, 'bar_offset':gart_offset,
                    'size':0x800, 'active':True},
            'cleanup':{'mec_cntl':0x50000000, 'hqd_active':0,
                       'hqd_doorbell':0, 'hqd_rptr':0,
                       'hqd_wptr_lo':0, 'hqd_wptr_hi':0,
                       'pq_status':0, 'doorbell_range_lower':0,
                       'doorbell_range_upper':0, 'wptr_poll_cntl':0},
            'final_gate':{
                'active_after':0, 'cp_stat_after':0,
                'cp_cpc_busy_after':0, 'pq_wptr_poll_after':0,
                'pq_status_after':0, 'doorbell_range_lower_after':0,
                'doorbell_range_upper_after':0,
                'gfx_ring_clean':True, 'gfx_retirement_confirmed':True,
                'graphics_pipe_proof_complete':True},
        }
        return receipt

    def schema6_recovery_receipt(self, tool, prior='a'*32, recovery='b'*32):
        receipt = self.recovery_receipt(tool, prior, recovery)
        receipt['schema'] = 6
        gc = receipt['gc_quiesce']
        gc.update({
            'sdma0_before':0x20,
            'sdma0_cntl_before':0x00040021,
            'sdma0_rb_before':0x80840021,
            'sdma0_ib_before':0x101,
            'sdma0_page_ib_before':0x101,
            'sdma0_page_ib_after':0x100,
            'sdma0_page_rb_before':0x80840021,
            'sdma0_page_rb_after':0x80840020,
            'sdma0_status_before':1,
            'sdma0_status_after':1,
            'sdma0_shutdown_trace':[
                {'step':'disable-page-ib', 'register':0x4d08,
                 'before':0x101, 'written':0x100, 'readback':0x100},
                {'step':'disable-page-rb', 'register':0x4ce0,
                 'before':0x80840021, 'written':0x80840020,
                 'readback':0x80840020},
            ],
            'sdma0_rlc_inputs':[
                {'index':0, 'rb_before':0x200, 'rb_after':0x200,
                 'ib_before':0x100, 'ib_after':0x100},
                {'index':1, 'rb_before':0x204, 'rb_after':0x204,
                 'ib_before':0x104, 'ib_after':0x104},
            ],
        })
        return receipt

    def schema6_host_kiq_receipt(self, tool, prior='a'*32):
        receipt = self.host_kiq_receipt(tool, prior)
        page_proof = self.schema6_recovery_receipt(tool, prior)['gc_quiesce']
        receipt['schema'] = 6
        for key in ('sdma0_before', 'sdma0_cntl_before',
                    'sdma0_rb_before', 'sdma0_ib_before',
                    'sdma0_page_ib_before', 'sdma0_page_ib_after',
                    'sdma0_page_rb_before', 'sdma0_page_rb_after',
                    'sdma0_status_before', 'sdma0_status_after',
                    'sdma0_shutdown_trace', 'sdma0_rlc_inputs'):
            receipt['gc_quiesce'][key] = page_proof[key]
        return receipt

    def test_identity_mismatches_and_missing_values_fail_closed(self):
        validate = self.module().validate_identity
        expected = dict(binary_sha256='a'*64, info_sha256='b'*64, boot_args='rgpu=1',
                        kdk_sha256={'HWLibs': 'c'*64}, build_id='candidate')
        self.assertEqual(validate(expected, dict(expected)), [])
        for key in expected:
            for value in (None, 'stale'):
                observed = dict(expected, **{key: value})
                self.assertIn(key, validate(expected, observed))

    def test_production_manifest_requires_all_identity_fields(self):
        check = getattr(self.module(), 'required_identity', None)
        self.assertIsNotNone(check, 'production identity completeness check missing')
        missing = check({'build_id': 'candidate'})
        for key in ('source_commit', 'kdk_sha256', 'binary_sha256', 'info_sha256',
                    'config_sha256', 'boot_args', 'image_id', 'probe_binary_sha256'):
            self.assertIn(key, missing)

    def test_requested_diagnostic_is_part_of_boot_identity(self):
        validate = self.module().boot_argument_errors
        baseline = ('-v rgpu=0xfffa5981 rgpuvmm=3 rgpumem=2 rgpuptb=2 '
                    'rgpumqd=2 rgpuhybrid=1 rgpusdma=1')
        self.assertEqual(validate(baseline, 'rgpusdma=1'), [])
        self.assertIn('requested_diagnostic',
                      validate(baseline.replace(' rgpusdma=1', ''), 'rgpusdma=1'))
        self.assertIn('requested_diagnostic',
                      validate(baseline.replace('rgpusdma=1', 'rgpusdma=0'), 'rgpusdma=1'))
        self.assertIn('functional_baseline',
                      validate(baseline.replace('rgpumqd=2', 'rgpumqd=1'), 'rgpusdma=1'))
        self.assertIn('retired_experiment', validate(baseline+' rgpureset=1', 'rgpusdma=1'))

    def test_raphael_target_marker_is_exact_and_bound_to_the_vbios_device(self):
        tool = self.module()
        check = getattr(tool, 'raphael_target_marked', None)
        self.assertIsNotNone(check, 'per-device Raphael identity check missing')
        path = 'PciRoot(0x0)/Pci(0x6,0x0)'
        config = {'DeviceProperties': {'Add': {path: {
            'ATY,bin_image': b'VBIOS',
            'rgpu,raphael-target': b'RGPU-RAPHAEL\x01'}}}}
        self.assertTrue(check(config))
        for value in (None, b'RGPU-RAPHAEL', b'RGPU-RAPHAEL\x00', 'RGPU-RAPHAEL\x01'):
            changed = {'DeviceProperties': {'Add': {path: dict(config['DeviceProperties']['Add'][path])}}}
            if value is None:
                changed['DeviceProperties']['Add'][path].pop('rgpu,raphael-target')
            else:
                changed['DeviceProperties']['Add'][path]['rgpu,raphael-target'] = value
            self.assertFalse(check(changed))
        wrong_path = {'DeviceProperties': {'Add': {'PciRoot(0x0)/Pci(0x7,0x0)':
                      config['DeviceProperties']['Add'][path]}}}
        self.assertFalse(check(wrong_path))
        no_vbios = {'DeviceProperties': {'Add': {path: {
                    'rgpu,raphael-target': b'RGPU-RAPHAEL\x01'}}}}
        self.assertFalse(check(no_vbios))

    def test_ocprop_couples_target_marker_to_vbios_injection(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, output, rom = root/'config.plist', root/'out.plist', root/'rom.bin'
            source.write_bytes(plistlib.dumps({'DeviceProperties': {'Add': {}}}))
            rom.write_bytes(b'VBIOS')
            subprocess.run(['python3', str(ROOT/'tools/ocprop.py'), str(source),
                            '-o', str(output), '--vbios', str(rom)], check=True,
                           text=True, capture_output=True)
            config = plistlib.loads(output.read_bytes())
            props = config['DeviceProperties']['Add']['PciRoot(0x0)/Pci(0x6,0x0)']
            self.assertEqual(props['ATY,bin_image'], b'VBIOS')
            self.assertEqual(props['rgpu,raphael-target'], b'RGPU-RAPHAEL\x01')
            subprocess.run(['python3', str(ROOT/'tools/ocprop.py'), str(output),
                            '--drop-vbios'], check=True, text=True, capture_output=True)
            config = plistlib.loads(output.read_bytes())
            self.assertNotIn('PciRoot(0x0)/Pci(0x6,0x0)',
                             config['DeviceProperties']['Add'])

    def test_manifest_mode_must_be_explicit_boolean(self):
        check = self.module().required_identity
        for value in (None, 'false', 0, 1):
            self.assertIn('gpu', check({'gpu': value}))
        for value in (False, True):
            self.assertNotIn('gpu', check({'gpu': value}))

    def test_run_rejects_prepare_only_gpu_less_flag(self):
        result = subprocess.run(['python3', str(ROOT/'tools/experiment.py'), 'run',
                                 '--vm-dir', '/nonexistent', '--gpu-less'],
                                text=True, capture_output=True)
        self.assertIn('--gpu-less is only valid with prepare', result.stderr)

    def test_host_monitor_detects_fault_while_main_thread_is_blocked(self):
        tool = self.module()
        monitor_type = getattr(tool, 'HostMonitor', None)
        self.assertIsNotNone(monitor_type, 'continuous exposure monitor missing')
        interrupted = threading.Event()
        with patch.object(tool, 'kernel_updates', return_value=('next', ['Hardware Error'], ['Hardware Error'])):
            monitor = monitor_type('cursor', interrupted.set, interval=0.01)
            monitor.start()
            try: self.assertTrue(interrupted.wait(2), 'blocking operation suppressed host fault detection')
            finally: monitor.stop()
            self.assertTrue(monitor.error)
            self.assertEqual(monitor.error_kind, 'fault')
            self.assertIn('Hardware Error', monitor.messages)

    def test_host_monitor_distinguishes_capture_failure_from_kernel_fault(self):
        tool = self.module()
        published = []
        class PublicationMonitor(tool.HostMonitor):
            def __setattr__(self, name, value):
                if name == 'error' and value is not None:
                    published.append(getattr(self, 'error_kind', None))
                super().__setattr__(name, value)
        with patch.object(tool, 'kernel_updates', side_effect=RuntimeError('journal unavailable')):
            monitor = PublicationMonitor('cursor', lambda:None)
            monitor.poll()
        self.assertEqual(monitor.error_kind, 'capture')
        self.assertEqual(published, ['capture'])
        self.assertIn('capture failed', monitor.error)

    def test_failed_amdgpu_probe_is_not_completed_initialization(self):
        check = getattr(self.module(), 'amdgpu_initialized', None)
        self.assertIsNotNone(check)
        self.assertFalse(check('amdgpu 0000:7b:00.0: probe failed with error -22'))
        self.assertTrue(check('[drm] Initialized amdgpu 3.64.0 for 0000:7b:00.0 on minor 0'))
        self.assertFalse(check('[drm] Initialized amdgpu 3.64.0 for 0000:03:00.0 on minor 1'))

    def host(self):
        return dict(boot_id='boot-A', amdgpu_initialized=True, capture_ready=True,
                    watchdogs_verified=True, device_pinned_awake=True, active_vm=False,
                    driver='vfio-pci', device='1002:13c0', iommu_group='31',
                    device_accessible=True, reset_methods=[])

    def test_unknown_or_failed_host_gate_refuses_admission(self):
        admit = self.module().admit
        manifest = dict(max_seconds=180, boot_id='boot-A', source_clean=True,
                        vfio_device='0000:7b:00.0')
        self.assertEqual(admit(manifest, self.host(), set()), [])
        for key in ('amdgpu_initialized', 'capture_ready', 'watchdogs_verified',
                    'device_pinned_awake', 'device_accessible'):
            for value in (False, None):
                host = dict(self.host(), **{key: value})
                self.assertIn(key, admit(manifest, host, set()))
        for field, value in [('source_clean', False), ('vfio_device', None), ('max_seconds', 0)]:
            self.assertIn(field, admit(dict(manifest, **{field: value}), self.host(), set()))
        self.assertIn('boot_already_used', admit(manifest, self.host(), {'boot-A'}))
        self.assertIn('active_vm', admit(manifest, dict(self.host(), active_vm=True), set()))
        self.assertIn('reset_method', admit(
            manifest, dict(self.host(), reset_methods=['bus']), set()))

    def test_boot_reservation_survives_failure_and_cannot_be_replaced(self):
        reserve = self.module().reserve_boot
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            reserve(root, 'boot-A', 'first')
            with self.assertRaises(FileExistsError): reserve(root, 'boot-A', 'second')
            self.assertEqual(json.loads((root / 'boot-A.json').read_text())['launches'][0]['run_id'],
                             'first')

    def test_prelaunch_continuation_is_exact_and_marker_is_single_use(self):
        tool = self.module()
        recovery = tool.helper('vfio-recover')
        boot = tool.PRELAUNCH_CONTINUATION['boot_id']
        run = tool.PRELAUNCH_CONTINUATION['run_id']
        with tempfile.TemporaryDirectory() as temp:
            vm = Path(temp); original = vm/'run/original'; original.mkdir(parents=True)
            manifest = {key:'fixture' for key in tool.IDENTITY_FIELDS}
            manifest.update(boot_id=boot, run_id=run, max_seconds=180, gpu=True,
                            source_commit='old', source_sha256='driver-tree',
                            source_clean=True, vfio_device='0000:7b:00.0',
                            candidate_directory='run/candidate-174',
                            spec={'candidate_version':'1.0.174'},
                            prelaunch_replacement_reason=
                                'remove unsafe SEM diagnostic reads and preserve bounded critical capture')
            original_manifest = dict(manifest)
            original_manifest.pop('prelaunch_replacement_reason')
            original_manifest['candidate_directory'] = 'run/candidate-173'
            original_manifest['spec'] = {'candidate_version':'1.0.173'}
            manifest_path = vm/'manifest.json'
            manifest_bytes = json.dumps(manifest).encode()
            manifest_path.write_bytes(manifest_bytes)
            original_manifest_bytes = json.dumps(original_manifest).encode()
            (original/'manifest.json').write_bytes(original_manifest_bytes)
            verdict = {'valid':False, 'verdict':'INVALID',
                       'error':'OSError: [Errno 22] Invalid argument'}
            (original/'verdict.json').write_text(json.dumps(verdict))
            old_host = dict(self.host(), boot_id=boot, sleep_inhibited=True)
            (original/'host-before.json').write_text(json.dumps(old_host))
            (original/'host-after.json').write_text(json.dumps(old_host))
            descriptor_sha = hashlib.sha256(recovery.host_kiq_reservation_descriptor(
                run, recovery.HOST_KIQ_RESERVATION_PENDING)).hexdigest()
            stages = []
            for request in ('0x3b64','0x3b65','0x3b67','0x3b68','0x3b66','0x3b6a'):
                stages.append({'operation':'ioctl','request':request,'status':'ok'})
            for length in (0x10000000, 0x200000, 0x80000):
                stages += [{'operation':'ioctl','request':'0x3b6c','status':'ok'},
                           {'operation':'mmap','length':length,'status':'ok'}]
            stages.append({'operation':'ioctl','request':'0x3b69','status':'ok'})
            proof_host = dict(boot_id=boot, active_vm=False, driver='vfio-pci',
                              device='1002:13c0', iommu_group='31', pci_command=3,
                              reset_methods=[])
            proof = {'schema':1, 'purpose':'locate prelaunch EINVAL without writes',
                     'boot_id':boot, 'run_id':run, 'constructor':'ok', 'failure':None,
                     'descriptor':{'exact_pending_match':True,
                         'expected_sha256':descriptor_sha, 'observed_sha256':descriptor_sha,
                         'expected_size':72, 'size':72},
                     'before':proof_host, 'after':proof_host, 'kernel_messages':[],
                     'pre_faults':[], 'post_faults':[], 'stages':stages}
            proof_path = vm/'proof.json'; proof_path.write_text(json.dumps(proof))
            ledger_dir = vm/'run/used-gpu-boots'; ledger_dir.mkdir(parents=True)
            ledger_path = ledger_dir/(boot+'.json')
            ledger_path.write_text(json.dumps({'schema':2, 'boot_id':boot,
                                               'launches':[{'run_id':run}]}))
            readiness = {'schema':1,
                'purpose':'bounded read-only prelaunch HDP readiness',
                'boot_id':boot, 'run_id':run, 'writes_permitted':False,
                'marker_created':False, 'constructor':'ok',
                'failure':'RuntimeError: HDP remap 0x385c != 0x7f000',
                'descriptor':{'run_id':run,
                              'state':recovery.HOST_KIQ_RESERVATION_PENDING},
                'hdp_remap_offset_register':0x385c, 'config_memsize':0x200,
                'config_memsize_valid':True, 'active_launch_units':[],
                'kernel_messages_before':[], 'kernel_faults_before':[],
                'failure_kernel_messages':[], 'failure_kernel_faults':[],
                'before_pci':proof_host, 'failure_after_pci':proof_host,
                'ledger_sha256':hashlib.sha256(ledger_path.read_bytes()).hexdigest()}
            readiness_path = vm/'run/prelaunch-readiness-e583a1b2.json'
            readiness_path.write_text(json.dumps(readiness))
            observed = dict(manifest, source_commit='new')
            current_recovery_host = dict(proof_host)
            recovery.host_state = lambda:dict(current_recovery_host)
            pinned = dict(boot_id=boot, run_id=run,
                original_manifest_sha256=hashlib.sha256(original_manifest_bytes).hexdigest(),
                replacement_manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
                proof_sha256=hashlib.sha256(proof_path.read_bytes()).hexdigest(),
                verdict_sha256=hashlib.sha256((original/'verdict.json').read_bytes()).hexdigest(),
                output_sha256=tool.evidence_digest(original)[0],
                readiness_sha256=hashlib.sha256(readiness_path.read_bytes()).hexdigest())
            with patch.object(tool, 'PRELAUNCH_CONTINUATION', pinned), \
                 patch.object(tool, 'helper', return_value=recovery), \
                 patch.object(tool, 'current_qemu_version', return_value='fixture'), \
                 patch.object(tool, 'active_launch_units', return_value=[]):
                evidence, got_ledger, raw = tool.validate_prelaunch_continuation(
                    vm, manifest_path, manifest, original, proof_path, observed,
                    dict(old_host), ('cursor', [], []))
                self.assertEqual(evidence['coordinator_commit'],
                                 tool.command(['git','-C',str(ROOT),'rev-parse','HEAD']))
                self.assertEqual(got_ledger, ledger_path)
                self.assertEqual(raw, ledger_path.read_bytes())
                marker = tool.prelaunch_continuation_marker(vm, boot, run)
                marker.parent.mkdir()
                tool.write_once(marker, evidence)
                with self.assertRaises(FileExistsError): tool.write_once(marker, evidence)

                (original/'supervision.json').write_text('{}')
                with self.assertRaisesRegex(ValueError, 'original_after_prelaunch'):
                    tool.validate_prelaunch_continuation(
                        vm, manifest_path, manifest, original, proof_path, observed,
                        dict(old_host), ('cursor', [], []))
                (original/'supervision.json').unlink()
                ledger_path.write_text(json.dumps({'schema':2, 'boot_id':boot,
                    'launches':[{'run_id':run}, {'run_id':'f'*32}]}))
                with self.assertRaisesRegex(ValueError, 'boot_ledger'):
                    tool.validate_prelaunch_continuation(
                        vm, manifest_path, manifest, original, proof_path, observed,
                        dict(old_host), ('cursor', [], []))
                ledger_path.write_text(json.dumps({'schema':2, 'boot_id':boot,
                                                   'launches':[{'run_id':run}]}))
                for field, value, error in (
                        ('active_vm', True, 'resume_active_vm'),
                        ('reset_methods', ['bus'], 'resume_reset_method'),
                        ('pci_command', 7, 'resume_bus_master')):
                    current_recovery_host[field] = value
                    with self.assertRaisesRegex(ValueError, error):
                        tool.validate_prelaunch_continuation(
                            vm, manifest_path, manifest, original, proof_path, observed,
                            dict(old_host), ('cursor', [], []))
                    current_recovery_host[field] = proof_host[field]
                observed['binary_sha256'] = 'changed'
                with self.assertRaisesRegex(ValueError, 'binary_sha256'):
                    tool.validate_prelaunch_continuation(
                        vm, manifest_path, manifest, original, proof_path, observed,
                        dict(old_host), ('cursor', [], []))
                observed['binary_sha256'] = manifest['binary_sha256']
                with patch.object(tool, 'current_qemu_version', return_value='changed'):
                    with self.assertRaisesRegex(ValueError, 'qemu_version'):
                        tool.validate_prelaunch_continuation(
                            vm, manifest_path, manifest, original, proof_path, observed,
                            dict(old_host), ('cursor', [], []))
                with patch.object(tool, 'active_launch_units',
                                  return_value=['rgpu-launch-stale.service']):
                    with self.assertRaisesRegex(ValueError, 'active_launch_units'):
                        tool.validate_prelaunch_continuation(
                            vm, manifest_path, manifest, original, proof_path, observed,
                            dict(old_host), ('cursor', [], []))

    def test_run_continuation_consumes_marker_before_prepare_and_never_reserves_boot(self):
        tool = self.module()
        for mode in ('success', 'existing-marker', 'changed-ledger'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp:
                vm = Path(temp); (vm/'run').mkdir()
                manifest = {key:'fixture' for key in tool.IDENTITY_FIELDS}
                manifest.update(build_id='abc', run_id='a'*32, max_seconds=180,
                    boot_id='boot-A', bootdisk_verified=True, gpu=True,
                    spec={'requested_diagnostic':'rgpusdma=1'},
                    launch_options={'BOOTDISK_MODE':'custom', 'NVRAM':'stock'},
                    source_clean=True, vfio_device='0000:7b:00.0',
                    candidate_directory='run/candidate-173', image_id='sha256:expected')
                path = vm/'prepared.json'; path.write_text(json.dumps(manifest))
                ledger_dir = vm/'run/used-gpu-boots'; ledger_dir.mkdir()
                ledger = ledger_dir/'boot-A.json'; ledger.write_bytes(b'ledger-original')
                events = []
                marker = tool.prelaunch_continuation_marker(vm, 'boot-A', 'a'*32)
                if mode == 'existing-marker':
                    marker.parent.mkdir(); marker.write_text('{}')

                class NoopMonitor:
                    error = None; error_kind = None; messages = []
                    def __init__(self, *args): pass
                    def start(self): pass
                    def stop(self): pass

                def prepare_launch(*args, **kwargs):
                    events.append(('prepare', kwargs))
                    return {'state':'pending'}

                recovery = SimpleNamespace(prepare_launch=prepare_launch)
                supervisor = SimpleNamespace(
                    start_locked=lambda *args: (_ for _ in ()).throw(RuntimeError('stop after prepare')),
                    ManagedStopUnconfirmed=type('ManagedStopUnconfirmed',(RuntimeError,),{}))
                original_helper = tool.helper
                def helpers(name):
                    if name == 'vfio-recover': return recovery
                    if name == 'vm-supervision': return supervisor
                    return original_helper(name)
                original_write_once = tool.write_once
                def write_once(path_arg, value):
                    original_write_once(path_arg, value)
                    if Path(path_arg) == marker:
                        events.append(('marker', marker.name))
                        if mode == 'changed-ledger': ledger.write_bytes(b'ledger-changed')

                host = dict(self.host(), sleep_inhibited=True)
                continuation = {'schema':1}
                with patch.object(tool, 'current_identity', return_value=manifest), \
                     patch.object(tool, 'host_snapshot', return_value=host), \
                     patch.object(tool, 'kernel_updates', return_value=('cursor', [], [])), \
                     patch.object(tool, 'validate_prelaunch_continuation',
                         return_value=(continuation, ledger, b'ledger-original')), \
                     patch.object(tool, 'HostMonitor', NoopMonitor), \
                     patch.object(tool, 'helper', side_effect=helpers), \
                     patch.object(tool, 'write_once', side_effect=write_once), \
                     patch.object(tool, 'reserve_boot',
                         side_effect=AssertionError('continuation must not reserve boot')):
                    result = tool.run_one(vm, path, vm/('output-'+mode),
                                          vm/'original', vm/'proof.json')
                self.assertEqual(result['verdict'], 'INVALID')
                if mode == 'success':
                    self.assertEqual(events, [('marker', marker.name),
                                              ('prepare', {'expected_pending':True})])
                    self.assertEqual(ledger.read_bytes(), b'ledger-original')
                else:
                    self.assertFalse(any(row[0] == 'prepare' for row in events))

    def test_legacy_boot_reservation_accepts_one_matching_recovery_receipt(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as temp:
            vm = Path(temp); used = vm/'run/used-gpu-boots'; used.mkdir(parents=True)
            prior, current = 'a'*32, 'b'*32
            (used/'boot-A.json').write_text(json.dumps(
                {'boot_id':'boot-A', 'experiment':prior}))
            receipts = vm/'run/vfio-recovery/boot-A'; receipts.mkdir(parents=True)
            receipt = self.recovery_receipt(tool, prior, 'c'*32)
            (receipts/(prior+'.json')).write_text(json.dumps(receipt))
            authorization, errors = tool.reuse_authorization(vm, 'boot-A', current)
            self.assertEqual(errors, [])
            self.assertEqual(authorization['recovery_id'], 'c'*32)
            tool.reserve_boot(used, 'boot-A', current, authorization)
            ledger = json.loads((used/'boot-A.json').read_text())
            self.assertEqual([row['run_id'] for row in ledger['launches']], [prior, current])
            self.assertEqual(ledger['launches'][1]['recovery_id'], 'c'*32)
            replay, replay_errors = tool.reuse_authorization(vm, 'boot-A', 'd'*32)
            self.assertIsNone(replay)
            self.assertIn('recovery_receipt', replay_errors)

    def test_reuse_requires_latest_predecessor_and_stops_at_three_launches(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as temp:
            vm = Path(temp); used = vm/'run/used-gpu-boots'; used.mkdir(parents=True)
            runs = ['a'*32, 'b'*32, 'c'*32]
            ledger = {'schema':2, 'boot_id':'boot-A', 'max_launches':3,
                      'launches':[{'run_id':runs[0]},
                                  {'run_id':runs[1], 'recovery_id':'1'*32},
                                  {'run_id':runs[2], 'recovery_id':'2'*32}]}
            (used/'boot-A.json').write_text(json.dumps(ledger))
            receipt_dir = vm/'run/vfio-recovery/boot-A'; receipt_dir.mkdir(parents=True)
            wrong = {'schema':2, 'status':'recovered', 'authorizes_launch':True,
                     'boot_id':'boot-A',
                     'prior_run_id':runs[0], 'recovery_id':'3'*32,
                     'device':'0000:7b:00.0', 'iommu_group':'31', 'driver':'vfio-pci',
                     'pci_command_before':3, 'pci_command_after':3,
                     'reset_methods_before':[], 'reset_methods_after':[],
                     'kernel_messages':[],
                     'gc_quiesce':{'status':'quiesced', 'active_after':0,
                                   'dequeue_timeouts':0, 'forced_inactive':0,
                                   'cp_stat_after':0, 'cp_cpc_busy_after':0,
                                   'cp_me_after':0x15000000,
                                   'cp_mec_after':0x50000000,
                                   'pq_wptr_poll_after':0,
                                   'pq_status_after':0,
                                   'doorbell_range_lower_after':0,
                                   'doorbell_range_upper_after':0,
                                   'sdma0_after':1,
                                   'sdma0_cntl_after':0,
                                   'sdma0_rb_after':0,
                                   'sdma0_ib_after':0,
                                   'gfx_ring_clean':True,
                                   'gfx_retirement_confirmed':True,
                                   'gfx_needs_unmap':False,
                                   'gfx_was_stale':False,
                                   'host_kiq':{'status':'not-needed'},
                                   'gfx_rb_active_after':0,
                                   'gfx_rb_doorbell_after':0,
                                   'gfx_rb_wptr_after':0,
                                   'gfx_rb_wptr_hi_after':0,
                                   'gfx_rb_base_after':0,
                                   'gfx_rb_base_hi_after':0,
                                   'gfx_rb_cntl_after':0},
                     'commands':[{'command':0x00030000, 'response':0x80030000,
                                  'confirmed':True},
                                 {'command':0x000c0000, 'response':0x800c0000,
                                  'confirmed':True}]}
            (receipt_dir/(runs[2]+'.json')).write_text(json.dumps(wrong))
            authorization, errors = tool.reuse_authorization(vm, 'boot-A', 'd'*32)
            self.assertIsNone(authorization)
            self.assertIn('launch_ceiling', errors)

    def test_recovery_receipt_validation_fails_closed(self):
        tool = self.module()
        good = self.recovery_receipt(tool)
        self.assertEqual(tool.validate_recovery_receipt(good, 'boot-A', 'a'*32), [])
        native = json.loads(json.dumps(good))
        native['gc_quiesce']['reservation']['consume_hdp_flush']['remap'] = 0x385c
        self.assertEqual(tool.validate_recovery_receipt(native, 'boot-A', 'a'*32), [])
        native['gc_quiesce']['reservation']['consume_hdp_flush']['posted_read'] = 0x201
        self.assertIn('recovery_receipt', tool.validate_recovery_receipt(
            native, 'boot-A', 'a'*32))
        for key in ('remap', 'posted_read'):
            noninteger = self.recovery_receipt(tool)
            value = noninteger['gc_quiesce']['reservation']['consume_hdp_flush'][key]
            noninteger['gc_quiesce']['reservation']['consume_hdp_flush'][key] = float(value)
            self.assertIn('recovery_receipt', tool.validate_recovery_receipt(
                noninteger, 'boot-A', 'a'*32))
        self.assertIn('recovery_receipt', tool.validate_recovery_receipt(
            {key:value for key,value in good.items() if key != 'gc_quiesce'},
            'boot-A', 'a'*32))
        stale_gfx = json.loads(json.dumps(good))
        stale_gfx['gc_quiesce']['gfx_rb_active_after'] = 1
        self.assertIn('recovery_receipt', tool.validate_recovery_receipt(
            stale_gfx, 'boot-A', 'a'*32))
        recovered_stale_gfx = json.loads(json.dumps(good))
        reservation = recovered_stale_gfx['gc_quiesce']['reservation']
        fb = 0xf400000000
        recovered_stale_gfx['gc_quiesce'].update({
            'gfx_needs_unmap':True,
            'gfx_was_stale':True,
            'host_kiq':{'status':'retired', 'selector':9,
                        'cleanup_confirmed':True,
                        'gfx_active_after_unmap':0,
                        'gfx_active_before_scrub':0,
                        'graphics_pipes_after_unmap':
                            recovered_stale_gfx['gc_quiesce'][
                                'graphics_pipes_after_retirement'],
                        'packet_dwords':0x100,
                        'rptr_after':0x100,
                        'fence_sequence':0x12345678,
                        'fence_after':0x12345678,
                        'gfx_doorbell_offset':0x400,
                        'hdp_flush':{'remap':0x7f000, 'posted_read':0x200},
                        'reservation':reservation,
                        'addresses':{
                            'ring':fb+0x0f100000, 'mqd':fb+0x0f110000,
                            'rptr':fb+0x0f111000, 'wptr':fb+0x0f111008,
                            'eop':fb+0x0f112000, 'fence':fb+0x0f113000},
                        'gart':{'control':0, 'root':0, 'start_page':0,
                                'end_page':0, 'physical_fb':0x840000000,
                                'bar_offset':None, 'size':0, 'active':False},
                        'cleanup':{'mec_cntl':0x50000000, 'hqd_active':0,
                                   'hqd_doorbell':0, 'hqd_rptr':0,
                                   'hqd_wptr_lo':0, 'hqd_wptr_hi':0,
                                   'pq_status':0, 'doorbell_range_lower':0,
                                   'doorbell_range_upper':0, 'wptr_poll_cntl':0},
                        'final_gate':{
                            'active_after':0, 'cp_stat_after':0,
                            'cp_cpc_busy_after':0, 'pq_wptr_poll_after':0,
                            'pq_status_after':0, 'doorbell_range_lower_after':0,
                            'doorbell_range_upper_after':0,
                            'gfx_ring_clean':True,
                            'gfx_retirement_confirmed':True,
                            'graphics_pipe_proof_complete':True}},
        })
        before_pipe0 = recovered_stale_gfx['gc_quiesce'][
            'graphics_pipes_before']['pipes'][0]
        before_pipe0.update(rb0_active=1, active=1,
                            doorbell_control=0xc0000400,
                            doorbell_offset=0x400,
                            doorbell_status=0xc0000000)
        self.assertEqual(tool.validate_recovery_receipt(
            recovered_stale_gfx, 'boot-A', 'a'*32), [])
        recovered_stale_gfx['gc_quiesce']['host_kiq']['cleanup_confirmed'] = False
        self.assertIn('recovery_receipt', tool.validate_recovery_receipt(
            recovered_stale_gfx, 'boot-A', 'a'*32))
        for key, value in [('fence_after',0), ('gfx_doorbell_offset',0x800),
                           ('packet_dwords',6), ('reservation',{'consumed':True}),
                           ('hdp_flush',{'remap':0})]:
            broken = json.loads(json.dumps(recovered_stale_gfx))
            broken['gc_quiesce']['host_kiq']['cleanup_confirmed'] = True
            broken['gc_quiesce']['host_kiq'][key] = value
            self.assertIn('recovery_receipt', tool.validate_recovery_receipt(
                broken, 'boot-A', 'a'*32))

    def test_schema6_dispatch_accepts_new_proof_without_weakening_schema5(self):
        tool = self.module()
        schema5 = self.recovery_receipt(tool)
        schema6 = self.schema6_recovery_receipt(tool)

        self.assertEqual(tool.validate_recovery_receipt(
            schema5, 'boot-A', 'a'*32), [])
        self.assertEqual(tool.validate_recovery_receipt_v6(
            schema6, 'boot-A', 'a'*32), [])
        self.assertEqual(tool.validate_reuse_receipt(
            schema6, 'boot-A', 'a'*32), [])
        self.assertIn('recovery_receipt', tool.validate_recovery_receipt(
            schema6, 'boot-A', 'a'*32))

    def test_schema6_accepts_only_disabled_host_kiq_doorbell_status(self):
        tool = self.module()
        hit_only = self.schema6_host_kiq_receipt(tool)
        cleanup = hit_only['gc_quiesce']['host_kiq']['cleanup']
        cleanup['hqd_doorbell'] = 0x80000000

        self.assertEqual(tool.validate_recovery_receipt_v6(
            hit_only, 'boot-A', 'a'*32), [])
        self.assertEqual(tool.validate_reuse_receipt(
            hit_only, 'boot-A', 'a'*32), [])
        self.assertEqual(cleanup['hqd_doorbell'], 0x80000000)

        legacy = self.host_kiq_receipt(tool)
        legacy['gc_quiesce']['host_kiq']['cleanup']['hqd_doorbell'] = 0x80000000
        self.assertIn('recovery_receipt', tool.validate_recovery_receipt(
            legacy, 'boot-A', 'a'*32))

        for label, value in (
                ('enabled', 0x40000000),
                ('hit-and-enabled', 0xc0000000),
                ('mode', 0x00000001),
                ('scheduler-hit', 0x20000000),
                ('negative', -1),
                ('wider-than-dword', 0x100000000),
                ('boolean', True),
                ('not-an-integer', None)):
            with self.subTest(label=label):
                broken = self.schema6_host_kiq_receipt(tool)
                broken['gc_quiesce']['host_kiq']['cleanup'][
                    'hqd_doorbell'] = value
                self.assertIn('recovery_receipt',
                              tool.validate_recovery_receipt_v6(
                                  broken, 'boot-A', 'a'*32))

        missing = self.schema6_host_kiq_receipt(tool)
        missing['gc_quiesce']['host_kiq']['cleanup'].pop('hqd_doorbell')
        self.assertIn('recovery_receipt', tool.validate_recovery_receipt_v6(
            missing, 'boot-A', 'a'*32))

    def test_schema6_rejects_inaccessible_or_unsafe_sdma_scalar_proof(self):
        tool = self.module()
        good = self.schema6_recovery_receipt(tool)

        for malformed in (None, [], 'invalid'):
            with self.subTest(malformed_gc=malformed):
                broken = dict(good, gc_quiesce=malformed)
                self.assertEqual(tool.validate_recovery_receipt_v6(
                    broken, 'boot-A', 'a'*32), ['recovery_receipt'])

        mutations = [
            ('missing-page-proof', ('sdma0_page_ib_before',), None),
            ('page-ib-enabled', ('sdma0_page_ib_after',), 0x101),
            ('page-rb-wrong-transition', ('sdma0_page_rb_after',), 0x80000000),
            ('status-not-idle', ('sdma0_status_after',), 0),
            ('status-inaccessible', ('sdma0_status_before',), 0xffffffff),
            ('status-negative', ('sdma0_status_before',), -1),
            ('f32-inaccessible', ('sdma0_after',), 0xffffffff),
            ('f32-wider-than-dword', ('sdma0_before',), 0x100000000),
            ('gfx-input-inaccessible', ('sdma0_rb_before',), 0xffffffff),
            ('boolean-is-not-register', ('sdma0_page_rb_before',), True),
        ]
        for label, path, value in mutations:
            with self.subTest(label=label):
                broken = json.loads(json.dumps(good))
                if label == 'missing-page-proof':
                    broken['gc_quiesce'].pop(path[0])
                else:
                    broken['gc_quiesce'][path[0]] = value
                self.assertIn('recovery_receipt',
                              tool.validate_recovery_receipt_v6(
                                  broken, 'boot-A', 'a'*32))

    def test_schema6_rejects_wrong_page_trace_or_rlc_observations(self):
        tool = self.module()
        good = self.schema6_recovery_receipt(tool)

        mutations = []
        reversed_trace = list(reversed(good['gc_quiesce']['sdma0_shutdown_trace']))
        mutations.append(('trace-order', ('sdma0_shutdown_trace',), reversed_trace))
        wrong_register = json.loads(json.dumps(
            good['gc_quiesce']['sdma0_shutdown_trace']))
        wrong_register[0]['register'] += 4
        mutations.append(('trace-register', ('sdma0_shutdown_trace',), wrong_register))
        wrong_readback = json.loads(json.dumps(
            good['gc_quiesce']['sdma0_shutdown_trace']))
        wrong_readback[1]['readback'] ^= 1
        mutations.append(('trace-readback', ('sdma0_shutdown_trace',), wrong_readback))
        extra_trace_key = json.loads(json.dumps(
            good['gc_quiesce']['sdma0_shutdown_trace']))
        extra_trace_key[0]['extra'] = 0
        mutations.append(('trace-exact-keys', ('sdma0_shutdown_trace',), extra_trace_key))

        for label, path, value in mutations:
            with self.subTest(label=label):
                broken = json.loads(json.dumps(good))
                broken['gc_quiesce'][path[0]] = value
                self.assertIn('recovery_receipt',
                              tool.validate_recovery_receipt_v6(
                                  broken, 'boot-A', 'a'*32))

        rlc_mutations = [
            ('missing-row', lambda rows: rows.pop()),
            ('wrong-index', lambda rows: rows[1].update(index=0)),
            ('extra-key', lambda rows: rows[0].update(extra=0)),
            ('changed-observation', lambda rows: rows[0].update(rb_after=0x204)),
            ('enabled-rb', lambda rows: rows[0].update(rb_after=0x201,
                                                       rb_before=0x201)),
            ('enabled-ib', lambda rows: rows[1].update(ib_after=0x105,
                                                       ib_before=0x105)),
            ('inaccessible', lambda rows: rows[0].update(ib_before=0xffffffff,
                                                         ib_after=0xffffffff)),
            ('boolean-register', lambda rows: rows[0].update(rb_before=False,
                                                             rb_after=False)),
            ('wider-than-dword', lambda rows: rows[0].update(rb_before=0x100000000,
                                                             rb_after=0x100000000)),
        ]
        for label, mutate in rlc_mutations:
            with self.subTest(label=label):
                broken = json.loads(json.dumps(good))
                mutate(broken['gc_quiesce']['sdma0_rlc_inputs'])
                self.assertIn('recovery_receipt',
                              tool.validate_recovery_receipt_v6(
                                  broken, 'boot-A', 'a'*32))

    def test_recovery_receipt_admission_mutation_checks_every_hardware_proof(self):
        tool = self.module()
        good = self.host_kiq_receipt(tool)
        self.assertEqual(tool.validate_recovery_receipt(good, 'boot-A', 'a'*32), [])

        def changed(path, value, *, mirror_reservation=False):
            receipt = json.loads(json.dumps(good))
            target = receipt
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            if mirror_reservation:
                receipt['gc_quiesce']['host_kiq']['reservation'] = json.loads(
                    json.dumps(receipt['gc_quiesce']['reservation']))
            return receipt

        # Receipt schemas are deliberately not backward-compatible: adding a
        # proof changes the version and older receipts fail closed.
        self.assertIn('recovery_receipt', tool.validate_recovery_receipt(
            changed(('schema',), 3), 'boot-A', 'a'*32))

        for index, expected in tool.RECOVERY_BAR_REGIONS.items():
            for field, value in expected.items():
                bad = (not value if type(value) is bool else value + 1)
                with self.subTest(area='region', index=index, field=field):
                    self.assertIn('recovery_receipt', tool.validate_recovery_receipt(
                        changed(('bar5','regions',index,field), bad),
                        'boot-A', 'a'*32))
        for field, value in tool.RECOVERY_BAR_REGIONS['5'].items():
            bad = (not value if type(value) is bool else value + 1)
            with self.subTest(area='bar5', field=field):
                self.assertIn('recovery_receipt', tool.validate_recovery_receipt(
                    changed(('bar5',field), bad), 'boot-A', 'a'*32))

        reservation_bad = {
            'version':2, 'state':0, 'heap_limit':0, 'reservation_start':0,
            'scratch_start':0, 'reservation_end':0, 'run_id':'c'*32,
            'checksum':0, 'consumed':False,
        }
        for field, bad in reservation_bad.items():
            with self.subTest(area='reservation', field=field):
                self.assertIn('recovery_receipt', tool.validate_recovery_receipt(
                    changed(('gc_quiesce','reservation',field), bad,
                            mirror_reservation=True), 'boot-A', 'a'*32))
        for field, bad in [('remap',0), ('posted_read',0xffffffff)]:
            with self.subTest(area='reservation-flush', field=field):
                self.assertIn('recovery_receipt', tool.validate_recovery_receipt(
                    changed(('gc_quiesce','reservation','consume_hdp_flush',field), bad,
                            mirror_reservation=True), 'boot-A', 'a'*32))

        host_bad = {
            'status':'failed', 'selector':8, 'cleanup_confirmed':False,
            'gfx_active_after_unmap':1, 'gfx_active_before_scrub':1,
            'packet_dwords':6, 'rptr_after':0, 'fence_sequence':0,
            'fence_after':0, 'gfx_doorbell_offset':0x800,
        }
        for field, bad in host_bad.items():
            with self.subTest(area='host-kiq', field=field):
                self.assertIn('recovery_receipt', tool.validate_recovery_receipt(
                    changed(('gc_quiesce','host_kiq',field), bad),
                    'boot-A', 'a'*32))
        for field, bad in [('remap',0), ('posted_read',0xffffffff)]:
            self.assertIn('recovery_receipt', tool.validate_recovery_receipt(
                changed(('gc_quiesce','host_kiq','hdp_flush',field), bad),
                'boot-A', 'a'*32))

        for field in ('ring','mqd','rptr','wptr','eop','fence'):
            value = good['gc_quiesce']['host_kiq']['addresses'][field]
            with self.subTest(area='addresses', field=field):
                self.assertIn('recovery_receipt', tool.validate_recovery_receipt(
                    changed(('gc_quiesce','host_kiq','addresses',field), value+4),
                    'boot-A', 'a'*32))
        gart_bad = {'control':0, 'root':0, 'start_page':2, 'end_page':0xfe,
                    'physical_fb':0x850000000, 'bar_offset':0x0e000004,
                    'size':0x808, 'active':False}
        for field, bad in gart_bad.items():
            with self.subTest(area='gart', field=field):
                self.assertIn('recovery_receipt', tool.validate_recovery_receipt(
                    changed(('gc_quiesce','host_kiq','gart',field), bad),
                    'boot-A', 'a'*32))
        cleanup_bad = {
            'mec_cntl':0, 'hqd_active':1, 'hqd_doorbell':1,
            'hqd_rptr':1, 'hqd_wptr_lo':1, 'hqd_wptr_hi':1,
            'pq_status':2, 'doorbell_range_lower':1,
            'doorbell_range_upper':1, 'wptr_poll_cntl':0x80000000,
        }
        for field, bad in cleanup_bad.items():
            with self.subTest(area='cleanup', field=field):
                self.assertIn('recovery_receipt', tool.validate_recovery_receipt(
                    changed(('gc_quiesce','host_kiq','cleanup',field), bad),
                    'boot-A', 'a'*32))
        for field, value in good['gc_quiesce']['host_kiq']['final_gate'].items():
            bad = (not value if type(value) is bool else value + 1)
            with self.subTest(area='final-gate', field=field):
                self.assertIn('recovery_receipt', tool.validate_recovery_receipt(
                    changed(('gc_quiesce','host_kiq','final_gate',field), bad),
                    'boot-A', 'a'*32))
        for key, value in [('status','failed'), ('prior_run_id','c'*32),
                           ('pci_command_after',7), ('reset_methods_after',['bus']),
                           ('kernel_messages',['vfio-pci 0000:7b:00.0: resetting']),
                           ('commands',[{'confirmed':True}])]:
            self.assertIn('recovery_receipt', tool.validate_recovery_receipt(
                dict(good, **{key:value}), 'boot-A', 'a'*32))
        for key, value in [('dequeue_timeouts',1), ('forced_inactive',1),
                           ('cp_stat_after',0x80008200),
                           ('cp_cpc_busy_after',0x08080000)]:
            broken = dict(good)
            broken['gc_quiesce'] = dict(good['gc_quiesce'], **{key:value})
            self.assertIn('recovery_receipt', tool.validate_recovery_receipt(
                broken, 'boot-A', 'a'*32))

    def test_schema5_rejects_unsafe_or_missing_pipe_proof(self):
        tool = self.module()
        good = self.recovery_receipt(tool)

        def copy():
            return json.loads(json.dumps(good))

        for stage in ('graphics_pipe_guard', 'graphics_pipes_before',
                      'graphics_pipes_after_retirement', 'graphics_pipes_final'):
            with self.subTest(stage=stage, condition='active'):
                broken = copy()
                snapshot = (broken['gc_quiesce'][stage]['snapshot']
                            if stage == 'graphics_pipe_guard'
                            else broken['gc_quiesce'][stage])
                snapshot['pipes'][1].update(rb1_active=1, active=1)
                self.assertIn('recovery_receipt', tool.validate_recovery_receipt(
                    broken, 'boot-A', 'a'*32))
            with self.subTest(stage=stage, condition='doorbell'):
                broken = copy()
                snapshot = (broken['gc_quiesce'][stage]['snapshot']
                            if stage == 'graphics_pipe_guard'
                            else broken['gc_quiesce'][stage])
                snapshot['pipes'][1].update(
                    doorbell_control=0x40000408, doorbell_offset=0x408,
                    doorbell_status=0x40000000)
                self.assertIn('recovery_receipt', tool.validate_recovery_receipt(
                    broken, 'boot-A', 'a'*32))

        broken = copy()
        broken['gc_quiesce'].pop('graphics_pipes_before')
        self.assertIn('recovery_receipt', tool.validate_recovery_receipt(
            broken, 'boot-A', 'a'*32))
        broken = copy()
        broken['gc_quiesce']['graphics_pipe_guard']['reservation_after']['checksum'] ^= 1
        self.assertIn('recovery_receipt', tool.validate_recovery_receipt(
            broken, 'boot-A', 'a'*32))
        broken = copy()
        broken['gc_quiesce']['graphics_pipe_proof_complete'] = False
        self.assertIn('recovery_receipt', tool.validate_recovery_receipt(
            broken, 'boot-A', 'a'*32))

        # Off-diagonal ACTIVE cells have no source-backed meaning. Preserve them
        # as raw evidence without treating even all-ones as a pipe-1 claim.
        observed = copy()
        for key in ('snapshot',):
            observed['gc_quiesce']['graphics_pipe_guard'][key][
                'pipes'][1]['rb0_active'] = 0xffffffff
        for stage in ('graphics_pipes_before', 'graphics_pipes_after_retirement',
                      'graphics_pipes_final'):
            observed['gc_quiesce'][stage]['pipes'][1]['rb0_active'] = 0xffffffff
        self.assertEqual(tool.validate_recovery_receipt(
            observed, 'boot-A', 'a'*32), [])

    def test_startup_schema4_is_fallback_and_both_ids_are_single_use(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as temp:
            vm = Path(temp)
            used = vm/'run/used-gpu-boots'; used.mkdir(parents=True)
            prior, current = 'a'*32, 'b'*32
            ledger = {'schema':2, 'boot_id':'boot-A', 'max_launches':3,
                      'launches':[{'run_id':prior}]}
            (used/'boot-A.json').write_text(json.dumps(ledger) + '\n')
            receipt = {'schema':4, 'recovery_id':'c'*32, 'attempt_id':'d'*32,
                       'ledger_sha256':hashlib.sha256(
                           (used/'boot-A.json').read_bytes()).hexdigest()}
            target = vm/'run/startup-noqueue-recovery/boot-A'; target.mkdir(parents=True)
            (target/(prior+'.json')).write_text(json.dumps(receipt))
            calls = []
            startup = SimpleNamespace(validate_receipt=lambda value, boot, run, root:
                (calls.append((value, boot, run, root)) or []))
            with patch.object(tool, 'helper', return_value=startup):
                authorization, errors = tool.reuse_authorization(
                    vm, 'boot-A', current)
                self.assertEqual(errors, [])
                self.assertEqual(authorization, receipt)
                tool.reserve_boot(used, 'boot-A', current, authorization)
            self.assertEqual([call[3] for call in calls], [vm, vm])
            updated = json.loads((used/'boot-A.json').read_text())
            self.assertEqual(updated['launches'][1]['recovery_id'], 'c'*32)
            self.assertEqual(updated['launches'][1]['attempt_id'], 'd'*32)

            # Either identity being present in a prior launch makes a new
            # startup receipt a replay.
            for field in ('recovery_id', 'attempt_id'):
                replay = dict(receipt, recovery_id='e'*32, attempt_id='f'*32)
                replay[field] = updated['launches'][1][field]
                replay['ledger_sha256'] = hashlib.sha256(
                    (used/'boot-A.json').read_bytes()).hexdigest()
                with patch.object(tool, 'helper', return_value=startup):
                    with self.assertRaisesRegex(ValueError, 'startup_noqueue_receipt'):
                        tool.reserve_boot(used, 'boot-A', '1'*32, replay)

    def test_startup_schema4_rechecks_raw_ledger_before_reservation(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as temp:
            vm = Path(temp)
            used = vm/'run/used-gpu-boots'; used.mkdir(parents=True)
            prior = 'a'*32
            path = used/'boot-A.json'
            path.write_text(json.dumps({'schema':2, 'boot_id':'boot-A',
                                        'max_launches':3,
                                        'launches':[{'run_id':prior}]}) + '\n')
            receipt = {'schema':4, 'recovery_id':'c'*32, 'attempt_id':'d'*32,
                       'ledger_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
            target = vm/'run/startup-noqueue-recovery/boot-A'; target.mkdir(parents=True)
            (target/(prior+'.json')).write_text(json.dumps(receipt))
            startup = SimpleNamespace(validate_receipt=lambda *args:[])
            with patch.object(tool, 'helper', return_value=startup):
                authorization, errors = tool.reuse_authorization(
                    vm, 'boot-A', 'b'*32)
            self.assertEqual(errors, [])

            # Preserve the JSON value but alter its exact byte preimage between
            # admission and reservation.
            path.write_text(json.dumps(json.loads(path.read_text()), indent=2) + '\n')
            before = path.read_bytes()
            with patch.object(tool, 'helper', return_value=startup):
                with self.assertRaisesRegex(ValueError, 'startup_noqueue_receipt'):
                    tool.reserve_boot(used, 'boot-A', 'b'*32, authorization)
            self.assertEqual(path.read_bytes(), before)

    def test_remaining_budget_uses_earlier_launch_cap(self):
        eligible = self.module().probe_fits
        self.assertFalse(eligible(now=100, launch_deadline=150, container_deadline=190))
        self.assertTrue(eligible(now=100, launch_deadline=180, container_deadline=190))
        self.assertFalse(eligible(now=100, launch_deadline=None, container_deadline=190))

    def test_running_guest_must_have_exact_image_and_vfio_device(self):
        check = getattr(self.module(), 'validate_running', None)
        self.assertIsNotNone(check, 'actual QEMU admission check missing')
        manifest = {'image_id': 'sha256:expected', 'vfio_device': '0000:7b:00.0'}
        observed = {'image_id': 'sha256:expected', 'vfio_args':
                    ['vfio-pci,host=0000:7b:00.0,x-pci-device-id=0x73ff']}
        self.assertEqual(check(manifest, observed), [])
        self.assertIn('vfio_device', check(manifest, dict(observed, vfio_args=[])))
        self.assertIn('image_id', check(manifest, dict(observed, image_id='sha256:wrong')))

    def test_immutable_json_never_overwrites_prepared_identity(self):
        write = self.module().write_once
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'manifest.json'
            write(path, {'candidate': 'first'})
            with self.assertRaises(FileExistsError): write(path, {'candidate': 'second'})
            self.assertEqual(json.loads(path.read_text()), {'candidate': 'first'})

    def test_transactional_esp_staging_preserves_backup_and_reads_back(self):
        stage = getattr(self.module(), 'stage_image', None)
        self.assertIsNotNone(stage, 'transactional image staging missing')
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); image = root / 'esp.img'
            subprocess.run(['mformat', '-i', str(image), '-C', '-T', '16384', '::'], check=True)
            for directory in ('::/EFI', '::/EFI/OC', '::/EFI/OC/Kexts'):
                subprocess.run(['mmd', '-i', str(image), directory], check=True)
            before = image.read_bytes()
            bundle = root / 'RaphaelGPU.kext'
            (bundle / 'Contents/MacOS').mkdir(parents=True)
            (bundle / 'Contents/MacOS/RaphaelGPU').write_bytes(b'new-executable')
            (bundle / 'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleVersion': '1.0.163'}))
            config = plistlib.dumps({'test': 'new-config'})
            result = stage(image, bundle, config, offset=0)
            self.assertEqual(Path(result['backup']).read_bytes(), before)
            self.assertEqual(result['binary_sha256'], hashlib.sha256(b'new-executable').hexdigest())
            got = subprocess.check_output(['mtype', '-i', str(image), '::/EFI/OC/config.plist'])
            self.assertEqual(got, config)
            good = image.read_bytes()
            (bundle / 'Contents/MacOS/RaphaelGPU').unlink()
            with self.assertRaises((ValueError, FileNotFoundError)):
                stage(image, bundle, config, offset=0)
            self.assertEqual(image.read_bytes(), good)

    def test_one_run_archives_failure_stops_and_never_reuses_boot(self):
        self.exercise_run('hybrid')

    def test_wrong_running_image_aborts_and_stops_exact_container(self):
        self.exercise_run('wrong-image')

    def test_cancelled_observation_stops_exact_container(self):
        self.exercise_run('cancel')

    def test_definitive_capture_loss_stops_without_using_remaining_budget(self):
        self.exercise_run('capture-loss')

    def test_runtime_abort_after_validated_launch_attempts_guest_shutdown_first(self):
        self.exercise_run('runtime-abort')

    def test_host_capture_failure_attempts_guest_shutdown_but_forbids_reuse(self):
        self.exercise_run('monitor-capture')

    def test_host_kernel_fault_uses_immediate_exact_stop_and_forbids_reuse(self):
        self.exercise_run('monitor-fault')

    def test_unresolved_startup_stop_is_explicit(self):
        self.exercise_run('unconfirmed')

    def test_gpueless_coordinator_does_not_open_vfio_or_consume_gpu_boot(self):
        self.exercise_run('gpu-less')

    def test_kernel_fault_during_shutdown_invalidates_result(self):
        self.exercise_run('shutdown-fault')

    def test_probe_runs_exactly_once_after_native_readiness(self):
        self.exercise_run('probe-ready')

    def test_probe_is_not_started_without_cleanup_budget(self):
        self.exercise_run('probe-no-budget')

    def test_confirmed_forced_stop_receipt_admits_next_same_boot_launch(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as temp:
            vm = Path(temp); (vm/'run').mkdir()
            manifests = []
            for run_id in ('a'*32, 'b'*32):
                manifest = {key:'fixture' for key in tool.IDENTITY_FIELDS}
                manifest.update(
                    build_id='abc', run_id=run_id, max_seconds=180,
                    boot_id='boot-A', bootdisk_verified=True, gpu=True,
                    spec={'run_probe_only_after_native_start':True,
                          'requested_diagnostic':'rgpusdma=1'},
                    launch_options={'BOOTDISK_MODE':'custom', 'NVRAM':'stock'},
                    source_clean=True, vfio_device='0000:7b:00.0',
                    candidate_directory='run/candidate-173',
                    image_id='sha256:expected')
                path = vm/f'prepared-{run_id[0]}.json'
                path.write_text(json.dumps(manifest))
                manifests.append((manifest, path))

            host = dict(self.host(), sleep_inhibited=True)
            now = [100.0]
            calls = []
            lines = [
                'BUILD: identity=abc',
                'HY: HWLibs hybrid trace route=ok entries-match=1',
                'XJ:   waitForHwStamp(1) -> 1',
                'HY: createHybridEngine enter: engine=1 available=1',
                'HY: createHybridEngine exit: engine=1 valid=1 available-before=1 status=4',
                'XJ: AMDHardware::startHWEngines -> 0',
            ]
            serial = 'RGPU_RECORDS build=abc count=6 dropped=0 truncated=0\n'+''.join(
                f'RGPU_EVENT build=abc seq={i} {line}\n'
                for i,line in enumerate(lines))

            class StopUnconfirmed(RuntimeError):
                pass

            def start(*args):
                calls.append(('start', args[2]))
                (vm/'run/serial.log').write_text(serial)
                return {'cid':'c'*64, 'deadline_epoch':now[0]+180,
                        'max_seconds':180}

            supervisor = SimpleNamespace(
                start_locked=start, verify=lambda state:None,
                ManagedStopUnconfirmed=StopUnconfirmed,
                stop_exact=lambda cid:calls.append(('unexpected-stop', cid)))

            def shutdown(vm_path, state, expected_build, grace):
                calls.append(('forced-stop-confirmed', state['cid']))
                return {'cid':state['cid'], 'outcome':'forced',
                        'request_sent':True, 'guest_boot_uuid':'1'*36,
                        'request_id':'2'*32, 'request_error':None,
                        'acpi_request_sent':True,
                        'acpi_request_error':'bounded grace expired'}

            def recover(vm_path, prior):
                calls.append(('recover', prior))
                recovery_id = ('f' if prior == 'a'*32 else 'e')*32
                receipt = self.recovery_receipt(tool, prior, recovery_id)
                target = vm_path/'run/vfio-recovery/boot-A'
                target.mkdir(parents=True, exist_ok=True)
                (target/(prior+'.json')).write_text(json.dumps(receipt))
                return receipt

            def prepare_launch(expected_boot, run_id):
                calls.append(('prepare-recovery-reservation', expected_boot, run_id))
                return {'boot_id':expected_boot, 'run_id':run_id, 'state':'pending'}

            recovery = SimpleNamespace(recover=recover, prepare_launch=prepare_launch)
            guest_shutdown = SimpleNamespace(shutdown=shutdown)
            original_helper = tool.helper

            def helpers(name):
                if name == 'vm-supervision': return supervisor
                if name == 'guest-shutdown': return guest_shutdown
                if name == 'vfio-recover': return recovery
                return original_helper(name)

            class NoopMonitor:
                def __init__(self, cursor, interrupt, interval=1):
                    self.messages = []; self.error = None; self.error_kind = None
                def start(self): pass
                def stop(self): pass

            observed = iter([manifests[0][0], manifests[1][0]])
            with patch.object(tool, 'current_identity', side_effect=lambda *args:next(observed)), \
                 patch.object(tool, 'host_snapshot', return_value=host), \
                 patch.object(tool, 'helper', side_effect=helpers), \
                 patch.object(tool, 'running_identity', return_value={
                     'image_id':'sha256:expected',
                     'vfio_args':['vfio-pci,host=0000:7b:00.0']}), \
                 patch.object(tool, 'kernel_updates', return_value=('cursor', [], [])), \
                 patch.object(tool, 'HostMonitor', NoopMonitor), \
                 patch.object(tool.time, 'time', side_effect=lambda:now[0]), \
                 patch.object(tool.time, 'sleep', side_effect=lambda n:now.__setitem__(0, now[0]+n)):
                first = tool.run_one(vm, manifests[0][1], vm/'evidence-a')
                second = tool.run_one(vm, manifests[1][1], vm/'evidence-b')

            self.assertEqual(first['warm_reuse'], 'recovered')
            self.assertEqual(second['warm_reuse'], 'recovered')
            self.assertEqual([call for call in calls if call[0] == 'start'], [
                ('start', ['--gpu','0000:7b:00.0','--gpu-id','0x73ff',
                           '--gpu-rom','run/gpu-patched.rom']),
                ('start', ['--gpu','0000:7b:00.0','--gpu-id','0x73ff',
                           '--gpu-rom','run/gpu-patched.rom'])])
            self.assertEqual(len([call for call in calls
                                  if call[0] == 'forced-stop-confirmed']), 2)
            self.assertNotIn(('unexpected-stop', 'c'*64), calls)
            ledger = json.loads((vm/'run/used-gpu-boots/boot-A.json').read_text())
            self.assertEqual([row['run_id'] for row in ledger['launches']],
                             ['a'*32, 'b'*32])
            self.assertEqual(ledger['launches'][1]['prior_run_id'], 'a'*32)
            self.assertEqual(ledger['launches'][1]['recovery_id'], 'f'*32)
            admitted = json.loads(
                (vm/'run/vfio-recovery/boot-A'/('a'*32+'.json')).read_text())
            self.assertEqual(tool.validate_recovery_receipt(
                admitted, 'boot-A', 'a'*32), [])

    def exercise_run(self, mode):
        tool = self.module()
        self.assertTrue(hasattr(tool, 'run_one'))
        with tempfile.TemporaryDirectory() as temp:
            vm = Path(temp); (vm/'run').mkdir()
            manifest = {key:'fixture' for key in tool.IDENTITY_FIELDS}
            manifest.update(build_id='abc', run_id='a'*32, max_seconds=180, boot_id='boot-A',
                            bootdisk_verified=True, gpu=True,
                            spec={'run_probe_only_after_native_start': True,
                                  'requested_diagnostic': 'rgpusdma=1'},
                            launch_options={'BOOTDISK_MODE':'custom', 'NVRAM':'stock'},
                            source_clean=True, vfio_device='0000:7b:00.0',
                            candidate_directory='run/candidate-163', image_id='sha256:expected')
            if mode in ('probe-ready', 'probe-no-budget'):
                manifest['spec']['required_observations'] = [
                    'sdma_vm_program', 'vmid2_root_repair']
            path = vm/'prepared.json'; path.write_text(json.dumps(manifest))
            host = dict(self.host(), sleep_inhibited=True)
            if mode == 'gpu-less':
                manifest['gpu'] = False; path.write_text(json.dumps(manifest))
            now = [100.0]; calls = []
            lines = ['BUILD: identity=abc', 'HY: HWLibs hybrid trace route=ok entries-match=1',
                     'XJ:   waitForHwStamp(1) -> 1',
                     'HY: createHybridEngine enter: engine=1 available=1',
                     'HY: createHybridEngine exit: engine=1 valid=1 available-before=1 status=4',
                     'XJ: AMDHardware::startHWEngines -> 0']
            if mode in ('probe-ready', 'probe-no-budget'):
                lines = [
                    'BUILD: identity=abc',
                    'VM: route AMDGFX10VMM::prepareVMInvalidateRequest -> ok (org=0xffffff8000000000)',
                    'HY: HWLibs hybrid trace route=ok entries-match=1',
                    'XJ:   waitForHwStamp(1) -> 1',
                    'HY: createHybridEngine enter: engine=1 available=1',
                    'HY: createHybridEngine exit: engine=1 valid=1 available-before=1 status=0',
                    'XJ: AMDHardware::startHWEngines -> 1',
                    'XJ: AMDGraphicsAccelerator::powerUpHW -> 1',
                ]
            serial = 'RGPU_RECORDS build=abc count=6 dropped=0 truncated=0\n'+''.join(
                f'RGPU_EVENT build=abc seq={i} {line}\n' for i,line in enumerate(lines))
            if mode in ('probe-ready', 'probe-no-budget'):
                serial = serial.replace('count=6', 'count=8')
            def start(*args):
                calls.append('start'); (vm/'run/serial.log').write_text(serial)
                if mode == 'gpu-less': self.assertEqual(args[2], [])
                if mode == 'unconfirmed': raise StopUnconfirmed('pending service stop unknown')
                deadline = 160 if mode == 'probe-no-budget' else 280
                return dict(cid='c'*64, deadline_epoch=deadline, max_seconds=180)
            if mode == 'capture-loss': serial = serial.replace('dropped=0','dropped=1')
            class StopUnconfirmed(RuntimeError): pass
            def verify(state):
                if mode == 'cancel': raise KeyboardInterrupt()
                if mode == 'runtime-abort': raise RuntimeError('runtime observation failed')
            def shutdown(vm_path, state, expected_build, grace):
                if mode == 'shutdown-fault': calls.append('host-fault')
                calls.append(('guest-shutdown', state['cid'], expected_build))
                return dict(cid=state['cid'], outcome='forced')
            def kernel(cursor=None):
                faults = ['Hardware Error'] if 'host-fault' in calls else []
                return 'cursor', faults, faults
            class ImmediateMonitor:
                def __init__(self, cursor, interrupt, interval=1):
                    self.messages = []
                    self.error_kind = 'fault' if mode == 'monitor-fault' else 'capture'
                    self.error = ('new host kernel fault during exposure' if
                                  self.error_kind == 'fault' else
                                  'host kernel capture failed: journal unavailable')
                def start(self): pass
                def stop(self): pass
            supervisor = SimpleNamespace(start_locked=start, verify=verify,
                ManagedStopUnconfirmed=StopUnconfirmed,
                stop_exact=lambda cid:calls.append(('stop',cid)))
            guest_shutdown = SimpleNamespace(shutdown=shutdown)
            def recover(vm_path, prior):
                calls.append(('recover', prior))
                receipt = {'schema':2, 'status':'recovered', 'authorizes_launch':True,
                           'boot_id':'boot-A',
                           'prior_run_id':prior, 'recovery_id':'f'*32,
                           'device':'0000:7b:00.0', 'iommu_group':'31', 'driver':'vfio-pci',
                           'pci_command_before':3, 'pci_command_after':3,
                           'reset_methods_before':[], 'reset_methods_after':[],
                           'kernel_messages':[],
                           'gc_quiesce':{'status':'quiesced', 'active_after':0,
                                         'dequeue_timeouts':0, 'forced_inactive':0,
                                         'cp_stat_after':0, 'cp_cpc_busy_after':0,
                                         'cp_me_after':0x15000000,
                                         'cp_mec_after':0x50000000,
                                         'pq_wptr_poll_after':0,
                                         'pq_status_after':0,
                                         'doorbell_range_lower_after':0,
                                         'doorbell_range_upper_after':0,
                                         'sdma0_after':1,
                                         'sdma0_cntl_after':0,
                                         'sdma0_rb_after':0,
                                         'sdma0_ib_after':0,
                                         'gfx_ring_clean':True,
                                         'gfx_retirement_confirmed':True,
                                         'gfx_needs_unmap':False,
                                         'gfx_was_stale':False,
                                         'host_kiq':{'status':'not-needed'},
                                         'gfx_rb_active_after':0,
                                         'gfx_rb_doorbell_after':0,
                                         'gfx_rb_wptr_after':0,
                                         'gfx_rb_wptr_hi_after':0,
                                         'gfx_rb_base_after':0,
                                         'gfx_rb_base_hi_after':0,
                                         'gfx_rb_cntl_after':0},
                           'commands':[{'command':0x00030000, 'response':0x80030000,
                                        'confirmed':True},
                                       {'command':0x000c0000, 'response':0x800c0000,
                                        'confirmed':True}]}
                target = vm_path/'run/vfio-recovery/boot-A'; target.mkdir(parents=True, exist_ok=True)
                (target/(prior+'.json')).write_text(json.dumps(receipt))
                return receipt
            def prepare_launch(expected_boot, run_id):
                calls.append(('prepare-recovery-reservation', expected_boot, run_id))
                return {'boot_id':expected_boot, 'run_id':run_id, 'state':'pending'}
            recovery = SimpleNamespace(recover=recover, prepare_launch=prepare_launch)
            def probe(vm_path, prepared):
                calls.append('probe')
                return {'run_id':prepared['run_id'],
                        'output':'RGPU_EXIT '+prepared['run_id']+' 1\n'}
            original_helper = tool.helper
            def helpers(name):
                if name == 'vm-supervision': return supervisor
                if name == 'guest-shutdown': return guest_shutdown
                if name == 'vfio-recover': return recovery
                return original_helper(name)
            actual = dict(image_id='wrong' if mode == 'wrong-image' else 'sha256:expected',
                          vfio_args=['vfio-pci,host=0000:7b:00.0'])
            if mode == 'gpu-less': actual['vfio_args'] = []
            monitor_type = ImmediateMonitor if mode in ('monitor-capture', 'monitor-fault') \
                else tool.HostMonitor
            with patch.object(tool, 'current_identity', return_value=manifest), \
                 patch.object(tool, 'host_snapshot', return_value=host), \
                 patch.object(tool, 'helper', side_effect=helpers), \
                 patch.object(tool, 'running_identity', return_value=actual), \
                 patch.object(tool, 'kernel_updates', side_effect=kernel), \
                 patch.object(tool, 'HostMonitor', monitor_type), \
                 patch.object(tool, 'run_probe', side_effect=probe), \
                 patch.object(tool.time, 'time', side_effect=lambda:now[0]), \
                 patch.object(tool.time, 'sleep', side_effect=lambda n:now.__setitem__(0,now[0]+n)):
                out = vm/'evidence'
                result = tool.run_one(vm, path, out)
                self.assertEqual(calls.count('start'), 1)
                if mode != 'gpu-less':
                    self.assertLess(calls.index(('prepare-recovery-reservation',
                                                 'boot-A', 'a'*32)),
                                    calls.index('start'))
                    self.assertTrue((out/'recovery-reservation.json').exists())
                if mode == 'hybrid':
                    self.assertEqual(result['verdict'], 'HYBRID_QUEUE_SUSPECTED')
                    self.assertIn(('guest-shutdown','c'*64, 'fixture'), calls)
                elif mode == 'gpu-less':
                    self.assertEqual(result['verdict'], 'GPULESS_CAPTURE_CHECK')
                    self.assertFalse((vm/'run/used-gpu-boots/boot-A.json').exists())
                    return
                elif mode == 'unconfirmed':
                    self.assertEqual(result['verdict'], 'STOP_UNCONFIRMED')
                elif mode == 'shutdown-fault':
                    self.assertEqual(result['verdict'], 'INVALID')
                    self.assertIn('host kernel fault', result['error'])
                    self.assertNotIn(('recover', 'a'*32), calls)
                elif mode == 'monitor-capture':
                    self.assertEqual(result['verdict'], 'INVALID')
                    self.assertIn('capture failed', result['error'])
                    self.assertIn(('guest-shutdown','c'*64, 'fixture'), calls)
                    self.assertNotIn(('stop','c'*64), calls)
                    self.assertNotIn(('recover', 'a'*32), calls)
                elif mode == 'monitor-fault':
                    self.assertEqual(result['verdict'], 'INVALID')
                    self.assertIn('host kernel fault', result['error'])
                    self.assertIn(('stop','c'*64), calls)
                    self.assertNotIn(('guest-shutdown','c'*64, 'fixture'), calls)
                    self.assertNotIn(('recover', 'a'*32), calls)
                elif mode == 'wrong-image':
                    self.assertEqual(result['verdict'], 'INVALID')
                    self.assertIn(('stop','c'*64), calls)
                    self.assertNotIn(('guest-shutdown','c'*64, 'fixture'), calls)
                elif mode in ('probe-ready', 'probe-no-budget'):
                    self.assertEqual(result['verdict'], 'INCONCLUSIVE')
                    self.assertEqual(result['earliest_failure'],
                                     'sdma_vm_program_missing')
                    self.assertEqual(calls.count('probe'),
                                     1 if mode == 'probe-ready' else 0)
                    self.assertEqual((out/'probe.json').exists(),
                                     mode == 'probe-ready')
                else:
                    self.assertEqual(result['verdict'], 'INVALID')
                    self.assertIn(('guest-shutdown','c'*64, 'fixture'), calls)
                    self.assertNotIn(('stop','c'*64), calls)
                if mode == 'unconfirmed':
                    self.assertNotIn(('recover', 'a'*32), calls)
                elif mode not in ('shutdown-fault', 'monitor-capture', 'monitor-fault'):
                    self.assertIn(('recover', 'a'*32), calls)
                if mode == 'capture-loss': self.assertLess(now[0], 110)
                self.assertTrue((out/'verdict.json').exists())
                self.assertTrue((vm/'run/used-gpu-boots/boot-A.json').exists())
                second = tool.run_one(vm,path,vm/'second')
                self.assertEqual(second['verdict'], 'INVALID')
                self.assertEqual(calls.count('start'), 1)


if __name__ == '__main__': unittest.main()
