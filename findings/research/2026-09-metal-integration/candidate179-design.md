# Candidate 179: correlated page-table commit observer

> **Superseded; never implemented.** Exact backing dispatch and concurrency review found that
> retry ordering, reusable-slot lifetime, and partial counter snapshots make this design unable
> to identify the final failed prepare attempt reliably. The active diagnostic is the direct,
> append-only `AMDAccelVidMemory::allocPhysical` observer described in
> [report-backing-review.md](report-backing-review.md). The remainder is retained as historical
> design analysis, not an active implementation plan.

## Status

Design for review only. No route, source change, build, experiment card, authority, or hardware run
is authorized by this document.

## Problem

Candidate177 placed the first retained native rejection in resource mapping preparation, before
`AMDAccelChannel::submitBuffer`. Candidate178-A and candidate178-B then classified every failed
outer `batchMemoryMapPrepare` call in the final `backing-pte` family:

| Run | Failed outer calls | Capacity | Final VA/reclaim | Backing/PTE | Unknown | Submit calls |
|---|---:|---:|---:|---:|---:|---:|
| 178-A | 483 | 0 | 0 | 483 | 0 | 0 |
| 178-B | 531 | 0 | 0 | 531 | 0 | 0 |

Both runs retained the same coherent map state before and after failure:
`batch=0`, `prepare=0`, `flags=0xb13`, raw GPUVA `0x4000c0000`. The assigned bit remains set.
The unchanged Metal probe ends in status 5 / `e00002bd` with zero completed commands, values, or
pixels. These results exclude batch capacity and final VA allocation/reclaim as the observed
blocking phase. They do not distinguish superclass backing/wiring preparation from page-table
commit, and the aggregate trace does not identify the probe PID or nonce.

Candidate179 should answer that remaining adjacent question with one observation-only route and
exact synchronous correlation to the existing outer wrapper.

## Exact private implementation evidence

The target is the 24G830 X6000 executable:

`/home/bogdan/macos-vm/kdk/x/System/Library/Extensions/AMDRadeonX6000.kext/Contents/MacOS/AMDRadeonX6000`

SHA-256:
`2e364270c3243c532a9428c670313d5afd20406e42d64edb4fa8f3572504104e`.

The exact disassembly is `/home/bogdan/macos-vm/re/x6000.asm`, lines 64585–64667.
`AMDAccelMemoryMap::commitIntoGPUPageTable()` is at file/image offset `0x3b4d2`. Its observed ABI
is `bool(map *)`. The first 17 bytes form complete, non-relative instructions:

```text
554889e5415741564155415453504889fb
```

They decode as the frame setup, register saves, and `mov rbx,rdi`. There is no RIP-relative operand
or relative control transfer in this span. The normal runtime route must still check the exact
binary identity and these bytes before installation.

The method reads task pointer `map+0x90` and branches on byte `task+0x268 == 1`:

- mode 1 loads its call target from `task+0x260` and invokes vtable slot `+0x120`;
- the alternate path loads its call target from raw `map+0x118` and invokes vtable slot `+0x130`.

The alternate pointer is a native commit target. Its broader class and ownership are not yet
proven. The method also reads raw `map+0x18`, raw GPUVA `map+0x98`, and obtains another argument by
calling map vtable slot `+0x168` in mode 1. Reading `map+0x18` here does not establish that it is a
length, and this observer must not call vtable slot `+0x168` a second time merely to capture its
result.

Both callback branches return Boolean in `AL`. The method uses that result to update bit `0x40` in
the 32-bit field at `map+0x138`: clear on success, set on failure. It returns `AL & 1`. These are
build-specific facts, not public ABI.

The exact IOAcceleratorFamily2 archive member has SHA-256
`1700f3badafbb9014d55b7f6ecde5cdff0d585bd1f0e143c9f8465e4466e5d35`. Its superclass prepare
path calls the X6000 override only after GPUVA assignment. No additional superclass or framework
route is proposed because a safe entry span and exact ABI for a single backing subcall have not
been established. A guessed second route would add risk without trustworthy semantics.

## Required outcome classes

