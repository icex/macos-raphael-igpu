# Candidate 191 recovery differential

Date: 2026-09-10
Scope: frozen evidence and source only; no device access, reset, retry, VM launch,
or policy change.

## Inputs

- Candidate 191 frozen recovery:
  `/home/bogdan/macos-vm/run/metal-025-191/recovery.json`, SHA-256
  `0d5420be9c85a5bc22ef43f166ec14203ddb70448c4e059866227add594b864e`.
- Candidate 190 successful canonical recovery:
  `/home/bogdan/macos-vm/run/vfio-recovery/3bca3e47-1f28-4f78-af00-5dbf76b00620/3ffc5f3dbec53665214863ed91fee0e7.json`,
  SHA-256
  `82560e48da2e6fb4300f5b0095e821d3da404d170108fd891ca7824aad49967a`.
- Recovery implementation: `tools/vfio-recover.py`, SHA-256
  `3616a938db007c84ecae6048bfd83100902759a328dda92c1d5394801e2d288e`.
  Both manifests pin this same helper, so the differential is device state, not
  a recovery-code revision.
- Primary source reference: upstream-stable Linux v7.2.3 commit
  `58e7295cfecaddec94629160386412e0f2b1e8fe`,
  `drivers/gpu/drm/amd/amdgpu/gfx_v10_0.c`, as frozen under
  `/home/bogdan/macos-vm/run/research/metal-integration-20260909/cache/linux-stable-v7.2.3/`.
  The matching local GC10.3.6 copy used for line-by-line review has SHA-256
  `b8bf032fea2e6da3fc3517eed86fd395a2a764a6a3f63699fde4d6a16c06f100`.

## First demonstrated divergence

The common prefix succeeds through temporary-KIQ activation and doorbell
submission:

| Boundary | Candidate 190 | Candidate 191 |
|---|---:|---:|
| launch lease | OWNED/ACTIVE/VALID | OWNED/ACTIVE/VALID |
| active compute HQDs | selectors 8, 9 | selectors 4, 8, 9 |
| firmware dequeues | 2/2, no timeout | 3/3, no timeout |
| `CP_MEC_CNTL` before/after | `0x50000000` / `0x50000000` | same |
| temporary HQD activation readback | 1 | 1 |
| submitted KIQ WPTR | 256 dwords | 256 dwords |
| terminal KIQ RPTR/report/fence | 256 / 256 / expected sequence | 0 / 0 / 0 after 2,000 polls |

Thus the first observed divergence is **after** the host programs selector 9,
reads `CP_HQD_ACTIVE=1`, enables the global doorbell gate, releases MEC2 from
halt, and writes doorbell WPTR 256, but **before** MEC2 fetches the first KIQ
packet. Candidate 191 does not reach `UNMAP_QUEUES`; its graphics ring therefore
cannot be said to have consumed or rejected that packet.

The candidate 191 cleanup evidence reinforces that boundary. Its final selected
HQD has `ACTIVE=0`, `RPTR=0`, and `WPTR_LO=256`. The nonzero WPTR proves the
doorbell submission reached the queue's register state, while zero RPTR, zero
VRAM RPTR report, and zero fence show no demonstrated packet consumption. The
cleanup correctly refuses authorization because WPTR cannot be cleared by the
existing stopped-HQD path. Candidate 190 instead recorded matching RPTR and
fence sequence, graphics inactive after unmap, genuine KIQ dequeue, and all-zero
final KIQ pointers.

The extra candidate 191 selector 4 is a real pre-recovery state difference, as
are graphics WPTR (`23040` versus `68224`) and SDMA GFX/PAGE IB control values.
Selector 4 nevertheless dequeued in one poll and the rescan found no live HQD.
The frozen evidence does not establish that it caused MEC2's later failure. All
other coarse command-processor end gates (`CP_STAT`, CPC busy, PQ status, pointer
poll control) are equal and zero after cleanup.

## Linux GFX10 requirements and comparison

Linux's GFX10 KIQ path provides three relevant contracts:

1. `gfx_v10_0_kiq_init_queue()` initializes or restores a complete compute MQD,
   clears the ring for reset recovery, selects the KIQ HQD, and calls
   `gfx_v10_0_kiq_init_register()`.
2. `gfx_v10_0_kiq_init_register()` disables write-pointer polling, requests
   dequeue if the selected HQD is already active, writes EOP/MQD/PQ bases and
   controls, report and poll addresses, doorbell ranges/control, WPTR, VMID,
   persistent state, and finally ACTIVE. Linux performs this as part of the
   broader CP resume path, followed by KCQ and graphics queue resume and ring
   tests.
3. `gfx10_kiq_unmap_queues()` emits the same six-dword packet shape used here:
   `PACKET3_UNMAP_QUEUES`, one queue, graphics engine selection, target doorbell
   offset, and zero payload for ordinary unmap.

The host helper deliberately implements a smaller, previously demonstrated
subset because it operates after VFIO has discarded guest DMA mappings. It uses
lease-owned VRAM, verifies the ring/MQD CPU writes, flushes HDP, programs the
selected HQD, starts only MEC2, and requires both fetch progress and an explicit
fence before accepting the unmap. Candidate190 proves this exact subset can work
on the same boot and helper version.

Linux does **not** support treating `ACTIVE=1` or a changed WPTR as execution
proof. Its normal driver owns firmware lifecycle, CP resume ordering, queue
resources, memory mappings, interrupts, and ring tests. The recovery helper has
no safe basis to recreate those global ownership transitions after a guest
failure. In particular, Linux's full CP/KIQ resume procedure is not a recipe
that can be copied piecemeal into VFIO recovery without proving the current
firmware and queue state.

