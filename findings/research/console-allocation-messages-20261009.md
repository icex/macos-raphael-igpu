# Candidate390 allocation-message audit

Read-only follow-up to the scale-policy run. Candidate386 and388 retained serial
logs have zero `Failed to allocate` messages;390 has eight logged messages, all
requesting60293120 bytes. This is not an exact failure count: active
`rgpualloclog=1` preserves the first eight messages and samples each1024th later
failure (`src/AllocationLogBudget.hpp`, `budgetAllocationFailure` in
`src/RaphaelGPU.cpp`). No later sampled cumulative count was found. Capture
limitations are retained in the native report.

The first message reports77426688 free bytes; successive logged values rise to
81702912. Fixed-free remains1883172864. The log does not establish which resize
or source surface caused the requests.60293120=0x3980000=20480×2944, compatible
with5120-pixel BGRA rows and2880 rows padded to2944, but this arithmetic does not
identify a surface or prove its alignment policy.

## Decoded source evidence

Exact local24G830 sources, with inferred C types checked against assembly where
noted:

- `re/decompiled-24G830/X6000-full/functions/000531b6_AMDRadeonX6000_AMDHWMemory__allocateLargeBlocks.c`
  (under `~/macos-vm/`): attempts ordinary allocation, then noncontiguous
  allocation with progressively reduced chunk size; failure logs a rounded
  size. Assembly addresses0x53328 and0x53338 load separate allocator objects
  at`this+0x68` and`this+0x70` before their `total_free` calls.
- Same directory `00053048_*allocateNonContiguous.c`: allocation type and the
  total/visible/base fields determine the eligible address interval.
  `00052e4a_*allocateNonContiguous.c` allocates through`+0x68`; the second
  allocator is reserved conditionally. These are distinct accounting views,
  not two free-byte figures that can be added.
- `re/roadmap-24G830/IOAcceleratorFamily2-full/functions/0001fc62_IOAccelMemoryAllocator2__allocPages.c`:
  sufficient aggregate free space is only the first test. The allocator walks
  extents subject to alignment, address interval and chunk constraints. An
  incomplete multi-extent allocation is rolled back. Largest contiguous free
  extent alone would also be insufficient to describe this path.
- X6000 `00052a1e_*enableAllocations.c/.asm` initializes both allocator objects
  using provider base/total/visible fields.390 logs retain2GiB total,
  256MiB visible, and the native2MiB host-reserved tail. Current
  `wrapHwMemVram` observes those provider fields; this audit supplies no evidence
  for enlarging BARs or removing the reservation.

## Interpretation and next discriminator

Constrained eligible ranges or fragmentation are plausible; neither is proved
by total-free values. No direct decoded call-site attribution of this request to
WindowServer, a framebuffer or a texture was established. Successful desktop,
input and audio probes do not imply error-free allocation.

First compare the unchanged next-boot persistence baseline. If reproducible,
a bounded first-failure diagnostic should correlate cumulative failure count,
requested/rounded size, alignment, minimum chunk, allocation type/eligible
range and caller identity with mode/presenter timestamps. Preserve allocator
behavior and host reservations. No diagnostic fixture or memory modification
was made for this audit.
