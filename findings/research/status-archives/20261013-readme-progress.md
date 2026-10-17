## Current status

**Latest matched performance:**15.8.1 and26.7.1 deliver essentially equal GPU
render/FP32 compute throughput with the same driver and benchmark binary.
[Workloads, raw samples and limits](findings/research/update-portability-20261013/performance-latest.md).

**October 13, candidate 490: one dynamic driver passes macOS 15.8.1 and 26.7.1.**
The same executable checks 61.3 million pixels with zero errors on each, with
correct moving window self-captures and native shutdown/recovery.15.8.1 presents
at 120 fps and its QEMU desktop is visibly correct. Tahoe presentation timing and
unlocked desktop remain unqualified because its tested session is locked.
Driver addresses, call relocations and active userspace fixes are discovered
from current images; no per-build UUID/address list is needed. The original
15.8.1 disk is restored. Candidate490 is the desktop release; normal sessions
retain clipboard, USB redirection and audio, while autonomous tests stay bounded.
[Latest-version evidence and limits](findings/research/update-portability-20261013/latest-release-matrix.md).

**October 13, candidate489: macOS 26.6 / 25G72 passes core Metal rendering.**
All 164 driver sites resolve dynamically, with guarded compiler families and
owner-bound interior sites. Hybrid entry checks and the VCN allocation patch
preserve the running image's call relocations. Readback passes 61.3 million
pixels with zero mismatches; UID501 self-captures show correct colors and motion.
Native shutdown and ordinary recovery pass. FPS and direct QEMU visibility
remain unqualified; 26.7.1 update coverage is next. The installed launcher still
uses qualified candidate486.
[Evidence and limits](findings/research/update-portability-20261013/runtime-25g72.md).

**October 13, candidate 486: macOS 15.8.1 / 24H32 passes the updated driver.**
Kernel routes and active Metal/VCN fixes are discovered from the current images,
with no per-build UUID/address allowlist. The real updated guest passes 61.3 million
readback pixels, a ~120 fps Metal window with correct self-capture, and clean
shutdown/recovery. Each changed disk is inspected in a GPU-less guest before
exposure; unsupported or ambiguous code/ABI contracts refuse launch.
The installed desktop shortcut now uses candidate486 / metal-281; a bounded
launcher verification also passes the desktop probe and native shutdown/recovery.
[Evidence and limits](findings/research/update-portability-20261013/runtime-24h32.md).
The same driver now passes live 15.7.9 / 24G830, 15.8 / 24H23 and 15.8.1 / 24H32.
That meets the user's three-version minimum; macOS 26 and its updates are next.
15.8 rendering/captures pass, while its presentation timestamps/FPS remain unqualified.
[Third live run](findings/research/update-portability-20261013/runtime-24h23.md).
See [second live run](findings/research/update-portability-20261013/runtime-24g830.md). Arbitrary future Apple
ABI changes are not guaranteed to need no maintenance.

**October 12, candidate 483: desktop release starts on a fresh boot with one click.**
The **macOS (Raphael iGPU)** shortcut ([desktop launcher](docs/desktop-launcher.md)) binds
the iGPU without a password, runs the full safety cycle and opens macOS in QEMU's window
with the iGPU's own Retina display (up to 120 Hz), clipboard, USB redirection and audio,
with no session limit. On a fresh host boot the Linux driver's display firmware image
(DMCUB 0x05003500) is now taken over by the guest (stopped the Linux way, its secure windows
kept, then PSP replaces the TMR), so no host suspend is needed: run d20261012213127 started
on a fresh boot, ran macOS with the accelerator, shut down from macOS's menu and recovered
with an authorizing receipt. Do not set `amdgpu.virtual_display` for the iGPU: it leaves the
platform's own DMCUB image, which crashed the host (481) and is now refused before QEMU.

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
[444 evidence](findings/research/console-4k-pipeline-locks-20261011.md).

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
[443 evidence](findings/research/console-gl-pacing-20261010.md).

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
[441 evidence](findings/research/console-raw-gpu-scaling-20261010.md).

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
The current virtual snapshot transport is still capped at 4K/60. Physical HDMI
4K120 does not establish 120 Hz delivery through the virtual copy/SPICE path.
[Native evidence](findings/research/virt-manager-clipboard-usb-native-20261010.md).

