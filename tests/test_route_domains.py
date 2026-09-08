"""Reject valid symbol offsets routed relative to the wrong loaded kext."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class RouteDomainTests(unittest.TestCase):
    def checker(self):
        path = ROOT / 'tools/route-domains.py'
        self.assertTrue(path.exists(), 'route binary ownership check is missing')
        spec = importlib.util.spec_from_file_location('route_domains', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.check

    def test_accepts_existing_driver_and_rejects_wrong_table_base(self):
        check = self.checker()
        source = (ROOT / 'src/RaphaelGPU.cpp').read_text()
        self.assertEqual(check(source), [])
        # Reproduce the actual 1.0.160/161 failure: a valid HWLibs offset in
        # the X6000 route table. Symbol-address verification alone accepts it.
        bad = source.replace('{kOffAccPowerUpHW, &orgAccPowerUpHW,',
                             '{kOffTtlSetDevCap, &orgAccPowerUpHW,', 1)
        errors = check(bad)
        self.assertTrue(any('kOffTtlSetDevCap' in error and 'X6000' in error for error in errors))

    def test_rejects_framebuffer_offset_in_hwlibs_diagnostics(self):
        check = self.checker()
        source = (ROOT / 'src/RaphaelGPU.cpp').read_text()
        bad = source.replace('base + kOffIpcfgGet,', 'base + kOffPpPowerUp,', 1)
        self.assertTrue(any('kOffPpPowerUp' in error for error in check(bad)))
