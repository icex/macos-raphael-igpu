# Live status — 2026-10-10 — 443 moving GL output and pacing comparison

Only full-field 4K performance is active. All 120 Hz / 5K / native-framebuffer / other
roadmap work is on hold. Host viewer stays a normal window (no fullscreen, grabs or
automatic USB). Host sleep:idle blocker `rgpu-work-awake` retained.
No VM running; all three 443 runners finished, guest test jobs removed, viewers closed.

Candidate 443 / metal-237, build bd869353edd843aebb3b2edfd3728a6b, GPU source d1deade…
unchanged, boot ba51b3c6…, MODE2 338-340. Exact 441 raw-primary GtkGLArea client.
A-B-A cycles: a default pacing (439 image), b 17 ms start-relative (440 image), c default.

Moving GL output: 300/300 sampled FBO readbacks valid across the three cycles, 0 missing,
strictly increasing fresh tokens at full 3840x2160 → 1440x810. Sparse sampled frames only,
not every-frame integrity, text quality or FPS.

Performance (source outlived every 100 s observer; standard analyzer accepted all three):
full-field client IDs/s a 41.77/41.45, b 39.40/37.83, c 38.61/39.44; localized ~56-57.
The 441 GPU-scaling gain repeats (Cairo was 23.7-23.9). Start-relative pacing raised
full-field refresh 47-48 → 58/s but dequeued commands stayed ~41/s: no material delivery
gain, and the a→c drift is as large as the arm difference. Blocking issue: ~40 commands/s
are created from full-field refreshes regardless of refresh rate, upstream of the client.

All runs CORE_PROBE_PASS, exited-after-guest-request, natural captures, private terminal
verified; stopped-container reconciliation warning retained; recovery recovered,
authorizes_launch=true. Host suite 1559 tests (8 skipped) passed before launch.
Checked-in 428 bundle unchanged; no main publication; renderer remains opt-in research.

Evidence: findings/research/console-gl-pacing-20261010.md and evidence JSON;
~/macos-vm/run/c443-* and candidate-443{,-attempt-start-b,-attempt-default-c}-results.
Next: compare per-phase guest presenter publications with QEMU update/command creation to
locate the full-field refresh-to-command gap. No further pacing work. Goal remains active.
