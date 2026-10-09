# Candidate355: bounded wait for an independently observed guest shutdown

This is a software-qualified proposal, not native qualification. Candidate354
observed a real SHUTDOWN_GUEST callback followed by an exact zombie QEMU leader
with a running vCPU worker, then process disappearance. A zombie leader alone
still does not prove that the worker released files or VFIO ownership.

The new path applies only after all existing admission, plan, resume permit,
running identity and PID namespace checks pass, and the original PID/start pair
is a zombie whose existing completion helper refuses specifically `not-sole-task`.
The complete other-process/unknown-visibility scan still runs. A durable callback
observation must match the same full identity and namespace, domain name/UUID,
libvirt event6/detail1, and predate the collector's actual EOF by at most2s.
Host/unknown events, ordinary live processes, missing/partial/oversized/malformed
observations and stale or nonfinite timing never authorize a wait.

`sercat.py` records monotonic/epoch time at `recv(b'')`. Only a clean EOF followed
by successful final log synchronization publishes the per-channel observation,
scoped to CID, StartedAt, run and admission digest. Publication uses a non-overwriting
hard link and directory fsync. Collector error/interruption leaves no usable
marker. Arm removes a prior marker for that exact CID/channel. The host rejects
missing, malformed, oversized, symlinked, future or expired observations. The
absolute two-second budget starts at recv EOF, so fsync and hook startup consume
it; the original run deadline also caps it. The independent deadline timer and
ordinary/direct capture-fatal stops remain immediate.

During an eligible wait, each bounded probe repeats full binding/visibility and
the original sole-task/empty-FD/stable-Z completion proof. No surviving worker
is classified as exited. Expiry or any lost predicate forces the exact CID stop.
A container that disappears between probes has a distinct
`container-stopped-during-shutdown-wait` observation after exact CID/StartedAt
verification; that label does not assert process proof or manufacture terminal
receipts. The controller remains the sole source of `terminal.json`.

## Software evidence

[Machine-readable results](libvirt-shutdown-wait-evidence-20261009.json) retain
all probe observations and scope. Source scripts are
[worker discriminator](libvirt-shutdown-worker-smoke-20261009.py) and
[collector/TCG integration](libvirt-clean-eof-smoke-20261009.py).

- `run/c355-worker-3873d38a`: real pthread group leader enters Z while a worker
  remains alive. A700ms worker reaches the unchanged completion proof and the
  adapter reports exit after0.710s. A3000ms worker hits the EOF-origin budget and
  is killed after2.001s, with no exited proof. Missing event kills after0.00145s.
  No case creates a terminal receipt. Admission/event/PID-namespace view and
  Docker operations are explicit synthetic adapters; no real VM/container
  lifetime or libvirt callback ordering is claimed by this discriminator.
- `run/c355-capture-exit-655ba9e8`: isolated pinned-image TCG/TAP guest, no KVM,
  physical GPU or host network. Actual entry/libvirt/permit/controller and actual
  collector recv/fsync/EOF-marker code run. The collector reuses an already
  connected fixture socket through a connect-only adapter. S5 has a real bound
  guest event before EOF, natural container exit in0.264s, exit0 and genuine
  `guest-shutdown`/`process_exited=true` terminal. Deliberately lost live capture
  has no guest event, stateS, immediate stop in0.131s and exit1. Both owned
  containers were inspected stopped. This run did not force a delayed QEMU
  worker; the real pthread case isolates that condition separately.

Focused tests cover invalid marker/event types and identities, stale/future/
nonfinite timing, interruption/fsync failure, full process visibility, changed
bindings while waiting, expiry, and disappearance between probes. The earlier
capture-exit, serial collector and supervision tests remain passing. Native
qualification must still demonstrate the staged collector, both channels,
actual systemd ExecStopPost wiring, genuine terminal and valid GPU recovery.

The2s event-age cap intentionally may reject a legitimate but late shutdown.
Partial callback JSON while the file is appended also conservatively refuses.
Neither case extends the budget or relaxes capture-fatal behavior.
