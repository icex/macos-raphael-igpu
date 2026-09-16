# Texture reclamation, global accounting and GPU events — 2026-09-16

Candidate 280 run `5a2f13feed4b7922fd6d109860befda0` extends M5 qualification with
three passing workloads. The driver binary is unchanged: build
`51bfd732cf824249b70981f0c36fe314`. Host boot
`2508eb6d-ddf3-497d-9774-00a7ecebe3ed`, eighteenth exposure, fresh MODE2 #158.

## Texture and IOSurface recreation

`tests/texture_reclamation_probe.m` exercises private, managed and IOSurface-backed
textures, BGRA8Unorm and RGBA8Unorm, at 1024×1024 and 1003×769. Row pitch is rounded
to 256 bytes; the odd-width case checks untouched padding as well as every pixel.
Each case uploads a distinct CPU pattern on one queue, waits for completion,
reads back on a second queue and synchronizes the managed output for CPU access.
This part uses host ordering; it does not claim GPU-only synchronization.

Each process runs one 12-case warmup followed by four measured cycles. Seed 13 runs
alone; seeds 23 and 47 run in separate concurrent processes. Every allocation has a
CPU oracle incorporating seed, cycle, storage, format and size. GPU completion has
a 20-second bound and each process has a 180-second alarm.

**144 measured cases / 131,031,576 pixels pass**, with zero pixel and row-padding
errors. The 36 additional warmup cases also pass. Each process's peak Metal
`currentAllocatedSize` is 13,377,536 bytes; every measured release returns to the
same 614,400-byte baseline. The acceptance tolerance was 4 MiB and the observed
residual growth is zero. IOSurface ownership ends with the case's autorelease pool;
its allocation size is recorded separately from Metal's accounting.

## Global accounting: measured response and limits

The exact matching accelerator's `PerformanceStatistics` and
`PerformanceStatisticsAccum` are sampled while resources are live and after release.
A separate read-only IOKit probe, `tests/gpu_memory_statistics_probe.m`, takes 20
half-second samples after all texture clients exit, without creating a Metal client.

| Counter (bytes) | Before workload | During workload range | After clients exit range |
|---|---:|---:|---:|
| vramFreeBytes | 173,727,744 | 105,070,592–173,727,744 | 173,195,264 |
| inUseVidMemoryBytes | 183,681,024 | 183,562,240–209,358,848 | 183,463,936–184,274,944 |
| orphanedReusableVidMemoryBytes | 11,603,968 | 11,497,472–72,998,912 | 11,542,528–12,353,536 |
| gartUsedBytes | 32,972,800 | 31,387,648–52,117,504 | 32,206,848–33,239,040 |

Non-reusable orphaned video and system-memory counters remain zero in all samples.
Free VRAM returns to within 532,480 bytes of its starting value. In-use video memory
and GART usage return to ranges containing their starting values. These observations
support bounded backing-memory reclamation, including retirement of much of the
reusable cache after process exit. They do not prove exact global accounting:
WindowServer and other clients remain active, samples are not atomic across counters,
and the workload is short. GPU virtual-address space reclamation is not measured.

Local decompilation provides a source lead for the counter:
`X6000-full/functions/00023cf8_AMDRadeonX6000_AMDAccelStatistics__writeInternalStats.c`
publishes `vramFreeBytes` from a native memory object's virtual call.
`00053688_AMDRadeonX6000_AMDHWMemory__totalFreeMemory.c` and
`0005342a_AMDRadeonX6000_AMDHWMemory__computeTotalFreeMemory.c` call
`IOAccelMemoryAllocator2::total_free`. The unresolved virtual-call association is
not a complete ABI proof; the workload's observed counter response is independent
evidence that these are not merely static advertised memory sizes.

## GPU-only cross-queue event ordering

`tests/queue_event_probe.m` holds three 4 MiB buffers and two command queues. The
consumer command buffer is committed first and waits on an MTLSharedEvent. Ten
milliseconds later the producer is committed; it copies the new CPU pattern into
a private buffer and signals the round's monotonically increasing event value.
Only after both buffers complete does the CPU verify the readback.

All **32 rounds / 33,554,432 values pass** with zero mismatches and the expected
signal value. This exercises consumer-before-producer ordering without an
intermediate host completion wait. It does not qualify interprocess event handles,
all compute/render hazards, untracked-resource fences, or multi-GPU synchronization.

## Existing allocation diagnostics remain an investigation item

Startup/baseline serial output contains `Failed to allocate size:16842752` messages
before the new texture probe. The same diagnostic family exists in the earlier
passing 280 and 280-reclamation captures (446 and 161 intact textual occurrences,
respectively; interleaving can hide additional messages). It is not a newly
introduced texture-test regression.

The local `000531b6_AMDRadeonX6000_AMDHWMemory__allocateLargeBlocks.c` emits this
message after its contiguous/non-contiguous allocation attempts fail, reports two
allocator free totals, and returns failure. The higher-level caller and any fallback
are not yet proven. Passing API readbacks do not resolve these allocation diagnostics,
and the message alone does not prove a leak or fatal GPU failure. Next discrimination:
correlate the failing request with its caller, allocation class and subsequent fallback
or API failure before changing allocator policy.

Results: `/home/bogdan/macos-vm/run/candidate-280-attempt-textures-results`.

## Capture and lifecycle

Identity and strict critical capture pass: final snapshot 18 contains 387 records,
zero drops/truncation. Guest exits after the requested shutdown. Schema 6 recovery
is recovered and authorizes launch, with CP_STAT=0, active_after=0 and no forced
HQD clears. Overall **CORE_PROBE_PASS**. This is the third complete candidate 280
lifecycle on this host boot; it does not qualify host reboot or crash recovery.
PerfPowerServices is 0.0% CPU / 0.77 seconds cumulative after the workloads.
Host regression suite: 938 tests OK, 3 skipped.
[Artifact and source hashes](texture-memory-and-events-evidence-20260916.json).
