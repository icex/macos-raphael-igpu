# macOS on an AMD Raphael iGPU

Reverse-engineering notes and tooling for making Apple's Navi 2x graphics stack bind to the
**integrated GPU of a Ryzen 9000-series (Raphael / Granite Ridge) desktop CPU**, passed through
with VFIO to a macOS Sequoia guest under QEMU/KVM.

Development and VM control run on Linux; the kext is cross-compiled on Linux and also built in CI.

## Status — 2026-09-16

**Candidate 280 renders the remote macOS desktop with the reproduced transparency
corruption fixed.** This remains an experimental driver: full desktop qualification,
physical HDMI/DP output, performance and game compatibility are still open.

| Area | Verified result | Evidence |
|---|---|---|
| Transparency corruption | Native render-target expansion fixes green/smeared feedback pixels; controlled patch/restore comparison and clean raw RFB captures | [Visual fix](findings/research/feedback-decompression-20260916.md) |
| Hardware video | H.264 decode/encode and HEVC Main8 decode/encode pass; Main10 decode matches software across 32 frames at 720p/1080p | [HEVC](findings/research/hevc-decode-appleGVA-20260916.md), [Main10](findings/research/main10-qualification-20260916.md) |
| PerfPowerServices | QEMU AppleSMC key enumeration fixed; 0.0% CPU on ten measured guest boots on one host boot | [SMC fix](findings/research/perfpower-smc-enumeration-20260916.md) |
| Memory and synchronization | Longer address reuse, 192 MiB allocations, untracked GPU fences and cross-queue events pass CPU oracles | [Memory/GPU tests](findings/research/address-reclaim-desktop-20260916.md) |
| Depth/stencil and MSAA | 128 cases, 49,625,792 correct pixels at 1×/4× samples | [Depth/stencil](findings/research/depth-stencil-20260916.md) |
| Cross-process IOSurface | 32 bidirectional GPU-copy rounds, 49,363,648 correct pixels; host completion orders transfers | [IOSurface](findings/research/iosurface-process-20260916.md) |
| Cleanup and relaunch | Clean guest-request shutdown/recovery passes; one abnormal QEMU closure followed by recovery and successful desktop relaunch | [Lifecycle](findings/research/supervised-qemu-closure-result-20260916.md) |

The abnormal-closure run retains an INVALID capture verdict for truncated terminal
serial data; the independent recovery/relaunch result does not erase that verdict.
Independent host boots, guest-panic and unavailable-command-channel recovery remain
unqualified. Physical output is unqualified; Screen Sharing is the tested display path.
No games have been verified. Hardware HEVC Main10 encoding is unavailable in the
native advertised profile set, and explicit decoder GPU-ID selection remains limited;
automatic required-hardware decoding works.

The graphics baseline retains `rgpunobin=1`, `rgpusdmacfg=2` and `rgputexdiag=2`:
these handle Navi23 binning limits, Raphael's SDMA address layout, userspace texture
addressing and the guarded feedback-expansion fix. Use the exact experiment card and
build identities, not these arguments alone, to reproduce a run.

[status.md](status.md) contains current host/guest state, tested binary hashes and the
next experiment. [docs/ROADMAP.md](docs/ROADMAP.md) tracks scoped acceptance and open
work, including GPU-only cross-process event sharing through XPC and source-guided
display initialization. Work is integrated on `dev`; candidate branches retain
experiment history. No `main` merge or push before full desktop acceptance.

## The three things worth knowing

**1. An APU's VBIOS is missing exactly two ATOM data tables.** Apple's driver wants a PSP
directory (master-data-table index 9) and a `vram_info` (index 28); an APU ROM has neither,
because its security processor lives in the SoC. Both can be synthesised — the parsers are
undemanding, and `populateMemoryConfig` fails only on a *zero* memory type or width, with no enum
validation at all. Apple never reads `ATOM_ROM_HEADER.pspdirtableoffset`, which is a tempting
red herring.

**2. Delivery must be the `ATY,bin_image` device property.** `readAtomBios` tries that property
first and the PCI expansion ROM second — and the ROM path bails when config offset 0x30 reads 0,
which is always the case under OVMF because EDK2 releases option-ROM BARs after enumeration.
There is a hard **64 KiB ceiling** on anything Apple will look at, so a real 1 MB discrete ROM
cannot be injected even in principle.

**3. HWLibs dispatches on the silicon's real IP-discovery versions, not the spoofed PCI id.**
That is why a device-id spoof gets you a long way and then stops dead. Most of the gates turn out
to be a single version field pointed at an implementation Apple already ships.

