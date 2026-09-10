#!/usr/bin/env python3
"""Pure validation for the schema-3 persistent recovery lifetime marker."""

import importlib.util
from pathlib import Path
import struct
from typing import NamedTuple, Optional


def _load_recovery_lease_v2():
    path = Path(__file__).with_name("recovery_lease_v2.py")
    spec = importlib.util.spec_from_file_location("recovery_lease_v2_lifetime", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RECOVERY_LEASE_V2 = _load_recovery_lease_v2()

U64_MAX = (1 << 64) - 1
LIFETIME_OFFSET = 0x200
LIFETIME_MAGIC = int.from_bytes(b"RGPUKLM3", "little")
LIFETIME_VERSION = 3
STATE_VALID = int.from_bytes(b"VALD", "little")
STATE_ABORTING = int.from_bytes(b"ABTG", "little")
STATE_ABORT = int.from_bytes(b"ABRT", "little")
CHECKSUM_DOMAIN = 0x6A09E667F3BCC909

REASON_DUPLICATE_READY = 1
REASON_VMM_RANGE = 2
REASON_POOL_OWNER = 3
REASON_DUPLICATE_POOL = 4
ABORT_REASONS = frozenset((
    REASON_DUPLICATE_READY, REASON_VMM_RANGE,
    REASON_POOL_OWNER, REASON_DUPLICATE_POOL,
))

LIFETIME_STRUCT = struct.Struct("<QIIQQQQQQQQQ")
STATE_WORD = 3

READBACK_ABSENT = "absent"
READBACK_UNFINISHED = "unfinished"
READBACK_VALID = "valid"
READBACK_ABORTING = "aborting"
READBACK_ABORT = "abort"


class LifetimeValidationError(ValueError):
    pass


class LifetimeStatus(NamedTuple):
    magic: int
    version: int
    state: int
    lease_offset: int
    lease_end: int
    nonce_lo: int
    nonce_hi: int
    generation: int
    ownership_checksum: int
    pool_checksum: int
    reason: int
    checksum: int

    def pack(self) -> bytes:
        _validate_self(self)
        return LIFETIME_STRUCT.pack(*self)


class LifetimeReadback(NamedTuple):
    kind: str
    status: Optional[LifetimeStatus]


def _u64(value, name):
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= U64_MAX:
        raise LifetimeValidationError(f"{name} is outside the unsigned 64-bit domain")
    return value


def checksum_fields(*fields):
    value = CHECKSUM_DOMAIN
    for index, field in enumerate(fields):
        value ^= _u64(field, f"checksum field {index}")
    return value


def _binding(ownership_raw, pool_raw):
    if not isinstance(ownership_raw, bytes) or not isinstance(pool_raw, bytes):
        raise LifetimeValidationError("lifetime binding records must be bytes")
    try:
        owned = RECOVERY_LEASE_V2.OwnershipDescriptor.unpack(ownership_raw)
        pool = RECOVERY_LEASE_V2.PoolStatus.unpack(pool_raw)
        RECOVERY_LEASE_V2.validate_pool_status(pool, owned)
    except RECOVERY_LEASE_V2.LeaseValidationError as error:
        raise LifetimeValidationError("invalid lifetime binding: " + str(error)) from error
    if pool.state != RECOVERY_LEASE_V2.POOL_ACTIVE:
        raise LifetimeValidationError("lifetime marker requires an ACTIVE pool status")
    return (
        owned.lease_offset, owned.lease_end, owned.nonce_lo, owned.nonce_hi,
        owned.generation, owned.checksum, pool.checksum,
    )


def _validate_self(status):
    if not isinstance(status, LifetimeStatus):
        raise LifetimeValidationError("lifetime marker has the wrong type")
    for index, value in enumerate(status):
        _u64(value, f"lifetime field {index}")
    if status.magic != LIFETIME_MAGIC or status.version != LIFETIME_VERSION:
        raise LifetimeValidationError("lifetime marker magic or version mismatch")
    if status.state == STATE_VALID:
        if status.reason != 0:
            raise LifetimeValidationError("VALID lifetime marker has an abort reason")
    elif status.state == STATE_ABORT:
        if status.reason not in ABORT_REASONS:
            raise LifetimeValidationError("ABORT lifetime marker has an unknown reason")
    else:
        raise LifetimeValidationError("lifetime marker has a noncommitted state")
    if status.checksum != checksum_fields(*status[:-1]):
        raise LifetimeValidationError("lifetime marker checksum mismatch")


def make_valid_marker(ownership_raw, pool_raw):
    binding = _binding(ownership_raw, pool_raw)
    fields = (LIFETIME_MAGIC, LIFETIME_VERSION, STATE_VALID, *binding, 0)
    return LifetimeStatus(*fields, checksum_fields(*fields))


def make_abort_marker(valid, reason):
    _validate_self(valid)
    if valid.state != STATE_VALID:
        raise LifetimeValidationError("ABORT must derive from a VALID lifetime marker")
    if reason not in ABORT_REASONS:
        raise LifetimeValidationError("ABORT lifetime marker has an unknown reason")
    fields = (*valid[:2], STATE_ABORT, *valid[3:-2], reason)
    return LifetimeStatus(*fields, checksum_fields(*fields))


def validate_marker(status, ownership_raw, pool_raw, *, require_valid=False):
    _validate_self(status)
    if status[3:10] != _binding(ownership_raw, pool_raw):
        raise LifetimeValidationError("lifetime marker binding mismatch")
    if require_valid and status.state != STATE_VALID:
        raise LifetimeValidationError("lifetime marker is ABORT")
    return status


def inspect_readback(raw, ownership_raw, pool_raw):
    if not isinstance(raw, bytes) or len(raw) != LIFETIME_STRUCT.size:
        raise LifetimeValidationError("lifetime readback has the wrong byte length")
    if not any(raw):
        return LifetimeReadback(READBACK_ABSENT, None)
    fields = LIFETIME_STRUCT.unpack(raw)
    state = fields[2]
    if state == 0:
        return LifetimeReadback(READBACK_UNFINISHED, None)
    if state == STATE_ABORTING:
        return LifetimeReadback(READBACK_ABORTING, None)
    if state not in (STATE_VALID, STATE_ABORT):
        raise LifetimeValidationError("lifetime readback has an invalid commit state")
    status = LifetimeStatus(*fields)
    validate_marker(status, ownership_raw, pool_raw)
    return LifetimeReadback(
        READBACK_VALID if state == STATE_VALID else READBACK_ABORT, status)


def require_valid_readback(raw, ownership_raw, pool_raw):
    readback = inspect_readback(raw, ownership_raw, pool_raw)
    if readback.kind != READBACK_VALID:
        if readback.kind == READBACK_ABORT:
            raise LifetimeValidationError("lifetime marker is ABORT")
        raise LifetimeValidationError("lifetime marker is not committed VALID")
    return readback.status


def _words(status):
    return struct.unpack("<" + "I" * (LIFETIME_STRUCT.size // 4), status.pack())


def publish_valid(status, write, read, fence):
    validate_state = status.state == STATE_VALID
    if not validate_state:
        raise LifetimeValidationError("VALID publication requires a VALID marker")
    words = _words(status)
    if read(STATE_WORD) != 0:
        return False
    write(STATE_WORD, 0)
    fence()
    if read(STATE_WORD) != 0:
        return False
    for index, value in enumerate(words):
        if index != STATE_WORD:
            write(index, value)
    fence()
    write(STATE_WORD, words[STATE_WORD])
    fence()
    return all(read(index) == value for index, value in enumerate(words))


def publish_abort(status, write, read, fence):
    _validate_self(status)
    if status.state != STATE_ABORT:
        raise LifetimeValidationError("ABORT publication requires an ABORT marker")
    current = [read(index) for index in range(LIFETIME_STRUCT.size // 4)]
    try:
        prior = LifetimeStatus(*LIFETIME_STRUCT.unpack(
            struct.pack("<" + "I" * len(current), *current)))
        _validate_self(prior)
    except LifetimeValidationError:
        return False
    if prior.state != STATE_VALID or prior[3:10] != status[3:10]:
        return False
    words = _words(status)
    write(STATE_WORD, STATE_ABORTING)
    fence()
    if read(STATE_WORD) != STATE_ABORTING:
        return False
    for index, value in enumerate(words):
        if index != STATE_WORD:
            write(index, value)
    fence()
    write(STATE_WORD, words[STATE_WORD])
    fence()
    return all(read(index) == value for index, value in enumerate(words))
