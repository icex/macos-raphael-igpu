# Candidate 184 prelaunch-refusal follow-up plan

Date: 2026-09-10

## Proven boundary

Candidate 184 run `f32c2266a96dd7e3c91a46b85ac7878d` was refused before
ledger reservation and before QEMU. Its frozen verdict records
`one-run qualification refused: harness_sha256,launch_options`; both serial
captures are empty. The boot ledger remains byte-identical at SHA-256
`2f715f2067a57cf502ae61d64a745121fd385556b055ad36f04480fadf000b83`,
one launch used out of the unchanged ceiling of three. This is not a GPU cycle
and creates no recovery event.

Preserve without alteration:

- candidate-184 worktree commit, build, distribution, staging record, bootdisk
  backups, manifest, and output `run/metal-017-184`;
- policy SHA-256
  `0152bb1319021d37125b33c7f379988d8938a24ba9fd3953246758cd9ce2b7bd`;
- activation SHA-256
  `65311f882058257cf52e5695c6a6fbf57293cdab22e4114485d5bcd7f16e79fc`.

Although the authority was never consumed by a reservation, it cannot authorize
another attempt: it binds the frozen candidate-184 manifest, run ID and output,
and its output-absent predicate is now false.

## Smallest supported fresh sequence

1. **Finish and review the host-only gate fix.** Pass the manifest's exact
   `launch_options` into the final reservation-time `current_identity` call,
   matching preparation and the later running-identity check. Add the narrow
   regression that reaches the real final reservation gate with
   `GENERIC_GRAPHICS=off` and proves the manifest harness map, including
   `vm-entry.sh`, is compared. Run focused tests and one final Python/static
   check. Do not rerun the tiny-guest COM2 qualification because UART,
   collector, formatter, and transport code did not change.

2. **Create one clean successor identity.** Commit the reviewed fix as a fresh
   source identity and use candidate `1.0.185` with a new card ID such as
   `metal-018`. Preserve the metal-017 diagnostic, COM2, schema-3 recovery,
   `GENERIC_GRAPHICS=off`, 180-second VM cap and 45-second probe unchanged.
   Make only the mechanical version/card additions required by the existing
   candidate-specific staging validator and metadata tests. Candidate 184 paths
   are immutable, so reusing its number or run ID is unsupported.

3. **Build and verify candidate 185 from its clean worktree.** The kext driver
   source may remain byte-identical, but the build identities bind the whole
   source commit and candidate version, and Info.plist must identify 1.0.185.
   Therefore do not relabel or reuse the candidate-184 build. Use new
   `candidate-185`, distribution, build-log, and build-identities paths and the
   same pinned KDK and Docker image. Verify the artifact set through the existing
   staging verifier.

4. **Deploy only the changed reviewed runtime source.** The final-gate fix is in
   worktree `experiment.py`, which runs from the complete worktree and is not a
   standalone live-VM deployment. Redeploy a runtime file only if its reviewed
   bytes changed; otherwise verify the existing four deployed runtime hashes.

5. **Stage candidate 185 once.** Run the existing candidate staging transaction
   from the clean candidate-185 worktree with a new generated run ID. It may use
   the currently published candidate-184 disk as its preimage, but must create
   distinct candidate-185 backups and staging evidence. Verify the fresh numeric
   nonce, bootdisk, card, COM2 and no-generic launch options before preparing a
   new manifest and a new absent output path `run/metal-018-185`.

6. **Add the smallest necessary authority namespace fix.** There is no existing
   supported API for a second one-run policy on the same boot: creation always
   opens the single fixed `<boot>/policy.json` with `O_EXCL`. Do not rename,
   delete, replace, or edit candidate 184's live policy or activation merely to
   clear that guard. Change the helper so newly created policies use the already
   bound run ID in an exclusive run-scoped filename such as
   `<boot>/<run-id>.policy.json`; keep the activation at
   `<boot>/<run-id>.json`. Authorization must select the exact run-scoped policy
   for new activations while retaining read compatibility with the existing
   legacy `<boot>/policy.json` authority. It must still verify the caller's exact
   policy hash, activation's policy hash, manifest/run/output binding, ledger
   preimage, helper hashes and every current gate. Add focused regressions for
   two distinct same-boot policy files, legacy candidate-184 authorization, and
   refusal to overwrite either run-scoped file. This is a filename namespace
   correction, not a reusable budget or retry mechanism.

