# Candidate 190 incomplete-CR2 recovery independent review

Review state: final offline review of proof-only revision 2. The proof SHA-256 is
`7ca3fe481f2c869465f806d9e7a65a1b2ce22b639a5993215aea545c696b9126`.

Candidate 190 remains INVALID. The extractor's output is metadata for a
recovery-only attempt; it is neither cleanup evidence nor launch authority.

## Resolved review findings

1. The earlier `execute_once` wrapped every normal `recover` return as
   `status=complete` and exits zero. `vfio-recover.perform_recovery` deliberately
   returns schema-6 receipts with `status=incomplete` and
   `authorizes_launch=false` without raising. The wrapper must validate the
   returned receipt's exact schema, boot ID, prior run ID, helper hashes, recovery
   status, and authorization fields. This is corrected: an incomplete receipt is
   retained in a durable failed result and produces a nonzero command result.

2. Reviewed source identity was subject to a time-of-check/time-of-use split.
   `build_proof` imports the replay, recovery, and lifetime modules before hashing
   their source files. Execution rebuilds and compares the proof, then reloads
   `vfio-recover.py` before hardware access. A source change between those steps
   could make the reviewed hashes differ from code already loaded or subsequently
   executed. Execution now rebuilds the proof before and after module loading and
   refuses any source or frozen-evidence drift before recovery.

3. Frozen input members previously accepted symlinks and non-regular files. The
   proof builder now requires each expected member to be a regular non-symlink
   file before hashing it.

The coordinator's separate findings are also implemented: canonical per-boot
and per-run attempt placement; explicit current-boot equality; exact manifest
transport/readiness validation; and stricter CR2 snapshot, END, bound, and
malformed XH2/XH3 handling. Adversarial follow-up additionally found and closed
acceptance of reversed chunk order, stale snapshot order, and a chunk following
the same snapshot's END.

## Evidence checked

- The current extractor builds a proof from the frozen candidate 190 directory
  without modifying that directory.
- The extracted OWNED, ACTIVE, and VALID records are byte-identical in snapshots
  4 through 12 and pass the existing lease and lifetime validators.
- The proof retains candidate 190's `INVALID` classification and explicitly sets
  `authorizes_launch=false`.
- The execution path requires a reviewed proof hash and writes an attempt marker
  before calling recovery, but its placement and receipt-result semantics need
  the blocking corrections above.
- Thirty-two focused replay, extractor, and independent adversarial tests pass.
  The revision-2 proof is byte-identical to a fresh read-only proof rebuild;
  it retains classification `INVALID` and `authorizes_launch=false`.

No VM, VFIO, device, sudo, reset, recovery execution, or frozen-evidence write
was performed during this review.

## Recovery receipt validation

The canonical schema-6 receipt at
`run/vfio-recovery/3bca3e47-1f28-4f78-af00-5dbf76b00620/3ffc5f3dbec53665214863ed91fee0e7.json`
has SHA-256
`82560e48da2e6fb4300f5b0095e821d3da404d170108fd891ca7824aad49967a`.
On immutable fixture copies, the schema-6 validator returns no errors when
supplied candidate 190's manifest-pinned recovery-helper hashes. The reuse
validator also returns no errors when supplied that manifest and its path.

The recovery wrapper's recorded failed result is a caller defect: it invoked
`validate_reuse_receipt` without the manifest. Schema-6 dispatch derives its
required helper hashes from that manifest; omission produces
`["recovery_receipt"]` for this otherwise valid receipt. This validation failure
does not invalidate or repeat the completed cleanup.

The receipt is schema 6, `status=recovered`, and `authorizes_launch=true`, bound
to the exact candidate boot and run IDs and manifest helper hashes. Its checked
cleanup fields include two queue dequeues, zero dequeue timeouts, zero forced
inactive clears, final active count zero, matching authenticated/pre-scratch
lifetime bytes, confirmed graphics retirement and clean-ring/pipe proof, and
confirmed PSP destroy commands. The repository's full schema-6 validator covers
the remaining structural and readback invariants.
