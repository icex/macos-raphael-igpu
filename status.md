# Live status — 2026-10-10

## Candidate 406: eight-vCPU VirtualBox software qualification, stopped

BootE UUID `339a6c46-92f4-4c31-b32c-80351ac14947`, source `7132cd4`, reaches the
actual macOS desktop with RealTSCOffset at 4699997773 Hz and eight CPUs. Root
verified Terminal marker VBOX406_INPUT_OK, build 24G830 and owned awake assertions.
The owned launchctl awake job was removed and its display/system idle assertions
cleared before ACPI shutdown. Initial keyboard interaction was slow; no latency
claim. PerfPowerServices around one CPU core remains an unresolved software issue.
Retained UART has no panic/monotonicity marker; short duration is not sustained
SMP qualification. No physical GPU, VFIO or Metal acceleration was used.

Natural guest shutdown is verified: ACPI S5 at 264.423 s, OFF at 264.426 s and
TERMINATED at 264.475 s, before the 300 s deadline. Original result poweroff,
unregistered=true, one attempt, no cleanup error; independent exact-UUID absence
was confirmed 15.846 seconds before deadline. The cleanup retry branch was not
exercised. Automated guest_boot_qualified=false remains unchanged; manual visual,
input and awake evidence is separately scoped in the report.

Host suite: 1474 tests passed, 8 skipped, 56.685 seconds. Evidence:
`findings/research/virtualbox-eight-cpu-qualified-native-20261010.md` and companion
manifest. Prior status is archived as `status-before-candidate406-20261010.md`.

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

Both native runs are stopped. Full-field 4K delivery remains about 25 decoded
IDs/s despite lower snapshot copy cost; sustained 4K60 and whole-frame dynamic
integrity remain unqualified. VirtualBox PerfPowerServices CPU use, sustained SMP
stability, first-user console setup and actual accelerated VBox transport remain
open. The 405/408 source audits are integrated; no VBox presentation adapter is
implemented. Root owns later launches; this document grants no admission.

Candidate407 integrates these milestones locally for review. The checked-in
binary and unchanged canonical manifest are the exact tested candidate402 build
582b7a9276a54795ad3ff711d4130474, executable SHA256
7bebb5596f5aa31cf1cfff6c4e95b185b74b254ba62c9e01ac403317a19b1bd5.
Published dev remains84159a9d33ab22e385e56f4861b0e6dae069cbf4 with hosted test/build
passed (Actions37993406232), until root publishes and verifies the new exact
commit. Main is unchanged. Integrated407 checks are pending; 406's suite above is
historical evidence, not a claim about this merged tree.
