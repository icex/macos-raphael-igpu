# Live status — 2026-10-09

## Candidate354: clean shutdown with transient zombie/vCPU overlap observed

Run `0bb9177e80b4d9db4494927fd22d0796`, metal-197, build1.0.354,
MODE2#293, bootba51b3c6. Native Metal/WindowServer/display pass; normal HiDPI
desktop visible in actual virt-manager, viewer closure leaves VM alive. Same
approved O2 presenter, full refresh ON; no guest TCC changes or performance claim.

Capture CORE_PROBE_PASS, earliest_failure=null. Actual controller terminal:
guest-shutdown/process_exited=true. Both EOF hooks see QEMU already reaped and
allow natural exit (~0.445s). GPU recovery recovered/authorizes_launch=true.
VM/cycle stopped; host sleep:idle inhibitor retained. No reboot/rebind needed.

New diagnostic records bound SHUTDOWN_GUEST; independent task sampling catches
leader113Z plus CPU0/KVM thread120R before disappearance~0.120s after event.
This demonstrates transient shutdown overlap, not safety of arbitrary workers.
Exact native EOF timestamp is absent; no event-to-EOF timing claim.352/353's
terminal-receipt race remains open. Next355 tests a conservative guest-event-bound
wait in software first, preserving actual completion proof and absolute2s/deadline.

1196 host tests pass,8skip. Checked-in kext remains353 with matching manifest;
354 build is separately pinned/staged.352/353 measured HiDPI copy/delivery milestone
is being integrated into dev with hosted CI; main unchanged. General desktop,
window resize/input, console audio/install durability and VirtualBox remain open.
[Evidence](findings/research/libvirt-shutdown-native-20261009.md) ·
[Receipts/tasks](findings/research/libvirt-shutdown-native-evidence-20261009.json) ·
[Previous status](findings/research/status-archives/status-before-354-20261009.md).
