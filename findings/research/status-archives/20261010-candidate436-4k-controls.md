# Live status — 2026-10-10 — 4K QEMU performance

Only full-field 4K QEMU performance is active; other roadmap work is on hold.
Keep the host viewer in a normal window, with no automatic input grabs or USB
redirection. The host user's other applications remain untouched.

Candidate 436 / metal-230 / run 8192b942c66179da66fcda9d9cc957a8 completed.
Its identity-bound Metal probe passed. Two 100-second normal-window controls
used actual 3840×2160 scale-1 guest content, source approximately 60 draws/s,
1440×900 GDK1 scaled viewer and the unchanged candidate-402 pool image.
Localized updates reached 55–57 decoded IDs/s; full-field phases 24.86–26.64.
Both controls had zero invalid or duplicate decoded tokens. These observations
are sampled token delivery, not full-frame integrity, GPU FPS or host scanout.

No comparable new performance regression is established: these results repeat
397/399/402/430's longstanding approximately 25–27/s full-field limit. The Retina
attempt initially selected 1920×1080 logical / 3840×2160 backing, then reverted
to scale 1 and produced invalid tokens; exclude it from throughput qualification.
Sustained 4K Retina at 60 delivered frames/s remains unqualified.

QEMU profiling and exact container ELF offset decoding identify rgpu_diff_bbox's
per-pixel border comparisons as a candidate hot path. Original perf symbol names
resolved against host DSOs and are excluded. Profiling during the failed Retina
attempt establishes execution cost, not a comparable Retina performance control.
Next discriminator: optimize border comparisons while preserving the exact dirty
rectangle, test against a brute-force oracle, then repeat the valid 4K control.

Shutdown receipt: exited-after-guest-request; capture receipts natural-container-
exit. Container inspection reconciliation reported unavailable/mismatched, while
private terminal receipts verified. Recovery recovered / authorizes_launch=true;
retain that limitation rather than calling every shutdown check clean.
Artifacts: ~/macos-vm/run/candidate-436-results/, c436-fourk-b-analysis.json,
c436-retina-c-analysis.json, c436-retina-e-cadence.jsonl.summary.json and
c436-qemu-perf-raw.txt. Research audit contains the comparison and limitations.

1538 host tests passed, 8 skipped before this run. No new verified milestone was
published. Last published dev e240b38ae1d878d429369e41ab5b1179108c2a26 has green
hosted CI 38040411149. Main unchanged. Native framebuffer work remains disabled.


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-437-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`
