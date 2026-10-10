# RaphaelGPU

Experimental macOS graphics acceleration for the **AMD Raphael / Granite Ridge
integrated GPU**, using Apple's native AMD graphics stack through a Lilu plugin.
The current development platform is a macOS Sequoia VM on Linux with QEMU/KVM
and VFIO GPU passthrough.

Our goal is a usable, correctly rendered Metal desktop, hardware video acceleration,
physical display output, and reliable shutdown and recovery. Development is active
on **`dev`**; this is not yet a generally supported driver release.

[Current status](status.md) · [Roadmap](docs/ROADMAP.md) ·
[QEMU setup](examples/qemu/README.md) · [Build instructions](docs/releases.md)

## Current status

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

GPU-native virtual display transport is **not implemented**: Metal renders on
Raphael, while presentation captures/copies into a separate virtual framebuffer.
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

The tested baseline is **macOS Sequoia build 24G830** with a matching driver,
Lilu, OpenCore configuration and grafted VBIOS. Stock QEMU 10.1.2 now works with
[VirtualSMC and an OpenCore SMC ownership patch](docs/stock-qemu-smc.md), keeping
PerfPowerServices CPU usage normal without modifying QEMU. Other hypervisors and
arbitrary macOS updates are not validated.
Performance, games and general application compatibility are not yet qualified.

See [live status and evidence](status.md) for exact tested builds and the scope of
each result. A successful build or individual probe does not establish full desktop
readiness.

[Physical HDMI setup and remaining limits](docs/hdmi-status.md). DisplayPort is untested.

Host tests and the macOS source build run in GitHub Actions on `dev` and `main`; see
[CI prerequisites and scope](docs/releases.md).

## Goals and next steps

- **Qualify full 4K Screen Sharing:** the isolated Retina helper now selects a crisp
  1920×1080 logical desktop with 3840×2160 backing at nominal 60 Hz. Continue
  validating reboot/login behavior, capture transport, delivered frame rate and
  latency independently of mode timing. A prior mixed 90/120 Hz sequence produced
  a user-black desktop and was cleanly restored; those requested rates are not
  proven modes.
- **Qualify remote streaming:** Sunshine offers hardware H.264 and HEVC Main8. With the
  VCN preset fix (candidate 284; 4K encode 11ms, equal to Linux), a 2GB BIOS UMA
  carve-out and ScreenCaptureKit capture, the user reports stable 4K at 60 Hz streaming in Moonlight
  with no stutter. True 120Hz needs a CoreDisplay patch: macOS virtual displays vsync at a
  hardcoded 60Hz, a live memory patch proved 120Hz, and the permanent patch is designed but
  not built. 4K encoding tops out at ~66–83fps; 1440p/1080p should reach 120fps.
  [Measurements and 120Hz design](findings/research/encoder-pipeline-20260917.md)
  · [Setup, LAN access and firewall rules](docs/sunshine.md)
  · [Sunshine patches](patches/sunshine/).
- **Broaden portability:** extend the working stock-QEMU/OpenCore setup across
  host boots and supported versions, and document requirements for other hypervisors,
  including actual PCIe passthrough support.
- **Broaden desktop correctness:** test ordinary applications, sustained composition,
  additional texture formats, resource ownership and concurrent GPU clients.
- **Strengthen reliability:** qualify crash recovery, repeated shutdown/relaunch,
  memory reclamation and operation across independently initialized host boots.
- **Extend physical display support:** Apple's embedded display core is being
  steered onto its DCN 3.02 path with DCN 3.1.5 register translation. Native PSP firmware
  startup, framebuffer fetch and native1080p layout work. Samsung HiDPI 120 Hz now has
  correct colors and audible HDMI audio; broader monitors, sleep/hotplug and HDCP
  remain unqualified. [120Hz evidence](findings/research/hdmi-hidpi120-20260924.md). [Port plan](findings/research/display-dcn315-port-20260917.md)
  · [HDMI audio plan](findings/research/hdmi-audio-passthrough-20260917.md).
