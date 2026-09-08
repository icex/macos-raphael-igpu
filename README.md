# macOS on an AMD Raphael iGPU

Reverse-engineering notes and tooling for making Apple's Navi 2x graphics stack bind to the
**integrated GPU of a Ryzen 9000-series (Raphael / Granite Ridge) desktop CPU**, passed through
with VFIO to a macOS Sequoia guest under QEMU/KVM.

Development and VM control run on Linux. Release CI compiles the x86_64 kext on a GitHub-hosted macOS runner.

## Roadmap

[GPU acceleration roadmap](docs/ROADMAP.md) tracks verified milestones, remaining gates,
host constraints and the next experiment. The linked execution plan replaces ad-hoc
iterations with immutable identities, explicit hypotheses and automatic result classification.
The [Raphael-versus-Navi23 Linux comparison](findings/raphael-vs-navi-linux.md) records which
IP blocks genuinely share an implementation, which only share an ISA generation, and the
evidence required before adding another compatibility patch.

## Status

**Experimental; full Metal acceleration is not working.** Hardware-tested **1.0.164**
executes native KIQ setup and proves the next failure is X6000's false second SDMA
object requesting global instance 1 when Raphael discovery exposes only instance 0.
`AMDHardware::startHWEngines` consequently returns 0 and the native Metal probe is
not eligible to submit work.

[Clean-run serial evidence](findings/metal-tests/20260908T052603Z-8dad7535/serial.txt)
and [automated verdict](findings/metal-tests/20260908T052603Z-8dad7535/result.json)
are retained. Later experimental builds 1.0.160/161 had incorrectly placed diagnostic
hooks and are excluded from conclusions about the hybrid-engine failure. A later
session also encountered an active KIQ that would not dequeue; recovery is unresolved.

| Stage | Verified state |
|---|---|
| VBIOS graft and OpenCore/Lilu delivery | Controller and plugin load before AMD initialization |
| PSP firmware loading | TOC/TMR established; successful IP firmware loads recorded |
| SMU | Apple's dummy backend avoids the host CPU's SMU mailbox |
| GC/TTL initialization and accelerator attach | Reached in the clean run |
| VRAM and initial GART | 256 MB allocator; native physical root `0x84fdfc001` verified |
| Command processor / KIQ | Three native setup stamps completed; RPTR caught WPTR |
| Hybrid engines | Instance-0 queues succeed; false instance-1 request returns status 4 |
| Metal | Metal 3 device enumerates; **zero completed compute/render submissions** |
| Physical display | DCN 3.1.5 path remains incomplete |
| Games | **Zero verified playable games**; [compatibility list](docs/supported-games.md) |
| Host stability | Three historical hard hangs; cause unresolved |

A percentage would obscure the remaining unknowns. Driver enumeration and queue setup
are milestones, not a measure of end-to-end rendering completeness.

The [1.0.164 experiment](findings/experiments/hybrid-002-164/notes.md) includes all
critical records, exact build identity and an orderly guest shutdown. Current
Hardware-tested **1.0.165** completed the one-instance SDMA repair and TTL initialization,
then exposed a null SDMA1 channel lookup in X6000's `createAccelChannels`.
**1.0.166** adds the exact guarded SDMA1-to-SDMA0 channel mapping used for one-engine
APUs; it is validated offline and awaits one fresh-boot experiment. Full Metal remains
unavailable. Published 1.0.159 remains the earlier research snapshot.

The repair is scoped by a byte-exact `rgpu,raphael-target` device property coupled to the
grafted VBIOS. The tooling verifies that identity before a physical experiment, so the
real Navi23 `0x73ff` PCI identity alone can never select Raphael-specific topology code.

See [release builds](docs/releases.md), [current research corrections](findings/GPU-RE.md),
and [historical bring-up notes](docs/bring-up-history.md).

### Host protection and automatic execution test

The iGPU passthrough has hard-hung the host. Its cause remains unresolved. `redeploy.sh`
defaults to a GPU-less VM; `--gpu` opts in to an experiment with an exposure timer. The iGPU
must have been initialized by amdgpu during the current boot. Early VFIO binding is refused,
and the former virgin-device override has been removed. Never cycle vfio-pci → amdgpu →
vfio-pci within a boot. Crash capture and a timer reduce exposure and improve diagnostics;
they cannot guarantee recovery from a fabric or CPU lockup.

Launch, serial capture, and the stop deadline are owned by user systemd services. The
deadline targets the full container ID and includes startup time. A GPU run requires a
positive `RGPU_MAX_SECONDS`; zero no longer disables its cap. Launch failure or loss of
serial capture stops that container. The launcher verifies connected serial capture and
the active deadline before reporting success. Serial capture also holds an idle/sleep
inhibitor for the VM's lifetime.

Bounded launches request ACPI powerdown 30 seconds before the container deadline.
The request gets at most 20 seconds; timeout forces a stop while the original timer
stays armed. In the GPU-less live test, ACPI did not shut macOS down and the fallback
was required. This does not yet provide verified driver teardown.

To request an earlier bounded shutdown:

```sh
python3 -B tools/vm-supervision.py shutdown --state /path/to/macos-vm/run/supervision.json
```

A standalone request rejects a stale StartedAt. Do not restart a supervised container
concurrently: supervision owns that entire container ID and still stops it at its
original deadline. Start a new experiment with a new container ID.

Prepare the native test with an already running GPU-less guest and Command Line Tools:

```sh
python3 -B tools/metal-test.py --vm-dir /path/to/macos-vm --prepare-only
```

Then, during an explicitly started, bounded GPU experiment:

```sh
python3 -B tools/metal-test.py --vm-dir /path/to/macos-vm
```

The runner uses the existing `gx` guest channel. It does not launch or rebind a GPU. A pass
requires the Navi23 Metal 3 device to complete three compute submissions, return all 196,608
expected integers, render and read back all 4,096 expected pixels, and exit successfully.
Each run has a fresh ID and saves its output and JSON verdict in `findings/metal-tests/`.
Do not issue other `gx` commands during a test. The GPU completion timeout is five seconds;
the probe also has a 45-second process deadline. Neither deadline can stop a host lockup.
Offscreen rendering does not prove that the separate DCN display path works or establish
long-term driver stability.

The result validator's regression tests run without hardware:

```sh
python3 -B -m unittest discover -s tests -v
```

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
             KiqAddresses.hpp   validated MQD/EOP address conversion
             GartAddresses.hpp  native physical framebuffer accounting
kext/        recorded experimental executable and Info.plist
tools/       mkrom.py           grafts the PSP directory + vram_info onto an APU ROM
             ocprop.py          edits OpenCore config.plist (device properties, boot-args)
             milestones.py      the patch ladder, re-verifies every pattern before deploying
             autorun.sh         walks the ladder unattended and classifies each verdict
             redeploy.sh        rebuild ROM, push to the ESP, restart, drain serial
             vm-supervision.py  persistent launch/capture and exact-container deadline
             metal-test.py      native Metal compute and render validation through gx
             gpu-bind.sh        amdgpu -> vfio-pci, with the runtime-PM workaround
             recover-igpu.sh    recovery after the vfio runtime-PM oops
             build-kext.sh      compile a Lilu plugin kext
             build-release.py   compile/package an experimental release
findings/    GPU-RE.md          the reverse-engineering write-up
             ip_discovery.txt   this chip's real IP block versions
tests/       metal_probe.m      GPU results checked against independent expected values
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
