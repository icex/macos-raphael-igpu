# Ranked failure hypotheses for full Raphael desktop Metal acceleration

**Research date:** 2026-09-09  
**Evidence cut:** candidate178-A and candidate178-B completed with final validators clean.  
**Ranking method:** causal proximity to the earliest observed rejection, ability to explain all
measured facts, and availability of a narrow discriminator. Confidence words are qualitative;
no numerical probabilities are inferred from the small run count.

## Evidence that constrains every hypothesis

The first committed command currently fails before native channel submission. Candidate177
observed false `batchMemoryMapPrepare`, zero mapping-batch progress, final false `BatchPrepare`,
queue error `e00002bd`, and zero `submitBuffer` calls.[^e177] Candidate178-A then classified all
483 failed outer map-preparation calls as `backing-pte`, with capacity 0, VA/reclaim 0, unknown 0.
Its two retained samples have assigned GPUVA state before and after the false return:
`flags=0xb13`, `GPUVA=0x4000c0000`, prepare count 0, batch count 0.[^e178a]
Candidate178-B repeated the result with the identical build: all 531 failed calls were
`backing-pte`, with zero in the other three classes, the same retained fields, zero submit calls,
and the same Metal error with zero completed work.[^e178b]

The unchanged probe again enumerated the device, advertised Metal 3, compiled shaders and a
pipeline, created a queue and two 256 KiB managed buffers, then failed its compound compute plus
managed-synchronization command with status 5 / `e00002bd` and zero completed work.[^probe]
The local 24G830 header defines `e00002bd` as `kIOReturnNoMemory`; that name does not identify which
allocation-like suboperation failed.[^forensics]

The ranking therefore starts inside post-VA mapping preparation. Downstream submission, VMID,
shader, fence, rendering, and presentation remain real work for full desktop acceleration, but
they cannot explain the first observed rejection.

## Ranked matrix

| Rank | Hypothesis | Current confidence | Earliest discriminator |
|---:|---|---|---|
| 1 | Backing acquisition, wiring, or residency fails before GPU page-table commit | High | count `commitIntoGPUPageTable` entries versus failed outer calls |
| 2 | The selected GPU page-table commit callback returns false | High | wrap exact `0x3b4d2`, retain native Boolean and branch mode |
| 3 | The selected task mode/commit callback is wrong for this integrated GPU | Moderate | correlate `task+0x268` with mode-specific commit result and raw target identity |
| 4 | Managed storage/coherency resource policy drives the failing map class | Moderate | after phase split, controlled shared/managed/private and blit-only matrix |
| 5 | X6000's discrete-VRAM assumptions produce an invalid post-VA map target on Raphael | Moderate | inspect raw failed map/target fields and chosen pool without altering placement |
| 6 | Duplicate allocator-pool initialization corrupts later resource bookkeeping | Moderate-low | prove a damaged allocator/backing invariant before changing the second init |
| 7 | Native reclaim/page-on fallback cannot make the backing/PTE map preparable | Moderate-low | observe first prepare, fallback result/progress, final retry separately |
| 8 | Resource-map lifetime or prepare-count imbalance survives batch cleanup | Low | balanced retain/prepare/release observations around one failed map |
| 9 | Commit-update scratch allocation fails despite assigned client VA | Low, conditional on commit false | exact callback result plus update-storage allocation result |
| 10 | Page size, address form, or PTE flags are wrong for the commit target | Low, conditional on commit false | decode one rejected update's exact VA/raw fields against 24G830 |
| 11 | Host IOMMU/DMA mapping rejects the resource backing | Low, conditional on pre-commit failure | exact wiring/DMA-map return and physical segment constraints |
| 12 | Per-client GPUVM root/PTE encoding or invalidation fails after commit | Deferred | first successful commit+submit, then exact client-root walk |
| 13 | Channel or IB publication fails after resource preparation | Deferred | first submit entry/result and exact IB scalar fields |
| 14 | SDMA/VMID/queue consumption fails after publication | Deferred | producer/consumer and VMID/root transitions |
| 15 | Fence/interrupt completion or cache visibility fails | Deferred | emitted/signalled fence followed by validated readback |
| 16 | Shader ABI/ISA or resource binding produces wrong compute results | Deferred | completed dispatch with deterministic word mismatch |
| 17 | Managed CPU/GPU coherency fails after execution | Deferred | correct GPU write plus distinct synchronized/unsynchronized CPU reads |
| 18 | Render layout, tiling, cache, or blit produces wrong pixels | Deferred | correct compute followed by failed 4,096-pixel offscreen check |
| 19 | CAMetalLayer/IOSurface/WindowServer presentation fails | Deferred | offscreen pass followed by drawable turnover and compositor lifecycle |
| 20 | QEMU display transport or physical DCN scanout fails | Deferred | explicit VFIO GFX-plane or physical connector/DCN evidence |

