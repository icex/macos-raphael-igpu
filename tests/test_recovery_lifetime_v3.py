import importlib.util
import struct
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lease = load("recovery_lease_v2_for_lifetime_test", ROOT / "tools/recovery_lease_v2.py")
lifetime = load("recovery_lifetime_v3", ROOT / "tools/recovery_lifetime_v3.py")


class RecoveryLifetimeV3Tests(unittest.TestCase):
    def setUp(self):
        self.owned = lease.make_ownership_descriptor(
            0x0A000000, 0x0123456789ABCDEF, 0xFEDCBA9876543210)
        self.pool = lease.make_pool_status(
            self.owned, state=lease.POOL_ACTIVE,
            pool0_before=0x0E000000, pool0_after=0x0DFEB000,
            pool1_before=0x0C000000, pool1_after=0x0BFEB000, reason=0)
        self.valid = lifetime.make_valid_marker(self.owned.pack(), self.pool.pack())
        self.golden = dict(
            line.split("=", 1) for line in
            (ROOT / "tests/fixtures/recovery-lifetime-v3-golden.txt").read_text().splitlines()
            if line and not line.startswith("#"))

    def test_exact_schema3_layout_and_shared_golden_bytes(self):
        self.assertEqual(lifetime.LIFETIME_OFFSET, 0x200)
        self.assertEqual(lifetime.LIFETIME_STRUCT.format, "<QIIQQQQQQQQQ")
        self.assertEqual(lifetime.LIFETIME_STRUCT.size, 88)
        self.assertLessEqual(
            lifetime.LIFETIME_OFFSET + lifetime.LIFETIME_STRUCT.size,
            lease.SCRATCH_RELATIVE_OFFSET)
        self.assertEqual(self.valid.pack().hex(), self.golden["valid"])
        aborted = lifetime.make_abort_marker(
            self.valid, lifetime.REASON_DUPLICATE_POOL)
        self.assertEqual(aborted.pack().hex(), self.golden["abort_duplicate_pool"])

    def test_valid_marker_requires_exact_owned_and_active_pool_binding(self):
        lifetime.validate_marker(
            self.valid, self.owned.pack(), self.pool.pack(), require_valid=True)
        stale_owned = lease.make_ownership_descriptor(
            self.owned.lease_offset, self.owned.nonce_lo ^ 1, self.owned.nonce_hi)
        with self.assertRaises(lifetime.LifetimeValidationError):
            lifetime.validate_marker(
                self.valid, stale_owned.pack(), self.pool.pack(), require_valid=True)
        invalid_pool = lease.make_pool_status(
            self.owned, state=lease.POOL_INVALID,
            pool0_before=1, pool0_after=1,
            pool1_before=1, pool1_after=1,
            reason=lease.POOL_INVALID_REASONS.__iter__().__next__())
        with self.assertRaisesRegex(lifetime.LifetimeValidationError, "ACTIVE"):
            lifetime.make_valid_marker(self.owned.pack(), invalid_pool.pack())

    def test_readback_refuses_missing_unfinished_aborting_abort_and_corruption(self):
        absent = lifetime.inspect_readback(
            bytes(lifetime.LIFETIME_STRUCT.size), self.owned.pack(), self.pool.pack())
        self.assertEqual(absent.kind, lifetime.READBACK_ABSENT)
        with self.assertRaises(lifetime.LifetimeValidationError):
            lifetime.require_valid_readback(
                bytes(lifetime.LIFETIME_STRUCT.size), self.owned.pack(), self.pool.pack())

        unfinished = bytearray(self.valid.pack())
        unfinished[12:16] = bytes(4)
        self.assertEqual(lifetime.inspect_readback(
            bytes(unfinished), self.owned.pack(), self.pool.pack()).kind,
            lifetime.READBACK_UNFINISHED)

        aborting = bytearray(self.valid.pack())
        aborting[12:16] = struct.pack("<I", lifetime.STATE_ABORTING)
        self.assertEqual(lifetime.inspect_readback(
            bytes(aborting), self.owned.pack(), self.pool.pack()).kind,
            lifetime.READBACK_ABORTING)

        aborted = lifetime.make_abort_marker(
            self.valid, lifetime.REASON_POOL_OWNER).pack()
        self.assertEqual(lifetime.inspect_readback(
            aborted, self.owned.pack(), self.pool.pack()).kind,
            lifetime.READBACK_ABORT)
        with self.assertRaisesRegex(lifetime.LifetimeValidationError, "ABORT"):
            lifetime.require_valid_readback(
                aborted, self.owned.pack(), self.pool.pack())

        corrupt = bytearray(self.valid.pack())
        corrupt[-1] ^= 1
        with self.assertRaisesRegex(lifetime.LifetimeValidationError, "checksum"):
            lifetime.inspect_readback(
                bytes(corrupt), self.owned.pack(), self.pool.pack())

    def test_every_partial_valid_publication_is_non_authorizing(self):
        words = lifetime.LIFETIME_STRUCT.size // 4
        expected_operations = words + 1
        for stop in range(expected_operations):
            with self.subTest(stop=stop):
                memory = [0] * words
                operations = 0

                def write(index, value):
                    nonlocal operations
                    if operations == stop:
                        raise InterruptedError
                    operations += 1
                    memory[index] = value

                with self.assertRaises(InterruptedError):
                    lifetime.publish_valid(
                        self.valid, write, lambda index: memory[index], lambda: None)
                raw = struct.pack("<" + "I" * words, *memory)
                with self.assertRaises(lifetime.LifetimeValidationError):
                    lifetime.require_valid_readback(
                        raw, self.owned.pack(), self.pool.pack())

    def test_valid_publication_cannot_overwrite_an_existing_terminal_marker(self):
        aborted = lifetime.make_abort_marker(
            self.valid, lifetime.REASON_DUPLICATE_READY)
        memory = list(struct.unpack(
            "<" + "I" * (lifetime.LIFETIME_STRUCT.size // 4), aborted.pack()))
        writes = []
        self.assertFalse(lifetime.publish_valid(
            self.valid,
            lambda index, value: writes.append((index, value)),
            lambda index: memory[index], lambda: None))
        self.assertEqual(writes, [])

    def test_abort_publication_poison_is_first_and_never_returns_to_valid(self):
        words = lifetime.LIFETIME_STRUCT.size // 4
        aborted = lifetime.make_abort_marker(
            self.valid, lifetime.REASON_DUPLICATE_READY)
        expected_operations = words + 1
        for stop in range(1, expected_operations):
            with self.subTest(stop=stop):
                memory = list(struct.unpack("<" + "I" * words, self.valid.pack()))
                operations = 0

                def write(index, value):
                    nonlocal operations
                    if operations == stop:
                        raise InterruptedError
                    operations += 1
                    memory[index] = value

                with self.assertRaises(InterruptedError):
                    lifetime.publish_abort(
                        aborted, write, lambda index: memory[index], lambda: None)
                raw = struct.pack("<" + "I" * words, *memory)
                with self.assertRaises(lifetime.LifetimeValidationError):
                    lifetime.require_valid_readback(
                        raw, self.owned.pack(), self.pool.pack())

        memory = list(struct.unpack("<" + "I" * words, self.valid.pack()))
        writes = []
        self.assertTrue(lifetime.publish_abort(
            aborted,
            lambda index, value: (writes.append((index, value)),
                                  memory.__setitem__(index, value))[1],
            lambda index: memory[index], lambda: None))
        second_writes = []
        self.assertFalse(lifetime.publish_abort(
            lifetime.make_abort_marker(self.valid, lifetime.REASON_POOL_OWNER),
            lambda index, value: second_writes.append((index, value)),
            lambda index: memory[index], lambda: None))
        self.assertTrue(writes)
        self.assertEqual(second_writes, [])

    def test_abort_reason_domain_is_closed(self):
        for reason in lifetime.ABORT_REASONS:
            lifetime.validate_marker(
                lifetime.make_abort_marker(self.valid, reason),
                self.owned.pack(), self.pool.pack())
        for reason in (0, max(lifetime.ABORT_REASONS) + 1, 1 << 32):
            with self.subTest(reason=reason):
                with self.assertRaises(lifetime.LifetimeValidationError):
                    lifetime.make_abort_marker(self.valid, reason)


if __name__ == "__main__":
    unittest.main()
