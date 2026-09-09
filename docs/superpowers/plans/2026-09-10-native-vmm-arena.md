# Native VMM arena and recovery ownership implementation plan

> For agentic workers: use subagent-driven-development for the assigned implementation
> and tests. The coordinator reviews code and evidence. No hardware run follows from
> this document alone; existing finite experiment and host gates remain mandatory.

**Goal:** restore native VMM arena allocation and measure real Metal execution while
preserving exclusive host recovery scratch ownership.

**Architecture:** reserve a small native hardware allocation before VMM initialization,
then exclude precisely that range from both software pools after their sole native
initialization. Host recovery derives its scratch addresses from immutable, launch-bound
ownership metadata. Keep the current 256/256 MiB compatibility setting and early paging
channel setup; remove the 240 MiB cap and premature software-pool initialization.

**Tech stack:** C++ Lilu plugin, exact macOS 24G830 AMD binaries, Python host harness,
mocked VFIO tests, existing automated Metal probe.

**Spec:** root `status.md`, `AGENTS.md`, native report reviews, and `report-astra.md`.

## Constraints

- No main merge/push; no host reset, driver cycle, virgin passthrough, sudo probe,
  or boot configuration change. Keep sleep inhibition and crash capture active.
- Preserve all historical evidence, including the existing 6/6 boot ledger.
- No GPU run until the adversarial report and guest/host integration are reviewed.
- Pure unit tests do not count as GPU cycles or evidence of Metal acceleration.
- Do not reduce Metal correctness thresholds to make the candidate pass.

## Completed investigation

- [x] Reconstruct at least four failed cycles: 176, 177, 178-A, 178-B.
- [x] Archive the original Astra report with matching SHA-256 and dispatch Astra xhigh.
- [x] Verify the native three-argument allocator ABI is not an inverted interval.
- [x] Establish the historical VMM interval `[0x0b708000,0x0fb08000)` overlaps the
  fixed recovery scratch and extends beyond the 240 MiB cap.
- [x] Trace native VMM arena request through `withPhysicalAddress` to software reserve;
  null skips construction of `VMM+0x78/+0x80`, and null `+0x78` rejects `allocVMBlock`.

## Guest implementation and regression gate

Files: `src/RecoveryLease.hpp`, `src/RaphaelGPU.cpp`,
`tests/test_recovery_lease.cpp`, shared wire/log fixtures.

- [x] Verify target owner, exact native dispatch, visible bounds and GART separation
  before allocation metadata is written. Refuse duplicate initialization before
  native mutation.
- [x] Publish immutable 80-byte OWNED and separate 104-byte POOL records with the
  state DWORD last; use a native 0x15000-byte lease.
- [x] Remove forced memory enable and the old 240 MiB cap. Reserve the full
  `memoryBase+leaseOffset` range in both native pools; require both actual element
  addresses and exact 0x15000 free-byte reductions before admitting clients.
- [x] Make the guest log nonce LOW_HIGH agree with the host parser and test actual
  producer formatting, not only serialized structure bytes.
- [x] Log `VMM+0x50/+0x58/+0x78/+0x80` after early and normal native VMM enable calls
  using existing routes. Retain early paging-channel construction.
- [x] Pass affected C++ sanitizer tests, whole-driver syntax, exact-KDK preflight,
  and behavior tests for ownership failures and repeated initialization.

## Host integration and regression gate

Files: `tools/recovery_lease_v2.py`, `tools/vfio-recover.py`,
`tools/experiment.py`, `tools/warm-qualification.py`, corresponding Python tests,
`tools/functional-regression.py`, `.github/workflows/release.yml`.

- [x] Parse the actual bounded critical stream, including ordinary diagnostics and
  identical replay. Reject conflicting wire identity and committed corruption.
- [x] Derive a per-recovery layout from manifest-bound OWNED and matching BAR bytes;
  pass it explicitly through image construction, GART checks, writes and receipts.
  Never overwrite immutable ownership metadata during cleanup.
- [x] Stop new launches from writing a v1 pending descriptor. Keep old receipt
  validation available for frozen history and the initial 178-B baseline.
- [x] Require the run identity before staging numeric `rgpurnlo/rgpurnhi` boot args;
  validate it against the sealed manifest and disk hashes before launch. Do not
  change boot images after sealing the run manifest.
- [x] Prove with mocked transports that absent/stale/conflicting ownership prevents
  scratch writes, dynamic writes stay inside the lease, and early OWNED recovery
  does not depend on a completed POOL update. Only state zero is an uncommitted
  status; a committed record with bad checksum is not a successful partial write.
- [x] Check regression reporting against complete capture/probe evidence. Partial
  counters and startup-only zero summaries must not become acceptance or loss claims.
- [x] Include new fixtures in CI and pin imported recovery-helper dependencies in
  experiment evidence.

## First finite hardware experiment

- [x] Review the completed Astra report and both implementations; record accepted
  recommendations and any remaining uncertainty in `status.md`.
- [ ] Produce one reviewed candidate artifact on dev and seal its identities. Prepare
  a new finite one-run experiment preserving all six existing ledger entries and
  binding the 178-B cleanup evidence. Do not auto-extend the old plan.
- [ ] Recheck live boot identity, device ownership, no active VM, host fault journal,
  watchdogs, sleep inhibition, receipt and exact artifacts through existing gates.
- [ ] Sole operator runs the bounded experiment and normal cleanup. Capture the
  native lease, one pool initialization, pool exclusion, full VMM arena interval,
  page-table allocator pointers, existing backing observer and submission trace.
- [ ] If arena allocation still fails, compare its requested full interval with actual
  free pools and exclusions. If it succeeds but DMA clearing stalls, classify that
  as a downstream execution failure and inspect captured SDMA evidence before retry.
- [ ] Run the unchanged probe when readiness admits it. Require correct compute values
  and rendered pixels; compare with both 178-B and historical 171 submission progress.
- [ ] Publish a brief progress table and issue, archive evidence, update the failure
  streak, and decide the next experiment from the observed first failing boundary.

## After the first functional result

Correct probe compute and offscreen rendering precede compositor/display qualification.
Only after desktop acceleration is evidenced should the user receive the GPU-backed VM
display for interactive testing. Repeated normal cleanup and forced-close/guest-crash
recovery require their own bounded tests; they are not established by this first run.
