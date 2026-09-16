# Stock QEMU with VirtualSMC

The stock-QEMU path keeps SMC compatibility in OpenCore and the guest. It requires
no QEMU source changes and no additional RaphaelGPU driver patch. Two fresh guest
boots pass on QEMU 10.1.2, macOS Sequoia 24G830 and VirtualSMC 1.3.7 on one host boot. [Evidence and exact identities](../findings/research/smc-opencore-handoff-20260916.md).
This does not qualify other hypervisors or remove the GPU passthrough prerequisites.

## Why ownership matters

QEMU's SMC device supplies boot-time key access but its tested stock implementation
lacks key-index enumeration. Native PerfPowerServices can loop on that missing
command. Merely enabling VirtualSMC can leave AppleSMC attached to the QEMU provider.

Keep the QEMU `isa-applesmc` device and your private key configuration. An exact
OpenCore ACPI patch marks only its SMC device as absent (`_STA=0`), while VirtualSMC
provides the service macOS attaches to. VirtualSMC implements enumeration and the
terminal error correctly. PerfPowerServices remains enabled and unmodified.

## Prepare OpenCore

1. Back up the working OpenCore boot disk and config. Obtain
   [VirtualSMC1.3.7](https://github.com/acidanthera/VirtualSMC/releases/tag/1.3.7),
   place `VirtualSMC.kext` in `EFI/OC/Kexts`, and add its usual `Kernel → Add` entry
   after enabled Lilu. The project's matching Lilu remains required for RaphaelGPU.
2. Obtain the VM's **unmodified DSDT**. OpenCore's DEBUG build with
   `Misc → Debug → SysReport=true` can dump ACPI tables to the ESP's `SysReport`
   directory; this feature is unavailable in RELEASE builds.
   [OpenCore configuration reference](https://github.com/acidanthera/OpenCorePkg/blob/master/Docs/Configuration.tex).
   Keep these reports private because they also contain machine identity data.
3. From this repository, prepare a separate config:

   ```sh
   python3 tools/prepare-smc-handoff.py \
     --config /path/to/EFI/OC/config.plist \
     --dsdt /path/to/original/DSDT.aml \
     --output /path/to/config-stock-qemu.plist
   ```

   The tool enables the existing VirtualSMC entry, adds `vsmcgen=2`, and appends a
   DSDT-only patch with Count1. It requires exactly one matching QEMU SMC prefix,
   refuses conflicting VirtualSMC settings, and never overwrites the input config.
   It does not install the bundle or launch the VM. Keep other SMC emulators disabled.
4. Review the diff and validate the output with `ocvalidate` from your matching
   OpenCore release, then install it as the boot disk's `EFI/OC/config.plist`.
   Keep QEMU's SMC device in place. No change to `AppleSmcIo` is required by the
   tested configuration, where it remains false.
5. Use the [supervised VM workflow](running-an-experiment.md). Check the provider
   and CPU behavior below before adopting this configuration as your baseline.

The tested patch matches the bytes for `SMC_`, `_HID=APP0001`, and `_STA=0x0b`,
and changes only the status byte. Do not broaden its masks or disable other ACPI
devices to make a different DSDT match. Repeat preparation against a fresh original
DSDT after a QEMU/firmware change; matching bytes alone do not qualify a new build.

## Verify in macOS

Compile and run the bounded provider probe in the guest:

```sh
clang -fobjc-arc -O2 smc_provider_probe.m \
  -framework Foundation -framework IOKit -o smc-provider-probe
./smc-provider-probe VirtualSMC
ps -axo pid,pcpu,time,comm | grep '[P]erfPowerServices'
```

The source is [tests/smc_provider_probe.m](../tests/smc_provider_probe.m). Require
`passed:true`, provider `VirtualSMC`, a nonzero key count, and end result `0xb8`.
The tested configuration enumerates69 keys and rejects out-of-range indices;
other configurations may legitimately expose a different number. No key values
are read by the probe. Observe CPU after startup and after graphics/video work,
then verify a fresh guest boot and complete shutdown/recovery.

This verifies SMC ownership and the reproduced CPU-loop fix. VirtualSMC's generic
keys do not establish accurate physical sensor telemetry or power management.
Independent host boots and broader macOS/QEMU version support remain open.

## Rollback

After supervised shutdown and verified GPU recovery, restore the saved OpenCore
boot disk/config and select the prior tested QEMU build as a pair. The previous
[QEMU enumeration patch](../patches/qemu/10.1.2-applesmc-key-enumeration.patch)
remains an alternative with its original configuration. Do not modify boot media
while its guest is running.

## Tested compatibility

| Configuration | Evidence |
|---|---|
| Stock QEMU10.1.2 + Sequoia24G830 + VirtualSMC1.3.7/gen2 + exact ACPI patch | Two guest boots on one host boot: provider/enumeration, low CPU, Metal, codecs, remote desktop and clean recovery pass their scoped checks. |
| Previous patched QEMU10.1.2 + original OpenCore config | Eleven measured guest boots with low PerfPowerServices CPU; retained rollback baseline. |
| Other QEMU/macOS versions or independently initialized hosts | Not yet qualified. |
| VirtualBox / other hypervisors | Not tested; physical PCIe exposure and recovery support must be established separately. |
