import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import tempfile
import unittest
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
BOOT = '5d6f45d0-4384-4340-b819-7751bc26ebb3'
PRIOR = '4a45f4a4c1dd49c69fab2dc37e2e4898'
RECOVERY = '8fb71c4acf944fa3b6ee545dfb58a448'
RUN = '0123456789abcdeffedcba9876543210'
FROZEN = ROOT / 'findings/experiments/metal-011-178-b'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Candidate179QualificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = ROOT / 'tools/candidate179-qualification.py'
        spec = importlib.util.spec_from_file_location(
            'candidate179_qualification', path)
        cls.helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.helper)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.vm = Path(self.temporary.name)
        helper = self.helper
        ledger = self.vm / 'run/used-gpu-boots' / f'{BOOT}.json'
        ledger.parent.mkdir(parents=True)
        shutil.copyfile(FROZEN / 'used-gpu-boot-ledger.json', ledger)
        canonical = self.vm / 'run/vfio-recovery' / BOOT / f'{PRIOR}.json'
        canonical.parent.mkdir(parents=True)
        shutil.copyfile(FROZEN / 'canonical-recovery-receipt.json', canonical)
        run_receipt = self.vm / 'run/metal-011-178-b/recovery.json'
        run_receipt.parent.mkdir(parents=True)
        shutil.copyfile(FROZEN / 'recovery.json', run_receipt)

        self.card_path = ROOT / 'experiments/metal-012.json'
        self.card = json.loads(self.card_path.read_text())

        nonce_lo, nonce_hi = struct.unpack('<QQ', bytes.fromhex(RUN))
        helpers = helper.current_recovery_helpers_sha256()
        self.manifest = {
            'boot_id':BOOT, 'run_id':RUN, 'gpu':True,
            'candidate_directory':'run/candidate-179',
            'experiment':'metal-012', 'max_seconds':180,
            'recovery_lease_schema':2,
            'recovery_helpers_sha256':helpers,
            'boot_args':('rgpu=0xfffa5981 rgpuvmm=3 rgpumem=1 rgpuptb=2 '
                         'rgpumqd=2 rgpuhybrid=1 rgpusubmit=1 '
                         f'rgpurnlo={nonce_lo} rgpurnhi=0x{nonce_hi:x}'),
            'source_clean':True, 'bootdisk_verified':True,
            'build_id':'4' * 32, 'source_sha256':'1' * 64,
            'binary_sha256':'2' * 64, 'bootdisk_sha256':'3' * 64,
            'spec':self.card,
        }
        manifest_dir = self.vm / 'run/candidate179-qualification-manifests'
        manifest_dir.mkdir(parents=True)
        self.manifest_path = manifest_dir / '179.json'
        self.manifest_path.write_text(json.dumps(self.manifest, indent=2) + '\n')
        self.output = self.vm / 'run/metal-012-179'

        policy = {
            'schema':1, 'kind':'candidate179-one-run-qualification-policy',
            'boot_id':BOOT,
            'ledger_preimage_sha256':helper.TERMINAL_LEDGER_SHA256,
            'prior_run_id':PRIOR, 'prior_recovery_id':RECOVERY,
            'prior_canonical_receipt_sha256':helper.PRIOR_CANONICAL_RECEIPT_SHA256,
            'prior_run_receipt_sha256':helper.PRIOR_RUN_RECEIPT_SHA256,
            'design_sha256':digest(helper.DESIGN_PATH),
            'experiment_py_sha256':digest(ROOT / 'tools/experiment.py'),
            'qualification_helper_sha256':digest(
                ROOT / 'tools/candidate179-qualification.py'),
            'recovery_helpers_sha256':helpers,
            'experiment_card_sha256':digest(self.card_path),
            'manifest_path':'run/candidate179-qualification-manifests/179.json',
            'manifest_sha256':digest(self.manifest_path), 'run_id':RUN,
            'output_path':'run/metal-012-179',
            'from_max_launches':6, 'to_max_launches':7,
            'additional_launches':1, 'vm_max_seconds':180,
            'probe_max_seconds':45, 'automatic_extension':False,
            'automatic_retry':False,
            'purpose':'candidate179-native-vmm-arena-one-run',
        }
        self.policy_path = helper.policy_path(self.vm, BOOT)
        self.policy_path.parent.mkdir(parents=True)
        self.policy_path.write_text(json.dumps(policy, sort_keys=True) + '\n')
        self.policy_sha = digest(self.policy_path)
        activation = {
            'schema':1, 'kind':'candidate179-one-run-qualification-activation',
            'stage':'ONLY', 'boot_id':BOOT, 'policy_sha256':self.policy_sha,
            'ledger_preimage_sha256':helper.TERMINAL_LEDGER_SHA256,
            'manifest_sha256':digest(self.manifest_path), 'run_id':RUN,
            'prior_run_id':PRIOR, 'recovery_id':RECOVERY,
            'canonical_recovery_receipt_sha256':
                helper.PRIOR_CANONICAL_RECEIPT_SHA256,
            'run_recovery_receipt_sha256':helper.PRIOR_RUN_RECEIPT_SHA256,
            'automatic_retry':False,
        }
        self.activation_path = helper.activation_path(self.vm, BOOT, RUN)
        self.activation_path.write_text(json.dumps(activation, sort_keys=True) + '\n')
        self.activation_sha = digest(self.activation_path)

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

    def reseal_manifest(self):
        self.manifest_path.write_text(json.dumps(self.manifest, indent=2) + '\n')
        policy = json.loads(self.policy_path.read_text())
        policy['manifest_sha256'] = digest(self.manifest_path)
        self.policy_path.write_text(json.dumps(policy, sort_keys=True) + '\n')
        self.policy_sha = digest(self.policy_path)
        activation = json.loads(self.activation_path.read_text())
        activation['manifest_sha256'] = digest(self.manifest_path)
        activation['policy_sha256'] = self.policy_sha
        self.activation_path.write_text(json.dumps(activation, sort_keys=True) + '\n')
        self.activation_sha = digest(self.activation_path)

    def create_owned_output(self):
        self.output.mkdir()
        (self.output / 'manifest.json').write_bytes(self.manifest_path.read_bytes())
        (self.output / 'host-before.json').write_text(
            json.dumps({'boot_id':BOOT}) + '\n')

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

    def test_authorizes_read_only_and_builds_exact_single_append(self):
        ledger_path = self.vm / 'run/used-gpu-boots' / f'{BOOT}.json'
        before_raw = ledger_path.read_bytes()
        before = json.loads(before_raw)

        authorization, errors = self.authorize()
        self.assertEqual(errors, [])
        self.assertIsNotNone(authorization)
        self.assertEqual(ledger_path.read_bytes(), before_raw)
        self.create_owned_output()
        path, updated = self.helper.build_reservation(
            authorization, BOOT, RUN, authorization['receipt'],
            self.gate(authorization), 123.5)

        self.assertEqual(path, ledger_path)
        self.assertEqual(ledger_path.read_bytes(), before_raw)
        self.assertEqual(updated['schema'], 5)
        self.assertEqual(updated['initial_max_launches'], 3)
        self.assertEqual(updated['max_launches'], 7)
        self.assertEqual(updated['launches'][:6], before['launches'])
        self.assertEqual(updated['cap_revisions'][:2], before['cap_revisions'])
        self.assertEqual(len(updated['launches']), 7)
        self.assertEqual(len(updated['cap_revisions']), 3)
        self.assertEqual(updated['launches'][-1], {
            'run_id':RUN, 'reserved_epoch':123.5,
            'recovery_id':RECOVERY, 'prior_run_id':PRIOR,
            'candidate179_policy_sha256':self.policy_sha,
            'candidate179_activation_sha256':self.activation_sha,
            'qualification':'candidate179-native-vmm-arena-one-run',
            'qualification_ordinal':'ONLY',
        })
        revision = updated['cap_revisions'][-1]
        self.assertEqual((revision['from_max_launches'], revision['to_max_launches'],
                          revision['additional_launches']), (6, 7, 1))
        self.assertIs(revision['automatic_extension'], False)
        self.assertIs(revision['automatic_retry'], False)

    def test_manifest_nonce_helper_or_receipt_drift_is_rejected(self):
        mutations = (
            lambda: self.manifest.update(boot_args=self.manifest['boot_args'].replace(
                'rgpurnlo=17279655951921914625', 'rgpurnlo=1')),
            lambda: self.manifest['recovery_helpers_sha256'].update(
                {'tools/recovery_lease_v2.py':'0' * 64}),
            lambda: (self.vm / 'run/vfio-recovery' / BOOT / f'{PRIOR}.json').write_text('{}'),
        )
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                self.tearDown()
                self.setUp()
                mutate()
                authorization, errors = self.authorize()
                self.assertIsNone(authorization)
                self.assertTrue(errors)

    def test_resealed_duplicate_or_retired_gpu_argument_is_rejected(self):
        mutations = (
            lambda: self.manifest.update(
                boot_args=self.manifest['boot_args'] + ' rgpurnlo=1'),
            lambda: self.manifest.update(
                boot_args=self.manifest['boot_args'] + ' rgpucp=0'),
        )
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                self.tearDown()
                self.setUp()
                mutate()
                self.reseal_manifest()
                authorization, errors = self.authorize()
                self.assertIsNone(authorization)
                self.assertIn('candidate179_manifest', errors)

    def test_replay_and_incomplete_live_gate_fail_closed(self):
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

    def test_rejected_authorization_does_not_write_vm_tree(self):
        before = {
            path.relative_to(self.vm):path.read_bytes()
            for path in self.vm.rglob('*') if path.is_file()
        }
        self.manifest['recovery_lease_schema'] = 1

        authorization, errors = self.authorize()

        after = {
            path.relative_to(self.vm):path.read_bytes()
            for path in self.vm.rglob('*') if path.is_file()
        }
        self.assertIsNone(authorization)
        self.assertIn('candidate179_manifest', errors)
        self.assertEqual(after, before)

    def test_build_rechecks_exact_identity_receipt_and_finite_epoch(self):
        authorization, errors = self.authorize()
        self.assertEqual(errors, [])
        self.create_owned_output()
        cases = []
        wrong_identity = self.gate(authorization)
        wrong_identity['identity_gate']['recovery_helpers_sha256'] = {
            'tools/vfio-recover.py':'0' * 64,
        }
        cases.append((authorization['receipt'], wrong_identity, 1, 'live_gate'))
        wrong_receipt = copy.deepcopy(authorization['receipt'])
        wrong_receipt['authorizes_launch'] = False
        cases.append((wrong_receipt, self.gate(authorization), 1, 'arguments'))
        cases.append((authorization['receipt'], self.gate(authorization),
                      float('nan'), 'arguments'))
        for recovery, gate, epoch, error in cases:
            with self.subTest(error=error, epoch=epoch):
                with self.assertRaisesRegex(ValueError, error):
                    self.helper.build_reservation(
                        authorization, BOOT, RUN, recovery, gate, epoch)

    def test_build_rejects_mutable_authorization_or_output_drift_without_writes(self):
        for mutation in ('manifest', 'policy', 'output'):
            with self.subTest(mutation=mutation):
                self.tearDown()
                self.setUp()
                authorization, errors = self.authorize()
                self.assertEqual(errors, [])
                self.create_owned_output()
                gate = self.gate(authorization)
                if mutation == 'manifest':
                    authorization['manifest']['boot_args'] += ' rgpurnlo=1'
                    gate['identity_gate']['boot_args'] += ' rgpurnlo=1'
                elif mutation == 'policy':
                    authorization['policy']['automatic_retry'] = True
                else:
                    (self.output / 'unexpected.json').write_text('{}\n')
                before = {
                    path.relative_to(self.vm):path.read_bytes()
                    for path in self.vm.rglob('*') if path.is_file()
                }
                with self.assertRaisesRegex(ValueError, 'concurrent_change'):
                    self.helper.build_reservation(
                        authorization, BOOT, RUN, authorization['receipt'], gate, 1)
                after = {
                    path.relative_to(self.vm):path.read_bytes()
                    for path in self.vm.rglob('*') if path.is_file()
                }
                self.assertEqual(after, before)


if __name__ == '__main__':
    unittest.main()
