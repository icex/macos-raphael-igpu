import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
BOOT = '5aa7641a-6dd5-4cb6-a482-5bd1b15fa946'
PRIOR = '7966fb1045ddeae71535030cd94deab1'
RECOVERY = '74d7749f63c04cdaa0034df35c58d308'
RUN = '0123456789abcdeffedcba9876543210'
CURSOR = 's=98f6cb2295dc45898ee97031451ba7c8;i=41f4c;b=5aa7641a6dd54cb6a4825bd1b15fa946;m=e92e9098'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class OneRunQualificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = ROOT / 'tools/one-run-qualification.py'
        spec = importlib.util.spec_from_file_location('one_run_qualification', path)
        cls.helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.helper)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.vm = Path(self.temporary.name)
        helper = self.helper
        self.card_path = ROOT / 'experiments/metal-014.json'
        self.card = json.loads(self.card_path.read_text())
        helpers = helper.current_recovery_helpers_sha256(3)

        ledger = self.vm / 'run/used-gpu-boots' / f'{BOOT}.json'
        ledger.parent.mkdir(parents=True)
        ledger.write_text(json.dumps({
            'schema':2, 'boot_id':BOOT, 'max_launches':3,
            'launches':[{'run_id':PRIOR, 'reserved_epoch':1.0}]}, indent=2) + '\n')
        self.receipt = {
            'schema':6, 'status':'recovered', 'authorizes_launch':True,
            'boot_id':BOOT, 'prior_run_id':PRIOR, 'recovery_id':RECOVERY,
            'recovery_helpers_sha256':helpers, 'kernel_cursor_after':CURSOR,
        }
        canonical = self.vm / 'run/vfio-recovery' / BOOT / f'{PRIOR}.json'
        canonical.parent.mkdir(parents=True)
        canonical.write_text(json.dumps(self.receipt, indent=2) + '\n')
        retry = self.vm / 'run/metal-013-180/recovery-retry.json'
        retry.parent.mkdir(parents=True)
        retry.write_text(json.dumps({'proof_sha256':'0' * 64,
                                     'recovery':self.receipt}) + '\n')

        nonce_lo, nonce_hi = struct.unpack('<QQ', bytes.fromhex(RUN))
        self.manifest = {
            'boot_id':BOOT, 'run_id':RUN, 'gpu':True,
            'candidate_directory':'run/candidate-181',
            'experiment':'metal-014', 'max_seconds':180,
            'recovery_lease_schema':3, 'critical_replay_schema':2,
            'critical_replay_tolerance':'terminal-prefix',
            'recovery_helpers_sha256':helpers,
            'boot_args':('rgpu=0xfffa5981 rgpuvmm=3 rgpumem=1 rgpuptb=2 '
                         'rgpumqd=2 rgpuhybrid=1 rgpusubmit=1 rgpuvmroot=3 '
                         f'rgpurnlo={nonce_lo} rgpurnhi=0x{nonce_hi:x}'),
            'source_clean':True, 'bootdisk_verified':True,
            'build_id':'4' * 32, 'source_sha256':'1' * 64,
            'binary_sha256':'2' * 64, 'bootdisk_sha256':'3' * 64,
            'spec':self.card,
        }
        manifest_dir = self.vm / 'run/one-run-qualification-manifests'
        manifest_dir.mkdir(parents=True)
        self.manifest_path = manifest_dir / '181.json'
        self.manifest_path.write_text(json.dumps(self.manifest, indent=2) + '\n')
        self.output = self.vm / 'run/metal-014-181'
        created = helper.create(
            self.vm, BOOT, PRIOR, 'run/metal-013-180/recovery-retry.json', 'recovery',
            'experiments/metal-014.json', 'run/one-run-qualification-manifests/181.json',
            'run/metal-014-181', 'candidate181-entry-conversion-one-run')
        self.policy_path = Path(created['policy_path'])
        self.policy_sha = created['policy_sha256']
        self.activation_path = Path(created['activation_path'])
        self.activation_sha = created['activation_sha256']

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def hooks():
        return SimpleNamespace(
            validate_receipt=lambda receipt, boot, prior: [],
            validate_host=lambda host, boot: [],
            validate_vfio=lambda vfio, boot: [],
        )

    def authorize(self):
        return self.helper.authorize(
            self.vm, self.manifest, self.manifest_path, self.output,
            self.policy_sha, self.activation_sha, self.hooks())

    def reseal(self):
        self.manifest_path.write_text(json.dumps(self.manifest, indent=2) + '\n')
        for path in (self.policy_path, self.activation_path):
            path.unlink()
        created = self.helper.create(
            self.vm, BOOT, PRIOR, 'run/metal-013-180/recovery-retry.json', 'recovery',
            'experiments/metal-014.json', 'run/one-run-qualification-manifests/181.json',
            'run/metal-014-181', 'candidate181-entry-conversion-one-run')
        self.policy_sha = created['policy_sha256']
        self.activation_sha = created['activation_sha256']

    def create_owned_output(self):
        self.output.mkdir()
        (self.output / 'manifest.json').write_bytes(self.manifest_path.read_bytes())
        (self.output / 'host-before.json').write_text(json.dumps({'boot_id':BOOT}) + '\n')

    def gate(self, authorization):
        receipt = authorization['receipt']
        return {
            'kernel_cursor_before':receipt['kernel_cursor_after'],
            'kernel_cursor_after':receipt['kernel_cursor_after'],
            'kernel_messages':[], 'host_gate':{'boot_id':BOOT},
            'vfio_gate':{'boot_id':BOOT},
            'identity_gate':{
                key:copy.deepcopy(self.manifest[key]) for key in (
                    'run_id', 'boot_id', 'boot_args', 'recovery_lease_schema',
                    'recovery_helpers_sha256', 'build_id', 'source_sha256',
                    'binary_sha256', 'bootdisk_sha256')},
            'active_launch_units':[], 'pending_launches':[],
        }

    def test_policy_pins_every_live_input(self):
        policy = json.loads(self.policy_path.read_text())
        self.assertEqual(set(policy), self.helper.POLICY_FIELDS)
        self.assertEqual(policy['experiment_py_sha256'], digest(ROOT / 'tools/experiment.py'))
        self.assertEqual(policy['qualification_helper_sha256'],
                         digest(ROOT / 'tools/one-run-qualification.py'))
        self.assertEqual(policy['design_sha256'], digest(self.helper.DESIGN_PATH))
        self.assertEqual((policy['from_max_launches'], policy['to_max_launches'],
                          policy['additional_launches']), (3, 3, 0))
        self.assertEqual(policy['prior_recovery_id'], RECOVERY)

    def test_authorizes_read_only_and_appends_exactly_one_row(self):
        ledger_path = self.vm / 'run/used-gpu-boots' / f'{BOOT}.json'
        before_raw = ledger_path.read_bytes()
        authorization, errors = self.authorize()
        self.assertEqual(errors, [])
        self.assertEqual(ledger_path.read_bytes(), before_raw)
        self.create_owned_output()
        path, updated = self.helper.build_reservation(
            authorization, BOOT, RUN, authorization['receipt'],
            self.gate(authorization), 123.5)
        self.assertEqual(path, ledger_path)
        self.assertEqual(ledger_path.read_bytes(), before_raw)
        self.assertEqual(updated['schema'], 2)
        self.assertEqual(updated['max_launches'], 3)
        self.assertNotIn('cap_revisions', updated)
        self.assertEqual(len(updated['launches']), 2)
        self.assertEqual(updated['launches'][-1], {
            'run_id':RUN, 'reserved_epoch':123.5, 'recovery_id':RECOVERY,
            'prior_run_id':PRIOR, 'one_run_policy_sha256':self.policy_sha,
            'one_run_activation_sha256':self.activation_sha,
            'qualification':'candidate181-entry-conversion-one-run',
            'qualification_ordinal':'ONLY'})

    def test_manifest_nonce_helper_receipt_and_ledger_drift_are_rejected(self):
        mutations = (
            ('_manifest', lambda: self.manifest.update(
                boot_args=self.manifest['boot_args'].replace('rgpuvmroot=3', 'rgpuvmroot=1'))),
            ('_manifest', lambda: self.manifest.update(recovery_lease_schema=2)),
            ('_manifest', lambda: self.manifest.update(critical_replay_tolerance=None)),
            ('_manifest', lambda: self.manifest['recovery_helpers_sha256'].update(
                {'tools/critical-replay.py':'0' * 64})),
            ('_receipt', lambda: (self.vm / 'run/vfio-recovery' / BOOT / f'{PRIOR}.json')
                .write_text(json.dumps(dict(self.receipt, authorizes_launch=False)))),
            ('_ledger', lambda: (self.vm / 'run/used-gpu-boots' / f'{BOOT}.json').write_text(json.dumps({
                'schema':2, 'boot_id':BOOT, 'max_launches':3,
                'launches':[{'run_id':PRIOR}, {'run_id':'f' * 32, 'recovery_id':RECOVERY}]}))),
        )
        for label, mutate in mutations:
            with self.subTest(label=label):
                self.tearDown(); self.setUp()
                mutate()
                authorization, errors = self.authorize()
                self.assertIsNone(authorization)
                self.assertTrue(errors)
                self.assertTrue(any(error.endswith(label) or error.endswith('_authority')
                                    for error in errors), errors)

    def test_resealed_duplicate_or_retired_argument_is_rejected(self):
        for extra in (' rgpurnlo=1', ' rgpucp=0'):
            with self.subTest(extra=extra):
                self.tearDown(); self.setUp()
                self.manifest['boot_args'] += extra
                self.reseal()
                authorization, errors = self.authorize()
                self.assertIsNone(authorization)
                self.assertIn('one-run_manifest', errors)

    def test_incomplete_live_gate_and_replay_fail_closed(self):
        authorization, errors = self.authorize()
        self.assertEqual(errors, [])
        ledger_path = self.vm / 'run/used-gpu-boots' / f'{BOOT}.json'
        gate = self.gate(authorization)
        self.create_owned_output()
        replay = json.loads(ledger_path.read_text())
        replay['launches'].append({'run_id':RUN})
        ledger_path.write_text(json.dumps(replay))
        with self.assertRaisesRegex(ValueError, 'concurrent_change|launch_ceiling'):
            self.helper.build_reservation(
                authorization, BOOT, RUN, authorization['receipt'], gate, 1)
        ledger_path.write_bytes(authorization['ledger_raw'])
        gate['pending_launches'] = ['pending.json']
        with self.assertRaisesRegex(ValueError, 'live_gate'):
            self.helper.build_reservation(
                authorization, BOOT, RUN, authorization['receipt'], gate, 1)
        faulted = self.gate(authorization)
        faulted['kernel_messages'] = ['AMD-Vi: Event logged [IO_PAGE_FAULT device=7b:00.0]']
        with self.assertRaisesRegex(ValueError, 'live_gate'):
            self.helper.build_reservation(
                authorization, BOOT, RUN, authorization['receipt'], faulted, 1)

    def test_rejected_authorization_does_not_write_vm_tree(self):
        before = {path.relative_to(self.vm):path.read_bytes()
                  for path in self.vm.rglob('*') if path.is_file()}
        authorization, errors = self.helper.authorize(
            self.vm, self.manifest, self.manifest_path, self.output,
            '0' * 64, self.activation_sha, self.hooks())
        after = {path.relative_to(self.vm):path.read_bytes()
                 for path in self.vm.rglob('*') if path.is_file()}
        self.assertIsNone(authorization)
        self.assertIn('one-run_authority', errors)
        self.assertEqual(after, before)


if __name__ == '__main__':
    unittest.main()
