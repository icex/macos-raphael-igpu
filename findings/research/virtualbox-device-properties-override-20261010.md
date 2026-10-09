# Candidate400: replace the incomplete VBox EFI device-property protocol

AttemptA is preserved under `run/c398-vbox-boot-a`, including its writable disks. It reached OpenCore/APFS enumeration but failed in the VBox firmware assertion `VBoxAppleSim.c:145`, `AppleGetVar_Unknown0`. The owned VM was powered off and unregistered; no physical GPU was attached. Earlier FirmwareFeatures invalid-parameter output is retained but is not assumed to be the assertion's cause.

## Source-supported intervention

Pinned official VirtualBox7.2.18 commit14841851fa211c7faf615978ba385d59947236c6, VBoxAppleSim.c:114–145 defines Apple device-property GUID91BD12FE-F6C3-44FB-A5B7-5122AB303AE0 and its first placeholder operation calls DebugAssert before returning EFI_UNSUPPORTED. OpenCore's DevicePathPropertyDatabase.h:66–68 defines the same GUID; its first operation is GetProperty (line180).

Pinned OpenCore1.0.5 reference commite8437f737708c7151b243d967f9ceca54193d97e: OpenCoreUefi.c:398 passes UEFI.ProtocolOverrides.DeviceProperties to OcDevicePathPropertyInstallProtocol. OcDevicePropertyLib.c:805–820 uninstalls the existing instances when true; false locates and returns the firmware implementation. Lines984–995 install OpenCore's full implementation. Configuration.tex:9085–9093 documents replacement for VM compatibility and warns that firmware-provided entries are discarded. Existing configured DeviceProperties.Add entries therefore remain intact; blindly removing them is not the intervention.

The installed626688-byte OpenCore.efi contains only a REL-XXX-YYYY-MM-DD template in the initial string scan. BootB picker screenshot `screen-001.png`, visually inspected by the hardware owner, independently identifies **REL-105-2025-07-07**. The source reference is therefore updated to official1.0.5; prior1.0.6 reference artifacts remain retained. Release alignment is not a byte-for-byte build provenance proof.

## Prepared independent bootB

`run/c398-vbox-clones/OpenCore-b-boot.vdi` and `mac_hdd_ng-b-boot.vdi` derive independently from the verified baseline VDIs, not attemptA's modified disks. The loader retains documented398 changes (disable VirtualSMC and exact QEMU SMC ACPI patch, remove vsmcgen=2, add-rgpuoff) and changes only **UEFI.ProtocolOverrides.DeviceProperties=false→true** relative toA's prepared config. All other plist values, including identity and two DeviceProperties.Add entries, compare equal. FAT-file readback equals the new config, and qemu-img compare proves the edited raw loader equals its VDI. Original baselines and attemptA were not written. The system derivative is a reflink without a new whole-disk scan.

`boot-b-preparation.json` retains safe configuration/loader hashes and exact checks. No VM registration or start was performed by this agent. Root owns execution. Success at this boundary means no recurring placeholder assertion and progression beyond it; it does not establish macOS desktop, acceleration or fix unrelated CPU/SMC/storage behavior.

The controller now treats observed gurumeditation as functional_failure=firmware-or-vm-guru, promptly leaves observation for owned cleanup and returns nonzero. That state alone does not identify EFI as the cause; the separate assertion evidence does. AttemptA's original result is not rewritten. Eight focused existing controller/preparation tests pass; this new observed-state branch still requires runtime execution.

## BootB progression (initial observation)

The root-owned attempt progressed past the previous VBox firmware placeholder assertion to the OpenCore picker and EXITBS/HANDOFFXNU, then kernel APFS and USB-tablet initialization. The hardware owner reports AHCI timeouts probing empty ports0/1 with disks on2/4; boot completion was pending at this observation. This demonstrates the targeted protocol-boundary improvement, not a macOS desktop or acceleration result. The completed attempt is recorded below.

## Completed bootB: userspace timekeeping panic

The guest entered userspace, then panicked at approximately66.843 seconds on CPU6: `Non-monotonic time: invoke at 0xf8faf2a44, runnable at 0xf8faf8032 @sched_prim.c:3242`. The current process was diskarbitrationd (PID127); that identifies the affected task, not a demonstrated disk defect. Kernel version is Darwin24.6.0/xnu-11417.140.69.711.44. No macOS desktop was observed; screenshot015 still shows initial kernel text. EFI/APFS/XNU progression therefore passes only the earlier firmware boundary.

Root stopped the exact owned VM; result.json verifies poweroff and unregistered=true, guest_boot_qualified=false. Twenty screenshots were attempted. This is deliberate software-VM cleanup after a kernel panic, not natural guest shutdown and not physical GPU recovery. The controller did not classify the serial-only XNU panic as gurumeditation; its original result is retained unchanged. No Raphael/VFIO device was attached.

Next source-guided discriminator: inspect actual configured VBox TSC/CPUID handling and the scheduler monotonicity assertion. Compare one vCPU against the same eight-vCPU profile before attributing the failure to AHCI, a specific timer mode, or adding guessed extradata settings. CPU stress and another VM launch remain owned by root.
