"""rgpudcn steers Apple's display core onto DCN 3.02 on Raphael's DCN 3.1.5, and rgpuvd120
patches CoreDisplay's virtual-display refresh in WindowServer. Candidate 285's guest DMCUB
firmware registration froze the host; assert the guest can no longer reach DMCUB."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'src/RaphaelGPU.cpp').read_text()


def function(name):
    return SOURCE.split(name, 1)[1].split('\n}\n', 1)[0]


class DcnDisplaySourceTests(unittest.TestCase):
    def test_boot_arguments_are_bounded_and_logged(self):
        self.assertIn('PE_parse_boot_argn("rgpudcntrace", &dcnTrace, sizeof(dcnTrace))', SOURCE)
        self.assertIn('PE_parse_boot_argn("rgpuvd120", &vd120, sizeof(vd120)) && vd120 == 1', SOURCE)
        self.assertIn('kDcnDmubGuard = 16, kDcnDioWake = 32, kDcnHostI2cSpeed = 64, kDcnDmcubSurvey = 128,\n'
                      '    kDcnDmubHook = 256, kDcnDmubDeliver = 512,\n'
                      '    kDcnAllowed = kDcnTrace | kDcnTranslate | kDcnPool302 | kDcnDmubGuard | kDcnDioWake |\n'
                      '                  kDcnHostI2cSpeed | kDcnDmcubSurvey | kDcnDmubHook | kDcnDmubDeliver,', SOURCE)

    def test_withdrawn_dmcub_firmware_and_unpaired_pool_are_refused(self):
        self.assertIn('(dcn & ~kDcnAllowed) == 0 &&\n'
                      '        ((dcn & kDcnPool302) != 0) == ((dcn & kDcnTranslate) != 0)) dcnMode = dcn;',
                      SOURCE)
        for gone in ('_dmcub_set_fw_entry_info', '_dmcub_load_fw', 'DmcubFirmware.hpp',
                     'raphaelDmcubFirmware', 'kOffDmcubLoadFw'):
            self.assertNotIn(gone, SOURCE.split('// ---- Physical display', 1)[1].split(
                'static uint32_t wrapFbXgmiConfig', 1)[0].replace(
                '// The guest never programs DMCUB.', ''), gone)

    def test_route_offsets_match_24g830(self):
        for name, offset in (('kOffDcnRegWait', '0x110bd7'), ('kOffDcCreate', '0xfea5e'),
                             ('kOffDcHardwareInit', '0xff053')):
            self.assertRegex(SOURCE, rf'static constexpr size_t {name}\s*= {offset};')

    def test_pool_requires_interposition(self):
        body = function('static void *wrapDcCreate(void *init) {')
        interpose = body.index('cgs[8] = reinterpret_cast<uint64_t>(wrapDcnRegRead);')
        clear = body.index('if (dcnNativeRead == nullptr) dcnMode &= ~(kDcnTrace | kDcnTranslate | kDcnPool302);')
        rev = body.index('if (family == 0x8f && (rev < 60 || rev >= 70)) asic[3] = 60;')
        self.assertLess(interpose, clear)
        self.assertLess(clear, rev)
        self.assertIn('if (init != nullptr && dcnTranslating()) {', body)

    def test_dmcub_is_fenced(self):
        write = function('static void wrapDcnRegWrite(void *context, uint32_t index, uint32_t value) {')
        blocked = write.split('if (isDmcubRegister(index)) {', 1)[1].split('} else if', 1)[0]
        self.assertNotIn('dcnNativeWrite', blocked)
        read = function('static uint32_t wrapDcnRegRead(void *context, uint32_t index) {')
        self.assertIn('value = maskDmcubStrap(dcnNativeRead(context, m.index));', read)

    def test_dal_mailbox_never_reaches_silicon(self):
        write = function('static void wrapDcnRegWrite(void *context, uint32_t index, uint32_t value) {')
        mailbox = write.split('DalMailbox::owns(index)', 1)[1].split('} else {', 1)[0]
        self.assertNotIn('dcnNativeWrite', mailbox)

    def test_evidence_lines(self):
        for line in ('"DCN: dc_create chip=%#x family=%#x pci_rev=%#x hw_internal_rev %u -> %u "',
                     '"DCN: DMUB service never attached; installed an inert dc_dmub_srv so "',
                     '"DCN: blocked DMCUB register write %#x = %#x"',
                     '"VD120: COW pid=%d addr=%#llx p=%d w=%d r=%d v=%d"'):
            self.assertIn(line, SOURCE)


    def test_dmcub_survey_is_read_only(self):
        start = SOURCE.index('static void dcnSurveyDmcub(')
        body = SOURCE[start:SOURCE.index('\nstatic void dcnLogDmcubState(', start)]
        self.assertNotIn('dcnNativeWrite', body)
        self.assertNotRegex(body, r'fb\[[^\]]*\]\s*=[^=]')
        self.assertIn('if (!(dcnMode & kDcnDmcubSurvey)', body)


    def test_dmub_delivery_is_gated(self):
        start = SOURCE.index('static void wrapDcDmubQueue(')
        body = SOURCE[start:SOURCE.index('\nstatic void installDcnRoutes(', start)]
        self.assertIn('const bool deliver = type == 128 && !(sub == 3 && (cmd[1] & 0xff) >= 4) && dmubDeliverReady();', body)
        self.assertIn('PE_parse_boot_argn("rgpudallog", &dalLogMask, sizeof(dalLogMask));', SOURCE)
        self.assertIn('(dcnMode & kDcnDmubDeliver) && !dmubDeliverDead', SOURCE)
        # The only DMCUB register the hooks write is INBOX1_WPTR.
        self.assertEqual(body.count('dcnNativeWrite('), 1)
        self.assertIn('dcnNativeWrite(dcnRegContext, 0x3696, dmubWptr);', body)
        self.assertIn('dmubDeliverDead = true;', body)


    def test_agdp_pikera_is_gated_and_exact(self):
        self.assertIn('PE_parse_boot_argn("rgpuagdp", &agdpPikera, sizeof(agdpPikera));', SOURCE)
        self.assertIn('static const uint8_t find[] = "board-id";', SOURCE)
        self.assertIn('static const uint8_t repl[] = "board-ix";', SOURCE)
        self.assertIn('KernelPatcher::LookupPatch lp {&kexts[KextAgdp], find, repl, sizeof(find), 1};', SOURCE)


if __name__ == '__main__':
    unittest.main()
