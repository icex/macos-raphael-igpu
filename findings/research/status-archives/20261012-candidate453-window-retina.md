# Live status — 2026-10-12 — 453 iGPU display in QEMU's own window

Priority (user, 2026-10-11/12): performance, reliability, the iGPU's own display in QEMU's
window, resizable with the window, Retina at 1080p 120 Hz (4K at 120 native); then the rest.
Milestone list and audits: ~/macos-vm/run/milestones-igpu-qemu-display.md.

Candidate 453 / metal-247 (current, run 343e8eee544c008fc4fb31172548b256, QEMU image
076e6f38…, `VM_CONSOLE=igpu`, pins-igpu-display-v3.json): macOS renders with Metal on the
iGPU and DCN writeback puts every composited frame into QEMU's GTK/GL window through a
hidden guest-physical region (no emulated adapter, no mirror, no HDMI plug). Measured
60.0 distinct buffers/s at 3840x2160 and 3840x2400, 60.0 content changes/s in full-field
motion. The virtual panel follows the window shape at 3840 px wide with Retina defaults
("looks like 1920x1080" for 16:9, 1920x1200 for 16:10). 449–452 CORE_PROBE_PASS.

Blocking / next: 120 Hz (4K needs ODM 2:1 because one pipe's DP DTO tops at 600 MHz);
fresh-boot support (works only with DMCUB empty, i.e. after a host suspend/resume; on a
fresh boot the accelerator does not start); corner-exact pointer proof; shutdowns are
`exit-unverified-after-request` (recovery always authorizes).

Safety: host froze 2026-10-11 21:18 launching 450 after a SIGKILLed 449 left writeback
armed. Every MODE2 now quiesces writeback first (fails closed); the guest stops it on
power-off. No faults since. Host awake: user-held `systemd-inhibit --who=rgpu-dev`
(logind refuses inhibitors from a remote shell). GPU on vfio-pci, power/control=on.
Host suite 1564 (8 skipped) passed. No main publication.

Evidence: findings/research/igpu-writeback-qemu-window-20261012.md and evidence JSON;
~/macos-vm/run/candidate-449-attempt-r2-*, candidate-450-*, candidate-451-*, candidate-452-*,
candidate-453-*, c449/c450/c451/c452/c453 measurement JSONs, c450-shots/.
