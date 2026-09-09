# Astra adversarial review: a capped-out native VMM arena

**Review cut:** 2026-09-09 21:45 UTC / 2026-09-10 local. Reviewed on dev, HEAD
ef326108b868a00efb292e481ea2efb866205efa, against current status.md, exact
24G830 binaries, frozen runs, and concurrent uncommitted implementation.
This is the mandatory fourth-cycle review, using gpt-6-astra / xhigh.

The requested prompt was:

> review whatever the current status.md of this project is, check its documentation, methodology, tests, experiments. figure out why this fails and report back in a report-astra.md file for other agents to review

The original report is preserved byte-for-byte at
[the dated archive](findings/research/astra-reviews/2026-09-09-2138-original/report-astra.md),
SHA-256 0ebfab9c494ee8183392c6d03bcec0c58132b154dc30733528b3f6f095fcf3bf.
This review modified only this report. No VM, device/VFIO/MMIO access, sudo,
reset, recovery, build, deployment, ledger mutation, or commit was performed.

## Finding and decision

**The strongest current explanation is more specific than general VRAM exhaustion:
the 240 MiB cap excludes the upper part of Apple's fixed 68 MiB VMM arena. Native
VMM initialization then cannot reserve that arena in its software pool and can
leave the page-table allocators uncreated.** Existing logs check only whether the
DMA paging channel exists, missing this distinct failure after channel creation.

The exact binary establishes the complete reservation/rejection chain below.
The captured pool sizes and inferred arena interval satisfy its failure condition.
The final runtime fields VMM+0x58/+0x78/+0x80 were not recorded, so this is a
strong, mechanically specified causal hypothesis, **not yet a measured attribution
of candidate178's failed map to that branch**. Live dispatch, intervening pool
mutation, and the failed map's selected backend remain runtime checks.

Prioritize this chain and its smallest observation before another broad hypothesis
matrix or an unchanged diagnostic run. Complete and review the native recovery
lease because the old fixed range has a demonstrated ownership conflict. Retain
256/256 MiB semantics and early VMM channel creation for the first functional
candidate; remove the obsolete early software-pool initialization and 240 MiB rewrite.
The first test should check the native VMM arena and its two allocators, then reuse
the unchanged checked Metal probe. Submission is progress, not desktop acceleration.

The stalled issue remains unresolved across **at least four actual cycles**:

| Cycle | Run ID | Observation |
|---|---|---|
| 176 | e02fbed46a6a4df4ae48d7c1d8597985 | NoMemory; no completed Metal command |
| 177 | ff2eb6e2492a4c5c96c6c6a847ed0c26 | NoMemory; zero observed submit entries |
| 178-A | f103e47500ed4a06ae346df23250d95d | 483 backing/PTE failures; zero submit entries |
| 178-B | 4a45f4a4c1dd49c69fab2dc37e2e4898 | 531 backing/PTE failures; zero submit entries |

Offline discoveries do not reset this count or reopen the terminal 6/6 ledger.

## Newly resolved native failure chain

All X6000 offsets refer to executable SHA-256
2e364270c3243c532a9428c670313d5afd20406e42d64edb4fa8f3572504104e.
IOAcceleratorFamily2 refers to
1700f3badafbb9014d55b7f6ecde5cdff0d585bd1f0e143c9f8465e4466e5d35.
I independently verified both local hashes, read the instruction intervals, and
resolved the cited vtable entries from Mach-O segments with llvm-nm symbol names.

### 1. Top-down allocation gives the VMM a fixed 68 MiB address

AMDHWVMM::setVirtualSpaceReady(true), X6000 0x578ce, calls hardware vslot +0x180
with type 1, size 0x04400000, alignment 0x1000 (0x578e3..0x578f2). The
Navi23 table resolves this to AMDHardware::appendToReservedVRAMOffset at
0x72afe. With equal size fields, type 1 falls back to the type-0 top-down cursor.

The method adds framebuffer base and stores the full result at VMM+0x50
(0x57908..0x57915). It is native **void**; old wrappers incorrectly logged an
incidental 32-bit return. Combining logged low value 191922176, the exact
store sequence, and framebuffer base 0xf400000000 yields:

