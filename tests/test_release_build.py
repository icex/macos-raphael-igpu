"""A release must contain a real compiled kext, never a stale prebuilt fallback."""
import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock

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

    def test_rejects_unsupported_thread_local_sections_and_tlv_bootstrap(self):
        spec = importlib.util.spec_from_file_location('release_build', TOOL)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        header = struct.pack('<8I', 0xfeedfacf, 0x1000007, 3, 11, 1, 152, 0, 0)
        segment = struct.pack('<II16sQQQQiiII', 0x19, 152, b'__DATA', 0, 0, 0, 0,
                              7, 3, 1, 0)
        section = struct.pack('<16s16sQQIIIIIIII', b'__thread_vars', b'__DATA', 0, 0,
                              0, 0, 0, 0, 0, 0, 0, 0)
        with self.assertRaisesRegex(ValueError, 'unsupported thread-local'):
            module.validate_macho(header + segment + section)
        with self.assertRaisesRegex(ValueError, 'unsupported TLV bootstrap'):
            module.validate_macho(header.replace(struct.pack('<I', 152), struct.pack('<I', 18)) +
                                  struct.pack('<18s', b'__tlv_bootstrap'))

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

    def test_private_debug_script_adds_only_requested_debug_flags(self):
        spec = importlib.util.spec_from_file_location('release_build', TOOL)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        original = b'FLAGS=(-target x86_64-apple-macos10.15 -mkernel -O2\n  -fno-c++-static-destructors)\n'
        patched = module.debug_build_script(original)
        self.assertIn(b'-mkernel -O2 -g -gdwarf-4\n', patched)
        self.assertEqual(patched.count(b'-g'), 2)  # -g and -gdwarf-4
        self.assertNotEqual(module.sha256(original), module.sha256(patched))
        with self.assertRaisesRegex(ValueError, 'exactly once'):
            module.debug_build_script(original.replace(b'-mkernel -O2\n', b'-mkernel -O0\n'))

    def test_debug_identity_requires_matching_executable_and_dsym_uuid(self):
        spec = importlib.util.spec_from_file_location('release_build', TOOL)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        responses = ['UUID: AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE (x86_64) file',
                     'UUID: AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE (x86_64) dsym']
        with mock.patch.object(module.subprocess, 'check_output', side_effect=responses):
            self.assertEqual(module.verify_debug_uuids(Path('/x'), Path('/d')),
                             'AAAAAAAABBBBCCCCDDDDEEEEEEEEEEEE'.lower())
        with mock.patch.object(module.subprocess, 'check_output', side_effect=[responses[0],
                'UUID: 11111111-2222-3333-4444-555555555555 (x86_64) dsym']):
            with self.assertRaisesRegex(ValueError, 'UUID mismatch'):
                module.verify_debug_uuids(Path('/x'), Path('/d'))
