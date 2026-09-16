# Native video-memory allocation failures: caller and retry analysis

This is an offline audit of exact 24G830 code and retained candidate 280 artifacts.
It identifies real failed internal requests and available recovery paths. It does
not establish a memory leak, nor prove that every failure was recovered.

## Observed requests

`candidate-280-attempt-textures-results/wrapper-result.json` retains four failures
from the existing `AMDAccelVidMemory::allocPhysical` observer. The first requested
0x1010000 (16,842,752) bytes; the following three requested 0x1000000 bytes on the
same backing object/thread. Their allocation element was zero before and after;
flags were 0x1010007, pool index zero. The retained summary reached 981 successful
and 282 failed calls. Only four detailed failure samples were retained (278 later
samples omitted by that bounded observer). This is distinct from critical-stream
loss: critical capture itself had zero dropped/truncated records.

The ordinary serial diagnostic initially reports less free memory than requested,
then repeated 16 MiB failures with increasing free totals. That is compatible with
reclaim/retry activity but does not identify each caller's eventual result.

## Exact native dispatch

[Binary identity and extracted vtable slots](allocation-vtable-20260916.json)
resolve AMDHWMemory's slot +0x180 to `allocateLargeBlocks` at X6000 +0x531b6.
`AMDAccelVidMemory::allocPhysical` (+0x3aa76) calls this slot through its backend
pointer at +0x110 when flag bit 24 is set and bit 22 clear (with the other special
branches excluded). The captured 0x1010007 flags satisfy that path. The captured
+0x120 values are inputs; do not assign them an unproved high-level meaning.

`allocateLargeBlocks` first tries allocation mode 1, optionally mode 0, and then
noncontiguous allocations at several chunk sizes. After exhaustion it prints the
message and returns false. `allocPhysical` propagates failure. There is no system
memory migration within either function.

The lower allocator at X6000 +0x52e4a uses `IOAccelMemoryAllocator2::allocPages`
through backend +0x68. The separate +0x70 allocator is used for fixed reservations
and `canAllocate` trials. `safeFree` (+0x5351e) releases the ordinary allocation and
conditionally its fixed reservation. **Do not add free and fixed-free values as
independent available capacity.** Range, alignment and contiguity constraints also
apply; total free bytes alone cannot prove that this request should succeed.

## Higher-level recovery paths

The exact IOAcceleratorFamily2 sources are under
`/home/bogdan/macos-vm/re/roadmap-24G830/IOAcceleratorFamily2-full/functions/`:

- `IOAccelVidMemory::wire` (+0x561c0) calls video backing slot +0x1e8 and propagates
  failure. The AMD concrete slot resolves to +0x3aa76; the earlier
  `2026-09-metal-integration/report-backing-review.md` audits its ABI and mapping.
- `IOGraphicsAccelerator2::freeToPrepareMemory` (+0x3fd76) prunes orphaned video
  backing, attempts reclaim and retries, including forced/waiting paths.
- `freeWaitToPrepareVidMemory` (+0x402a8) scans the video-memory LRU and retries
  after reclaiming eligible, unprepared resources.
- `IOAccelResource2::prepare` (+0x272e6) and `prepareInTaskWithOption` (+0x27872)
  contain a fallback branch after preparation/reclaim failure.
- `IOAccelResource2::fallback` (+0x27ba6) creates fallback backing, finishes events,
  redirects active mappings and replaces the resource backing. Its
  `allocFallbackMemory` (+0x27b6a) constructs IOAccelSysMemory.
- AMD's fallback override (+0x15924) calls the inherited fallback and, on success,
  updates AMD-specific backing/auxiliary state.

These branches explain how an internal failed request can coexist with successful
Metal output. They do not prove which branch handled the retained runtime requests.

## Next discriminating observation

Correlate a failed backing request with its enclosing resource preparation and
subsequent successful retry or system-memory fallback, preserving object/thread
identity and nested-call semantics. Do not equate the last global commit event
with an outer call's final result. No allocator-policy patch is justified by the
current evidence alone.