Ranks 1 and 2 are sibling branches of the same next observation. They should be tested in one
bounded diagnostic, not in separate blind hardware runs.

## 1. Backing acquisition, wiring, or residency fails before commit

**Claim.** The map already has a GPU virtual address, but IOAccelerator cannot acquire, pin, wire,
or otherwise prepare the memory backing needed to enter that address into the GPU page table.

**Evidence for.** Candidate178-A/B prove that the final failed maps retain assigned VA state. In the
exact path, `AMDAccelMemoryMap::prepare` tail-calls the IOAccelerator superclass after VA assignment.
Candidate178's `backing-pte` class therefore includes precisely this region.[^phase] A failure here
fits `kIOReturnNoMemory` without requiring literal exhaustion.

**Evidence against or limiting.** Metal created the managed buffer objects and their CPU mappings,
and the machine has enough memory to boot and run the workload. This weakens simple host-memory
exhaustion, but object creation can precede command-time residency/wiring. No exact backing call or
return value has been observed.

**Smallest discriminator.** Add one observation-only wrapper for exact X6000
`AMDAccelMemoryMap::commitIntoGPUPageTable` at `0x3b4d2`. Count failed outer preparations and
commit entries/results. Capture only direct fields read by the exact native method: task
pointer/mode, raw `map+0x118`, raw `map+0x18`, GPUVA, and `map+0x138` flags. Do not
assign semantics to the two raw fields or re-invoke map vtable slot `+0x168` to observe the
callback argument it returns.[^commit]

**Accept.** Assigned-VA outer calls return false without a matching commit entry, under a complete
non-overflowing lifetime counter.

**Refute.** Each relevant failed outer call reaches the commit function and the commit function
itself returns false.

**Repair direction if accepted.** Disassemble the exact superclass prepare caller immediately
before commit and identify the single failed backing/wiring return. Correct the integrated-memory
object/pool contract shown by that return; do not bypass preparation or mark an unwired object
ready.

## 2. GPU page-table commit callback returns false

**Claim.** Backing preparation reaches X6000's commit method, but the chosen native callback rejects
the update.

**Evidence for.** All observed failed maps have assigned GPUVA state and remain unchanged. The exact
`commitIntoGPUPageTable` method returns a Boolean and sets bit `0x40` in `map+0x138` when its chosen
callback returns false. It has two call branches, both capable of producing the false result.[^commit]
Linux's public RDNA2-era AMDGPU path likewise separates VM-update preparation, PTE/PDE emission,
and commit, showing that allocation of VA alone is not enough.[^linux-vm]

**Evidence against or limiting.** Candidate178 observes only before and after the *outer* prepare.
It neither proves this function was entered nor reads its result. `backing-pte` is deliberately a
family, not a PTE verdict.

**Smallest discriminator.** The same single wrapper proposed for hypothesis 1. Preserve the native
Boolean exactly; record entry/exit totals, false totals by mode, and bounded first samples. The
complete 17-byte entry span is `554889e5415741564155415453504889fb`, with no RIP-relative or
relative-control instruction.[^commit]

**Accept.** The commit method is entered and returns false for the settled failed maps; bit `0x40`
is set consistently at return.

**Refute.** No commit entry occurs before the assigned-VA outer failure, or commit returns true and
the outer path fails later.

**Repair direction if accepted.** Follow only the selected callback: mode 1 uses object
`task+0x260`, vtable `+0x120`; alternate mode uses the raw target at `map+0x118`, vtable `+0x130`. Establish
the callback's exact contract and failed prerequisite before changing page-table data or return
handling.

## 3. Wrong task mode or commit backend for Raphael

**Claim.** X6000 selects a commit backend intended for a different memory topology because the
Raphael device inherits a Navi23/discrete policy bit or object graph that is not valid for this APU.

**Evidence for.** `commitIntoGPUPageTable` branches on `task+0x268 == 1` and then calls materially
different objects and ABIs. Raphael has an APU memory topology: AMDGPU's public model describes APU
VRAM as a BIOS carveout and GTT as GPU-accessible system memory through GART.[^amdgpu-core] This
project deliberately adapts a discrete Navi23 macOS driver, so topology-sensitive choices deserve
scrutiny.

