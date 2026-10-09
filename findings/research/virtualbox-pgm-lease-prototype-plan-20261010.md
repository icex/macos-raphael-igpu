# First PGM DMA lease prototype: proposed scope, not implemented

The candidate 418 full production build tests the existing 411/413 transaction patch. It does not add or qualify a DMA backing lease. Physical VFIO remains blocked.

## Minimal next implementation slice

Use a PGM-owned acquisition/release API with a trusted PDM wrapper, not a device-side loop over maximum guest address. Proposed files are `include/VBox/vmm/pgm.h`, `include/VBox/vmm/pdmdev.h`, `src/VBox/VMM/include/PGMInternal.h`, `VMMR3/PDMR3DevHlp.cpp`, `VMMR3/PGMR3Phys.cpp`, and the specifically identified disposition paths below. The helper-table version and wrappers must change together; no ABI-only declaration is a complete implementation.

First implement an **unconnected software lease test**: acquire an authoritative interval/page inventory while EMTs are quiesced, materialize private RAM backing, retain writable mapping locks, and record generation plus GPA, host pointer, page ID and HCPHYS. Coalesce only genuinely contiguous GPA/HVA pages. Return a PGM-owned token and immutable extent list. Register the lease before execution resumes. Release checks identity/generation and reverses all retained mappings. Refuse NEM, unsupported page states, ballooned RAM, inconsistent or empty discovery, and overflow in this initial prototype. No device enables BME or calls VFIO using this prototype yet.

`PGMR3PhysGetRamRangeCount/GetRange` (`PGMR3Phys.cpp:1455–1509`) take the PGM lock separately; `pfIsMmio` only tests AD_HOC_MMIO. Use one locked traversal and per-page RAM validation. `PGMR3PhysGetRamBootZeroedRanges` at 1522 is an enumeration example, not a lease API. Memory holes are excluded by authoritative range membership, while errors inside an expected RAM interval fail acquisition.

## Boundaries that must be enforced before connecting DMA

- `PGMR3Phys.cpp:1598` `pgmPhysFreePage` replaces HCPHYS/page ID with the zero page at 1655–1657. It does not consult mapping-lock counts. Reject leased pages before any counters, free requests or page state change. Also reject whole destructive operations before partial work, rather than depending solely on a failure halfway through a batch.
- RAM reset/zero at `pgmR3PhysRamReset:2270` / `pgmR3PhysRamZeroAll:2302`; balloon rendezvous at 5465 and its free at 5513. Saved-state page replacement calls `pgmPhysFreePage` in `PGMR3SavedState.cpp:2845/2868`. Initially refuse reset/load/balloon operations while a lease exists; do not pretend those features work transparently.
- MMIO mapping (`PGMR3PhysMmioMap:2808`) and MMIO2 overlap (`PGMR3PhysMmio2Map:3839`, worker 3640–3666) can turn RAM into device pages. Validate the complete affected interval before freeing RAM or replacing page metadata. MMIO/MMIO2 unmap at 2978/4036 and RAM registration at 2074 must maintain the same interval-generation contract.
- Copy-on-write/private allocation in `PGMAllPhys.cpp:2305`, with HCPHYS/page ID replacement at 2409–2410, must not replace a leased page. Materialize before publishing the lease. Do not block ordinary writes to an already-private leased page.
- `PGMR0SharedPage.cpp:95–99` already requires zero read/write mapping locks before sharing; retained write locks prevent this specific consolidation path. This is narrower than a general immovability promise. Review large-page allocation (`PGMAllPhys.cpp:2481`) and `PGMR0.cpp:698–701` disposition paths before declaring the list exhaustive.

The token and guards must be visible wherever backing changes, including relevant ring-0 paths. Adding a ring-3 getter alone cannot meet this contract. No PGM mutex may remain held across blocking VFIO ioctls. A later device integration must acquire lease → map transaction → enable BME, and stop DMA → unmap → release lease; failed unmap keeps backing retained until IOMMU destruction is established. Device reset policy remains a separate prerequisite.

## Discriminating software acceptance

With a small software VM and no physical device, verify exact RAM coverage with a hole; fresh private backing for zero/shared pages; rollback on allocation/map failure; stable GPA/HVA/page identities after ordinary writes; refusal before mutation for balloon, MMIO overlap, reset and state load; release restores permitted operations; stale/double release refuses. The initial source-only stage can compile all production paths and test pure range logic, but it must not be called a lifetime proof until these actual PGM operations are exercised.

Source is the verified official VirtualBox 7.2.18 release archive recorded in [the baseline report](virtualbox-isolated-baseline-build-20261010.md); cited paths are relative to `src/VBox/VMM/` unless otherwise stated. Official pinned equivalent: <https://github.com/VirtualBox/virtualbox/tree/14841851fa211c7faf615978ba385d59947236c6/src/VBox/VMM>.
