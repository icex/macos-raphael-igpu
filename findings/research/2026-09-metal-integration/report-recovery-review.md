# Recovery ownership review of `report.md` and `report-astra.md`

**Evidence cut:** 2026-09-09, source commit
`ef326108b868a00efb292e481ea2efb866205efa`, macOS 15.7.9 / 24G830.
This is an offline source and artifact review. It does not authorize a GPU launch,
recovery operation, ledger change, build, or device access.

## Decision

`report-astra.md` states the current functional result with appropriate limits:
candidate178-A and B reached an assigned GPU virtual address and failed in the combined
backing/PTE phase before the instrumented `submitBuffer` boundary. The exact rejecting
backing or commit operation remains unmeasured.

`report.md` identifies a valuable correlation between the recovery heap cap and the
regression from candidate171, but it turns that correlation into a causal conclusion. The
cap is a strong hypothesis, not an established root cause. More importantly, its proposed
test—leave the recovery descriptor and host-KIQ scratch inside an uncapped Apple heap—is
unsafe. A checksum detects some corruption after it occurs; it neither grants ownership of
the bytes nor prevents the recovery producer from overwriting live guest allocations.

The safe implementation direction is a **version-2 native-owned dynamic recovery lease**.
The launch nonce must arrive outside VRAM. The guest obtains a small recovery block through
Apple's native reserved-VRAM allocator before the VMM reservation, publishes its actual
location, and excludes the same interval from both software pools before ordinary clients
can allocate. The host uses the published location only to find an exact nonce-bound
descriptor and retains every existing holder, BME, GART, queue-retirement, capture, and
journal gate.

The current same-boot ledger is terminal at 6/6 and must remain byte-for-byte unchanged.
Any functional candidate needs a separately reviewed finite policy. There is no generic cap
override and no seventh launch under the completed plan.

## Exact findings

### The current recovery interval lacks exclusive ownership

The version-1 descriptor claims the final 16 MiB by changing both Apple pool-size fields to
`0x0f000000` immediately before `AMDHWMemory::enableAllocations`:

| Object | Half-open BAR0 interval |
| --- | --- |
| v1 descriptor | `[0x0f000000, 0x0f000048)` |
| host-KIQ ring | `[0x0f100000, 0x0f110000)` |
| MQD | `[0x0f110000, 0x0f110800)` |
| RPTR | `[0x0f111000, 0x0f111004)` |
| WPTR | `[0x0f111008, 0x0f111010)` |
| EOP | `[0x0f112000, 0x0f113000)` |
| fence | `[0x0f113000, 0x0f113004)` |

These ranges match `src/RecoveryReservation.hpp:12-15` and
`tools/vfio-recover.py:147-169`. The producer writes the six scratch objects only after
halting the MECs and rechecks them against the live GART. Candidate176's GART was
`[0x0fdfc000, 0x0fffe008)`, so the producer's actual writes are disjoint from that table.
That GART result does not prove that Apple has excluded the descriptor or scratch from every
other native reservation.

The exact X6000 `AMDHWVMM::setVirtualSpaceReady(true)` at `0x578ce` requests allocation type
1, size `0x04400000`, and alignment `0x1000` through hardware vtable slot `+0x180`. The
resolved `AMDHardware::appendToReservedVRAMOffset` at `0x72afe` is a top-down allocator: it
subtracts the requested size from the selected reserved cursor and returns the new base.
The candidate171 and candidate178 logs report decimal `191922176`, exactly `0x0b708000`,
not `0x0b70a000` as `report.md` says. The resulting 68 MiB interval is therefore:

```text
[0x0b708000, 0x0fb08000)
```

Both the v1 descriptor at `0x0f000000` and the whole scratch span through `0x0f113004`
fall inside that native interval. The native VMM append occurs before the recovery
descriptor is activated and before the software pools are initialized. Capping those later
pools cannot retroactively establish ownership against the earlier native reservation.
The fact that candidates175-178 completed recovery shows that these bytes happened to
remain usable in those runs. It does not prove exclusive ownership or make future writes
safe.