| Range | Half-open interval |
|---|---|
| Inferred VMM BAR offsets | [0x0b708000, 0x0fb08000) |
| Inferred full VMM addresses | [0xf40b708000, 0xf40fb08000) |
| Capped software pool | [0xf400000000, 0xf40f000000) |

The arena extends **0x00b08000 bytes, 11.03125 MiB**, beyond the capped pool.
171 and 178-B record the same inferred VMM base. The defect is an end-address
mismatch, not merely insufficient total free bytes elsewhere: fixed reservation
requires the entire interval represented in a free span.

### 2. The VMM guard skips channel creation, not arena reservation

AMDHWVMM::setMemoryAllocationsEnabled(true) begins at 0x5791e.
At 0x57938..0x5793d, non-null VMM+0x20 jumps to **0x57ba8**, not the return.
The skipped block creates the channel and attaches existing contexts.
The common continuation always performs:

1. Obtain the handler through hardware vslot +0x2c8.
2. Call handler vslot +0x1d8 with VMM+0x50, length 0x04400000,
   flags 0x80000, Boolean true, origin 0x22, and operation 0x19.
3. Store its result at VMM+0x58.
4. Return if that result is null.

The factory call is at 0x57bdc; store/null branch are 0x57be3..0x57bea.
Nesting at VMM+0x3c is not this initialization gate.

Early rgpuvmm=3 can therefore create +0x20/+0x28/+0x30 while software pools
are empty, fail arena reservation, and leave those channel pointers present.
The later native enable **retries the arena even when the channel already exists**.
Calling the entire method idempotently skipped once +0x20 exists was incomplete.

### 3. The exact factory reserves the arena through AMDHWMemory

| Dispatch | Exact target |
|---|---|
| Navi23 hardware table 0x185010, address point +0x10, slot +0x2c8 | Getter 0x9df5e returns hardware+0x18, the handler |
| AMDHWHandler table 0x16f698, address point +0x10, slot +0x1d8 | createVidMemoryWithPhysicalAddress at 0x4ab86 |
| Factory call 0x4abb6 | AMDAccelVidMemory::withPhysicalAddress at 0x3a830 |
| Hardware slot +0x2d8 inside that factory | Getter 0x9df76 returns hardware+0x370, the memory object |
| AMDHWMemory table 0x172080, address point +0x10, slot +0x198 | AMDHWMemory::reserve at 0x5343c |

The true argument selects withPhysicalAddress's reserve branch
(0x3a88e..0x3a8c7). It passes the exact full address and length into
AMDHWMemory::reserve, with both-pools true. A false result releases the video
object and returns null (0x3a8ce..0x3a8eb). **This path does not need to call
AMDAccelVidMemory::allocPhysical at 0x3aa76.**

AMDHWMemory::reserve first calls framework interval reserve on pool +0x68
(0x53487..0x5349f). Framework containment requires the requested start/end
inside one free interval (0x1f986..0x1f998). A pool ending at
base+0x0f000000 cannot reserve an arena ending at base+0x0fb08000.
It fails before the second pool. This also explains why the 4 MiB
allocateLargeBlocks error string can disappear: fixed-address reserve failure
does not use that diagnostic path.

### 4. Channel presence does not imply page-table allocation readiness

Only a non-null arena at VMM+0x58 reaches:

- Native clearWithDMA of the arena, 0x57c00..0x57c0b, then channel submission
  handling at 0x57c10..0x57c37.
- Creation and initialization of a **64 MiB allocator at VMM+0x78**,
  0x57c3d..0x57ca2.
- Creation and initialization of a **4 MiB allocator at VMM+0x80**,
  0x57ca4..0x57d13.

AMDHWVMM::allocVMBlock, 0x57ed2, returns false immediately when +0x78
is null (0x57ee3..0x57eea, failure 0x57f71). Valid task VA and an existing
DMA channel can therefore coexist with no usable VM page-table allocator.
That fits candidate178's assigned-VA, backing/PTE failure family.
The failed live map's selected backend remains unrecorded; keep that final
association conditional.