**Evidence against or limiting.** There is no measured task mode yet, and either native path may be
valid. The mere existence of two paths is not evidence that the chosen one is wrong.

**Smallest discriminator.** In the commit wrapper, capture `task+0x268`, `task+0x260`, raw
`map+0x118`, raw `map+0x18`, and native Boolean. Aggregate false results by mode while retaining
only a few samples. The wrapper must not call vtable slot `+0x168` again.

**Accept.** Failures are confined to a branch whose object or required memory domain is demonstrably
incompatible with the observed map/backing type, and the exact native comparison selects it.

**Refute.** The chosen branch and object graph match known-successful X6000 semantics, or both modes
fail identically for the same prior reason.

**Repair direction if accepted.** Correct the upstream property/mode derivation at its source. Do
not force the opposite branch at the commit call without proving its object and lifetime contract.

## 4. Managed storage/coherency policy drives the failed map

**Claim.** The first command fails because managed CPU/GPU dual-copy semantics or its explicit
synchronize command creates a backing path that the adapted driver cannot prepare.

**Evidence for.** The first command uses two managed 256 KiB buffers, CPU writes plus
`didModifyRange:`, compute, and a blit `synchronizeResource:` in one command. Apple's managed mode
requires explicit synchronization between CPU and GPU views.[^apple-managed] The failure occurs
while preparing resources for this compound command.

**Evidence against or limiting.** Candidate177 sees broad background map failures before and around
the probe, so managed buffers may not be unique. The trace lacks PID/nonce association. X6000 can
also prepare internal command/pipeline resources along the same path.

**Smallest discriminator.** Only after hypotheses 1/2 split the exact native phase, run a separately
approved, deterministic matrix with equal small sizes: shared buffer/no sync, current managed
buffer/sync, private working buffer plus transfer buffer, blit-only, and compute-only followed by a
separate readback command.

**Accept.** The same native phase succeeds for shared or private-transfer resources and fails
reproducibly only for managed/synchronize resources, with actual completed data validation.

**Refute.** A minimal shared or blit-only command fails at the same native object and phase.

**Repair direction if accepted.** Fix storage-mode placement, coherency, or backing selection. Do
not remove the synchronization and declare stale CPU data correct.

## 5. Discrete-VRAM assumptions create invalid backing on the APU

**Claim.** The native map gets a VA, but its backing object, range, or memory-domain choice reflects
discrete Navi23 assumptions that do not hold for Raphael's carveout plus system-memory topology.

**Evidence for.** The driver reports 512 MiB framebuffer memory and a 256 MiB CPU-visible aperture,
and project code already has to cap pool sizes to the aperture. Public AMDGPU architecture separates
VRAM, GTT, and CPU-only memory and requires fixed/pinned GPU-visible placement for some uses.[^amdgpu-core]
The failure family begins exactly where backing must become GPU accessible.

**Evidence against or limiting.** The retained candidate178 sample has a plausible assigned
GPUVA `0x4000c0000`; an address alone says nothing about physical backing. Native startup, KIQ, and
engines work, so the basic carveout is not wholly unusable.

**Smallest discriminator.** At the single commit boundary, record raw `map+0x118` and
`map+0x18`, then use exact 24G830 constructors/getters/callers to establish their meanings outside
the hot path. Compare successful and failed calls without changing policy. The value returned by
vtable slot `+0x168` is outside this observer unless a later inside-callback boundary is proven.

**Accept.** Failed maps consistently select a domain/object whose range or backing is incompatible
with the measured aperture/carveout, and the exact callback rejects that property.

**Refute.** Failed and successful maps have the same valid backing contract, while the failure is
strictly inside PTE commit.

**Repair direction if accepted.** Correct size/domain derivation for Raphael while preserving
bounds. Enlarging a CPU mapping or accepting out-of-range physical memory is not a valid repair.

## 6. Duplicate allocator-pool initialization corrupts later bookkeeping

**Claim.** Calling `AMDHWMemory::enableAllocations` manually and then again through native power-up
reinitializes the same allocator pools, clearing/rebuilding bookkeeping in a way that later breaks
backing preparation.

**Evidence for.** The exact IOAcceleratorFamily2 `init_pool(uint64_t,uint64_t)` at `0x1f8e8` calls
the inner `init_pool(uint64_t)` at `0x1f784`, which clears fields and rebuilds lists. Candidate176
serial shows two `enableAllocations` calls on the same pools.[^forensics]

