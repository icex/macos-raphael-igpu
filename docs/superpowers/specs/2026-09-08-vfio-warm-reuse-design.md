# Rootless VFIO warm-reuse design

## Goal

Allow repeated, bounded macOS GPU experiments on the Raphael iGPU during one host boot after one
privileged handoff, without per-run sudo, a PCI bus reset, or another vfio-pci/amdgpu driver
transition. A successful cleanup must be proven before the next launch is admitted.

## Measured constraints

- `0000:7b:00.0` exposes only the PCI `bus` reset method. Its upstream bus also contains
  the host CCP/PSP, two xHCI controllers and audio functions, so resetting that bus is unsafe.
- The iGPU remains bound to `vfio-pci`; `/dev/vfio/31` is owned by the desktop user and the
  VFIO container node is world accessible. Mapping BAR0, BAR2 and BAR5 through VFIO therefore
  needs no root after the one-way handoff.
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

Before QEMU starts, the coordinator opens VFIO and writes a `PENDING` descriptor containing the
128-bit run ID into BAR0. `RaphaelGPU` recognizes that exact challenge immediately before
`AMDHWMemory::enableAllocations`, caps both Apple BAR0 allocator pools at `0x0f000000`, and changes
the descriptor to `ACTIVE`. The final 16 MiB is then outside both allocator pools. Recovery
requires `ACTIVE` plus the exact prior run ID and consumes the descriptor before using the
reserved region. An old launch nonce, a still-pending descriptor, a corrupt descriptor, or a
second recovery attempt fails closed.

The utility maps BAR0 VRAM, BAR2 doorbells and BAR5 MMIO. It disables write-pointer polling with
bit 31, walks all ME1/ME2 HQDs, and requests dequeue while the MECs still run. A stuck or newly
active HQD blocks the temporary KIQ and makes the transaction non-authorizing. If the legacy
graphics ring is active or has an enabled/hit doorbell, recovery validates doorbell offset
`0x400`, masks the 24-bit framebuffer fields, and translates the enabled flat context-0 page
table exactly as `GartAddresses.hpp`: physical root minus `FB_OFFSET << 24`, with the complete
table inside the 256 MiB BAR0 window. Unknown depth, flags, address form, bounds, or scratch
overlap aborts before scratch is written.

With both MECs halted, recovery builds a temporary MEC2/pipe1/queue0 KIQ in the reserved BAR0
range. Its 0x100-dword ring contains the exact graphics `UNMAP_QUEUES`, a confirmed
`WRITE_DATA` fence to reserved VRAM, and KIQ NOP padding; `CP_HQD_PQ_CONTROL` is `0xd130060d`.
CPU BAR0 writes are ordered with the validated NBIO 7.2 `HDP_MEM_FLUSH_CNTL` remap and the NBIO
CONFIG_MEMSIZE posted-read barrier before MEC2 starts. The BAR2 doorbell is one aligned native
64-bit store. Success requires the ring read pointer, the unique GPU-written fence, and the
target graphics `CP_RB_ACTIVE=0` before any legacy register scrub. Cleanup always re-halts MECs,
retires the temporary HQD, restores selector zero, and leaves the PQ doorbell gate, doorbell
ranges, and bit-31 pointer poller disabled.

Recovery then disables SDMA context switching, ring and IB before halting physical SDMA0; halts
the graphics CP; clears legacy programming only after the ordered retirement proof; and proves
all selectors inactive. It finally submits `DESTROY_RINGS` (`0x00030000`) followed by
`DESTROY_GPCOM_RING` (`0x000c0000`). A forced HQD clear remains diagnostic only and can never
authorize another launch. Every timeout, readback mismatch, fence mismatch, PSP response error,
or non-idle CP status prevents a receipt.

The transaction never pulses `GRBM_SOFT_RESET`, writes GMC or SMU, binds amdgpu, unbinds
vfio-pci, invokes `/sys/.../reset`, removes a PCI function, or changes runtime power. It then
unmaps and closes every VFIO object, verifies bus mastering is still disabled and reset methods
remain empty, and rejects any VFIO reset message or new IOMMU, lockup, machine-check or PCI fault.

## Durable admission record

A successful transaction writes an immutable JSON receipt under
`run/vfio-recovery/<boot-id>/<prior-run-id>.json`. It contains the current boot ID, previous
run ID, recovery ID, device/group/driver identity, PCI command values, both PSP command
transitions, all three VFIO region records, launch-bound reservation evidence, HDP flush,
temporary-KIQ fence and final engine/gate readbacks, plus the kernel-capture interval. A failed
transaction writes evidence to the requested output but never creates a reusable receipt.

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

Earlier candidate-166 reuse proved PSP cleanup could permit one reinitialization, then the third
launch exposed inherited HQDs; it does not prove this expanded recovery. The BAR0/BAR2/BAR5
host-KIQ implementation and its failure paths are covered offline, but no physical launch has
yet activated the reservation descriptor or demonstrated its fence. Hardware qualification must
first inspect those records, then prove a subsequent initialization on the same host boot. A
later three-cycle qualification must also prove native guest shutdown or explicitly preserve
forced-stop outcomes; cleanup does not relabel shutdown.

## Privilege boundary

The old `gpu-quiesce.sh` opened the root-only sysfs `resource5`, so that implementation needed
sudo for every cleanup. The replacement needs root once per boot for the existing amdgpu to
vfio-pci handoff and to write an empty value to the root-owned `reset_method` sysfs attribute.
Only after that verified write does `gpu-bind.sh` grant the experiment user access to the VFIO
group. Builds, launches, BAR0/BAR2/BAR5 cleanup, receipts, and repeated warm tests then run as
the user.
