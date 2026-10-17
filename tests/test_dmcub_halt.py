import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('dmcub_halt', ROOT / 'tools/dmcub-halt.py')
H = importlib.util.module_from_spec(spec)
spec.loader.exec_module(H)


class FakeDmcub:
    """Running host firmware: answers STOP_FW, its timer runs until reset."""
    def __init__(self, responsive=True, cntl=0x190000):
        self.r = {H.CNTL: cntl, H.CNTL2: 0, H.SCRATCH0: 0x43, H.SCRATCH1: 0x05003500,
                  H.MMHUBBUB_SOFT_RESET: 0, H.TIMER_CURRENT: 1000}
        for i, reg in enumerate(H.CW_REGS + H.REGION_REGS):
            self.r[reg] = 0x1000 + i
        self.responsive = responsive

    def read(self, reg):
        if reg == H.TIMER_CURRENT and not (self.r[H.CNTL2] & 1):
            self.r[reg] += 7
        return self.r.get(reg, 0)

    def write(self, reg, value):
        self.r[reg] = value & 0xffffffff
        if reg == H.GPINT_DATAIN1 and value == H.STOP_FW and self.responsive:
            self.r[H.GPINT_DATAIN1] = H.STOP_FW_ACKED
            self.r[H.SCRATCH7] = H.STOP_FW_RESPONSE
            self.r[H.CNTL] |= H.PWAIT
        if reg == H.CNTL2 and value & 1:
            self.r[H.CNTL] &= ~H.PWAIT  # held in reset: no longer waiting


class DmcubHaltTests(unittest.TestCase):
    def test_running_firmware_reaches_the_cold_path_empty_state(self):
        f = FakeDmcub()
        r = H.halt(f.read, f.write, lambda s: None)
        self.assertEqual(r['kind'], 'running')
        self.assertTrue(r['empty_after'], r)
        self.assertTrue(r['steps'][0]['stop_fw_acked'] and r['steps'][0]['stop_fw_response'])
        self.assertEqual(f.r[H.CNTL2] & 1, 1)
        self.assertFalse(f.r[H.CNTL] & H.ENABLE)
        self.assertEqual(f.r[H.MMHUBBUB_SOFT_RESET] & H.DMUIF_RESET, H.DMUIF_RESET)
        self.assertEqual(f.r[H.GPINT_DATAIN1], 0)
        self.assertTrue(H.empty(f.read))

    def test_unresponsive_firmware_is_still_forced_into_reset(self):
        f = FakeDmcub(responsive=False)
        r = H.halt(f.read, f.write, lambda s: None, polls=3)
        self.assertFalse(r['steps'][0]['stop_fw_acked'])
        self.assertTrue(r['empty_after'])

    def test_already_empty_writes_nothing(self):
        f = FakeDmcub()
        f.r.update({H.CNTL: 0x90000, H.CNTL2: 1, H.SCRATCH0: 0, H.SCRATCH1: 0})
        for reg in H.CW_REGS + H.REGION_REGS:
            f.r[reg] = 0
        before = dict(f.r)
        r = H.halt(f.read, f.write, lambda s: None)
        self.assertEqual(r['kind'], 'empty')
        self.assertTrue(r['empty_after'])
        self.assertEqual({k: v for k, v in f.r.items() if k != H.TIMER_CURRENT},
                         {k: v for k, v in before.items() if k != H.TIMER_CURRENT})

    def test_unreadable_or_unknown_state_is_refused(self):
        f = FakeDmcub()
        f.r[H.CNTL] = 0xffffffff
        r = H.halt(f.read, f.write, lambda s: None)
        self.assertEqual(r['kind'], 'unreadable')
        self.assertFalse(r['empty_after'])
        g = FakeDmcub(cntl=0x80000)  # not in reset and not enabled
        r = H.halt(g.read, g.write, lambda s: None)
        self.assertEqual(r['kind'], 'unknown')
        self.assertFalse(r['empty_after'])

    def test_platform_firmware_with_locked_windows_is_held_not_emptied(self):
        # Fresh boot: the UEFI boot display loaded DMCUB through the PSP, which locks its
        # window registers. The halt holds the CPU in reset; the windows keep their values.
        class Locked(FakeDmcub):
            def write(self, reg, value):
                if reg in H.CW_REGS:
                    return
                super().write(reg, value)
        f = Locked(cntl=0x1900c6)
        r = H.halt(f.read, f.write, lambda s: None)
        self.assertFalse(r['empty_after'])
        self.assertTrue(r['held_after'], r)
        self.assertNotIn('error', r)
        self.assertEqual(f.r[H.CNTL] & ~H.PWAIT, 0x800c6)
        self.assertTrue(any(f.r[reg] for reg in H.CW_REGS))

    def test_held_state_requires_the_cpu_to_stay_in_reset(self):
        class Stubborn(FakeDmcub):
            def write(self, reg, value):
                if reg in H.CW_REGS or reg == H.CNTL2:
                    return
                super().write(reg, value)
        f = Stubborn(cntl=0x1900c6)
        r = H.halt(f.read, f.write, lambda s: None)
        self.assertFalse(r['empty_after'] or r.get('held_after'))
        self.assertIn('error', r)

    def test_unexpected_control_value_fails_the_contract(self):
        f = FakeDmcub(cntl=0x1d0000)  # extra bit the guest cold path does not accept
        r = H.halt(f.read, f.write, lambda s: None)
        self.assertFalse(r['empty_after'])
        self.assertIn('error', r)