**Evidence against or limiting.** No allocation has been proven between the calls, no allocator
failure log appears, and candidate178 proves final GPUVA allocation succeeds for all classified
failures. This lowers the hypothesis from its pre-178 rank. Reinitialization might be harmless at
that point or affect a distinct backing pool, but neither is shown.

**Smallest discriminator.** First identify whether hypothesis 1 or 2 wins. Then inspect only the
allocator used by that exact failing suboperation and compare its list/extents immediately after
each initialization and at failure.

**Accept.** A native invariant or live allocation is destroyed by the second initialization and
the exact later backing/commit call consumes that damaged state.

**Refute.** Both calls occur before any live allocation and the relevant allocator state remains
valid and unchanged, or the failing callback uses another allocator.

**Repair direction if accepted.** Make initialization occur once at the native lifecycle point that
has all prerequisites, rather than masking the eventual false result.

## 7. Native reclaim/page-on fallback never repairs the target backing

**Claim.** The first superclass prepare attempt fails; X6000's system/video-memory reclaim or page-on
fallback runs but cannot make the target map preparable, leading to the final outer false result.

**Evidence for.** Exact `batchMemoryMapPrepare` disassembly contains fallback callbacks and retries.
Candidate178's class describes the final retry state, and 483 plus 531 repeated failures show retry does
not resolve the condition.[^phase]

**Evidence against or limiting.** No fallback entry, result, or reclaimed byte/map count is
currently measured. The target's assigned VA surviving does not prove fallback ran.

**Smallest discriminator.** After the commit/backing split, add counters at the already-identified
outer fallback decisions: first-prepare false, chosen fallback, fallback Boolean/progress, retry
Boolean. Keep them scalar and bounded.

**Accept.** The first attempt fails, fallback is invoked, reports no useful progress or prepares the
wrong object class, and the final retry fails at the same downstream phase.

**Refute.** No fallback runs, or it reports progress and the target passes commit before a later
unrelated failure.

**Repair direction if accepted.** Correct the fallback's resource/domain eligibility or progress
accounting. An unconditional retry loop would only hide the invariant and risk hangs.

## 8. Resource-map lifetime or prepare-count imbalance

**Claim.** A retain/release or prepare-count imbalance leaves a map in a state that has an assigned
VA but cannot complete native preparation.

**Evidence for.** The retained 178 samples have prepare count zero at entry and exit and fail
repeatedly on the same map object. Batch preparation explicitly retains successful maps and later
ends the batch. A lifecycle imbalance could therefore create a stable retry loop.

**Evidence against or limiting.** The snapshots are internally consistent: no impossible nonzero
prepare count or assigned-bit teardown appears, and both A and B shut down cleanly. No release
imbalance is observed.

**Discriminator.** Count prepare/retain/release transitions for one map at reviewed methods, using
lifetime counters rather than per-call logs. **Accept** if a missing or extra transition precedes
repeat failure. **Refute** if the map's native counts balance through batch end. A repair would fix
the missing transition at its owner, never force the count.

## 9. Commit-update scratch allocation fails

**Claim.** The commit callback is reached but cannot allocate its temporary job, command, or update
storage, even though the client VA is assigned.

**Evidence for.** Public AMDGPU's SDMA VM backend allocates update-job storage before emitting and
committing PTE work, and such allocation can fail independently of client VA assignment.[^linux-vm]
The Apple error class is compatible with an internal allocation failure.

**Evidence against or limiting.** This is architectural analogy, not Apple's private implementation.
No X6000 commit entry or allocation return is yet measured.

**Discriminator.** First prove native commit false with the rank-1/2 observer, then identify its
exact callback and the immediately failed allocation return. **Accept** only if that exact
allocation fails. **Refute** if the callback has all update storage and rejects PTE parameters or
never runs. Repair the correctly identified scratch allocator or sizing path.

## 10. Page size, address form, or PTE flags are wrong

**Claim.** The commit target rejects a GPUVA/range/flag combination derived from discrete Navi23
assumptions or incompatible Raphael page geometry.

**Evidence for.** The project already required build-specific GPUVM root and page-table geometry
work. Public AMDGPU treats PTE/PDE construction as a distinct operation after VA selection.[^linux-vm]
The stable `GPUVA=0x4000c0000` and `map+0x138` state give concrete inputs to trace if commit fails.

**Evidence against or limiting.** The raw meanings of `map+0x18`, `map+0x118`, and the value
returned by vtable `+0x168` are not proven. The current phase observer cannot say that a PTE was
attempted.

