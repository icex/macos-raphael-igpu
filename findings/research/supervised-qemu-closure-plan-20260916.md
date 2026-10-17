# Supervised QEMU closure qualification

The user authorized continued roadmap work. M7 includes QEMU closure and crash
recovery. Candidate 280's four clean guest shutdowns do not qualify either path.

The new `vm-supervision.py intentional-close` action requires a card declaring
`lifecycle_test: supervised-qemu-quit`, a passed core probe, matching run IDs in
manifest/probe/interactive-ready, exact manifest hash and canonical supervision
state in the same results directory. Existing supervisor verification and
StartedAt checks run before and after durable single-use request publication.
The namespace-local monitor peer must be QEMU. Only literal HMP `quit` is sent.
The original deadline stays armed; there is no fallback stop/kill in this action.
A separate durable receipt records action/stop confirmation, never recovery.

The experiment coordinator is unchanged. It will detect closure, retain its
ordinary INVALID verdict, observe an already-stopped guest and attempt normal
strict recovery. Evaluate functional probe, capture, action, cleanup and overall
verdict independently. An expected INVALID is not relabeled CORE_PROBE_PASS.
A closure receipt alone cannot authorize GPU reuse.

Tests cover success, changed StartedAt, wrong results state path, absent deadline,
write-ahead replay, manifest mismatch and action deadline expiry without an HMP
send or fallback stop. Full host suite: 946 tests OK, three skipped. These mocks
validate control flow, not firmware/hardware recovery.

The first hardware attempt uses metal-128 / candidate 280 / attempt closure on
the explicitly named twentieth-exposure allowance in status.md. A fresh successful
MODE2 reset, exact identity and all existing capture/host-fault/recovery guards
remain mandatory. No host reboot, sudo, driver binding change or guest security
change is part of this experiment.
