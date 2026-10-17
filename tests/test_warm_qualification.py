import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
BOOT = '5d6f45d0-4384-4340-b819-7751bc26ebb3'
RUN_A = 'a1' * 16
RUN_B = 'b2' * 16
RECOVERY_A = 'c3' * 16


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class WarmQualificationTests(unittest.TestCase):
    def module(self):
        path = ROOT / 'tools/warm-qualification.py'
        self.assertTrue(path.exists(), 'missing focused warm qualification helper')
        spec = importlib.util.spec_from_file_location('warm_qualification', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def hooks(self):
        path = ROOT / 'tools/classify-run.py'
        spec = importlib.util.spec_from_file_location('warm_test_classifier', path)
        classifier = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(classifier)
        return SimpleNamespace(
            validate_receipt=lambda receipt, boot, prior: [],
            validate_running=lambda manifest, running: [],
            parse_serial=lambda manifest, serial: classifier.parse_serial(
                serial,
                critical_replay_schema=manifest.get('critical_replay_schema'),
                expected_build=manifest.get('build_id')),
            classify_readiness=lambda manifest, events: {
                'valid': True, 'verdict': 'PROBE_NOT_RUN'},
            admit_host=lambda manifest, host, boots, reuse_allowed=False: [],
            validate_full_host=lambda host, boot: [],
            validate_vfio=lambda host, boot: [],
        )

    def manifest(self, run_id):
        old = json.loads((ROOT / 'findings/experiments/metal-010-177/'
                          'manifest.json').read_text())
        card = json.loads((ROOT / 'experiments/metal-011.json').read_text())
        old.update(run_id=run_id, experiment='metal-011',
                   candidate_directory='run/candidate-178', spec=card,
                   max_seconds=180, source_clean=True)
        return old

    def fixture(self):
        helper = self.module()
        temp = tempfile.TemporaryDirectory()
        vm = Path(temp.name)
        ledger_path = vm / 'run/used-gpu-boots' / f'{BOOT}.json'
        ledger_path.parent.mkdir(parents=True)
        ledger_path.write_bytes((ROOT / 'findings/experiments/metal-010-177/'
                                 'used-gpu-boot-ledger.json').read_bytes())

        manifest_dir = vm / 'run/warm-qualification-manifests'
        manifest_dir.mkdir(parents=True)
        manifest_a = self.manifest(RUN_A)
        manifest_b = self.manifest(RUN_B)
        manifest_a_path = manifest_dir / '178-a.json'
        manifest_b_path = manifest_dir / '178-b.json'
        manifest_a_path.write_text(json.dumps(manifest_a, indent=2) + '\n')
        manifest_b_path.write_text(json.dumps(manifest_b, indent=2) + '\n')

        canonical = vm / 'run/vfio-recovery' / BOOT / (
            helper.PRIOR_RUN_ID + '.json')
        canonical.parent.mkdir(parents=True)
        canonical.write_bytes((ROOT / 'findings/experiments/metal-010-177/'
                               'canonical-recovery-receipt.json').read_bytes())
        run_copy = vm / 'run/metal-010-177/recovery.json'
        run_copy.parent.mkdir(parents=True)
        run_copy.write_bytes((ROOT / 'findings/experiments/metal-010-177/'
                              'recovery.json').read_bytes())
        candidate176_canonical = vm / 'run/vfio-recovery' / BOOT / (
            helper.CANDIDATE176_RUN_ID + '.json')
        candidate176_canonical.write_bytes(
            (ROOT / 'findings/experiments/metal-009-176/'
             'canonical-recovery-receipt.json').read_bytes())
        candidate176_run = vm / 'run/metal-009-176/recovery.json'
        candidate176_run.parent.mkdir(parents=True)
        candidate176_run.write_bytes(
            (ROOT / 'findings/experiments/metal-009-176/recovery.json').read_bytes())

        policy = {
            'schema': 1,
            'kind': 'two-run-same-boot-warm-qualification-policy',
            'boot_id': BOOT,
            'ledger_preimage_sha256': digest(ledger_path),
            'prior_run_id': helper.PRIOR_RUN_ID,
            'prior_recovery_id': helper.PRIOR_RECOVERY_ID,
            'prior_canonical_receipt_sha256': digest(canonical),
            'prior_run_receipt_sha256': digest(run_copy),
            'candidate176_run_id': helper.CANDIDATE176_RUN_ID,
            'candidate176_recovery_id': helper.CANDIDATE176_RECOVERY_ID,
            'candidate176_canonical_receipt_sha256': digest(candidate176_canonical),
            'candidate176_run_receipt_sha256': digest(candidate176_run),
            'design_sha256': digest(ROOT / 'docs/superpowers/specs/'
                                    '2026-09-09-two-run-warm-qualification-design.md'),
            'experiment_py_sha256': digest(ROOT / 'tools/experiment.py'),
            'qualification_helper_sha256': digest(ROOT / 'tools/warm-qualification.py'),
            'recovery_producer_sha256': digest(ROOT / 'tools/vfio-recover.py'),
            'experiment_card_sha256': digest(ROOT / 'experiments/metal-011.json'),
            'manifest_a_path': str(manifest_a_path.relative_to(vm)),
            'manifest_a_sha256': digest(manifest_a_path),
            'run_id_a': RUN_A,
            'output_a_path': 'run/metal-011-178-a',
            'manifest_b_path': str(manifest_b_path.relative_to(vm)),
            'manifest_b_sha256': digest(manifest_b_path),
            'run_id_b': RUN_B,
            'output_b_path': 'run/metal-011-178-b',
            'from_max_launches': 4,
            'to_max_launches': 6,
            'additional_launches': 2,
            'vm_max_seconds': 180,
            'probe_max_seconds': 45,
            'automatic_extension': False,
            'purpose': 'm7-two-run-warm-qualification',
        }
        policy_path = helper.policy_path(vm, BOOT)
        policy_path.parent.mkdir(parents=True)
        policy_path.write_text(json.dumps(policy, indent=2) + '\n')
        policy_sha = digest(policy_path)

        activation_a = {
            'schema': 1,
            'kind': 'two-run-warm-qualification-activation',
            'stage': 'A',
            'boot_id': BOOT,
            'policy_sha256': policy_sha,
            'ledger_preimage_sha256': digest(ledger_path),
            'manifest_sha256': digest(manifest_a_path),
            'run_id': RUN_A,
            'prior_run_id': helper.PRIOR_RUN_ID,
            'recovery_id': helper.PRIOR_RECOVERY_ID,
            'canonical_recovery_receipt_sha256': digest(canonical),
            'run_recovery_receipt_sha256': digest(run_copy),
            'automatic_retry': False,
        }
        activation_a_path = helper.activation_path(vm, BOOT, RUN_A)
        activation_a_path.write_text(json.dumps(activation_a, indent=2) + '\n')

        return SimpleNamespace(
            cleanup=temp, helper=helper, vm=vm, ledger_path=ledger_path,
            manifest_a=manifest_a, manifest_b=manifest_b,
            manifest_a_path=manifest_a_path, manifest_b_path=manifest_b_path,
            output_a=vm / policy['output_a_path'],
            output_b=vm / policy['output_b_path'],
            policy=policy, policy_path=policy_path, policy_sha=policy_sha,
            activation_a=activation_a, activation_a_path=activation_a_path,
            activation_a_sha=digest(activation_a_path),
        )

    def authorize_a(self, f):
        authorization, errors = f.helper.authorize(
            f.vm, f.manifest_a, f.manifest_a_path, f.output_a,
            f.policy_sha, f.activation_a_sha, self.hooks())
        self.assertEqual(errors, [])
        self.assertEqual(authorization['stage'], 'A')
        return authorization

    def gate(self, manifest, receipt, after, messages=None):
        messages = [] if messages is None else messages
        identity_fields = {
            'binary_sha256', 'info_sha256', 'config_sha256', 'build_id',
            'source_sha256', 'source_commit', 'source_clean',
            'built_from_commit', 'kdk_sha256', 'build_inputs_sha256',
            'boot_args', 'harness_sha256', 'rom_sha256', 'launch_options',
            'image_id', 'guest_build', 'probe_source_sha256',
            'probe_binary_sha256', 'boot_id', 'kernel', 'bootdisk_sha256',
        }
        host = {
            'boot_id': BOOT, 'active_vm': False, 'driver': 'vfio-pci',
            'device': '1002:13c0', 'iommu_group': '31', 'pci_command': 3,
            'reset_methods': [], 'canonical_device': '/device',
            'power_control': 'on', 'power_state': 'D0',
            'runtime_status': 'active', 'enable_count': '0',
            'sleep_inhibited': True,
            'watchdogs': {'watchdog':'1', 'nmi_watchdog':'1',
                          'hardlockup_panic':'1'},
            'residual_units': [], 'siblings': {}, 'reset_domain': {},
            'kernel_release': manifest['kernel'], 'vfio_module_sha256': 'module',
            'vfio_module_build_id': 'build-id', 'journal_cursor': after,
            'journal_messages': messages, 'journal_faults': [],
            'amdgpu_initialized': True, 'capture_ready': True,
            'watchdogs_verified': True, 'device_pinned_awake': True,
            'device_accessible': True, 'pstore_files': None,
        }
        return {
            'kernel_cursor_before': receipt['kernel_cursor_after'],
            'kernel_cursor_after': after, 'kernel_messages': messages,
            'host_gate': host,
            'vfio_gate': {
                'boot_id': BOOT, 'active_vm': False, 'driver': 'vfio-pci',
                'device': '1002:13c0', 'iommu_group': '31',
                'pci_command': 3, 'reset_methods': [],
            },
            'identity_gate': {key: manifest[key] for key in identity_fields},
            'active_launch_units': [], 'pending_launches': [],
        }

    def reserve(self, f, authorization):
        receipt = authorization['receipt']
        gate = self.gate(
            authorization['manifest'], receipt,
            's=gate;i=3f3b0;b=' + BOOT + ';m=2', ['routine'])
        path, updated = f.helper.build_reservation(
            authorization, f.manifest_a['boot_id'],
            authorization['manifest']['run_id'], receipt, gate,
            reserved_epoch=123.0)
        path.write_text(json.dumps(updated, indent=2) + '\n')
        return updated

    def write_successful_a_output(self, f):
        f.output_a.mkdir(parents=True)
        (f.output_a / 'manifest.json').write_text(
            json.dumps(f.manifest_a, indent=2) + '\n')
        (f.output_a / 'supervision.json').write_text(json.dumps({
            'max_seconds': 180, 'started_at': 'now', 'cid': 'container',
            'deadline_epoch': 200, 'launch_deadline_epoch': 200,
            'timer_unit': 'timer', 'serial_unit': 'serial',
            'serial_ready': 'ready', 'launch_unit': 'launch'}) + '\n')
        (f.output_a / 'running-identity.json').write_text(json.dumps({
            'image_id': f.manifest_a['image_id'],
            'vfio_args': ['vfio-pci,host=0000:7b:00.0']}) + '\n')
        serial = (f"RGPU_RECORDS build={f.manifest_a['build_id']} count=1 "
                  "dropped=0 truncated=0\n"
                  f"RGPU_EVENT build={f.manifest_a['build_id']} seq=0 "
                  f"BUILD: identity={f.manifest_a['build_id']}\n")
        events = self.hooks().parse_serial(f.manifest_a, serial)
        (f.output_a / 'events.jsonl').write_text(
            ''.join(json.dumps(event) + '\n' for event in events))
        (f.output_a / 'serial.txt').write_text(serial)
        probe = json.loads((ROOT / 'findings/experiments/metal-010-177/'
                            'probe.json').read_text())
        probe['run_id'] = RUN_A
        probe['output'] = probe['output'].replace(f.helper.PRIOR_RUN_ID, RUN_A)
        (f.output_a / 'probe.json').write_text(json.dumps(probe) + '\n')
        (f.output_a / 'shutdown.json').write_text(json.dumps({
            'cid': 'container', 'guest_boot_uuid': 'guest',
            'request_id': 'request', 'outcome': 'exited-after-guest-request'}) + '\n')
        host = {
            'boot_id': BOOT, 'capture_ready': True,
            'watchdogs_verified': True, 'device_pinned_awake': True,
            'device_accessible': True, 'active_vm': False,
            'sleep_inhibited': True, 'driver': 'vfio-pci',
            'device': '1002:13c0', 'iommu_group': '31',
            'reset_methods': [], 'amdgpu_initialized': True,
        }
        for name in ('host-before.json', 'host-after.json'):
            (f.output_a / name).write_text(json.dumps(host) + '\n')
        (f.output_a / 'host-kernel-messages.json').write_text('[]\n')
        receipt = json.loads((f.vm / 'run/vfio-recovery' / BOOT /
                              (f.helper.PRIOR_RUN_ID + '.json')).read_text())
        receipt.update(prior_run_id=RUN_A, recovery_id=RECOVERY_A)
        (f.output_a / 'recovery.json').write_text(json.dumps(receipt) + '\n')
        canonical = f.vm / 'run/vfio-recovery' / BOOT / (RUN_A + '.json')
        canonical.write_bytes((f.output_a / 'recovery.json').read_bytes())
        (f.output_a / 'verdict.json').write_text(json.dumps({
            'valid': False, 'verdict': 'INCONCLUSIVE',
            'earliest_failure': 'resource_mapping_prepare_failed',
            'warm_reuse': 'recovered'}) + '\n')
        return receipt, canonical

    def activate_b(self, f):
        receipt, canonical = self.write_successful_a_output(f)
        ledger_sha = digest(f.ledger_path)
        activation = {
            'schema': 1,
            'kind': 'two-run-warm-qualification-activation',
            'stage': 'B',
            'boot_id': BOOT,
            'policy_sha256': f.policy_sha,
            'ledger_preimage_sha256': ledger_sha,
            'manifest_sha256': digest(f.manifest_b_path),
            'run_id': RUN_B,
            'prior_run_id': RUN_A,
            'recovery_id': RECOVERY_A,
            'canonical_recovery_receipt_sha256': digest(canonical),
            'run_recovery_receipt_sha256': digest(f.output_a / 'recovery.json'),
            'a_output_sha256': f.helper.evidence_digest(f.output_a),
            'a_activation_sha256': f.activation_a_sha,
            'automatic_retry': False,
        }
        path = f.helper.activation_path(f.vm, BOOT, RUN_B)
        path.write_text(json.dumps(activation, indent=2) + '\n')
        return activation, path, digest(path)

    def test_a_appends_revision_and_row_five_without_rewriting_history(self):
        f = self.fixture(); self.addCleanup(f.cleanup.cleanup)
        before = json.loads(f.ledger_path.read_text())
        authorization = self.authorize_a(f)
        updated = self.reserve(f, authorization)
        self.assertEqual(updated['schema'], 4)
        self.assertEqual(updated['initial_max_launches'], 3)
        self.assertEqual(updated['max_launches'], 6)
        self.assertEqual(updated['launches'][:4], before['launches'])
        self.assertEqual(len(updated['launches']), 5)
        self.assertEqual(updated['launches'][4]['run_id'], RUN_A)
        self.assertEqual(updated['launches'][4]['qualification_ordinal'], 'A')
        self.assertEqual(len(updated['cap_revisions']), 2)
        self.assertEqual(updated['cap_revisions'][0], before['cap_revisions'][0])
        self.assertEqual(updated['cap_revisions'][1]['from_max_launches'], 4)
        self.assertEqual(updated['cap_revisions'][1]['to_max_launches'], 6)

    def test_b_requires_successful_a_and_appends_only_row_six(self):
        f = self.fixture(); self.addCleanup(f.cleanup.cleanup)
        self.reserve(f, self.authorize_a(f))
        _, _, activation_sha = self.activate_b(f)
        authorization, errors = f.helper.authorize(
            f.vm, f.manifest_b, f.manifest_b_path, f.output_b,
            f.policy_sha, activation_sha, self.hooks())
        self.assertEqual(errors, [])
        self.assertEqual(authorization['stage'], 'B')
        before = json.loads(f.ledger_path.read_text())
        receipt = authorization['receipt']
        gate = self.gate(
            f.manifest_b, receipt,
            's=gate;i=3f3b1;b=' + BOOT + ';m=3')
        _, updated = f.helper.build_reservation(
            authorization, BOOT, RUN_B, receipt, gate, reserved_epoch=124.0)
        self.assertEqual(updated['launches'][:5], before['launches'])
        self.assertEqual(len(updated['launches']), 6)
        self.assertEqual(updated['launches'][5]['qualification_ordinal'], 'B')
        f.ledger_path.write_text(json.dumps(updated, indent=2) + '\n')
        replay, replay_errors = f.helper.authorize(
            f.vm, f.manifest_b, f.manifest_b_path, f.output_b,
            f.policy_sha, activation_sha, self.hooks())
        self.assertIsNone(replay)
        self.assertIn('warm_qualification_ledger', replay_errors)

    def test_b_closes_on_missing_or_invalid_a_evidence(self):
        cases = ('missing-output', 'probe-missing', 'probe-unexpected',
                 'probe-abbreviated-nomemory', 'probe-false-success',
                 'capture-loss', 'shutdown', 'verdict-error', 'host-fault',
                 'receipt-mismatch')
        for case in cases:
            with self.subTest(case=case):
                f = self.fixture(); self.addCleanup(f.cleanup.cleanup)
                self.reserve(f, self.authorize_a(f))
                if case == 'missing-output':
                    _, _, activation_sha = self.activate_b(f)
                    for path in f.output_a.iterdir(): path.unlink()
                    f.output_a.rmdir()
                else:
                    _, activation_path, activation_sha = self.activate_b(f)
                    if case == 'probe-missing':
                        (f.output_a / 'probe.json').unlink()
                    elif case == 'probe-unexpected':
                        probe = json.loads((f.output_a / 'probe.json').read_text())
                        probe['output'] = ('RGPU_METAL_RESULT ' + json.dumps({
                            'passed': False, 'run_id': RUN_A,
                            'completed_command_buffers': 0,
                            'error': 'unexpected failure'}) + '\n' +
                            f'RGPU_EXIT {RUN_A} 1\n')
                        (f.output_a / 'probe.json').write_text(json.dumps(probe))
                    elif case == 'probe-abbreviated-nomemory':
                        probe = json.loads((f.output_a / 'probe.json').read_text())
                        probe['output'] = ('RGPU_METAL_RESULT ' + json.dumps({
                            'passed': False, 'run_id': RUN_A,
                            'completed_command_buffers': 0,
                            'error': 'e00002bd'}) + '\n' +
                            f'RGPU_EXIT {RUN_A} 1\n')
                        (f.output_a / 'probe.json').write_text(json.dumps(probe))
                    elif case == 'probe-false-success':
                        probe = json.loads((f.output_a / 'probe.json').read_text())
                        probe['output'] = ('RGPU_METAL_RESULT ' + json.dumps({
                            'passed': True, 'run_id': RUN_A,
                            'metal3': True}) + '\n' + f'RGPU_EXIT {RUN_A} 0\n')
                        (f.output_a / 'probe.json').write_text(json.dumps(probe))
                    elif case == 'capture-loss':
                        (f.output_a / 'events.jsonl').write_text(
                            json.dumps({'kind': 'capture_loss'}) + '\n')
                    elif case == 'shutdown':
                        (f.output_a / 'shutdown.json').write_text(json.dumps({
                            'outcome': 'forced-after-abort'}))
                    elif case == 'verdict-error':
                        verdict = json.loads((f.output_a / 'verdict.json').read_text())
                        verdict['error'] = 'runtime failure'
                        (f.output_a / 'verdict.json').write_text(json.dumps(verdict))
                    elif case == 'host-fault':
                        (f.output_a / 'host-kernel-messages.json').write_text(
                            json.dumps(['AMD-Vi: IO_PAGE_FAULT']) + '\n')
                    else:
                        recovery = json.loads((f.output_a / 'recovery.json').read_text())
                        recovery['recovery_id'] = 'd4' * 16
                        (f.output_a / 'recovery.json').write_text(json.dumps(recovery))
                    activation = json.loads(activation_path.read_text())
                    activation['a_output_sha256'] = f.helper.evidence_digest(f.output_a)
                    activation['run_recovery_receipt_sha256'] = digest(
                        f.output_a / 'recovery.json')
                    activation_path.write_text(json.dumps(activation, indent=2) + '\n')
                    activation_sha = digest(activation_path)
                authorization, errors = f.helper.authorize(
                    f.vm, f.manifest_b, f.manifest_b_path, f.output_b,
                    f.policy_sha, activation_sha, self.hooks())
                self.assertIsNone(authorization)
                self.assertIn('warm_qualification_a_evidence', errors)

    def test_rejects_manifest_drift_malformed_authority_and_replay(self):
        cases = ('manifest-b-drift', 'policy-sha', 'policy-field',
                 'activation-sha', 'activation-field', 'ledger-drift',
                 'output-in-repo', 'equal-output-paths',
                 'equal-manifest-paths', 'policy-array', 'activation-array')
        for case in cases:
            with self.subTest(case=case):
                f = self.fixture(); self.addCleanup(f.cleanup.cleanup)
                policy_sha = f.policy_sha
                activation_sha = f.activation_a_sha
                output = f.output_a
                if case == 'manifest-b-drift':
                    changed = json.loads(f.manifest_b_path.read_text())
                    changed['binary_sha256'] = '0' * 64
                    f.manifest_b_path.write_text(json.dumps(changed, indent=2) + '\n')
                    policy = json.loads(f.policy_path.read_text())
                    policy['manifest_b_sha256'] = digest(f.manifest_b_path)
                    f.policy_path.write_text(json.dumps(policy, indent=2) + '\n')
                    policy_sha = digest(f.policy_path)
                    activation = json.loads(f.activation_a_path.read_text())
                    activation['policy_sha256'] = policy_sha
                    f.activation_a_path.write_text(json.dumps(activation, indent=2) + '\n')
                    activation_sha = digest(f.activation_a_path)
                elif case == 'policy-sha':
                    policy_sha = '0' * 64
                elif case == 'policy-field':
                    policy = json.loads(f.policy_path.read_text())
                    policy['automatic_extension'] = True
                    f.policy_path.write_text(json.dumps(policy, indent=2) + '\n')
                    policy_sha = digest(f.policy_path)
                    activation = json.loads(f.activation_a_path.read_text())
                    activation['policy_sha256'] = policy_sha
                    f.activation_a_path.write_text(json.dumps(activation, indent=2) + '\n')
                    activation_sha = digest(f.activation_a_path)
                elif case == 'activation-sha':
                    activation_sha = '0' * 64
                elif case == 'activation-field':
                    activation = json.loads(f.activation_a_path.read_text())
                    activation['automatic_retry'] = True
                    f.activation_a_path.write_text(json.dumps(activation, indent=2) + '\n')
                    activation_sha = digest(f.activation_a_path)
                elif case == 'ledger-drift':
                    f.ledger_path.write_bytes(f.ledger_path.read_bytes() + b' ')
                elif case == 'equal-output-paths':
                    policy = json.loads(f.policy_path.read_text())
                    policy['output_b_path'] = policy['output_a_path']
                    f.policy_path.write_text(json.dumps(policy, indent=2) + '\n')
                    policy_sha = digest(f.policy_path)
                    activation = json.loads(f.activation_a_path.read_text())
                    activation['policy_sha256'] = policy_sha
                    f.activation_a_path.write_text(json.dumps(activation, indent=2) + '\n')
                    activation_sha = digest(f.activation_a_path)
                elif case == 'equal-manifest-paths':
                    policy = json.loads(f.policy_path.read_text())
                    policy['manifest_b_path'] = policy['manifest_a_path']
                    policy['manifest_b_sha256'] = policy['manifest_a_sha256']
                    f.policy_path.write_text(json.dumps(policy, indent=2) + '\n')
                    policy_sha = digest(f.policy_path)
                    activation = json.loads(f.activation_a_path.read_text())
                    activation['policy_sha256'] = policy_sha
                    f.activation_a_path.write_text(json.dumps(activation, indent=2) + '\n')
                    activation_sha = digest(f.activation_a_path)
                elif case == 'policy-array':
                    f.policy_path.write_text('[]\n')
                    policy_sha = digest(f.policy_path)
                elif case == 'activation-array':
                    f.activation_a_path.write_text('[]\n')
                    activation_sha = digest(f.activation_a_path)
                else:
                    output = ROOT / 'run/forbidden-warm-output'
                authorization, errors = f.helper.authorize(
                    f.vm, f.manifest_a, f.manifest_a_path, output,
                    policy_sha, activation_sha, self.hooks())
                self.assertIsNone(authorization)
                self.assertTrue(errors)

    def test_build_reservation_rejects_stale_bundle_and_argument_substitution(self):
        f = self.fixture(); self.addCleanup(f.cleanup.cleanup)
        authorization = self.authorize_a(f)
        gate = self.gate(
            f.manifest_a, authorization['receipt'],
            's=gate;i=3f3b0;b=' + BOOT + ';m=2')
        for boot, run, receipt, bundle in (
                ('other-boot', RUN_A, authorization['receipt'], authorization),
                (BOOT, RUN_B, authorization['receipt'], authorization),
                (BOOT, RUN_A, {}, authorization),
                (BOOT, RUN_A, authorization['receipt'],
                 dict(authorization, ledger_raw=b'changed'))):
            with self.subTest(boot=boot, run=run, receipt=bool(receipt)):
                with self.assertRaisesRegex(ValueError, 'warm qualification refused'):
                    f.helper.build_reservation(
                        bundle, boot, run, receipt, gate, reserved_epoch=123.0)
        self.assertEqual(digest(f.ledger_path), f.helper.FOUR_ROW_LEDGER_SHA256)

    def test_b_rejects_rewritten_historical_prefix_with_fresh_activation(self):
        for case in ('launch', 'revision', 'truncated-a-host-gate',
                     'unrelated-a-cursor'):
            with self.subTest(case=case):
                f = self.fixture(); self.addCleanup(f.cleanup.cleanup)
                self.reserve(f, self.authorize_a(f))
                _, activation_path, _ = self.activate_b(f)
                ledger = json.loads(f.ledger_path.read_text())
                if case == 'launch':
                    ledger['launches'][0]['run_id'] = '9' * 32
                elif case == 'revision':
                    ledger['cap_revisions'][0]['purpose'] = 'rewritten'
                elif case == 'truncated-a-host-gate':
                    ledger['cap_revisions'][1]['host_gate'] = {'boot_id': BOOT}
                else:
                    ledger['cap_revisions'][1]['kernel_cursor_before'] = (
                        's=x;i=1;b=' + BOOT + ';m=1')
                f.ledger_path.write_text(json.dumps(ledger, indent=2) + '\n')
                activation = json.loads(activation_path.read_text())
                activation['ledger_preimage_sha256'] = digest(f.ledger_path)
                activation_path.write_text(json.dumps(activation, indent=2) + '\n')
                authorization, errors = f.helper.authorize(
                    f.vm, f.manifest_b, f.manifest_b_path, f.output_b,
                    f.policy_sha, digest(activation_path), self.hooks())
                self.assertIsNone(authorization)
                self.assertIn('warm_qualification_ledger', errors)

    def test_builder_rejects_empty_gates_and_nonmonotonic_cursor(self):
        f = self.fixture(); self.addCleanup(f.cleanup.cleanup)
        authorization = self.authorize_a(f)
        receipt = authorization['receipt']
        good = self.gate(
            f.manifest_a, receipt, 's=x;i=3f3b0;b=' + BOOT + ';m=2')
        for changed in (
                dict(good, host_gate={}), dict(good, vfio_gate={}),
                dict(good, identity_gate={}),
                dict(good, kernel_cursor_after='s=x;i=0;b=' + BOOT + ';m=2')):
            with self.assertRaisesRegex(ValueError, 'warm qualification refused'):
                f.helper.build_reservation(
                    authorization, BOOT, RUN_A, receipt, changed, 123.0)


if __name__ == '__main__':
    unittest.main()
