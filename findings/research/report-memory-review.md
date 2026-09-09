# Memory-cap regression and native recovery-lease review (24G830)

Updated: 2026-09-10 UTC  
Scope: read-only static analysis of `report.md`, `report-astra.md`, the exact local 24G830
framework binaries/disassembly, candidate 171, and candidate 178-A/B. This note proposes a
review contract only. It does not authorize a build, VM launch, VFIO access, MMIO, or recovery.

## Decision

The proposed `size0=256 MiB, size1=512 MiB` swap in `report.md` is not a valid fix. The native
driver requires `size1 <= size0` and would immediately clamp that proposal back to
`256 MiB / 256 MiB`. The report also misreads the three-argument IOAcceleratorFamily2 pool
initializer: its arguments are a total endpoint, a reservation start, and a reservation length.
They are not a start/end pair. Apple's measured `512 MiB / 256 MiB` values therefore do not
construct an inverted pool.

The current workaround still creates a proven ownership/capacity defect, although the preserved
runs do not establish it as the functional cause of the Metal failure. It first overwrites Apple's
`512 MiB / 256 MiB` values with `256 MiB / 256 MiB`, then the recovery handshake overwrites both
again with `240 MiB / 240 MiB`. Equalizing the fields also changes the native type-1 reserved-VRAM
allocator into its type-0 fallback. Candidate 178's low 32-bit VMM value, combined with the exact
native arithmetic and the zero low 32 bits of the framebuffer base, identifies a native 68 MiB
reserved interval at BAR offsets `[0x0b708000, 0x0fb08000)`. The fixed recovery descriptor at
`0x0f000000` and scratch writes through `0x0f113004` are inside that interval. This is a concrete
ownership conflict even though the preserved runs do not prove that overlapping bytes were
actually corrupted.

The smallest coherent first functional delta is therefore:

1. retain the existing `256 MiB / 256 MiB` equalization temporarily, because restoring
   `512 MiB / 256 MiB` changes the native type-1 allocation domain to an unmeasured secondary
   provider window;
2. remove the forced early `rgpumem=2` call, leaving exactly one native pool initialization;
3. replace the fixed top-16-MiB recovery area with a launch-bound, native-owned dynamic type-0
   lease obtained immediately before the native VMM reserves its 68 MiB arena;
4. after the sole native `enableAllocations` initializes both software pools, reserve the same
   dynamic lease in both pools before returning to ordinary clients; and
5. refuse queue/client startup or host recovery unless the phase, nonce, bounds, publication,
   and both-pool exclusion checks appropriate to that point succeed.

This first delta removes the demonstrated overlap and duplicate reset without relying on the
unverified secondary reserved-VRAM window. Restoring the native `512 MiB / 256 MiB` fields is a
separate follow-up after that window's provider values and effective pool behavior are captured.

## Exact evidence identity

| Item | SHA-256 |
|---|---|
| 24G830 `AMDRadeonX6000` binary | `2e364270c3243c532a9428c670313d5afd20406e42d64edb4fa8f3572504104e` |
| `/home/bogdan/macos-vm/re/x6000.asm` | `bf7a9c911fb793aabee8e6611b098e24c63f698c461d784a08fe2e316948a50b` |
| local `/tmp/ioaccel.dis` extraction | `85e957220ed9246aa6819524edbbdb311c4396af4a10ac2bea08dc492cae6b43` |
| `report.md` | `71753863c18c3ae0d623b391f6d3c550017466fe1df4b8799200a749ce67d7de` |
| `report-astra.md` | `0ebfab9c494ee8183392c6d03bcec0c58132b154dc30733528b3f6f095fcf3bf` |
| candidate 171 serial | `69c23ffb109a2583f2b163e926ac98b82a38499a72ae1ca8f7ba0e6710e67112` |
| candidate 178-A serial | `c4a877508517dc78402e0b82c42dd5a2a20113a90965a27f92f5b0b6d7ac918c` |
| candidate 178-B serial | `a5b1317d78c52b22d776feec72bb91877b82000c2eb16d03f0d62f9a7d98201c` |

