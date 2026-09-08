# Rootless VFIO warm-reuse design

## Goal

Allow repeated, bounded macOS GPU experiments on the Raphael iGPU during one host boot,
without sudo, a PCI bus reset, or a vfio-pci/amdgpu driver transition. A successful cleanup
must be proven before the next launch is admitted.

## Measured constraints

- `0000:7b:00.0` exposes only the PCI `bus` reset method. Its upstream bus also contains
  the host CCP/PSP, two xHCI controllers and audio functions, so resetting that bus is unsafe.
- The iGPU remains bound to `vfio-pci`; `/dev/vfio/31` is owned by the desktop user and the
  VFIO container node is world accessible. Mapping BAR5 through VFIO therefore needs no root.
- QEMU/VFIO teardown disables PCI bus mastering, interrupts and DMA mappings. It cannot reset
  this function because the shared-bus reset is ineligible.
- The persistent state known to break the next Apple PSP initialization consists of the UM/RBI
  and GPCOM rings. Both can be destroyed through MP0 `C2PMSG_64` in BAR5. The command response
  identifies the command and completion; mailbox value zero alone is not proof of cleanliness.

## Recovery transaction

`tools/vfio-recover.py` owns the recovery transaction. It refuses unless all of these are true:

1. no Docker-OSX/QEMU process is active;
2. the exact Raphael device is `1002:13c0`, bound to `vfio-pci`, in IOMMU group 31;
3. PCI command bus-master enable is clear;
4. the prior run belongs to the current host boot and is the most recent launch in the boot
   ledger;
5. the initial three-launch-per-boot ceiling has not been reached.

The utility opens the legacy VFIO container and group as the current user, attaches the group,
gets the device file descriptor, and maps only BAR5. It unconditionally submits
`DESTROY_RINGS` (`0x00030000`) followed by `DESTROY_GPCOM_RING` (`0x000c0000`). Each command
must return the matching ready response within two seconds. It then unmaps and closes every
VFIO object, verifies bus mastering is still disabled, and checks the kernel journal for new
IOMMU, lockup, machine-check or PCI faults.

No CP, SDMA, GMC, SMU or bridge register is written. The transaction never binds amdgpu,
unbinds vfio-pci, invokes `/sys/.../reset`, removes a PCI function, or changes runtime power.

## Durable admission record

A successful transaction writes an immutable JSON receipt under
`run/vfio-recovery/<boot-id>/<prior-run-id>.json`. It contains the current boot ID, previous
run ID, recovery ID, device/group/driver identity, PCI command values, both PSP command
transitions, VFIO region metadata, and the kernel-capture interval. A failed transaction writes
evidence to the requested output but never creates a reusable receipt.

The boot ledger at `run/used-gpu-boots/<boot-id>.json` records ordered launches. The first
launch is admitted from the clean-boot host gates. Every later launch must atomically consume
one unconsumed receipt whose `prior_run_id` equals the ledger's latest run. Consumption is
recorded in the ledger before VFIO is opened for the next launch. Historical receipt files
remain immutable.

Existing one-entry reservation files are interpreted as a one-launch ledger. They cannot admit
another launch until a valid recovery receipt is produced for that recorded run.

## Experiment integration

The experiment coordinator performs recovery after QEMU stop is positively confirmed and the
continuous host monitor has completed its final poll. Recovery failure leaves the boot closed.
For the initial validation, at most three GPU launches may occur in one host boot. Any
unconfirmed VM stop, active VM, bus-master enable, mailbox timeout, VFIO setup failure, or new
kernel fault revokes warm reuse.

The first hardware proof is candidate 166 on the current boot after recovering from candidate
165. Success requires exact PSP responses, an admitted second ledger entry, normal guest PSP
initialization, and no host fault. A later three-cycle qualification must also prove native
guest shutdown or explicitly preserve forced-stop outcomes; cleanup does not relabel shutdown.

## Why sudo is unnecessary

The old `gpu-quiesce.sh` opened the root-only sysfs `resource5`, so that implementation needed
sudo. VFIO already grants the experiment user controlled access to this device and its BARs.
Using the existing VFIO ownership removes the root requirement while preserving kernel IOMMU
ownership and isolation.

