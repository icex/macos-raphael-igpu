# Raphael iGPU acceleration roadmap

**Current delivery:** candidate 490 is installed; macOS 26.7.1 is the desktop
default, with the original 15.8.1 image retained for rollback. Latest-version
compatibility and matched GPU render/compute comparisons are delivered on `dev`.
Unused installer/test/build versions are being removed; runtime and recovery
evidence and Git source history are retained. Unlocked Tahoe presentation,
full-field 4K120, physical display and general crash/fresh-boot qualification
remain separate open gates. [Current status](../status.md).

**Latest matched performance:**15.8.1 and26.7.1 deliver essentially equal GPU
render/FP32 compute throughput with the same driver and benchmark binary.
[Workloads, raw samples and limits](../findings/research/update-portability-20261013/performance-latest.md).

**October 13, candidate 490: one dynamic driver passes macOS 15.8.1 and 26.7.1.**
The same executable checks 61.3 million pixels with zero errors on each, with
correct moving window self-captures and native shutdown/recovery.15.8.1 presents
at 120 fps and its QEMU desktop is visibly correct. Tahoe presentation timing and
unlocked desktop remain unqualified because its tested session is locked.
Driver addresses, call relocations and active userspace fixes are discovered
from current images; no per-build UUID/address list is needed. The original
15.8.1 disk is restored. Candidate490 is the desktop release; normal sessions
retain clipboard, USB redirection and audio, while autonomous tests stay bounded.
[Latest-version evidence and limits](../findings/research/update-portability-20261013/latest-release-matrix.md).

**October 13, candidate489: macOS 26.6 / 25G72 passes core Metal rendering.**
All 164 driver sites resolve dynamically, with guarded compiler families and
owner-bound interior sites. Hybrid entry checks and the VCN allocation patch
preserve the running image's call relocations. Readback passes 61.3 million
pixels with zero mismatches; UID501 self-captures show correct colors and motion.
Native shutdown and ordinary recovery pass. FPS and direct QEMU visibility
remain unqualified; 26.7.1 update coverage is next. The installed launcher still
uses qualified candidate486.
[Evidence and limits](../findings/research/update-portability-20261013/runtime-25g72.md).

**October 13, candidate486: first dynamic macOS 15 update milestone verified.**
15.8.1 / 24H32 boots, uses the accelerator for WindowServer, passes 61.3 million
readback pixels and a ~120 fps Metal window, then shuts down/reuses cleanly.
Routes, VM producer return sites and active userspace patches resolve from the
current images. Fresh GPU-less inspection prevents stale build labels from
admitting exposure. The same binary now also passes live 15.7.9 / 24G830 tests,
including native shutdown/recovery. Installer-only 15.7.7 and 15.8 inputs pass
unchanged discovery contracts. Live 15.8 / 24H23 also passes readback/captures
and native shutdown/recovery, meeting the three-version minimum; its presentation
timestamps are zero so FPS is unqualified. Next: Tahoe installation/updates.
Unknown code/ABI families fail safe.
The installed desktop shortcut now uses candidate486 / metal-281; a bounded
launcher verification also passes the desktop probe and native shutdown/recovery.
[Evidence and scope](../findings/research/update-portability-20261013/runtime-24h32.md).

**October 12, candidates 479–483: one-click desktop release, fresh boots without suspend.**
Desktop shortcut with passwordless iGPU bind, clipboard (qemu-vdagent), USB redirection over
owner-only sockets, audio, no session limit. Fresh boots: the guest takes over the Linux
driver's DMCUB image (483, verified on hardware); the platform image left by
`amdgpu.virtual_display` froze the host (481) and is refused. Open: early-boot guest panics,
shutdown receipt labels a guest-initiated power-off as forced.

**October 12, candidates 475–478: user-chosen resolution, clean window, boot output.**
The user picks the Retina resolution in Displays; QEMU scales it into any window shape,
centred with black bars, and shows firmware/OpenCore/boot logo through a ramfb until the
iGPU path starts. Early-boot guest panics (~1 in 10 boots) remain open.

**October 12, candidates 469–474: standard Retina steps, aspect-snapping window.**
Displays lists standard Retina steps for six aspect classes (1080p/1440p 16:9, 1200p/1600p
16:10, 21:9, 32:9, 3:2, 4:3), all at 120 Hz. A window resize picks the step nearest
window/1.33 points within the current mode's aspect; QEMU scales between steps and snaps
the window to the aspect after a resize. [Evidence](../findings/research/igpu-sdma-4k120-qemu-window-20261012.md).

