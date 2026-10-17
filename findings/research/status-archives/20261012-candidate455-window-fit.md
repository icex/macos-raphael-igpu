# Live status — 2026-10-12 — 455 window-fit HiDPI/1x, 120 Hz where one pipe fits

Priority (user): performance, reliability, the iGPU's own display in QEMU's window,
resizable with HiDPI and low-DPI choices, Retina at 1080p 120 Hz (4K at 120 native); then
the rest. Milestones and audits: ~/macos-vm/run/milestones-igpu-qemu-display.md.

Candidate 455 / metal-249 (current, QEMU image 076e6f38…, `VM_CONSOLE=igpu`, guest helper
installed): one display per window size with a 3840-wide HiDPI panel (default) and the
window's exact pixel size at 1x; 120 Hz in the exact mode when it fits one pipe. Measured:
60 fps Retina full-field (59.95/s over 65 s, 453) and 120 fps exact-fit full-field
(119.71/s over 65 s, 455). QEMU's display thread ~2% of a host core.

Blocking / next: Retina at 120 Hz needs a scanout-copy transport (writeback captures only
half a frame under ODM 2:1); HiDPI at arbitrary exact sizes needs a CoreDisplay patch
(macOS ignores /Library/Displays overrides); fresh-boot DMCUB halt implemented but not yet
run on a fresh boot; pointer corner proof pending (needs the user's mouse); three
consecutive verified shutdowns (454 verified, first of the series).

Safety: writeback quiesced before every MODE2; guest stops it on power-off. Host awake via
the user's systemd-inhibit. GPU on vfio-pci, power/control=on. Host suite 1591 (8 skipped)
passed. No main publication.

Evidence: findings/research/igpu-window-fit-120hz-20261012.md,
igpu-writeback-qemu-window-20261012.md and evidence JSON; docs/igpu-display-helper.md.
