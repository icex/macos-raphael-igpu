# Linux baseline — boot2f77

Captured 2026-09-13 at 13:52:49–13:54:00 UTC (16:52:49–16:54:00 local) while `0000:7b:00.0` was bound to `amdgpu`. Raw values are in [linux-baseline-boot2f77.raw.txt](linux-baseline-boot2f77.raw.txt). A final noninvasive check at 13:54:27Z found `vfio-pci`, indicating concurrent binding proceeded after the device-specific reads.

| Area | Observation | Interpretation |
|---|---|---|
| Driver identity | `1002:13c0`, class `030000`, driver `amdgpu` | Live Linux host binding at capture and recheck |
| VRAM counters | `mem_info_vram_total=536870912`; `mem_info_vis_vram_total=536870912` | 512 MiB total and visible counters |
| PCI BAR0 | `0xfc20000000–0xfc2fffffff` | 256 MiB PCI resource window |
| Kernel memory report | `VRAM=512M`, `Detected VRAM RAM=512M, BAR=512M`, GART 1024M, GTT 15474M | Driver's reported VRAM/BAR accounting is separate from the current sysfs PCI BAR resource span |
| IP / firmware | Ten IP blocks initialized; VBIOS fetched from VFCT; DMUB/VCN firmware loaded; SMU initialized | Relevant firmware and IP discovery data accessible in journal |
| Display | HDMI-A-3 connected with 256-byte readable EDID; DP-3/4/5 disconnected | EDID is available and hash-preserved in raw capture |
| Watchdog / pstore | NMI watchdog enabled; EFI pstore backend registered; no pstore files | No persisted crash artifact observed in this boot |

The 512 MiB Linux VRAM and visible counters must not be treated as the PCI BAR length: the current BAR0 resource is 256 MiB. This is a Linux-visible counter versus PCI-resource distinction and does not establish a wrong-driver or wrong-capacity conclusion.

The journal contains a preexisting display timeout at 16:45:21 local: `optc31_disable_crtc line:146`. It occurred about seven minutes before this baseline and is retained as a host issue/blocking observation. No host Oops, BUG, lockup, or MCE hardware-error match was found in the concise checks, which is not a safety qualification.

No sudo, MMIO or `/dev/vfio` open, write, reset, bind, or unbind was performed. Device-specific reads stopped when the final check detected the driver transition to `vfio-pci`.
