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

    def test_address_config_route_is_gated_guarded_and_uses_live_register(self):
        self.assertIn('static uint32_t addrConfigMode = 0;', self.source)
        self.assertIn('PE_parse_boot_argn("rgpuaddrcfg", &addrCfg, sizeof(addrCfg)) && addrCfg <= 2', self.source)
        self.assertIn('static constexpr size_t kOffAlignManager2Init = 0x6032a;', self.source)
        self.assertIn('static constexpr size_t kHwInfoGbAddrConfig = 0xa0;', self.source)
        install = self.body('if (addrConfigMode != 0 || hwCapClearMask != 0) {', 'if (swizzleLogMode != 0) {')
        self.assertIn('0x41, 0x56, 0x41, 0x54, 0x53, 0x48, 0x81, 0xec, 0x90, 0x00, 0x00, 0x00', install)
        self.assertIn('entryMatches(addr, sz, kOffAlignManager2Init', install)
        self.assertIn('if (alignMatches) {', install)
        wrapper = self.body('static int wrapAlignManager2Init(', 'static constexpr size_t kOffPendingCommandReport')
        self.assertIn('fbRead(asicInfo, kGcGbAddrConfig)', wrapper)
        self.assertIn('addrConfigMode == 2 && live != 0xdeadbeef && live != 0 && reported != live', wrapper)
        self.assertLess(wrapper.index('memcpy(info + kHwInfoGbAddrConfig'), wrapper.index('org(that, hwInterface)'))

    def test_swizzle_knobs_default_off_and_are_guarded(self):
        for decl in ('static uint32_t swizzleLogMode = 0;', 'static uint32_t hwCapClearMask = 0;',
                     'static uint32_t vgprMode = 0;'):
            self.assertIn(decl, self.source)
        self.assertIn('PE_parse_boot_argn("rgpuswlog", &swLog, sizeof(swLog)) && swLog <= 2', self.source)
        self.assertIn('PE_parse_boot_argn("rgpuvgpr", &vgpr, sizeof(vgpr)) && vgpr <= 3', self.source)
        install = self.body('if (swizzleLogMode != 0) {', 'Exact complete instructions displaced')
        self.assertIn('0x48, 0x83, 0xec, 0x70, 0x49, 0x89, 0xfe, 0x31, 0xdb', install)
        self.assertIn('if (preferredMatches) {', install)
        wrapper = self.body('static uint32_t wrapPreferredSwizzleMode2(', '// rgpuvgpr: sampler-side')
        self.assertIn('swizzleLogMode == 2 ? 0u : preferred', wrapper)
        vgpr = self.body('static void applyVgprSwizzle(', 'static constexpr size_t kOffPendingCommandReport')
        self.assertIn('vgprMode == 1 && lds != 0xdeadbeef', vgpr)
        self.assertIn('vgprMode == 2 && sq != 0xdeadbeef', vgpr)
        start = self.body('static void startRlc() {', 'fbWrite(asicInfo, kGcRlcCgcg, 0);')
        self.assertLess(start.index('applyNoBinning'), start.index('applyVgprSwizzle'))

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
        self.assertIn('sampleGfxProgress(samples++, lastWptr, advances, drained);', worker)
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

    def test_decoder_checksum_matches_kext_vector(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('decoder', ROOT / 'tools/decode-hang-dump.py')
        decoder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(decoder)
        self.assertEqual(decoder.line_checksum(0x10, [0xc0004600, 0x16, 0xc0065800, 0x86287fc3]),
                         0xa1b663ae)
        with tempfile.TemporaryDirectory() as temporary:
            serial = Path(temporary) / 'serial.txt'
            serial.write_text(
                'RaphaelGPU rgpu: @ XB: cb0 p1 [0x0010] c0004600 00000016 c0065800 86287fc3 x=a1b663ae\n'
                'RaphaelGPU rgpu: @ XB: cb0 p2 [0x0010] c0004600 00000016 c0065800 86287fc4 x=a1b663ae\n')
            buffers, rejected = decoder.parse_command_buffers(serial)
        self.assertEqual(rejected, 1)
        self.assertEqual(buffers[0][0x13], 0x86287fc3)

    def test_printing_is_paced_after_capture(self):
        printer = self.body('static void printHangCommandBuffer', 'static void hangDumpThread')
        self.assertLess(printer.index('IOSleep(3000);'), printer.index('RLOG("XB: cb%u p%u'))
        self.assertIn('RaphaelHang::lineChecksum(first, cb.words + first, count)', printer)
        capture = self.body('static void capturePendingCommandBuffer',
                            'static void wrapPendingCommandReport')
        self.assertIn('RLOG("XB: pending CB %u wait %u at=', capture)

    def test_cp_microcode_swap_is_gated_and_type_matched(self):
        self.assertIn('static uint32_t cpFwMode = 0;', self.source)
        init = self.body('static uint32_t wrapPspNpFwInit', 'static uint32_t pspReadCount')
        self.assertLess(init.index('if (cpFwMode == 1 && arr != nullptr)'),
                        init.index('FunctionCast(wrapPspNpFwInit, orgPspNpFwInit)'))
        swap = self.body('static void substituteCpFirmware', 'static mach_vm_address_t orgPspBufPrep')
        self.assertIn('if ((p.fwType & 0xffffu) != (fwType & 0xffffu)) continue;', swap)
        self.assertIn('if (!signedPayload) continue;', swap)
        self.assertIn('if (len != p.size) {', swap)
        for fw_type in ('0x81012001u', '0x81012002u', '0x81012003u'):
            self.assertIn(fw_type, self.source)
        self.assertNotIn('0x81012004u', self.source)

    def test_no_binning_override_is_gated(self):
        self.assertIn('static uint32_t noBinMode = 0;', self.source)
        body = self.body('static void applyNoBinning', 'static void startRlc()')
        self.assertLess(body.index('if (noBinMode != 1 || asicInfo == nullptr) return;'),
                        body.index('fbWrite(asicInfo, kGcPaScEnhance1, before | 0x8u);'))
        self.assertIn('kGcPaScEnhance1 = kGcSeg0 + 0x109d;', self.source)

    def test_late_quiesce_responder_is_gated_and_bounded(self):
        worker = self.body('static void criticalDumpThread', 'static uint32_t mask = 0;')
        late = worker[worker.index('if (criticalUartQuiesceEnabled) {\n        // Candidate 217'):]
        self.assertIn('kLateQuiesceUs = UINT64_C(6000000000);', late)
        self.assertIn('while (late.remainingUs(io.micros()) != 0 && lateReplay < 64) {', late)
        self.assertLess(late.index('uart.pollQuiesceRequest()'), late.index('emitSnapshot('))
        self.assertLess(late.index('criticalSnapshotCaughtUp('), late.index('uart.writeQuiesced('))

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
