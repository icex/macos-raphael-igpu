Experimental RaphaelGPU 1.0.173 candidate for Sequoia 15.7.9 (24G830).

- Hardware-tested candidate 1.0.171 completed native one-instance SDMA startup, KIQ stamps 1
  through 6, `AMDHardware::startHWEngines`, and accelerator power-up. The first terminal event
  was an SDMA0 paging timeout; a later KIQ stamp 28 timeout followed channel restart attempts.
- The classifier now preserves raw terminal ordering, so replayed structured KIQ records cannot
  outrank an earlier raw SDMA failure.
- Candidate 1.0.172 replaces an unused `programAndInvalidateVM` observation with a read-only hook
  on `prepareVMInvalidateRequest`. It copies the complete VMID 2 source request and all 21 native
  register/value dwords after Apple encodes them. The callback performs no MMIO, logging,
  allocation or waits; a dedicated kernel thread emits the bounded observation later.
- Exact KDK preflight verifies the new route at X6000 offset `0x6249c` and its safe prologue.
  Linux v6.12 uses the same GFXHUB 2.1 implementation, GC register header and GC segment 0/1 bases
  for Navi23 GC 10.3.4 and Raphael GC 10.3.6, so the next patch will require a measured packet
  mismatch rather than a family-wide register assumption.
- Candidate 1.0.173 adds the separately gated `rgpuvmroot=1` experiment. For only the marked
  Raphael hub-0 VMID-2 reprogram request, it copies the 0x28-byte request and converts the
  non-SYSTEM root address from the logical framebuffer domain to the GFXHUB physical domain.
  It preserves the caller object and all allowed bits, rejects unknown flag and aperture forms,
  and verifies that Apple's 21-dword output contains the repaired root.
- Its worker correlates VM programming and SDMA submission by sequence, samples the live VMID-2,
  fault, invalidate and SDMA state at dispatch and bounded delays, and walks the three relevant
  virtual addresses through BAR0. The walk follows translated non-SYSTEM child page-directory
  pointers for diagnosis only. It never changes child PDEs, leaves, submitted VAs, response mode
  or firmware. A logical `0xf4...` child would identify the next producer fix.
- `AMDGraphics10Hardware::setVMRegisters` now preserves the pointer-width return ABI established
  by the 24G830 implementation and checked by preflight.
- Candidate 1.0.171 produced the first authorizing reset-free recovery after native startup: both
  active HQDs dequeued immediately, no forced clear was used, CP status was idle, SDMA halted,
  both PSP teardown commands completed, and no host fault was recorded. This permits one guarded
  same-boot experiment when every current admission rule is satisfied.
- The source-built test suite includes terminal-ordering, prepared-request parsing, route guards,
  bounded-copy fixtures, and the existing VM/VFIO lifecycle checks.

Metal 3 still only enumerates. No compute or render command buffer has completed, accelerated
desktop composition is not yet verified, and zero games are supported. This remains a research
prerelease with three historical host hangs; all bounded launch and recovery guards remain in
force.