**October 12, candidates 465–468: Retina up to 5K at 120 Hz, window-exact.**
ODM 4:1 drives all four pipes (5120x2880 at 119.98 Hz). Retina panels follow the window's
exact aspect at 2 x window / 1.33, so "looks like" is about window/1.33 points (2560x1440
on 5120x2880, 2593x1518 on 5186x3036, both at 120 Hz) once the EDID lets DisplayID carry
the native size. The compact 1x mode runs at 120 Hz up to the ODM budget. 5K full-field
Metal is rendering-bound at ~42 frames/s. [Evidence](../findings/research/igpu-sdma-4k120-qemu-window-20261012.md).

**October 12, candidates 460–464: full 4K at 120 Hz in QEMU's window.**
An SDMA queue we own copies every new scanout frame (2.33 ms at 3840x2160) into QEMU's
buffers, so ODM no longer halves the capture: the Retina "1920x1080" panel runs at
119.98 Hz with 120.0 frames/s presented over 65 s of full-field Metal (464). Scanout
surfaces are allocated without DCC, the copy follows the surface's pixel format, and the
hardware cursor is copied separately and drawn by QEMU as an overlay.
[Evidence](../findings/research/igpu-sdma-4k120-qemu-window-20261012.md).

**October 12, candidates 456–459: 4K at 120 Hz scanout, own SDMA queue.**
ODM 2:1 forced for the virtual stream runs the 3840x2160 Retina panel at 119.98 Hz (457).
Writeback captures only one ODM segment, so full frames will come from copying the scanout
surface with an SDMA0 queue we own (live in 458; copy loop in 459). Scanout surfaces are
DCC-compressed, so a DCC-aware copy is next. QEMU's control-page handling was hardened
against guest double fetches.

**October 12, candidates 454–455: window-fit HiDPI/1x and 120 Hz.**
Each QEMU window size gives one display with a 3840-wide HiDPI panel (default) and the
window's exact pixel size at 1x; a guest helper selects either. The exact mode runs at
120 Hz where one display pipe fits (119.71 distinct frames/s over 65 s at 1600x1000).
Direct-launcher shutdowns can now be verified (454: exited-after-guest-request), and fresh
boots take over the Linux driver's DMCUB image in the guest (483; no host-side halt). Open: Retina at 120 Hz (needs a scanout copy; writeback
sees half a frame under ODM), HiDPI at arbitrary sizes (macOS ignores display overrides).
[Evidence](../findings/research/igpu-window-fit-120hz-20261012.md).

**October 12, candidates 449–453: the iGPU's own display in QEMU's window, Retina, 60 fps.**
DCN display writeback copies every composited frame into a RAM region QEMU owns (reached
through an MMHUB AGP window; no emulated display adapter, no mirror, no plug), and QEMU's
vfio device presents it in its GTK/GL window as zero-copy dmabufs. 453 delivers 60.0
distinct frames per second at 3840x2160/3840x2400, follows the window shape (runtime EDID +
emulated hotplug) and keeps macOS at Retina "looks like 1920x1080/1200". Writeback is
quiesced before every reset after a host freeze on 2026-10-11. Open: 120 Hz (needs ODM),
fresh-boot firmware state, pointer proof. [Evidence](../findings/research/igpu-writeback-qemu-window-20261012.md).

**October 11, candidates 446–448: plug-free iGPU display at 60 Hz.**
The iGPU now drives a single macOS display without any monitor: the driver reports an AMD DC
virtual-signal sink ("Raphael VD", our own EDID) and keeps every physical connector
disconnected, so no PHY, link training or display firmware is involved. With the DCHUBBUB
global timer, Raphael's 600 MHz DTO reference and the compressed-buffer size set as Linux
does, 448 passes the Metal probe, macOS shows one 3840×2160 (1920×1080 HiDPI) display at
60 Hz with no mirror, the display timer measures 59.99 Hz and page flips latch. QEMU does
not show it yet: next is a per-flip GPU copy into guest-visible RAM read by a QEMU console of
the vfio device. [Evidence](../findings/research/igpu-virtual-sink-20261011.md).

**October 11, candidate 445: iGPU display engine as the QEMU display (new priority).**
The user's target is now the iGPU driving its own display with QEMU showing that output
directly: no virtual display, no Bochs device, no mirror, eventually no HDMI plug. With a
dummy HDMI sink and the 330 display configuration on today's source, macOS shows a single
iGPU display and the scanout is a linear ARGB8888 4K surface inside BAR0, but the
accelerator fails TTL initialisation (no Metal, software compositing), the stream runs at
67.5 Hz instead of 60, and BAR0 reads are uncached (~22 MB/s). Next: the 330→444
regression, the stream clock, a guest-RAM scanout transport for QEMU, then an emulated sink.
[445 survey](../findings/research/igpu-native-display-survey-20261011.md).

