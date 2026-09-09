#!/usr/bin/env python3
"""Pure wire and geometry validation for the native-owned recovery lease v2.

This module performs no device access.  Callers must validate a canonical critical-record
sequence here before opening VFIO, then compare the returned bytes with BAR readback before
constructing any recovery write plan.
"""

import re
import struct
from typing import Iterable, NamedTuple, Optional


U64_MAX = (1 << 64) - 1
U32_MAX = (1 << 32) - 1
VRAM_BAR_SIZE = 0x10000000
LEASE_ALIGNMENT = 0x1000
LEASE_SIZE = 0x15000
POOL_STATUS_OFFSET = 0x100
SCRATCH_RELATIVE_OFFSET = 0x1000
SCRATCH_RELATIVE_END = 0x14004

OWNERSHIP_MAGIC = int.from_bytes(b"RGPUKIR2", "little")
OWNERSHIP_VERSION = 2
OWNERSHIP_OWNED = int.from_bytes(b"OWND", "little")
POOL_STATUS_MAGIC = int.from_bytes(b"RGPUKPS2", "little")
POOL_ACTIVE = int.from_bytes(b"ACTV", "little")
POOL_INVALID = int.from_bytes(b"INVL", "little")
POOL_INVALID_REASONS = frozenset(range(1, 8))
GENERATION = 1
CHECKSUM_DOMAIN = 0x9E3779B97F4A7C15

OWNERSHIP_STRUCT = struct.Struct("<QIIQQQQQQQQ")
POOL_STATUS_STRUCT = struct.Struct("<QIIQQQQQQQQQQQ")

# This bounds the already-extracted canonical critical stream.  Repetition within the bound
# has no ownership meaning: byte-identical immediate/deferred replays are deduplicated below.
MAX_CRITICAL_RECORDS = 256
MAX_RECORD_BYTES = 512
MAX_CRITICAL_STREAM_BYTES = 8 * 1024 * 1024

_HEX = r"(0|0x[1-9a-f][0-9a-f]*)"
_OWNED_RE = re.compile(
    r"XH2 OWNED nonce=([0-9a-f]{16})_([0-9a-f]{16}) gen=1 "
    r"lease=" + _HEX + r"-" + _HEX + r" scratch=" + _HEX + r"-" + _HEX +
    r" checksum=" + _HEX
)
_POOL_RE = re.compile(
    r"XH2 POOL state=(ACTIVE|INVALID) nonce=([0-9a-f]{16})_([0-9a-f]{16}) "
    r"gen=1 lease=" + _HEX + r"-" + _HEX + r" pool0=" + _HEX + r"->" + _HEX +
    r" pool1=" + _HEX + r"->" + _HEX + r" reason=(0|[1-9][0-9]*) checksum=" + _HEX
)


class LeaseValidationError(ValueError):
    pass


class OwnershipDescriptor(NamedTuple):
    magic: int
    version: int
    state: int
    lease_offset: int
    lease_end: int
    scratch_offset: int
    scratch_end: int
    nonce_lo: int
    nonce_hi: int
    generation: int
    checksum: int

    def pack(self) -> bytes:
        validate_ownership_descriptor(self)
        return OWNERSHIP_STRUCT.pack(*self)

    @classmethod
    def unpack(cls, raw: bytes):
        if len(raw) != OWNERSHIP_STRUCT.size:
            raise LeaseValidationError("ownership descriptor has the wrong byte length")
        value = cls(*OWNERSHIP_STRUCT.unpack(raw))
        validate_ownership_descriptor(value)
        return value


class PoolStatus(NamedTuple):
    magic: int
    version: int
    state: int
    lease_offset: int
    lease_end: int
    nonce_lo: int
    nonce_hi: int
    generation: int
    pool0_before: int
    pool0_after: int
    pool1_before: int
    pool1_after: int
    reason: int
    checksum: int

    def pack(self) -> bytes:
        _validate_integer_fields(self)
        if self.checksum != checksum_fields(*self[:-1]):
            raise LeaseValidationError("pool status checksum mismatch")
        return POOL_STATUS_STRUCT.pack(*self)

    @classmethod
    def unpack(cls, raw: bytes):
        if len(raw) != POOL_STATUS_STRUCT.size:
            raise LeaseValidationError("pool status has the wrong byte length")
        value = cls(*POOL_STATUS_STRUCT.unpack(raw))
        _validate_integer_fields(value)
        if value.checksum != checksum_fields(*value[:-1]):
            raise LeaseValidationError("pool status checksum mismatch")
        return value


