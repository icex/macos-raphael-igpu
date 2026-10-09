# Candidate 420: PGM lease investigation paused

Paused at the user's request before implementation. Candidate 420 was created from freshly fetched dev `0ecc171` and merged candidate 418 `3fb2c8d`. No PGM source patch, new build, VM execution, device access, installation or module operation was performed in this iteration. The completed 416/418 builds remain in their separate scratch directories; no build process owned by this task remains active.

## New concrete finding

A refusal only inside `pgmPhysFreePage` cannot make reset safe or transactional. In the verified official 7.2.18 release:

- `src/VBox/VMM/VMMR3/VMR3.cpp:2572` `vmR3HardReset` changes VM state and CPU state, then calls `GIMR3Reset`, `PDMR3Reset`, and `PGMR3Reset` at 2622–2624. These device mutations already occurred before RAM reset.
- `PGMR3MemSetup` in `VMMR3/PGMR3.cpp:2199` returns void and only applies `AssertReleaseRC` to `pgmR3PhysRamZeroAll` failure. Adding a failure deep in PGM would not roll back the surrounding reset.
- `vmR3Load` in `VMR3.cpp:1852–1883` changes state before invoking `SSMR3Load`. PGM load preparation (`PGMR3SavedState.cpp:2230`) itself calls void `PGMR3Reset` and then returns success.

Therefore a lease requires a top-level reset/load admission check before device/state mutation, plus the previously identified PGM disposition guards. A partial guard patch must not be presented as a complete lifetime contract.

## Resume point

Continue tracing all reset routes (`vmR3ResetCommon`, hard/soft reset, forced reset/triple fault), load entry points, and teardown ordering before implementing the smallest unconnected PGM acquisition/release test. Existing `pgmPhysGCPhys2CCPtrInternal` (`PGMAllPhys.cpp:3345`) accepts an already-owned PGM lock and retains a writable page mapping, but can materialize backing; acquisition must control that phase and publish the lease only after complete success. The public range getter pair is not an atomic inventory.

The [418 proposal](virtualbox-pgm-lease-prototype-plan-20261010.md) remains a proposal, not implemented functionality. The first implementation must keep VFIO disconnected and establish authoritative page coverage, rollback and refusal-before-mutation in software before physical DMA is considered. Physical backing lifetime and reset policy remain unresolved.

No test result is added by this source-only review. The last completed relevant checks remain candidate 418: full patched userland build exit 0, compiled transaction/UAPI tests, and 1,488 host tests with 8 skipped. No new milestone or publication is claimed here.
