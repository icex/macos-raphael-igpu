# Live status — 2026-10-11 — 444 full-field 4K window: lock contention and client copies

Only full-field 4K performance is active. All 120 Hz / 5K / native-framebuffer / other
roadmap work is on hold. Host viewer stays a normal window (no fullscreen, grabs or
automatic USB). Host sleep:idle blocker `rgpu-work-awake` retained.
No VM running; all runners finished, guest test jobs removed, viewers and relay stopped.

Candidate 444 / metal-238, build 245bdd63d44749ad908125b57e216c88, GPU source d1deade…
unchanged, guest presenter unchanged, boot ba51b3c6…, MODE2 342-345. Server arms by pins:
439 baseline, unlocked snapshot copy, + publish-on-commit, + SPICE update creation without
the global lock (arm D, image a18ff5a…). Client: 441 raw-primary GL, then a private
zero-copy-receive build (aligned reusable large buffers, raw bitmaps wrapped in place).

Loss budget (443 budget-d, 439 image): full-field ~58 captured → ~45 presenter commits
(commit waits for QEMU's global lock behind SPICE update creation) → ~42 published/sent.
444 full-field client IDs/s · dequeues/s: a 38.7/39.1 · 38.7/39.3; b 40.1/39.5 · 40.4/41.2;
c 38.8/39.3 · 38.9/39.3 (0 replaced, localized 57.7-57.9); d 39.3/40.3 · 53.1/53.6 (viewer
thread 90% at ~1.3 GB/s raw); LZ4 34-35 (rejected); arm D + zero-copy client 50.35/49.79 ·
52.5/52.2, localized 57.3, viewer 79%. Moving GL output with that client: 100/100 sampled
readbacks valid, unique, strictly increasing.

Blocking issue: remaining full-field gap is the presenter (single frame in flight, ~6-10
drops/s) and one client blit + texture upload per frame. Next: presenter overlap (needs a
rebuild and one Screen Recording consent renewal in the guest), then client copy reduction.
Moonlight: guest Sunshine (ScreenCaptureKit build) runs and answers through the relay; the
host client is not paired (guest trusts only the user's MBP and iPad); deferred by the user.

Lifecycle: 444 a-d CORE_PROBE_PASS, exited-after-guest-request, natural captures, private
terminal verified, stopped-container warning retained, recovery authorizes_launch=true.
443 budget-d (with seven slirp forwards + relay) was strictly capture-abort-after-request
(QEMU still exiting when captures ended); recovery authorized reuse. One profiled viewer
crashed after DWARF profiling (unexplained; not reproduced unprofiled).
Host suite 1559 tests (8 skipped) passed before launch. No main publication.

Evidence: findings/research/console-4k-pipeline-locks-20261011.md and evidence JSON;
~/macos-vm/run/c443-d-*, c444-*, candidate-444*-results.
