"""candidate 504: Apple's GFX10 Metal defaults oversubscribe the GE parameter cache for
Navi2x (GE_PC_ALLOC = OVERSUB_EN | 512 lines); Raphael has 256 lines and deadlocks on
attribute-heavy late-Z draws. The kext clears allowGePcAllocOverSub in every Metal client by
default through the dynamic ge-pc-oversub family; rgpupcoversub=1 keeps Apple's setting."""
from pathlib import Path
import json
import unittest


ROOT = Path(__file__).resolve().parents[1]


class GePcOversubSourceTests(unittest.TestCase):
    def setUp(self):
        self.source = (ROOT / 'src/RaphaelGPU.cpp').read_text()

    def test_default_on_with_opt_out(self):
        self.assertIn('static bool gePcOversubOff = true;', self.source)
        self.assertIn('gePcOversubOff = !(PE_parse_boot_argn("rgpupcoversub", &keepPcOversub, '
                      'sizeof(keepPcOversub)) &&\n                       keepPcOversub == 1);',
                      self.source)

    def test_target_is_dynamic_and_gated_on_its_own(self):
        parser = (ROOT / 'src/TextureDiagParser.hpp').read_text()
        self.assertIn('target.dynamicSite = &ge_pc_oversub;\n'
                      '            target.settingField = "allowGePcAllocOverSub";', parser)
        self.assertIn('{&RaphaelTextureDiag::kGePcOversubTarget, DiagTargetKind::kGePcOversub, '
                      '"ge-pc-oversub"}', self.source)
        self.assertIn('case DiagTargetKind::kGePcOversub:\n        return gePcOversubOff;',
                      self.source)

    def test_success_records_are_budgeted(self):
        self.assertIn('SAMPLED_CRLOG(gePcCowRecordBudget, cowSucceeded, "GEPC: COW', self.source)
        self.assertNotIn('CRLOG("GEPC: image', self.source)

    def test_catalog_rows_wildcard_both_constructor_immediates(self):
        rows = json.loads((ROOT / 'findings/research/update-portability-20261013/'
                                  'userspace-sites.json').read_text())
        by_name = {row['name']: row for row in rows}
        texture, ge_pc = by_name['texture'], by_name['ge-pc-oversub']
        self.assertEqual(texture['bytes'], ge_pc['bytes'])
        self.assertEqual(texture['mask'], ge_pc['mask'])
        mask = bytes.fromhex(ge_pc['mask'])
        for delta in (texture['target_delta'], ge_pc['target_delta']):
            self.assertEqual(mask[delta:delta + 2], b'\xff\xff')          # movabs rax
            self.assertEqual(mask[delta + 2:delta + 10], bytes(8))        # immediate wildcard


if __name__ == '__main__':
    unittest.main()
