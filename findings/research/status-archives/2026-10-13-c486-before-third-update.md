# Live status — 2026-10-13 — dynamic macOS 15.8.1 compatibility milestone verified

Candidate486 / metal-280 / run 4d8855d4b09389190beed0794d1ba4a1 on 24H32:
all 163 kernel sites discovered; dynamic Metal/VCN discovery handles changed
UUIDs; VM producer returns normalize correctly from the actual KC map.
CORE_PROBE_PASS: WindowServer/display use Navi23 Metal 3; 61,274,112 readback
pixels across main/driver-only matrices, zero mismatches. Console-user window
presents ~120 fps, correct drawable quadrants and moving-bar self-captures.
QEMU host window visibly shows the desktop; root screen-recording permission
limits parent capture checks. Full-field 4K120 stress was not repeated here.
Native shutdown exited-after-guest-request / QEMU exit 0; recovery recovered,
authorizes_launch=true. Host boot 2e377991-b6d2-4fe5-81dd-fd6afe9999f7 remains
usable. Full host suite 1620 (8 skipped) passes. The driver milestone is on dev at
f6ed6b4694498bec9f28329c0705339e88a85255; exact-commit hosted test/build pass
(Actions run 38384315428).
Evidence: findings/research/update-portability-20261013/runtime-24h32.md and
~/macos-vm/run/candidate-486-results/. Superseded attempts are preserved there
and in candidate485's results/status history; no failed receipt was overwritten.

Desktop pointer now selects candidate486 / metal-281 (interactive profile);
the installed launcher preserves the existing USB picker behavior. A bounded
launcher run 02ba1491c5bc178274d034f196f8c7eb / d20261013140104 also passes:
61,274,112 readback pixels, zero errors, console-user ~119.75 fps, no failed
frames/missing drawables. Native shutdown, QEMU exit 0, recovery recovered and
authorizes_launch=true. Critical capture ends recv-reset at verified natural
container exit; exit reconciliation reports no errors. Launcher delivery CI pending.
Real 15.8 / 24H23 installer KC resolves all 163 sites without catalog changes
(offline evidence, not a guest/GPU verdict). The 24G830 backup clone booted
GPU-less but its root agent was absent; sudo authentication failed, so no VFIO
launch occurred. It shut down through System Events; user disk was restored.
Now inspecting installer userspace images on an independent 24H32 CPU-only
clone, with the original disk preserved in run/macos15-update-tests/.
Next: qualify the same driver on another macOS 15 update. User priority is macOS 15 first. Tahoe's
verified installer is retained; no Tahoe installation/qualification is claimed.
Automatic GPU-less inspection is required when disk/contracts change; unknown
or ambiguous code/ABI refuses exposure. Arbitrary future private ABI changes
are not guaranteed. Fresh-host-boot and crash-recovery coverage remain open.

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

Desktop release 483 (docs/desktop-launcher.md, pins v15, metal-277): shortcut, passwordless
iGPU bind, clipboard, USB, audio, no session limit, self-held sleep block. VERIFIED on a fresh
boot (96307e7a, no suspend, `amdgpu.virtual_display` removed): mode2 #417 admitted DMCUB
`linux-image` (running, 0x05003500) without writing it; the guest logged "DCNCOLD: Linux DMCUB
image stopped=1", held=1, native tail 32 MiB reserved, "DMCUB held and memory reserved before
PSP TMR replacement", then accelerator power-up; the user used macOS and shut it down from its
menu at 21:35; recovery `recovered`, authorizes_launch=true. Harness verdict INVALID
(probe_completion_missing: interactive desktop run, no probe) and shutdown.json says
`forced-after-shutdown-error` because QEMU had already exited when the serial service was
checked: both bookkeeping, not GPU faults. Cause of the earlier fresh-boot failures:
`amdgpu.virtual_display` (2026-10-12) left the platform's DMCUB image (0x05000549), which
481 crashed the host over; it is refused before QEMU. Dummy plug: not the cause.

Earlier: 478, force-stopped after the guest stopped answering; its recovery is an
immutable `incomplete` receipt (SDMA copy queue left enabled), so the next launch needs a
host reboot and `gpu-bind.sh`. 479 (clipboard via qemu-vdagent, USB via owner-only
usbredir sockets + tools/rgpu-usb.sh, fullscreen aspect, exit stop list for the SDMA queue)
is built and staged but not yet run. Audio works (user). 469-477 r2 ended with verified exits and authorizing
recovery. Early-boot macOS kernel panics at 457, 468 and 477 (different signatures, ~1 in 10
boots; retries boot cleanly): open reliability item. Host LLVM upgraded to 23.1.1 mid-session; 473+ built with it.

Open: pointer corner proof and keyboard check (needs the user); Retina below 3840 wide
(small windows show the larger 'panel = 3840' UI); shutdown receipt mislabels a guest power-off as forced; one transient OSKext::copyInfo guest panic at 457's first boot.

Safety: QEMU validates the guest control page from one snapshot and bounds BAR offsets in
64 bits; writeback and our SDMA queue are quiesced before every MODE2 and listed in QEMU's
exit stop list. Host suite 1606 (8 skipped) passed. No main publication.

Evidence: findings/research/igpu-sdma-4k120-qemu-window-20261012.md,
igpu-window-fit-120hz-20261012.md; ~/macos-vm/run/c460-dcc-scanout-copy-notes.md.

Housekeeping 2026-10-12: old candidate builds/dists (<449 entirely; 449-478 extracted
builds and dists only, results kept), per-launch OpenCore/config backups (newest 3 kept),
the c398 VirtualBox clones, the guest disk backup, old project docker images and
containers, and 259 old worktrees were removed (log: ~/macos-vm/run/cleanup-20261012.log;
uncommitted worktree changes saved in ~/macos-vm/run/worktree-leftovers/ and pushed as
preserve/* branches).


## One-command GPU test

- Output: `/home/user/macos-vm/run/candidate-486-attempt-24g830r2-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`