**Smallest discriminating observation:** extend the existing VMM set-allocation
wrapper's scalar record with full +0x50 and pointers +0x58/+0x78/+0x80 before
and after early and final native calls. Distinguish those calls and record
pool sizes/identities at the final one. No new private route or virtual invocation
is needed to read these established fields. Non-null pointers are prerequisites;
verify initialized extents/free state before claiming usable allocators.
Capture entry and native clear progress so a stall before return is not mistaken
for absence of initialization.

## Other report claims checked against source

**The proposed total/visible swap is wrong.** Native initialization clamps size1
to size0 only when size1 > size0 (0x525f5..0x52603). Swapping the measured
512/256 to 256/512 collapses back to 256/256.

Framework init_pool with three numeric arguments at 0x1facc means
(totalEnd, reservedStart, reservedLength). X6000's unequal branch calls it with
(base+512MiB, base+256MiB, 0), then reserves [0,base) separately.
It does not create an inverted interval.

The zero-length reservation is also **not a no-op**. Framework reserve's interior
branch 0x1fa49..0x1fab2 inserts a zero-length allocated element and another free
node at the marker. Free bytes do not decrease, but contiguous allocation checks
the next address-list boundary (allocPages, 0x1fce2..0x1fd19). This represents
a placement seam at the BAR boundary; noncontiguous allocations may handle pieces
separately. Simple capacity arithmetic does not reproduce this policy.

**The old recovery interval lacks exclusive ownership.** Descriptor 0x0f000000
and scratch [0x0f100000,0x0f113004) lie inside the inferred VMM arena.
Later pool capping cannot exclude earlier top-down reservations. Actual corruption
of the overlapping bytes was not captured, but the ownership design is unsound.
The proposed uncapped diagnostic leaving scratch there is rejected. Moving it to
an apparently empty fixed gap is unsupported without the older native owner ranges.

**Duplicate initialization is real, but does not isolate the historical regression.**
init_pool rebuilds allocator state, and both 171 and 178 have an early forced
call followed by a native call. No preserved object is proved to be a live
allocation from those same software pools between calls. VMM top-down allocation,
MQD/EOP offsets, and SYSTEM-backed rings are different domains.

Removing the obsolete forced call allows one authoritative initialization followed
by lease exclusion. Retaining rgpuvmm=3 is compatible with the later arena retry
shown above; its early channel creation originally preceded the forced memory
initialization anyway. Native powerUpHW intentionally enables the software pools
after engine startup. This source ordering supports the selected placement;
validate startup after removal because project adaptations can introduce dependencies.

**Replace the 183 MiB/four-connector inference with an actual consumer.**
reserveNDRVSpace, X6000 0x52f2, reserves an NDRV/framebuffer extent, then
attempts a fixed **160 MiB** at base+NDRVSize (0x5437..0x544e).
Navi23's default hardware size getter at 0x9df00 returns 5 MiB; a valid
framebuffer fbrs attribute can override it. Failure aborts powerUpHW
(0x50af..0x50b1). This is a concrete capacity consumer to observe if necessary.
The runtime fbrs amount and allocation occupancy were not captured here.
Do not infer per-head consumption from the MQD address or reduce connectors yet.

**Historical SDMA remains downstream.** 171 reached WindowServer paging work.
Its later dump shows a consumed GFX IB and unconsumed SDMA paging IB at different
VAs. Q1 HALT follows a restart path, so it does not establish the pre-timeout
cause. Same VMID does not give different IBs identical mappings or invalidation
history. Restored arena initialization itself emits native DMA clear work before
the Metal probe; an SDMA problem may reappear there. Recovery must cover that work.

## Version-2 lease: reasonable architecture, incomplete integration

The selected architecture is reasonable: outside-VRAM launch challenge, one
native type-0 allocation before VMM, immutable OWNED proof, and separate pool
status. With 256/256 semantics the later type-1 VMM request uses the same cursor
and moves below the lease. Exclude the exact full lease address in both software
pools before the memory-enable wrapper returns. Native powerUpHW tests that
return at 0x509f before NDRV reservation/client enable, preserving a false result.

