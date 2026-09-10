import importlib.util
import struct
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("gdb_kext_source", ROOT / "tools/gdb-kext-source.py")
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)


class GdbKextSourceTests(unittest.TestCase):
    def test_kernel_relocation_includes_fileset_offset(self):
        self.assertEqual(tool.kernel_relocation(0xffffff801b6e8000,
                                                0xffffff8000200000), 0x1b4e8000)

    def test_uuid_parser_is_bounded_and_fail_closed(self):
        uuid = bytes.fromhex("474ef697fc283ba283a4763d76c8e200")
        header = struct.pack("<IiiIIIII", 0xfeedfacf, 0x1000007, 3, 2, 1, 24, 0, 0)
        load = struct.pack("<II", 0x1b, 24) + uuid
        self.assertEqual(tool.macho_uuid(header + load), uuid.hex())
        with self.assertRaisesRegex(ValueError, "load commands exceed"):
            tool.macho_uuid(header[:20])
        with self.assertRaisesRegex(ValueError, "too large"):
            tool.macho_uuid(struct.pack("<IiiIIIII", 0xfeedfacf, 0x1000007, 3,
                                        2, 1, 65537, 0, 0))

    def test_kmod_walk_authenticates_name_and_uuid(self):
        uuid = bytes.fromhex("474ef697fc283ba283a4763d76c8e200")
        image = struct.pack("<IiiIIIII", 0xfeedfacf, 0x1000007, 3, 2, 1, 24, 0, 0)
        image += struct.pack("<II", 0x1b, 24) + uuid
        node = bytearray(0xac)
        node[0x10:0x10 + len(b"as.test.RaphaelGPU")] = b"as.test.RaphaelGPU"
        struct.pack_into("<Q", node, 0x9c, 0x2000)
        def read(address, size):
            base = 0x1000 if address < 0x2000 else 0x2000
            return memory[base][address-base:address-base+size]
        memory = {0x1000: bytes(node), 0x2000: image}
        found = tool.walk_kmods(read, 0x1000)
        self.assertEqual(found, ("as.test.RaphaelGPU", 0x2000, uuid.hex()))

    def test_kmod_walk_refuses_wrong_uuid_and_cycle(self):
        node = bytearray(0xac)
        node[0x10:0x10 + len(b"RaphaelGPU")] = b"RaphaelGPU"
        struct.pack_into("<Q", node, 0x9c, 0x2000)
        wrong = struct.pack("<IiiIIIII", 0xfeedfacf, 0x1000007, 3, 2, 1, 24, 0, 0)
        wrong += struct.pack("<II", 0x1b, 24) + b"\0" * 16
        def wrong_read(address, size):
            blob, base = (bytes(node), 0x1000) if address < 0x2000 else (wrong, 0x2000)
            return blob[address-base:address-base+size]
        with self.assertRaisesRegex(ValueError, "UUID mismatch"):
            tool.walk_kmods(wrong_read, 0x1000,
                           "474ef697fc283ba283a4763d76c8e200")
        struct.pack_into("<Q", node, 0, 0x1000)
        node[0x10:0x50] = b"Other" + b"\0" * 59
        with self.assertRaisesRegex(ValueError, "cycle"):
            tool.walk_kmods(lambda address, size: bytes(node), 0x1000)

    def test_generator_has_caps_authentication_and_top_level_step(self):
        text = tool.generate(0xffffff801b6e8000, "474ef697fc283ba283a4763d76c8e200",
                             "/tmp/kernel.symbols", "/tmp/RaphaelGPU.dSYM")
        self.assertIn("MAX_HEADER = 65536", text)
        self.assertIn("MAX_KMODS = 256", text)
        self.assertIn("KMOD_NAME = 0x10", text)
        self.assertIn("KMOD_ADDRESS = 0x9c", text)
        self.assertIn("EXPECTED_UUID = '474ef697fc283ba283a4763d76c8e200'", text)
        self.assertIn("gdb.decode_line('RaphaelGPU.cpp:532')", text)
        self.assertIn("gdb.execute('hbreak *%#x'", text)
        self.assertIn("walk_kmods", text)
        self.assertIn("runtime_data[0] + 0x214938", text)
        self.assertIn("criticalDumpThread bytes mismatch", text)
        self.assertLess(text.index("continue\nprintf \"SOURCE_BREAKPOINT_HIT"),
                        text.index("set $before_pc=$pc\nsi\nprintf \"AFTER_SOURCE_STEP"))


if __name__ == "__main__":
    unittest.main()
