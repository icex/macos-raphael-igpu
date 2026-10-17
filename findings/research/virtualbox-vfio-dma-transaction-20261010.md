# Candidate 411: transactional VFIO DMA error handling

Offline experimental patch only, against VirtualBox 7.2.18 commit
`14841851fa211c7faf615978ba385d59947236c6`. No physical device, VM, deployment or
full VirtualBox build. Existing default device behavior is changed only by applying
this separate patch; installed VirtualBox is untouched.

The stock map loop (DevPciVfio.cpp2093–2164) logs failed IOMMU extents, marks the
whole mapping complete and returns success. The COMMAND handler (2345–2371) also
continues to physical BUSMASTER even if its mapping call fails. These source
facts make an ID/ROM-only passthrough experiment premature.

The patch allocates an extent record before every map ioctl, records successful
maps and reverses them on the first map/record-allocation failure. Legacy VFIO
and IOMMUFD unmap results must report the requested length. Rollback failures are
logged while remaining extents still receive rollback attempts. Every admission
failure latches a device-lifetime refusal; later BME writes cannot retry ambiguous
mapping state. Only a successful transaction sets fGuestRamMapped. A failed BME
admission returns before the physical write or emulated default-update path.
Disabling BME remains allowed. Device reopening, not a config write, clears the
zero-initialized latch. The latch is shared by functions, like the existing map flag.

## What was tested

The patch applies cleanly to the exact pinned source and yields the retained
patched-source SHA. One host unittest compiles exact patched transaction functions
and the actual COMMAND/BME admission branch with bounded PGM/map/ioctl substitutes.
It runs both legacy and IOMMUFD modes, successful reuse, first/middle/final map
failure, ledger allocation failure before side effects, reverse-order rollback,
rollback ioctl failure/short length, balanced temporary allocations/page locks,
sticky retry refusal and no BME write-through after failure. A successful BME path
and BME-disable path proceed. It does not compile the complete device callback or
VirtualBox binary. Linux IOMMUFD headers and a C++ compiler are prerequisites;
missing prerequisites produce an explicit test skip, not a fabricated pass.

## Remaining blockers; no safe-exposure claim

The existing scan policy is retained deliberately. It is NOT authoritative RAM
registration. Pinned pdmdev.h3155–3189 says PhysGCPhys2CCPtr may replace shared/zero
pages and distinguishes reserved pages from invalid guest physical addresses.
The stock scan treats failures as holes and releases PGM locks before later DMA
use; it can still claim success for an incomplete/empty discovered set. Kernel
VFIO pinning of a userspace mapping alone does not prove the guest PGM backing
cannot change. A dedicated RAM-range enumeration and retained backing/removal
contract is still needed; simply retaining millions of temporary PGM locks is
not an audited solution. The scan also retains its upstream fixed 4 KiB assumption.

Rollback assumes the failed map ioctl did not install an unreported partial
extent. No physical BME is enabled by this admission path on failure, but the patch
does not prove the device started with BME off, serialize competing PGM changes,
quiesce DMA, or repair reset/destruction behavior. It does not add a teardown map
ledger after success. Whole-container close remains the upstream lifetime path.

Next code review should establish that authoritative RAM/lifetime interface and
an explicit reset policy. pciVfioReset blindly requests VFIO_DEVICE_RESET;
destruction attempts IOMMUFD detach even for legacy. QEMU MODE2/recovery receipts
cannot automatically authorize another hypervisor's behavior. Identity overlay
and exact external ROM support come after these gates, with no writes to physical
PCI IDs. All GPU exposure remains unqualified.

Primary sources: [VFIO device](https://github.com/VirtualBox/virtualbox/blob/14841851fa211c7faf615978ba385d59947236c6/src/VBox/Devices/Bus/DevPciVfio.cpp),
[PDM mapping API](https://github.com/VirtualBox/virtualbox/blob/14841851fa211c7faf615978ba385d59947236c6/include/VBox/vmm/pdmdev.h).
