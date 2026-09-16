# Review report: why Raphael iGPU Metal acceleration still fails

Reviewed 2026-09-09 against `status.md` (20:13 UTC version), `docs/ROADMAP.md`,
`findings/GPU-RE.md`, the research drafts under `findings/research/2026-09-metal-integration/`,
the driver source, the test suite, the experiment cards, and the raw serial logs of every
archived hardware run. Written for other agents. Every claim below points at a file and line.
Line numbers for disassembly refer to the pre-existing listings
`/home/bogdan/macos-vm/re/x6000.asm` (AMDRadeonX6000, SHA-256 `2e3642...`) and
`/tmp/ioaccel.dis` (IOAcceleratorFamily2, SHA-256 `1700f3...`, extracted by an earlier session).

## 1. Summary

**The project's own diagnosis is correct but incomplete.** Status says the first Metal command
fails with `kIOReturnNoMemory` because `batchMemoryMapPrepare` returns false after a GPU virtual
address was assigned, "in backing-memory preparation or page-table insertion", and proposes a
fifth observation-only hardware run to split those two. That reading of candidates 177/178 is
right. What it misses is the run-to-run diff that explains *why* the map cannot be prepared.

- **Finding A (highest confidence).** The pre-submit `NoMemory` failure appeared in exactly the
  runs where candidate 175's "recovery reservation" capped Apple's two VRAM allocator pools from
  256 MiB to 240 MiB. That cap is activated only on warm launches (it needs a `PEND` descriptor
  written by the host recovery tool). Every run in which native power-up succeeded **without**
  the cap (166-reuse, 170, 171) got WindowServer work onto the GFX and SDMA hardware queues.
  Every run **with** the cap (175, 176, 177, 178-A, 178-B) prepared zero maps. The project never
  compared these serials, and its classifier has no token for Apple's own allocator error line.
- **Finding B.** Even without the cap the VRAM heap is nearly exhausted before the first client
  command. In the cold runs Apple logged `Failed to allocate size:4194304. There is 2592768 free
  memory remaining, and 16797696 fixed-free memory remaining` 14 to 24 times per run. The heap is
  256 MiB (BAR0 size) instead of the 512 MiB carve-out, the two size fields Apple reads arrive in
  the opposite order from what Apple's own code expects, and roughly 183 MiB plus a 68 MiB VMM
  arena are consumed before the pools are even enabled. Fixing A alone will likely land back on B.
- **Finding C.** Two grafts from the era when native power-up failed (`rgpumem=2`, `rgpuvmm=3`)
  are still in the "frozen baseline". They now make `enableAllocations` run twice, and
  IOAccelerator's `init_pool` wipes and rebuilds the allocator on the second call.
- **Finding D.** The last hardware-level blocker actually reached (cold runs 170/171) is SDMA0
  queue 1 (`SDMA0_PAGE`) halted with an unconsumed VMID-2 indirect buffer, while in the same run
  the graphics CP consumed a VMID-2 indirect buffer completely. The candidate-173 "VMID-2 root in
  the wrong address domain" theory does not explain that asymmetry and has never been exercised.
- **Methodology.** About 80% of the tooling lines and 89% of the test lines serve lifecycle and harness. The
  last four hardware runs re-observed one known failure with ever finer observation hooks while a
  one-line configuration difference went unnoticed. The boot-ledger policy now forbids the single
  cheap experiment that would settle Finding A.

## 2. What was reviewed

