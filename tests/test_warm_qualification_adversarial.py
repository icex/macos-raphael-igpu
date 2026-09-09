import importlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

base = importlib.import_module('tests.test_warm_qualification')
experiment_tests = importlib.import_module('tests.test_experiment')


class WarmQualificationAdversarialTests(unittest.TestCase):
    def fixture(self):
        owner = base.WarmQualificationTests(methodName='runTest')
        fixture = owner.fixture()
        self.addCleanup(fixture.cleanup.cleanup)
        return owner, fixture

    @staticmethod
    def hooks(parsed_events):
        return SimpleNamespace(
            validate_receipt=lambda receipt, boot, prior: [],
            validate_running=lambda manifest, running: [],
            classify_readiness=lambda manifest, events: {
                'valid': True, 'verdict': 'PROBE_NOT_RUN'},
            admit_host=lambda manifest, host, boots, reuse_allowed=False: [],
            parse_serial=lambda serial: parsed_events,
        )

    @staticmethod
    def reserve(fixture, authorization):
        receipt = authorization['receipt']
        manifest = authorization['manifest']
        identity_keys = ('image_id', 'build_id', 'source_sha256', 'boot_id',
                         'bootdisk_sha256')
        gate = {
            'kernel_cursor_before': receipt['kernel_cursor_after'],
            'kernel_cursor_after': 's=gate;i=ffffff;b=' + base.BOOT + ';m=2',
            'kernel_messages': [],
            'host_gate': {'boot_id': base.BOOT, 'sleep_inhibited': True},
            'vfio_gate': {'boot_id': base.BOOT, 'driver': 'vfio-pci'},
            'identity_gate': {key: manifest[key] for key in identity_keys},
            'active_launch_units': [],
            'pending_launches': [],
        }
        path, updated = fixture.helper.build_reservation(
            authorization, base.BOOT, manifest['run_id'], receipt, gate, 123.0)
        path.write_text(json.dumps(updated, indent=2) + '\n')

    def test_b_rejects_events_not_reparsed_from_a_serial(self):
        owner, fixture = self.fixture()
        self.reserve(fixture, owner.authorize_a(fixture))
        _, _, activation_sha = owner.activate_b(fixture)

        recorded = [json.loads(line) for line in
                    (fixture.output_a / 'events.jsonl').read_text().splitlines()]
        self.assertTrue(recorded)
        parsed = [dict(recorded[0], build='different-serial-build')]
        authorization, errors = fixture.helper.authorize(
            fixture.vm, fixture.manifest_b, fixture.manifest_b_path,
            fixture.output_b, fixture.policy_sha, activation_sha,
            self.hooks(parsed))

        self.assertIsNone(authorization)
        self.assertIn('warm_qualification_a_evidence', errors)

    def test_b_rejects_rewritten_preserved_ledger_prefix(self):
        mutations = (
            ('launch-row', lambda ledger: ledger['launches'][0].update(
                reserved_epoch=ledger['launches'][0]['reserved_epoch'] + 1)),
            ('original-revision', lambda ledger: ledger['cap_revisions'][0].update(
                purpose='rewritten-history')),
        )
        for label, mutate in mutations:
            with self.subTest(label=label):
                owner, fixture = self.fixture()
                self.reserve(fixture, owner.authorize_a(fixture))
                ledger = json.loads(fixture.ledger_path.read_text())
                mutate(ledger)
                fixture.ledger_path.write_text(json.dumps(ledger, indent=2) + '\n')
                _, _, activation_sha = owner.activate_b(fixture)

                authorization, errors = fixture.helper.authorize(
                    fixture.vm, fixture.manifest_b, fixture.manifest_b_path,
                    fixture.output_b, fixture.policy_sha, activation_sha,
                    owner.hooks())
                self.assertIsNone(authorization)
                self.assertIn('warm_qualification_ledger', errors)

    def test_b_rejects_a_row_or_revision_substitution(self):
        mutations = (
            ('a-row-recovery', lambda ledger: ledger['launches'][4].update(
                recovery_id='d4' * 16)),
            ('a-row-prior', lambda ledger: ledger['launches'][4].update(
                prior_run_id='e5' * 16)),
            ('a-revision-activation', lambda ledger: ledger['cap_revisions'][1].update(
                activation_a_sha256='f6' * 32)),
            ('a-revision-preimage', lambda ledger: ledger['cap_revisions'][1].update(
                ledger_preimage_sha256='07' * 32)),
        )
        for label, mutate in mutations:
            with self.subTest(label=label):
                owner, fixture = self.fixture()
                self.reserve(fixture, owner.authorize_a(fixture))
                ledger = json.loads(fixture.ledger_path.read_text())
                mutate(ledger)
                fixture.ledger_path.write_text(json.dumps(ledger, indent=2) + '\n')
                _, _, activation_sha = owner.activate_b(fixture)

                authorization, errors = fixture.helper.authorize(
                    fixture.vm, fixture.manifest_b, fixture.manifest_b_path,
                    fixture.output_b, fixture.policy_sha, activation_sha,
                    owner.hooks())
                self.assertIsNone(authorization)
                self.assertIn('warm_qualification_ledger', errors)

    def test_b_requires_the_exact_preserved_a_activation_file(self):
        for case in ('deleted', 'internally-consistent-substitution'):
            with self.subTest(case=case):
                owner, fixture = self.fixture()
                self.reserve(fixture, owner.authorize_a(fixture))
                _, activation_path, _ = owner.activate_b(fixture)
                if case == 'deleted':
                    fixture.activation_a_path.unlink()
                else:
                    invented = '09' * 32
                    ledger = json.loads(fixture.ledger_path.read_text())
                    ledger['launches'][4][
                        'warm_qualification_activation_sha256'] = invented
                    ledger['cap_revisions'][1][
                        'activation_a_sha256'] = invented
                    fixture.ledger_path.write_text(
                        json.dumps(ledger, indent=2) + '\n')
                    activation = json.loads(activation_path.read_text())
                    activation['a_activation_sha256'] = invented
                    activation['ledger_preimage_sha256'] = base.digest(
                        fixture.ledger_path)
                    activation_path.write_text(
                        json.dumps(activation, indent=2) + '\n')

                authorization, errors = fixture.helper.authorize(
                    fixture.vm, fixture.manifest_b, fixture.manifest_b_path,
                    fixture.output_b, fixture.policy_sha,
                    base.digest(activation_path), owner.hooks())
                self.assertIsNone(authorization)
                self.assertIn('warm_qualification_authority', errors)

    def integration_fixture(self, vm):
        used = vm / 'run/used-gpu-boots'
        used.mkdir(parents=True)
        manifest = {
            'boot_id': 'boot-A', 'run_id': 'd' * 32,
            'candidate_directory': 'run/candidate-178',
            'spec': {'requested_diagnostic': 'rgpusubmit=1'},
            'image_id': 'image', 'build_id': 'build',
            'source_sha256': 'source', 'bootdisk_sha256': 'disk',
            'source_clean': True, 'vfio_device': '0000:7b:00.0',
            'max_seconds': 180,
        }
        manifest_path = vm / 'run/a.json'
        manifest_path.write_text('{}\n')
        receipt = {'kernel_cursor_after': 's=x;i=10;b=boot-A;m=1'}
        authorization = {
            'policy_sha256': 'a' * 64, 'activation_sha256': 'b' * 64,
            'receipt': receipt, 'policy_raw': b'p', 'activation_raw': b'a',
            'ledger_raw': b'l', 'manifest_raws': [b'm1', b'm2'],
            'receipt_raws': [b'r1', b'r2'],
            'candidate176_receipt_raws': [b'c1', b'c2'],
        }
        identity = {key: manifest[key] for key in (
            'image_id', 'build_id', 'source_sha256', 'boot_id',
            'bootdisk_sha256')}
        host = {'boot_id': 'boot-A',
                'journal_cursor': 's=x;i=11;b=boot-A;m=2',
                'journal_messages': [], 'journal_faults': []}
        capture_host = dict(
            experiment_tests.ExperimentTests(methodName='runTest').host(),
            boot_id='boot-A', sleep_inhibited=True)
        return SimpleNamespace(
            used=used, manifest=manifest, manifest_path=manifest_path,
            output=vm / 'run/out', receipt=receipt,
            authorization=authorization, identity=identity,
            host=host, capture_host=capture_host,
            vfio={'boot_id': 'boot-A', 'driver': 'vfio-pci'},
        )

    def integration_helpers(self, tool, fixture, final):
        original_helper = tool.helper
        warm = SimpleNamespace(
            authorize=Mock(return_value=final),
            build_reservation=Mock(return_value=(
                fixture.used / 'boot-A.json', {'schema': 4})))
        retained = SimpleNamespace(
            collect_fresh_host=lambda cursor: fixture.host,
            host_errors=lambda host, boot, prefix='': [])
        recovery = SimpleNamespace(
            host_state=lambda: fixture.vfio,
            validate_host_state=lambda state, boot: [])

        def helpers(name):
            if name == 'warm-qualification':
                return warm
            if name == 'retained-kiq-continuation':
                return retained
            if name == 'vfio-recover':
                return recovery
            return original_helper(name)

        return warm, helpers

    def test_live_reservation_rejects_current_artifact_identity_drift(self):
        tool = experiment_tests.ExperimentTests(methodName='runTest').module()
        with tempfile.TemporaryDirectory() as temp:
            fixture = self.integration_fixture(Path(temp))
            final = (dict(fixture.authorization), [])
            warm, helpers = self.integration_helpers(tool, fixture, final)
            drifted = dict(fixture.identity, source_sha256='changed-source')
            with patch.object(tool, 'helper', side_effect=helpers), \
                 patch.object(tool, 'host_snapshot', return_value=fixture.capture_host), \
                 patch.object(tool, 'active_launch_units', return_value=[]), \
                 patch.object(tool, 'current_identity', return_value=drifted), \
                 patch.object(tool, 'replace_json') as replace:
                with self.assertRaisesRegex(ValueError, 'warm qualification'):
                    tool.reserve_warm_qualification(
                        fixture.used, 'boot-A', fixture.manifest['run_id'],
                        fixture.receipt, fixture.manifest, fixture.manifest_path,
                        fixture.output, fixture.authorization)
            warm.build_reservation.assert_not_called()
            replace.assert_not_called()

    def test_live_reservation_rejects_post_gate_authority_byte_drift(self):
        tool = experiment_tests.ExperimentTests(methodName='runTest').module()
        with tempfile.TemporaryDirectory() as temp:
            fixture = self.integration_fixture(Path(temp))
            changed = dict(fixture.authorization,
                           receipt_raws=[b'changed', b'r2'])
            warm, helpers = self.integration_helpers(
                tool, fixture, (fixture.authorization, []))
            warm.authorize.side_effect = [
                (fixture.authorization, []), (changed, [])]
            with patch.object(tool, 'helper', side_effect=helpers), \
                 patch.object(tool, 'host_snapshot', return_value=fixture.capture_host), \
                 patch.object(tool, 'active_launch_units', return_value=[]), \
                 patch.object(tool, 'current_identity', return_value=fixture.identity), \
                 patch.object(tool, 'replace_json') as replace:
                with self.assertRaisesRegex(ValueError, 'warm qualification'):
                    tool.reserve_warm_qualification(
                        fixture.used, 'boot-A', fixture.manifest['run_id'],
                        fixture.receipt, fixture.manifest, fixture.manifest_path,
                        fixture.output, fixture.authorization)
            warm.build_reservation.assert_not_called()
            replace.assert_not_called()

    def test_live_reservation_rejects_post_gate_a_evidence_race(self):
        tool = experiment_tests.ExperimentTests(methodName='runTest').module()
        with tempfile.TemporaryDirectory() as temp:
            fixture = self.integration_fixture(Path(temp))
            warm, helpers = self.integration_helpers(
                tool, fixture, (fixture.authorization, []))
            warm.authorize.side_effect = [
                (fixture.authorization, []),
                (None, ['warm_qualification_a_evidence'])]
            with patch.object(tool, 'helper', side_effect=helpers), \
                 patch.object(tool, 'host_snapshot', return_value=fixture.capture_host), \
                 patch.object(tool, 'active_launch_units', return_value=[]), \
                 patch.object(tool, 'current_identity', return_value=fixture.identity), \
                 patch.object(tool, 'replace_json') as replace:
                with self.assertRaisesRegex(ValueError, 'warm qualification'):
                    tool.reserve_warm_qualification(
                        fixture.used, 'boot-A', fixture.manifest['run_id'],
                        fixture.receipt, fixture.manifest, fixture.manifest_path,
                        fixture.output, fixture.authorization)
            warm.build_reservation.assert_not_called()
            replace.assert_not_called()


if __name__ == '__main__':
    unittest.main()