The suggested fixed alternative—descriptor at `0x0fc00000`, scratch at `0x0fd00000`, cap
at 252 MiB—is geometrically disjoint from the latest 68 MiB append and from the measured
candidate176 GART:

```text
VMM end       0x0fb08000
descriptor    0x0fc00000..0x0fc00048
scratch       0x0fd00000..0x0fd13004
GART start    0x0fdfc000
```

It is not yet an ownership proof. The append is top-down, so bytes above the latest
allocation's end may belong to older SWIP/native reservations represented by
`AMDHardware+0x340/+0x348` or `+0x350/+0x358`. No existing artifact enumerates those complete
intervals. Fixed `0xfc/0xfd` placement is therefore rejected unless an independent native
owner/free-span proof becomes available.

### The unequal pool path in `report.md` is misread

X6000 `AMDHWMemory::enableAllocations` at `0x52a1e` calls the three-argument allocator
initializer in the unequal-size branch as:

```text
init_pool(base + size0, base + size1, 0)
```

The exact IOAcceleratorFamily2 implementation shows that these arguments are
`total_end`, `reserved_start`, and `reserved_length`. `init_pool(uint64_t,uint64_t,uint64_t)`
at `0x1facc` first calls the one-argument initializer with `total_end`, then calls
`reserve(nullptr, reserved_start, reserved_length)`. It is not a start/end range constructor.
The current `512 MiB / 256 MiB` call therefore creates a pool ending at `base+512 MiB` and a
zero-length marker at `base+256 MiB`; it does not ask for an inverted interval.

The exact role of that zero-length marker and the allocation-type policy around the BAR
boundary still need to be documented before restoring the original unequal values. The
evidence already rules out swapping the fields merely to repair an alleged inversion.
Restoring native `512/256` semantics is a separate functional experiment. It must not be
combined with the first recovery-ownership/cap test.

The same IOAccelerator binary establishes that
`IOAccelMemoryAllocator2::reserve(GLKMemoryElement *, start, length)` at `0x1f92c` can reserve
an arbitrary interval and accepts a null owner, allocating its own internal list node. This
is the correct primitive for excluding a native recovery block from a software pool.

### The cap is a serious but confounded hypothesis

Candidate171 used uncapped 256 MiB pools. It emitted fourteen identical 4 MiB allocation
failures with `2,592,768` ordinary free bytes and `16,797,696` fixed-free bytes, then reached
WindowServer GFX and SDMA paging queues. Candidates177, 178-A, and 178-B used 240 MiB pools
and stopped before `submitBuffer`; A recorded 483 and B 531 final `backing-pte` failures.
Those facts make the missing 16 MiB a plausible direct contributor.

They are not a controlled cap-only comparison. Candidate171 was source commit
`d41b565830f0138fd5ce181c18c4c4d44abaddb1`; candidate178 was `ef326108...`, and the launch,
trace, recovery, VM-root, and same-boot state differed. The historical 166-reuse result also
used older bytes and configuration. The claim in `report.md` that the cap, rather than warm
state, is *the* variable that flips is too strong.

The proposed functional test should change recovery ownership and available heap while
keeping the current 256/256 equalization. It should also keep `rgpuvmm=3`. The forced early
`rgpumem=2` enable must be removed because a native lease needs one authoritative pool
initialization before exclusion; this means progress in that candidate would establish that
the corrected memory/recovery setup fixes the regression, but would not attribute all
improvement solely to the 16 MiB cap. Native 512/256 behavior remains a later, isolated
candidate.

### Candidate171 proves a historical SDMA paging stall, not the current cause

Candidate171's first recorded queue failure is at serial line 3189:

```text
HW Channel 12 SDMA0_PAGE is occupied by channel 34 stamp 1
```

