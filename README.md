# macOS on an AMD Raphael iGPU

Reverse-engineering notes and tooling for making Apple's Navi 2x graphics stack bind to the
**integrated GPU of a Ryzen 9000-series (Raphael / Granite Ridge) desktop CPU**, passed through
with VFIO to a macOS Sequoia guest under QEMU/KVM.

No Mac hardware, no macOS build host: everything here is produced and driven from Linux.

## Status

TTL's SWIP clients initialise in sequence; the failure has moved through three of them.

| stage | state |
|---|---|
| VBIOS / ATOM tables | **solved** — the controller starts and brands itself `AMD Radeon Navi23`, 512 MB, 128-bit GDDR6 |
| patch delivery | **solved** — OpenCore injects Lilu + this plugin into the boot collection, so every patch lands before `start()` |
| SWIP `BGM` | **complete** — all of `bgm_create`, VBIOS init, GDDR6 memory training |
| SWIP `GVM` | **complete** — UMC, VM, HDP and ATHUB all resolve handlers |
| SWIP `PSP` | **current blocker** — `PSP init/power-up failed` at `EVENT__SW_INIT` |

Nothing here adds new driver code. Every change either points Apple's stack at an
implementation it already ships for a near-identical IP version, or supplies a device
identity that a real Navi 23 would report. `findings/GPU-RE.md` is the full write-up,
including the measurement traps that produced wrong conclusions along the way.

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

Full write-up with every VMA: [`findings/GPU-RE.md`](findings/GPU-RE.md).

## Layout

```
src/         RaphaelGPU.cpp     the Lilu plugin (patch table + boot-arg mask)
kext/        prebuilt RaphaelGPU.kext
tools/       mkrom.py           grafts the PSP directory + vram_info onto an APU ROM
             ocprop.py          edits OpenCore config.plist (device properties, boot-args)
             milestones.py      the patch ladder, re-verifies every pattern before deploying
             autorun.sh         walks the ladder unattended and classifies each verdict
             redeploy.sh        rebuild ROM, push to the ESP, restart, drain serial
             gpu-bind.sh        amdgpu -> vfio-pci, with the runtime-PM workaround
             recover-igpu.sh    recovery after the vfio runtime-PM oops
             build-kext.sh      cross-build a Lilu plugin kext on Linux
findings/    GPU-RE.md          the reverse-engineering write-up
             ip_discovery.txt   this chip's real IP block versions
```

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

## Measurement

The AMD kexts log through **two** channels and you need both:

- `os_log` — read with `log show --predicate 'senderImagePath CONTAINS "AMD"'`
- `kprintf` — reaches the serial port only with `DB_KPRT` set, i.e. `debug=0x108` in boot-args

Reading only serial produces a badly wrong picture: it looks like nothing beyond the GPU wrangler
runs, when in fact the whole stack loads.

Static analysis needs the **Kernel Debug Kit** for the exact build. On an installed system every
AMD kext bundle is a stub, with the code prelinked into `SystemKernelExtensions.kc`.

## Licence / provenance

Original work. Technique is informed by the published behaviour of Apple's shipping binaries and
by Linux's `amdgpu`; no code is copied from ChefKiss projects, whose licence terms differ.
