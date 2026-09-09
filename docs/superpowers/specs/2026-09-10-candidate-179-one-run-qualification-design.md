# Candidate 179 One-Run Qualification Design

## Scope

Candidate 179 gets one explicitly reviewed GPU launch on the current host boot. The
authority is independent of the completed candidate-178 two-run policy. It does not
activate a launch, retry a failed launch, or create another authority. The existing
six launch rows, two cap revisions, candidate-178 artifacts, and recovery receipts
remain immutable inputs.

The offline implementation consists of a new
`tools/candidate179-qualification.py` validator and focused tests. Integration into
`tools/experiment.py`, creation of concrete policy and activation files, and any live
ledger update are separate reviewed work.

## Pinned historical preimage

The only accepted predecessor is the terminal candidate-178 ledger for boot
`5d6f45d0-4384-4340-b819-7751bc26ebb3`. Its exact bytes have SHA-256
`8105707580a4d89b2e883be90730e1e84ad32f42e69a0310264f3e5431f0260f`, schema 4,
`initial_max_launches=3`, `max_launches=6`, six launch rows, and two cap revisions.
The validator compares the complete parsed ledger with a frozen repository copy as
well as checking the byte digest.

The predecessor is candidate 178-B run
`4a45f4a4c1dd49c69fab2dc37e2e4898`, recovery
`8fb71c4acf944fa3b6ee545dfb58a448`. The canonical recovery receipt digest is
`fc1c08c831cd0b95862ae397f0ac60f09e312bba6316bac67c9cceae609e956c`; the run-copy
digest is `ea9f41341b5d0f5ff08f7ef72ee44bd052c2a823ebeaae267c57798b5dd789d5`.
Both JSON values must be identical, schema 6, recovered, authorizing, bound to the
same boot and prior run, and accepted by the historical schema-6 receipt validator.

## Concrete policy and activation

The policy is an immutable JSON object under the VM `run` directory. Its caller
supplies the reviewed SHA-256. Exact fields bind the terminal ledger digest, prior
run and recovery identities, both prior receipt digests, this design, the new helper,
`experiment.py`, all three recovery helpers, the candidate-179 experiment card, one
preselected manifest path/digest/run ID, one output path, and the transition
`6 -> 7` with `additional_launches=1`. It declares `automatic_extension=false`,
`automatic_retry=false`, a 180-second VM limit, and a 45-second probe limit.

The manifest must be the exact policy-pinned bytes and contain GPU candidate
`1.0.179`, experiment `metal-012`, directory `run/candidate-179`, schema-2 recovery,
the exact three-helper digest map, and the same experiment card as its `spec`. Its
numeric `rgpurnlo` and `rgpurnhi` boot arguments must equal the little-endian halves
of its preselected run ID. Its repeat policy must explicitly allow one reviewed run
and no automatic retry.

The separate activation object is also addressed by a caller-supplied reviewed
SHA-256. It binds the policy, manifest, ledger preimage, candidate run ID, predecessor
run and recovery, and both prior receipt digests. It declares one stage and no retry.
No wildcard, optional candidate identity, alternate predecessor, or automatic
extension is accepted.

## Authorization and reservation flow

`authorize(...)` performs read-only validation and returns an authorization object
containing every raw immutable input. It rejects unsafe or duplicate manifest/output
paths, any hash or shape mismatch, a reused run or recovery ID, and any failure from
the injected historical receipt validator. It does not inspect hardware or modify
the ledger. The output path must still be absent. The coordinator repeats this check
under its experiment and media locks before creating the path with exclusive-create
semantics.

Immediately before reservation, the experiment coordinator must independently
recheck current source and disk identity, the schema-2 nonce boot arguments and
recovery-helper digests, host boot identity, VFIO binding, PCI bus mastering off,
disabled reset methods, sleep inhibitor, watchdogs, persistent capture, no active VM,
no pending launch, and a fault-free journal interval starting at the 178-B receipt's
terminal cursor. Those observations form an exact gate object.

`build_reservation(...)` rechecks all authorization bytes, the candidate identity
values carried by the gate, the journal boundary, empty active/pending sets, and the
unchanged terminal ledger. It also requires the newly owned output to contain exactly
the byte-identical pinned `manifest.json` and the current-boot `host-before.json`, with
no other entries. It returns a prospective ledger value. The caller remains
responsible for the existing locked atomic replacement. The value preserves launch
rows 1 through 6 and cap revisions 1 and 2 exactly, appends one schema-5 revision
from 6 to 7, appends one candidate-179 row, retains `initial_max_launches=3`, and sets
`max_launches=7`.

After row 7 exists, the policy cannot be replayed because its required ledger bytes,
row count, and unused run/recovery identities no longer match. Cleanup may create a
receipt for candidate 179, but no eighth launch is authorized by this design.

## Tests

Focused tests construct concrete policy and activation files in a temporary VM tree.
They prove read-only authorization, exact preservation of the six-row/two-revision
prefix, the single 6-to-7 append, rejection of stale ledger or receipt bytes, rejection
of manifest nonce/helper drift, replay refusal, malformed gate refusal, and absence of
any automatic retry or extension route. Existing candidate-178 qualification tests
remain unchanged and must continue to pass.
