import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('writeback_quiesce', ROOT / 'tools/writeback-quiesce.py')
Q = importlib.util.module_from_spec(spec)
spec.loader.exec_module(Q)


class WritebackQuiesceTests(unittest.TestCase):
    def regs(self, **values):
        bank = {}
        for name, value in values.items():
            bank[getattr(Q, name) * 4] = value
        return bank, (lambda off: bank.get(off, 0)), (lambda off, v: bank.__setitem__(off, v))

    def test_armed_writeback_and_our_window_are_closed(self):
        bank, rd, wr = self.regs(FC_MODE_CTRL=0x101, MCIF_SW_CONTROL=0x1000001,
                                 DWB_ENABLE_CLK_CTRL=0x111, MPC_DWB0_MUX=0xf0,
                                 MM_FB_TOP=0xf47f, MM_AGP_BOT=0xf480, MM_AGP_TOP=0xf490,
                                 MM_AGP_BASE=0x4000, MM_SYS_HIGH=0x3d243f,
                                 DCN_AGP_BOT=0xf480, DCN_AGP_TOP=0xf490, DCN_AGP_BASE=0x4000)
        r = Q.quiesce(rd, wr)
        self.assertTrue(r['quiet'])
        self.assertEqual(bank[Q.FC_MODE_CTRL * 4], 0x100)
        self.assertEqual(bank[Q.MCIF_SW_CONTROL * 4], 0x1000000)
        self.assertEqual(bank[Q.DWB_ENABLE_CLK_CTRL * 4], 0x110)
        self.assertEqual(bank[Q.MPC_DWB0_MUX * 4] & 0xf, 0xf)
        self.assertEqual((bank[Q.MM_AGP_BOT * 4], bank[Q.MM_AGP_TOP * 4], bank[Q.MM_AGP_BASE * 4]),
                         (0xffffff, 0, 0))
        self.assertEqual(bank[Q.MM_SYS_HIGH * 4], 0x3d1fff)
        self.assertEqual(bank[Q.DCN_AGP_BASE * 4], 0)

    def test_sdma_queue_and_gc_window_are_closed(self):
        bank, rd, wr = self.regs(MPC_DWB0_MUX=0xf, SDMA0_RLC0_RB_CNTL=0x841015, SDMA0_RLC0_IB_CNTL=1,
                                 GC_AGP_BASE=0x4000, GC_AGP_BOT=0xf480, GC_AGP_TOP=0xf490,
                                 GC_FB_TOP=0xf47f, GC_SYS_HIGH=0x3d243f)
        r = Q.quiesce(rd, wr)
        self.assertTrue(r['quiet'])
        self.assertEqual(bank[Q.SDMA0_RLC0_RB_CNTL * 4], 0x841014)
        self.assertEqual(bank[Q.SDMA0_RLC0_IB_CNTL * 4], 0)
        self.assertEqual((bank[Q.GC_AGP_BASE * 4], bank[Q.GC_AGP_BOT * 4]), (0, 0xffffff))
        self.assertEqual(bank[Q.GC_SYS_HIGH * 4], 0x3d1fff)

    def test_foreign_aperture_is_left_alone(self):
        bank, rd, wr = self.regs(MPC_DWB0_MUX=0xf, MM_FB_TOP=0xf47f, MM_AGP_BOT=0xf500,
                                 MM_AGP_TOP=0xf5ff, MM_AGP_BASE=0x0, MM_SYS_HIGH=0x3d7fff)
        r = Q.quiesce(rd, wr)
        self.assertTrue(r['quiet'])
        self.assertEqual(r['actions'], [])
        self.assertEqual(bank[Q.MM_AGP_BOT * 4], 0xf500)
        self.assertEqual(bank[Q.MM_SYS_HIGH * 4], 0x3d7fff)

    def test_unreadable_device_writes_nothing(self):
        bank, rd, wr = self.regs(FC_MODE_CTRL=0xffffffff, MPC_DWB0_MUX=0)
        before = dict(bank)
        r = Q.quiesce(rd, wr)
        self.assertNotIn('quiet', r)
        self.assertEqual(bank, before)


if __name__ == '__main__':
    unittest.main()
