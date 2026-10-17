# Candidate355: critical peer reset bypasses clean-EOF eligibility

Run `a2e32b7d73a2dc3062421e39b457025c`, metal-198, build1.0.355
`602598df6baf4a098ff51331b0fa62cb`, MODE2#294, bootba51b3c6.
1214 host tests pass/eight skips; full expanded identity and dry-run pass.
All12 harness helpers are backed up/staged, including the updated collector.
Native Metal/WindowServer/display pass. Actual virt-manager shows the normal
HiDPI desktop, awake assertions pass, closing the viewer leaves the VM alive.
The future356 viewport fixture compiles in this guest (sourcead00f4a9,
executable11047a8e), but is not executed and has no viewport qualification yet.

## First abnormal observation and teardown

Producer quiesce ACK at epoch1791549038.6534443 binds snapshot10/count365 and
1653696 bytes/hash e422aad9. Final critical capture exactly matches that receipt.
Bound guest SHUTDOWN_GUEST arrives at1791549050.0291774, approximately11.376s
later. Console recv EOF follows at1791549050.0306334,1.454ms after the event;
its clean marker is published after final synchronization.

The critical collector instead reports `ConnectionResetError errno=104` in its
journal and exits1. It correctly publishes no *clean* EOF marker. Its stop hook
therefore immediately stops the exact container (elapsed~0.312s) at clean-eof
inspection. The other hook sees a Docker exec127 failure during this stop.
The terminal receipt is absent. Outer exited-after-guest-request does not prove
clean shutdown; this is a forced container stop. The new event-bound wait is
not exercised, and the failure is not evidence of a graphics/rendering regression.

A50ms read-only task observer catches the leader113Z and another QEMU thread115
first D in synchronize_rcu, then R. Process disappearance occurs after intervention
may have begun, so it cannot be called natural completion. The critical reset
itself has no retained monotonic timestamp; journal second precision is insufficient
to establish its exact ordering against SHUTDOWN_GUEST or console EOF.

Capture CORE_PROBE_PASS/earliest_failure=null, including unchanged critical
bytes after quiesce. GPU recovery recovered/authorizes_launch=true. VM/cycle
stopped; host remains awake. These do not supply the missing controller terminal.

## Next discriminator

The new mandatory clean marker precedes even the old already-exited proof, so an
error-end now loses an acceptance path that previously required positive process
completion. Preserve error semantics and the full completion proof; never relabel
RST as clean EOF. Investigate whether unread reverse quiesce tokens cause normal
socket reset on QEMU exit: ACK took3.05s while the collector retransmits each1s,
and guest polling stops draining after latching the request. This is a hypothesis,
not evidence that unread bytes existed in355. Reproduce a controlled unread-input
close and compare unrelated live capture loss before choosing a correction.

[Exact receipts, journal hashes and task observations](libvirt-clean-eof-native-evidence-20261009.json) ·
[Software-qualified wait and its limits](libvirt-shutdown-wait-20261009.md).
