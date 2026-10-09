# Candidate377: bounded diagnostics for a live-process capture refusal

Candidate374, run `f5fd1fe85aeb7a340b0ac52a4d78157a`, reached guest shutdown,
but both initial capture-exit witnesses saw original PID113 in **D state**.
They refused completion and shutdown deferral. Capture hooks force-stopped the
container; no private terminal was produced. Candidate373's repeat-witness137
fix was not exercised. Recovery independently authorized reuse.

## Exact retained chronology

2026-10-09 UTC:

| Time | Observation |
| --- | --- |
|15:21:01.801925| Identity-bound guest SHUTDOWN; monotonic74253.873776270 |
|15:21:01.826 approximately| Critical recv-reset74253.898085856; console clean EOF74253.898350117 |
|15:21:01.9173–.9175| Both initial `inspect-exited` commands start |
|15:21:01.9800| Both witnesses exit0, returning original-process/D-state refusal |
|15:21:01.995492 and15:21:02.000095| Docker SIGTERM events |
|15:21:02.004437 and.008737| Docker SIGKILL events |
|15:21:02.085922| Docker daemon receives containerd task-delete |
|15:21:02.321091| Outer container die event, exit137 |
|15:21:02.426662| Container destroy |

Both original hook receipts report `immediate-stop`, `deferred=false`,
`original-pid-present`, stateD, elapsed~.422s. The outer harness records
`exited-after-guest-request`, which is temporal ordering, not a clean shutdown
proof. There is no private `terminal.json` or observed STOPPED event in the retained
private events. An earlier inference of genuine private terminal was retracted;
the correct classification is **guest shutdown requested, capture-forced stop**.

Raw additional evidence (original receipts unchanged):

- `~/macos-vm/run/c374-capture-d-refusal-docker-events.txt`
- `~/macos-vm/run/c374-capture-d-refusal-docker-journal.txt`
- `~/macos-vm/run/c374-capture-d-refusal-capture-journal.txt`
- `~/macos-vm/run/c374-capture-d-refusal-evidence.json`

[Artifact hashes and retained commands](console-capture-d-refusal-evidence-20261009.json)
also cover the original hook receipts/private events and the inspected QEMU source.

## Source audit and uncertainty

Pinned QEMU10.1.2 `system/runstate.c:qemu_cleanup` closes character devices,
then performs `user_creatable_cleanup`. `system/main.c:qemu_default_main` returns
from cleanup, unlocks and calls `exit(status)`. Transport closure can therefore
precede completed process teardown. That sequence does **not** identify where374
blocked. The retained D-state refusal has no flags, wait channel or task inventory.
A local kernel header defines PF_EXITING as0x4, but it was not observed here;
that flag alone would not establish descriptor/VFIO release or process completion.

## Diagnostic-only change

On the existing initial `original-pid-present` refusal, add best-effort numeric
stat flags, symbolic wchan, bounded task states/start ticks/flags and enumeration
count. No argv, command name, stack, raw paths or exception text is recorded.
The helper checks the leader start ticks before collecting additional context.
Proc observations can race; these are diagnostic samples, not an atomic snapshot.

Bounds:20ms checked between operations;4096 bytes per stat;128 bytes per wchan;
64 counted task-directory entries plus at most1 lookahead entry, at most8 task-stat attempts. Enumeration count can be
a lower bound; truncation/budget/error fields are explicit. Reads use nonblocking,
no-follow opens; the existing external docker-exec timeout remains the syscall
bound. No helper extends the transport+2s or admitted/outer deadline. Host receipts
retain only typed, length-limited fields and fixed error codes.

No diagnostic value participates in completion, shutdown-wait, recovery or
same-boot admission. D state remains an immediate refusal. Missing, inaccessible,
malformed, truncated or expired diagnostic reads cannot create eligibility.

## Validation and next discriminator

Focused private-libvirt suite:158 tests pass. Cases include valid fields, malformed
and oversized stat/wchan, inaccessible/missing files, symlink refusal, stale PID
identity, task-count/sample caps, budget exhaustion, host sanitization and unchanged
immediate stop despite PF_EXITING-like flags. Full host suite:1294 tests pass,8 skipped (53.366s), recorded in
`~/macos-vm/run/c377-host-tests.log`; no native diagnostic run yet.

Next: retain this context on another real refusal, correlate with source-supported
kernel/QEMU teardown, and review any proposed eligibility separately. Do not change
D-state acceptance merely to make shutdown classification green.