**Discriminator.** After a measured false commit, disassemble only its selected callback and decode
one rejected update's exact raw inputs against 24G830 constructors/getters. **Accept** if an invalid
alignment, range, address form, or flag reaches the rejecting branch. **Refute** if input validation
passes and failure is an allocation or mapping return. Repair the producer of the wrong value.

## 11. Host IOMMU or DMA mapping rejects the backing

**Claim.** IOAccelerator cannot wire or DMA-map the backing into a form the passed-through iGPU may
access, so preparation stops before commit.

**Evidence for.** The iGPU shares host memory and operates behind VFIO/IOMMU ownership; GPU-visible
system memory requires valid DMA mappings. The observed family begins after GPUVA assignment and
can include backing wiring.

**Evidence against or limiting.** There is no host IOMMU fault in the retained run evidence and no
exact Apple DMA-map failure. The guest creates CPU-visible buffers normally. Absence of a host log
is not proof either way.

**Discriminator.** A zero commit-entry result first localizes pre-commit failure; then observe the
single exact wiring/DMA-map return and segment constraints. **Accept** on an exact failed return or
matching host fault for that mapping. **Refute** if wiring succeeds and commit is called. Repair
addressability/segment construction without weakening IOMMU isolation.

## 12. Per-client GPUVM root, PTE encoding, or invalidation fails after commit

**Claim.** After mapping preparation eventually succeeds, the submitted client context uses the
wrong root, leaf entries, address form, or invalidation sequence.

**Evidence for.** AMDGPU documents GPUVM as multiple in-flight protected address spaces and GART as
the kernel GPUVM mapping system resources.[^amdgpu-glossary] This project has historical VMID/root
work and only partial proof of per-client state.

**Evidence against or limiting.** Both 178 runs stop before `submitBuffer`; no workload VMID-2
program or PTE walk exists. This cannot be the current first blocker.

**Discriminator.** Require successful commit and first submit, then capture the exact client
VMID/root and walk one known resource GPUVA. **Accept** on a wrong/invalid translation or missing
invalidation. **Refute** when the submitted address resolves to expected backing before fetch.
Repair the narrow root/PTE/invalidation producer.

## 13. Channel or IB publication fails

**Claim.** Prepared resources reach `submitBuffer`, but the native channel cannot construct or
publish the command descriptor/IB.

**Evidence for.** Channel submission is a necessary distinct boundary, and Linux documents IBs as
larger command streams referenced by rings.[^amdgpu-ring]

**Evidence against or limiting.** Candidate177 and both 178 runs record zero `submitBuffer` calls.
This is deferred.

**Discriminator.** Once map preparation succeeds, retain first submit entry/exit and exact
build-proven descriptor scalars. **Accept** if the native function rejects before a producer update.
**Refute** if the ring/channel publishes the IB. Repair only the first rejected descriptor field or
allocation.

## 14. SDMA, VMID, or queue consumption fails after publication

**Claim.** A submitted IB is not consumed because paging SDMA, the selected VMID/root, MQD/HQD, or
ring producer/consumer state is wrong.

**Evidence for.** AMDGPU documents SDMA as a paging/page-table engine, MQDs/HQDs as queue state, and
rings as software-producer/hardware-consumer structures.[^amdgpu-core][^amdgpu-ring] These areas
required project-specific adaptations.

**Evidence against or limiting.** Native KIQ and engine startup pass, and the Metal workload has not
reached submission. Missing workload callbacks are expected at the current boundary.

**Discriminator.** After first submit, observe selected engine/VMID/root plus wptr/rptr movement.
**Accept** at the first published-but-unconsumed transition. **Refute** when the engine consumes the
IB. Repair that transition rather than forcing all contexts to one VMID.

## 15. Fence or interrupt completion fails

**Claim.** Hardware consumes work but macOS never observes completion because fence emission,
interrupt routing, or signal propagation is wrong.

**Evidence for.** Public AMDGPU distinguishes emitted from signalled fence sequences; a gap marks
outstanding engine work.[^amdgpu-debugfs] Interrupt and fence plumbing is mandatory in passthrough.

**Evidence against or limiting.** No workload submission or consumption exists yet, and orderly KIQ
fences during startup/recovery have worked.

**Discriminator.** For the first consumed workload, capture fence allocation/emission, hardware
write/signalled sequence, and completion callback. **Accept** on a stable gap at one adjacent
boundary. **Refute** on completed status plus correct data. Repair the exact signal path.

