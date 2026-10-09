# Live status — 2026-10-09

## Candidate 392: persistent native-scale console; resize-click fix verified

Run `e068279ba75991d9c288c0d141103dda`, metal-216, version 1.0.392, MODE2 #312,
host boot `ba51b3c6-9420-4510-af69-38a42b3c79c7`. Build source `743ee57`, launch
`9cdc4bb`, build ID `ee4fdfb5aa6045e9bb6b83c1ea6756a3`; executable SHA256
`45266d3217ce755cdc61a3d3a19784a9f0377cdb6da57e39718cfe74812def34`.

A fresh guest boot retains installed scale 1 and selects 3840×2160 physical/logical
without rewriting preferences, reinstalling helpers, changing the sealed capture
app or requesting new consent. Payload `5ed647ae17f902d25daf30021a29b50e64e2f27660dc85d8d84c668dd3697633`;
holder 643, resize agent 710, presenter 711 remain unchanged through viewer tests.
Ordinary presenter; experimental immutable-snapshot lease remains unarmed.
Guest display awake assertions hold. Default stereo sample delivery and independent
audio route/volume/mute/defaults/module restoration pass; endpoint audibility and
A/V synchronization remain unqualified.

Automatic 1440×900 → 1000×760 resize exposes a stock spice-gtk 0.42 bug: clicking
without pointer motion delivers stale guest coordinates. One attempt positioned
too late and was discarded; the controlled retry proves no motion across resize.
A same-configuration isolated unpatched library reproduces the failure (about
154×68 pixels wrong). The minimal CLIENT-mode position-before-button patch passes:
0.892/0.852-pixel axis errors, exactly one click, exact RGPU341 text. Actual loaded
libraries are pinned through /proc maps and hashes. System libraries are unchanged;
this qualifies the isolated client patch, not every manager or relative-input mode.
Normal desktop returns. Closing the owned viewer leaves the exact guest alive.

**Shutdown was forced, despite the outer observer's misleading label.** Both
capture hooks see original QEMU PID 113 still in state R when serial closes and
invoke immediate-stop. Docker records SIGTERM/SIGKILL, stop, exit 137 and destroy;
private terminal.json is absent. Original shutdown.json says
exited-after-guest-request; retain that artifact as a reporting discrepancy, not
proof of clean shutdown. No capture/host-safety gate was bypassed. Recovery reports
recovered/authorizes_launch=true. Replay accepts terminal-prefix snapshot 18 with
383 records, retaining one invalid-chunk line and incomplete snapshot 7 (415 chunks).
Captured serial has no panic marker or AMD large-allocation failure message; this
does not resolve candidate 390's rate-limited allocation errors.

Evidence: run/candidate-392-results; c392-persistence.txt;
c392-stationary-analysis.json; c392-stationary-ab-analysis.json;
c392-stationary-{base,fixed}-{libraries.json,manager-events.jsonl,final.txt};
c392-audio-result.txt; c392-audio-restored-independent.json; c392-final-state.txt;
c392-post-input-desktop.png; c392-viewer-close-alive.json; c392-docker-events.jsonl.
The candidate 393 integration worktree contains current docs, the isolated client
patch, and hashed native reports. Full integration suite: 1,449 tests, 8 skipped,
OK (54.621 seconds); run/candidate-393-host-tests.log.
The integration includes the exact tested 392 binary in kext/bin. Hosted CI for
this delivery is pending; previously published dev c8fc5d5 passed test/build
(37975249900). Main remains unchanged.

Shutdown reporting now reconciles the temporal exit observation with bound capture
and private completion receipts after cleanup. Archived 390 remains a verified
private guest completion even after Docker removes the container; archived 392
reports capture-abort-after-request. This fixes reporting, not the underlying
capture-exit race. Original artifacts remain unchanged; abort timing and recovery
gates are unchanged. Replay: run/c393-shutdown-reconciliation-replay.json.

Next: deliver current docs, reporting fix and exact tested 392 binary to dev,
then verify hosted CI.
Qualify installed immutable capture and implement restart-safe ownership before
claiming atomic production output. Sustained 60 Hz/full-frame integrity, broader
crash/independent-host-boot coverage, first-user setup and portability remain open.
VirtualBox GPU transport is unimplemented. Host keep-awake remains active; GPU
stays vfio-pci with power/control=on. No new run before this status is committed.
