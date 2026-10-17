"""candidate 508: IOGraphicsAccelerator2::start sizes the reusable orphaned-memory pool at
hw.memsize / 4, independent of VRAM, and only prunes above it. On Raphael's UMA carve-out the
cache filled VRAM (3.4 GB orphaned, 16 MB free) and WindowServer allocations failed during window
drags. The kext clamps the limit through the exported IOAccelOrphanedMemoryPool::init symbol."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class OrphanPoolSourceTests(unittest.TestCase):
    def setUp(self):
        self.source = (ROOT / 'src/RaphaelGPU.cpp').read_text()

    def test_resolved_by_exported_symbol_not_offset(self):
        self.assertIn('"__ZN25IOAccelOrphanedMemoryPool4initEP22IOGraphicsAccelerator2yj"',
                      self.source)
        self.assertIn('{"com.apple.iokit.IOAcceleratorFamily2", pathIOAccel, arrsize(pathIOAccel),',
                      self.source)

    def test_default_cap_with_opt_out(self):
        self.assertIn('static uint32_t orphanCapMb = 512;', self.source)
        self.assertIn('PE_parse_boot_argn("rgpuorphanmb", &orphanMb, sizeof(orphanMb))',
                      self.source)
        self.assertIn('if (orphanCapMb != 0) {', self.source)

    def test_only_lowers_a_finite_limit(self):
        self.assertIn('orphanCapMb != 0 && limit != UINT64_MAX && limit > cap ? cap : limit',
                      self.source)
        self.assertIn('discoveredVramTotal / 4 < cap', self.source)


class VidOrphanReleaseSourceTests(unittest.TestCase):
    """candidate 511: the unlimited second pool holds freed VRAM and was never pruned."""
    def setUp(self):
        self.source = (ROOT / 'src/RaphaelGPU.cpp').read_text()

    def test_release_uses_exported_symbols_only(self):
        for symbol in ('__ZN25IOAccelOrphanedMemoryPool21releaseOrphanedMemoryEv',
                       '__ZN25IOAccelOrphanedMemoryPool9addMemoryEP13IOAccelMemory',
                       '__ZN26AMDRadeonX6000_AMDHWMemory19allocateLargeBlocksEP16AMDMemoryElementyyy'
                       '15_eOP_ORIGINATOR9_eOP_TYPEb'):
            self.assertIn(symbol, self.source.replace('"\n                "', ''))

    def test_vram_pool_is_the_unlimited_one_and_release_runs_inside_add(self):
        self.assertIn('if (limit == UINT64_MAX && vidOrphanRelease) vidOrphanPool = pool;', self.source)
        add = self.source[self.source.index('static void wrapOrphanPoolAdd'):]
        add = add[:add.index('\n}\n')]
        # Release first: the allocation being added must never be freed under its caller.
        self.assertLess(add.index('vidOrphanMaybeRelease(pool);'),
                        add.index('FunctionCast(wrapOrphanPoolAdd, orgOrphanPoolAdd)(pool, memory);'))
        release = self.source[self.source.index('static void vidOrphanMaybeRelease'):]
        release = release[:release.index('\n}\n')]
        self.assertIn('if (pool != vidOrphanPool || orphanPoolRelease == nullptr) return;', release)
        self.assertIn('now - vidOrphanLastReleaseNs < 30000000000ull', release)

    def test_default_on_with_opt_out(self):
        self.assertIn('static bool vidOrphanRelease = true;', self.source)
        self.assertIn('PE_parse_boot_argn("rgpuvidorphan", &vidOrphan, sizeof(vidOrphan))', self.source)


if __name__ == '__main__':
    unittest.main()