- **Measure and release:** measure performance after correctness, publish a tested
  compatibility matrix, and produce reproducible builds with clear support limits.

The [roadmap](docs/ROADMAP.md) tracks acceptance criteria and remaining work.

## Get started with QEMU

1. Follow the [QEMU setup guide](examples/qemu/README.md). Copy the
   [base VM configuration](examples/qemu/macos-q35.cfg) into a private VM directory
   and supply your own macOS media, OpenCore disk, firmware and machine settings.
2. Boot the VM **without GPU passthrough first**. Enable Screen Sharing in macOS;
   the example forwards it to `127.0.0.1:5900` and SSH to `127.0.0.1:50922`.
3. Prepare the matching RaphaelGPU/Lilu builds, VBIOS and OpenCore properties
   described in the guide, then adapt the [Raphael VFIO overlay](examples/qemu/raphael-vfio.cfg).
4. Run accelerated sessions through the [supervised launch and recovery workflow](docs/running-an-experiment.md).
   Connect to guest Screen Sharing for the desktop.

Read [host safety](docs/host-safety.md) before GPU handoff: the GPU must first be
initialized by amdgpu, `power/control=on` must be pinned before VFIO access, and
vfio-pci must not be cycled back to amdgpu within the same host boot. The setup guide
covers the current QEMU SMC requirement and the complete matching configuration.
The example files alone do not configure or validate GPU recovery on a new host.

## Development

The driver can be cross-compiled on Linux; CI also builds experimental artifacts.
Follow the [build and packaging instructions](docs/releases.md) for pinned inputs
and installation requirements. Hardware-tested binary identities are recorded in
[status.md](status.md).

Run the host regression suite without GPU access:

```sh
python3 -B -m unittest discover -s tests
```

| Path | Contents |
|---|---|
| `src/` | RaphaelGPU Lilu plugin and supporting code |
| `tools/` | Build, configuration, experiment and recovery tools |
| `tests/` | Host regressions and guest graphics/video probes |
| `examples/qemu/` | General VM configuration and passthrough example |
| `docs/` | Setup, safety, architecture and roadmap |
| `findings/` | Reverse-engineering notes and recorded experiment evidence |

For implementation background, see the [GPU research](findings/GPU-RE.md),
[hardware notes](docs/hardware-notes.md) and [patch delivery](docs/patch-delivery.md).
Historical diagnoses and per-run details live in those documents rather than the
project overview. Continue development on `dev`; `main` contains the published
experimental snapshot. Publication does not imply a stable or fully qualified release.

## Licence

Original project code is [BSD-3-Clause](LICENSE). Firmware and third-party material
retain their own terms; see [third-party notices](THIRD_PARTY_NOTICES.md). The
[provenance audit](findings/research/licensing-audit-20260916.md) identifies exact
AMD sources for the TOC patterns and remaining SDK/distribution review items.

Candidate284's streaming work (2026-09-17) ended with CORE_PROBE_PASS, a clean
guest-request shutdown and authorizing recovery. The user reports stable 4K at 60 Hz streaming;
permanent 120Hz is the next step. [Evidence](findings/research/encoder-pipeline-20260917.md).

Candidate 302 (2026-09-23) establishes reversible CPU read/write access to the
reserved host DMCUB inbox on the same host boot. The first command passed full
readback but firmware did not consume it; HDMI output remains unqualified.
Capture and guest-request shutdown completed, recovery authorizes reuse.
See [live status](status.md).

### Same-boot recovery without a guest lease (2026-09-23)

Candidate 307's early panic was recovered on the same host boot using MODE2,
complete stable stopped-queue/SDMA scans and PSP ring teardown. The new schema-9
receipt permits one normal harness launch without borrowing an older lease.
This is a stopped, queue-free recovery result; active-queue recovery and physical
HDMI output remain separately qualified. Host regression: 1128 tests pass.

Current resize admission is physical640..3840 ×480..2160: explicit1× permits
odd dimensions;2× requires even dimensions. The selected lifetime policy persists
across helper updates and guest boots. Automatic DPI choice remains open.