The IOAcceleratorFamily2 listing is currently a temporary local extraction. Its hash identifies
the bytes consulted here but is not durable evidence by itself; the relevant intervals should be
archived with reproducible extraction instructions before an implementation milestone is signed.

## Native size producer and field semantics

`AMDHWMemory::init` at X6000 `0x524ea` creates the two
`IOAccelMemoryAllocator2` instances stored at `AMDHWMemory+0x68` and `+0x70`, initializes both
with an empty pool, and calls `AMDHWMemory::initVRAMInfo` at `0x525e8`.

`initVRAMInfo` at `0x527a4` obtains a producer via the hardware interface's vslot `+0x2c0`, then
calls that producer's vslot `+0x18` with a 0x48-byte output structure. The consumer assignments
are exact:

| Producer structure | `AMDHWMemory` field | Candidate 178-B value |
|---|---|---|
| `+0x00` | `+0x50`, framebuffer base | `0xf400000000` |
| `+0x08` | `+0x40`, size 0 | `0x20000000` (512 MiB) |
| `+0x10` | `+0x48`, size 1 | `0x10000000` (256 MiB) |
| `+0x18` | `+0x58`, physical framebuffer base | `0x840000000` |

The assignments are at `0x52800..0x52823`. Candidate 178-B records the same values at
[`serial.txt`](../experiments/metal-011-178-b/serial.txt) line 2415 and independently records the
512 MiB aperture at line 1823.

The native guard at `0x525f5..0x52603` is decisive: it loads `+0x40`, compares `+0x48`, and only
when `size1 > size0` writes `size1 = size0`. Thus the legal native relation is
`size1 <= size0`. The Claude proposal to swap the measured values would be normalized as:

```text
proposed: size0 = 0x10000000, size1 = 0x20000000
native guard: size1 > size0
effective: size0 = 0x10000000, size1 = 0x10000000
```

The current wrapper at [`src/RaphaelGPU.cpp`](../../src/RaphaelGPU.cpp) lines 2368-2413 instead
asserts that the unequal branch is inverted and changes both fields to the smaller value. That
premise is contradicted by the exact allocator implementation below.

## Exact IOAcceleratorFamily2 overload semantics

The relevant local functions are:

| Function | Offset | Proven behavior |
|---|---:|---|
| `init_pool(uint64_t totalEnd)` | `0x1f784` | Resets allocator bookkeeping and records `totalEnd` at allocator `+0x50`. |
| `init_pool(uint64_t base, uint64_t length)` | `0x1f8e8` | Calls `init_pool(base+length)`, then reserves `[0,base)`. |
| `init_pool(uint64_t totalEnd, uint64_t reservedStart, uint64_t reservedLength)` | `0x1facc` | Calls `init_pool(totalEnd)`, then reserves `[reservedStart,reservedStart+reservedLength)`. |
| `reserve(element,start,length)` | `0x1f92c` | Finds the requested interval in the free list and subtracts `length`; zero length is accepted if the point is representable. |

At `0x1facc`, the three incoming values are preserved as `RCX -> R14` (length), `RDX -> R15`
(start), while `RSI` remains the total endpoint for the call to `init_pool(uint64_t)`. The
subsequent reserve call passes `RSI=null element`, `RDX=R15`, `RCX=R14`. This is not an interval
constructor receiving two endpoints.

Apple's unequal path in `AMDHWMemory::enableAllocations` (`0x52a71..0x52a99`) calls both pools
as follows for the measured fields:

```text
totalEnd      = base + size0 = base + 512 MiB
reservedStart = base + size1 = base + 256 MiB
reservedLen   = 0
```

It then invokes `AMDHWMemory::reserve` through vslot `+0x198` at `0x52abf` with offset 0,
length `base`, both-pools true, and origin `0x22`. That reserves `[0,base)` and leaves the usable
address domain starting at `base`. The trailing hardware-interface vslot `+0x2a0` resolves through
the exact AMDHardware, AMDRTHardware, and Navi23 vtables to `AMDHardware::isDeviceValid` at
`0x70896`; it is a readiness predicate and performs no memory allocation.