if __name__ == '__main__':
    unittest.main()


class ResetToolArgsTests(unittest.TestCase):
    def test_reset_admits_empty_and_the_linux_image_only(self):
        # Fresh boots carry the image amdgpu loaded (0x05003500); the guest takes it over.
        f = FakeDmcub()
        kind, state = H.classify(f.read, lambda s: None)
        receipt, error = H.admit(kind, state)
        self.assertIsNone(error)
        self.assertEqual((receipt['kind'], receipt['state'], receipt['action']),
                         ('linux-image', 'running', 'none'))
        f.r[H.CNTL2] = 1; f.r[H.CNTL] = 0x800c6; f.r[H.SCRATCH0] = 0
        self.assertIsNone(H.admit(*H.classify(f.read, lambda s: None))[1])
        self.assertIsNone(H.admit('empty', {'SCRATCH1': 0})[1])

    def test_reset_refuses_the_platform_image(self):
        # 481 launched over the platform's own image (amdgpu.virtual_display boot) and the
        # host froze at guest power-up; a halted image has lost its version too.
        for kind, version in (('running', 0x05000549), ('held-loaded', 0x05000549),
                              ('held-loaded', 0), ('unknown', 0x05003500),
                              ('unreadable', 0xffffffff)):
            receipt, error = H.admit(kind, {'SCRATCH1': version})
            self.assertIn('reset refused', error, (kind, version))
            self.assertIn('amdgpu.virtual_display', error)

    def test_reset_tool_never_halts_or_writes_dmcub(self):
        source = (ROOT / 'tools/smu-mode2-reset.py').read_text()
        block = source[source.index("halt_running_dmcub', False):"):source.index("config_before = cfg.read(0, 256)")]
        self.assertIn("D.admit(kind, state)", block)
        self.assertNotIn("D.halt(", block)
        self.assertNotIn("_store_mmio_u32", block)

    def test_callers_without_the_new_flag_are_accepted(self):
        # mode2-noqueue-recover passes a SimpleNamespace built before the flag existed.
        source = (ROOT / 'tools/smu-mode2-reset.py').read_text()
        self.assertIn("getattr(args, 'halt_running_dmcub', False)", source)
        self.assertNotIn('if args.halt_running_dmcub', source)