**October 10 update, candidate 402:** a bounded private host-buffer pool reduces
measured 4K snapshot copy cost from 6.834 to 1.948 ms in the recorded comparison.
Localized motion reaches about 57 decoded token IDs/s; full-field motion remains
about 25 IDs/s and does not improve. The 100-second actual-manager observation has
4402 unique IDs and zero invalid or duplicate samples. These are sampled pipeline
updates, not GPU FPS, whole-frame integrity or sustained 4K at 60 Hz qualification.

Full-pixel stale-writer isolation, retained-map cleanup, owned presenter restart,
odd-size resize, five-target/text input and stereo sample delivery/restoration
pass. The sealed capture app is unchanged. Serial capture retains two corrupt lines and
two incomplete snapshots: function passes, capture is imperfect. Independent natural
shutdown and authorizing recovery pass.
[402 native evidence](findings/research/console-snapshot-private-pool-native-20261010.md).

**QEMU/virt-manager remains the priority; VirtualBox is deferred.**
VirtualBox work is deferred at the user’s request. Candidate 417 was stopped during
early boot at the earlier pause.
The controller helper forced poweroff, then unregistered the VM on its first
attempt without a reported cleanup error. This was not clean guest shutdown;
no desktop, root response or process-admission receipt qualified the hardened
process fix. No GPU was exposed. Candidate 420 retains source investigation only.
[417 pause result](findings/research/virtualbox-relay-pause-20261010.md) ·
[420 resume points](findings/research/virtualbox-pgm-lease-paused-20261010.md).

**Actual VirtualBox, candidate 410:** a small FAT exchange disk now returns fresh
macOS registry evidence from the stock VMSVGA software desktop. GFX0 is `15ad:0405`
at PCI `0:2.0`, with 64 MiB framebuffer memory and 2 MiB FIFO memory. Display_boot /
IONDRVFramebuffer and its user clients are still attached; this is not exclusive
ownership or accelerated presentation. Nine returned file hashes verify. Original
409 temporary files were absent and were not recovered.

Root verified input/awake state and removed the owned awake job before shutdown.
Independent S5/OFF evidence and medium closure prove natural completion, but the
original controller retains a transient state-query VBoxCallError and a 0×0
screenshot refusal. These errors are not erased by successful cleanup. Earlier 406
qualified eight-vCPU software input and natural shutdown; slow interaction and
PerfPowerServices CPU use remain open.
[410 evidence](findings/research/virtualbox-fat-exchange-native-20261010.md).

The next boot-framebuffer discriminator is **not yet run**: change an early
loader property to suppress IONDRVFramebuffer matching in the inspected 24G830
sources, then use read-only inventory to establish the resulting attachment state. It is not
a live takeover or an exclusive memory lease. Candidate 415 verified the virtio
network interface, but its root-command relay refused process admission with HTTP
403; no root payload ran. Natural shutdown and unregister succeeded.

Candidates 416/418 now compile the baseline and patched VirtualBox 7.2.18 userland
from full source in isolated directories. The first patched build exposed missing
bundled Linux UAPI definitions; the corrected build and ABI comparison pass.
Qt/OpenGL, host kernel-module builds and packaging were excluded, and the 242
built testcase executables were not run. Extracted transaction tests substitute
PGM and map-ioctl behavior; these are **not deployed or runtime-qualified builds**.
Complete RAM-lifetime, reset and passthrough safety remain unresolved. No Raphael
acceleration or atomic presentation adapter is implemented for VirtualBox.
[Framebuffer plan](findings/research/virtualbox-boot-framebuffer-ownership-20261010.md) ·
[415 relay refusal](findings/research/virtualbox-root-relay-native-20261010.md) ·
[418 production build](findings/research/virtualbox-dma-production-build-20261010.md) ·
[DMA limits](findings/research/virtualbox-dma-ram-lease-20261010.md) ·
[Stock fence limits](findings/research/virtualbox-stock-publication-fences-20261010.md).

Earlier candidate 395 supplies the private-buffer ownership and restart baseline;
candidate 399 supplies the fresh-backing timing comparison. Their original capture
and lifecycle limitations remain in the linked reports.
[395 baseline](findings/research/console-private-staging-cleanup-native-20261009.md) ·
[399 timing](findings/research/console-host-snapshot-timing-native-20261010.md).