The later diagnostic dump associates WindowServer, VMID 2, and a valid-content GFX IB at
`0x400200000`; the GFX dump reports it fully consumed. It also shows an SDMA0_PAGE IB at
`0x400100000`, with `ConsumedSize=0`, `RemainSize=0x70`, and Q1 halted. The dump was produced
after `Restart Channel: 34 SDMA0_PAGE`, so HALT is not proof of the queue's state before the
driver's timeout/restart path. The earlier occupied-channel event is the stronger chronology.
The recorded MM fault-event count is zero; the displayed VMID-15 MM status is stale or from a
different hub and cannot be assigned to the VMID-2 paging IB.

This establishes a real historical downstream stall once mappings and submission existed.
It does not establish that SDMA caused candidates177/178 to fail: their `submitBuffer` count
is zero. It also does not prove that Linux lacks an SDMA page-queue implementation, nor that
the same VM translation must succeed for the different GFX and SDMA IB addresses merely
because both use VMID 2. Treat SDMA queue-1 programming, mapping, invalidation, and consumption
as downstream hypotheses that become active only after the current build again submits work.

## Version-2 native-owned lease

### Guest ownership phases

The bootstrap nonce and requested lease version must be manifest-bound and delivered outside
VRAM, for example as an exact boot argument. The host must not write a pending descriptor into
an address whose native ownership has not been established.

At a route-gated point before `AMDHWVMM::setVirtualSpaceReady` makes its 68 MiB append, the
guest requests one `0x15000`-byte, 4 KiB-aligned type-0 block through the native
`appendToReservedVRAMOffset` method. Type, method identity, object identity, and call ABI must
be pinned to the exact 24G830 bytes. The returned interval must be nonzero, non-wrapping,
4 KiB aligned, wholly within the 256 MiB BAR, and large enough for this compact layout:

Under the selected 256/256 equalization, the later type-1 VMM request follows the function's
type-0 fallback and advances the same top-down cursor, so acquiring the lease first makes the
two native intervals disjoint. This claim is specific to the equal-size candidate. Restoring
512/256 selects the separate type-1 cursor and therefore still requires independent bounds and
ownership evidence before a hardware test.

| Relative offset | Object |
| --- | --- |
| `+0x0000..+0x0050` | 80-byte immutable nonce-bound ownership descriptor |
| `+0x0100..+0x0168` | 104-byte optional pool-status record |
| `+0x1000..+0x11000` | 64 KiB host-KIQ ring |
| `+0x11000..+0x11800` | MQD |
| `+0x12000..+0x12004` | RPTR |
| `+0x12008..+0x12010` | WPTR |
| `+0x13000..+0x14000` | EOP |
| `+0x14000..+0x14004` | fence |

The final `0xffc` bytes are padding. No host write may escape the allocated `0x15000` bytes.

After the native append succeeds, the guest writes an immutable `OWNED` descriptor. This
phase is needed because native KIQ and other TTL setup precede the final native
`AMDHWMemory::enableAllocations`; an early crash cannot be classified as having no active
queues merely because the software pools do not yet exist. `OWNED` means only that the native
reserved-VRAM allocator owns the block and that its bytes and nonce read back. It does not
claim that the software pools have been initialized. The guest never changes this descriptor
in place, so an exit between separate stores cannot turn the only ownership proof into a torn
`ACTIVE` record.

The one native `enableAllocations` then initializes both pools. The exact trailing
`AMDHWMemory` calls inside native enable are the base reservation at slot `+0x198` and
`isDeviceValid` at hardware slot `+0x2a0`; they do not allocate an ordinary client block in
the dynamic lease. Immediately after native enable returns, while still inside the wrapper
and before the caller can expose the pools to ordinary clients, reserve the exact native
lease interval in both `AMDHWMemory+0x68` and `+0x70` through the native reserve path. Each
reservation must succeed, and the free-byte change must match the actual intersection. Only
then may the guest write a separate, checksummed, one-shot pool-status record. A missing or
torn pool-status record leaves the immutable native-ownership descriptor intact; it cannot be
misread as proof that both software pools were excluded.

Removing the forced `rgpumem=2` early enable gives this path one authoritative initialization.
If later source reintroduces a second initialization, the descriptor must become invalid
until the interval has been reserved again in both rebuilt pools. A repeated initializer
must never silently erase the exclusion.

