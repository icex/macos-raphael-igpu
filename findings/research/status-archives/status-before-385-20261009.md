# Live status — 2026-10-09

## Candidate383: SPICE agent transport and bounded existing-mode resize pass

Run c23d74d98b192d4a33a08376d9a64811, metal211,1.0.383,MODE2#307,
bootba51b3c6. Source777bf28; build42a989b30403424e97098f562d46651e.
The previously omitted CONSOLE_VDAGENT option now crosses the actual systemd
launch boundary. Observed PCI virtio-console topology matches the manifest;
AppleVirtIOConsole exposes /dev/tty.com.redhat.spice.0. Exclusive second-open
refusal and real bidirectional SPICE capability exchange pass.

Candidate384 diagnostic sources ran against this same383 VM. Actual virt-manager
window changes selected existing2560x1440 and3840x2160 HiDPI modes through standard
SPICE monitor requests. Final40s diagnostic ended39.028s, exit0,7requests,
5verified applications; no helper timeout, no remaining tty holder. Settled
manager pixbuf and monitor maps match both sizes. Independent post-agent macOS
mode and presenter poll remain3840x2160. Correct desktop screenshot retained.

Early helper used application-scoped CGDisplaySetDisplayMode and mode drifted;
session-scoped transaction fixes persistence. Duplicate exact modes now skip
reconfiguration. Initial launchctl submit diagnostics restarted; removed and
replaced by explicit KeepAlive=false one-shot jobs. Invalid GI primary dimensions
are excluded: enum field was declared pointer in installed typelib. These
failures and source/hash boundaries are retained in the research report.

Audio sample delivery passes. First route restoration failed and required an
explicit identity-guarded retry; revised bounded reconciliation passes native
capture and restores route, volume, mute, defaults and removes owned module.
This proves samples, not endpoint audibility or A/V synchronization.

Viewer closure leaves exact VM alive. Harness stop then exits after guest request;
private terminal guest-shutdown/process_exited=true, Docker die exit0, no kill/stop
events. Both captures record natural-container-exit, deferred0.432s,
shutdown_event_wait=true, zombie=false; console EOF, critical recv-reset.
Producer quiesce snapshot18 accepted terminal-prefix. Recovery recovered,
authorizes_launch=true. CORE_PROBE_PASS is separate from desktop qualification.
Host remains awake, vfio-pci, power/control=on. No reboot or amdgpu rebind.

Evidence: run/candidate-383-results, c383-monitor-idempotent-complete.txt,
c383-manager-resize-idempotent.jsonl, c383-resize-session.png,
c383-audio-reconciliation*, c383-docker-events.jsonl. Candidate384 report contains
full experiment history. Native383 prelaunch1333tests/8skip; latest diagnostic
suite1367tests/8skip passes (54.641s), run/c384-host-tests-idempotent.log.

Remaining: persistent packaged agent, arbitrary viewport mode creation, input
coordinates after automatic resize, broader lifecycle and performance/corruption
qualification. Existing381 performance evidence remains valid only for its
measured workloads. Dev c6d7ef13cb16a90d0bbf45c95fd9ca2ec3e63b3c delivers383/384 with
hosted37968448791 test/build green; release skipped. Main unchanged. Do not call this completed roadmap work.


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-385-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`
