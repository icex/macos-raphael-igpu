# Rootless VFIO warm-reuse design

## Goal

Allow repeated, bounded macOS GPU experiments on the Raphael iGPU during one host boot after one
privileged handoff, without per-run sudo, a PCI bus reset, or another vfio-pci/amdgpu driver
transition. A successful cleanup must be proven before the next launch is admitted.

## Measured constraints

- `0000:7b:00.0` exposes only the PCI `bus` reset method. Its upstream bus also contains
  the host CCP/PSP, two xHCI controllers and audio functions, so resetting that bus is unsafe.
- The iGPU remains bound to `vfio-pci`; `/dev/vfio/31` is owned by the desktop user and the
  VFIO container node is world accessible. Mapping BAR5 through VFIO therefore needs no root.
- Legacy VFIO calls `pci_try_reset_function()` when the device is opened and may reset it again
  on close. On this host that selected the advertised `bus` method despite the shared APU bus.
  The handoff must therefore disable all reset methods before any VFIO consumer opens the device.
- PSP state that breaks the next Apple initialization includes the UM/RBI and GPCOM rings. Both
  can be destroyed through MP0 `C2PMSG_64` in BAR5. A fully started guest also leaves active
  GC/KIQ HQDs, CP engines and SDMA state; the third same-boot launch measured those queues and
  failed a KIQ stamp. The command response identifies PSP completion, but does not prove the GC
  is clean.

## Recovery transaction

`tools/vfio-recover.py` owns the recovery transaction. It refuses unless all of these are true:

1. no Docker-OSX/QEMU process is active;
2. the exact Raphael device is `1002:13c0`, bound to `vfio-pci`, in IOMMU group 31;
3. PCI command bus-master enable is clear;
4. `/sys/.../reset_method` exists and reads empty;
5. the prior run belongs to the current host boot and is the most recent launch in the boot
   ledger;

The utility opens the legacy VFIO container and group as the current user, attaches the group,
gets the device file descriptor, and maps only BAR5. It follows Linux GFX10 teardown: disable
`CP_PQ_WPTR_POLL_CNTL`, walk ME1/ME2 HQD selectors and request dequeue while the MECs still run,
then halt graphics CP, both MECs and physical SDMA0. If a queue cannot drain after QEMU removed
its guest DMA mappings, recovery disables its doorbell and clears `CP_HQD_ACTIVE` only after the
MEC halt readback. It clears stale pointers and proves every selector inactive. It then submits
`DESTROY_RINGS` (`0x00030000`) followed by `DESTROY_GPCOM_RING` (`0x000c0000`). Every register
transition and PSP response must read back correctly before a receipt is created.

The transaction never pulses `GRBM_SOFT_RESET`, writes GMC or SMU, binds amdgpu, unbinds
vfio-pci, invokes `/sys/.../reset`, removes a PCI function, or changes runtime power. It then
unmaps and closes every VFIO object, verifies bus mastering is still disabled and reset methods
remain empty, and rejects any VFIO reset message or new IOMMU, lockup, machine-check or PCI fault.

## Durable admission record

A successful transaction writes an immutable JSON receipt under
`run/vfio-recovery/<boot-id>/<prior-run-id>.json`. It contains the current boot ID, previous
run ID, recovery ID, device/group/driver identity, PCI command values, both PSP command
transitions, VFIO region metadata, and the kernel-capture interval. A failed transaction writes
evidence to the requested output but never creates a reusable receipt.

Cleanup still runs after the third launch so the device is left quiescent. The launch ceiling is
an admission rule; a receipt created at the ceiling cannot authorize a fourth launch.

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

## Privilege boundary

The old `gpu-quiesce.sh` opened the root-only sysfs `resource5`, so that implementation needed
sudo for every cleanup. The replacement needs root once per boot for the existing amdgpu to
vfio-pci handoff and to write an empty value to the root-owned `reset_method` sysfs attribute.
Only after that verified write does `gpu-bind.sh` grant the experiment user access to the VFIO
group. Builds, launches, BAR5 cleanup, receipts, and repeated warm tests then run as the user.