## Demonstrated conclusions

- Candidate 191 recovery is incomplete and authorizes no launch.
- All three discovered compute HQDs accepted firmware dequeue; there was no
  forced-inactive fallback.
- The temporary KIQ scratch image passed VRAM readback and HDP flush completed.
- Temporary HQD activation and doorbell WPTR publication completed.
- MEC2 produced no observed RPTR progress or fence write during the bounded
  poll, so graphics unmap was not consumed.
- The cleanup left all recorded global gates safe except selected-HQD WPTR_LO
  remained 256. The current schema correctly rejects that state.
- Candidate190's successful recovery used the identical helper and KIQ packet,
  and did observe fetch, fence, graphics retirement, KIQ dequeue, and clean
  pointers.

## Unknowns

- Whether MEC2 was executing instructions after its halt bit was cleared.
- Whether a CP/MEC firmware, scheduler, interrupt, or queue-resource state left
  by the failed first submission prevented dispatch.
- Whether selector 4's prior activity is causal or merely reflects the deeper,
  complete candidate191 run.
- Whether any unrecorded HQD/MQD register differs at the activation boundary.
- Whether a longer wait would change the result. Extending a timeout would not
  establish safety and is not justified by the flat zero-progress trace.
- Whether a global CP reset/resume would recover the device. Such a transition
  exceeds the current no-reset recovery contract and current boot budget.

## Safe next work

No recovery mutation is justified from this evidence, so this audit proposes no
implementation change. In particular, do not clear the stopped WPTR merely to
manufacture a clean receipt, do not accept ACTIVE/WPTR as execution, do not skip
the fence, and do not issue a second recovery attempt.

The smallest useful offline change for a *future* run is evidence-only: extend
the preexisting authenticated recovery receipt schema and hosted MMIO tests to
snapshot the complete selected KIQ HQD register set plus MEC/CP liveness inputs
immediately before activation, after MEC2 release, and at the terminal poll.
The capture must include the MQD/PQ bases and controls, VMID, persistent/IB
controls, dequeue state, doorbell and range controls, RPTR/WPTR, MEC halt state,
and available CP/MEC status registers. A future design review can then compare
the failed state against the successful 190 values and Linux's initialized MQD.
This instrumentation must remain observational and receipt-rejecting; it cannot
relax any current success predicate.

If that future evidence shows MEC2 released but unable to fetch from a fully
matching HQD, the next architectural decision is whether recovery may safely own
a documented CP microengine reinitialization. That would require a new contract,
independent review, and a fresh boot budget; it is not an incremental patch to
the existing KIQ transaction.

### Ranked read-only checklist

These are the top three discriminating snapshots. They are proposed for a future
reviewed recovery implementation, not for the stopped candidate 191 device.
Every read must occur while the existing transaction already has selector 9
selected. Diagnostic code must never write `GRBM_GFX_CNTL`, change a selector,
clear a fault, invalidate an instruction cache, or otherwise perturb state.

1. **Exact selected-HQD register image.** Immediately after programming and
   ACTIVE readback, then again at the terminal poll, read the Linux-init fields:
   MQD base/control; PQ base/control; RPTR report and WPTR-poll addresses; EOP
   base/control; doorbell control; VMID; persistent state; IB control; ACTIVE;
   DEQUEUE request/status; RPTR; and WPTR low/high. Compare them byte-for-byte
   with the helper's intended image and the retained MQD. This most directly
   distinguishes a posted/lost or residual HQD field from a correctly programmed
   queue that MEC2 did not schedule. These are ordinary `RREG32` fields in
   Linux's register dump/init paths; reads have no documented command semantics.

2. **MEC2 execution time series.** At pre-release, immediately after clearing
   the MEC2 halt bit, after doorbell publication, and terminal poll, read
   `CP_MEC_CNTL`, `CP_MEC2_INSTR_PNTR`, and `CP_CPC_STATUS` (especially
   `MEC2_BUSY`, dispatch-controller, request-controller, and instruction-cache
   busy bits). A changing instruction pointer or MEC2 busy transition with a
   static HQD narrows the failure to dispatch/fetch; an unchanged halted or idle
   MEC2 points earlier. Read the instruction-cache busy/status bit only; never
   set `MEC_INVALIDATE_ICACHE`. Linux lists both instruction pointer and CPC
   status in its read-only GFX register table.

3. **VMID0 fetch-fault tuple.** At the same pre-doorbell and terminal boundaries,
   read `GCVM_L2_PROTECTION_FAULT_STATUS` and its low/high address registers,
   together with the already sampled context-0 control/root/range/FB-offset
   tuple. This distinguishes a KIQ ring/MQD fetch translation fault from a
   scheduler that never attempted a fetch. Do not write
   `GCVM_L2_PROTECTION_FAULT_CNTL`: its bit 0 clears the latched fault, which
   would mutate evidence. Plain status/address reads are the existing diagnostic
   pattern and have no clear-on-read behavior in the pinned definitions.

Do not expand this list with broad register dumps. Snapshot 1 answers whether
the queue was initialized as intended; snapshot 2 answers whether MEC2 ran;
snapshot 3 answers whether its VMID0 fetch faulted. Together they partition the
observed zero-RPTR boundary without weakening the fence or cleanup gates.
