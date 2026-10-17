# Candidate397: native snapshot stage timings

Run `beb488f101c8ed33f8460d4a5ce6ce5e`, metal220, version1.0.397. Manifest source commit `9d5bb8bee88f149a0e64ac72f9d1f5f134f9f50a`, built-from commit `19b77a01e2d5863dd8b567366267a26458475047`, build ID `997d0d87122748708e34a1fa05c70f08`; executable SHA256 `7a9bae3f74471c1b26b4f7d15144283776ef7c9a7ef7203f984075d4b99b599b`. Opt-in kernel instrumentation measures the existing private-staging path; no copy/presentation optimization is claimed.

## Functional and measurement results

The installed snapshot desktop returned after the mixed-motion fixture. The hardware owner visually checked `c397-motion.png` and `c397-desktop.png`; awake state and original VM survival after viewer completion are separately retained. No new input/audio qualification is inferred.

Actual manager observation of the3840×2160 source in a1440×900/GDK1 viewport retained4160 unique token IDs in100.022947 seconds (41.5905 IDs/s), zero invalid or duplicate samples. Complete localized phases0/2/4 were approximately51 IDs/s; full-field phases1/3 approximately27 IDs/s. Phase5 contains only53 samples and does not qualify a complete phase. Source DRAW IDs associate the phase records; guest/host clocks are not subtracted. These are token-region observations, not full-frame integrity, GPU FPS, physical scanout, or60Hz qualification. Scaling remains part of this actual viewer configuration.

Kernel analysis retains61 metric rows, all with numeric stage/count/dropped fields intact.24 rows lose the trailing saturated flag to line truncation; its absence is not asserted equivalent to an observed zero. Selected windows37..58 cover5227 commits (4K,count>=100,dropped0; existing numeric totals are not saturated maxima), but are **not phase-aligned**. Weighted means:

| Stage | Mean milliseconds |
|---|---:|
| lock |0.000137|
| private RAM→WC copy plus fence |1.548818|
| geometry MMIO |0.235640|
| doorbell |6.872031|
| ACK checks |1.315673|

The observed doorbell interval is the largest measured stage. It includes synchronous host work/scheduling; the separate ACK reads also incur emulation overhead. The measurement does not isolate a particular host routine or justify calling the entire interval memcpy. It provides the next discriminator without establishing a performance gain or regression against an unmatched prior run.

## Capture and lifecycle

Verdict valid CORE_PROBE_PASS, earliest failure null. CR2 replay selects snapshot18/365 records with terminal-prefix-open tolerance; one malformed transport line5670 and incomplete snapshot7 (76 chunks,noEND) are retained. Capture is not described as error-free.

Shutdown reports exited-after-guest-request and private_terminal_verified=true; the private terminal records guest-shutdown/process_exited=true. Both capture hooks report natural-container-exit with deferred=true and shutdown_event_wait=true, approximately1.660seconds. Critical ends recv-reset, console clean EOF. The retained stopped-container-inspection warning follows container removal; independent Docker events show container exit0 without container kill/stop actions. Recovery is recovered/authorizes_launch=true. These positive receipts do not establish universal crash/closure recovery.

## Evidence and next scope

The accompanying `console-snapshot-timing-native-evidence-20261009.json` hashes raw observer/source/presenter/serial inputs, analysis programs/results, screenshots and lifecycle receipts. No source-CRC diagnostic or endpoint audio rerun is inferred. The last delivered dev milestone remains candidate395 (`c1f64d0`, hosted test/build green); candidate397 timing evidence is not yet a delivered optimization. Separate candidate398 VirtualBox disk preparation has not booted a guest or qualified acceleration.
