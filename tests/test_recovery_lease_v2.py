import importlib.util
import struct
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "tools" / "recovery_lease_v2.py"
GOLDEN_PATH = Path(__file__).parent / "fixtures" / "recovery-lease-v2-golden.txt"
SPEC = importlib.util.spec_from_file_location("recovery_lease_v2", MODULE_PATH)
lease = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lease)


class RecoveryLeaseV2Tests(unittest.TestCase):
    def setUp(self):
        self.nonce = (0x0123456789ABCDEF, 0xFEDCBA9876543210)
        self.base = 0x0A000000
        self.descriptor = lease.make_ownership_descriptor(self.base, *self.nonce)

    def owned_line(self, descriptor=None):
        return lease.format_owned_record(descriptor or self.descriptor)

    def active_status(self):
        return lease.make_pool_status(
            self.descriptor,
            state=lease.POOL_ACTIVE,
            pool0_before=0x0E000000,
            pool0_after=0x0DFEB000,
            pool1_before=0x0C000000,
            pool1_after=0x0BFEB000,
            reason=0,
        )

    @staticmethod
    def golden():
        return dict(
            line.split("=", 1)
            for line in GOLDEN_PATH.read_text().splitlines()
            if line and not line.startswith("#")
        )

    @staticmethod
    def resign_owned(descriptor, **changes):
        changed = descriptor._replace(**changes)
        return changed._replace(checksum=lease.checksum_fields(*changed[:-1]))

    @staticmethod
    def resign_status(status, **changes):
        changed = status._replace(**changes)
        return changed._replace(checksum=lease.checksum_fields(*changed[:-1]))

    def test_exact_wire_sizes_and_checksum_fields(self):
        raw = self.descriptor.pack()
        self.assertEqual(lease.OWNERSHIP_STRUCT.format, "<QIIQQQQQQQQ")
        self.assertEqual(len(raw), 80)
        fields = struct.unpack("<QIIQQQQQQQQ", raw)
        self.assertEqual(fields[:-1], (
            lease.OWNERSHIP_MAGIC,
            2,
            lease.OWNERSHIP_OWNED,
            self.base,
            self.base + 0x15000,
            self.base + 0x1000,
            self.base + 0x14004,
            *self.nonce,
            1,
        ))
        expected = lease.CHECKSUM_DOMAIN
        for value in fields[:-1]:
            expected ^= value
        self.assertEqual(fields[-1], expected)
        self.assertEqual(lease.OwnershipDescriptor.unpack(raw), self.descriptor)

        status = self.active_status()
        status_raw = status.pack()
        self.assertEqual(lease.POOL_STATUS_STRUCT.format, "<QIIQQQQQQQQQQQ")
        self.assertEqual(len(status_raw), 104)
        self.assertEqual(lease.PoolStatus.unpack(status_raw), status)

    def test_shared_cross_language_golden_bytes(self):
        golden = self.golden()
        self.assertEqual(self.base, int(golden["lease_offset"], 16))
        self.assertEqual(self.nonce, (
            int(golden["nonce_lo"], 16), int(golden["nonce_hi"], 16)))
        self.assertEqual(self.descriptor.pack().hex(), golden["ownership"])
        self.assertEqual(self.active_status().pack().hex(), golden["active"])
        invalid = lease.make_pool_status(
            self.descriptor,
            state=lease.POOL_INVALID,
            pool0_before=0x0E000000,
            pool0_after=0x0DFEB000,
            pool1_before=0x0C000000,
            pool1_after=0x0C000000,
            reason=2,
        )
        self.assertEqual(invalid.pack().hex(), golden["invalid"])

    def test_geometry_derives_only_bounded_nonoverlapping_writes(self):
        ranges = lease.scratch_ranges(self.descriptor)
        self.assertEqual(ranges, {
            "ring": (self.base + 0x1000, self.base + 0x11000),
            "mqd": (self.base + 0x11000, self.base + 0x11800),
            "rptr": (self.base + 0x12000, self.base + 0x12004),
            "wptr": (self.base + 0x12008, self.base + 0x12010),
            "eop": (self.base + 0x13000, self.base + 0x14000),
            "fence": (self.base + 0x14000, self.base + 0x14004),
        })
        ordered = sorted(ranges.values())
        self.assertTrue(all(a[1] <= b[0] for a, b in zip(ordered, ordered[1:])))
        self.assertTrue(all(self.base <= lo < hi <= self.base + 0x15000
                            for lo, hi in ordered))

    def test_geometry_rejects_corruption_bar_edges_and_gart_overlap(self):
        misaligned_base = self.base + 1
        semantic_bad = (
            self.resign_owned(
                self.descriptor,
                lease_offset=misaligned_base,
                lease_end=misaligned_base + lease.LEASE_SIZE,
                scratch_offset=misaligned_base + lease.SCRATCH_RELATIVE_OFFSET,
                scratch_end=misaligned_base + lease.SCRATCH_RELATIVE_END,
            ),
            self.resign_owned(
                self.descriptor, lease_end=self.descriptor.lease_end - 1),
            self.resign_owned(
                self.descriptor, scratch_offset=self.descriptor.scratch_offset + 1),
            self.resign_owned(
                self.descriptor, scratch_end=self.descriptor.scratch_end + 1),
        )
        for descriptor in semantic_bad:
            with self.subTest(semantic_descriptor=descriptor):
                with self.assertRaises(lease.LeaseValidationError):
                    lease.validate_ownership_descriptor(descriptor, expected_nonce=self.nonce)

        checksum_bad = self.descriptor._replace(checksum=self.descriptor.checksum ^ 1)
        with self.assertRaisesRegex(lease.LeaseValidationError, "checksum"):
            lease.validate_ownership_descriptor(checksum_bad, expected_nonce=self.nonce)

        bar_edge = lease.make_ownership_descriptor(
            lease.VRAM_BAR_SIZE - lease.LEASE_SIZE, *self.nonce)
        lease.validate_ownership_descriptor(bar_edge)
        with self.assertRaises(lease.LeaseValidationError):
            lease.validate_ownership_descriptor(
                bar_edge, bar_size=lease.VRAM_BAR_SIZE - 1)

        lease.validate_gart_disjoint(self.descriptor, self.base - 0x1000, 0x1000)
        lease.validate_gart_disjoint(
            self.descriptor, self.descriptor.lease_end, 0x2000)
        with self.assertRaises(lease.LeaseValidationError):
            lease.validate_gart_disjoint(
                self.descriptor, self.base - 0x1000, 0x1001)
        with self.assertRaises(lease.LeaseValidationError):
            lease.validate_gart_disjoint(
                self.descriptor, self.descriptor.lease_end - 1, 1)

    def test_nonce_and_integer_domain_are_strict(self):
        with self.assertRaises(lease.LeaseValidationError):
            lease.validate_ownership_descriptor(
                self.descriptor, expected_nonce=(self.nonce[0] ^ 1, self.nonce[1]))
        with self.assertRaises(lease.LeaseValidationError):
            lease.make_ownership_descriptor(-0x1000, *self.nonce)
        with self.assertRaises(lease.LeaseValidationError):
            lease.make_ownership_descriptor(0x1000, 1 << 64, self.nonce[1])
        with self.assertRaisesRegex(lease.LeaseValidationError, "wraps"):
            lease.make_ownership_descriptor(
                (1 << 64) - lease.LEASE_SIZE + 1, *self.nonce)
        lease.validate_ownership_descriptor(
            lease.make_ownership_descriptor(self.base, 0, self.nonce[1]),
            expected_nonce=(0, self.nonce[1]),
        )

    def test_active_pool_status_requires_exact_unsigned_deltas(self):
        status = self.active_status()
        lease.validate_pool_status(status, self.descriptor)
        self.assertEqual(status.pool0_before - status.pool0_after, lease.LEASE_SIZE)

        semantic_bad = (
            self.resign_status(status, reason=1),
            self.resign_status(status, pool0_after=status.pool0_after + 1),
            self.resign_status(status, pool1_before=status.pool1_after - 1),
            self.resign_status(status, nonce_hi=status.nonce_hi ^ 1),
        )
        for bad in semantic_bad:
            with self.subTest(semantic_status=bad):
                with self.assertRaises(lease.LeaseValidationError):
                    lease.validate_pool_status(bad, self.descriptor)

        checksum_bad = status._replace(checksum=status.checksum ^ 1)
        with self.assertRaisesRegex(lease.LeaseValidationError, "checksum"):
            lease.validate_pool_status(checksum_bad, self.descriptor)

    def test_invalid_pool_status_is_terminal_and_needs_reason(self):
        invalid = lease.make_pool_status(
            self.descriptor,
            state=lease.POOL_INVALID,
            pool0_before=0x100000,
            pool0_after=0xEB000,
            pool1_before=0x100000,
            pool1_after=0x100000,
            reason=2,
        )
        lease.validate_pool_status(invalid, self.descriptor)
        with self.assertRaises(lease.LeaseValidationError):
            lease.make_pool_status(
                self.descriptor,
                state=lease.POOL_INVALID,
                pool0_before=1,
                pool0_after=1,
                pool1_before=1,
                pool1_after=1,
                reason=0,
            )
        with self.assertRaises(lease.LeaseValidationError):
            lease.make_pool_status(
                self.descriptor,
                state=lease.POOL_INVALID,
                pool0_before=1,
                pool0_after=1,
                pool1_before=1,
                pool1_after=1,
                reason=1 << 32,
            )
        with self.assertRaises(lease.LeaseValidationError):
            lease.make_pool_status(
                self.descriptor,
                state=lease.POOL_INVALID,
                pool0_before=1,
                pool0_after=1,
                pool1_before=1,
                pool1_after=1,
                reason=8,
            )

    def test_optional_pool_readback_preserves_owned_recovery_across_torn_write(self):
        absent = lease.inspect_pool_status_readback(
            bytes(lease.POOL_STATUS_STRUCT.size), self.descriptor)
        self.assertEqual(absent.kind, lease.POOL_READBACK_ABSENT)
        self.assertIsNone(absent.status)

        active_raw = self.active_status().pack()
        # Guest writes the final checksum while state remains zero, then commits by
        # storing the state DWORD last. This is the exact precommit image.
        unfinished_raw = bytearray(active_raw)
        unfinished_raw[12:16] = bytes(4)
        unfinished = lease.inspect_pool_status_readback(
            bytes(unfinished_raw), self.descriptor)
        self.assertEqual(unfinished.kind, lease.POOL_READBACK_UNFINISHED)
        self.assertIsNone(unfinished.status)

        torn_checksum = bytearray(active_raw)
        torn_checksum[-1] ^= 1
        with self.assertRaisesRegex(lease.LeaseValidationError, "checksum"):
            lease.inspect_pool_status_readback(bytes(torn_checksum), self.descriptor)

        invalid_commit = bytearray(active_raw)
        invalid_commit[12:16] = (0x12345678).to_bytes(4, "little")
        with self.assertRaisesRegex(lease.LeaseValidationError, "commit state"):
            lease.inspect_pool_status_readback(bytes(invalid_commit), self.descriptor)

        committed = lease.inspect_pool_status_readback(active_raw, self.descriptor)
        self.assertEqual(committed.kind, lease.POOL_READBACK_COMMITTED)
        self.assertEqual(committed.status, self.active_status())

        semantically_bad = self.resign_status(self.active_status(), reason=1)
        with self.assertRaises(lease.LeaseValidationError):
            lease.inspect_pool_status_readback(semantically_bad.pack(), self.descriptor)

    def test_published_pool_status_requires_matching_committed_readback(self):
        active = self.active_status()
        self.assertEqual(
            lease.require_published_pool_readback(active, active.pack(), self.descriptor),
            active,
        )
        unfinished_raw = bytearray(active.pack())
        unfinished_raw[12:16] = bytes(4)
        with self.assertRaises(lease.LeaseValidationError):
            lease.require_published_pool_readback(
                active, bytes(unfinished_raw), self.descriptor)

    def test_parser_accepts_identical_replays_and_owned_only(self):
        owned = self.owned_line()
        evidence = lease.parse_critical_records(
            ["unrelated", owned, owned, owned], expected_nonce=self.nonce)
        self.assertEqual(evidence.descriptor, self.descriptor)
        self.assertIsNone(evidence.pool_status)
        self.assertEqual(evidence.owned_replays, 3)

        active = self.active_status()
        pool = lease.format_pool_record(active)
        evidence = lease.parse_critical_records(
            [owned, pool, owned, pool], expected_nonce=self.nonce)
        self.assertEqual(evidence.pool_status, active)
        self.assertEqual(evidence.owned_replays, 2)
        self.assertEqual(evidence.pool_replays, 2)

    def test_parser_accepts_production_diagnostics_around_wire_records(self):
        active = self.active_status()
        evidence = lease.parse_critical_records([
            "XH: dynamic recovery lease configured nonce="
            "0123456789abcdef_fedcba9876543210",
            "XH2: legacy diagnostic prefix is outside the wire namespace",
            self.owned_line(),
            "XH: pool init begin",
            lease.format_pool_record(active),
            "XH: pool exclusion active element=0xffffff8000000000",
            self.owned_line(),
            lease.format_pool_record(active),
        ], expected_nonce=self.nonce)
        self.assertEqual(evidence.descriptor, self.descriptor)
        self.assertEqual(evidence.pool_status, active)
        self.assertEqual(evidence.owned_replays, 2)
        self.assertEqual(evidence.pool_replays, 2)

    def test_pool_record_uses_c_printf_hex_spelling_for_zero(self):
        invalid = lease.make_pool_status(
            self.descriptor,
            state=lease.POOL_INVALID,
            pool0_before=0,
            pool0_after=0,
            pool1_before=0,
            pool1_after=0,
            reason=1,
        )
        record = lease.format_pool_record(invalid)
        self.assertIn("pool0=0->0 pool1=0->0", record)
        evidence = lease.parse_critical_records(
            [self.owned_line(), record], expected_nonce=self.nonce)
        self.assertEqual(evidence.pool_status, invalid)

    def test_parser_rejects_order_conflicts_and_malformed_xh2(self):
        owned = self.owned_line()
        active = self.active_status()
        pool = lease.format_pool_record(active)
        other = lease.make_ownership_descriptor(self.base - 0x20000, *self.nonce)
        invalid = lease.make_pool_status(
            self.descriptor,
            state=lease.POOL_INVALID,
            pool0_before=1,
            pool0_after=1,
            pool1_before=1,
            pool1_after=1,
            reason=1,
        )
        cases = (
            [pool, owned],
            [owned, lease.format_owned_record(other)],
            [owned, lease.format_pool_record(invalid), pool],
            [owned, "XH2 OWNED malformed"],
            [owned, "XH2 ABORT reason=duplicate-pool nonce="
                    "0123456789abcdef_fedcba9876543210"],
            [owned, pool.replace("state=ACTIVE", "state=BOGUS")],
            [owned, pool.replace("pool0=0xe000000", "pool0=0xE000000")],
            [owned, pool.replace("reason=0", "reason=00")],
        )
        for records in cases:
            with self.subTest(records=records):
                with self.assertRaises(lease.LeaseValidationError):
                    lease.parse_critical_records(records, expected_nonce=self.nonce)

    def test_parser_has_global_bounds_without_replay_semantics(self):
        owned = self.owned_line()
        records = [owned] * lease.MAX_CRITICAL_RECORDS
        evidence = lease.parse_critical_records(records, expected_nonce=self.nonce)
        self.assertEqual(evidence.owned_replays, lease.MAX_CRITICAL_RECORDS)
        with self.assertRaises(lease.LeaseValidationError):
            lease.parse_critical_records(records + [owned], expected_nonce=self.nonce)
        with self.assertRaises(lease.LeaseValidationError):
            lease.parse_critical_records(
                ["X" * (lease.MAX_RECORD_BYTES + 1), owned],
                expected_nonce=self.nonce)

        unrelated = ["ordinary critical record"] * lease.MAX_CRITICAL_RECORDS
        evidence = lease.parse_critical_records(
            unrelated + [owned], expected_nonce=self.nonce)
        self.assertEqual(evidence.owned_replays, 1)

        oversized_stream = [
            "x" * lease.MAX_RECORD_BYTES
        ] * (lease.MAX_CRITICAL_STREAM_BYTES // lease.MAX_RECORD_BYTES + 1)
        with self.assertRaisesRegex(lease.LeaseValidationError, "stream exceeds"):
            lease.parse_critical_records(
                oversized_stream + [owned], expected_nonce=self.nonce)

    def test_pool_record_without_status_or_missing_owned_refuses(self):
        with self.assertRaises(lease.LeaseValidationError):
            lease.parse_critical_records([], expected_nonce=self.nonce)
        with self.assertRaises(lease.LeaseValidationError):
            lease.parse_critical_records(
                ["ordinary critical record"], expected_nonce=self.nonce)

    def test_parser_binds_manifest_nonce(self):
        with self.assertRaisesRegex(lease.LeaseValidationError, "nonce"):
            lease.parse_critical_records(
                [self.owned_line()],
                expected_nonce=(self.nonce[0] ^ 1, self.nonce[1]),
            )


if __name__ == "__main__":
    unittest.main()
