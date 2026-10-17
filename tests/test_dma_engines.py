import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('dma_engines', Path(__file__).resolve().parents[1]/'tools/dma_engines.py')
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)


class Bus:
    def __init__(self):
        self.values = {offset: 0x40000001 for _, offset, _, _ in E.CONTROLS}
        self.values.update({offset: 0 for _, offset in E.STATUS})
        self.values[dict(E.STATUS)['sdma']] = 1
        self.writes = []
        self.ignored = None

    def read32(self, offset):
        return self.values[offset]

    def write32(self, offset, value):
        self.writes.append((offset, value))
        if offset != self.ignored:
            self.values[offset] = value


class EngineStopTests(unittest.TestCase):
    def exercise(self, bus):
        clock = [1.0]
        def sleep(seconds): clock[0] += seconds
        return E.quiesce(bus, sleep=sleep, monotonic=lambda: clock[0])

    def test_source_backed_halts_preserve_other_bits_and_prove_idle(self):
        bus = Bus()
        before = dict(bus.values)
        proof = self.exercise(bus)
        self.assertEqual(E.validate(proof), [])
        self.assertLessEqual({offset for offset, _ in bus.writes}, {offset for _, offset, _, _ in E.CONTROLS})
        for _, offset, clear, set_mask in E.CONTROLS:
            self.assertEqual(bus.values[offset], (before[offset] & ~clear) | set_mask)
        for field in ('me', 'mec', 'sdma_f32', 'sdma_gfx_rb'):
            tampered = copy.deepcopy(proof)
            tampered['samples'][-1]['values'][field] ^= 1 if field.startswith('sdma') else 0x10000000
            self.assertTrue(E.validate(tampered), field)
        for time_value in (float('nan'), float('inf'), 0):
            tampered = copy.deepcopy(proof)
            tampered['samples'][-1]['monotonic'] = time_value
            self.assertTrue(E.validate(tampered))

    def test_each_busy_engine_or_inaccessible_register_refuses_release(self):
        for label, value in (('cp', 1), ('cpc', 1), ('grbm', 0x80000000), ('sdma', 0), ('sdma', 0xffffffff)):
            bus = Bus()
            bus.values[dict(E.STATUS)[label]] = value
            with self.subTest(label=label, value=value), self.assertRaises(ValueError):
                self.exercise(bus)

    def test_failed_halt_readback_refuses_release(self):
        bus = Bus()
        bus.ignored = dict((n, o) for n, o, _, _ in E.CONTROLS)['me']
        with self.assertRaisesRegex(ValueError, 'readback mismatch'):
            self.exercise(bus)


if __name__ == '__main__':
    unittest.main()
