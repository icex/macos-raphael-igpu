# Candidate 188 recovery and next debugger admission

## Recovery validation

Candidate 188 remains `INCONCLUSIVE`; the recovery receipt does not change the
run verdict. The only classified evidence is capture loss from an incomplete
CR2 transport line. This was actual GPU cycle 10 overall and cycle 2 since the
post-186 review.

The run-local receipt is
`/home/bogdan/macos-vm/run/metal-021-188-continuation-output/recovery.json`
(SHA-256 `30b59aeca030470461820f0d091e3b7cc51dd28f50ad17510a810e4b9433f061`).
The canonical receipt is
`/home/bogdan/macos-vm/run/vfio-recovery/3bca3e47-1f28-4f78-af00-5dbf76b00620/cb1d0aadd8186205d867a23fe175c336.json`
(SHA-256 `1f960f9a3e508959cf53604bb15c834a42552bd9e977ec956276188c8aad82aa`).
Their JSON values are exactly equal; only serialization differs. Direct calls
from clean worktree commit `128b5884b2ad38393b0048dfb83289252a8637cf` to
`validate_recovery_receipt_v6`, with the manifest's exact schema-3 helper
hashes, and to `validate_reuse_receipt` both returned an empty error list.
The receipt is schema 6, `recovered`, and `authorizes_launch: true`, with recovery
ID `a64fe2a14264444184d6fafe219ddef1` and a same-boot ending journal cursor.

This establishes cleanup eligibility only. It does not make the invalid capture
valid, establish the missed debugger values, prove Metal, or itself reserve or
authorize another launch. Generic same-boot reuse remains refused without a
reviewed finite one-run policy and activation.

## Regression against candidate 187

Candidate 188 retained candidate 187's functional behavior: authenticated
headless PCI placement and the native KIQ/engine path progressed, followed by
the same VMID1 missing-page-table boundary described for 187. It did not produce
a Metal result. Candidate 188 added a real debugger entry breakpoint hit, but
the capture cannot establish the intended source/destination correlation
because the debugger selected an unproven CPU/thread pairing. The CR2 stream
also ended with an incomplete line, so the authoritative classification remains
`INCONCLUSIVE` rather than inheriting conclusions from otherwise readable
serial data. Recovery improved from 187's missing receipt to a valid schema-6
receipt, which permits consideration of a separately authorized same-boot run;
it is not functional progress on the VMID1 fault.

Frozen primary hashes for candidate 188 are: serial
`d462c86ea254d4cb81326a5cb46050f1a350643fe3fe426e56740dc661eed5ab`,
critical `f148d60dab620481fa4248bd5c2f77fa7ba58f33c83b5bd96c75a273881d6bf7`,
events `1fc1a7cfd450e5af3127505bf7e382b26bb4069a73c365e28245f43318c41158`,
and verdict `01987196b14c47057672b690715ca7e01cf9dc9a5ffd00d5aaa32ad4b5bdaacc`.
The GDB transcript hash is
`c68ee25233af98ec41aa8b28588a478c8fdefc685f69bbe60ed79a8ef1eabbdb`.

## Minimal next-candidate strategy

Use the existing run-scoped `one-run-qualification.py` policy and activation
with `additional_launches: 0`. The current boot ledger has one launch against
`max_launches: 3`, so the policy's `from_max_launches` and `to_max_launches`
both remain 3. This grants exactly one unused run ID and consumes the validated
recovery ID once; it does not extend the ceiling, create a rolling retry, or
automatically launch.

The next candidate should change only the debugger/coordinator tooling needed
to prove CPU/thread ownership at the breakpoint. Reuse candidate 188's exact
driver binary, Info.plist, build ID, source digest, retained dSYM/debug source,
ROM, image, KDK identities, and functional boot arguments. No driver rebuild is
justified. A fresh run ID is still required, so its two recovery nonce boot
arguments and the corresponding verified OpenCore media must be updated
transactionally; this is a run-identity reseal, not a new driver build. The new
experiment card and manifest must pin the corrected debugger procedure/tool and
retain the 180-second VM and 45-second probe limits.

After the corrected debugger code is committed and reviewed, the safe offline
sequence is:

1. Create a clean worktree at that commit and verify the debugger fix with
   GPU-less tests.
2. Generate a fresh 32-hex run ID, reseal only its nonce-bearing boot arguments,
   and prepare a new manifest that refers to the unchanged candidate-188
   artifact and newly pinned debugger/coordinator identities.
3. Create a run-scoped one-run policy using this receipt as both the canonical
   value and the run-local member, with their distinct raw hashes pinned,
   `additional_launches: 0`, one exact output path, `automatic_retry: false`,
   and an explicit CPU/thread-correlation purpose.
4. Create and separately review the `ONLY` activation hash. Run the read-only
   authority validator and live host/journal gates. Do not reserve the ledger or
   launch during review.
5. Only after explicit authorization, invoke `experiment.py run` with both
   reviewed one-run hashes. The locked coordinator then appends exactly one
   second ledger row and applies all ordinary capture, deadline, shutdown, and
   recovery gates.

Any debugger-only preparation must not use the valid receipt to reinterpret
candidate 188, bypass capture validity, reuse its run ID, rewrite its existing
ledger row, or grant more than the one remaining explicitly reviewed launch.
