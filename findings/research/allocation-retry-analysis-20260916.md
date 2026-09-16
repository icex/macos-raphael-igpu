# Native video-memory allocation failures: caller and retry analysis

This began as an offline audit of exact 24G830 code and retained candidate 280 artifacts.
The live follow-up below now demonstrates successful reclaim/retry under pressure.
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

## Live follow-up: recovered requests, not a standalone correctness blocker

Run `dd5c30a35fea14f9be511dee92ff85be`, candidate 280 / addressreuse, used native
IOAccelerator DTrace probes; no routed AMD entry or guest security setting changed.
The first 20-second panel window recorded 29 failed and 48 successful video-memory
wire calls. Failed stacks included 24 calls from `freeWaitToPrepareVidMap`, three
from AMD batch mapping, and two from generic resource prepare. No fallback return
was observed in that window. A second warm panel window saw one successful reclaim
with no nested failure; that alone did not resolve the first window's failures.

A linked trace then surrounded a 192 MiB live-buffer workload (16 MiB buffers, four
sets, one warmup and four measured rounds). It tracks native map prepare by thread
and nesting depth, saves its failed-wire count, and links the same map/thread to
subsequent reclaim entry/return. Observed: **81 reclaim calls, 41 true and 40 false,
with 1,525 failed wire attempts inside them**. All 40 false reclaim returns were
followed by a true return for the same thread/map; no failed pair remained at trace
end. Some successful calls required hundreds of internal attempts.

The independent CPU oracle checked 67,108,864 measured values with zero errors.
Allocation returned from 201,969,664 bytes to exactly 544,768 bytes every measured
round. The desktop remained responsive and the post-pressure raw RFB capture was
clean. No DTrace error/drop warning occurred in the successful capture.

The first linked script was rejected by DTrace for a forward self-reference before
its child workload ran. It was corrected and the passing capture is specifically
`reclaim-linked2-output.txt`, not the first attempt.

**Conclusion:** these observed requests recover through native reclamation. The
log message alone is no longer a reproduced correctness blocker for these workloads.
Do not suppress it or change allocator policy merely because it says ERROR. The
trace does not assign every map to a client PID, prove physical fragmentation,
prove every historical error recovered, or measure production performance. DTrace
and verbose serial logging affect timings; reclaim cost remains a performance
question. [Run evidence](address-reclaim-desktop-evidence-20260916.json).