| Area | Files |
|---|---|
| Status and roadmap | `status.md`, `docs/ROADMAP.md`, `README.md`, `docs/bring-up-history.md`, `docs/patch-delivery.md`, `docs/superpowers/plans/2026-09-08-gpu-acceleration.md` |
| Findings | `findings/GPU-RE.md` (3,780 lines), `findings/baseline-audit.md`, `findings/hybrid-cause.md`, `findings/raphael-vs-navi-linux.md`, all `findings/experiments/*/notes.md`, `findings/experiments/metal-009-176/submission-failure-forensics.md`, `findings/experiments/metal-010-177/memory-map-phase-design.md` |
| Research drafts | `findings/research/2026-09-metal-integration/{metal-internals,hypotheses-metal,hypotheses-hardware,top-20-issues,candidate179-design,raphael-navi-linux}.md` |
| Driver | `src/RaphaelGPU.cpp` (5,731 lines), `src/SubmissionTrace.hpp`, `src/RecoveryReservation.hpp`, `src/GartAddresses.hpp`, `src/GpuVmDiagnostics.hpp` |
| Harness and tests | `tools/*.py` (16,304 lines with shell), `tests/*.py` (10,865 lines, 377 tests), `tests/*.cpp` (1,281 lines), `tests/metal_probe.m`, `experiments/*.json`, `.github/workflows/release.yml` |
| Raw evidence | `serial.txt`, `events.jsonl`, `manifest.json` for every run under `findings/experiments/` and `$HOME/macos-vm/run/` |
| Binaries | `AMDRadeonX6000` 24G830 and the extracted `IOAcceleratorFamily2` listing |

## 3. Where the project stands

The verified chain is long and real: VBIOS graft, IP-version remapping, PSP TOC substitution,
dummy SMU, the BAR-relative-versus-MC address corrections for the GART root and MQD, the
one-instance SDMA topology repair, native KIQ execution, engine start, Metal 3 enumeration,
shader compilation, and a reset-free rootless recovery that has now survived three same-boot
restarts. None of that is in question.

What has never happened: one Metal command buffer completing. The table below is the
hardware-run history that matters, reconstructed from the raw serial logs rather than the notes.

| Run | Launch | Pool cap | Native `powerUpHW` | Apple `Failed to allocate` lines | WindowServer work reached a HW queue | Outcome |
|---|---|---|---|---:|---|---|
| hybrid-004 / 166-reuse | warm (PSP-only recovery) | none, 256 MiB | 1 | 14 | yes (4 channel restarts) | KIQ stamps to 21, channel restarts |
| metal-004 / 170 | cold | none | 1 | 24 | yes | SDMA0_PAGE stall on IB `0x400100020`, VMID 2 |
| metal-005 / 171 | cold | none | 1 | 14 | yes | `SDMA0_PAGE is occupied by channel 34 stamp 1`; KIQ 28 timeout later |
| metal-006 / 172 | warm | n/a | 0 | 0 | no | failed before allocations |
| metal-007 / 174 | warm | n/a | 0 | 0 | no | BAR0 mapping refusal |
| metal-008 / 175 | warm | **240 MiB** | 1 | 0 | no | probe withheld by harness; no WindowServer activity either |
| metal-009 / 176 | warm | **240 MiB** | 1 | 0 | no | probe `e00002bd` |
| metal-010 / 177 | warm | **240 MiB** | 1 | 0 | no | `e00002bd`, 0 submits in trace |
| metal-011 / 178-A | warm | **240 MiB** | 1 | 0 | no | same |
| metal-011 / 178-B | warm | **240 MiB** | 1 | 0 | no | same |

Sources: `grep -c 'Failed to allocate'`, `grep -c 'is occupied by channel'`,
`grep 'recovery reservation ACTIVE'` and `grep 'enableAllocations entry'` over each run's
`serial.txt`; `findings/experiments/metal-005-171/serial.txt:2784-2810,3189,3440-3462`;
`findings/experiments/metal-011-178-b/serial.txt:2557-2560,2738-2742,2794-2813`.

## 4. Finding A: the 240 MiB pool cap is the change that produced `NoMemory`

### 4.1 What changed between the last run that submitted work and the first run that did not