Full write-up with every VMA: [`findings/GPU-RE.md`](findings/GPU-RE.md). Transferable
bring-up knowledge for other AMD iGPUs: [`docs/hardware-notes.md`](docs/hardware-notes.md).

## Two traps that cost real time

**Passing this iGPU to QEMU NULL-derefs the host kernel** unless the device is pinned awake
first. Opening a runtime-suspended device with vfio-pci hits
`vfio_pci_core_runtime_resume -> down_write` on kernel 7.2.x. It presents as a *guest* hang —
QEMU becomes a zombie, the container still reports "Up", the guest emits zero serial bytes — and
it is unrecoverable without a reboot, because `power/runtime_status` sticks at `resuming` and any
operation needing the device's PM lock then blocks uninterruptibly. Pin `power/control=on` before
anything opens it; `gpu-bind.sh` does this and a udev rule enforces it at boot.

**Lilu silently disables itself on an OS newer than it knows.** On Sequoia it logs
`automatically disabling on an unsupported operating system` and exits, taking every plugin with
it. `-lilubetaall` is required. Worth checking early, because it makes WhateverGreen and AppleALC
inert too.

## Documentation

| Document | Purpose |
|---|---|
| [status.md](status.md) | Live state: candidate identity, counters, blocking issue |
| [docs/ROADMAP.md](docs/ROADMAP.md) | What is planned next, and why |
| [docs/host-safety.md](docs/host-safety.md) | Non-negotiable host rules and recovery procedures |
| [docs/running-an-experiment.md](docs/running-an-experiment.md) | The change → test → run → classify loop |
| [docs/releases.md](docs/releases.md) | Cross-build, CI, release packaging |
| [docs/patch-delivery.md](docs/patch-delivery.md) | How the kext reaches the boot KC; why Lilu's user patcher cannot work on Sequoia |
| [docs/hardware-notes.md](docs/hardware-notes.md) | Transferable AMD iGPU bring-up knowledge |
| [docs/critical-replay-v2.md](docs/critical-replay-v2.md) | Serial diagnostics wire format |
| [findings/GPU-RE.md](findings/GPU-RE.md) | The reverse-engineering write-up |

## Layout

```
src/          RaphaelGPU.cpp    the Lilu plugin: patch table, boot-arg mask, hooks
              *.hpp             address arithmetic, diagnostics, replay, texture parsing
kext/         recorded experimental executable and Info.plist
tools/        build-kext.sh     cross-compile the Lilu plugin kext on Linux
              build-release.py  compile/package an experimental release with pinned identity
              stage-candidate.py  validate a candidate's contract and stage its boot disk
              experiment.py     prepare and run one bounded GPU experiment
              classify-run.py   turn a run's artifacts into a verdict
              vm-supervision.py launch/capture with an exact-container deadline
              smu-mode2-reset.py  same-boot GPU reset, so relaunch needs no reboot
              gpu-bind.sh       amdgpu -> vfio-pci, with the runtime-PM workaround
              recover-igpu.sh   recovery after the vfio runtime-PM oops
              vfio-recover.py   rootless GC/SDMA/PSP teardown and reuse receipt
              mkrom.py          grafts the PSP directory + vram_info onto an APU ROM
              ocprop.py         edits OpenCore config.plist (device properties, boot-args)
              agent-server.py   guest command relay with reachability telemetry
tests/        desktop_metal_probe.m  the in-guest Metal probe
              test_*.py/.cpp    host-side regression suite (no hardware required)
findings/     GPU-RE.md         the reverse-engineering write-up
              research/         per-topic investigations and evidence
build-support/  pinned Lilu build inputs and the headless-init patch
```

## Measurement

The AMD kexts log through **two** channels and you need both:

- `os_log` — read with `log show --predicate 'senderImagePath CONTAINS "AMD"'`
- `kprintf` — reaches the serial port only with `DB_KPRT` set, i.e. `debug=0x108` in boot-args

Reading only serial produces a badly wrong picture: it looks like nothing beyond the GPU wrangler
runs, when in fact the whole stack loads.

Static analysis needs the **Kernel Debug Kit** for the exact build. On an installed system every
AMD kext bundle is a stub, with the code prelinked into `SystemKernelExtensions.kc`.

The host-side regression suite runs without hardware:

```sh
python3 -B -m unittest discover -s tests
```

## Licence / provenance

Original work. Technique is informed by the published behaviour of Apple's shipping binaries and
by Linux's `amdgpu`; no code is copied from ChefKiss projects, whose licence terms differ.
