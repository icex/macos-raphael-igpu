# Live status — 2026-10-11 — 448 plug-free iGPU virtual display

New user priority (2026-10-11): no mirror and no second display. The Raphael iGPU drives its
own display and QEMU shows that output directly ("iGPU → QEMU display"), eventually with no
HDMI plug. The bochs/virtual-display console path (444, ~50 full-field IDs/s) remains
available but is no longer the target. Host sleep:idle blocker `rgpu-work-awake` was
retained during work. No VM running.

Candidate 448 / metal-242 (current): plug-free virtual display on the iGPU. Opt-in
`rgpuvirtualsink=1` (with `rgpudcn` + `rgpudcncold`): `dc_link_detect` reports one AMD DC
virtual-signal sink with our own EDID ("Raphael VD") and every other connector disconnected;
the virtual stream's pixel clock goes through the DP DTO with Raphael's 600 MHz reference;
DCHUBBUB global timer enabled and COMPBUF sized as Linux dcn31 does. Build
ed310d421ce2459fbd2551154e52e506, MODE2 350, run aba7858fb23a2940be18621b2c9abb46.

Results: CORE_PROBE_PASS with Metal; macOS shows exactly one display, "Raphael VD"
(3840x2160 backing / 1920x1080 HiDPI, 60 Hz, no mirror); OTG measured 59.99 Hz; flips latch;
WindowServer 0.6% CPU. 446 (HDMI without firmware: 121 Hz, no fetch) and 447 (virtual sink
without the timer/reference fixes: 49.4 Hz, no fetch) were the steps to it.

Blocking issue / next: QEMU does not show the display yet. Scanout is tiled 10-bit outside
BAR0 (BAR0 reads ~22 MB/s), so next is a per-flip GPU copy into guest-visible RAM consumed
by a QEMU console owned by the vfio device (no guest display device), plus display-awake
handling and input mapping.

Lifecycle: 445 recovered via mode2-noqueue-recover (no reboot); 446/447 forced stops and
448 guest-request shutdown all recovered with authorizes_launch=true. GPU on vfio-pci,
power/control=on, no host kernel faults. Host suite 1559 (8 skipped) passed. No main
publication.

Evidence: findings/research/igpu-virtual-sink-20261011.md, igpu-virtual-sink-plan-20261011.md,
findings/research/igpu-native-display-survey-20261011.md,
findings/research/igpu-display-cold-firmware-20261011.md and evidence JSON;
~/macos-vm/run/candidate-445-*, candidate-446-*, c445-*, c446-*.