Therefore the report's “backwards range” and its proposed field swap are both disproved. The
zero-length marker at `base+256 MiB` may still carry framework meaning, but the listing does not
justify calling it a hard pool boundary. Its effect must be tested from native behavior rather
than inferred from parameter names.

`init_pool(uint64_t)` at `0x1f784..0x1f8e7` also confirms that a second call is a real reset: it
zeros allocator state and rebuilds list structures over offsets through `0x510`. It is not an
idempotent “already enabled” check.

## Native VMM reservation and the fixed recovery conflict

`AMDHWVMM::setVirtualSpaceReady(true)` at `0x578ce` calls hardware vslot `+0x180` with:

```text
allocation type = 1
size            = 0x04400000 (68 MiB)
alignment       = 0x1000
```

The exact Navi23/GFX10 hardware vtables resolve this slot to
`AMDHardware::appendToReservedVRAMOffset` at `0x72afe`. The function allocates top-down:

- type 0 subtracts from `AMDHardware+0x340` and updates used bytes at `+0x348`;
- type 1 uses `+0x350/+0x358` only when memory getter `size0 > size1`;
- otherwise type 1 falls back to the type-0 path.

The current equality rewrite makes the type-1 request fall back to type 0. Candidate 178-B line
2551 logs decimal `191922176`, which is exactly `0x0b708000`, not `0x0b70a000`. The native VMM
method is `void`; the wrapper currently declares a 32-bit return and logs an incidental truncated
register. The value is still useful only when combined with the exact native instructions:
`0x578f2` returns the reserved offset, `0x57908` obtains the framebuffer base, and
`0x5790e..0x57915` adds the two and stores the full 64-bit address at `VMM+0x50`. Because the
measured base `0xf400000000` has zero low 32 bits, the logged low word identifies this run's BAR
offset.

The resulting interval is:

```text
VMM BAR offsets:       [0x0b708000, 0x0fb08000)
VMM full addresses:    [0xf40b708000, 0xf40fb08000)
recovery descriptor:   [0x0f000000, 0x0f000048)
recovery scratch writes:[0x0f100000, 0x0f113004)
GART observed start:     0x0fdfc000
```

Both current recovery write intervals are contained in the 68 MiB native interval. The GART
starts after the VMM interval ends and is disjoint from the actual recovery writes, consistent
with the prior recovery-range correction. The old top-16-MiB allocator cap cannot protect
allocations made before pool initialization through this separate native top-down allocator.

`AMDRTHardware::getReservedVRAMForSwip` (`0x5def6`) supplies the top-down cursors from a provider
structure into hardware `+0x340/+0x348/+0x350/+0x358`. `AMDRTHardware::setVirtualSpaceReady`
calls it at `0x5e0c9` before dispatching `setVirtualSpaceReady(true)` to VMM and the engines.
The preserved logs do not record the complete provider structure or the secondary `+0x350`
window. Restoring unequal `512/256` would make type 1 select that secondary window; if its cursor
is zero or otherwise unsuitable, the 68 MiB request can fail or move into an unverified domain.
That is why full native-size restoration must not be bundled blindly with the first fix.

## Duplicate initialization: proven reset, unproven live same-pool loss

Candidate 178-B proves two calls on the same pool objects:

```text
2555  forced rgpumem path calls enableAllocations
2558  same pool0/pool1, 240 MiB fields
2559  first enable returns 1
2576..2696 KIQ and engine setup
2739  native enable enters on the same pool0/pool1
2740  second enable returns 1
2741  native VMM allocation-enable path
```

Candidate 178-A has the same order at lines 2539-2543 and 2723-2724. The current graft is in
[`src/RaphaelGPU.cpp`](../../src/RaphaelGPU.cpp) lines 4001-4027. The native
`AMDHWMemory::setVirtualSpaceReady` it wraps is only six bytes at `0x52c3a` and does no work.

The reset hazard is real, but the reports do not prove that a live allocation from the
`IOAccelMemoryAllocator2` objects at `AMDHWMemory+0x68/+0x70` exists between the calls:

