import json
import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest

from tests import test_classify_run as classify_tests


ROOT = Path(__file__).resolve().parents[1]
FROZEN_193_SHA256 = 'd8b7f2eb5ca1d1a0d1a5b9130aad440200068f6629169854b2d5526d4aa49130'


class EntryUpdateProductionIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.fixture = Path(cls.temporary.name) / 'entry-update-formatter'
        subprocess.run([
            'clang++', '-std=c++17', '-I', str(ROOT),
            str(ROOT / 'tests/entry_update_formatter_fixture.cpp'),
            '-o', str(cls.fixture),
        ], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def emitted_summary(self, mode):
        payload = subprocess.check_output(
            [str(self.fixture), str(mode)], text=True).strip()
        classifier = classify_tests.ClassifyTests().classifier()
        rows = [row for row in classifier.parse_serial(
            'RGPU_RECORDS build=abc count=1 dropped=0 truncated=0\n'
            f'RGPU_EVENT build=abc seq=0 {payload}\n')
                if row['kind'] == 'vm_entry_update']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['kind'], 'vm_entry_update')
        rows[0]['seq'] = 9
        return classifier, rows[0]

    def readiness(self, selected_mode, emitted_mode):
        classifier, summary = self.emitted_summary(emitted_mode)
        manifest = {'build_id': 'abc', 'spec': {'required_observations': [
            'vmid2_entry_gate', 'vmid2_entry_update',
            *(['map_process_root'] if selected_mode == 5 else []),
        ]}}
        base = classify_tests.ClassifyTests().events(available=1, status=0, started=1) + [
            dict(kind='accelerator_start', build='abc', seq=6, result=1),
            dict(kind='vm_entry_gate', build='abc', seq=7, marked=True,
                 aperture=True, mode=selected_mode),
            dict(kind='vm_entry_update_route', build='abc', seq=8, ok=True,
                 entry=True, original=0x559dc),
            dict(kind='fb_aperture', build='abc', ok=True,
                 mc_base=0xf400000000, physical_base=0x840000000,
                 aperture_size=0x20000000),
        ]
        if selected_mode == 5:
            base.append(dict(kind='vm_map_process_route', build='abc', seq=8,
                             ok=True, entry=True, original=0x8edce))
        child = dict(kind='vm_entry_update_sample', build='abc', seq=10,
                     bucket='child', caller=0x55a72, producer='child',
                     domain='converted', destination=0x84b6f3000, count=1,
                     source=0xf40b6f4000, result=0x84b6f4000,
                     template=0x2000000000000001, increment=0,
                     constructed=0x200000084b6f4001, state='returned', ok=True)
        control = dict(kind='vm_entry_update_sample', build='abc', seq=11,
                       bucket='control', caller=0x559dc, producer='leaf',
                       domain='physical', destination=0x84b6f3008, count=1,
                       source=0x84b6f5000, result=0x84b6f5000, template=1,
                       increment=0x1000, constructed=0x84b6f5001,
                       state='returned', ok=True)
        events = base + [summary, child, control]
        for sequence, row in enumerate(events):
            row['seq'] = sequence
        return classifier.classify_probe_readiness(manifest, events)

    def test_modes_four_and_five_reach_probe_readiness(self):
        for mode in (4, 5):
            with self.subTest(mode=mode):
                result = self.readiness(mode, mode)
                self.assertEqual(result['verdict'], 'PROBE_NOT_RUN')
                self.assertTrue(result['valid'])

    def test_candidate193_mode_five_gate_mode_four_summary_is_rejected(self):
        result = self.readiness(5, 4)
        self.assertEqual(result['verdict'], 'INVALID')
        self.assertEqual(result['earliest_failure'], 'vmid2_entry_update_state')

    def test_frozen_candidate193_complete_prefix_reproduces_mode_mismatch(self):
        run = Path.home() / 'macos-vm/run/metal-027-193'
        if not run.is_dir():
            self.skipTest('frozen candidate-193 evidence is unavailable')
        manifest = json.loads((run / 'manifest.json').read_text())
        critical = (run / 'critical.txt').read_bytes()
        self.assertEqual(hashlib.sha256(critical).hexdigest(), FROZEN_193_SHA256)
        lines = critical.decode(errors='replace').splitlines(True)
        end = next(index for index, line in enumerate(lines)
                   if 'RGPU_END2' in line and ' s=00000004 ' in line)
        classifier = classify_tests.ClassifyTests().classifier()
        events = classifier.parse_serial(
            ''.join(lines[:end + 1]), critical_replay_schema=2,
            expected_build=manifest['build_id'],
            critical_replay_tolerance='terminal-prefix')
        # The VMID2 aperture (512 MiB on this frozen candidate) is not part of
        # the CR2 protocol; it comes from the plain serial console the same way
        # the real classify-run.py pipeline reads it (parse_manifest_files).
        events += classifier.parse_console_lifecycle(
            (run / 'serial.txt').read_text(errors='replace'), manifest['build_id'])
        result = classifier.classify_probe_readiness(manifest, events)
        self.assertEqual(result['verdict'], 'INVALID')
        self.assertEqual(result['earliest_failure'], 'vmid2_entry_update_state')

        repaired_events = []
        count_keys = classifier.ENTRY_UPDATE_COUNT_KEYS
        omission_keys = classifier.ENTRY_UPDATE_OMISSION_KEYS
        for row in events:
            if row['kind'] != 'vm_entry_update':
                repaired_events.append(row)
                continue
            arguments = [str(self.fixture), '5', str(int(row['route'])),
                         str(row['inactive']),
                         *(str(row['counts'][key]) for key in count_keys),
                         *(str(row['omitted'][key]) for key in omission_keys)]
            payload = subprocess.check_output(arguments, text=True).strip()
            parsed = classifier.parse_serial(
                f'RGPU_RECORDS build={manifest["build_id"]} count=1 dropped=0 truncated=0\n'
                f'RGPU_EVENT build={manifest["build_id"]} seq=0 {payload}\n')
            emitted = next(item for item in parsed if item['kind'] == 'vm_entry_update')
            emitted['seq'] = row['seq']
            repaired_events.append(emitted)
        repaired = classifier.classify_probe_readiness(manifest, repaired_events)
        self.assertEqual(repaired['verdict'], 'PROBE_NOT_RUN')
        self.assertTrue(repaired['valid'])

    def test_driver_publisher_uses_the_production_formatter(self):
        source = (ROOT / 'src/RaphaelGPU.cpp').read_text()
        body = source.split('static void publishPendingVmEntryUpdates()', 1)[1]
        body = body.split('\n}', 1)[0]
        self.assertIn('CRLOG(RGPU_VM_ENTRY_UPDATE_SUMMARY_FORMAT, vmRootFixMode,', body)
        self.assertNotIn('entry-update mode=4', body)


if __name__ == '__main__':
    unittest.main()
