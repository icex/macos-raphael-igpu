Experimental RaphaelGPU 1.0.179 candidate for macOS Sequoia 15.7.9 (24G830).

- Replaces the fixed recovery scratch range and 240 MiB software-pool cap with a
  launch-bound native recovery lease. The exact lease is excluded from both native
  software pools before ordinary clients are admitted.
- Retains the 256 MiB BAR-visible compatibility pool so Apple's fixed 68 MiB VMM
  arena can fit. Candidate 1.0.178 stopped before submission after every captured
  mapping failed in the backing/PTE phase; source analysis found that the arena
  extended beyond the former 240 MiB cap.
- Publishes immutable OWNED and separate POOL records for host recovery. Exact
  owner, vtable target, visible-range, GART separation, both pool deltas, retained
  element addresses, nonce identity, and duplicate initialization are checked
  fail closed.
- Records the final native VMM arena and both page-table allocator pointers, and
  retains the candidate 1.0.178 submission observations plus the candidate 1.0.179
  physical-backing observer.
- Offline sanitizer, source-contract, whole-driver syntax, route ownership, and
  exact 24G830 KDK preflight checks cover this candidate. Hardware execution has
  not yet validated the new arena hypothesis.

The last hardware candidate enumerated Metal 3. No compute or render command buffer has completed,
accelerated desktop composition is not verified, and zero games are supported. This
remains a research prerelease with three historical host hangs; all bounded launch,
watchdog, recovery, and no-reset rules remain in force.
