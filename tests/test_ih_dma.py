import copy
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ih', ROOT/'tools/ih_dma.py')
ih = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ih)


class MMIO:
    def __init__(self):
        self.values = {ih.CNTL2: 0x108}
        for index, (control, pointer, mask) in enumerate(ih.RINGS):
            self.values[(ih.BASE + control)*4] = 0x1033011f if index == 0 else 0x55
            self.values[(ih.BASE + pointer)*4] = index * 32
        self.writes = []

    def read32(self, offset):
        return self.values[offset]

    def write32(self, offset, value):
        self.writes.append((offset, value))
        self.values[offset] = value


class IhDmaTests(unittest.TestCase):
    def test_shutdown_only_clears_documented_enable_bits(self):
        mmio = MMIO()
        before = dict(mmio.values)
        proof = ih.quiesce(mmio)
        self.assertEqual(ih.validate(proof), [])
        allowed = {ih.CNTL2: ih.WPTR_FORCE_ENABLE}
        allowed.update({(ih.BASE + control)*4: mask for control, _, mask in ih.RINGS})
        self.assertEqual(set(offset for offset, _ in mmio.writes), set(allowed))
        for offset, mask in allowed.items():
            self.assertEqual(mmio.values[offset], before[offset] & ~mask)
        self.assertGreaterEqual(proof['samples'][-1]['monotonic'] -
                                proof['samples'][0]['monotonic'], 0.1)

    def test_stale_receipt_enabled_ring_moving_pointer_or_short_window_refused(self):
        proof = ih.quiesce(MMIO())
        for index in range(3):
            bad = copy.deepcopy(proof)
            bad['samples'][2]['rings'][index]['control'] |= 1
            self.assertIn('ih_enabled', ih.validate(bad))
            bad = copy.deepcopy(proof)
            bad['samples'][3]['rings'][index]['wptr'] += 32
            self.assertIn('ih_pointer_moving', ih.validate(bad))
        bad = copy.deepcopy(proof)
        bad['samples'][0]['monotonic'] = float('nan')
        self.assertIn('ih_sample_interval', ih.validate(bad))
        bad = copy.deepcopy(proof)
        bad['samples'][2]['cntl2'] |= ih.WPTR_FORCE_ENABLE
        self.assertIn('ih_force_enabled', ih.validate(bad))
        self.assertTrue(ih.validate({}))
        self.assertTrue(ih.validate({'samples': []}))

    def test_inaccessible_and_failed_writes_refused(self):
        mmio = MMIO()
        mmio.values[(ih.BASE + 0x80)*4] = 0xffffffff
        with self.assertRaises(ValueError):
            ih.quiesce(mmio)
        self.assertEqual(mmio.writes, [])
        mmio = MMIO()
        mmio.write32 = lambda *_: None
        with self.assertRaisesRegex(ValueError, 'readback'):
            ih.quiesce(mmio)


if __name__ == '__main__':
    unittest.main()
