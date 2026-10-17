from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class UserspaceSiteLocatorTests(unittest.TestCase):
    def test_generated_families_match_reviewed_catalog(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('user_sites',ROOT/'tools/user-sites.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual((ROOT/'src/UserSiteCatalog.hpp').read_text(),module.generate_header())

    def test_metadata_bit_code_move_chunk_boundary_clear_and_ambiguity(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory)/'userspace-sites'
            subprocess.run(['c++','-std=c++14','-Wall','-Wextra','-Werror',
                            '-I',str(ROOT/'src'),str(ROOT/'tests/userspace_site_locator.cpp'),
                            '-o',str(binary)],check=True)
            subprocess.run([str(binary)],check=True)
