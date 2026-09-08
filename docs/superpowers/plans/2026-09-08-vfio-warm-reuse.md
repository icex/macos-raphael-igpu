# Rootless VFIO warm-reuse implementation plan

> **For agentic workers:** Execute this plan task by task. One owner controls all physical GPU
> operations; do not run hardware steps concurrently.

**Goal:** Admit repeated macOS GPU experiments in one host boot only after a rootless,
measured PSP, GC, SDMA and temporary-KIQ cleanup proves the previous VFIO assignment is
quiescent.

**Architecture:** Add a small VFIO transport with an injectable fake backend, map BAR0 VRAM,
BAR2 doorbells and BAR5 MMIO, store immutable recovery receipts, and replace the one-boot boolean
reservation with an ordered launch ledger. A launch-bound guest reservation protects the
temporary KIQ scratch range. The coordinator keeps the original host gates and three-launch
ceiling.

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
- [x] Implement Linux VFIO container/group/device setup and BAR0/BAR2/BAR5 mapping with no root
  path after the privileged one-way handoff.
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
- [x] Run the focused and full offline suites for the original BAR5-only transaction.
- [x] Re-run KDK preflight and all offline suites after the launch-bound reservation and
  temporary-KIQ kext changes described in Task 6.

## Task 4: Prove warm reuse on hardware

**Files:** update `findings/GPU-RE.md`, `docs/ROADMAP.md`, experiment evidence.

- [x] Record the current post-candidate-165 transaction; later analysis found it was confounded
  by legacy VFIO's implicit `bus` reset and it cannot prove cleanup.
- [ ] Rebuild/reprepare candidate 166 against the resulting source commit.
- [x] Launch candidate 166 on the same host boot with the 180-second supervisor and continuous
  host monitor.
- [x] Verify receipt consumption, normal PSP initialization and absence of host kernel faults.
- [ ] If it succeeds, run up to one more cleanup/launch cycle; otherwise close reuse for this
  boot and diagnose the first failed invariant.
- [x] Commit the implementation and evidence to `dev`; do not merge or push to `main`.

## Task 5: Remove implicit PCI resets and repeat the proof

- [x] Disable reset methods before granting user access during the one-way handoff.
- [x] Refuse launch and recovery before VFIO open unless `reset_method` reads empty.
- [x] Require schema-2 receipts with empty before/after reset methods and no reset messages.
- [ ] Validate GC/SDMA/PSP cleanup and one warm launch without a VFIO reset message.

## Task 6: Retire legacy graphics through a launch-bound host KIQ

**Files:** modify `src/RaphaelGPU.cpp`, `tools/vfio-recover.py`, `tools/experiment.py` and their
tests; create `src/RecoveryReservation.hpp` and `tests/test_recovery_reservation.cpp`.

- [x] Before QEMU starts, write a checksummed `PENDING` descriptor containing the exact run ID
  into BAR0; immediately before Apple enables allocations, cap both BAR0 allocator pools below
  the final 16 MiB and promote only that current-launch descriptor to `ACTIVE`.
- [x] Require and consume the exact `ACTIVE` run descriptor before scratch use. Reject absent,
  corrupt, pending, stale and replayed descriptors.
- [x] Mirror `GartAddresses.hpp::physicalTable` for runtime context-0 page-table validation and
  reject unknown address forms, invalid bounds and any GART/scratch overlap.
- [x] Build a 0x100-dword temporary KIQ ring containing graphics `UNMAP_QUEUES`, a unique
  `WRITE_DATA` fence and KIQ NOP padding; validate graphics doorbell offset `0x400`.
- [x] Order BAR0 writes with the validated NBIO 7.2 HDP flush, use an aligned native 64-bit BAR2
  doorbell store, and require rptr advancement, fence equality and graphics inactive before
  legacy scrub.
- [x] Leave pointer polling, PQ doorbell gate and MEC doorbell ranges disabled; restore selector
  zero and halt both MECs in every exit path. A stuck/force-cleared HQD remains non-authorizing.
- [x] Extend receipt admission to require the launch reservation, HDP, fence and final gate
  evidence, and cover all failure paths with offline fake-MMIO tests.
- [ ] Qualify the `PENDING` to `ACTIVE` transition, HDP flush, GPU-written fence and graphics
  retirement on physical hardware under the existing host monitor and exposure deadline.
- [ ] Use the resulting receipt for one successful same-boot macOS reinitialization. Until both
  hardware checks pass, this expanded recovery must not be described as proven warm reuse.
