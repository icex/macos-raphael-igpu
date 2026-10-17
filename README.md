# RaphaelGPU

Experimental macOS graphics acceleration for the **AMD Raphael / Granite Ridge
integrated GPU**, using Apple's native AMD graphics stack through a Lilu plugin.
The current development platform is a macOS Sequoia/Tahoe VM on Linux with QEMU/KVM
and VFIO GPU passthrough.

Our goal is a usable, correctly rendered Metal desktop, hardware video acceleration,
physical display output, and reliable shutdown and recovery. Development is active
on **`dev`**; this is not yet a generally supported driver release.

[Current status](status.md) · [Roadmap](docs/ROADMAP.md) ·
[QEMU setup](examples/qemu/README.md) · [Build instructions](docs/releases.md)

The local desktop also has [private SMB file sharing](docs/file-sharing.md):
the Linux-mounted SSD and Nextcloud folder are available read/write in Finder,
using a separate login and encrypted SMB3 over the VM's private connection.

## Current status

**Desktop default: macOS 26.7.1 / 25G241 with release 519 and QEMU pins v20.** The original
15.8.1 / 24H32 disk is retained locally at `~/macos-vm/rollback/`.

**2026-10-17: desktop sleep inhibition follows the VM session.** The shortcut
starts its inhibitor before preflight and releases it after shutdown/recovery
or a failed start. The helper container no longer restarts at host boot;
closing the VM leaves host sleep available.
The desktop shortcut starts an ordinary session without host regression tests
or automatic guest Metal workloads. It has no session expiry or scheduled
shutdown: it stays running until the user closes or shuts down macOS. The USB menu can redirect an external
drive to macOS; grant user access to its enclosure and unmount it on Linux first.
The attached Intel USB SSD's existing encrypted APFS volume mounted successfully
after the owner unlocked it in macOS.

**2026-10-15: VRAM no longer fills up; the QEMU window follows the display.** The
accelerator keeps freed VRAM allocations in a second, unlimited cache that only the sleep path
empties; in real use it reached 3.2 GB and window allocations failed. Release 512 releases that
cache through Apple's own routine after an allocation failure or every 30 s: a stress run kept it
near 350 MB with 2.5 GB free and no failures. QEMU's window now snaps to the display's aspect
when a resize settles, following whichever edge was dragged (user-confirmed).
The tested QEMU v20 image also fits the guest resolution into the host monitor's
work area when the desktop mode appears and keeps a visible host pointer; the
user confirmed both at 5K/120. Release 515's 290-second tone and foreground
CoreAudio captures stayed continuous through automated 4K/120 stress. A slow
manual QEMU-window resize can still halt guest-wide audio. Safari/YouTube can
stutter during fast page scrolling; the same video played without stutter in
Safari Picture in Picture and Brave. The user classified these audio symptoms
as lower priority. [Audio evidence](findings/research/audio-dropout-20261015.md).

**2026-10-14: window drags are smooth at 120 Hz.** The scanout copy into QEMU's window missed
macOS's rotated buffers and delivered 9 fps while macOS presented 120; release 509 copies every
flipped frame (119.9 fps). Clipboard and the QEMU USB menu work on the iGPU display (507).

**2026-10-15: guest-memory teardown is guarded in release 515.** The unowned
iGPU's display interrupt ring kept writing after QEMU exited; matching 32-byte
IH records appeared in host data and the earlier TCG core. Release 515 gives
QEMU an independent VFIO descriptor guard. It stops IH, display writes, GC and
SDMA and proves them stationary/idle before guest RAM is unmapped, including
after QEMU/container death. Ordinary queue retirement cannot run after this
pre-unmap halt, so the supervised runner uses a separate MODE2/no-queue recovery
receipt. Two native sessions and two identity-checked QEMU deaths passed the
guard and recovery path. The installed desktop launcher passed Metal readbacks,
a readable QEMU window, native guest shutdown and authorizing recovery. Two
post-crash plain Tahoe boots passed remap/page-query stress, image hashes and
native exit. A historically overwritten symbolication cache was quarantined
after a stopped-disk backup and clone trial. The earlier `heap` pmap panic's
precise cause remains unproved; these are bounded stability results, not a
guarantee against every corruption source.
[Evidence](findings/research/guest-memory-corruption-20261015.md).

