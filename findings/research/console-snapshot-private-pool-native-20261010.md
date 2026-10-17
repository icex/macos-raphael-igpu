# Candidate 402: native private snapshot pool timing

Completed native performance, regression and lifecycle audit.
Run `92b1f812226bb5f8594dbcbde467ef3d`, build
`582b7a9276a54795ad3ff711d4130474`, source
`c9a3a5d0d66e9dbd9e789df709068afc14bc6bea`, launch commit `5f39b75`.
Runtime image is `sha256:6d91e1ff4192f9c0fe693a171a2a2bbdb7b9d2a96b184e17a38776a2119c2bfa`.
The installed snapshot presenter remains unchanged. This tests the opt-in private
three-block host pool described in `console-snapshot-private-pool-20261010.md`.

## Observed timing and delivery

The 100.007-second actual-manager ROI observation retained 4402 unique token IDs,
zero duplicates and zero invalid samples (44.017 distinct IDs/s overall). The
source completed its 110-second mixed workload. Root visually verified both the
motion screenshot and the returned desktop after TOKEN_DONE. Token validity is
partial pixel evidence, not whole-frame integrity, GPU FPS or physical scanout.

| Metric, mean milliseconds | Candidate 399 fresh backing | Candidate 402 pool |
| --- | ---: | ---: |
| Host allocation / wrapper acquisition | 0.020582 | 0.003044 |
| Host snapshot copy including first touch | 6.834006 | 1.948414 |
| Host pending-surface release | 0.095214 | 0.000276 |
| Guest private-buffer copy and fence | 1.556178 | 1.569591 |
| Guest commit doorbell | 6.982687 | 1.968576 |
| Guest ACK checks | 1.468294 | 0.654529 |

Strict raw-log replay reproduces both retained timing analyses. Candidate 399
uses independently selected host/guest windows 8–27, 4691 commits in each.
Candidate 402 uses windows 9–28: 5677 host commits and 5679 guest commits. These
are independent steady-geometry aggregates, not a matched set of individual
frames. No guest/host clock subtraction or phase alignment is claimed. All
selected rows have complete stage fields, zero saturation and zero dropped
geometry; host allocation/copy/free call counts conserve commits.

The cumulative pool counters at boundaries 8 and 28 differ by exactly 5677
attempts, successes and reused leases, with zero new blocks or fallbacks.
All 35 retained pool rows report three blocks, 100663296 bytes, no fallback and
no saturation; the final row has 6507 attempts/successes, three created blocks
and 6504 reused leases. This measures pool reuse, not total QEMU memory usage.
The fallback path was not exercised by this native workload.

| Completed workload portion | 399 decoded ID intervals/s | 402 decoded ID intervals/s |
| --- | ---: | ---: |
| Localized phase 0 (partial initial observation) | 51.05 | 57.14 |
| Full-field phase 1 | 26.40 | 24.87 |
| Localized phase 2 | 48.84 | 57.32 |
| Full-field phase 3 | 26.39 | 25.15 |
| Localized phase 4 | 49.38 | 57.43 |

The short final phase is excluded (402: 81 samples across 1.960 seconds; 399:
49 across 0.990 seconds). Phase association uses decoded IDs and completed
source DRAW records; guest source times and host observer times stay separate.
Rates use unique intervals divided by the observed same-phase span, not the
scheduled phase duration. Source draw cadence is approximately 60/s in both.

The smaller snapshot-copy and doorbell means support reduced measured host
snapshot cost. Localized delivery improves in this pair; full-field delivery
does **not** improve. This is one sequential trial per configuration, without
randomized repeats or matched per-phase timing windows. It does not establish a
universal throughput gain or 4K at 60 Hz. Candidate 399's late desktop screenshot
was the wrong host window and is not used as a visual comparison.

## Observer and qualification limits

Both cases use a 3840×2160 scale-1 source and an actual-manager 1440×900 viewport,
GDK scale 1, scaling enabled, guest resize disabled and monitor 0. Candidate 402
has 4403 invalidate callbacks started, 4402 completed and the final terminating
callback in progress; its cost is excluded. Widget draws completed 4391 times,
21.358 seconds aggregate wall time, maximum 29.932 ms. These are whole-window
counts and costs, not phase-specific frame completion. Maximum heartbeat gap
was 414.982 ms; maximum observed token staleness was 64.936 ms. Synchronous ROI
sampling and GTK rendering can affect throughput. No source-CRC window is
imported into this result.

## Completed native regressions

The standalone native fixture passes with `cleanup_ok=true`, last IOReturn 0,
and all retained mappings/connections explicitly released. Retired A can unmap
and remap its own RAM; old commit/re-ARM and WC alias attempts are refused, as is
a fifth retained payload. Independent QEMU screenshots before and after stale-A
writes each compare all 481401 pixels of the 801×601 published B frame with zero
mismatches. This is full-pixel evidence for that controlled frame, not every
animated desktop frame.

After the fixture, the sealed installed capture app remained unchanged and an
owned restart resumed snapshot ACKs (49 then 68). Actual-manager resize reached
1235×743. The corrected overlay input fixture completed five target hits, zero
misses, exact text `RGPU402C1234`, zero geometry changes and passed=true; retained
manager events and UInput injection evidence identify the actual input path.
Awake assertions were present. Root visually verified the final desktop screenshot.

The bounded default-application audio capture passes at 48 kHz with separated
997/1498 Hz channels. Independent restoration verifies the same stream, original
sink/volume/mute/defaults and absence of the owned null sink/module. This proves
VM USB/QEMU/Pulse sample delivery, not audible output at the user's endpoint.

## Capture and final lifecycle

The run ended with `exited-after-guest-request` and independently verified private
`guest-shutdown` / process-exited terminal evidence. Both capture hooks report
`natural-container-exit`, deferred=true and shutdown_event_wait=true, approximately
0.618 seconds; critical transport ended with recv-reset, console with clean EOF.
The original reconciliation retains its stopped-container-inspection unavailable
note. Exact-container Docker events independently show die exit 0 and destroy,
without container kill events. Recovery is recovered and authorizes_launch=true.

Capture is not perfect: replay uses snapshot 18, 330 records, terminal-prefix-open;
two corrupt lines (invalid chunk bounds / malformed transport) and incomplete
snapshots 7 (816 chunks) and 14 (517 chunks) remain. No open attempt is reported.
These capture limits remain separate from successful pixel/input/audio evidence
and verified shutdown/recovery. Original receipts are unchanged.

The companion manifest hashes original bounded evidence. Private QEMU launch logs
are hash-only and must not be printed or published with private arguments.