7. **Create fresh zero-extension authority.** Make a new write-exclusive
   candidate-185 authority-input copy of the archived canonical GUI-183 recovery
   receipt and verify it and the live canonical receipt still have SHA-256
   `d2e2fad9244033002bdd3643e72049e9b4f4b858080aa8fa0cadd91d095ad367`.
   Run the existing `one-run-qualification.py create` once for the new card,
   manifest, run and output. Require `from_max_launches=3`,
   `to_max_launches=3`, `additional_launches=0`, `automatic_retry=false`,
   180/45-second caps, the unchanged ledger preimage, prior run
   `4661e574bbd5695d00176d85bfa87325`, and recovery
   `8447b84dca024433a6754a53464e9c14`.

8. **Repeat independent read-only admission review.** Validate the new authority
   through `one-run-qualification.authorize` using the candidate worktree's
   `experiment.py` hook wiring. Confirm the old authority and candidate-184
   evidence remain byte-identical, the new output is absent, ledger remains one
   of three, and all normal schema-3 warm-host gates still pass. Only then may a
   coordinator separately authorize the one new launch command. Record the
   candidate-184 authority as superseded by the fresh run in review metadata,
   while leaving its original live and archived bytes untouched.

No recovery receipt, budget extension, generic authorization mechanism, or
automatic retry is needed. The existing numerical capacity remains available,
but it does not itself authorize the successor attempt.

## Scope of this report

This was read-only planning apart from this report. It did not modify source,
VM files, staged media, artifacts, policy, activation, ledger, device state, or
the frozen candidate-184 output, and it did not invoke QEMU, a VM, reservation,
or recovery.

## Independent source review result

The successor source changes are cleared for commit and the later clean-worktree
build/staging sequence. No blocker remains in the reviewed source.

The locked candidate and warm reservation gates now pass the manifest run ID,
recovery lease schema, and exact launch-options object into `current_identity`.
The real one-run adapter regression observes the no-generic options at both
identity reads, and the mismatch regression proves the ledger replacement is not
called.

New policies use `<boot>/<run-id>.policy.json`. Authorization selects that exact
scoped path when present and falls back to legacy `<boot>/policy.json` only when
the scoped path is absent. Thus a malformed or wrong-hash scoped policy cannot
downgrade to the legacy policy. Reservation selects the path again and compares
it with the authorized path and bytes, catching a scoped-file creation/removal
race. Creation remains write-exclusive, activations remain run-scoped, two
authorities sharing a ledger preimage cannot both reserve, and all existing
manifest, output, receipt, helper, ledger-cap and retry checks remain in place.

The candidate-185 card/metadata/staging mapping preserves the candidate-184
diagnostic and safety contract, records that 184 never reached QEMU or consumed
a reservation, and uses the actual GUI-183 run as its immediate GPU baseline.

Final validation passed 133 focused tests and 624 full Python tests with one
explicit existing skip. `git diff --check`, Python compilation and shell syntax
also passed. The live candidate-184 policy, activation and ledger hashes remained
respectively `0152bb1319021d37125b33c7f379988d8938a24ba9fd3953246758cd9ce2b7bd`,
`65311f882058257cf52e5695c6a6fbf57293cdab22e4114485d5bcd7f16e79fc`,
and `2f715f2067a57cf502ae61d64a745121fd385556b055ad36f04480fadf000b83`.
The 132-second COM2 qualification was not repeated because its transport,
collector, formatter and UART topology sources did not change.
