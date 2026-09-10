"""Focused contract tests for the offline Lilu cross-builder."""
import importlib.util
from pathlib import Path
import plistlib
import struct
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools/build-headless-lilu.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("build_headless_lilu", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HeadlessLiluBuildTests(unittest.TestCase):
    def test_requires_all_three_explicit_paths(self):
        result = subprocess.run([sys.executable, str(TOOL)], text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(result.returncode, 2)
        self.assertIn("--prepared-source", result.stderr)
        self.assertIn("--toolchain", result.stderr)
        self.assertIn("--output", result.stderr)

    def test_refuses_output_that_exists_or_overlaps_an_input(self):
        module = load_tool()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "prepared"
            toolchain = root / "toolchain"
            source.mkdir()
            toolchain.mkdir()

            existing = root / "existing"
            existing.mkdir()
            with self.assertRaisesRegex(ValueError, "output already exists"):
                module.refuse_unsafe_paths(source, toolchain, existing)
            with self.assertRaisesRegex(ValueError, "overlaps prepared source"):
                module.refuse_unsafe_paths(source, toolchain, source / "out")
            with self.assertRaisesRegex(ValueError, "overlaps toolchain"):
                module.refuse_unsafe_paths(source, toolchain, toolchain / "out")

    def test_refuses_missing_required_inputs(self):
        module = load_tool()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "prepared"
            toolchain = root / "toolchain"
            source.mkdir()
            toolchain.mkdir()
            with self.assertRaisesRegex(ValueError, "missing prepared-source input"):
                module.verify_inputs(source, toolchain)

    def test_materializes_original_bundle_identity(self):
        module = load_tool()
        template = {
            "CFBundleExecutable": "$(EXECUTABLE_NAME)",
            "CFBundleIdentifier": "$(PRODUCT_BUNDLE_IDENTIFIER)",
            "CFBundleName": "$(PRODUCT_NAME)",
            "CFBundleShortVersionString": "$(MODULE_VERSION)",
            "CFBundleVersion": "$(MODULE_VERSION)",
            "IOKitPersonalities": {
                "as.vit9696.Lilu": {
                    "CFBundleIdentifier": "$(PRODUCT_BUNDLE_IDENTIFIER)",
                    "IOClass": "$(PRODUCT_NAME:rfc1034identifier)",
                    "IOMatchCategory": "$(PRODUCT_NAME:rfc1034identifier)",
                }
            },
        }
        info = plistlib.loads(module.materialize_info(plistlib.dumps(template)))
        self.assertEqual(info["CFBundleExecutable"], "Lilu")
        self.assertEqual(info["CFBundleIdentifier"], "as.vit9696.Lilu")
        self.assertEqual(info["CFBundleName"], "Lilu")
        self.assertEqual(info["CFBundleVersion"], "1.6.8")
        self.assertEqual(info["CFBundleShortVersionString"], "1.6.8")
        personality = info["IOKitPersonalities"]["as.vit9696.Lilu"]
        self.assertEqual(personality["CFBundleIdentifier"], "as.vit9696.Lilu")
        self.assertEqual(personality["IOClass"], "Lilu")
        self.assertEqual(personality["IOMatchCategory"], "Lilu")

    def test_accepts_only_x86_64_kext_bundle_macho(self):
        module = load_tool()
        good = struct.pack("<8I", 0xFEEDFACF, 0x1000007, 3, 11, 0, 0, 0, 0)
        module.validate_macho(good)
        for bad in (b"", good[:12], good[:12] + struct.pack("<I", 2) + good[16:],
                    good[:4] + struct.pack("<I", 0x100000C) + good[8:]):
            with self.assertRaises(ValueError):
                module.validate_macho(bad)


if __name__ == "__main__":
    unittest.main()
