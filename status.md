# Linux VCN baseline — 2026-09-15

User rebooted and explicitly requested native Linux testing and comparison.
Boot c782d007-ca85-409b-9cf5-ff12c1a8c6d5, kernel7.2.5-1-cachyos-bore,
Raphael1002:13c0 at0000:7b:00.0, amdgpu, renderD129, power/control=on.
Boot journal includes a suspend/resume before this experiment; preserve it.

## Run allowance
One bounded native Linux baseline session on boot
c782d007-ca85-409b-9cf5-ff12c1a8c6d5: software controls and H264/HEVC hardware
encode/decode with a repeat of each hardware workload. cycle.py linux-vcn;
max6000seconds, per-command90seconds, systemd-owned process group, inhibitor,
identity checks, capture-fatal and manual-stop paths. No VFIO, reset, rebind,
module reload or reboot. An isolated tracing instance captures Raphael register
access and queue events through a temporary privileged container. No GPU ledger
entry: this is native Linux, with no QEMU/VFIO exposure. Record native results
separately. Earlier macOS evidence remains in candidate262 and root status.