## 16. Shader ABI, ISA, or resource binding produces wrong compute values

**Claim.** Commands complete, but the compiled code, dispatch geometry, argument binding, or RDNA2
instruction semantics are wrong for the adapted device.

**Evidence for.** Compile success validates front-end acceptance, not executed machine code. AMD's
RDNA2 ISA is the relevant execution reference once a stream runs.[^amd-isa]

**Evidence against or limiting.** Current commands do not reach submit, so shader behavior cannot
cause today's error.

**Discriminator.** Require completion, then compare all deterministic words and shrink a mismatch
to one buffer/constant/thread. **Accept** on completed but reproducibly incorrect output with
coherency separately proven. **Refute** when all 196,608 values match. Repair compiler/device
features, binding, or dispatch at the demonstrated layer.

## 17. Managed CPU/GPU coherency fails after execution

**Claim.** The GPU writes correctly but CPU readback remains stale or incorrectly synchronized.

**Evidence for.** The probe deliberately uses managed buffers, CPU `didModifyRange:`, and GPU-to-CPU
`synchronizeResource:`; Apple defines managed mode around explicit synchronization.[^apple-managed]

**Evidence against or limiting.** The command never executes. The present zero-work result is not a
coherency observation.

**Discriminator.** Once execution is proven, compare a synchronized managed readback with a small
shared path and a GPU-side checksum. **Accept** if GPU-visible output is correct but synchronized CPU
bytes are stale. **Refute** when managed values match. Repair cache maintenance/synchronization,
not the shader.

## 18. Render layout, tiling, cache, or blit produces wrong pixels

**Claim.** Compute works but the private RGBA8 render target, raster pipeline, surface layout, or
texture-to-buffer blit is wrong.

**Evidence for.** The probe's render phase combines private texture placement, VS/PS execution,
rasterization, store, blit, managed synchronization, and 4,096-pixel validation.[^probe]

**Evidence against or limiting.** Rendering has never been reached and cannot explain pre-submit
NoMemory.

**Discriminator.** After correct compute, separate clear-only, triangle, and texture-to-buffer blit
while retaining exact pixel checks. **Accept** at the first completed stage with wrong pixels.
**Refute** when all 4,096 RGBA values match. Repair the demonstrated tiling/cache/blit stage.

## 19. CAMetalLayer, IOSurface, or WindowServer presentation fails

**Claim.** Offscreen rendering succeeds, but drawable allocation/sharing, present scheduling, or
WindowServer composition is unstable.

**Evidence for.** Apple exposes CAMetalLayer and MTLDrawable as a separate presentation lifecycle
from offscreen command execution.[^apple-layer] The current probe never requests a drawable.

**Evidence against or limiting.** No offscreen render success exists yet. This is a later product
requirement, not a present cause.

**Discriminator.** Render a known pattern into repeated CAMetalLayer drawables, verify scheduled and
completed presentation, then exercise WindowServer turnover. **Accept** when offscreen pixels pass
but drawable/compositor lifecycle fails. **Refute** through repeated correct presentation and clean
shutdown/restart. Repair IOSurface/drawable or compositor integration at the failing call.

## 20. QEMU transport or physical DCN scanout fails

**Claim.** macOS presentation works internally but no image reaches the desired host window or
physical connector.

**Evidence for.** QEMU 10.1.2's VFIO display code requires a VFIO GFX plane exported as DMABUF or
REGION; AUTO can silently continue when neither exists.[^qemu] Public AMDGPU architecture separates
DCN display from GC compute/render.[^amdgpu-core]

**Evidence against or limiting.** No live VFIO GFX-plane query was performed in this research, and
no drawable success exists. A boot framebuffer does not establish accelerated scanout.

**Discriminator.** After macOS drawable/WindowServer success, independently establish an explicit
VFIO plane transport or test the physical DCN connector path. **Accept** when internal frames pass
but the selected transport/link does not. **Refute** with observed frame turnover at the intended
output plus lifecycle stability. Repair the transport or DCN path; do not assume plain
`vfio-pci,display=on` attaches Raphael to QEMU's console.

## Facts now ruled out or narrowed

- Device enumeration, Metal-family advertisement, shader compilation, pipeline creation, command
  queue creation, and front-end buffer object creation are not the failing boundary.
- Candidate178-A/B rule out mapping-batch capacity and **final** GPUVA allocation/reclaim failure
  for their 483 and 531 classified failed calls. They do not prove an earlier VA miss never
  occurred before a recovered retry.