Candidate 175 (commit `7db5a73`, building on `26efd7c`) added `src/RecoveryReservation.hpp`.
When the host recovery tool has written a `PEND` descriptor into BAR0 at offset `0x0f000000`,
`wrapHwMemEnable` (`src/RaphaelGPU.cpp:5019-5067`) calls `RaphaelRecovery::activate`, which
rewrites both of Apple's pool-size fields (`AMDHWMemory+0x40` and `+0x48`) from `0x10000000` to
`HeapLimit = 0x0f000000` (`src/RecoveryReservation.hpp:12,96-104`) before the native
`enableAllocations` runs. The host side writes that descriptor from
`tools/vfio-recover.py:161-171,565-573`. A launch without a descriptor takes the `no valid pending recovery reservation` branch and
leaves the sizes alone (visible on the second, native call in 175-178, e.g. 178-B
`serial.txt:2738`). Runs 166-reuse, 170 and 171 predate the reservation code entirely.

This makes "warm launch" and "capped heap" perfectly confounded from 175 onward, and 166-reuse
shows that a warm launch without the cap still submits work. The cap, not the warm state, is
the variable that flips.

### 4.2 Why a 16 MiB cap can turn 100% success into 100% failure

Apple's heap was already at the edge before the cap existed. In 171, the first WindowServer
surfaces failed with:

```text
AMD ERROR! Failed to allocate size:4194304. There is 2592768 free memory remaining,
and 16797696 fixed-free memory remaining.
```

(`findings/experiments/metal-005-171/serial.txt:2784-2810`, 14 times; 24 times in 170; 14 in
166-reuse). That message is printed by `AMDHWMemory::allocateLargeBlocks`
(`x6000.asm:92589-92770`, string at `0x5335e`); the two numbers are
`IOAccelMemoryAllocator2::total_free()` of pool `+0x68` and pool `+0x70`
(`x6000.asm:92937-92948`). So with the full 256 MiB heap, the general pool had 2.47 MiB free
and the fixed pool 16.02 MiB free at the moment the desktop started. The reservation removes
16 MiB (`0x0f000000..0x10000000`), within 20 KiB of the fixed pool's entire free space.

Two further facts make the cap harmful independently of that coincidence:

1. Apple sizes its early reservations from the uncapped values. `AMDHWVMM::setVirtualSpaceReady`
   (`x6000.asm:98103-98130`, `0x578ce`) allocates `0x4400000` bytes (68 MiB) through the hardware
   interface and stores the result; the driver logs its return as `191922176` = `0xb70a000` in
   both 171 and 178-B (`serial.txt:2546` and `:2551`). That arena therefore spans
   `0x0b70a000..0x0fb0a000`, which ends 11 MiB above the new cap. The KIQ MQD sits immediately
   below it at `0x0b706000`, so roughly 183.5 MiB was already reserved before the VMM arena.
   Both happen before `enableAllocations` (178-B `serial.txt:2551` versus `:2559`).
2. `enableAllocations` takes the "equal sizes" branch and initialises **both** pools over the
   same range `[base, base+size0)` (`x6000.asm:91973`, `0x52a54-0x52a6a`). With size0 capped, the
   pools cover `[0, 240 MiB)` while Apple's reserved regions computed above extend to 251 MiB.

### 4.3 Where the failing map actually stops

The project plans a hardware run to learn whether the superclass prepare fails before or at
`commitIntoGPUPageTable`. The superclass cold path answers most of that statically.
`IOAccelMemoryMap::prepare` (`ioaccel.dis:93194`, `0x52c08`) calls `.cold.1` (`ioaccel.dis:99768`,
`0x58308`) for a map whose committed bit is clear. That function first calls the backing
object's vtable slot `+0x148` (`[map+0x18]`, the `IOAccelMemory`), and only if that returns true
calls `commit_pte` (`0x52c84`), which calls slot `+0x170` (the X6000 override). A false from the
backing call returns "handled, false" without touching the map's flags, which is exactly the
unchanged `0xb13` state 178 observed.

The map that fails in every batch (`0xffffff98fdc98180`, VA `0x4000c0000`, 178-B
`serial.txt:2797-2851`) has flag bit `0x10` set. In `batchMemoryMapPrepare`
(`x6000.asm:5310`, `0x65be-0x6621`) that bit selects the `+0x940` fallback instead of the
`+0x968` one. The project's phase design describes these two as the video-memory and
system-memory reclaim paths without proving which slot is which, so treat the label as
unproven. Under the reading that `0x10` marks a video-memory-backed map, a map whose VRAM
backing cannot be allocated, and whose reclaim fallback has nothing to evict, produces exactly
"VA assigned, backing false, `NoMemory`, no submit".