- the VMM 68 MiB block uses `appendToReservedVRAMOffset`, a distinct hardware cursor domain;
- the observed KIQ MQD/EOP uses native reserved offsets near `0x0b706000`;
- ring addresses such as `0xffbfea00` are backed by SYSTEM PTEs in the captured page-table
  evidence; and
- no preserved record binds a fence or another intervening object to either software pool.

Thus “the second init forgot live same-pool allocations” remains unproven. Removing the obsolete
forced call is nevertheless justified because the native power path now reaches the same method,
the first call resets real allocator state, and no current dependency requires it. Queue startup
must be gated on recovery-lease ownership directly rather than retaining this graft as an
accidental activation mechanism.

The analogous `rgpuvmm=3` forced VMM allocation-enable is different. Candidate 178-B lines
2551-2553 show it creates non-null VMM `+0x20/+0x28/+0x30` before early KIQ/engine setup; native
enable is only reached later at line 2741. Removing it in the same delta risks losing the DMA
paging channel needed by the already working startup path. Keep it for the first lease test and
audit its necessity separately.

## Proposed recovery-lease v2 contract

The fixed PEND descriptor must not remain active while the pool cap is removed. The new protocol
should use the run's manifest-bound nonce from a bootstrap channel outside VRAM and these explicit
phases.

### Phase 0: REQUESTED, outside VRAM

- The coordinator prebinds one run nonce, expected binary/source/config, and lease schema.
- The nonce reaches the guest through a reviewed boot property or argument; the host does not
  write a PEND descriptor into a guessed VRAM interval.
- Existing source-clean, receipt, watchdog, journal, inhibitor, identity, and one-use admission
  gates remain unchanged.

### Phase 1: OWNED, native top-down reservation

- In the VMM `setVirtualSpaceReady(true)` wrapper, before calling the original VMM method, obtain
  the hardware object from `VMM+0x10` and call its vslot `+0x180` with type 0, size `0x15000`,
  alignment `0x1000`.
- This point is after `getReservedVRAMForSwip` populated the type-0 cursor and before the original
  VMM method consumes 68 MiB. The native cursor update makes later VMM/MQD/EOP appends proceed
  below the lease rather than through it.
- Reject `-1`, misalignment, overflow, an interval outside the BAR-visible 256 MiB, duplicate
  acquisition, or a nonce/generation mismatch.
- Layout: descriptor in the first page; rebase current host KIQ ring/MQD/RPTR/WPTR/EOP/fence
  offsets from lease base `+0x1000`. The current highest byte is relative `+0x14004`, so a
  page-aligned `0x15000` lease contains every write with an explicit end bound.
- Only after native append and bounds checks succeed, write and read back an `OWNED` descriptor
  in the lease and publish a bounded locator, nonce, generation, base, and end to the durable
  serial capture.

The proposed immutable ownership wire record is 80 bytes, little-endian
`<QIIQQQQQQQQ>`: magic `RGPUKIR2`, version 2, state `OWND`, lease offset, lease end, scratch
offset, scratch end, nonce low, nonce high, generation, and checksum. The descriptor lives at
lease `+0x000`; its bytes never change after publication.

This native cursor ownership is sufficient for host recovery if the guest dies during early KIQ
startup before software pools exist. No ordinary software-pool allocation can occur before those
pools are initialized. KIQ preparation must require a valid in-memory OWNED lease and must refuse
to start if acquisition/publication failed.

### Phase 2: ACTIVE, both software pools exclude the lease

- Remove the forced `rgpumem=2` call. Let the native power path invoke `enableAllocations` once.
- Preserve `size0=size1=256 MiB` for this first delta; remove the old 240 MiB mutation.
- After the original native `enableAllocations` succeeds but before its wrapper returns, compute
  the full software-pool address as `AMDHWMemory+0x50 + lease BAR offset`, rejecting 64-bit
  overflow, and call `AMDHWMemory::reserve` vslot `+0x198` with a retained
  `AMDMemoryElement*` output, that exact full address, length `0x15000`, `both=true`, and a
  reviewed origin value. Passing the raw BAR offset would target the wrong address domain.
