# Candidate356: preserve transport errors and completed-process cleanup

Candidate355 captured a valid critical quiesce ACK 11.376s before the bound
libvirt SHUTDOWN_GUEST event. Console recv EOF followed that event by 1.454ms.
The critical collector instead exited1 with `ConnectionResetError errno=104`;
it correctly published no clean-EOF marker. Its hook required that marker even
before the independently valid completed-process proof, immediately stopped the
container and lost the controller terminal. The exact critical reset timestamp
was not retained, so it cannot be retrospectively ordered against the event.

Unread reverse control input is a supported hypothesis. The collector repeats
RGPUQ2 each second while the request exists; CriticalUart stops draining after
recognizing it. QEMU10.1.2 `hw/char/serial.c:555` stops accepting input when the
RX FIFO fills; `chardev/char-socket.c:143` propagates that capacity to socket
reads. Linux stream peer release reports ECONNRESET when the closing socket has
unread receive data ([upstream af_unix.c](https://raw.githubusercontent.com/torvalds/linux/master/net/unix/af_unix.c),
`unix_release_sock`). This does not prove355's exact unread bytes. The software
case below reproduces that mechanism independently.

## Narrow behavior change

Missing or invalid collector observations no longer suppress the existing full
identity/namespace/process-visibility/completion proof. If that independent proof
shows the exact process has completed, the original receipt-flush allowance is
restored. Without a valid actual transport observation, its at-most2s budget
starts at hook entry, explicitly recorded as `legacy-hook-completion-only` and
still capped by the run deadline. It never authorizes surviving workers.

For the pending exact Z leader with workers, the independent observed guest
shutdown and all355 admission/plan/permit/PID namespace/process scans remain
mandatory. Only actual recv EOF or a distinct recv-reset104 observation can supply
the temporal boundary. Reset metadata has `kind=recv-reset`, `operation=recv`,
`errno=104`, separate reset timestamps and a separate file; it contains no EOF
timestamp. The collector publishes it only after successful final log sync and
still exits1 with its original error. No reset is relabeled clean EOF. Send
errors, other recv errors, write/fsync failures and signals cannot produce this
observation. Dual records, dangling symlinks, bad types/identities and nonfinite,
future or stale times cannot authorize pending workers.

A matching guest event must precede the actual reset, and both inspection and
worker completion consume the original recv-origin2s budget. Completion remains
the unchanged sole-task/empty-FD/stable-Z or actual disappearance proof; pending
workers are never labeled exited. Deadline, live capture-loss, unknown process
visibility and host-fault behavior remain fail-closed. No shutdown request or
quiesce request is treated as an independently observed guest event.

## Evidence and limits

[Results](libvirt-recv-reset-evidence-20261009.json) retain both bounded software
runs. [TCG script](libvirt-recv-reset-smoke-20261009.py) and
[worker script](libvirt-reset-worker-smoke-20261009.py) are reproducible.

- `run/c356-reset-c48a60d7`: actual isolated TCG S5 plus unread reverse UART
  bytes produces collector recv-reset104/exit1, no EOF marker, and a genuine
  controller guest-shutdown/process-exited terminal with natural container exit0
  in0.291s. The negative retains live TCG while an independent AF_UNIX socketpair
  with unread reverse bytes generates real RST; capture loss immediately stops
  the exact container in0.137s, exit1, no terminal. Both containers were inspected
  stopped. No KVM, physical GPU or host network; isolated TAP only. The collector
  uses a connect-only adapter for an already-connected socket. Actual systemd
  ExecStopPost/native integration remains unqualified by this software case.
- `run/c356-reset-worker-55d52841`: a real pthread leader-Z/worker transition
  with synthetic reset/event/context/namespace-view and Docker adapters. A700ms
  worker reaches unchanged completion in0.709s; a3000ms worker is forced after
  2.001s with no exited proof; missing event stops in0.00146s. No terminal is
  synthesized. This isolates the state machine, not real libvirt callback or
  container ordering.
- Focused tests reproduce kernel AF_UNIX reset directly, reject send-reset and
  generic receive failure, verify sync failure creates no marker, reject dual
  records/symlinks and preserve the independent completed-process path even
  with missing/malformed observations.

The live356 experiment must independently establish transport classification,
controller terminal, both capture hooks and authorizing GPU recovery. A valid
transport-end observation cannot establish capture completeness or override a
failed capture verdict.

Earlier raw runs `c356-reset-f5ccd9fa` and `c356-reset-worker-0b62f333` remain
unchanged. Their reset timing fields inherited EOF names from the earlier
fixture; the qualified repeats above use generic `transport_end_*` evidence
names and never label a reset as EOF.
