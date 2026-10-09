# Live status — 2026-10-10

## Candidate 402: private snapshot pool tested and stopped

Run `92b1f812226bb5f8594dbcbde467ef3d`, build
`582b7a9276a54795ad3ff711d4130474`, source
`c9a3a5d0d66e9dbd9e789df709068afc14bc6bea`, launch `5f39b75`.
The opt-in private host pool lowers measured host snapshot copy from 399's
6.834 ms to 1.948 ms and guest doorbell from 6.983 ms to 1.969 ms.
Selected host windows contain 5677 reused successes, zero fallback/new blocks;
three blocks occupy 96 MiB. Host and guest timing windows are independent.

Actual-manager 4K mixed workload: 4402 unique tokens in 100.007 seconds, zero
invalid/duplicate samples. Localized phases reach about 57 IDs/s; full-field
phases remain about 25 IDs/s versus 399's 26.4. This single comparison does not
qualify 4K at 60 Hz or a uniform throughput gain. The short final phase is excluded.
Root viewed both motion and returned desktop screenshots.

Native isolation/cleanup passes: all 481401 controlled-frame pixels match before
and after stale mapping writes, retained unmap/remap succeeds, old calls/WC aliases
and excess retained buffers refuse, and all cleanup returns succeed. Unchanged
sealed app restart resumes ACKs; actual-manager odd resize reaches 1235×743.
Input passes five targets, exact text, zero misses/geometry changes. Audio sample
delivery passes separated 997/1498 Hz channels; independent route restoration
passes. Endpoint audibility is not claimed.

Shutdown is verified: private guest-shutdown/process-exited terminal, both capture
hooks natural-container-exit with deferred event waits (~0.618 s), Docker die 0
without kill events, and recovered/authorizes_launch=true. Original reconciliation
retains the unavailable stopped-container-inspection note. CR2 snapshot 18 has
330 records under terminal-prefix tolerance, two corrupt lines and incomplete
snapshots 7/14; logs are not claimed perfect. The GPU cycle is stopped.

Evidence: [native pool report](findings/research/console-snapshot-private-pool-native-20261010.md)
and its hashed manifest. Prior status is archived under
`findings/research/status-archives/status-before-candidate402-20261010.md`.

## Remaining work and delivery

Full-field 4K delivery remains the performance blocker. Repeatability, first-user
console-only installation and actual accelerated VirtualBox transport remain open.
VirtualBox software desktop evidence is separate from Raphael/QEMU acceleration.
Root owns subsequent native launches; candidate 406 software qualification is
prepared separately. No new launch is authorized by this status text.

This candidate's results are local pending reviewed milestone integration. Current
published dev is `84159a9d33ab22e385e56f4861b0e6dae069cbf4`; its hosted test and
build jobs passed (Actions 37993406232). Main remains unchanged. The checked-in
binary still represents tested candidate 399 until explicit milestone delivery.

## Separate VirtualBox software path

Candidate403 reached an eight-vCPU software desktop with RealTSCOffset; no new
input or graceful shutdown was qualified. Deadline poweroff and later verified
unregister remain explicit in its report. The exact transient post-stop state-query
retry is integrated without relaxing identity or timeout gates. Candidate406's
committed plan/source is included; its later native result remains root-owned and
will be recorded separately.
[403 evidence](findings/research/virtualbox-eight-cpu-real-tsc-native-20261010.md).
