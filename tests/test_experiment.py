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

    def test_legacy_boot_reservation_accepts_one_matching_recovery_receipt(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as temp:
            vm = Path(temp); used = vm/'run/used-gpu-boots'; used.mkdir(parents=True)
            prior, current = 'a'*32, 'b'*32
            (used/'boot-A.json').write_text(json.dumps(
                {'boot_id':'boot-A', 'experiment':prior}))
            receipts = vm/'run/vfio-recovery/boot-A'; receipts.mkdir(parents=True)
            receipt = {'schema':2, 'status':'recovered', 'authorizes_launch':True,
                       'boot_id':'boot-A',
                       'prior_run_id':prior, 'recovery_id':'c'*32,
                       'device':'0000:7b:00.0', 'iommu_group':'31', 'driver':'vfio-pci',
                       'pci_command_before':3, 'pci_command_after':3,
                       'reset_methods_before':[], 'reset_methods_after':[],
                       'kernel_messages':[],
                       'gc_quiesce':{'status':'quiesced', 'active_after':0,
                                     'dequeue_timeouts':0, 'forced_inactive':0,
                                     'cp_stat_after':0, 'cp_cpc_busy_after':0,
                                     'cp_me_after':0x15000000,
                                     'cp_mec_after':0x50000000,
                                     'sdma0_after':1},
                       'commands':[{'command':0x00030000, 'response':0x80030000,
                                    'confirmed':True},
                                   {'command':0x000c0000, 'response':0x800c0000,
                                    'confirmed':True}]}
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
                                   'sdma0_after':1},
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
        good = {'schema':2, 'status':'recovered', 'authorizes_launch':True,
                'boot_id':'boot-A',
                'prior_run_id':'a'*32, 'recovery_id':'b'*32,
                'device':'0000:7b:00.0', 'iommu_group':'31', 'driver':'vfio-pci',
                'pci_command_before':3, 'pci_command_after':3,
                'reset_methods_before':[], 'reset_methods_after':[],
                'kernel_messages':[],
                'gc_quiesce':{'status':'quiesced', 'active_after':0,
                              'dequeue_timeouts':0, 'forced_inactive':0,
                              'cp_stat_after':0, 'cp_cpc_busy_after':0,
                              'cp_me_after':0x15000000,
                              'cp_mec_after':0x50000000,
                              'sdma0_after':1},
                'commands':[{'command':0x00030000, 'response':0x80030000,
                             'confirmed':True},
                            {'command':0x000c0000, 'response':0x800c0000,
                             'confirmed':True}]}
        self.assertEqual(tool.validate_recovery_receipt(good, 'boot-A', 'a'*32), [])
        self.assertIn('recovery_receipt', tool.validate_recovery_receipt(
            {key:value for key,value in good.items() if key != 'gc_quiesce'},
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
            serial = 'RGPU_RECORDS build=abc count=6 dropped=0 truncated=0\n'+''.join(
                f'RGPU_EVENT build=abc seq={i} {line}\n' for i,line in enumerate(lines))
            def start(*args):
                calls.append('start'); (vm/'run/serial.log').write_text(serial)
                if mode == 'gpu-less': self.assertEqual(args[2], [])
                if mode == 'unconfirmed': raise StopUnconfirmed('pending service stop unknown')
                return dict(cid='c'*64, deadline_epoch=280, max_seconds=180)
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
                                         'sdma0_after':1},
                           'commands':[{'command':0x00030000, 'response':0x80030000,
                                        'confirmed':True},
                                       {'command':0x000c0000, 'response':0x800c0000,
                                        'confirmed':True}]}
                target = vm_path/'run/vfio-recovery/boot-A'; target.mkdir(parents=True, exist_ok=True)
                (target/(prior+'.json')).write_text(json.dumps(receipt))
                return receipt
            recovery = SimpleNamespace(recover=recover)
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
                 patch.object(tool.time, 'time', side_effect=lambda:now[0]), \
                 patch.object(tool.time, 'sleep', side_effect=lambda n:now.__setitem__(0,now[0]+n)):
                out = vm/'evidence'
                result = tool.run_one(vm, path, out)
                self.assertEqual(calls.count('start'), 1)
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