Candidate392 retains next-guest-boot1× 4K startup, input/audio evidence and a scoped
stationary-pointer fix in an isolated spice-gtk client. System client libraries
are unchanged. Candidate394 verifies installed snapshot startup plus two helper
restarts and audio delivery, but ends in forced capture-abort teardown.395 has
independent guest-shutdown/Docker exit0/recovery evidence; its original outer
classification remains unverified because it missed a completed shutdown-wait
receipt variant. Witness exit137 is not container exit137.
[Preference usage](docs/console-helper-install.md#persistent-guest-scale).

GPU-native display transport (candidate 483, `VM_CONSOLE=igpu`, desktop launcher): an SDMA
copy of each scanout frame puts the iGPU's desktop into QEMU's own GTK/GL window with no
emulated adapter or mirror, following the window: Retina 3840x2160 at 120 Hz (120 frames/s
measured; standard Retina steps from 1920x1080 to 2560x1600 and 3840x1080 at 120 Hz, chosen
in Displays and scaled into the window); the hardware cursor is drawn by QEMU as an
overlay. See [the guest display helper](docs/igpu-display-helper.md). It needs the patched
QEMU image (pins v15); boot output appears in the same window. [Evidence](findings/research/igpu-sdma-4k120-qemu-window-20261012.md). The older
console path below captures/copies into a separate virtual framebuffer.
VirtualBox7.2.18 has a configuration-dispatch-tested Linux VFIO backend and the
software desktop above; Raphael safety/acceleration and a separate accelerated
console transport remain unqualified.
It is not supported by a configuration switch or by a VirtualBox-styled QEMU window.
[VirtualBox source audit](findings/research/virtualbox-vfio-configuration-design-20261009.md).
Fresh-user installation, automatic DPI choice, broader crash/host-boot coverage,
audio endpoint audibility and A/V sync remain open.

Stock QEMU remains the default; snapshot experiments use separately pinned images.
[Current agent transport and bounded resize evidence](findings/research/console-vdagent-native-20261009.md)
· [Prior viewport, audio and lifecycle evidence](findings/research/console-viewport-native-20261009.md)
· [Prior mixed-motion evidence](findings/research/console-mixed-motion-native-20261009.md)
· [Input/audio evidence](findings/research/console-default-audio-input-20261009.md)
· [Setup and limits](docs/virtual-console.md).

The qualified remote baseline from **2026-09-16**, candidate **1.0.280**, runs an accelerated desktop through
macOS Screen Sharing. Native window effects and Safari composition checks pass,
including the previously affected transparent areas. Broader application coverage
and long-duration reliability are still being tested.

| Capability | Current result |
|---|---|
| Remote desktop | WindowServer uses the accelerator; a restored isolated setup is visibly crisp at 1920×1080 logical, 3840×2160 backing, 2× and nominal 60 Hz. Transparency, blur, window movement and resizing render correctly. |
| Metal rendering and compute | Verified output in targeted compute, texture, depth/stencil and MSAA tests. Full Metal conformance is not established. |
| Memory and synchronization | Buffer/texture reuse, synchronized CPU/GPU texture updates, retained color contents, GPU fences, shared events and cross-process IOSurface transfers pass targeted checks. |
| Hardware video | H.264 and HEVC Main8 encode/decode work. HEVC Main10 decoding passes short tests; Main10 hardware encoding is unavailable in the current native profile set. |
| Shutdown and reuse | Repeated clean guest shutdowns and same-host-boot reuse work in the supervised workflow. Crash recovery and independent-host-boot coverage remain incomplete. |
| Physical HDMI | Correct 1920×1080 HiDPI / 3840×2160 pixels at120Hz on Samsung Odyssey G95NC, with audible HDMI audio (330). Audio selection/playback survives tested HiDPI 120 Hz→60→120 switches. |

The earlier broad qualification baseline is **macOS Sequoia build 24G830**;
**15.8.1 / 24H32** now passes the scoped update-compatibility tests above. Use matching driver,
Lilu, OpenCore configuration and grafted VBIOS. Stock QEMU 10.1.2 now works with
[VirtualSMC and an OpenCore SMC ownership patch](docs/stock-qemu-smc.md), keeping
PerfPowerServices CPU usage normal without modifying QEMU. Other hypervisors and
all macOS update builds are not yet validated.
Performance, games and general application compatibility are not yet qualified.

See [live status and evidence](status.md) for exact tested builds and the scope of
each result. A successful build or individual probe does not establish full desktop
readiness.

[Physical HDMI setup and remaining limits](docs/hdmi-status.md). DisplayPort is untested.

Host tests and the macOS source build run in GitHub Actions on `dev` and `main`; see
[CI prerequisites and scope](docs/releases.md).