- `AMDHWMemory::reserve` is at `0x5343c`. It allocates an internal descriptor, reserves pool 0,
  links it into `AMDHWMemory+0x88`, stores it through the output pointer, and attempts pool 1 with
  the embedded element at descriptor `+0x30`. The implementation does **not** propagate the
  second pool's return value. Therefore `bool true` alone is insufficient: record both pools'
  total-free values immediately before and after and require each to fall by exactly `0x15000`;
  also require a non-null retained element and exact interval fields. Any mismatch is failure.
- Keep the returned `AMDMemoryElement*` for the allocation lifetime. Do not free it during normal
  operation. A subsequent pool initialization after ACTIVE is a protocol violation.
- The OWNED descriptor is immutable after its first publication. Only after both exclusions
  validate, write and read back a separate one-shot ACTIVE pool-status record in the descriptor
  page and publish its matching locator/generation record. A failed check may publish a separate
  one-shot INVALID pool-status record, but never rewrites the ownership descriptor.
- Ordinary client submission requires ACTIVE. A failure marks the descriptor INVALID, blocks
  clients, and closes the run without trying another initialization or lease.

The proposed pool-status wire record is 104 bytes, little-endian
`<QIIQQQQQQQQQQQ>`: magic `RGPUKPS2`, version 2, state `ACTV` or `INVL`, lease offset, lease
end, nonce low, nonce high, generation, pool-0 before/after, pool-1 before/after, reason, and
checksum. It lives at lease `+0x100` and is written once. Absence means the run remains in the
early OWNED phase.

### Host recovery

- The recovery tool accepts only the manifest-bound locator record, matching nonce/generation,
  an OWNED or ACTIVE descriptor at that exact dynamic base, and descriptor/scratch ranges fully
  inside the `0x15000` lease.
- OWNED authorizes recovery of an early-startup death; ACTIVE additionally proves exclusion from
  both software pools. Neither state proves native guest teardown.
- Existing VFIO ownership, BME, D0/runtime, exact sibling/parent, GART, cursor, watchdog/journal,
  doorbell, queue-retirement, fence, and post-recovery host checks remain mandatory.
- Invalid, absent, ambiguous, replayed, out-of-range, or multiply published locator evidence
  causes no scratch write and no reuse authorization.

This protocol preserves the no-reboot recovery property while removing the need to guess a free
fixed VRAM hole. It is a schema and host/guest contract change, not a small constant adjustment.

## Routing and ABI constraints

- `AMDHWVMM::setVirtualSpaceReady` is native `void`. Read the full 64-bit stored `VMM+0x50`
  after the original call for evidence; do not treat an integer return as an API result.
- `AMDHWMemory::setVirtualSpaceReady` at `0x52c3a` is a six-byte no-op. When the forced memory
  graft is removed, remove this route entirely. A long-form trampoline could overwrite the
  adjacent function at `0x52c40` if a near jump were unavailable.
- Use the already resolved native hardware vslot `+0x180` and AMDHWMemory vslot `+0x198`; do not
  add private IOAcceleratorFamily2 routes merely to recreate behavior already exposed through
  X6000.
- The native `enableAllocations` tail at hardware-interface vslot `+0x2a0` is
  `AMDHardware::isDeviceValid`, not an allocation. Reserving the lease in the wrapper after the
  original returns occurs after the pool initialization and `[0,base)` reservation, with no
  intervening software-pool allocation in that function.
- `AMDGraphicsAccelerator::powerUpHW` calls the memory object's vslot `+0x118` at X6000
  `0x5099`; that slot resolves to `AMDHWMemory::enableAllocations`. It tests `AL` at `0x509f`
  and branches to the failure exit at `0x5192` before `reserveNdrvSpace` (`0x50aa`) and
  `setMemoryAllocationsEnabled` (`0x50c6`). The wrapper must therefore return false when the
  post-native lease exclusion fails, preserving this native fail-closed propagation.