For an existing outer call that candidate178 classifies `backing-pte`, candidate179 classifies the
nested commit evidence as:

1. `pre-commit`: no matched commit entry occurred during that outer native call;
2. `commit-false`: at least one balanced matched commit occurred and the final matched native
   commit result was false;
3. `commit-true-outer-false`: the final matched native commit result was true but the outer native
   call still returned false;
4. `unknown`: correlation storage was unavailable, entry/exit counts are unbalanced, map/thread
   context mismatches, snapshots are unavailable, or another impossible state appears.

Successful outer calls remain `none`. Outer capacity, final-VA, and already-unknown calls remain in
their existing candidate178 classes and do not enter this split.

The word “matched” means same map pointer and kernel thread during the synchronous dynamic extent
of one outer wrapper call. It does not mean guest PID, Metal object, probe run ID, or nonce.

## Synchronous correlation

Global before/after counter deltas cannot attribute a commit when concurrent threads run. The
outer `wrapBatchMemoryMapPrepare` therefore owns a fixed, bounded correlation context for the
duration of its single native call:

1. After the existing capture gate passes, obtain `current_thread()` once and scan exactly 16
   fixed slots once, attempting one atomic compare-and-swap from `empty` to `claiming` per empty
   candidate. There is no retry loop. If every slot is occupied, native execution continues and
   this outer result is `unknown`.
2. While the slot is `claiming`, write the map pointer, thread token, and a new monotonically
   increasing outer token, then publish state `active` with release ordering before calling native.
   The commit scan ignores `claiming` slots and reads context only from `active` slots.
3. The commit wrapper, after its own capture gate passes, scans all 16 slots once for the exact
   map/thread pair with acquire ordering. Exactly one match receives commit evidence. Zero matches
   is an `unscoped` commit, which may be a legitimate native commit outside the wrapped outer call.
   More than one match means nested same-map/same-thread reentry; every matching slot is marked
   ambiguous and none receives an attributed result.
4. For exactly one match, it increments matched commit entry/exit counters and stores the final
   native result, task mode, selected raw target pointer, raw fields, and `map+0x138` before/after
   state in that slot.
5. After native outer return, the outer wrapper takes one coherent copy, clears/releases the slot,
   retains the existing map-phase observation, and appends the derived split observation.

The fixed bound is 16 regardless of observed concurrency. Correctness never depends on all slots
being available. Saturation increments a counter and makes only that outer result `unknown`; it
must never be reported `pre-commit`. Nested same-map/same-thread ambiguity likewise makes every
affected outer result `unknown`. Multiple sequential commit calls inside one unambiguous outer
context are counted, and the final matched result chooses `commit-false` or
`commit-true-outer-false` only when entries/exits balance.

The commit wrapper also maintains independent lifetime entry, exit, true, false, mode-1,
alternate-mode, unscoped, ambiguous, saturation, and malformed/unavailable counters. These remain useful after sample
buffers fill. If the route is armed throughout a fully captured interval and its global commit
entry count is zero while coherent outer `backing-pte` failures are nonzero, the entire interval is
legitimately upstream of this commit method. If commit entries are nonzero, per-outer attribution
requires the unique matched slot evidence; global deltas alone are insufficient. Unscoped commits
are reported as coverage context and do not invalidate unrelated native work.

The worker must not treat a mixed read of independently updated counters as malformed. For each
publication opportunity it takes one full counter snapshot, takes one second full snapshot, and
publishes only if the two are identical. If they differ, it defers the summary to a later poll; it
does not spin or wait. The class `total` is computed from the four class counts in that accepted
snapshot rather than maintained as a separately incremented value. A callback legitimately in
flight can therefore delay one summary but cannot create false arithmetic or invalidate the run.
The shutdown/final drain uses the same bounded read-and-defer rule after callback activity has
settled.

## Captured fields

The commit wrapper may copy only values that the exact method itself dereferences and only after
all gates pass:

| Field | Capture | Meaning allowed in output |
|---|---|---|
| `map` | pointer | raw map identity |
| `current_thread()` | pointer token | kernel callback thread identity |
| `map+0x90` | pointer | raw task pointer |
| `task+0x268` | byte, only if task nonnull | native branch mode |
| `task+0x260` | pointer, only in mode 1 | raw mode-1 commit target |
| `map+0x118` | pointer, only in alternate mode | raw alternate commit target |
| `map+0x18` | `uint64_t` raw value | `raw18`; no `length` label |
| `map+0x98` | `uint64_t` | raw GPUVA |
| `map+0x138` | `uint32_t` before/after | commit flags; bit `0x40` consistency |
| native `AL & 1` | Boolean | exact commit result |

A null task or unavailable conditional target makes the contextual sample unavailable/unknown but
does not change the native call. No extra virtual call is permitted. No field is written.

## Hot-path and route safety

- A disabled, partially installed, unready, or non-Raphael path forwards directly to native before
  evaluating any new field address or correlation slot.
- The wrapper calls the native method exactly once and returns its Boolean unchanged.
- It performs no allocation, MMIO, formatted logging, lock wait, sleep, retry, or error rewrite.
- Fixed stores use atomic counters and bounded copies only.
- Already-installed wrappers continue to native-forward safely if another route installation fails.
- Capture becomes active only after all six submission routes pass exact symbol-domain, offset,
  byte-span, ABI, and trampoline checks and one atomic all-routes-ready flag is published.
- `AMDAccelMemoryMap::prepare` at `0x3b3fe` remains unrouted because its initial displaced span
  contains a relative branch outside that span.
- `setSubmissionError` at `0xace4` remains unrouted because its safe entry span is insufficient.

## Retention and output

Use one small production helper/store, exercised directly by the C++ fixture:

- lifetime counters for all four split classes and commit entry/exit/result/mode/correlation states;
- first two samples per non-`none` split class;
- explicit per-class dropped sample counts;
- at most eight detailed split records;
- a separately bounded settled summary cadence, including an initial all-zero readiness summary;
- summary arithmetic where `total == pre_commit + commit_false + commit_true_outer_false + unknown`.

Keep the existing trace/map-phase schemas unchanged. Add a distinct compact prefix such as:

```text
SUB: routes=ok count=6 entries-match=1 capture=armed
SUB: commit-split-summary total=0 pre-commit=0 commit-false=0 commit-true-outer-false=0 unknown=0 ...
SUB: commit-split seq=... class=... outer=... map=... thread=... mode=... target=... raw18=... gpuva=... flags=.../... commits=... result=...
```

The exact schema should keep raw fields visibly raw. A worker-thread token must not be presented as
issuer identity. Phase-summary cadence must have its own cap so existing summary traffic cannot
consume all opportunities to publish final split counters.

Candidate178's submission diagnostic has a documented maximum of 174 critical records in the
512-record channel. Candidate179 adds at most eight detailed records, a six-route readiness row,
and no more than 32 split summaries: at most 41 additional records and 215 total. Keep overflow and
truncation checks. Do not reduce the 512-record capacity.

## Parser and admission requirements

The serial parser should accept only exact route, detailed, and summary forms; reject malformed
integers, Boolean/result values, modes, counts, duplicate sequence numbers, and summary arithmetic.
When the candidate179 experiment requires the commit observer:

- readiness requires the existing strict route row with `routes=ok`, `count=6`,
  `entries-match=1`, `capture=armed`, and the initial valid zero split summary before
  the workload starts;
- any explicit malformed split record makes the run invalid, even after probe output;
- sample drops are legitimate when lifetime counters and critical replay remain valid;
- actual commit calls are not a readiness prerequisite because requiring workload activity before
  launching the workload would create a circular gate;
- the existing final compute/render validator remains unchanged.

The experiment card uses the unchanged functional boot arguments and unchanged probe. A new
diagnostic boot token may arm this observer, but it must not alter resource behavior.

## Offline verification

Focused pure C++ tests must exercise the production classifier, correlation slots, and store:

- outer assigned-VA failure with zero matched commits → `pre-commit`;
- one balanced false commit → `commit-false`;
- one balanced true commit plus outer false → `commit-true-outer-false`;
- multiple commits use the final balanced result and preserve total entry/exit counts;
- no slot, mismatched map/thread, null task, unbalanced entry/exit, or invalid result → `unknown`;
- nested same-map/same-thread reentry marks every competing context `unknown` and never chooses the
  first slot;
- a synthetic commit interleaved while a slot is `claiming` cannot read partial context or match
  that slot;
- successful outer call → `none` regardless of raw GPUVA zero;
- counters continue after every sample class overflows;
- concurrent synthetic contexts never cross-pair, and more than 16 active contexts saturate
  without retries or incorrect `pre-commit` classification;
- a production-helper counter mutation between the worker's two snapshots suppresses that
  publication without marking it malformed, while the next stable pair publishes exact arithmetic;
- full-width raw fields and `map+0x138` are preserved.

Source-shape tests must prove:

- inactive direct-forward precedes correlation and all field reads;
- native is called exactly once;
- the exact `0x3b4d2` ABI, 17-byte span, offset, symbol, and `[x6]` preflight domain are pinned;
- route readiness expects exactly six routes;
- record and summary budgets remain below 512.

Parser/classifier tests cover missing, failed, duplicate, and malformed route/readiness rows;
malformed detailed records before and after probe; incorrect summary totals; legitimate sample
drops; and a zero-call readiness state. Finish with the full translation-unit syntax check and the
offline preflight against the exact 24G830 X6000 binary. No build, stage, version bump, or hardware
action belongs to design verification.

## Interpretation and next repair boundary

| Observation | Proven conclusion | Next offline work |
|---|---|---|
| All coherent outer failures are `pre-commit`; global commit entries zero | superclass preparation stops before the X6000 commit override | disassemble the exact superclass prepare interval and prove one safe backing/wiring subcall before proposing repair |
| Matched final commit returns false in mode 1 | object at `task+0x260`, slot `+0x120`, rejected the final commit | recover exact callback symbol/ABI and its failed prerequisite |
| Matched final commit returns false in alternate mode | raw target at `map+0x118`, slot `+0x130`, rejected the final commit | recover exact target class/ABI and rejected raw input |
| Commit returns true but outer returns false | failure lies after successful commit or correlation assumptions are incomplete | follow the exact outer return path; do not “fix” commit |
| Unknown, ambiguity, or saturation dominates | instrumentation cannot support attribution | repair observation/correlation offline before another run; unscoped native commits remain separate coverage context |

A commit-false result does not yet prove malformed PTE contents; the callback can fail while
allocating update storage or mapping backing. A pre-commit result does not prove physical memory
exhaustion. Any behavioral repair requires the immediately rejecting native branch and a concrete
violated invariant. There is no automatic retry, cap increase, or follow-on hardware authority.

## Evidence references

- Candidate178 phase semantics:
  `findings/experiments/metal-010-177/memory-map-phase-design.md`, SHA-256
  `cfd1a7ed410bb418fc15aff6b5b9f6849e8cb628e29ae88bcdc68f7e9be85f59`.
- Candidate177 submission boundary:
  `findings/experiments/metal-010-177/notes.md`, SHA-256
  `d0667b1a9c0939b7c97f20af8b17e098d1c024087f4349aff04138be80cc302c`.
- Candidate178-A events/probe/serial SHA-256:
  `bca76681ba59335cd4da50815774307ca5cf6bca47ee84a3c3d766a12187a016`,
  `076bbc22f0922827ab1d8eda362fa13dea80e2118ab58a1e3e33d76b47e4e743`,
  `c4a877508517dc78402e0b82c42dd5a2a20113a90965a27f92f5b0b6d7ac918`.
- Candidate178-B events/probe/serial SHA-256:
  `ece23f169283c148b1e5b5b758e539218bf3f20ca6226860ab68b35746455966`,
  `b49d5d2c9a2fcf7408ea26d237f2ed11281604c69c0e9805d47ff9677bc61755`,
  `a5b1317d78c52b22d776feec72bb91877b82000c2eb16d03f0d62f9a7d98201c`.