Before publishing ownership, the guest zeroes and reads back the separate pool-status slot.
It then publishes the complete immutable ownership descriptor through the immediate bounded
critical channel as soon as its VRAM bytes read back. Deferred replay may repeat that exact
lease identity. Later records form an ordered phase history keyed by the same identity and
include the separate pool-status fields, pool identities, reservation results, generation,
and checksum. Exact byte-identical replays are deduplicated within the globally bounded
critical-record stream; a second lease identity, reversed phase, or conflicting duplicate is
rejected. The critical serial record locates the descriptor and lets the host validate its
expected bytes before opening VFIO; it is not by itself authority to write VRAM. A crash
before immediate publication or a lost critical record is explicitly unrecoverable by this
protocol and produces a missing-locator refusal.

Both wire records use a write-last state DWORD as their commit marker. The guest writes the
final checksum while state remains zero, issues the ordering fence, stores `OWND`, `ACTV`, or
`INVL` last, fences again, and requires a full-record readback before first publication. A
zero or noncommitted optional pool-status image does not invalidate the separate immutable
ownership proof. It remains an `OWNED`-only recovery: the host must inspect possible queues,
must not claim that the pools were excluded, and must not authorize reuse. A checksum-valid
`INVL` status is an explicit terminal pool-reservation failure. If a pool status was published,
its final BAR bytes must match that published record exactly or recovery is refused.

### Host validation and recovery

The version-2 prelaunch path writes no BAR bytes. It records the exact challenge in the
manifest and launch authority. After QEMU exits, the host validates the immutable manifest,
output digest, source identity, boot/run identity, and the complete serialized descriptor in
the structured locator before opening any recovery transaction. A missing, duplicated,
malformed, saturated, or contradictory locator is a refusal.

Only after that offline validation may the host open VFIO and read the descriptor at the
reported location. The BAR bytes must exactly match the previously validated serialized
descriptor on version, state, nonce, layout, allocation base and size, generation, and
checksum. The host derives every component range from those matching records. It rejects
overflow, misalignment, out-of-BAR placement, escape from the native block, component overlap,
and any overlap with the live GART. No BAR or register write occurs before these checks. The
GART check happens before logically consuming the nonce-bound lease and is repeated
immediately before scratch use. The host never zeroes or otherwise mutates the immutable v2
ownership descriptor or its separate pool-status record; replay prevention belongs in the
receipt and launch-policy state. Historical v1 consumption semantics remain confined to the
v1 recovery path.

The immutable ownership descriptor and optional pool-status record need separate host rules:

- A valid ownership descriptor plus valid pool status authorizes the normal recovery algorithm
  only after all current host gates pass.
- A valid ownership descriptor without pool status may authorize scratch use after an early
  guest failure only when the exact serial
  phase history proves native ownership was established before the failure. It must never be
  treated as evidence that queues are absent. Recovery must inspect and retire every possible
  active queue using the same conservative machinery as the current producer.
- Any reserve failure, missing ownership descriptor, invalid pool status, or inconsistent phase causes a
  no-write recovery refusal and forbids same-boot reuse.

The existing no-QEMU/no-VFIO-holder check, BME-off state, reset-method policy, source pins,
capture and journal gates, live queue snapshot, GART derivation, host-KIQ fence, PSP teardown,
and final all-queues-retired checks remain mandatory. The v2 receipt records the exact dynamic
ranges and the locator/descriptor evidence. Existing schema-6/v1 receipt validation remains
unchanged; a new schema or explicitly versioned reservation subrecord must not reinterpret old
receipts.

## Required offline regression coverage

The implementation needs representative production-path tests rather than copies of helper
logic:

1. Preserve exact v1 pending/active descriptor bytes and validate archived schema-6 receipts,
   including candidate176's GART interval.
2. Reject v2 bad alignment, integer wrap, short blocks, out-of-BAR ranges, component escape,
   component overlap, and descriptor/scratch overlap with GART.
3. Reject absent, duplicate, malformed, nonce-mismatched, layout-mismatched, or stale serial
   locators before constructing a write plan.