- Native disable/free walks the reservation list at `AMDHWMemory+0x88` and may free the custom
  `AMDMemoryElement`. The first experiment supports one ready/allocation epoch only: reject a
  duplicate native initialization or ready epoch before clients, never reuse a cached element,
  and make no suspend/resume claim. Guest teardown may release its in-memory element; the
  immutable OWNED descriptor and separate status bytes must remain readable in the native-owned
  VRAM lease for host recovery after guest ownership ends.

## Required regression tests before any build

Tests must exercise behavior and invariants rather than only source strings.

1. **Exact native size semantics fixture**
   - Decode or model the `0x525f5..0x52603` clamp and assert `512/256` survives while `256/512`
     becomes `256/256`.
   - Model `init_pool(Eyyy)` from `0x1facc`: `512/256/0` yields total endpoint `base+512`, marker
     at `base+256`, zero length, never an inverted range.
   - Assert the implementation does not mutate Apple's fields to 240 MiB.

2. **Lease layout and arithmetic**
   - Check 64-bit add/subtract overflow, alignment, BAR containment, descriptor containment, and
     every rebased scratch write through relative `+0x14004` within `[base,base+0x15000)`.
   - Reject the historical fixed descriptor/scratch because they intersect
     `[0x0b708000,0x0fb08000)`.
   - Prove a type-0 lease acquired first and the following type-1-to-type-0 VMM append are
     disjoint under the retained 256/256 mode.

3. **Phase and publication state machine**
   - REQUESTED cannot authorize MMIO recovery.
   - OWNED requires one native append, matching nonce/generation, exact locator, readback, and
     permits only early-startup recovery.
   - ACTIVE requires one successful native pool init, the full pool address
     `memoryBase+leaseOffset`, and exact reserve deltas in both pools.
   - Any failure reaches INVALID; replay, a second append, a second pool init, duplicate locator,
     or later transition out of INVALID is rejected.

4. **Second-pool failure**
   - Fake the native `AMDHWMemory::reserve` behavior where pool 0 succeeds, pool 1 fails, and the
     function still returns true. The wrapper must reject it from the unequal free-byte deltas
     and must not publish ACTIVE.

5. **Ordering**
   - Require type-0 lease acquisition before original VMM reservation.
   - Require OWNED before KIQ preparation.
   - Require native `enableAllocations` exactly once, both-pool reserve before wrapper return,
     and ACTIVE before ordinary client submission.
   - Fake the native caller and require a lease-exclusion failure to propagate as false before
     the later NDRV reservation/allocation-enable steps.
   - Reject a second ready/init epoch and stale `AMDMemoryElement` reuse; label suspend/resume
     unsupported for this bounded experiment.
   - Retain `rgpuvmm=3` for this first delta and prove the DMA paging channel remains non-null.

6. **Host recovery compatibility**
   - Rebase all descriptor and scratch writes from the validated dynamic base.
   - Reject stale/malformed locator evidence before any VRAM write.
   - Keep existing descriptor/KIQ/GART disjointness tests, recovery fence tests, and full schema-6
     validation; add OWNED early-death and ACTIVE normal-death cases.

7. **Progress regression comparison**
   - Candidate 171 reached a WindowServer GFX/SDMA submission: its serial lines 3446/3458 identify
     pending VMID-2 buffers, line 3788 shows a consumed GFX IB, and lines 3852-3860 show SDMA0
     active with a pending paging IB.
   - Candidate 178-A ended with 483/483 `backing-pte` failures and submit `0/0/0`; candidate 178-B
     ended with 531/531 and submit `0/0/0`. Their probes both reported status 5,
     `e00002bd`, and zero completed command buffers.
   - A future functional run must be compared with both baselines. Reaching native submit is
     progress relative to 178, but it must also reach or exceed 171's furthest safe stage without
     reintroducing its stall/fault behavior. Only the unchanged Metal compute/render probe can
     establish execution.

## Deferred native-capacity restoration

Restoring Apple's measured `512/256` values is likely necessary to recover the missing capacity,
but it is not safe to combine with the first lease change. Before enabling it, capture and bind:

