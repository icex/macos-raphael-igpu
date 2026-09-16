# Stock-QEMU SMC ownership investigation

## Hypothesis and source basis

VirtualSMC implements bounded key enumeration; the unresolved question is who owns
AppleSMC when QEMU also exposes an SMC device. `VirtualSMC::devicesPresent` refuses
startup if another SMC already has an AppleSMC child. The proposed OpenCore patch
sets only QEMU SMC's ACPI `_STA` byte from0x0b to0, leaving the emulated device and
its boot-time port reads available. Enable VirtualSMC and select documented gen2.
Do not patch PerfPowerServices, falsify its return codes or disable the service.

VirtualSMC release1.3.7 source is `dbd1ae1ee5adc7f2debd9311bf28ca2902d1bfcc`.
Its ownership/protocol implementation is identical to the initially reviewed
`b15991dd87e36a102bf159ea56490e3126245590` for kern_vsmc, kern_prov, kern_keystore,
kern_pmio and kern_mmio. Sources:
[ownership and virtual port callbacks](https://github.com/acidanthera/VirtualSMC/blob/dbd1ae1ee5adc7f2debd9311bf28ca2902d1bfcc/VirtualSMC/kern_vsmc.cpp),
[enumeration](https://github.com/acidanthera/VirtualSMC/blob/dbd1ae1ee5adc7f2debd9311bf28ca2902d1bfcc/VirtualSMC/kern_keystore.cpp),
[QEMU AML](https://gitlab.com/qemu-project/qemu/-/blob/v10.1.2/hw/misc/applesmc.c).
The [upstream ownership/boot report](https://github.com/acidanthera/bugtracker/issues/2513)
motivates retaining the QEMU device; it does not prove this configuration works.

## Offline result

Paused stock QEMU10.1.2 with dummy SMC key, no disks, KVM or VFIO exposes one exact
SMC prefix in its generated DSDT. `tools/prepare-smc-handoff.py` matches that prefix
once, emits a private OpenCore config and refuses missing/ambiguous AML, provider
conflicts, disabled/misordered Lilu, or repeated preparation. It does not install
or launch anything. Five focused host tests pass. These checks prove preparation,
not native ACPI matching or successful macOS boot.

DSDT length8254, SHA256 `f56eb1c8fb4883396d8a8267bb655fb75c5e167d2c9af326cace0b472b6baab9`.
Exact prefix `534d435f085f4849440c06100001085f5354410a0b`; replacement changes
only its last byte to00. ACPI patch is DSDT-only, Count1, with no masks.

VirtualSMC release ZIP SHA256 `12f1d379969f926306fa92d94ddbf33b32b31176589dc42089d864a26b31b700`;
executable SHA256 `865f736ae87654ee31617692167c004bb3e282bf1d7b20d8e4ca353c6599068a`;
Info.plist SHA256 `c197bd0ac6ddf2d114d803ee9289c5cade2eb639d09657a062206c310b4a057e`.
Downloaded upstream release remains private, outside this repository.

## Native discriminator

`tests/smc_provider_probe.m` requires exactly one AppleSMC, a VirtualSMC parent,
bounded enumeration, unique nonzero keys, repeated identical enumeration, and
0xb8 for the first two out-of-range indices and UINT32_MAX. It reads no key values.
A60s alarm bounds failure. Also require boot/key services, idle and post-workload
PerfPowerServices CPU, unchanged Metal output, complete capture and clean recovery.
Both native boots now pass the scoped checks below. Setup is documented in
[the stock-QEMU guide](../../docs/stock-qemu-smc.md).

Private preparation, original boot-media backups and qtest artifacts are under
`/home/bogdan/macos-vm/run/research/smc-ownership-20260916/`. Live boot media was
prepared with VirtualSMC1.3.7 and the handoff config, and both raw/qcow2 readbacks
matched. The normal cycle will stage fresh driver/nonces and bind the entire boot
image to the run. The first test uses the unchanged280 driver/card baseline with
an explicit stock-QEMU image pin and a named-boot allowance in status.md.

## First native result

Run `711baaeda692ee9629548284c3c3a7ad`, MODE2#168, exposure26, stock packaged
QEMU10.1.2 executable SHA256 `bf7a8b373cda802d5b63dc162fee9cbf4698a5920b50d9a993458c676ecdafa3`.
Metal baseline passes. One AppleSMC, parent VirtualSMC1.3.7;69 distinct keys,
repeat enumeration and end-of-list pass, including after a PerfPowerServices restart.
Service CPU0.0% initially0.73s, after workload0.79s, new PID after restart0.0%/0.59s.
H.264 and HEVC both select hardware encoder/decoder and each pass120frames720p
with107,019,000 checked luma values; maximum error1 and0 respectively.
Three-minute native material workload completes1,828 event ticks (not FPS); two raw
RFB captures are clean by visual inspection. Initial capture client attempts failed
at credential decoding/authentication and produced no images; successful captures
use native account authentication and Raw encoding. No transport workaround applied.

Clean guest-request shutdown, schema6 recovered/authorizes_launch=true, CP_STAT0,
active_after0, forced_inactive0, dequeue_timeouts0, no host kernel messages.
Overall CORE_PROBE_PASS with valid capture. The fresh-guest-boot repeat also passes;
independent host boots, arbitrary macOS/QEMU builds and other hypervisors remain open.

## Fresh-boot repeat and current baseline

Run `81c11a768f28ad722971a4d85d70aac8`, MODE2#169, exposure27 on the same host boot.
One VirtualSMC-backed AppleSMC again supplies69 keys and correct terminal responses.
PerfPowerServices0.0%,0.85s initially and0.86s after workload. Metal baseline passes;
both hardware codecs again pass120frames720p each with107,019,000 checked luma
values per codec (maximum error H.264=1, HEVC=0). Raw desktop capture is clean.
Both runs total480 hardware encode/decode frames,428,076,000 checked luma samples;
the first run's separate3-frame software-encode/hardware-decode control also passes.

Capture:408 records/snapshot18 on the first run,405/snapshot18 on the repeat;
strict classifier valid/CORE_PROBE_PASS for both. Both exit after guest shutdown,
recover with CP_STAT0, active_after0, no forced clears/timeouts or host fault logs.
The stock image is now the default `experiments/pins.json` value. The legacy patched
image and original boot-media backups are retained for rollback; no source/driver
binary changed. No new exposure allowance follows from these results.

[Hashes, native outcomes and scope](smc-opencore-handoff-evidence-20260916.json).
The repository's only QEMU patch changes AppleSMC enumeration; the derived image
replaces only QEMU. This stock-image test removes that project's emulator change,
not the usual VFIO/OpenCore/ROM setup. Independent host boots, additional QEMU/macOS
versions and other hypervisors remain untested. Successful login/desktop/DSMOS
startup is observed; comprehensive keychain/secure-service functionality was not tested.
