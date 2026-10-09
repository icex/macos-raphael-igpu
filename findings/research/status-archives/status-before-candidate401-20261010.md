# Live status —2026-10-10

## Candidate400: actual VirtualBox reaches userspace, then timekeeping panic

Software-only bootB, UUID71c17267-a87c-4d72-9aaf-8db06c21ce98,
run/c400-vbox-boot-b. Independent disks, no physical GPU/VFIO.
OpenCore's supported DeviceProperties override replaces the asserting VBox EFI
placeholder. Picker identifies REL-105-2025-07-07; official1.0.5 source pinned.
Guest progresses through APFS/XNU into userspace, then CPU6 panics~66.843s:
Non-monotonic time: invoke0xf8faf2a44,runnable0xf8faf8032,sched_prim.c3242.
Current task diskarbitrationd is not evidence of a disk-specific cause.
No macOS desktop or VirtualBox acceleration has been established.

Root stopped the exact owned VM; result verifies poweredoff/unregistered,
guest_boot_qualified=false. This is deliberate cleanup after panic, not natural
shutdown or GPU recovery. AttemptA, bootB, baseline disks and original receipts
remain separate/preserved. Source/report/hash manifest:
findings/research/virtualbox-device-properties-override-20261010.md.

Latest hardware run397 ended with private guest-shutdown/process-exited,
natural capture exits and authorizing recovery; its timing report remains
findings/research/console-snapshot-timing-native-20261009.md.4K token delivery
~51localized/~27full-field; no optimization gain or60Hz claim. Root owns any
subsequent399 timing cycle; this software report does not describe its live state.
Last delivered dev remains c1f64d0 (tested395; hosted CI green), main unchanged.

Next: source-audit actual VBox TSC/CPU configuration and XNU assertion; prepare
bounded one-vCPU discriminator rather than guessing a timer override. Continue
true VirtualBox boot/presentation work separately from the QEMU accelerated path.