- the complete provider output consumed by `getReservedVRAMForSwip`;
- hardware `+0x340/+0x348/+0x350/+0x358` immediately before and after each append;
- the full 64-bit VMM `+0x50` address and its 68 MiB end;
- both pool total-free values after native enable and every native external reservation; and
- proof that all resulting intervals are within their intended aperture and mutually disjoint.

If the secondary window is valid, native `512/256` plus the dynamic lease should be tested as a
separate, exact artifact. If it is absent, a different native policy is required; swapping the
fields or forcing a guessed upper interval is vetoed.

## Claims ruled out, open, and untested

**Ruled out by static evidence**

- `init_pool(total,reservedStart,reservedLength)` does not interpret its first two values as an
  inverted `[start,end)` range.
- The proposed `256/512` swap cannot survive native initialization.
- Decimal `191922176` is not `0x0b70a000`; it is `0x0b708000`.
- `setReservedNdrvSpace` alone does not prove that all memory below the MQD is consumed.
- The VMM reservation grows top-down; the lower ~183 MiB is not proved occupied merely because
  the MQD lies near `0x0b706000`.

**Proven facts with limited implications**

- The current wrapper reduces the two native sizes to 256 MiB and the active recovery handshake
  reduces both to 240 MiB.
- The current fixed descriptor and scratch lie inside the exact inferred VMM interval.
- Both pool initializers run twice on the same pool objects in candidates 178-A/B.
- Candidate 178-A/B fail before channel submit and complete zero Metal command buffers.

**Open or untested**

- No preserved record proves actual VMM writes corrupted the fixed descriptor/scratch, or the
  reverse; overlap establishes unsound ownership, not observed corruption.
- No live allocation from the same IOAccelerator pools is proved between the two init calls.
- The secondary reserved-VRAM cursor used by the unequal native fields is not captured.
- The zero-length reservation marker's downstream policy role is not fully known.
- Dynamic lease v2 has not been implemented, built, or exercised on hardware.

## Source index

- Current equalization and stale rationale: [`src/RaphaelGPU.cpp`](../../src/RaphaelGPU.cpp),
  lines 2368-2413.
- Forced memory/VMM grafts: [`src/RaphaelGPU.cpp`](../../src/RaphaelGPU.cpp), lines 4001-4049.
- Current fixed reservation activation: [`src/RaphaelGPU.cpp`](../../src/RaphaelGPU.cpp),
  lines 5019-5067; [`src/RecoveryReservation.hpp`](../../src/RecoveryReservation.hpp), lines 8-106.
- Host scratch layout: [`tools/vfio-recover.py`](../../tools/vfio-recover.py), lines 145-169 and
  542-549.
- Candidate 171 furthest stage: [`findings/experiments/metal-005-171/serial.txt`](../experiments/metal-005-171/serial.txt),
  lines 3440-3462, 3786-3788, and 3852-3871.
- Candidate 178-A native sizes/order/result: [`findings/experiments/metal-011-178-a/serial.txt`](../experiments/metal-011-178-a/serial.txt),
  lines 2399, 2535-2543, 2560-2724, and final submission summaries; probe result in
  [`probe.json`](../experiments/metal-011-178-a/probe.json).
- Candidate 178-B native sizes/order/result: [`findings/experiments/metal-011-178-b/serial.txt`](../experiments/metal-011-178-b/serial.txt),
  lines 2415, 2551-2559, 2576-2742, and 3445-3446; probe result in
  [`probe.json`](../experiments/metal-011-178-b/probe.json).
- Exact X6000 offsets: `AMDHWMemory::init` `0x524ea`, `initVRAMInfo` `0x527a4`,
  `enableAllocations` `0x52a1e`, `reserve` `0x5343c`, `AMDHWVMM::setVirtualSpaceReady`
  `0x578ce`, `AMDRTHardware::getReservedVRAMForSwip` `0x5def6`,
  `AMDRTHardware::setVirtualSpaceReady` `0x5e0b2`, `AMDHardware::isDeviceValid` `0x70896`, and
  `AMDHardware::appendToReservedVRAMOffset` `0x72afe`, from the hash-pinned local 24G830 image.