**2026-10-14: the Tahoe desktop freeze is fixed.** Apple's Metal driver configures
Navi2x-sized parameter-cache oversubscription. On Raphael's 256-line parameter cache this
deadlocked attribute-heavy draws, such as Weather's map and the Memoji picker, and the
resulting GPU restart storms also wedged hardware video. The driver now clears that setting
dynamically in every Metal client. A 40-minute soak with Weather, Maps, Chess, Photos and
hardware HEVC/H.264 encoding ran with no GPU hang and ended in ordinary recovery.
[Evidence](findings/research/tahoe-gfx-deadlock-20261014.md).

One driver discovers kernel sites and active Metal/VCN patches from the current
images, without a per-build UUID or address list. A fresh GPU-less inspection
binds compatibility evidence to the selected disk before GPU exposure; unknown
or ambiguous code/ABI contracts refuse launch. Both latest tested releases pass
61.3 million readback pixels, moving window self-captures and native shutdown/
recovery. 15.8.1 presents at 60–120 fps according to its selected display mode;
unlocked Tahoe desktop presentation remains unqualified.

Tahoe interactive mode check: 3840×2160 at 60 Hz is usable after restoring
logical 1920×1080. Release 519 also copies the logical 2048×1152 / physical
4096×2304 scaled mode at 120 Hz, and returns to 5K/120. It reads the source
viewports across four display pipes, validates their coverage and pitch, and
keeps the existing copy bounds checks. Two supervised runs passed Metal,
continuous scaled frames, normal guest shutdown and stopped-device recovery;
the installed launcher also passed its normal start/stop path.
[Scaled-mode evidence](findings/research/scaled-mode-copy-20261015.md).

| Matched GPU workload | macOS 15.8.1 | macOS 26.7.1 |
| --- | ---: | ---: |
| Offscreen render, 1280×1024 / 20,001 triangles | 2,762 fps | 2,785 fps |
| FP32 compute | 283.50 GFLOP/s | 283.56 GFLOP/s |

Same hardware, driver, benchmark binary and 60 Hz background display; ten
measured samples after warmup, with output correctness checks. These are GPU
workload throughput figures, not desktop/game FPS or peak compute claims.
[Benchmark and raw samples](findings/research/update-portability-20261013/performance-latest.md).

The installed shortcut retains clipboard, USB redirection and audio. Host
safety, identity, capture, immutable recovery and same-boot reuse checks remain
mandatory. A guest panic was observed before one benchmark; its cause remains
unproven, and complete recovery plus a bounded retry passed. This milestone does
not establish full-field 4K120, physical HDMI, every codec or crash/fresh-boot
qualification. [Latest release evidence](findings/research/update-portability-20261013/latest-release-matrix.md).

Superseded progress summaries are retained in the
[progress archive](findings/research/status-archives/20261013-readme-progress.md).

## Goals and next steps

- Broaden memory and desktop-launcher qualification across independently
  initialized host boots. Retain synchronized captures if the known Safari
  scroll or slow host-window resize audio issues are revisited.
- Qualify unlocked Tahoe desktop presentation beyond the verified 40-minute soak.
- Broaden texture formats, resource ownership and concurrent GPU client coverage.
- Investigate the recorded guest panic and qualify crash cleanup and operation
  across independently initialized host boots.
- Qualify full-field 4K120 capture, delivery latency and remote streaming.
- Continue physical display, sleep/hotplug, HDMI audio and codec qualification
  using configuration-specific evidence rather than earlier partial results.
- Maintain dynamic compatibility as Apple changes private code/ABI contracts,
  with reproducible builds and explicit support limits.

The [roadmap](docs/ROADMAP.md) retains acceptance criteria and historical evidence.

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
HDMI output remain separately qualified. Host regression: 1630 tests pass (8 skipped).

Current resize admission is physical640..3840 ×480..2160: explicit1× permits
odd dimensions;2× requires even dimensions. The selected lifetime policy persists
across helper updates and guest boots. Automatic DPI choice remains open.

Published research has been sanitized: personal paths and host/network identifiers
are examples, and private OpenCore identities and browser captures are excluded.
See [publication privacy](docs/publication-privacy.md).
