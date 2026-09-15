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

## First native result and supplemental allowance
The first Linux run completed software controls, H264/HEVC hardware encoding,
hardware decoding and repeated hardware workloads. All validated three frames;
maximum luma error1 H264 and0 HEVC. Firmware bytes exactly match our macOS
payload and SMU version625300 matches. Capture reports zero dropped/overrun
events; cleanup stopped workloads and left amdgpu attached.
Results: /home/bogdan/macos-vm/run/linux-vcn-c782d007.

One supplemental native session on boot c782d007-ca85-409b-9cf5-ff12c1a8c6d5
captures the SRAM image at amdgpu_vcn_psp_update_sram using read-only kprobe
fetches. Exact running-kernel BTF gives adev.vcn offset201152, inst0 offset8,
SRAM CPU pointer offset3400 within inst: absolute204560; current pointer204576.
Function BTF prototype is (adev, inst_idx, ucode_id), NOT the newer vinst ABI.
Filter physical device13c0 and inst0; capture96words from512byte allocation.
Same bounded harness/cleanup and codecs; no reset/rebind/reboot.
