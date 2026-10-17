# One-Run Qualification Design (policy-pinned same-boot authority)

## Scope

The coordinator refuses generic same-boot reuse for lease-schema launches: "a
reviewed finite policy must select and bind one exact launch". The candidate 179
helper implemented that for one boot with every identity as a source constant.
This design generalizes it: `tools/one-run-qualification.py` keeps the same
validation, gate, and reservation rules, but every identity is a field of the
immutable policy file, which the operator binds by supplying its SHA-256.

A policy authorizes exactly one launch on one host boot after one validated
recovery receipt. It never activates a launch, never retries, and cannot be
replayed: its ledger preimage digest, its unused run and recovery identities,
and the absent output path all change once the launch is reserved.

## Pinned inputs

The policy pins: boot ID; the exact current ledger bytes; the prior run and its
recovery identity; both copies of the schema-6 receipt (the canonical
`run/vfio-recovery/<boot>/<prior>.json` and a second copy, optionally nested
under a member of another evidence file, which must be equal); this design; the
helper and `tools/experiment.py`; the recovery helper set for the selected lease
schema; the experiment card, its identity and candidate version and directory;
the sealed manifest path, digest and run ID; the absent output path; the
launch-count transition (`from`, `to`, `additional`, normally within the base
cap so `additional` is zero); the 180-second VM and 45-second probe limits; and
`automatic_extension=false`, `automatic_retry=false`, plus a purpose string.

The separate activation pins the policy digest, ledger preimage, manifest
digest, run ID, prior run, recovery identity, both receipt digests, and declares
one stage with no retry.

## Manifest contract

The manifest must be the exact pinned bytes and carry the policy's boot, GPU
mode, candidate directory, experiment, lease schema (schema 3 requires CR2
transport), the card's critical-replay tolerance, current recovery helper
digests, a clean verified source and boot disk, the functional baseline
switches, the card's `functional_boot_arguments`, the requested diagnostic, and
numeric `rgpurnlo`/`rgpurnhi` equal to the little-endian halves of its run ID.
Duplicate or retired `rgpu*` arguments are refused.

## Authorization, gate and reservation

`authorize(...)` is read-only and returns an authorization object holding every
raw immutable input. `build_reservation(...)` rechecks all raw bytes, the live
host, VFIO, identity and journal gates supplied by the coordinator, the
receipt's kernel cursor continuity, and the unchanged ledger, then returns a
prospective ledger with exactly one appended row carrying the policy and
activation digests. When `additional_launches` is nonzero it also appends one
cap revision; otherwise the base cap is untouched. The coordinator performs the
locked atomic replacement.

## Tests

`tests/test_one_run_qualification.py` builds a concrete policy and activation in
a temporary VM tree from a synthetic schema-2 ledger and receipt, and proves
read-only authorization, the single append, refusal of manifest, nonce, helper,
receipt and ledger drift, refusal of an incomplete live gate, and absence of any
write on a rejected authorization.
