# macOS on an AMD Raphael iGPU

Reverse-engineering notes and tooling for making Apple's Navi 2x graphics stack bind to the
**integrated GPU of a Ryzen 9000-series (Raphael / Granite Ridge) desktop CPU**, passed through
with VFIO to a macOS Sequoia guest under QEMU/KVM.

Development and VM control run on Linux; the kext is cross-compiled on Linux and also built in CI.

## Status

**Working: the macOS desktop composites on the Raphael iGPU through Metal.** Window rendering,
offscreen render/readback, buffer and texture copies, and the full managed/private/upload copy
matrix are exact (0 mismatches, 64×64 → 2048×2048).

Reaching that took three hardware-specific corrections, all carried by the kext:

| Problem | Cause | Fix |
|---|---|---|
| Graphics ring hung on the first desktop draw | Navi23-sized DPBB binning (`MAX_ALLOC_COUNT` 340 vs Raphael's 256-line cache) | `rgpunobin=1` |
| Whole desktop tile-permuted | Apple's HWLibs writes `SDMA0_GB_ADDR_CONFIG=0x444` (Navi23: 16 pipes/16 packers); Raphael is `0x42` (4 pipes) | `rgpusdmacfg=2` restores `0x42` |
| Managed textures wrong by one pipe-bank-xor bit at 64 px | Apple's *userspace* Metal driver applies a texture pipeBankXor that mismatches a 4-pipe config | `rgputexdiag=2` clears `enableTexturePipeBankXor` per process ([docs/patch-delivery.md](docs/patch-delivery.md)) |

**Known open:**

- **Display output is virtual only.** Apple's framebuffer has no DCN 3.1.5 code, so there is no
  physical HDMI/DP scanout. The desktop is reachable over Screen Sharing, not a monitor.
- **Rendering artifacts seen over a remote-desktop session are not diagnosed.** Sparse 8×8-pixel
  blocks appear over translucent/vibrancy regions. 8×8 is both one 256-byte GFX10 micro-tile *and*
  the JPEG DCT block size, and the only evidence so far is a host screenshot of a VNC client, so a
  GPU defect and a codec artifact are not yet distinguished. See [docs/ROADMAP.md](docs/ROADMAP.md).
- **Guest sleep/wake** resumes the GPU cleanly, but macOS ignores ACPI powerdown, so host-driven
  teardown is always a forced stop ([docs/host-safety.md](docs/host-safety.md)).
- **No games verified.** Nothing has been qualified beyond the desktop and the probe matrix.

The authoritative live state — current candidate identity and hashes, launch/reset counters, and
the blocking issue — is [status.md](status.md). Future work is in [docs/ROADMAP.md](docs/ROADMAP.md).

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
