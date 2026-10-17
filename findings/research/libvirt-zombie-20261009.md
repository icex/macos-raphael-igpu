# Candidate347: prove an unreaped QEMU has completed

Native345 completed the functional/capture probe and GPU recovery but lost the
controller terminal receipt. Both EOF hooks report original QEMU PID113 in stateZ
and immediate-stop. The receipt is absent; no clean controller-exit claim is made.
[Native evidence](native-refresh-20261009.md).

## Source and proof boundary

Linux reference commit238650ef6c7c7cca08e032527329424c9fbd70e5 (7.3-rc3)
`kernel/exit.c` calls exit_mm/exit_files before exit_notify sets EXIT_ZOMBIE.
However, a zombie group leader may still have live worker threads: exit_notify
separately tests thread_group_empty before notification/reaping. StateZ alone is
not sufficient to prove shared descriptors or VFIO ownership are gone.
The host actually runs7.2.5-cachyos; the real pthread check below verifies this
behavior on the running host rather than claiming the reference is its exact build.

The new bounded proof accepts only the original exact PID/start time, stateZ,
a task directory containing only that leader, an empty descriptor directory,
and a matching state/start re-read. It repeats that check when skipping the
original process in the existing scan and before returning the proof. Unknown
visibility, extra workers/descriptors, malformed state, PID reuse, or another
QEMU still refuse. Reaping during inspection counts only when stat of the PID
directory returns ENOENT; permission failures are not absence. The original
container/run/namespace/permit bindings and all other process checks remain.

No signal or reaping operation is added. The host's existing maximum2-second
natural-exit window and original exposure deadline remain unchanged. A proven
completed zombie can let libvirt finish its actual terminal receipt; no receipt
is synthesized. The host records whether this exact zombie proof was used.

## Software observations

- A real pthread process calls pthread_exit in its group leader while a worker
  remains alive. The leader is stateZ and the new proof refuses. After the worker
  is terminated and only the descriptor-free zombie remains, the proof passes.
- An isolated container runs the exact experimental QEMU10.1.2 image with machine
  none, zero CPUs, KVM disabled, no devices and networknone. A live QEMU refuses.
  QMP quit leaves PID7 unreaped by the test parent, stateZ, taskset{7}, descriptors
  empty. The proof passes; wait then returns exit0 and the container exits normally.
- The existing real TCG guest/entry/serial-EOF pair still completes S5 with a real
  guest-shutdown terminal receipt and natural container exit. Its live-QEMU
  capture-loss negative control still immediately stops the exact container.
  The S5 pair happened after normal reaping, so it is not evidence of taking the
  new zombie branch in the full native controller.

Focused process/capture suite:27 tests pass. Native347 remains the required next
observation. [Artifact hashes](libvirt-zombie-evidence-20261009.json).
