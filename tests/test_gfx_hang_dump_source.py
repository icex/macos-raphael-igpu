from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class GfxHangDumpSourceTests(unittest.TestCase):
    def setUp(self):
        self.source = (ROOT / 'src/RaphaelGPU.cpp').read_text()

    def body(self, start, end):
        first = self.source.index(start)
        return self.source[first:self.source.index(end, first)]

    def test_boot_argument_defaults_off_and_gates_thread(self):
        self.assertIn('static uint32_t hangDumpMode = 0;', self.source)
        self.assertIn('PE_parse_boot_argn("rgpuhangdump", &hangDump, sizeof(hangDump))',
                      self.source)
        start = self.body('static void pluginStart()', 'static const char *bootargOff[]')
        gate = start.index('if (hangDumpMode == 1) {')
        self.assertLess(gate, start.index('kernel_thread_start(hangDumpThread'))
        observe = self.body('static void observeGfxRingHang', '// rgpuhangdump=1, candidate 213.')
        self.assertLess(observe.index('if (hangDumpMode != 1 || asicInfo == nullptr) return;'),
                        observe.index('fbRead('))

    def test_kiq_observation_triggers_after_selector_restore(self):
        kick = self.body('static void kickKiq()', '#if RGPU_HAVE_MEC_FW')
        restore = kick.rindex('fbWrite(asicInfo, kGcGrbmGfxCntl, 0);')
        self.assertLess(restore, kick.index('observeGfxRingHang("KIQ observation");'))

    def test_hook_side_reads_registers_only(self):
        observe = self.body('static void observeGfxRingHang', '// rgpuhangdump=1, candidate 213.')
        for forbidden in ('fbWrite(', 'IOMemoryDescriptor', 'readHangPage', 'fbAperture('):
            self.assertNotIn(forbidden, observe)
        self.assertIn('RaphaelHang::ringStalled(rptr, wptr, after)', observe)
        worker = self.body('static void hangDumpThread', 'static void reportVmid2Runtime')
        self.assertIn('dumpGfxHangMemory(served, hangSnapshots[served]);', worker)

    def test_memory_reads_are_read_only_and_64_bit(self):
        reader = self.body('static bool readHangPage', 'static constexpr uint32_t kHangMaxDwords')
        self.assertIn('IOMemoryDescriptor::withAddressRange(\n        source.address, 0x1000, '
                      'kIODirectionIn, nullptr);', reader)
        self.assertIn('descriptor->map(kIOMapReadOnly)', reader)
        self.assertNotIn('fbWrite(', reader)
        # This build has no KERNEL define; the SDK's withPhysicalAddress would bind
        # the 32-bit __ZN18IOMemoryDescriptor19withPhysicalAddressEjjj.
        self.assertNotIn('withPhysicalAddress(', self.source.replace(
            'withPhysicalAddress is withAddressRange', ''))
        dump = self.body('static void dumpGfxHangMemory', 'static void hangDumpThread')
        self.assertNotIn('fbWrite(', dump)

    def test_register_offsets_match_linux_gc_10_3(self):
        for text in ('kGcCpMeHeaderDump  = kGcSeg0 + 0x0f41;',
                     'kGcCpPfpHeaderDump = kGcSeg0 + 0x0f42;',
                     'kGcCpCeHeaderDump  = kGcSeg0 + 0x0f44;',
                     'kGcGrbmStatusSe0   = kGcSeg0 + 0x0da5;',
                     'kGcPaScFifoSize    = kGcSeg0 + 0x1093;',
                     '{kGcSeg1 + 0x20cc, kGcSeg1 + 0x20cd, kGcSeg1 + 0x20ce, kGcSeg1 + 0x2092},',
                     '{kGcSeg1 + 0x20cf, kGcSeg1 + 0x20d0, kGcSeg1 + 0x20d1, kGcSeg1 + 0x2093},'):
            self.assertIn(text, self.source)

    def test_pending_command_report_wrapper_is_guarded_and_bounded(self):
        wrapper = self.body('static void wrapPendingCommandReport', '// Observe the native frame')
        self.assertLess(wrapper.index('FunctionCast(wrapPendingCommandReport, orgPendingCommandReport)'),
                        wrapper.index('capturePendingCommandBuffer(cb);'))
        capture = self.body('static void capturePendingCommandBuffer',
                            'static void wrapPendingCommandReport')
        self.assertLess(capture.index('if (hangDumpMode != 1 || cb == nullptr'),
                        capture.index('hangMapCmdBuffers)(cb, 1, &mapped)'))
        self.assertLess(capture.index('hangMapCmdBuffers)(cb, 1, &mapped)'),
                        capture.index('hangUnmapCmdBuffers)(cb, 1, &mapped)'))
        self.assertIn('out.copied = size < kHangCbMaxDwords ? size : kHangCbMaxDwords;', capture)
        self.assertNotIn('fbWrite(', capture)
        self.assertNotIn('RLOG("XB: cb%u [', capture)
        route = self.body('if (hangDumpMode == 1) {\n            // Complete instructions',
                          'RLOG("XB: pending command report route')
        self.assertLess(route.index('entryMatches(addr, sz, kOffPendingCommandReport'),
                        route.index('patcher.routeFunction('))
        for text in ('kOffPendingCommandReport = 0xd950;', 'kOffMapCmdBuffers = 0x4d58e;',
                     'kOffUnmapCmdBuffers = 0x4d608;'):
            self.assertIn(text, self.source)

    @unittest.skipUnless(shutil.which('g++'), 'g++ unavailable')
    def test_arithmetic_unit(self):
        with tempfile.TemporaryDirectory() as temporary:
            binary = Path(temporary) / 'hang-test'
            subprocess.run(['g++', '-std=c++14', '-Wall', '-Wextra', '-Werror',
                            str(ROOT / 'tests/test_gfx_hang_dump.cpp'), '-o', str(binary)],
                           check=True)
            subprocess.run([str(binary)], check=True, capture_output=True)


if __name__ == '__main__':
    unittest.main()
