# Two-run same-boot warm qualification

Status: **conditional design only**. This document does not authorize implementation, build,
staging, authority creation, ledger reservation, VFIO exposure, or a VM launch. The current
schema-3 ledger remains exhausted at 4/4. Every artifact and each activation described below needs
separate exact-byte coordinator and independent review before use.

## Decision and limit

Conditionally permit one finite policy revision from four to six launches on the current boot for
M7 lifecycle qualification. Reuse one byte-identical candidate-178 binary, staged configuration,
boot-argument set, experiment card, and Metal probe in two separately admitted runs, `178-A` and
`178-B`. Each run has its own precreated manifest and unique run ID.

Both A and B retain a maximum VM exposure of **180 seconds**. The unchanged probe has its own
**45-second** budget in each run. There is no automatic continuation or retry. The absolute
terminal ceiling is **6** for this plan; no receipt or outcome can admit a seventh launch.

The revision is acceptable in principle because candidates 176 and 177 both completed normal
schema-6 physical recovery, both unchanged receipts validate, candidate 177 successfully
reinitialized after candidate 176, and neither interval produced a host, IOMMU, or reset fault.
Candidate 178 extends observation at the memory-map boundary without changing native GPU routes,
reset behavior, functional boot arguments, or workload. This evidence narrows the uncertainty that
motivated the earlier ceiling, but it does not prove Metal execution, desktop usability, native
teardown, routine reuse, or safety beyond this bounded sequence.

## Preserved history and predeclared artifacts

The implementation must preserve byte-for-byte and in order:

- all four existing launch rows and the original 3-to-4 cap-revision record;
- the immutable candidate-176 recovery evidence, including canonical receipt SHA-256
  `4e6c1519f18c0bb60efeb816045eb3aedf6231a0ef8746a530c768996e7e6676`;
- the immutable candidate-177 recovery evidence, including full recovery SHA-256
  `09aa1cfd2433b587d37fa45bc23c75ade7757edbae19711af3c83877a980ce4b` and canonical receipt
  SHA-256 `e2fcf3ba93d88b0e19ac5a71260029ead38b501cf1dc5b2adce0bddd6482c446`;
- the complete four-row ledger preimage SHA-256
  `e319d5d954e063a7142bd4873a597cc3bb8ccb9b29d577511eaaf92f924fd496`;
- every historical manifest, authority, receipt, evidence file, and checksum without rewriting or
  reinterpretation.

Before A can be reserved, both A and B manifests must already exist and bind distinct run IDs to
the same exact candidate-178 source, commit/tree, binary, build, Info.plist, staged image, config,
boot disk, experiment card, boot arguments, probe, recovery producer/consumer, harness, boot ID,
180-second VM limit, and 45-second probe budget. The candidate-178 delta must remain observation
only. Any difference in those shared artifact identities between A and B is a veto.

## Finite ledger revision

A separately reviewed write-once policy record may authorize exactly one append-only transition
from `max_launches=4` to `max_launches=6` with `additional_launches=2`. It must bind the current boot,
the exact four-row ledger preimage, the full preserved history above, the final tool source hashes,
the single candidate-178 artifact set, and both exact manifests and run IDs. It must declare M7
warm-recovery qualification as its sole purpose and `automatic_extension=false`.

Reservation preserves every prior row and revision, appends the 4-to-6 revision, and appends only
the launch being admitted. Row 5 records A's manifest/run ID, the policy and A-activation hashes,
ordinal A, and its unique consumption of candidate 177's recovery ID. Row 6 may be appended only
after the separate B activation below and records the corresponding B identities and unique
consumption of A's recovery ID. A reservation consumes its slot even if macOS or the probe never
starts. There is no lease outside the ledger, reused run ID, replacement row, generic cap API, or
automatic path past six.

## Separate activation reviews

Run A requires a write-once activation whose exact bytes are independently and coordinately
approved immediately before reservation. It binds the policy record, exact four-row ledger,
candidate-177 raw and canonical validating schema-6 evidence, both predeclared manifests, and the
shared candidate-178 artifacts. A then uniquely consumes candidate 177's authorizing receipt while
row 5 is appended atomically.

Run B receives no advance activation. After A finishes, a new write-once B activation may be
prepared only if A passed every lifecycle and host gate. It must bind A's immutable full recovery
result and canonical schema-6 receipt, their successful validation under the exact reviewed
consumer, the exact five-row ledger preimage, the unchanged candidate-178 artifacts, and the
already-bound B manifest. Independent and coordinator review must approve those exact bytes before
B reserves row 6 and uniquely consumes A's receipt.

Failure or missing evidence from A permanently closes B under this policy. A previously reviewed
policy record, manifest, or unused second slot cannot override that closure.

## Admission and runtime gates

Immediately before each reservation, fail closed unless all existing gates pass:

- the host boot ID, PCI function, parent and exact sibling identities match the reviewed evidence;
- PCI power is D0, runtime and enable state are expected, bus mastering is off, `reset_method` is
  empty, and the expected VFIO binding has no holder;
- no QEMU, recovery process, launch unit, pending reservation, or VM exists;
- watchdog, NMI watchdog, and hard-lockup panic are all verified as `1`, and the accepted
  `efi_pstore`/persistent one-second journal capture gate is ready; unread `pstore_files=None` stays
  explicitly unknown and does not invite a privileged probe;
- the journal scan begins at the prior receipt's immutable ending cursor, contains no intervening
  GPU, IOMMU, host fault, or reset, and seeds the continuous monitor with its returned cursor;
- source, build, boot disk, staged image, config, card, manifest, probe, boot arguments, recovery
  tools, and all authority hashes match their reviewed bytes;
- the ordinary readiness, exact probe identity, 180-second VM exposure, and 45-second probe budget
  remain intact.

Each run uses the normal experiment path, prepared probe, automatic guest shutdown, and built-in
schema-6 recovery. It permits no manual MMIO, extra guest command, reset, rebind, extra probe,
restart, or retry. Native lifecycle observations remain evidence; independently validated physical
retirement remains the reuse authority when native teardown cannot complete.

Any startup, capture, probe-identity, supervision, shutdown, recovery, receipt-validation, or host
poststate failure closes the remaining plan. Forced ACTIVE clear, reset escalation, manual recovery,
nonzero final protected state, host/IOMMU/reset fault, persistent D-state task, hash drift, malformed
or raced authority, or missing durable interval are unconditional vetoes. The expected unchanged
Metal status 5 / `e00002bd` / zero-submit result is diagnostic evidence and is not by itself an M7
lifecycle veto.

## Qualification accounting and interpretation

The accepted transition count is exact:

1. candidate-176 cleanup to candidate-177 startup: transition 1;
2. candidate-177 cleanup to candidate-178-A startup: transition 2;
3. candidate-178-A cleanup to candidate-178-B startup: transition 3.

Candidate-178-B must still finish normal schema-6 cleanup to close the bounded sequence. Its final
receipt is evidence only under this plan because the terminal six-launch ceiling forbids consuming
it for another launch.

Three successful transitions would satisfy the same-boot M7 cleanup-to-restart evidence requested
by the roadmap. They would not satisfy M8's requirement for independently initialized host boots,
prove Metal command execution or desktop rendering, explain the historical host-hang mechanism, or
authorize unattended no-reboot automation. Any failed transition remains evidence and closes this
qualification attempt without uniquely attributing the cause to the preceding recovery.
