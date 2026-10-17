# Live status — 2026-10-09

## Candidate347: paired console measurements and native clean shutdown

Run `fe659d623c40c9650ca999f83ae39635`, metal-191, build1.0.347,
MODE2#286 on bootba51b3c6. Native Metal/WindowServer/display ownership pass;
actual virt-manager renders native1080p and1080HiDPI with awake assertions.
Fresh full/ROI samples:30.497/30.323updates/s native,19.664/25.198HiDPI.
Median observer cost2.228/1.363ms native,5.222/1.452ms HiDPI. All fixtures finish;
normal desktop screenshot verified. Partial-token samples remain; no GPU-fps or
atomic-presentation claim.345's50updates/s native result is not reproduced.

Capture: CORE_PROBE_PASS, earliest_failure=null. Outer shutdown:
exited-after-guest-request. Actual native terminal.json: guest-shutdown,
process_exited=true. Both EOF handlers: natural-container-exit; completed zombie
branch=false (already reaped), so native race-specific coverage remains open.
GPU recovery: recovered, authorizes_launch=true. VM/cycle stopped, host sleep:idle
inhibitor active. No reboot/rebind needed.

Next: split presenter's approximately20ms HiDPI lock/copy interval to identify
its actual bottleneck; repeat bounded lifecycle coverage. Automatic resize,
atomic presentation, broader desktop/boot/crash coverage and VirtualBox remain open.
1176 host tests pass,8 skipped;5 optional ROI guard tests separately pass.
Kext/manifest match347; default image stock, explicit pins-spice60 selects the
experimental refresh image.347 milestone integrated into dev; hosted CI pending for this delivery.
343's earlier hosted test/build run passed.
[Evidence](findings/research/console-roi-native-20261009.md) ·
[Hashes](findings/research/console-roi-native-evidence-20261009.json) ·
[Previous status](findings/research/status-archives/status-before-347-20261009.md).
