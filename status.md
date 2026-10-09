# Live status — 2026-10-10 — QEMU desktop integration resumed

The user deferred VirtualBox and resumed work on the QEMU/virt-manager experience:
bidirectional text clipboard and GUI USB redirection. Candidate421 owns integration
and native tests;422/423 perform offline USB/clipboard work. No new GPU run yet.
[Plan](findings/research/qemu-desktop-integration-plan-20261010.md).

Published dev4fdd0f3 passed hosted test and macOS build jobs (run38000293238).
The previous candidate417 was forcibly stopped during boot at the pause request;
its controller unregistered successfully and no relay runtime result was qualified.
VirtualBox418 full build passes;420 remains source investigation only. All VBox
work is deferred, not completed or abandoned.

Last physical GPU run remains402 with authorizing recovery. At this resume check,
GPU7b:00.0 power/control=on, inhibitor container and host awake service are active,
and no test VM is running. Revalidate run-specific ownership and admission before
launch. Keep the sealed capture app and existing console qualification intact.
