# Candidate394: private staging isolation and installed restart evidence

**Partial native qualification; explicit retired-unmap/capacity recovery fails.**
Run`af7889e45df129e345d9c7f6b03525cd`, container
`3f191ce6f3c05412de6592caf168cbbba72a16bc69f6df7b61cbfc677e6f61e5`.
The accompanying manifest pins build/run identity and stable evidence. Root owns
all native operations. Final teardown is a forced capture abort; stopped-GPU recovery authorizes reuse.

## Isolation succeeds; cleanup fixture fails

The native probe retires A while retaining its connection and private mapping,
then arms B. Old A COMMIT and re-ARM are refused; a WC mapping alias is refused.
B commits a known801×601 whole-frame pattern with exact ACK1. Independent QEMU
screenshots before and after A overwrites its retired buffer each match all
481401 pixels, zero mismatches, identical pixel hashes. No new B commit occurs
between those screenshots. This qualifies that host framebuffer isolation case,
not every manager frame or malicious concurrent current-owner mutation.

Four retained mapped private buffers exhaust the bounded slot pool as expected.
However, the probe then fails at`release-A-capacity`, reports`cleanup_ok:false`,
and exits1. Capacity recovery is **not** qualified by this run. Exact original
negative returns and the failing result remain in`c394-native-final.txt`.

Apple's `IOUserClient.cpp::is_io_connect_unmap_memory_from_task` calls
`clientMemoryForType` again before a reference-only mapping lookup.394 returns
NotReady for retired owners, so explicit unmap cannot find A's descriptor.
This source-supported defect motivates395's separate per-client retained private
buffer reference through RETIRE, released at final close; publication remains
restricted to the active owner. The394 probe did not print individual cleanup
returns, so do not claim its original output directly recorded that exact unmap
error. Process-exit cleanup is distinct from the failed explicit-unmap assertion.

## Installed sealed presenter and resize

The external support payload installs with the capture app unchanged. Actual
launcher logs select snapshot1/default cache; presenter output contains successful
ACKs after initial startup and two owned helper-session restarts in the same VM.
These are real installed application restarts, not only host protocol simulation.
No app re-signing or TCC alteration is part of this external support update.

Actual manager resizes1235×743,1237×745 and1441×961 settle correctly. Root views
`c394-snapshot-desktop.png` as a normal desktop. Stereo sample capture passes
48kHz with997/1498Hz channels and independent restoration passes. This is sample
delivery, not endpoint audibility or A/V-sync qualification. No new input pass is
inferred merely from resize.

Static desktop presenter timing is approximately9–10ms snapshot COMMIT and
14–15ms total worker at4K;1441-wide output is approximately1.6–1.7ms COMMIT and
2.3–2.5ms worker. These combine kernel/host work within the measured call, not
isolated memcpy cost. Low source cadence on a static desktop is expected and does
not establish sustained60fps, full-frame dynamic integrity or scanout rate.

## Remaining boundary

Retained-map cleanup/capacity recovery must pass with395 before claiming complete
restart-safe ownership. Client death during commit, repeated resource exhaustion,
longer mixed-content performance and independent host-boot coverage remain open.
The immutable path remains experimental; GPU-native virtual transport and
VirtualBox support are not implemented. Functional evidence does not establish
clean shutdown; final receipts below record a capture abort.


## Final lifecycle: capture abort, separately successful recovery

`shutdown.json` now classifies`capture-abort-after-request`, retaining the earlier
outer observation`exited-after-guest-request` only as`observed_outcome`.
`exit_reconciliation.private_terminal_verified=false`; the private terminal is
missing. Both capture receipts report`immediate-stop`, no deferral, about0.515s.
Original QEMU PID113 remains stateR with one task and flags138412428 at inspection;
this is not an exited-process proof. Docker records SIGTERM and SIGKILL, stop,
exit137 and destroy. Thus there is no clean guest-shutdown qualification.

The stopped-GPU recovery receipt independently reports`recovered` and
`authorizes_launch=true`. The host safety gate remains intact; successful recovery
does not erase forced teardown or the native fixture's explicit-unmap failure.
