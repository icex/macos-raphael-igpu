# Candidate 178 memory-map phase observer

Candidate 177 located the earliest retained native rejection at
`AMDGraphicsAccelerator::batchMemoryMapPrepare`, before `submitBuffer`. The next
diagnostic extends that existing safe wrapper only. It adds no route, framework
dependency, MMIO, allocation, wait, log formatting in the callback, workload change,
or functional workaround.

The exact 24G830 `AMDRadeonX6000` binary has SHA-256
`2e364270c3243c532a9428c670313d5afd20406e42d64edb4fa8f3572504104e`.
`AMDAccelMemoryMap::prepare` is at `0x3b3fe`, but it is deliberately not routed:
the first complete 18-byte entry span contains a short relative branch at function
offset `+0xd` whose target is outside the displaced span. The existing
`batchMemoryMapPrepare` route at `0x6550` retains its reviewed 16-byte prologue and
`bool(accelerator *, IOAccelMemoryMap *)` ABI.

The exact extracted 24G830 `IOAcceleratorFamily2` binary has SHA-256
`1700f3badafbb9014d55b7f6ecde5cdff0d585bd1f0e143c9f8465e4466e5d35`.
Its allocator and prepare paths establish these fields:

- accelerator `+0x1fb0`: 32-bit number of maps already prepared in this batch;
  `batchMemoryMapPrepare` rejects a new map when the entry value is greater than
  `0x3ff`, and a false return does not change it;
- map `+0xc`: 32-bit prepare count; a nonzero entry count takes the successful fast
  path, while a false return cannot leave it nonzero;
- map `+0x10`: 32-bit flags; bit 0 records an assigned GPU virtual address and bit
  `0x20` permits a successful assignment whose raw stored address is zero;
- map `+0x98`: 64-bit raw GPU virtual address, retained as corroborating evidence and
  never used alone to classify failure.

`IOAccelMemoryMap::allocGPUVirtualAddress` writes `+0x98` and sets flags bit 0 only
after allocation succeeds. `IOAccelMemoryMap::prepare` does not clear either field
when backing preparation or PTE commit fails. `freeGPUVirtualAddress` is the explicit
path that zeros `+0x98` and clears bit 0. The system- and video-memory fallback paths
free other objects and retry the target map; they do not clear the target's assigned
address. Therefore the wrapper's final post-call bit 0 identifies the blocking phase
after all native retries. It does not identify the first failed attempt: a final
`backing-pte` result may include an earlier VA miss that a fallback retry recovered.

The wrapper first checks the existing all-routes-ready and Raphael-target gate.
When inactive it forwards directly to native before evaluating any field address.
When active it copies the four fields before and after exactly one native call and
returns the native Boolean unchanged. A failed call is classified as:

1. `unknown` if a snapshot is unavailable, either prepare count is nonzero, the
   batch count changed, or flags bit 0 changed from set to clear;
2. `capacity` if the remaining entry batch count is greater than `0x3ff` and the
   capacity fast path left the target flags and raw address unchanged;
3. `va-allocation-reclaim` if final flags bit 0 is clear;
4. `backing-pte` if final flags bit 0 is set.

The phase store retains the first two samples in each of the four failure classes and
increments atomic lifetime counters after every completed failed native call, even
after a sample buffer fills. Successful outer calls classify as `none` and do not
enter failure counts or sample buffers, including a legal success with flags `0x21`
and raw GPU virtual address zero. The observation worker emits at most eight field records
and 32 phase summaries. Its phase-summary cadence is independent of the original
trace-summary budget and emits on initial readiness and after phase-count activity
settles, so the aggregate remains visible after the original sample buffers fill.
Each summary's `total` is the sum of the four failure-class counters and reports
per-class sample drops. Together with the existing trace, the
submission diagnostic has an explicit maximum of 174 critical records within the
512-record channel. The sample's `thread` value is only the kernel worker/callback
thread token; it does not establish an issuer PID, probe nonce, or one-to-one probe
association.
