import copy
import importlib.util
from pathlib import Path
import unittest
from tests import test_vfio_recover as legacy_tests

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), ROOT/'tools'/(name+'.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class IhRecoveryTests(unittest.TestCase):
    def test_ih_shutdown_precedes_legacy_recovery_and_has_final_proof(self):
        tool = load('ih-vfio-recover')
        tool.R.EXPECTED_CONFIG_MEMSIZE = 0x200
        fake = legacy_tests.FakeTransport(tool.R)
        control = (tool.IH.BASE + 0x80)*4
        fake.registers[control] = 0x1033011f
        state = legacy_tests.VfioRecoveryTests().state
        receipt = tool.perform_recovery('boot-A', 'a'*32, state, lambda: fake,
            lambda cursor=None: ('cursor-2', [], []), sleep=lambda _: None)
        self.assertEqual(receipt['schema'], 10)
        self.assertTrue(receipt['authorizes_launch'])
        self.assertEqual(tool.IH.validate(receipt['ih_dma']['shutdown']), [])
        self.assertEqual(tool.IH.validate(receipt['ih_dma']['final']), [])
        ih_stop = fake.events.index(('write', control, 0x1031001e))
        psp_stop = fake.events.index(('write', tool.R.C2PMSG_64_OFFSET, tool.R.DESTROY_RINGS))
        self.assertLess(ih_stop, psp_stop)
        legacy = lambda value, *_: [] if value['schema'] == 6 else ['legacy_schema']
        self.assertEqual(tool.validate_receipt(receipt, 'boot-A', 'a'*32, legacy, None), [])
        bad = copy.deepcopy(receipt)
        del bad['ih_dma']['final']
        self.assertTrue(tool.validate_receipt(bad, 'boot-A', 'a'*32, legacy, None))
        bad = copy.deepcopy(receipt)
        bad['ih_helpers_sha256']['ih_dma'] = '0'*64
        self.assertEqual(tool.validate_receipt(bad, 'boot-A', 'a'*32, legacy, None), ['ih_recovery_identity'])

    def test_stale_sources_fail_before_host_access(self):
        tool = load('ih-vfio-recover')
        with self.assertRaisesRegex(tool.R.RecoveryError, 'helpers differ'):
            tool.recover(Path('/not-opened'), 'a'*32, ih_helpers_sha256={})

    def test_legacy_receipt_cannot_admit_repaired_manifest(self):
        experiment = load('experiment')
        for schema in (4, 6, 7, 8):
            self.assertEqual(experiment.validate_reuse_receipt({'schema': schema}, 'boot', 'a'*32,
                manifest={'ih_recovery_helpers_sha256': {}}), ['ih_recovery_required'])


if __name__ == '__main__':
    unittest.main()
