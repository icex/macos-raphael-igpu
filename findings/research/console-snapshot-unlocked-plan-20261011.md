# Candidate 444: snapshot copy outside the QEMU global lock

Only full-field 4K performance is active. Host viewer stays a normal 1440x900 window (GDK1, X11),
no fullscreen, input grabs or automatic USB. Host awake blocker retained.

## Why: the 443 budget-d loss budget

443 attempt `budget-d` (run `b056c43988e9507beb3f6d7306cc5809`, 439 image, default pacing) repeated
the coordinated GL performance window and additionally captured the guest presenter log and QEMU's
`bochs-snapshot-timing` windows (host monotonic, aligned to the analyzer's phase bounds).

Full-field phases, per second:

| Stage | Rate |
|---|---|
| ScreenCaptureKit complete frames reaching the presenter (copied + dropped) | ~58 |
| Presenter copies + snapshot commits | 44.1-45.9 |
| QEMU commits replaced before publication | 2.2-3.8 |
| Published snapshots ≈ SPICE commands ≈ client unique IDs | 41.9-42.6 / 42.0 / 42.0 |

Localized phases: 58 commits/s, 0.2-2.2 replaced/s, ~56-57 client IDs/s.

The presenter is the main loss. It keeps one frame in flight; its worker time rises from ~8.3 ms
(localized) to ~15.6 ms (full-field): lock 3.3→4.7, rows 1.3→3.4, snapshot commit 3.7→7.5 ms.
QEMU's own staging copy inside that commit is only ~3.3 ms, so ~4 ms of each full-field commit is
spent waiting for the global lock while the main loop creates SPICE updates (~4.9 ms each, mirror
2.5 + bitmap 2.3 ms, under the same lock). The copy itself also holds the lock and delays refresh
(48/s full-field), which is where the ~3/s replacements come from.

## Change

444 image = 439 image with one rebuilt QEMU binary. In `bochs_snapshot_write` the 4K
staging-to-surface memcpy runs with the global lock released. Validation, pool allocation,
pending replacement and counters stay under the lock. A second commit during the copy is refused
(error 6); after the copy the state, epoch and sequence are revalidated and a stale copy is
discarded (error 7). Patch: `patches/qemu-10.1.2-bochs-snapshot-unlocked-copy.patch` (applied to
the 437 source that produced the 439 binary, verified identical). QEMU `copy_us` now includes
re-acquiring the lock.

Expected: full-field commit falls toward the bare copy cost, presenter worker below the 16.7 ms
frame budget, fewer presenter drops, refresh less delayed. Not expected to remove the presenter's
single-in-flight design limit; that is the next change (needs a presenter rebuild and consent).

## Measurement

One card (metal-238), two arms by pins on the same boot, A-B-A:
`pins-bochs-client-lossless.json` (439) and `pins-bochs-unlocked-copy.json` (444, `dade0cb…`).
Per arm: the coordinated 100 s GL observer with a 120 s mixed source started within the first
QEMU timing windows, presenter log, QEMU snapshot timing/pool lines, SPICE timing trace,
standard pipeline analyzer. Report per stage: presenter copies/drops, commits, replacements,
commands, client IDs; and commit/worker timings.