The same map is the first entry of every 3-mapping batch across two different command queues
(`0xffffff98fecd1000` and `0xffffff98fecce000`), so it is a per-task or global resource that
every WindowServer submission needs. Its VA is one of the three the candidate-173 walker was
designed around (`0x4000c0000`, `0x400100000`, `0x400200000`), i.e. the same client region whose
IBs the hardware saw in 170/171.

### 4.4 Why the project missed it

- `tools/classify-run.py` has no rule for `AMD ERROR! Failed to allocate`, `is occupied by
  channel`, or `Restart Channel`. Five consecutive verdicts of
  `INCONCLUSIVE / sdma_vm_program_missing` are uninformative by construction: they demand a
  record from a stage the run never reaches.
- No document compares the 176-178 serials with 170/171. `findings/experiments/metal-004-170`
  and `metal-005-171` notes do not mention the allocation-failure burst at all.
- The reservation was reviewed as recovery infrastructure ("caps both allocator ranges before
  `enableAllocations` populates them", `docs/ROADMAP.md`) and never as a functional change to
  Apple's memory manager, so the "one behavioral delta per experiment" rule did not flag it.
- `hypotheses-metal.md` rank 6 and `top-20-issues.md` rank 6 downgrade "duplicate allocator
  initialisation" for lack of evidence; none of the 20 rows mentions the cap or the measured
  2.5 MiB free.

### 4.5 How to test it (one launch, no new hooks)

Run the identical 178 build with the reservation **activated but not capping**: keep the
descriptor handshake (recovery still needs its nonce) but leave `+0x40/+0x48` at `0x10000000`.
Alternatively launch cold. Expected results:

- The `Failed to allocate size:4194304` burst returns and WindowServer channels show activity.
- The probe either reaches `submitBuffer` and stalls on the SDMA0_PAGE queue (Finding D), or
  still fails `NoMemory` because Finding B dominates. Either outcome is decisive.

Add, in the same run, a read of `PerformanceStatisticsAccum` through the existing `gx` agent
(`ioreg -rc AMDRadeonX6000_AMDNavi23GraphicsAccelerator`) right after native power-up and again
after the probe. The project used exactly this in the 1.0.15x era
(`findings/GPU-RE.md:2688-2745`) and dropped it. It is an IORegistry read with no MMIO, and it
reports `vramFreeBytes` and `inUseVidMemoryBytes` directly.

The host recovery's descriptor and scratch would then sit inside Apple's heap during the run.
That is acceptable for a diagnostic: the tool already validates magic, nonce, and checksum
before consuming the descriptor, and fails closed if Apple overwrote it.

## 5. Finding B: the heap is undersized and misdescribed even without the cap

### 5.1 The two size fields are in the wrong order for Apple's code

`AMDHWMemory::initVRAMInfo` (`x6000.asm:91790`, `0x527a4`) copies a hardware-interface struct
into `+0x50` (base), `+0x40` (size0), `+0x48` (size1), `+0x58` (physical). On this device the
driver logs `size0=0x20000000 size1=0x10000000` (`serial.txt:2415`). `enableAllocations`
(`0x52a71-0x52a99`) handles unequal sizes by building both pools over
`[base + size0, base + size1)`, which only makes sense when `size0 <= size1`. The comment at
`src/RaphaelGPU.cpp:2380-2396` noticed the inverted range and "fixed" it by forcing both fields
to the smaller value (256 MiB, the BAR0 size), discarding half of the 512 MiB carve-out that the
GFXHUB aperture already covers (`XG: framebuffer aperture -> 0xf400000000..0xf41fffffff (512 MB)`,
178-B `serial.txt:1823`).

The comment's premise, "every Navi 2x Mac has a resizable BAR as large as its VRAM, so the
unequal path never ships", is asserted without evidence. Apple's binary carries an explicit
unequal branch plus a visible-window reservation call (`0x52a9e-0x52abf`, vtable `+0x198` with
`&this+0x78`), which is the shape a driver needs for a small BAR in front of large VRAM. The
correct configuration to test is `size0 = 256 MiB` (visible), `size1 = 512 MiB` (total), and the
first step is to find which producer fills that struct (the object returned by the hardware
interface's vtable `+0x2c0`, method `+0x18`) rather than patching the consumer.

### 5.2 Where the 256 MiB go

Measured in 171 at the first client command: 2.47 MiB free in the general pool, 16 MiB in the
fixed pool. Consumers visible in the logs and disassembly:

| Consumer | Size | Evidence |
|---|---|---|
| Region below the KIQ MQD | ~183.5 MiB | MQD at `0x0b706000` (171 `serial.txt:2637`); `setReservedNdrvSpace` stores `base + n` at `+0x38` (`x6000.asm:91843`) |
| VMM "virtual space" arena | 68 MiB at `0x0b70a000` | `x6000.asm:98103`, logged `191922176` |
| GART page table | ~2 MiB at `0x0fdfc000` | `XM: post-TTL: CTX0 ptb=0x8_4fdfc001` |
| WindowServer surfaces | 4 MiB each until exhaustion | `Failed to allocate size:4194304` |

The 183.5 MiB region is the strongest lead. The grafted VBIOS advertises four display
connectors (`tools/mkrom.py:111`), the framebuffer driver instantiates `FB:0..3` (four
`setCursorImage() !!! Driver is offline` lines), and a per-head framebuffer reservation is the
natural explanation for a large fixed reservation on a card Apple believes is a discrete GPU.
Hook or log the argument of `setReservedNdrvSpace` to confirm, then reduce the connector count
to one in `mkrom.py` if it is per head.

## 6. Finding C: stale grafts now double-initialise the allocator

`rgpumem=2` makes `wrapHwMemSetVSReady` call `enableAllocations` early
(`src/RaphaelGPU.cpp:4001-4028`), and `rgpuvmm=3` makes `wrapVmmSetVSReady` call
`setMemoryAllocationsEnabled(true)` early (`:4030-4049`). Both were written when
`ttlPowerUp` failed and nothing else reached those calls (`findings/GPU-RE.md:2712-2745`). Since
candidate 171 the native path runs them itself. The 178-B serial shows the result:

```text
2555 XM: calling AMDHWMemory::enableAllocations()      (forced by rgpumem=2)
2559 XH: enableAllocations -> 1
...   three KIQ kicks, engine start
2739 XH: enableAllocations entry ...                    (native, from powerUpHW)
2740 XH: enableAllocations -> 1
2741 XV: setMemoryAllocationsEnabled(1) entry ...       (native)
```

`IOAccelMemoryAllocator2::init_pool(uint64_t)` (`ioaccel.dis:35299`, `0x1f784`) calls
vtable `+0x88`, zeroes the allocator's `+0x58/+0x68`, and rebuilds every list head over
`0x510` bytes: a full reset, not an idempotent no-op. Anything allocated from the pools between
`serial.txt:2559` and `:2739` (the MQD, EOP, rings and fences are prepared in that window) is
forgotten by the allocator on the second call. The research matrix downgraded this because
"no live allocation is proven between the calls"; the window is visible in the log.

Both grafts should be removed from the boot arguments before the next run. Native
`enableAllocations` and `setMemoryAllocationsEnabled(1)` are demonstrably called at
`:2739-2742`. `AMDHWMemory::setVirtualSpaceReady` is in fact an empty function
(`x6000.asm:92131`), so `rgpumem=2` hooks a no-op only to inject its own call.

## 7. Finding D: the hardware blocker behind A and B

When maps prepared (170, 171), the first stall was not a GPU fault. The driver's own dump
(`findings/experiments/metal-005-171/serial.txt:3440-3462,3786-3788,3856-3871`) shows:

```text
[33] Channel: GFX (HW [00])       FirstPendingCB: PID = 159 WindowServer, VMID = 2
     GPUAddress = 0x0000000400200000, Size = 0x1e5, ContentValidation = PASS
  Graphic Ring ... IB: GPUAddress = 0x400200000, ConsumedSize = 0x1f0, RemainSize = 0
[34] Channel: SDMA0_PAGE (HW [12]) FirstPendingCB: PID = 159 WindowServer, VMID = 2
     GPUAddress = 0x0000000400100000, Size = 0x7
  SDMA0: BUSY, MicroEngine: ACTIVE
    Q0: ACTIVE, ReadPtr = 0, WritePtr = 0
    Q1: HALT,   ReadPtr = 0x510, WritePtr = 0xd80
        IB: ENABLED, GPUAddress = 0x400100000, ConsumedSize = 0, RemainSize = 0x70
VM Protection Fault (MM): Page GPUAddress = 0xfffffffff000, VMID = 15, Client ID = 511
```

The CP fetched and consumed a VMID-2 indirect buffer; the SDMA page queue (queue 1) is in HALT
with work pending and consumed nothing. On GC 10.3 both the graphics ring and SDMA translate
through GFXHUB, so a VMID-2 root in the wrong address domain (the candidate-173 theory,
`docs/ROADMAP.md` "high-confidence defect") would have stopped the CP as well. The evidence
points at the page queue itself: Linux `sdma_v5_2.c` brings up only the gfx ring per instance;
its `SDMA0_PAGE_*` registers appear only in the register-dump table (cached
`linux-stable-v7.2.3/.../sdma_v5_2.c:89-97`), and page-queue bring-up exists only in
`sdma_v4_0.c`. Apple's Navi23 class drives a second queue per engine, and Raphael's SDMA 5.2.6
exposes a different per-engine queue count (`findings/raphael-vs-navi-linux.md`, SDMA row). The `Q1: HALT` state with
`rptr < wptr` is where the next hardware-facing investigation belongs once maps prepare again.
The MMHUB fault line is a stale or unconfigured-hub status (MMHUB base/top are unconfigured,
`serial.txt:1822`) and should not be read as a GFXHUB fault.

## 8. Documentation, methodology and test review

**What is good.** Immutable per-run archives with hashes; exact binary offsets and entry-span
checks before routing; the address-domain findings (GART root, MQD, EOP) were real, measured,
and fixed; the SDMA one-instance repair is source-backed; the rootless recovery works.

**What is failing.**

1. **Three sources of truth.** `status.md` (333 lines), `docs/ROADMAP.md` (608 lines) and
   `findings/GPU-RE.md` (3,780 lines) each carry a chronological narrative of the same runs, with
   different levels of correction. `README.md` still describes 1.0.171 as the hardware-tested
   state. Reviewers cannot tell which document is authoritative for a given claim without
   reading all three.
2. **The research process reasons only from the newest trace.** All three hypothesis documents
   and the top-20 matrix take candidate 177/178 as the evidence cut and never re-read the raw
   170/171 serials, which is where the allocator numbers, the channel dump and the CP-versus-SDMA
   asymmetry are. Twenty ranked hypotheses were produced without the one grep that isolates the
   configuration change.
3. **Observation-only runs.** metal-009, -010 and -011 (four launches) re-ran an unchanged
   failing workload with progressively finer hooks, framed as lifecycle qualification
   ("the expected unchanged Metal NoMemory result is diagnostic evidence rather than a lifecycle
   veto", `experiments/metal-011.json`). Candidate 179 proposes a fifth. The per-run
   "one behavioral delta" rule, applied to a baseline that was frozen with stale grafts in it,
   guarantees that no run ever removes an intervention.
4. **Classifier grammar.** `tools/classify-run.py` (686 lines, 45 tests) understands the plugin's
   own records but none of Apple's diagnostics, so the most informative lines in the serial log
   never reach a verdict.
5. **Effort allocation.** Lifecycle and recovery tooling: 9,940 lines; experiment harness: 3,190;
   driver: 6,987; probe: 201. Tests: 7,494 lines (16 files) for lifecycle and harness, 3,371 for
   other harness, 1,281 lines of C++ fixtures for driver helpers. Nothing tests the effect of
   `wrapHwMemVram` or `RaphaelRecovery::activate` on Apple's allocator; the fixtures check the
   descriptor arithmetic only.
6. **Self-imposed blocking.** `status.md` records the boot ledger as terminal at 6/6 and
   "no further hardware run is currently authorized". The next step is a host reboot and one
   launch; the process needs an explicit authorization to allow it.
7. **Driver shape.** `src/RaphaelGPU.cpp` is a 5,731-line monolith with 31 mask bits and
   fourteen `rgpu*` boot-arg selectors besides the mask, many marked legacy. The baseline audit lists each as an intervention
   but the audit's own conclusion ("do not shrink the mask wholesale before T5") was never
   revisited after T5 completed.

## 9. Recommended next steps, in order

1. **Offline, hours.** Add Apple's allocator and channel strings to the classifier. Diff the
   171 and 178-B serials formally and archive the diff. Identify the producer of the
   `initVRAMInfo` struct. Remove `rgpumem=2` and `rgpuvmm=3` from the functional baseline and
   re-run the offline gates.
2. **One launch (needs authorization).** Identical 178 driver, reservation handshake kept but
   pool sizes left at `0x10000000`, both grafts off, `PerformanceStatisticsAccum` captured before
   and after the probe. This settles Finding A and quantifies Finding B in one run.
3. **Then Finding B.** Try one connector in the grafted VBIOS; then present visible/total in
   Apple's order and observe the unequal branch. Measure `vramFreeBytes` each time.
4. **Then Finding D.** Compare Apple's SDMA queue-1 (PAGE) bring-up on this engine with the SDMA
   5.2.6 register set: RB/IB control, doorbell range, `F32_CNTL.HALT`. Decide whether the PAGE
   channel should map to queue 0 or whether queue 1 needs different programming.
5. **Process.** Every hardware run should be compared against the most recent run that reached
   the same or a later stage, not only against its own predicted records. Stop scheduling
   observation-only runs while a known configuration diff is untested.

## 10. Evidence index

| Claim | Location |
|---|---|
| Cap applied only with a PENDING descriptor; sizes `0xf000000` | 178-B `serial.txt:2557-2560,2738`, `src/RaphaelGPU.cpp:5019-5067`, `src/RecoveryReservation.hpp:12,96-104`, `tools/vfio-recover.py:161-171` |
| Runs with/without cap versus hardware submission | Section 3 table; grep commands listed there |
| Apple allocator exhaustion in cold runs | 171 `serial.txt:2784-2810`; 170 and 166-reuse serials, 24 and 14 lines |
| Message producer and pool getters | `x6000.asm:92589-92770` (`allocateLargeBlocks`), `:92937-92948` |
| `enableAllocations` equal/unequal branches | `x6000.asm:91973-92041` |
| `init_pool` full reset | `ioaccel.dis:35299-35380` |
| Superclass prepare cold path | `ioaccel.dis:99768-99800`, `:93194-93260` |
| Fallback path selected by map flag `0x10` | `x6000.asm:5310-5380` |
| Failing map identity and repetition | 178-B `serial.txt:2794-2851` |
| VMM 68 MiB arena, logged `191922176` | `x6000.asm:98103-98130`; 171 `:2546`; 178-B `:2551` |
| Double `enableAllocations` | 178-B `serial.txt:2555-2560,2738-2742`; `src/RaphaelGPU.cpp:4001-4049` |
| Size fields inverted and equalised | 178-B `serial.txt:2415-2416`; `src/RaphaelGPU.cpp:2380-2412`; `x6000.asm:91790-91842` |
| CP consumed VMID-2 IB, SDMA0 Q1 HALT | 171 `serial.txt:3440-3462,3786-3788,3856-3871` |
| Four framebuffer heads | 171 and 178-B `serial.txt` (`setCursorImage` lines), `tools/mkrom.py:111` |
| Code and test volume by area | `wc -l` over `tools/`, `tests/`, `src/` (section 8) |
