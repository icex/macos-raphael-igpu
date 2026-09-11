import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / 'tools' / 'small-metal-test.py'


class SmallMetalResultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('small_metal_test', MODULE)
        cls.tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.tool)

    def output(self, **changes):
        result = {
            'run_id': 'fresh-run', 'passed': True,
            'device': 'AMD Radeon Navi23', 'registry_id': 1234,
            'metal3': True, 'completed_command_buffers': 1,
            'values_checked': 1, 'value': 0x12345678,
        }
        result.update(changes)
        return ('RGPU_SMALL_METAL_RESULT ' + json.dumps(result) +
                '\nRGPU_EXIT fresh-run 0\n')

    def test_accepts_one_completed_small_submission(self):
        result = self.tool.validate_output(self.output(), 'fresh-run')
        self.assertTrue(result['passed'])
        self.assertEqual(result['completed_command_buffers'], 1)

    def test_rejects_identity_or_execution_false_positive(self):
        for changes in (
                {'device': 'Apple Software Renderer'},
                {'metal3': False}, {'registry_id': 0},
                {'completed_command_buffers': 0}, {'values_checked': 0},
                {'passed': False},):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    self.tool.validate_output(self.output(**changes), 'fresh-run')

    def test_rejects_stale_nonce_duplicate_or_missing_exit(self):
        with self.assertRaises(ValueError):
            self.tool.validate_output(self.output(), 'other-run')
        with self.assertRaises(ValueError):
            self.tool.validate_output(self.output() * 2, 'fresh-run')
        with self.assertRaises(ValueError):
            self.tool.validate_output(self.output().split('RGPU_EXIT')[0], 'fresh-run')

    def test_probe_source_is_single_small_submission(self):
        source = (ROOT / 'tests' / 'small_metal_probe.m').read_text()
        self.assertEqual(source.count('[command commit]'), 1)
        self.assertIn('MTLSizeMake(1, 1, 1)', source)
        self.assertIn('values_checked', source)
        self.assertNotIn('MTLResourceStorageModeManaged', source)


if __name__ == '__main__':
    unittest.main()
