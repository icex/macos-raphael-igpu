# Candidate354: persist shutdown observations before terminal cleanup

Source corroboration: libvirt11.9.0
[qemuProcessHandleShutdown](https://github.com/libvirt/libvirt/blob/v11.9.0/src/qemu/qemu_process.c#L611)
translates QEMU's guest-initiated boolean into lifecycle SHUTDOWN_GUEST,
SHUTDOWN_HOST or SHUTDOWN_FINISHED (unknown). Fake reboot/restart-policy paths
suppress the normal shutdown event. The event is queued after the process shutdown
handler runs. Installed libvirt-domain.h defines these details1/2/0 respectively;
STOPPED is a different, later lifecycle event. Consequently delivery before serial
EOF is plausible but not guaranteed. Only GUEST distinguishes observed guest
shutdown from a host action; requests, STOP_REQUESTED files and unknown details
cannot replace it.

Implemented diagnostic-only change: lifecycle callback immediately fsyncs a
libvirt-lifecycle-observed row with timestamps, namespace scope and previously
verified domain/run/PID/start identity when names/UUID/run match. Unbound events
remain explicitly unbound. Only exact SHUTDOWN+GUEST becomes guest_shutdown=true.
This is an observation, not exit proof, recovery permission or capture-loss grace.
A write lock prevents callback and main-loop event records interleaving. Write
failure is retained as event_error and event remains queued; normal health checks
stay fail-closed. Existing later libvirt-lifecycle records remain for compatibility.

Not-sole-task refusals now include at most eight task IDs/states/start ticks and
an explicit truncation flag. Unknown/disappearing task data remain unknown, never
completion. No command lines or names are exposed. Host output admits only typed,
allowlisted diagnostic fields. Original completion proof, immediate-stop branches,
absolute two-second EOF budget and recovery admission are unchanged.

Potential future shutdown-only grace is deliberately NOT implemented here. First
qualify callback persistence timing with an isolated software guest ACPI poweroff,
serial EOF and deliberately delayed remaining worker. Compare an unrelated
serial-disconnect/live-worker case: it must retain immediate stop. Capture raw
observed event, EOF, thread state, natural exit/terminal and absolute deadline.
Missing/delayed/wrong-domain/host/unknown shutdown observations cannot authorize
waiting; persistence failure must still stop. If callback delivery cannot reliably
precede EOF, investigate earlier QMP event receipt through the same private owner,
not a broader alive-process exception.

A later reviewed gate would bind any observation to current admission/plan,
permit/running CID/start, namespace and original PID/start, reject stale/replayed
observations, and only describe shutdown-in-progress. It would still require the
existing sole-thread/empty-FD completion proof before declaring exit, force stop
at the original absolute two-second/deadline budget, and never synthesize terminal
or recovery receipts. Observation timestamp freshness alone is insufficient.

Prepared tests cover exact guest vs host/unknown/stopped event, unknown/mismatched
identity, immediate durable recording and persistence failure, plus task-state
refusal diagnostics. Per parent instruction these tests have NOT been run while
candidate353 performance work is active. Only source review/diff check performed;
no builds, containers, guest or hardware operations.

Focused follow-up: five lifecycle observation, nine zombie proof and22 capture-exit
tests pass. The existing exact-diagnostic expectation was updated for the newly
reported task fields; refusal behavior is unchanged. Full suite and software
lifecycle timing qualification remain pending.
