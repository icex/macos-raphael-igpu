# QEMU setup for normal VM use

These editable files describe a normal VM, with an optional Raphael passthrough
configuration. They are based on the project's Docker-OSX/QEMU launcher topology,
but do not require Docker or hard-code a developer's disk paths, credentials,
OpenCore identity or container image. They are configuration examples, not a macOS
installer or a replacement for the GPU lifecycle supervisor.

## 1. Prepare the VM

Install QEMU/KVM with user networking, an OVMF firmware pair, and access to `/dev/kvm`
for your regular user. Provide your own macOS install/recovery media and an OpenCore
boot disk configured for your AMD CPU and target macOS release. The tested driver
baseline is Sequoia build24G830; arbitrary macOS updates are not qualified.

Create a private VM directory. Copy `macos-q35.cfg` there, along with a matching
`OVMF_CODE.fd` and **a private copy** of its matching `OVMF_VARS.fd`, your
`OpenCore.qcow2` boot disk and `macos.qcow2` system disk. To create an empty disk:

```sh
qemu-img create -f qcow2 macos.qcow2 128G
chmod 600 macos-q35.cfg
```

Edit the config to match your filenames/formats, memory, CPU count, unique MAC
address and your AppleSMC key. The key placeholder deliberately cannot boot macOS;
do not commit a filled-in private config. Keep sockets × cores × threads equal to
cpus. OpenCore platform identifiers and AMD kernel patches belong in your own
OpenCore configuration and are not supplied by this graphics project.

For a fresh installation, attach your recovery/install disk on another free AHCI
port (for example `sata.3`) through an additional `drive`/`ide-hd` pair with the
correct image format; select it in OpenCore. The command below also works with an
already installed system.

## 2. Boot without passthrough first

From the VM directory, with no other process using these disks:

```sh
qemu-system-x86_64 -nodefaults -smbios type=2 \
  -cpu Haswell-noTSX,kvm=on,vendor=GenuineIntel,+invtsc,vmware-cpuid-freq=on \
  -readconfig macos-q35.cfg \
  -vga vmware -display none -vnc 127.0.0.1:1
```

Connect a VNC viewer to `127.0.0.1:5901` for the firmware/installer console. Inside
macOS, enable **System Settings → General → Sharing → Screen Sharing** and, if
wanted, Remote Login. Guest Screen Sharing is forwarded to `127.0.0.1:5900`; SSH is
`ssh -p 50922 YOUR_GUEST_USER@127.0.0.1`. These are separate from QEMU's console.
For access from another computer, use an SSH tunnel to the Linux host rather than
changing the loopback bindings. Choose Shut Down inside macOS before closing QEMU
or modifying disks. Never open the same writable VM disk in two QEMU processes.

## 3. Prepare Raphael acceleration

The accelerated setup needs more than PCI spoofing:

- Stock QEMU10.1.2 works with [VirtualSMC1.3.7 and the OpenCore SMC handoff](../../docs/stock-qemu-smc.md).
  Keep QEMU's SMC device for boot-time access; the exact ACPI patch lets VirtualSMC
  own the native service and prevents the reproduced PerfPowerServices CPU loop.
  Prepare and verify this configuration using the linked guide. The older QEMU
  enumeration patch remains an alternative with its original boot configuration.
- Build RaphaelGPU with the pinned inputs in [release instructions](../../docs/releases.md).
  Use the matching Lilu build, including this project's headless-init integration.
  Put both bundles in the OpenCore ESP's `EFI/OC/Kexts` and enable Lilu before
  RaphaelGPU in `Kernel → Add`. See [delivery details](../../docs/patch-delivery.md).
- Dump your own iGPU VBIOS while native amdgpu owns the device, then graft it with
  `python3 tools/mkrom.py -i YOUR_VBIOS.rom -o gpu-patched.rom --total 0xB600`.
  Inject that same ROM as `ATY,bin_image` at `PciRoot(0x0)/Pci(0x6,0x0)` using
  `tools/ocprop.py`; supplying QEMU `romfile` alone is insufficient.
- Use the complete matching functional settings from [metal-127](../../experiments/metal-127.json),
  not just `-lilubetaall`, `rgpunobin=1`, `rgpusdmacfg=2` and `rgputexdiag=2`.
  The card records additional memory, queue, firmware and lifecycle prerequisites.
  Do not combine arbitrary kext versions and historical argument lists.

Read [host safety](../../docs/host-safety.md) before the handoff. Native amdgpu must
initialize the GPU during this host boot; pin `power/control=on` before VFIO opens
it, verify the device/IOMMU group and arrange the one-way handoff with appropriate
host permissions. Do not cycle vfio-pci back to amdgpu within a boot. These examples
perform no privileged setup and do not change PCI bindings.

Copy `raphael-vfio.cfg` and replace `REPLACE_WITH_GPU_BDF` with your verified device.
The accelerated QEMU topology adds `-readconfig raphael-vfio.cfg`, replaces
`-vga vmware` with `-vga none`, and keeps `-display none`; omit QEMU's VNC console.
Keep the endpoint directly on `pcie.0` at0x6. Use **guest Screen Sharing on port5900**;
Samsung HDMI picture and audio now work with the additional
[candidate330 HiDPI120/audio configuration](../../docs/hdmi-status.md); DisplayPort is untested. A black QEMU console in this mode
is expected, not evidence that the guest failed to boot.

## 4. Own launch, shutdown and recovery

An ordinary macOS desktop session can run within the project's supervised
interactive window; the safety mechanisms are needed for daily use too. On the
validated development host, use `tools/cycle.py` with the matching candidate/card,
verified build identities and deliberate environment pins, as described in
[running a VM](../../docs/running-an-experiment.md). The wrapper owns the container,
serial capture, positive deadline (up to6000 seconds), identity checks and cleanup.
Do not replace that route with an unsupervised raw VFIO QEMU command on this host.

On a different host, adapting the config does **not** qualify its reset/recovery
path. Establish the same launch ownership, bounded lifetime, capture-failure and
host-fault aborts, and verified post-exit cleanup before adopting passthrough as
normal use. A timer or successful QEMU exit alone is not a GPU recovery receipt.
Use the current boot's authenticated recovery and fresh MODE2 path for same-boot
reuse; do not assume PCI FLR or a driver rebind performs that recovery.

The base config is suitable for normal installation/boot and contains no test
workload. The VFIO overlay documents the tested topology; it does not itself grant
GPU admission or claim independent-host validation. [Current results](../../status.md).

Validation: the base config initializes under paused QEMU TCG with temporary dummy
disks/SMC data and exits through QMP without errors. This checks config/device
syntax, not a new macOS installation or GPU passthrough. The [stock-QEMU SMC handoff](../../docs/stock-qemu-smc.md) has separate native
boot, provider, CPU, Metal, codec and lifecycle evidence; the base-config syntax
check alone does not establish those results.

## Optional Retina and Moonlight streaming

For1080p HiDPI backed by4K pixels and a hardware-only VideoToolbox Sunshine setup,
see the [Sunshine guide](../../docs/sunshine.md). It includes the additional QEMU
TCP/UDP forwarding entries for LAN access. The tested desktop timing is60Hz;
90/120FPS client requests and actual delivered frames need separate measurement.
