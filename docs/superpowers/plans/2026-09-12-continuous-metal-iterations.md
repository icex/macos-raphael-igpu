# Continuous Metal Acceleration Iteration Plan

## Objective

Reach and qualify a visible macOS desktop rendered by the Raphael iGPU with
Metal, while keeping every launch bounded, observable, and recoverable without a
host reboot.

## Current baseline

- Candidate 194: Metal compute and offscreen render/readback demonstrated.
- Candidate 201: exact RIP `0x610ad` is
  `AMDGFX10ComputeRing::enable+0x21`, a write through null `[ring+0xb0]` after
  `PM4 initComputeMQD`; `AMDHardware::powerUp+0x66` is only a caller frame.
- Candidate 202: engine/vtable skip-as-success guards were built but do not cover
  the internal ring null and must not be used. No candidate-202 GPU run occurred.
- Host observation: iGPU accessible on `vfio-pci` and no active QEMU. This does
  not by itself prove graphics retirement or reusable recovery.
- Review gate: at least candidates 199, 200, and 201 are actual attempts since
  the last completed review; no further hardware is authorized until the
  required refreshed offline Astra xhigh review completes.

## Invariant workflow for every iteration

1. Read `status.md`; record the current unresolved boundary and attempt count.
2. Verify host state: boot ID, iGPU driver, runtime power, no QEMU, no kernel fault.
3. Create a new candidate number, card, clean worktree commit, build artifact,
   debug symbols, and identities. Never reuse a candidate authority or run ID.
4. Run preflight, focused regression tests, and the full Python suite before
   touching hardware. Stop the iteration offline if any identity or regression
   check fails.
5. Stage and prepare exactly once. Validate `GENERIC_GRAPHICS=off`, `-vga none`,
   bounded exposure, serial capture, critical capture, and recovery lease.
6. Start one external user-level idle inhibitor, then launch the managed VM.
   Do not use sudo for sleep inhibition and do not start a second admission path.
7. Collect serial, critical replay, panic/backtrace, Metal probe, and submission
   counters until the bounded deadline. Do not infer success from enumeration.
8. Stop through the exact supervisor unit. If the supervisor rejects shutdown,
   stop that exact systemd unit and verify Docker/QEMU disappearance.
9. Verify host-after state and recovery receipt before any next iteration.
10. Append a short progress table and blocker to `status.md`, preserving raw
    evidence and marking harness failures separately from GPU failures.

## Debug decision tree

- If launch fails before QEMU/VFIO: repair harness and do not consume a GPU
  attempt or alter the driver hypothesis.
- If guest fails before `powerUpHW`: instrument the earliest Apple call boundary
  and patch only the demonstrated null/error path.
- If `powerUpHW` fails: correlate the exact symbol offset and registers against
  KDK disassembly; add a read-only wrapper before changing control flow.
- If VMM becomes ready but submissions remain zero: inspect allocator/map calls,
  page-table domains, and queue state in that order.
- If submissions execute but KIQ stalls: capture instruction-cache base, HQD,
  doorbell, GART, and VM fault state from the same run.
- If Metal compute works but desktop is black: qualify IOFramebuffer, connector,
  HPD/EDID, and scanout independently from the compute path.
- If any host fault or incomplete graphics quiesce occurs: stop hardware work,
  preserve evidence, and repair recovery before another launch.

## Candidate 203 is not yet authorized

- Base any revision on the exact-RIP audit in
  `findings/research/panic201-exact-rip-audit.md`, after coordinator and mandatory
  Astra review. Do not inherit the candidate-202 engine guard.
- Remove the `wireSysMemory` route at `0x4ad44`: its wrapper has the wrong ABI
  and also substitutes `nullptr` without any real deferral mechanism.
- Restore the native accelerator power-service failure branch. Candidate 201
  accidentally retained this bypass and therefore entered PM4 startup after
  resource initialization had failed.
- Preserve `rgpuvmmforce` disabled. Diagnose and repair the producer path that
  must make `AMDRTRing::allocateMemoryResources` publish compute-ring `+0xb0`;
  do not skip or report success for absent objects/resources.
- Add offline regression checks for the exact six-register `wireSysMemory` ABI,
  candidate-201 RIP/instruction bytes, and fail-closed ring prerequisites. Keep
  candidate 194 as the functional comparison while acknowledging that its whole
  run verdict was inconclusive due capture loss.
- Only after the review gate and offline checks pass may a new candidate/card be
  prepared. Its first live discriminator is a clean native resource failure or
  successful ring-pointer publication; reaching PM4 with null `+0xb0` is an
  immediate abort condition.

## Completion gates

Desktop Metal is complete only when all are demonstrated in a fresh run and a
repeat run: `MTLDevice` Metal 3, changing desktop frames through the Raphael
path, no generic QEMU GPU, sustained submissions without KIQ timeout, clean
shutdown and forced-close recovery, and host safety with no reboot between the
repeat runs.
