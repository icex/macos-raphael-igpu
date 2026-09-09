"""A release must contain a real compiled kext, never a stale prebuilt fallback."""
import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest

TOOL = Path(__file__).resolve().parents[1] / 'tools/build-release.py'

class ReleaseBuildTests(unittest.TestCase):
    def test_release_documents_include_authoritative_status(self):
        spec = importlib.util.spec_from_file_location('release_build', TOOL)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertIn('status.md', module.RELEASE_DOCUMENTS)
        for relative in module.RELEASE_DOCUMENTS:
            self.assertTrue((TOOL.parents[1] / relative).is_file(), relative)

    def test_rejects_executable_or_wrong_architecture_as_kext(self):
        self.assertTrue(TOOL.is_file(), 'release builder is missing')
        spec = importlib.util.spec_from_file_location('release_build', TOOL)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        good = struct.pack('<8I', 0xfeedfacf, 0x1000007, 3, 11, 0, 0, 0, 0)
        module.validate_macho(good)
        for bad in (b'', good[:12], good[:12]+struct.pack('<I',2)+good[16:],
                    good[:4]+struct.pack('<I',0x100000c)+good[8:]):
            with self.assertRaises(ValueError): module.validate_macho(bad)

    def test_refuses_changed_sdk_or_lilu_inputs(self):
        spec = importlib.util.spec_from_file_location('release_build', TOOL)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertTrue(hasattr(module, 'verify_toolchain'), 'dependency verification is missing')
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            sdk = root / 'MacKernelSDK-master'
            lilu = root / 'liludbg/Lilu.kext/Contents/Resources'
            sdk.mkdir(); lilu.mkdir(parents=True)
            (sdk / 'header.h').write_text('original SDK')
            (lilu / 'header.h').write_text('original Lilu')
            expected = {'sdk_tree_sha256':module.tree_digest(sdk),
                        'lilu_resources_sha256':module.tree_digest(lilu)}
            module.verify_toolchain(root, expected)
            (sdk / 'header.h').write_text('different SDK')
            with self.assertRaises(ValueError): module.verify_toolchain(root, expected)
            (sdk / 'header.h').write_text('original SDK')
            (lilu / 'header.h').write_text('different Lilu')
            with self.assertRaises(ValueError): module.verify_toolchain(root, expected)
