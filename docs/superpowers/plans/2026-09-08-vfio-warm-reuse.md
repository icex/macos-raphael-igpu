# Rootless VFIO warm-reuse implementation plan

> **For agentic workers:** Execute this plan task by task. One owner controls all physical GPU
> operations; do not run hardware steps concurrently.

**Goal:** Admit repeated macOS GPU experiments in one host boot only after a rootless,
measured PSP-ring cleanup proves the previous VFIO assignment is quiescent.

**Architecture:** Add a small VFIO transport with an injectable fake backend, store immutable
recovery receipts, and replace the one-boot boolean reservation with an ordered launch ledger.
The coordinator keeps the original host gates and three-launch ceiling.

**Tech stack:** Python standard library, Linux legacy VFIO API, unittest, existing experiment
coordinator and QEMU supervisor.

**Spec:** [Rootless VFIO warm-reuse design](../specs/2026-09-08-vfio-warm-reuse-design.md)

## Task 1: Lock the recovery contract with unit tests

**Files:** create `tests/test_vfio_recover.py`; create `tools/vfio-recover.py`.

- [x] Test exact device/group/driver and inactive-VM gates.
- [x] Test refusal when PCI bus mastering is enabled before or after the transaction.
- [x] Test both PSP commands, exact response matching, timeout and cleanup ordering using a
  fake VFIO transport.
- [x] Test immutable receipt creation only after commands and kernel-fault checks pass.
- [x] Implement Linux VFIO container/group/device setup and BAR5 mapping with no root path.
- [x] Validate ioctl numbers against the installed Linux UAPI header.

## Task 2: Add a single-use launch ledger

**Files:** modify `tools/experiment.py`, `tests/test_experiment.py`.

- [x] Test first-launch admission, legacy reservation migration, exact predecessor linkage,
  receipt consumption, replay refusal and the three-launch ceiling.
- [x] Implement backwards-compatible ledger reads and atomic next-launch reservation.
- [x] Keep GPU-less launches outside the GPU ledger.
- [x] Preserve the current fail-closed admission gates for every launch.

## Task 3: Integrate post-run recovery

**Files:** modify `tools/experiment.py`, `tests/test_experiment.py`.

- [x] Run recovery only after exact QEMU stop confirmation and the host monitor's final poll.
- [x] Archive recovery output and expose recovery status in the run verdict without changing
  the observed guest result.
- [x] Ensure STOP_UNCONFIRMED, active QEMU, host faults and recovery failures create no receipt.
- [x] Run the focused and full offline suites. Candidate 166's KDK preflight had already passed;
  this change does not alter the kext or its build inputs.

## Task 4: Prove warm reuse on hardware

**Files:** update `findings/GPU-RE.md`, `docs/ROADMAP.md`, experiment evidence.

- [x] Recover the current post-candidate-165 device without sudo and record exact evidence.
- [ ] Rebuild/reprepare candidate 166 against the resulting source commit.
- [ ] Launch candidate 166 on the same host boot with the 180-second supervisor and continuous
  host monitor.
- [ ] Verify receipt consumption, normal PSP initialization and absence of host kernel faults.
- [ ] If it succeeds, run up to one more cleanup/launch cycle; otherwise close reuse for this
  boot and diagnose the first failed invariant.
- [ ] Commit the implementation and evidence to `dev`; do not merge or push to `main`.