4. Prove call order: native append precedes VMM append; native enable completes; both pool
   reservations complete before the wrapper returns and before a modeled first ordinary
   allocation.
5. Prove a reservation failure in either pool never publishes `ACTIVE`, never reaches host
   scratch writes, and cannot authorize another launch.
6. Model a repeated allocator initialization and require re-exclusion before returning; for
   the intended candidate, assert that removing `rgpumem=2` leaves exactly the expected native
   initialization.
7. Compare consumer-derived v2 component ranges against the producer's actual descriptor,
   ring, MQD, pointer, EOP, and fence writes at both boundaries.
8. Preserve the producer's pre-consumption and immediate pre-use GART checks, including the
   descriptor-before-GART ordering regression.
9. Exercise early failures after native ownership but before pool activation with possible
   active queues. The expected result is conservative queue inspection/recovery when all
   proofs exist, otherwise no-write refusal; never a fabricated no-queue receipt.
10. Verify policy behavior against the immutable terminal 6/6 ledger: ordinary launch remains
    rejected, no generic maximum-count knob appears, and any future finite extension binds the
    exact candidate, manifest, source, prior receipts, and one allowed row.

## Functional decision criteria

The first hardware candidate after offline review should keep the current 256/256 pool-size
equalization and `rgpuvmm=3`, remove the forced `rgpumem=2` initialization, replace the fixed
v1 scratch with the native v2 lease, and remove only the 240 MiB size rewrite. It should not
also restore 512/256, change connector count, alter SDMA programming, or add a second workload.

Use the existing bounded Metal probe and phase counters. Compare the stage reached with the
historical candidate171 evidence:

- If maps prepare and `submitBuffer` becomes nonzero, the corrected memory/recovery setup is a
  demonstrated regression fix. The result supports the cap/initialization hypothesis but
  does not isolate which of those two required corrections was causal.
- If the historical 4 MiB allocation-failure signature returns and work reaches GFX/SDMA,
  record that as restored 171-like progression, not functional success.
- If the current build still produces only `backing-pte`, zero submit, and NoMemory after the
  240 MiB size rewrite is gone and only the small native lease is excluded, the old cap is not
  sufficient to explain the current failure. This describes allocator geometry, not a claim
  that almost 256 MiB remain free after Apple's native reservations and desktop allocations.
  Backing class, commit mode/range, and native 512/256 semantics remain open.
- If lease ownership, capture, lifecycle, host state, or recovery fails, the experiment is
  invalid for the memory hypothesis and same-boot reuse is prohibited.
- If submission resumes, candidate171's SDMA paging stall becomes the next measured boundary.
  It remains a separate downstream defect until reproduced by the current source.

A terminal fresh-boot launch with no recovery descriptor or scratch is the safety fallback if
native ownership cannot be implemented. It would require a reboot before any subsequent GPU
launch and does not meet the project's reuse goal, so it is not the selected path.

## Evidence provenance and limits

- `report.md` SHA-256:
  `71753863c18c3ae0d623b391f6d3c550017466fe1df4b8799200a749ce67d7de`.
- `report-astra.md` SHA-256:
  `0ebfab9c494ee8183392c6d03bcec0c58132b154dc30733528b3f6f095fcf3bf`.
- Exact IOAcceleratorFamily2 executable SHA-256:
  `1700f3badafbb9014d55b7f6ecde5cdff0d585bd1f0e143c9f8465e4466e5d35`.
- Candidate171 serial SHA-256:
  `69c23ffb109a2583f2b163e926ac98b82a38499a72ae1ca8f7ba0e6710e67112`;
  manifest source commit `d41b565830f0138fd5ce181c18c4c4d44abaddb1`.
- Candidate178-A/B evidence is summarized in their immutable experiment directories and
  `findings/research/2026-09-metal-integration/metal-internals.md`.

No fresh tests were run for this review. All proposed v2 behavior remains a design until the
exact native call gates, phase lifetime, software-pool exclusions, host parser, and receipt
compatibility are implemented and independently tested offline.