- `GPUVA==0` is not a valid failure test. In this build flags bit 0 is authoritative, and assigned
  raw zero is legal with flags such as `0x21`.[^phase]
- Physical VRAM exhaustion is not proven by the generic `kIOReturnNoMemory` result.
- GPU execution, SDMA workload submission, VMID-2 programming, and fence failure are not the first
  current blocker because `submitBuffer` remains unentered.
- Stale PSP state is not the sole blocker: native startup, KIQ, engine initialization, and orderly
  shutdown/recovery succeed. This does not establish every PSP-mediated feature.
- Correct GART/kernel-root setup does not prove a client resource's backing and PTE commit.
- Offscreen Metal success, when achieved, will not by itself prove QEMU host-window or physical
  display output.
- Candidate178 samples identify kernel map objects and worker threads, not the issuing process or a
  probe nonce. Aggregate agreement supports the path but does not create one-to-one probe identity.

## Proposed single-candidate next diagnostic

The source-backed next design is one additional observation route at exact X6000
`AMDAccelMemoryMap::commitIntoGPUPageTable`, offset `0x3b4d2`, ABI `bool(map *)`, entry span 17 bytes
`554889e5415741564155415453504889fb`.[^commit] It should:

1. use exact 24G830 binary/prologue guards and the existing all-routes-ready/Raphael target gate;
2. forward directly before field reads while inactive;
3. snapshot task `map+0x90`, task mode byte `task+0x268`, raw alternate target
   `map+0x118`, raw `map+0x18`, raw GPUVA `map+0x98`, and full commit flags
   `map+0x138`, without assigning unproven semantic labels or calling vtable `+0x168` again;
4. call native exactly once and return its Boolean unchanged;
5. keep atomic entry/success/false counters by the two task modes after sample buffers fill;
6. retain only a few first false samples, plus an explicitly bounded settled summary;
7. compare commit entries to existing assigned-VA outer failures.

No commit entry distinguishes a pre-commit backing/wiring blocker. A false commit distinguishes the
PTE callback and identifies its native branch. A true commit followed by outer false would reveal a
later path and prevent a false two-way conclusion. `map+0x138` bit `0x40` supplies a native internal
consistency check: the exact function clears it on success and sets it on failure.

The design must not alter resource flags, fabricate a successful return, add MMIO, allocate or log
in the callback, change the probe, or authorize a run. One reviewed candidate can collect both
backing-versus-commit and branch evidence. Further hardware use should follow explicit review of
that evidence rather than a generic retry or cap increase.

## Sources