class LeaseEvidence(NamedTuple):
    descriptor: OwnershipDescriptor
    pool_status: Optional[PoolStatus]
    owned_replays: int
    pool_replays: int


POOL_READBACK_ABSENT = "absent"
POOL_READBACK_UNFINISHED = "unfinished"
POOL_READBACK_COMMITTED = "committed"


class PoolReadback(NamedTuple):
    kind: str
    status: Optional[PoolStatus]


def _u64(value: int, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= U64_MAX:
        raise LeaseValidationError(f"{name} is outside the unsigned 64-bit domain")
    return value


def _validate_integer_fields(values) -> None:
    for index, value in enumerate(values):
        _u64(value, f"field {index}")


def _checked_add(left: int, right: int, name: str) -> int:
    _u64(left, name)
    _u64(right, f"{name} length")
    result = left + right
    if result > U64_MAX:
        raise LeaseValidationError(f"{name} wraps the unsigned 64-bit domain")
    return result


def checksum_fields(*fields: int) -> int:
    value = CHECKSUM_DOMAIN
    for index, field in enumerate(fields):
        value ^= _u64(field, f"checksum field {index}")
    return value


def make_ownership_descriptor(
        lease_offset: int, nonce_lo: int, nonce_hi: int) -> OwnershipDescriptor:
    lease_end = _checked_add(lease_offset, LEASE_SIZE, "lease")
    scratch_offset = _checked_add(lease_offset, SCRATCH_RELATIVE_OFFSET, "scratch")
    scratch_end = _checked_add(lease_offset, SCRATCH_RELATIVE_END, "scratch end")
    fields = (
        OWNERSHIP_MAGIC, OWNERSHIP_VERSION, OWNERSHIP_OWNED,
        lease_offset, lease_end, scratch_offset, scratch_end,
        nonce_lo, nonce_hi, GENERATION,
    )
    descriptor = OwnershipDescriptor(*fields, checksum_fields(*fields))
    validate_ownership_descriptor(descriptor, expected_nonce=(nonce_lo, nonce_hi))
    return descriptor


def validate_ownership_descriptor(
        descriptor: OwnershipDescriptor, *, expected_nonce=None,
        bar_size: int = VRAM_BAR_SIZE) -> None:
    if not isinstance(descriptor, OwnershipDescriptor):
        raise LeaseValidationError("ownership descriptor has the wrong type")
    _validate_integer_fields(descriptor)
    _u64(bar_size, "BAR size")
    if descriptor.magic != OWNERSHIP_MAGIC or descriptor.version != OWNERSHIP_VERSION:
        raise LeaseValidationError("ownership descriptor magic or version mismatch")
    if descriptor.state != OWNERSHIP_OWNED or descriptor.generation != GENERATION:
        raise LeaseValidationError("ownership descriptor state or generation mismatch")
    if descriptor.checksum != checksum_fields(*descriptor[:-1]):
        raise LeaseValidationError("ownership descriptor checksum mismatch")
    if descriptor.lease_offset == 0 or descriptor.lease_offset % LEASE_ALIGNMENT:
        raise LeaseValidationError("lease offset is zero or misaligned")
    if descriptor.lease_end != _checked_add(
            descriptor.lease_offset, LEASE_SIZE, "lease"):
        raise LeaseValidationError("lease extent does not match the v2 size")
    if descriptor.lease_end > bar_size:
        raise LeaseValidationError("lease extends beyond the BAR")
    if descriptor.scratch_offset != _checked_add(
            descriptor.lease_offset, SCRATCH_RELATIVE_OFFSET, "scratch"):
        raise LeaseValidationError("scratch offset does not match the v2 layout")
    if descriptor.scratch_end != _checked_add(
            descriptor.lease_offset, SCRATCH_RELATIVE_END, "scratch end"):
        raise LeaseValidationError("scratch end does not match the v2 layout")
    if POOL_STATUS_OFFSET + POOL_STATUS_STRUCT.size > SCRATCH_RELATIVE_OFFSET:
        raise LeaseValidationError("metadata overlaps scratch")
    if expected_nonce is not None:
        if (not isinstance(expected_nonce, tuple) or len(expected_nonce) != 2 or
                (descriptor.nonce_lo, descriptor.nonce_hi) != expected_nonce):
            raise LeaseValidationError("ownership nonce mismatch")


def scratch_ranges(descriptor: OwnershipDescriptor):
    validate_ownership_descriptor(descriptor)
    base = descriptor.lease_offset
    ranges = {
        "ring": (base + 0x1000, base + 0x11000),
        "mqd": (base + 0x11000, base + 0x11800),
        "rptr": (base + 0x12000, base + 0x12004),
        "wptr": (base + 0x12008, base + 0x12010),
        "eop": (base + 0x13000, base + 0x14000),
        "fence": (base + 0x14000, base + 0x14004),
    }
    ordered = sorted(ranges.values())
    if any(lo < descriptor.scratch_offset or hi > descriptor.scratch_end or lo >= hi
           for lo, hi in ordered):
        raise LeaseValidationError("scratch component escapes the authenticated span")
    if any(left[1] > right[0] for left, right in zip(ordered, ordered[1:])):
        raise LeaseValidationError("scratch components overlap")
    return ranges


def validate_gart_disjoint(
        descriptor: OwnershipDescriptor, gart_offset: int, gart_size: int,
        *, bar_size: int = VRAM_BAR_SIZE) -> None:
    validate_ownership_descriptor(descriptor, bar_size=bar_size)
    if gart_size <= 0:
        raise LeaseValidationError("GART size must be positive")
    gart_end = _checked_add(gart_offset, gart_size, "GART")
    if gart_end > bar_size:
        raise LeaseValidationError("GART extends beyond the BAR")
    if descriptor.lease_offset < gart_end and gart_offset < descriptor.lease_end:
        raise LeaseValidationError("native recovery lease overlaps the live GART")


def make_pool_status(
        descriptor: OwnershipDescriptor, *, state: int,
        pool0_before: int, pool0_after: int, pool1_before: int, pool1_after: int,
        reason: int) -> PoolStatus:
    validate_ownership_descriptor(descriptor)
    fields = (
        POOL_STATUS_MAGIC, OWNERSHIP_VERSION, state,
        descriptor.lease_offset, descriptor.lease_end,
        descriptor.nonce_lo, descriptor.nonce_hi, descriptor.generation,
        pool0_before, pool0_after, pool1_before, pool1_after, reason,
    )
    status = PoolStatus(*fields, checksum_fields(*fields))
    validate_pool_status(status, descriptor)
    return status


def validate_pool_status(status: PoolStatus, descriptor: OwnershipDescriptor) -> None:
    validate_ownership_descriptor(descriptor)
    if not isinstance(status, PoolStatus):
        raise LeaseValidationError("pool status has the wrong type")
    _validate_integer_fields(status)
    if status.magic != POOL_STATUS_MAGIC or status.version != OWNERSHIP_VERSION:
        raise LeaseValidationError("pool status magic or version mismatch")
    if status.state not in (POOL_ACTIVE, POOL_INVALID):
        raise LeaseValidationError("pool status state is invalid")
    if status.checksum != checksum_fields(*status[:-1]):
        raise LeaseValidationError("pool status checksum mismatch")
    if (status.lease_offset, status.lease_end) != (
            descriptor.lease_offset, descriptor.lease_end):
        raise LeaseValidationError("pool status lease mismatch")
    if (status.nonce_lo, status.nonce_hi) != (
            descriptor.nonce_lo, descriptor.nonce_hi):
        raise LeaseValidationError("pool status nonce mismatch")
    if status.generation != descriptor.generation:
        raise LeaseValidationError("pool status generation mismatch")
    if status.reason > U32_MAX:
        raise LeaseValidationError("pool status reason exceeds the published uint32 domain")
    if status.state == POOL_ACTIVE:
        if status.reason != 0:
            raise LeaseValidationError("ACTIVE pool status has a failure reason")
        if status.pool0_before < status.pool0_after or status.pool1_before < status.pool1_after:
            raise LeaseValidationError("ACTIVE pool free-byte counters increase")
        if (status.pool0_before - status.pool0_after != LEASE_SIZE or
                status.pool1_before - status.pool1_after != LEASE_SIZE):
            raise LeaseValidationError("ACTIVE pool exclusion deltas are not exact")
    elif status.reason not in POOL_INVALID_REASONS:
        raise LeaseValidationError("INVALID pool status has an unknown failure reason")


def inspect_pool_status_readback(
        raw: bytes, descriptor: OwnershipDescriptor) -> PoolReadback:
    """Classify the optional one-shot status without weakening immutable OWNED proof.

    The guest zeroes this slot before publishing OWNED, writes the final status and checksum
    with state held at zero, then stores state last as the commit marker.  Any noncommitted
    image is therefore evidence of an interrupted optional update, not corruption of the
    separate ownership record.
    """
    validate_ownership_descriptor(descriptor)
    if len(raw) != POOL_STATUS_STRUCT.size:
        raise LeaseValidationError("pool status readback has the wrong byte length")
    if not any(raw):
        return PoolReadback(POOL_READBACK_ABSENT, None)
    fields = POOL_STATUS_STRUCT.unpack(raw)
    state = fields[2]
    if state == 0:
        return PoolReadback(POOL_READBACK_UNFINISHED, None)
    if state not in (POOL_ACTIVE, POOL_INVALID):
        raise LeaseValidationError("pool status has an invalid commit state")
    if fields[-1] != checksum_fields(*fields[:-1]):
        raise LeaseValidationError("committed pool status checksum mismatch")
    status = PoolStatus(*fields)
    validate_pool_status(status, descriptor)
    return PoolReadback(POOL_READBACK_COMMITTED, status)


def require_published_pool_readback(
        published: PoolStatus, raw: bytes,
        descriptor: OwnershipDescriptor) -> PoolStatus:
    validate_pool_status(published, descriptor)
    readback = inspect_pool_status_readback(raw, descriptor)
    if readback.kind != POOL_READBACK_COMMITTED or readback.status != published:
        raise LeaseValidationError("published pool status does not match committed readback")
    return published


def format_owned_record(descriptor: OwnershipDescriptor) -> str:
    validate_ownership_descriptor(descriptor)
    return (
        f"XH2 OWNED nonce={descriptor.nonce_lo:016x}_{descriptor.nonce_hi:016x} "
        f"gen=1 lease={_c_hex(descriptor.lease_offset)}-{_c_hex(descriptor.lease_end)} "
        f"scratch={_c_hex(descriptor.scratch_offset)}-{_c_hex(descriptor.scratch_end)} "
        f"checksum={_c_hex(descriptor.checksum)}"
    )


def format_pool_record(status: PoolStatus) -> str:
    if status.state == POOL_ACTIVE:
        state = "ACTIVE"
    elif status.state == POOL_INVALID:
        state = "INVALID"
    else:
        raise LeaseValidationError("pool status state is invalid")
    _validate_integer_fields(status)
    if status.checksum != checksum_fields(*status[:-1]):
        raise LeaseValidationError("pool status checksum mismatch")
    return (
        f"XH2 POOL state={state} nonce={status.nonce_lo:016x}_{status.nonce_hi:016x} "
        f"gen=1 lease={_c_hex(status.lease_offset)}-{_c_hex(status.lease_end)} "
        f"pool0={_c_hex(status.pool0_before)}->{_c_hex(status.pool0_after)} "
        f"pool1={_c_hex(status.pool1_before)}->{_c_hex(status.pool1_after)} "
        f"reason={status.reason} checksum={_c_hex(status.checksum)}"
    )


def _c_hex(value: int) -> str:
    _u64(value, "formatted hexadecimal field")
    return "0" if value == 0 else f"{value:#x}"


def _parse_hex(value: str) -> int:
    return _u64(int(value, 16), "record hexadecimal field")


def _parse_owned(record: str) -> OwnershipDescriptor:
    match = _OWNED_RE.fullmatch(record)
    if match is None:
        raise LeaseValidationError("malformed XH2 OWNED record")
    nonce_lo, nonce_hi = (int(match.group(1), 16), int(match.group(2), 16))
    lease_offset, lease_end, scratch_offset, scratch_end, checksum = (
        _parse_hex(value) for value in match.groups()[2:]
    )
    descriptor = OwnershipDescriptor(
        OWNERSHIP_MAGIC, OWNERSHIP_VERSION, OWNERSHIP_OWNED,
        lease_offset, lease_end, scratch_offset, scratch_end,
        nonce_lo, nonce_hi, GENERATION, checksum,
    )
    validate_ownership_descriptor(descriptor)
    return descriptor


def _parse_pool(record: str, descriptor: OwnershipDescriptor) -> PoolStatus:
    match = _POOL_RE.fullmatch(record)
    if match is None:
        raise LeaseValidationError("malformed XH2 POOL record")
    state = POOL_ACTIVE if match.group(1) == "ACTIVE" else POOL_INVALID
    nonce_lo, nonce_hi = (int(match.group(2), 16), int(match.group(3), 16))
    lease_offset, lease_end, pool0_before, pool0_after, pool1_before, pool1_after = (
        _parse_hex(value) for value in match.groups()[3:9]
    )
    reason = _u64(int(match.group(10), 10), "pool reason")
    checksum = _parse_hex(match.group(11))
    status = PoolStatus(
        POOL_STATUS_MAGIC, OWNERSHIP_VERSION, state,
        lease_offset, lease_end, nonce_lo, nonce_hi, GENERATION,
        pool0_before, pool0_after, pool1_before, pool1_after, reason, checksum,
    )
    validate_pool_status(status, descriptor)
    return status


def parse_critical_records(
        records: Iterable[str], *, expected_nonce) -> LeaseEvidence:
    descriptor = None
    pool_status = None
    owned_replays = 0
    pool_replays = 0
    wire_count = 0
    stream_bytes = 0
    for record in records:
        if not isinstance(record, str):
            raise LeaseValidationError("critical record is not text")
        record_bytes = len(record.encode("utf-8"))
        stream_bytes += record_bytes + 1
        if stream_bytes > MAX_CRITICAL_STREAM_BYTES:
            raise LeaseValidationError("canonical critical-record stream exceeds its byte bound")
        if record_bytes > MAX_RECORD_BYTES:
            raise LeaseValidationError("critical record exceeds its byte bound")
        if not record.startswith("XH2 "):
            continue
        wire_count += 1
        if wire_count > MAX_CRITICAL_RECORDS:
            raise LeaseValidationError("canonical XH2 wire-record stream exceeds its bound")
        if record.startswith("XH2 OWNED"):
            parsed = _parse_owned(record)
            validate_ownership_descriptor(parsed, expected_nonce=expected_nonce)
            if descriptor is None:
                descriptor = parsed
            elif descriptor != parsed:
                raise LeaseValidationError("conflicting XH2 ownership records")
            owned_replays += 1
        elif record.startswith("XH2 POOL"):
            if descriptor is None:
                raise LeaseValidationError("XH2 pool status precedes ownership")
            parsed = _parse_pool(record, descriptor)
            if pool_status is None:
                pool_status = parsed
            elif pool_status != parsed:
                raise LeaseValidationError("conflicting XH2 pool status records")
            pool_replays += 1
        else:
            raise LeaseValidationError("malformed XH2-prefixed record")
    if descriptor is None:
        raise LeaseValidationError("missing XH2 ownership record")
    return LeaseEvidence(descriptor, pool_status, owned_replays, pool_replays)