The first candidate must verify the dynamic VMM arena is below and disjoint
from the lease, within the pool, and compatible with native/GART ownership.
Wire arithmetic alone cannot establish this.

The worktree changed concurrently. These issues were sent to the coordinator;
they are **snapshot findings, not claims about final corrected code**:

| Priority | Snapshot issue | Required check |
|---|---|---|
| Blocking | Guest OWNED/POOL text printed nonce high then low; Python interpreted low then high | Actual producer text and struct bytes round-trip with unequal nonce halves |
| Blocking | Optional status readback treated arbitrary bad state/checksum as unfinished | Only the defined unpublished marker is unfinished; corrupt committed or contradictory published data refuses recovery |
| Blocking | Route, epoch, native ownership, and admission checks were still separate from helper tests | Exercise exact production readiness, failure propagation, duplicate, disable/free, and no-client paths |
| High | One-shot ACTIVE publication could remain while later duplicate/invalid epoch failed | No accepted stale ACTIVE after ownership/exclusion lifetime ends |
| High | Tested establishPools sequencing was not yet the actual wrapper in an inspected snapshot | Integrate the tested production sequence or directly test the wrapper |

The coordinator independently found overlapping issues and is directing fixes.
This report is assessment input, not launch approval. OWNED-only early-crash
recovery must never imply no queues. Missing ownership/locator proof cannot
authorize guessed scratch. Historical v1 receipt compatibility does not admit v1
for a new launch.

## Methodology and test review

I freshly verified **all 27 hashes in 178-A and 29 in 178-B**.
Final traces show 483 and 531 backing/PTE failures, zero capacity/VA/unknown
classifications, zero submit entries, and zero completed Metal commands.
Those 1,014 calls include retries/background work; they are not independent
resources or GPU cycles. Sample identities do not bind maps to probe buffers.

| Evidence | Reached stage | Limit |
|---|---|---|
| 166-reuse / 170 | Occupied-channel diagnostics; 14 / 23 exact allocator-error-string matches in these archives | Older configurations; unequal observer coverage |
| 171 | Three valid archived SDMA submission records; fourteen 4 MiB allocation errors | Failed workload, no Metal acceptance |
| 175 | Active cap, no retained equivalent client submission evidence | Probe withheld; not a completed Metal attempt |
| 176 | NoMemory, no retained valid SDMA submit | Lacks the later direct submit observer |
| 177 / 178-A / 178-B | Explicit zero submit entries and failed probe | Native VMM arena/allocator state not captured |

report.md counts 24 errors in 170; I counted **23 exact matches** for
"AMD ERROR! Failed to allocate" in this repository archive. Interleaving or a
different retained file may explain it. This minor discrepancy does not affect
the lost-stage conclusion, whose build/configuration confounding remains explicit.

Three test gaps matter:

1. **Mock ordering is not native initialization proof.** Fake successful append,
   enable, and reserve callbacks validate a helper's ordering, not the VMM
   continuation, arena factory, zero-length seam, allocator reset, or DMA clear.
   Add a source-grounded dependency fixture for a fixed arena crossing the cap
   and the final VMM retry, then measure corresponding fields in the admitted run.
2. **The allocPhysical observer does not cover the newly resolved factory.**
   Its immutable samples and independent live counters avoid old slot races.
   Zero failures there cannot refute fixed-address VMM reservation failure.
   Native false also need not mean exhausted bytes: a nonzero incoming element
   returns false immediately, and flags affect later return paths.
3. **The regression tool overstates some evidence.** In the inspected
   functional-regression.py, positive counters alone produce stages called
   compute/render acceptance; receipt booleans alone produce cleanup.
   Startup identity plus no capture-loss record may produce negative evidence
   without whole-workload coverage. Reuse production probe/receipt validators
   or label these claimed partial progress. A startup-only zero summary must
   not prove later absence. The complete manually reviewed A/B traces still
   support their actual conclusion.

Do not repeat the stalled workload merely to collect a fifth repetition.
Preserve frozen raw verdicts, but distinguish functional outcome, observed
boundary, capture sufficiency, and lifecycle. Lifecycle passing does not
substitute for acceleration.

