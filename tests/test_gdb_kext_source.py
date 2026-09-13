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
                             "/tmp/kernel.symbols", "/tmp/RaphaelGPU.dSYM",
                             0x42130, "wrapVmmUpdateEntries",
                             bytes.fromhex("554889e541574156"), [0x42200, 0x42220],
                             "/tmp/rgpu-release-old/src", 0xf40b702c00)
        self.assertIn("MAX_HEADER = 65536", text)
        self.assertIn("MAX_KMODS = 256", text)
        self.assertIn("KMOD_NAME = 0x10", text)
        self.assertIn("KMOD_ADDRESS = 0x9c", text)
        self.assertIn("EXPECTED_UUID = '474ef697fc283ba283a4763d76c8e200'", text)
        self.assertIn("FUNCTION_OFFSET = 0x42130", text)
        self.assertIn("WRAPPER_NAME = 'wrapVmmUpdateEntries'", text)
        self.assertIn("set substitute-path /tmp/rgpu-release-old/src /tmp/source", text)
        self.assertIn("TARGET_GPU_ADDRESS = 1048163920896", text)
        self.assertLess(text.index("disable 2"), text.index("continue\npython\nif int"))
        self.assertLess(text.index("disable 1\nenable 2\nenable 3"),
                        text.index("condition 2"))
        for register in ('rdi', 'rsi', 'rdx', 'rcx', 'r8', 'r9'):
            self.assertIn("$entry_" + register, text)
        self.assertIn("safe_memory('self-before'", text)
        self.assertIn("hbreak *$entry_return", text)
        self.assertIn("safe_memory('self-after-return'", text)
        self.assertIn("GPU addresses; intentionally not dereferenced", text)
        self.assertIn("runtime wrapper bytes mismatch", text)
        self.assertIn("native boundary stop PC mismatch", text)
        self.assertIn("native call identity mismatch", text)
        self.assertIn("return stop PC mismatch", text)
        self.assertIn("return stack mismatch", text)
        self.assertIn("print cachedFbOffset", text)
        self.assertIn("info source", text)
        self.assertIn("info locals", text)
        self.assertIn("walk_kmods", text)
        self.assertIn("runtime_data[0] + 0x214938", text)
        self.assertNotIn("criticalDumpThread", text)

    def test_function_offset_is_positive_and_uuid_can_come_from_binary(self):
        with self.assertRaisesRegex(ValueError, "function offset"):
            tool.generate(0xffffff801b6e8000, "474ef697fc283ba283a4763d76c8e200",
                          "/tmp/kernel", "/tmp/dsym", 0, "wrapVmmUpdateEntries")

    def test_native_call_identity_uses_frame_return_and_stable_arguments(self):
        entry_args = (0x1000, 0x2000, 1, 0x3000, 0x271, 0x10000)
        self.assertTrue(tool.matching_native_call(
            0x8000, 0x9000, entry_args, 0x7ff8, 0x9000,
            (0x1000, 0x2000, 1, 0x4000, 0x271, 0x10000)))
        for rbp, saved_return, outgoing in (
                (0x7000, 0x9000, entry_args),
                (0x7ff8, 0xa000, entry_args),
                (0x7ff8, 0x9000, (0x1001, *entry_args[1:])),
                (0x7ff8, 0x9000, (*entry_args[:4], 0x272, entry_args[5]))):
            self.assertFalse(tool.matching_native_call(
                0x8000, 0x9000, entry_args, rbp, saved_return, outgoing))

    def test_target_coverage_is_overflow_safe_and_boundary_exact(self):
        target = 0xf40b702c00
        self.assertTrue(tool.update_covers(target, 1, target))
        self.assertTrue(tool.update_covers(target - 8, 2, target))
        self.assertFalse(tool.update_covers(target - 8, 1, target))
        self.assertFalse(tool.update_covers(target, 0, target))
        self.assertFalse(tool.update_covers(0, 1 << 61, target))

    def test_invalidate_info_and_prepared_root_decode_are_exact_and_bounded(self):
        raw = bytearray(0x28)
        struct.pack_into("<IIQQQI", raw, 0, 0, 1, 0x400000000,
                         0x23ffffffff, 0xf40b6ff000, 0xff)
        raw[0x24] = 1
        self.assertEqual(tool.decode_invalidate_info(bytes(raw)),
                         (0, 1, 0xf40b6ff000, 1))
        with self.assertRaisesRegex(ValueError, "0x28"):
            tool.decode_invalidate_info(bytes(raw[:-1]))
        prepared = bytearray(0x54)
        struct.pack_into("<I", prepared, 4, 0x4b6ff000)
        struct.pack_into("<I", prepared, 12, 0x8)
        self.assertEqual(tool.decode_prepared_root(bytes(prepared)), 0x84b6ff000)
        with self.assertRaisesRegex(ValueError, "0x54"):
            tool.decode_prepared_root(bytes(prepared[:-1]))

    def test_vmid1_root_scenario_captures_request_native_copy_and_prepared_output(self):
        text = tool.generate(0xffffff801b6e8000, "474ef697fc283ba283a4763d76c8e200",
                             "/tmp/kernel.symbols", "/tmp/RaphaelGPU.dSYM",
                             0x41000, "wrapVmmPrepare",
                             bytes.fromhex("554889e541574156"), [0x41100],
                             "/tmp/rgpu-release-old/src", scenario="vmid1-root")
        self.assertIn("SCENARIO = 'vmid1-root'", text)
        self.assertIn("hub == 0 and vmid == 1 and reprogram == 1", text)
        self.assertIn("safe_memory('vmid1-original-info'", text)
        self.assertIn("safe_memory('vmid1-native-info'", text)
        self.assertIn("VMID1_ORIGINAL_ROOT", text)
        self.assertIn("VMID1_NATIVE_ROOT", text)
        self.assertIn("VMID1_PREPARED_CPU_OUTPUT", text)
        self.assertIn("ACTUAL_REGISTER_PROGRAMMING_UNESTABLISHED", text)
        self.assertIn("$rdi==$entry_rdi && $rsi==$entry_rsi && $rcx==$entry_rcx", text)
        self.assertNotIn("$rdx==$entry_rdx", text)

    def test_vmid1_root_rejects_artifact_without_frame_pointer_prologue(self):
        with self.assertRaisesRegex(ValueError, "frame-pointer prologue"):
            tool.generate(0xffffff801b6e8000, "474ef697fc283ba283a4763d76c8e200",
                          "/tmp/kernel", "/tmp/dsym", 0x41000,
                          "wrapVmmPrepare", bytes.fromhex("4883ec2841574156"),
                          [0x41100], scenario="vmid1-root")

    def test_post_probe_keeps_runtime_auth_before_readonly_snapshot(self):
        text = tool.generate(0xffffff801b6e8000, "474ef697fc283ba283a4763d76c8e200",
                             "/tmp/kernel.symbols", "/tmp/RaphaelGPU.dSYM",
                             0x41000, "wrapVmmPrepare",
                             bytes.fromhex("554889e541574156"), [],
                             "/tmp/rgpu-release-old/src", scenario="post-probe")
        self.assertLess(text.index("RAPHAEL_AUTHENTICATED"),
                        text.index("POST_PROBE_INTERRUPT_HIT"))
        self.assertLess(text.index("gdb.execute('interrupt')"),
                        text.index("POST_PROBE_INTERRUPT_HIT"))
        self.assertIn("gdb.execute('quit')\nend\nquit", text)
        self.assertNotIn("hbreak", text[text.index("POST_PROBE_INTERRUPT_HIT"):])
        self.assertNotIn("continue", text[text.index("POST_PROBE_INTERRUPT_HIT"):])

    def test_prepare_native_call_pair_allows_copied_info_pointer(self):
        self.assertTrue(tool.matching_native_call(
            0x8000, 0x9000, (1, 2, 3, 4), 0x7ff8, 0x9000,
            (1, 2, 99, 4), stable_indices=(0, 1, 3)))
        self.assertFalse(tool.matching_native_call(
            0x8000, 0x9000, (1, 2, 3, 4), 0x7ff8, 0x9000,
            (1, 7, 99, 4), stable_indices=(0, 1, 3)))


if __name__ == "__main__":
    unittest.main()
