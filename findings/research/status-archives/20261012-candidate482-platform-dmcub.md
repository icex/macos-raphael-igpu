# Live status — 2026-10-12 — 482: host crash on 481's fresh-boot path; held platform DMCUB withdrawn

Priority (user): performance, reliability, the iGPU's own display in QEMU's window,
resizable with HiDPI/low-DPI choices, Retina at 1080p 120 Hz; then the rest.
Milestones and audits: ~/macos-vm/run/milestones-igpu-qemu-display.md.

Usable now (464, `VM_CONSOLE=igpu`, pins-igpu-display-v6, guest helper): the 3840x2160
"looks like 1920x1080" Retina panel scans out at 119.98 Hz (ODM 2:1) and an SDMA queue we
own copies every new frame (2.33 ms) into QEMU's window: 120.0 frames/s presented over
65 s of full-field Metal. At 60 Hz 59.0/s. Scanout surfaces are allocated without DCC
(Apple's GPUDCCDisplayable bit patched off); the hardware cursor is copied separately and
drawn by QEMU as a GL overlay (user confirmed).

Since 469-474 (`rgpuodm=2`, pins v10): Displays lists standard Retina steps for six aspect
classes (1920x1080, 2560x1440, 1920x1200, 2560x1600, 2560x1080, 3840x1080, 1920x1280,
2160x1440, 1920x1440, 2048x1536), all at 120 Hz (ODM 2:1/4:1 up to 5120x3200). The user
picks the resolution in Displays (macOS remembers it); the QEMU window scales the picture,
centred with black bars when its shape differs (477). Firmware, OpenCore and the Apple
boot logo show in the same window through a ramfb until the driver takes over (478). Window-following steps
(`rgpufollow=1`) and aspect snapping (`RGPU_SNAP_ASPECT=1`) are opt-in. 5K full-field Metal reaches ~42
frames/s (rendering-bound); 4K-class steps reach 120.

Desktop release 482 (docs/desktop-launcher.md): shortcut, passwordless iGPU bind, no session
limit, self-held sleep block. HOST CRASH (boot 4dc21315, 20:39): 481 launched over the
platform's PSP-loaded DMCUB held in reset; the guest finished dc_hardware_init and the host
froze at accelerator power-up (PSP TMR replacement), no kernel message. That path is withdrawn:
mode2 now refuses every DMCUB state except empty. With amdgpu.virtual_display the UEFI boot
display (iGPU HDMI dummy plug) still loads DMCUB, so fresh boots need the iGPU without a boot
display; next test: dummy plug removed, then reboot.

Earlier: 478, force-stopped after the guest stopped answering; its recovery is an
immutable `incomplete` receipt (SDMA copy queue left enabled), so the next launch needs a
host reboot and `gpu-bind.sh`. 479 (clipboard via qemu-vdagent, USB via owner-only
usbredir sockets + tools/rgpu-usb.sh, fullscreen aspect, exit stop list for the SDMA queue)
is built and staged but not yet run. Audio works (user). 469-477 r2 ended with verified exits and authorizing
recovery. Early-boot macOS kernel panics at 457, 468 and 477 (different signatures, ~1 in 10
boots; retries boot cleanly): open reliability item. Host LLVM upgraded to 23.1.1 mid-session; 473+ built with it.

Open: pointer corner proof and keyboard check (needs the user); Retina below 3840 wide
(small windows show the larger 'panel = 3840' UI); fresh-boot DMCUB halt untested on a
fresh boot; one transient OSKext::copyInfo guest panic at 457's first boot.

Safety: QEMU validates the guest control page from one snapshot and bounds BAR offsets in
64 bits; writeback and our SDMA queue are quiesced before every MODE2 and listed in QEMU's
exit stop list. Host suite 1593 (8 skipped) passed. No main publication.

Evidence: findings/research/igpu-sdma-4k120-qemu-window-20261012.md,
igpu-window-fit-120hz-20261012.md; ~/macos-vm/run/c460-dcc-scanout-copy-notes.md.

Housekeeping 2026-10-12: old candidate builds/dists (<449 entirely; 449-478 extracted
builds and dists only, results kept), per-launch OpenCore/config backups (newest 3 kept),
the c398 VirtualBox clones, the guest disk backup, old project docker images and
containers, and 259 old worktrees were removed (log: ~/macos-vm/run/cleanup-20261012.log;
uncommitted worktree changes saved in ~/macos-vm/run/worktree-leftovers/ and pushed as
preserve/* branches).
