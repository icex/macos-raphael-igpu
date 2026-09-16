# Bounded Metal resource reclamation — 2026-09-16

Candidate 280 run `0795287602bef3497900423ebc89a178` passes process-local buffer
reclamation and data-integrity checks. This is an M5 milestone, not complete memory
qualification.

## Method and observed result

`tests/resource_reclamation_probe.m` selects the exact GPU registry ID, then performs
three warmup rounds and 32 measured rounds. Each round creates a command queue and
four sets of 4 MiB managed input, private intermediate and managed output buffers:
48 MiB of live resources. Distinct per-round/per-buffer CPU patterns are copied
managed → private → managed; outputs are synchronized and every 32-bit value is
checked after command completion. The round's objects leave their autorelease pool
before allocation is sampled. GPU waits are bounded at 20 seconds; the entire probe
has a 150-second alarm.

All **134,217,728 measured values** match. Every measured round reports:

- Peak `currentAllocatedSize`: **50,974,720 bytes**.
- After release: **544,768 bytes**, exactly the post-warmup baseline.
- Settling sample: first 100 ms poll, within the two-second bound.

The predeclared acceptance tolerance was 4 MiB; observed residual growth is zero.
All three warmups also pass their data checks. PerfPowerServices remains 0.0% CPU
with 0.74 seconds cumulative CPU time on this fourth fresh guest boot using the
corrected QEMU image, on the same host boot.

## Scope and remaining work

Metal's `currentAllocatedSize` is process-local resource accounting. Returning to
baseline does not prove physical VRAM, kernel backing allocations or GPU virtual
addresses were globally reclaimed, nor does it rule out long-duration leaks. RSS is
recorded as auxiliary evidence and is not the reclamation oracle. The tested path
is managed/private buffer blits; textures, IOSurfaces, multiple queues and crash
reclamation require separate coverage. The earlier 48-case feedback test supplies
bounded concurrent-client correctness evidence, not these missing measurements.

Build `51bfd732cf824249b70981f0c36fe314`; host boot
`2508eb6d-ddf3-497d-9774-00a7ecebe3ed`; fresh MODE2 #157; seventeenth exposure.
No driver changes from the previously qualified candidate 280 build.
Results: `/home/bogdan/macos-vm/run/candidate-280-attempt-reclamation-results`.

## Capture, cleanup and overall result

The desktop Metal baseline passes with a WindowServer accelerator client. Final
acknowledged critical snapshot 5 contains 370 records with zero loss. Guest-request
shutdown completes; schema 6 recovery authorizes launch, CP_STAT=0, active_after=0,
forced_inactive=0. Overall **CORE_PROBE_PASS**. This is the second complete clean
candidate 280 lifecycle on this host boot. Earlier lossy runs remain failed capture
qualification. [Artifact hashes](resource-reclamation-evidence-20260916.json).