**October 11, candidate 444: full-field 4K in the window from ~40 to ~50 IDs/s.**
A per-stage budget showed the guest presenter's snapshot commits waiting for QEMU's
global lock behind SPICE update creation. Three QEMU changes (snapshot copy and SPICE
update creation outside that lock, publish on commit) let the server send 52-54 full
4K updates/s with no replaced snapshots; the viewer then saturated copying ~1.3 GB/s
of raw pixels. A private client build that receives raw bitmaps without the extra copy
measured 50.35/49.79 decoded IDs/s full-field and ~57 localized at 3840×2160 → 1440×900,
with 100/100 sampled moving frames valid. LZ4 was slower. These are research images and
a private client, not sustained 4K60 or scanout FPS. Next: overlap the presenter's capture
lock with its commit, then the client's remaining copy; Moonlight pairing is pending.
[444 evidence](../findings/research/console-4k-pipeline-locks-20261011.md).

**October 10, candidate 443: GPU-scaled moving output verified; pacing is not the limit.**
Across three same-boot cycles, 300 of 300 sampled moving frames read back from the
host GL framebuffer carried the correct fresh token after scaling 3840×2160 into the
1440×900 window. With the source now outliving every observation, default-pacing GL
measured 38.6–41.8 decoded IDs/s in full-field phases (repeating 441's gain over
Cairo's 23.7–23.9). QEMU start-relative pacing raised full-field refreshes from
about 48/s to 58/s but did not raise delivery (37.8–39.4 IDs/s): about 40 commands/s
are created regardless of refresh rate, so the remaining ceiling lies upstream of
the client. These are sampled and decoded observations, not scanout FPS or sustained
4K60. All runs shut down at guest request and recovered with reuse authorized.
[443 evidence](../findings/research/console-gl-pacing-20261010.md).

**October 10, candidate 441: optional host GPU scaling improves full-field 4K.**
In the same boot, the private GTK client’s raw-primary GL renderer observed
37.74–41.80 decoded token IDs/s during full-field phases, versus 23.73–23.85
with Cairo. Localized phases remained about 56 IDs/s. Both used a 1920×1080
logical desktop with 3840×2160 backing, approximately 60 source draws/s, raw
SPICE transport and a normal 1440×900/GDK1 host window.

No invalid tokens occurred within the compared source intervals. The nominal
100-second observers started late and outlasted the 110-second fixtures, producing 32 GL
and 36 Cairo trailing missing-border samples; these are not clean 100-second
runs. A static native GL framebuffer matched the scaled CPU image’s bilinear
RGB oracle exactly, including black letterboxing. Moving whole-frame integrity,
quality equivalence to Cairo and input behavior with this renderer remain
unqualified. These are decoded observations, not scanout FPS or sustained 4K60.

The renderer is an opt-in private host-client experiment, not the default client,
not a new guest GPU transport and not included in the checked-in candidate 428
kext bundle. Only full-field 4K performance is active; native framebuffer, 120 Hz,
5K and other roadmap work remain on hold. The harness completed
guest-requested shutdown and recovered the GPU with reuse authorized; capture
and reconciliation details remain in the run evidence.
[441 evidence](../findings/research/console-raw-gpu-scaling-20261010.md).

**October 10, candidate 428: native virt-manager clipboard and USB milestone.**
Fresh ASCII and Unicode/multiline text passes in both directions using the tested
X11 client backend. The existing USB chooser redirects the Kingston DataTraveler:
macOS enumerates its USB3 storage and two 1 MiB reads match. Arctis USB audio also
enumerates and accepts stereo output callbacks; audible playback was not tested.
Window-driven 1280×720, 1101×703 and 1600×900 modes are checked separately.
Normal Arctis chooser detach restores host drivers; abrupt viewer failure does
not have the same recovery guarantee. Kingston eject attempts remained busy.
Guest shutdown was observed, but capture forced an abort; GPU recovery passed.

**Earlier Retina/refresh investigation (now on hold).**

Candidate432 native EDID adds2560×1440/120Hz with a HiDPI variant, but a same-process
probe still reports33.33ms CVDisplayLink timing. EDID alone cannot provide120Hz
pacing. Native framebuffer timing/VBL and dynamic modes were proposed follow-up work, now on hold;
the current holder remains available. Mode reversion and sustained native120 output
are unqualified. [Evidence](../findings/research/console-native-edid-result-20261010.md).
The current virtual snapshot transport is still capped at 4K/60. Physical HDMI
4K120 does not establish 120 Hz delivery through the virtual copy/SPICE path.
[Native evidence](../findings/research/virt-manager-clipboard-usb-native-20261010.md).

Updated 2026-10-10. Performance baseline: **402**; desktop integration: **428**. The bounded
private host-buffer pool lowers measured snapshot copy cost from 6.834 to 1.948 ms.
Localized motion reaches about 57 decoded IDs/s, while full-field motion stays
about 25/s: sustained 4K at 60 Hz and whole-frame dynamic integrity remain open. The
100-second manager observation has 4402 unique IDs and zero invalid/duplicate
samples; these are pipeline samples, not GPU FPS. One sequential trial per
configuration does not establish a universal performance gain.

402 also passes controlled full-pixel stale-owner isolation, retained-map cleanup,
owned presenter restart with unchanged capture-app seal, odd resize, five-target
input/exact text and stereo sample delivery/restoration. Serial capture retains
two corrupt lines and two incomplete snapshots. Independent natural shutdown and
recoverable cleanup do not erase those capture defects.
[402 evidence](../findings/research/console-snapshot-private-pool-native-20261010.md).

**QEMU/virt-manager remains the priority; VirtualBox is deferred.**
VirtualBox work is deferred at the user’s request. Candidate 417 was stopped during
early boot at the earlier pause.
The controller helper forced poweroff, then unregistered the VM on its first
attempt without a reported cleanup error. This was not clean guest shutdown;
no desktop, root response or process-admission receipt qualified the hardened
process fix. No GPU was exposed. Candidate 420 retains source investigation only.
[417 pause result](../findings/research/virtualbox-relay-pause-20261010.md) ·
[420 resume points](../findings/research/virtualbox-pgm-lease-paused-20261010.md).

**VirtualBox 410** now returns fresh registry evidence over a bounded FAT exchange
disk. Stock VMSVGA GFX0 at `0:2.0` has 64 MiB framebuffer / 2 MiB FIFO memory and an active
Display_boot/IONDRVFramebuffer with user clients. Nine returned file hashes pass;
original 409 temporary files were absent. Independent natural S5/OFF, unregister
and medium closure pass, while the controller's transient state-query error and
0×0 screenshot refusal remain recorded. 406's earlier eight-vCPU input/natural
shutdown remains scoped; PerfPowerServices CPU use and sustained stability stay open.
[410 result](../findings/research/virtualbox-fat-exchange-native-20261010.md).

VirtualBox work is deferred at the user’s request. Candidate 420 is source investigation only;
no implementation or runtime result is claimed. On resumption, qualify early boot-framebuffer suppression using the inspected 24G830
AAPL,iokit-ignore-ndrv property and read-only inventory. This candidate has not
run; it must not claim exclusive aperture ownership or write FIFO/registers.
Candidate 415 verified virtio networking, but the guarded root relay returned
HTTP 403 and executed no payload; natural shutdown and unregister succeeded.
Candidates 416/418 now pass isolated full-source baseline/patched userland builds
with optional Qt/OpenGL, kernel-module builds and packaging excluded. Corrected
bundled unmap UAPI definitions pass a compiled Linux ABI comparison. The 242 built
testcase executables were not run; extracted transaction fixtures substitute PGM
and map calls. Nothing was installed or runtime-qualified. Authoritative RAM
coverage/lifetime, reset policy and complete passthrough safety remain blockers. Stock FIFO fences
do not establish immutable frame publication. No VBox Raphael acceleration or
production display adapter exists.
[Framebuffer plan](../findings/research/virtualbox-boot-framebuffer-ownership-20261010.md) ·
[Production build](../findings/research/virtualbox-dma-production-build-20261010.md) ·
[DMA readiness and lease limits](../findings/research/virtualbox-dma-ram-lease-20261010.md) ·
[Stock fence audit](../findings/research/virtualbox-stock-publication-fences-20261010.md).

Existing scale preference, odd 1× resize, connected-agent input/audio and fresh-boot
1× 4K startup remain qualified in their recorded scopes. The isolated client
stationary-pointer fix is not installed system-wide. Fresh-user setup, broader
crash/host-boot coverage and other frontends remain open. GPU-native virtual display
transport is unimplemented. VirtualBox 7.2.18 has a VFIO backend with observed configuration dispatch;
Raphael safety and accelerated-console integration remain unqualified.

Physical baseline remains **330**, user-confirmed correct-color HiDPI 120 Hz/HDMI audio.
Full desktop acceleration is **not qualified**. Detailed historical milestones and
limits remain below. [395 evidence](../findings/research/console-private-staging-cleanup-native-20261009.md)
· [VirtualBox source audit](../findings/research/virtualbox-vfio-configuration-design-20261009.md).

This is the current roadmap. [Live state and run authority](../status.md) are separate.
The [previous roadmap](../findings/research/status-archives/roadmap-before-20260916-refresh.md)
preserves the candidate159–194 history and review decisions; its dated launch budgets
and “next experiment” instructions do not describe today's host.

CI portability (2026-09-17): install image-analysis dependencies, fetch historical
source contracts, and use temporary Lilu/KVM fixtures in host tests. The Linux
regression and macOS source-build jobs remain required; see [CI setup](releases.md).