[^e177]: Private candidate177 evidence: `/home/bogdan/macos-vm/run/metal-010-177/events.jsonl`, SHA-256 `9813152e5403cfc2b4f6d947c2a36ae8fc93cb7ecafd0817ed9330b8de0cd01c`; `serial.txt`, SHA-256 `31dcc1693caf6873e1855d09dcabc9f32599123a02f531262cc4652a70fc6ecb`; analysis `/home/bogdan/src/macos-raphael-igpu/findings/experiments/metal-010-177/notes.md`, SHA-256 `d0667b1a9c0939b7c97f20af8b17e098d1c024087f4349aff04138be80cc302c`.
[^e178a]: Private candidate178-A evidence: `/home/bogdan/macos-vm/run/metal-011-178-a/events.jsonl`, SHA-256 `bca76681ba59335cd4da50815774307ca5cf6bca47ee84a3c3d766a12187a016`; `probe.json`, SHA-256 `076bbc22f0922827ab1d8eda362fa13dea80e2118ab58a1e3e33d76b47e4e743`; `serial.txt`, SHA-256 `c4a877508517dc78402e0b82c42dd5a2a20113a90965a27f92f5b0b6d7ac918`; build `5908f278b80548d6b9c88e2e9a300ae5`, run `f103e47500ed4a06ae346df23250d95d`.
[^e178b]: Private candidate178-B evidence: `/home/bogdan/macos-vm/run/metal-011-178-b/events.jsonl`, SHA-256 `ece23f169283c148b1e5b5b758e539218bf3f20ca6226860ab68b35746455966`; `probe.json`, SHA-256 `b49d5d2c9a2fcf7408ea26d237f2ed11281604c69c0e9805d47ff9677bc61755`; `serial.txt`, SHA-256 `a5b1317d78c52b22d776feec72bb91877b82000c2eb16d03f0d62f9a7d98201c`; build `5908f278b80548d6b9c88e2e9a300ae5`, run `4a45f4a4c1dd49c69fab2dc37e2e4898`.
[^probe]: Exact probe `/home/bogdan/src/macos-raphael-igpu/tests/metal_probe.m`, commit `ef326108b868a00efb292e481ea2efb866205efa`, SHA-256 `f0fc0ced81fe70732c3491cff1557a83d85c9ccb8c18a6303f9070ae1f969d77`, lines 108–197.
[^forensics]: Private exact analysis `/home/bogdan/src/macos-raphael-igpu/findings/experiments/metal-009-176/submission-failure-forensics.md`, SHA-256 `e93a8a6b3e2ee411ffa8126aa5ff3e1dbe7a45d68a48392bc773674be8552423`. Exact X6000 SHA-256 `2e364270c3243c532a9428c670313d5afd20406e42d64edb4fa8f3572504104e`; exact IOAcceleratorFamily2 SHA-256 `1700f3badafbb9014d55b7f6ecde5cdff0d585bd1f0e143c9f8465e4466e5d35`.
[^phase]: Private phase proof `/home/bogdan/src/macos-raphael-igpu/findings/experiments/metal-010-177/memory-map-phase-design.md`, SHA-256 `cfd1a7ed410bb418fc15aff6b5b9f6849e8cb628e29ae88bcdc68f7e9be85f59`. Build-specific offsets: `batchMemoryMapPrepare` `0x6550`; `AMDAccelMemoryMap::prepare` `0x3b3fe`.
[^commit]: Private exact disassembly `/home/bogdan/macos-vm/re/x6000.asm`, lines 64585–64667, from X6000 SHA-256 `2e364270c3243c532a9428c670313d5afd20406e42d64edb4fa8f3572504104e`. `AMDAccelMemoryMap::commitIntoGPUPageTable` is `0x3b4d2`; ABI `bool(map *)`; entry bytes `554889e5415741564155415453504889fb`; task-mode branch at `0x3b4e3..0x3b4f1`; callbacks at `0x3b546` and `0x3b5a5`; result-to-bit-`0x40` logic at `0x3b5ab..0x3b5d9`.
[^apple-managed]: Apple, [Synchronizing a managed resource in macOS](https://developer.apple.com/documentation/metal/synchronizing-a-managed-resource-in-macos) and [Setting resource storage modes](https://developer.apple.com/documentation/metal/setting-resource-storage-modes).
[^apple-layer]: Apple, [CAMetalLayer](https://developer.apple.com/documentation/quartzcore/cametallayer) and [MTLDrawable](https://developer.apple.com/documentation/metal/mtldrawable).
[^amdgpu-core]: Linux kernel documentation, [AMDGPU Core Driver Infrastructure](https://docs.kernel.org/gpu/amdgpu/driver-core.html), “GPU Hardware Structure” and “Memory Domains.”
[^amdgpu-glossary]: Linux kernel documentation, [AMDGPU Glossary](https://docs.kernel.org/gpu/amdgpu/amdgpu-glossary.html), GART, GPUVM, GTT, PTE, SDMA, and VMID.
[^linux-vm]: Linux v6.12 primary source, [`amdgpu_vm.c`](https://github.com/torvalds/linux/blob/v6.12/drivers/gpu/drm/amd/amdgpu/amdgpu_vm.c) and [`amdgpu_vm_sdma.c`](https://github.com/torvalds/linux/blob/v6.12/drivers/gpu/drm/amd/amdgpu/amdgpu_vm_sdma.c).
[^amdgpu-ring]: Linux kernel documentation, [AMDGPU Ring Buffer](https://docs.kernel.org/gpu/amdgpu/ring-buffer.html).
[^amdgpu-debugfs]: Linux kernel documentation, [AMDGPU DebugFS](https://docs.kernel.org/gpu/amdgpu/debugfs.html), ring, IB, fence, and VM sections.
[^amd-isa]: AMD, [RDNA 2 Shader Instruction Set Architecture](https://www.amd.com/content/dam/amd/en/documents/radeon-tech-docs/instruction-set-architectures/rdna2-shader-instruction-set-architecture.pdf).
[^qemu]: QEMU 10.1.2 primary source, [`hw/vfio/display.c`](https://raw.githubusercontent.com/qemu/qemu/v10.1.2/hw/vfio/display.c), `vfio_display_probe`, lines 478–502; QEMU documentation, [VirtIO GPU](https://www.qemu.org/docs/master/system/devices/virtio/virtio-gpu.html).
