# GPU-less delivery and guest-agent shutdown — 2026-09-08

Actual QEMU PID 1 had **no vfio-pci arguments**. The iGPU remained on host amdgpu.
OpenCore loaded 1.0.163 build `90fc73c8b2e74ad79ecc2db3eb85ad4c`; repeated critical
snapshots contained build record sequence 0 and reported dropped=0, truncated=0.
No AMD hardware route was invoked without the device. This proves candidate delivery
and basic logging, not hardware instrumentation or Metal execution.

The root LaunchDaemon compiled the unchanged Metal probe successfully. Guest 24G830,
boot UUID, uid 0, probe source hash and executable hash are in `shutdown/guest-identity.json`.
The preparation output is in `20260908T091828Z-0db70750`.

The guarded `/sbin/shutdown -h now` request was admitted through the root agent.
Within its 20-second grace interval, the guest emitted nested kernel page-fault traps
and did not exit. The supervisor force-stopped exact CID
`1a75c342331bed353e8779b05484418a91f8e90b38f44adaf12af4ee917e6053`.
See `shutdown/serial.txt` and `shutdown/shutdown.json`.

The first visible trap reports RIP/CR2 `0xffffff8005dee210`; subsequent nested traps
prevent a usable full backtrace. No causal attribution to the GPU or new logging is
justified. The device was not passed through. The host retained boot ID
`23aedc74-6a57-4321-94f0-ae91d0e79354`, and the iGPU stayed with amdgpu.

Guest-agent graceful poweroff therefore **fails qualification**. The GPU coordinator
keeps the previously tested bounded ACPI request and exact-CID fallback. Neither
forced stop nor container exit is evidence of GPU teardown; physical reuse is still
forbidden in this boot after the first GPU experiment. Diagnose this guest panic in
a separate GPU-less lifecycle experiment; do not add shutdown patches to hybrid-001.
