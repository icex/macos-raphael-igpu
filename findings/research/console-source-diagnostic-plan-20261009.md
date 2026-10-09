# Candidate351: actual capture source copy diagnostic

Opt in with exactly `RGPU_CONSOLE_SOURCE_DIAGNOSTIC=1`; unset or `0` retains the
normal copy path, other values fail startup. One 3840×2160×4 aligned RAM buffer
is allocated and touched before capture starts. No kernel/GPU blit changes.

For each of exactly1920×1080 and3840×2160, the first eight successful steady-mode
samples compare direct SCK→WC with SCK→RAM→WC under the same read-only CV lock.
The first mode-programming frame is not sampled. Each geometry's counter persists
through mode changes, so returning to that geometry cannot restart diagnostics.
Direct-first and staged-first alternate. Both paths use the existing row widths
and actual source stride; each WC write receives SFENCE. Full destination versus
staged-RAM byte comparison follows outside timed legs. This checks final shared
content, not independent viewer delivery; mismatch exits6, preserving evidence.

CONSOLE_SOURCE_DIAG records actual bytes/stride, order/sample, direct-copy/fence,
source-to-RAM, RAM-to-WC/fence, combined legs, verification, and total diagnostic
work. Eight records per supported geometry maximum. The verification reads WC
memory and can be slow; it affects cache state and subsequent behavior. Compare
only like protocols and both orderings. This experiment is not an optimization:
it copies the same source twice, writes WC twice and holds the source lock longer.
Queue drops and old CONSOLE averages intentionally include extra work, announced
at startup; diagnostic frames are excluded from CONSOLE_TIMING steady-stage
counters. The preexisting timer counts method/log/readback overhead in rows for
these diagnostic frames, so use SOURCE_DIAG leg fields, not legacy copy averages.

Large SCK→RAM cost with cheap RAM→WC supports costly source access; it does not
identify physical memory/cache mode or GPU ownership. A cheap RAM copy with slow
direct path suggests an interaction needing another discriminator. Staging only
helps if the total two-leg cost beats direct copying after correctness checks;
no throughput or frame-atomicity conclusion follows from these samples.

Offline: source review and diff check; existing host console tests do not compile
Apple frameworks. Native compile/sign, normal Settings Screen Recording renewal,
bounded supervised execution and post-diagnostic desktop restoration remain the
root owner's responsibility. No TCC policy/database change is proposed.
