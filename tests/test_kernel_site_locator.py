import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class KernelSiteLocatorTests(unittest.TestCase):
    def test_relocation_layout_ambiguity_bounds_and_noncode_refusal(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / 'locator'
            subprocess.run(['c++', '-std=c++14', '-Wall', '-Wextra', '-Werror',
                            '-I', str(ROOT / 'src'), str(ROOT / 'tests/kernel_site_locator.cpp'),
                            '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)

    def test_catalog_covers_every_direct_image_address_and_installer_guards(self):
        import re
        source = (ROOT / 'src/RaphaelGPU.cpp').read_text()
        entries = json.loads((ROOT / 'findings/research/update-portability-20261013/kernel-sites.json').read_text())
        keys = {entry['reference'] for entry in entries}
        constants = dict(re.findall(r'static constexpr size_t (kOff\w+)\s*=\s*(0x[0-9a-f]+)', source))
        for reference in re.findall(r'imageAddress\([^,]+,\s*(0x[0-9a-f]+|kOff\w+)\)', source):
            self.assertIn(int(constants.get(reference, reference), 16), keys)
        for reference in re.findall(r'entryMatches\(addr,\s*(?:sz|size),\s*(0x[0-9a-f]+)', source):
            self.assertIn(int(reference, 16), keys)
        for owner in ('HWLibs', 'FB', 'X6000'):
            branch = source.index('if (kexts[Kext'+owner+'].loadIndex == index) {')
            self.assertIn('discoverImageSites(patcher, Kext'+owner, source[branch:branch+220])
        self.assertNotRegex(source, r'\b(?:hwlibsBase|x6Base|dcnFbBase)\s*\+')

    def test_host_discovery_refuses_changed_named_abi_and_duplicate_anonymous_code(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('kernel_sites', ROOT/'tools/kernel-sites.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        site = dict(symbol='method', symbol_delta=0, target_delta=0,
                    bytes='554889e5488b8731050000', mask='ff'*11, section='__text')
        code = bytes.fromhex(site['bytes'])
        image = bytearray(128)
        image[20:31] = code
        sections = {'__text': (16, 80), '__const': (96, 32)}
        self.assertEqual(module.discover(image, sections, {'method': 20}, site), 20)
        image[64:75] = code
        image[27] = 0x32
        # A still-named method with changed object offsets must not redirect to
        # the unrelated matching function elsewhere in the image.
        self.assertIsNone(module.discover(image, sections, {'method': 20}, site))
        self.assertEqual(module.discover(image, sections, {}, site), 64)
        image[20:31] = code
        self.assertIsNone(module.discover(image, sections, {}, site))
        image[20:31] = b'\0'*11
        image[64:75] = b'\0'*11
        image[100:111] = code
        self.assertIsNone(module.discover(image, sections, {}, site))

    def test_compiled_catalog_matches_reviewed_contracts(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('kernel_sites', ROOT/'tools/kernel-sites.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual((ROOT/'src/KernelSiteCatalog.hpp').read_text(), module.generate_header())

    def test_moved_interior_sites_stay_in_owner_and_require_unique_code(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('kernel_sites', ROOT/'tools/kernel-sites.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        site = dict(symbol='method', symbol_delta=4, target_delta=2,
                    bytes='488b8731050000', mask='ff'*7, section='__text',
                    scope_end_symbol='nextMethod')
        image = bytearray(128)
        image[40:47] = bytes.fromhex(site['bytes'])
        sections = {'__text': (16, 96)}
        symbols = {'method': 20, 'nextMethod': 64}
        self.assertEqual(module.discover(image, sections, symbols, site), 42)
        image[48:55] = bytes.fromhex(site['bytes'])
        self.assertIsNone(module.discover(image, sections, symbols, site))
        image[40:55] = bytes(15)
        image[80:87] = bytes.fromhex(site['bytes'])
        self.assertIsNone(module.discover(image, sections, symbols, site))
        image[40:47] = bytes.fromhex(site['bytes'])
        # A newly inserted function must not silently widen the owning scope.
        self.assertIsNone(module.discover(image, sections, dict(symbols, insertedMethod=32), site))
        self.assertIsNone(module.discover(image, sections, {'method':20}, site))

    def test_equivalent_families_preserve_field_checks_and_refuse_ambiguous_addresses(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('kernel_sites', ROOT/'tools/kernel-sites.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        site = dict(symbol='method', symbol_delta=0, target_delta=0,
                    bytes='807f4000', mask='ff'*4, section='__text',
                    alternatives=[dict(bytes='f6474001', mask='ff'*4)])
        image = bytearray(128)
        image[20:24] = bytes.fromhex('f6474001')
        sections = {'__text': (16, 96)}
        self.assertEqual(module.discover(image, sections, {'method':20}, site),20)
        image[22] = 0x41  # Native object offset remains exact in both families.
        self.assertIsNone(module.discover(image, sections, {'method':20}, site))
        image[20:24] = bytes.fromhex('f6474001')
        image[64:68] = bytes.fromhex('807f4000')
        self.assertIsNone(module.discover(image, sections, {}, site))
