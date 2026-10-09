# Candidate 413: false DMA readiness refusal and required RAM lease

Offline only. The combined 411 patch now refuses empty discovery and treats
reserved-page/unexpected mapping errors as transaction failures, rolling back
prior successful extents and latching refusal. Only the documented invalid-GPA
hole code is skipped. Compiled extracted-function tests cover empty discovery,
reserved/unexpected failure before any map and after a prior extent, in addition
to the 411 map/unmap/BME fault matrix. This is not authoritative completeness:
an invalid GPA inside an expected RAM interval still requires a known interval
set to distinguish it from a legitimate hole. Installed VBox remains unchanged.

## Precise existing APIs

Official 7.2.18 commit14841851fa211c7faf615978ba385d59947236c6 exports
PGMR3PhysGetRamRangeCount/GetRange (pgm.h1478–1480;
PGMR3Phys.cpp1455–1509). Each call individually takes/releases PGM lock. GetRange's
pfIsMmio only tests AD_HOC_MMIO, not every ROM/MMIO2/mixed page type. Neither API
is present in the current PDM device helper table. They cannot simply replace the
scan and confer lifetime safety.

Internal PGMR3PhysGetRamBootZeroedRanges (PGMR3Phys.cpp1522–1580) filters non-ad-hoc
ranges under PGM lock. Its documented purpose is boot-zeroing / Hyper-V hints,
not DMA leases. Per-page dispositions still require validation. Preallocation
by itself is not a proof against later reset, MMIO overlap or ballooning.

PGMAllPhys.cpp3240–3275 mapping locks retain mapping references and increment page
write-lock counts. However PGMR3Phys.cpp1598–1665 pgmPhysFreePage replaces backing
HCPHYS/state/page ID with the zero page without a check of those counts in that
path. Its documented callers include balloon, MMIO2 remap, reset and state load.
Balloon rendezvous5455–5520 directly invokes it for RAM pages. Thus ordinary map
locks are not an established promise that the GPA keeps identifying the same
pages. VFIO pinning the old host pages cannot repair a changed guest GPA binding.

## Smallest practical core API proposal, not implemented

Add a trusted PDM helper backed by PGM, conceptually PhysDmaRamLeaseAcquire/Release.
Acquire must run in a quiesced EMT/rendezvous context, enumerate non-ad-hoc ranges
and validate each actual page as writable RAM. Materialize private backing first;
then record GPA, host pointer, backing/page identity and mapping lifetime in a
PGM-owned token. Return coalesced GPA/host segments plus the token, not borrowed
raw pointers with independently released locks. Fail closed on any expected page
error, overflow, incomplete interval or unsupported page type.

PGM must register the lease **before** allowing execution to resume. Every GPA
replacement/disposition operation must reject or synchronously revoke the lease
before changing it: at minimum free/balloon, MMIO/MMIO2 overlay, sharing/COW,
reset and state load. A limited first prototype can refuse those operations while
the fixed-RAM lease exists; no transparent hotplug/migration support is required.
A token generation and page-identity check protects stale releases, but is not a
substitute for preventing remap while DMA runs. Lock ordering must avoid holding
PGM mutex while performing blocking VFIO ioctls.

The device first acquires the lease, maps all segments transactionally, and only
then enables BME. Failure unmaps successful extents before releasing their lease.
On shutdown the hardware owner must stop DMA/BME and prove quiescence before
unmap/release; failed unmap must retain backing until IOMMU context teardown.
This needs a small core contract plus guards across disposition paths; adding only
one getter or retaining temporary mapping locks is insufficient. Full VBox build
and real software lifecycle tests are prerequisites before any physical GPU run.
Reset policy and guest identity/ROM work remain separate gates.

Primary pinned sources: [PGMR3Phys](https://github.com/VirtualBox/virtualbox/blob/14841851fa211c7faf615978ba385d59947236c6/src/VBox/VMM/VMMR3/PGMR3Phys.cpp),
[PGMAllPhys](https://github.com/VirtualBox/virtualbox/blob/14841851fa211c7faf615978ba385d59947236c6/src/VBox/VMM/VMMAll/PGMAllPhys.cpp),
[PGM declarations](https://github.com/VirtualBox/virtualbox/blob/14841851fa211c7faf615978ba385d59947236c6/include/VBox/vmm/pgm.h).
