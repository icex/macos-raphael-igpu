# Live status — 2026-10-12 — 459: 4K120 scanout via ODM, SDMA copy queue live, DCC next

Priority (user): performance, reliability, the iGPU's own display in QEMU's window,
resizable with HiDPI/low-DPI choices, Retina at 1080p 120 Hz; then the rest.
Milestones and audits: ~/macos-vm/run/milestones-igpu-qemu-display.md.

Usable today (455, `VM_CONSOLE=igpu`, guest helper): window-fit display with HiDPI (3840-wide
panel, 60 fps, 59.95 distinct frames/s) or exact 1x size at 120 Hz (119.7/s). Reliability:
three consecutive same-boot cycles with verified clean exits and authorizing recovery (455).

Retina at 120 Hz in progress: 457 forces ODM 2:1 for the virtual stream (pool trimmed to the
4 real pipes, DET3/COMPBUF for pipe 3, 1.2 GHz pixel-clock capability) and the 3840x2160
"looks like 1920x1080" panel scans out at 119.98 Hz; writeback can only capture one ODM
segment. 458 proved an SDMA0 RLC0 queue we own (fence in 26 us, GFX-hub AGP window); 459
copies latched scanout surfaces with it but every surface is DCC-compressed, so the copy
refuses. Next: DCC-aware detiling copy (or DCC off for displayable surfaces).

Open: HiDPI at arbitrary exact sizes (macOS ignores /Library/Displays overrides); pointer
corner proof (needs the user's mouse); fresh-boot DMCUB halt untested on a fresh boot; one
transient guest panic in OSKext::copyInfo at 457's first boot (not reproduced).

Safety: QEMU validates the guest control page from one snapshot (double-fetch fix,
security review); writeback and our SDMA queue quiesced before every MODE2 and listed in
QEMU's exit stop list. Host suite 1593 (8 skipped) passed. No main publication.

Evidence: findings/research/igpu-window-fit-120hz-20261012.md,
igpu-writeback-qemu-window-20261012.md; ~/macos-vm/run/c454-odm-4k120-notes.md,
c456-sdma-scanout-copy-notes.md; candidate-45{5..9}-results.
