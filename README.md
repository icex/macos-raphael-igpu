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

As of **2026-09-16**, candidate **1.0.280** runs an accelerated desktop through
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
| Physical HDMI/DisplayPort | Not yet working as a qualified display path; use guest Screen Sharing. |

The tested baseline is **macOS Sequoia build 24G830** with a matching driver,
Lilu, OpenCore configuration and grafted VBIOS. Stock QEMU 10.1.2 now works with
[VirtualSMC and an OpenCore SMC ownership patch](docs/stock-qemu-smc.md), keeping
PerfPowerServices CPU usage normal without modifying QEMU. Other hypervisors and
arbitrary macOS updates are not validated.
Performance, games and general application compatibility are not yet qualified.

See [live status and evidence](status.md) for exact tested builds and the scope of
each result. A successful build or individual probe does not establish full desktop
readiness.

## Goals and next steps

- **Qualify full 4K Screen Sharing:** the isolated Retina helper now selects a crisp
  1920×1080 logical desktop with 3840×2160 backing at nominal 60 Hz. Continue
  validating reboot/login behavior, capture transport, delivered frame rate and
  latency independently of mode timing. A prior mixed 90/120 Hz sequence produced
  a user-black desktop and was cleanly restored; those requested rates are not
  proven modes.
- **Qualify remote streaming:** Sunshine offers hardware H.264 and HEVC Main8.
  The H.264 + Moonlight-Qt comparison reached user-reported 4K60, falling to about
  40 FPS over transparent Safari; a server trace averages about 55 submissions/s
  with occasional long calls. HEVC remains enabled at the user’s request. Client and
  codec changed together, so their individual effects remain unproven. Sustained
  frame delivery and input latency remain open. A live capture-buffer optimization removes CPU locks and retains a clear picture,
  but motion-triggered encoder stalls remain across the desktop; it is not a complete fix. [Measurements](findings/research/moonlight-qt-h264-20260916.md)
  · [Setup, LAN access and firewall rules](docs/sunshine.md)
  · [Current investigation and next steps](findings/research/streaming-handoff-20260916.md).
- **Broaden portability:** extend the working stock-QEMU/OpenCore setup across
  host boots and supported versions, and document requirements for other hypervisors,
  including actual PCIe passthrough support.
- **Broaden desktop correctness:** test ordinary applications, sustained composition,
  additional texture formats, resource ownership and concurrent GPU clients.
- **Strengthen reliability:** qualify crash recovery, repeated shutdown/relaunch,
  memory reclamation and operation across independently initialized host boots.
- **Enable physical displays:** bring up the Raphael display engine, then validate
  modes, reconnection and higher resolutions.
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

Candidate282's streaming investigation ended with valid capture, a clean
guest-request shutdown and authorizing recovery. Motion performance remains
open; the final120FPS-request/60Hz-display trace requires a matching4K60 control.
[Final evidence](findings/research/safari-motion-20260916.json).
