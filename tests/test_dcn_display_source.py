"""candidate 285: rgpudcn steers Apple's display core onto DCN 3.02 on Raphael's DCN 3.1.5,
and rgpuvd120 patches CoreDisplay's virtual-display refresh in WindowServer. Assert the
boot arguments, exact route guards and evidence log lines stay wired."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'src/RaphaelGPU.cpp').read_text()


class DcnDisplaySourceTests(unittest.TestCase):
    def test_boot_arguments_are_bounded_and_logged(self):
        self.assertIn('PE_parse_boot_argn("rgpudcn", &dcn, sizeof(dcn)) && dcn <= kDcnAll', SOURCE)
        self.assertIn('PE_parse_boot_argn("rgpudcntrace", &dcnTrace, sizeof(dcnTrace))', SOURCE)
        self.assertIn('PE_parse_boot_argn("rgpuvd120", &vd120, sizeof(vd120)) && vd120 == 1', SOURCE)
        self.assertRegex(SOURCE, r'kDcnTrace = 1, kDcnTranslate = 2, kDcnPool302 = 4, '
                                 r'kDcnDmcubFirmware = 8, kDcnDmubGuard = 16')

    def test_route_offsets_match_24g830(self):
        for name, offset in (('kOffDcnRegWait', '0x110bd7'), ('kOffDcCreate', '0xfea5e'),
                             ('kOffDcHardwareInit', '0xff053'), ('kOffDmcubSetFwEntry', '0x7a38'),
                             ('kOffDmcubLoadFw', '0x78ee')):
            self.assertRegex(SOURCE, rf'static constexpr size_t {name}\s*= {offset};')

    def test_pool_change_only_for_navi_family_and_translation_requires_it(self):
        self.assertIn('if (family == 0x8f && (rev < 60 || rev >= 70)) asic[3] = 60;', SOURCE)
        self.assertIn('return (dcnMode & (kDcnTranslate | kDcnPool302)) == (kDcnTranslate | kDcnPool302);',
                      SOURCE)
        self.assertIn('dcnMode &= ~(kDcnPool302 | kDcnTranslate | kDcnTrace);', SOURCE)

    def test_dal_mailbox_never_reaches_silicon(self):
        body = SOURCE.split('static void wrapDcnRegWrite', 1)[1].split('\n}\n', 1)[0]
        mailbox = body.split('DalMailbox::owns(index)', 1)[1].split('} else {', 1)[0]
        self.assertNotIn('dcnNativeWrite', mailbox)

    def test_evidence_lines(self):
        for line in ('"DCN: dc_create chip=%#x family=%#x pci_rev=%#x hw_internal_rev %u -> %u "',
                     '"DCN: DMUB service never attached; installed an inert dc_dmub_srv so "',
                     '"DMCUB: registered Raphael DMCUB %#x (%zu bytes) for PSP -> %u (entries %u)"',
                     '"VD120: COW pid=%d addr=%#llx p=%d w=%d r=%d v=%d"'):
            self.assertIn(line, SOURCE)


if __name__ == '__main__':
    unittest.main()