## Revised hypothesis and smallest useful functional test

**H1:** the late cap prevents fixed-address acquisition of the VMM's 68 MiB arena;
the paging channel exists but its page-table allocators do not. Removing the cap
through an exclusively owned compact lease should allow the final native VMM
call to create them. This can re-expose the historical SDMA paging/clear stall.

Before hardware, the coordinator and implementation agents should verify the
dispatch chain above, add existing-wrapper observations, close lease/parser
defects, and test receipt compatibility and production sequencing. Keep 256/256,
rgpuvmm=3, current SDMA/PTE behavior, VBIOS connectors, and the acceptance probe.
Restoring 512/256 changes the secondary top-down domain and is a later experiment.

Once a separate finite experiment is validly admitted:

| Observation | Required/predicted result | Interpretation |
|---|---|---|
| Early VMM enable, before pools | Channel present; arena may be null | Expected early arena miss does not alone stop startup |
| Lease and sole pool enable | Native ownership; 256/256 fields; exact both-pool lease exclusion | Ownership/capacity prerequisite |
| Final native VMM enable | +0x58/+0x78/+0x80 initialized; arena inside pool and disjoint from lease | Direct progress through the identified boundary |
| Native arena clear | Progress/completion evidence or localized stall | SDMA may receive work before Metal probe |
| Unchanged probe | Compare preparation/submission against 171 and 178-B; check expected values/pixels | Submission is progress, full correctness still required |
| Cleanup | Existing independent queues, GART, PSP, journal, receipt checks | Normal, early failure, and crash cases remain distinct |

If final arena/allocators stay absent, inspect the exact factory and actual native
intervals; do not move to shader/display changes. If they initialize but maps
still fail, H1 alone is insufficient: follow the concrete backing return and
selected commit callback/range. If native clear or submitted work stalls, record
the reached boundary and investigate its exact queue/VM/fence state.
If startup regresses after removing early memory enable, explain that dependency;
it is not a clean refutation of H1.

**No new GPU run occurred. Metal execution and desktop acceleration remain
undemonstrated.** This report claims neither completion nor hardware approval.

## Evidence anchors and snapshot limits

- Authoritative [status.md](status.md), frozen
  [171](findings/experiments/metal-005-171/),
  [178-A](findings/experiments/metal-011-178-a/),
  [178-B](findings/experiments/metal-011-178-b/).
- Exact X6000 listing: /home/bogdan/macos-vm/re/x6000.asm. Executable:
  /home/bogdan/macos-vm/kdk/x/System/Library/Extensions/AMDRadeonX6000.kext/Contents/MacOS/AMDRadeonX6000.
- Framework listing: /tmp/ioaccel.dis. Reviewed executable:
  /tmp/kdk-forensics.HZuAtO/IOAcceleratorFamily2. Durable KDK extraction and
  hash instructions are in
  [report-backing-review.md](findings/research/2026-09-metal-integration/report-backing-review.md).
- Related reviews: [memory](findings/research/report-memory-review.md),
  [recovery](findings/research/2026-09-metal-integration/report-recovery-review.md),
  [original external report](report.md). The new VMM continuation analysis
  supersedes interpretations that treat channel presence as arena readiness.
- Mid-review hashes identify criticized concurrent snapshots:
  RaphaelGPU.cpp e206b20612b46948944f4662dc2aaa375a1762b4932882c9d942b54fc34de92e;
  RecoveryLease.hpp aa6be6adc4f04d7e23f0d2c3eda7d78cc583f156c953029136fb48768b6e90f6;
  recovery_lease_v2.py e81fd24e7571a4b0d9f89d728614a3e6dd912a1f45dcc37f8050bf7bd0078f04;
  functional-regression.py 370496633b22fb2e2d83aa30cf79cba1d6621f618b1485be94efb28a667591c6.
  These are development snapshots, not release identities.

Fresh checks were read-only hash, text/JSON, native dispatch, and instruction
analysis. No fresh driver/unit-test pass or native execution result is claimed.
