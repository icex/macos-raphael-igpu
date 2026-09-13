import importlib.util
import struct
import re
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("gdb_kext_source", ROOT / "tools/gdb-kext-source.py")
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)


class GdbKextSourceTests(unittest.TestCase):
    def test_kiq_start_generator_describes_five_arg_result_and_three_breakpoints(self):
        text = tool.generate_kiq_start(
            0xffffff801b6e8000, "474ef697fc283ba283a4763d76c8e200",
            "/tmp/kernel.symbols", "/tmp/RaphaelGPU.dSYM", 0x19120,
            bytes.fromhex("554889e541574156"), 0x1920c, "/tmp/source")
        self.assertIn("KIQ_START_ENTRY", text)
        self.assertIn("KIQ_START_NATIVE_CALL_BOUNDARY", text)
        self.assertIn("KIQ_START_RETURN result=%#x", text)
        self.assertIn("KIQ_START_CAPTURE_COMPLETE", text)
        self.assertIn("KIQ_START_DETACHED", text)
        self.assertIn("read(entry_spec,12)", text)
        self.assertIn("read(entry_out,4)", text)
        for register in ("rdi", "rsi", "rdx", "rcx", "r8"):
            self.assertIn("entry_" + register, text)
        self.assertIn("& 0xffffffff", text)
        self.assertEqual(text.count("gdb.BP_HARDWARE_BREAKPOINT"), 3)

    def test_kiq_start_generated_loop_stops_after_success_or_failure_return(self):
        text = tool.generate_kiq_start(
            0xffffff801b6e8000, "474ef697fc283ba283a4763d76c8e200",
            "/tmp/kernel.symbols", "/tmp/RaphaelGPU.dSYM", 0x19120,
            bytes.fromhex("554889e541574156"), 0x1920c, "/tmp/source")
        self.assertIn("if result == 0: outcome='success'", text)
        self.assertIn("if result == 0: outcome='success'", text)
        self.assertIn("else: outcome='failure'", text)
        self.assertIn("raw=read(entry_spec,12)", text)
        self.assertIn("raw_out=read(entry_out,4)", text)
        self.assertIn("native_reached=True", text)
        self.assertIn("native_reached=False", text)
        self.assertLess(text.index("gdb.execute('detach')"), text.index("gdb.execute('quit')"))

    def test_kiq_start_exact_generated_loop_executes_success_and_refusal(self):
        text = tool.generate_kiq_start(
            0xffffff801b6e8000, "474ef697fc283ba283a4763d76c8e200",
            "/tmp/kernel.symbols", "/tmp/RaphaelGPU.dSYM", 0x19120,
            bytes.fromhex("554889e541574156"), 0x1920c, "/tmp/source")
        body = text.split("class ReturnBP", 1)[1].split("\nend\nquit", 1)[0]
        body = "class ReturnBP" + body
        for result in (0, 0xe00002bc):
            events = [
                {'pc': 0x100000, 'rsp': 0x8000, 'rbp': 0x7ff8,
                 'rdi': 0x1000, 'rsi': 1, 'rdx': 2, 'rcx': 0x9000, 'r8': 0xa000, 'rax': 0},
                {'pc': 0xbeef, 'rsp': 0x8008, 'rbp': 0x7ff8,
                 'rdi': 0xdead, 'rsi': 0, 'rdx': 0, 'rcx': 0, 'r8': 0, 'rax': result},
            ]
            if result == 0:
                events.insert(1, {'pc': 0x1000ec, 'rsp': 0x7f00, 'rbp': 0x7ff8,
                                   'rdi': 0x1000, 'rsi': 1, 'rdx': 2, 'rcx': 0, 'r8': 0, 'rax': 0})
            state = dict(events[0]); state['detached'] = False
            class BP:
                def __init__(self, spec, kind=None, internal=False): self.enabled = True
                def delete(self): self.enabled = False
            class Fake:
                BP_HARDWARE_BREAKPOINT = 1; Breakpoint = BP
                def parse_and_eval(self, reg): return state[reg[1:]]
                def selected_thread(self): return types.SimpleNamespace(ptid='fake')
                def selected_inferior(self): return types.SimpleNamespace(read_memory=lambda a,n: b'\0'*n)
                def execute(self, command):
                    if command == 'continue': state.update(events.pop(0))
                    elif command == 'detach': state['detached'] = True
            fake = Fake()
            def read(addr, size):
                if addr == 0x8000 and size == 8: return (0xbeef).to_bytes(8, 'little')
                return b'\0' * size
            ns = {'gdb': fake, 'struct': struct, 'read': read, 'start': 0x100000,
                  'native': 0x1000ec, 'entry_rsp': None, 'entry_return': None,
                  'entry_rdi': None, 'entry_out': None}
            exec(body, ns)
            self.assertTrue(state['detached'])
            self.assertEqual(events, [])

    def test_kiq_stamp_scenario_uses_dynamic_return_and_bounded_channel_state(self):
        text = tool.generate_kiq_stamp(
            0xffffff801b6e8000, "474ef697fc283ba283a4763d76c8e200",
            "/tmp/kernel.symbols", "/tmp/RaphaelGPU.dSYM",
            0x1eeb0, bytes.fromhex("554889e541574156"),
            0x1a620, bytes.fromhex("554889e541574156"), "/tmp/source")
        self.assertIn("KIQ_WAIT_FAILURE result=0", text)
        self.assertIn("gdb.BP_HARDWARE_BREAKPOINT", text)
        self.assertIn("a+0x84", text)
        self.assertIn("a+0x30", text)
        self.assertIn("a+0xc0", text)
        self.assertIn("a+0xe0", text)
        self.assertIn("timestamp_memory32", text)
        self.assertIn("safe_canonical(label+'-ring-descriptor',ring,0x100)", text)
        self.assertIn("safe('kiq-channel-descriptor',selfp,0x100)", text)
        self.assertIn("safe('kiq-channel-descriptor-return',selfp,0x100)", text)
        self.assertIn("result=int(gdb.parse_and_eval('$rax')) & 0xff", text)
        self.assertIn("return_bp.delete()", text)
        self.assertNotIn("delete 3", text)
        self.assertIn("entry=None; ret=None", text)

    def test_kiq_stamp_generated_loop_handles_nested_and_clobbered_return(self):
        text = tool.generate_kiq_stamp(
            0xffffff801b6e8000, "474ef697fc283ba283a4763d76c8e200",
            "/tmp/kernel.symbols", "/tmp/RaphaelGPU.dSYM", 0x1eeb0,
            bytes.fromhex("554889e541574156"), 0x1a620,
            bytes.fromhex("554889e541574156"), "/tmp/source")
        block = text.split("class ReturnBP(gdb.Breakpoint):\n", 1)[1].split("end\nquit", 1)[0]
        events = []
        state = {'pc': 0, 'rsp': 0, 'rdi': 0, 'rsi': 0, 'rdx': 0, 'rcx': 0, 'r8': 0, 'rax': 0,
                 'detached': False, 'reads': []}
        class BP:
            next_id = 1
            all = []
            def __init__(self, spec, kind=None, internal=False):
                self.address = int(spec[1:], 16); self.enabled = True
                self.deleted = False; self.number = BP.next_id; BP.next_id += 1
                BP.all.append(self)
            def delete(self): self.deleted = True; self.enabled = False
        class FakeGdb:
            BP_HARDWARE_BREAKPOINT = 1
            Breakpoint = BP
            def parse_and_eval(self, reg): return state[reg[1:]]
            def selected_thread(self): return types.SimpleNamespace(ptid='fake-thread')
            def execute(self, command):
                if command == 'continue':
                    while events:
                        state.update(events.pop(0))
                        active = [b for b in BP.all if b.enabled and not b.deleted and hasattr(b, 'stop')]
                        if not active or all(b.stop() for b in active): break
                elif command == 'detach': state['detached'] = True
        fake = FakeGdb(); gdbmod = fake
        def read(addr, size):
            state['reads'].append((addr, size))
            returns = {0x8100: 0x9000, 0x8200: 0x9100,
                       0x1000 + 0x30: 0x6000}
            if size == 8 and addr in returns:
                return returns[addr].to_bytes(8, 'little')
            if addr in (0x1000 + 0x80, 0x1000 + 0x84, 0x1000 + 0x30):
                return (1).to_bytes(4, 'little') * (size // 4)
            if addr == 0x1000 + 0xc0 and size == 8:
                return (0x7000).to_bytes(8, 'little')
            if addr == 0x1000 + 0xe0 and size == 4:
                return (0xffffffff).to_bytes(4, 'little')
            if addr == 0x7000 and size == 4:
                return bytes(range(1, 5))
            if addr == 0x6000 and size == 0x100:
                return bytes(range(0x100))
            return b'\0' * size
        wa, sa = 0x2000, 0x3000
        events.extend([
            {'pc': sa, 'rsp': 0x8000, 'rdi': 0x1000, 'rsi': 0, 'rax': 0},
            {'pc': wa, 'rsp': 0x8100, 'rdi': 0x1000, 'rsi': 7, 'rax': 0},
            {'pc': 0x9000, 'rsp': 0x8108, 'rdi': 0xdead, 'rsi': 0, 'rax': 0x10001},
            {'pc': wa, 'rsp': 0x8200, 'rdi': 0x1000, 'rsi': 8, 'rax': 0},
            {'pc': 0x9100, 'rsp': 0x9999, 'rdi': 0xbeef, 'rsi': 0, 'rax': 0},
            {'pc': 0x9100, 'rsp': 0x8208, 'rdi': 0xbeef, 'rsi': 0, 'rax': 0x10000},
        ])
        channel_src = 'def channel_state' + text.split('def channel_state', 1)[1].split('kh=read', 1)[0]
        safe_src = 'def safe' + text.split('def safe', 1)[1].split('def channel_state', 1)[0]
        canonical_src = 'def canonical' + text.split('def canonical', 1)[1].split('def channel_state', 1)[0]
        ns = {'gdb': gdbmod, 'struct': struct, 'read': read,
              'wa': wa, 'sa': sa, 'WAIT_OFFSET': 0, 'SUBMIT_OFFSET': 0,
              'time': types.SimpleNamespace(monotonic=lambda: 1.0)}
        exec(channel_src, ns)
        exec(safe_src, ns)
        exec(canonical_src, ns)
        exec('class ReturnBP(gdb.Breakpoint):\n' + block, ns)
        self.assertTrue(state['detached'])
        self.assertTrue(any(addr == 0x1000 + 0x84 for addr, _ in state['reads']))
        self.assertTrue(any(addr == 0x1000 + 0x30 for addr, _ in state['reads']))
        self.assertTrue(any(addr == 0x1000 + 0xc0 for addr, _ in state['reads']))
        self.assertTrue(any(addr == 0x1000 + 0xe0 for addr, _ in state['reads']))
        self.assertTrue(any(addr == 0x7000 and size == 4 for addr, size in state['reads']))
        self.assertTrue(any(addr == 0x6000 and size == 0x100 for addr, size in state['reads']))
        self.assertTrue(any(addr == 0x1000 and size == 0x100 for addr, size in state['reads']))
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
