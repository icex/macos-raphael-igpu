# Resume prompt: full-field 4K after candidate 443

Continue /home/bogdan/src/macos-raphael-igpu from remote dev (fetch first) in a fresh
candidate worktree under ~/macos-vm/run/worktrees/. Read AGENTS.md, status.md,
docs/host-safety.md and docs/running-an-experiment.md. This is historical evidence, not
live host state: recheck boot, VM, viewers, awake blocker and the last recovery receipt.

Only full-field 4K performance is active; everything else stays on hold. Keep the host
viewer a normal window and the host awake blocker running. Launch with tools/cycle.py
under systemd-run; stop through stop-requested.

443 result: 300/300 sampled moving GL readbacks valid; default-pacing GL full-field
38.6-41.8 IDs/s (441 gain repeated, clean source overlap); 17 ms start-relative pacing
raised refresh to 58/s but not delivery. About 40 commands/s are dequeued from full-field
refreshes regardless of refresh rate. Do not pursue more pacing variants.

Operator recipe (candidate-443/.research, untracked): c443-drive.py CYCLE RUN_ID
[moving|perf|all] runs the GL readback check then a coordinated window (viewer first,
then 120 s source, 100 s observer). c430-source-cadence accepts at most 120 s. Same card
runs either server image via pins; use --attempt NAME plus stage-candidate
prepare_attempt_copy for repeat cycles; run-gpu-test appends to status.md, so restore it
before the next cycle's clean-worktree check.

Next: per-phase guest presenter publication counts versus QEMU update/command creation,
to decide whether the ~40/s ceiling is guest publication or QEMU's update-to-command path.
Then GL filtering/text quality, input/cursor/resize/fallback, and the sustained 60 Hz gap.
Main publication needs a fresh explicit request.
