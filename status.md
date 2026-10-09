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

## Parallel accelerated-console milestone and remaining work

Root completed candidate 402's native pool performance/regression cycle with
verified natural shutdown and authorizing recovery; its exact report/status lives
on candidate 402 commit 00721a2 pending reviewed integration. Smaller snapshot cost
does not yet qualify full-field 4K at 60 Hz. Actual VBox accelerated transport,
first-user console-only setup and sustained desktop qualification remain open.
Both native runs are stopped; root owns any later launch. No new launch admission
is granted by this status. Dev milestone integration is handled separately; main
remains unchanged.
