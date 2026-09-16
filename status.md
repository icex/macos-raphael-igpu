# Live status — 2026-09-16

**Candidate 280 passes longer buffer/address, explicit GPU-fence and broader desktop checks.**
The reproduced transparency corruption remains fixed. Native allocation errors were
traced to successful reclaim/retry under pressure; the message alone is not a
reproduced correctness blocker. Full desktop and physical display acceptance remain open.

## Current host / guest

Guest **stopped** after supervised HMP quit in run
`042d7770f42059319cda491e50396bd8`, candidate280/metal-128/closure,
MODE2#161, twentieth exposure on boot `2508eb6d-ddf3-497d-9774-00a7ecebe3ed`.
GPU remains vfio-pci, power/control=on. Probe passed; closure receipt confirms stop.
Strict capture is incomplete (snapshot14 transport tail), so overall **INVALID**.
Existing recovery policy authenticates snapshot13/374 records and returns schema6
`recovered`, `authorizes_launch=true`: five queues dequeued, zero forced clears or
timeouts, CP_STAT=0, graphics retirement confirmed, no recovery host faults.
This is positive abnormal-closure cleanup evidence, not clean guest shutdown or
full lifecycle qualification. [Result](findings/research/supervised-qemu-closure-result-20260916.md).

## Verified progress

| Area | Evidence and scope |
|---|---|
| Buffer/address reuse | 512 measured rounds, 2,147,483,648 correct values; all 6,144 measured address assignments reused earlier ranges; allocation returns exactly to 544,768 bytes |
| Larger allocations | 192 MiB live resources, four measured rounds, 67,108,864 correct values, exact allocation return |
| Native reclaim | 81 traced calls: 41 true, 40 false; all 40 false returns followed by same-thread/map success; 1,525 internal wire failures observed |
| GPU fences | 128 untracked blit/compute/blit rounds, 134,217,728 correct values; prior cross-queue shared-event checks also pass |
| Native desktop | Three minutes of moving/resizing native material windows; four clean raw RFB captures |
| Safari | Two-minute transparency/blur/scrolling page; three clean captures plus clean desktop after larger-buffer pressure |
| PerfPowerServices | 0.0% CPU, latest 1.04 s cumulative; corrected QEMU on six guest boots, all on one host boot |
| Host regression | 948 tests OK, three skipped |

Earlier texture recreation (144 cases / 131,031,576 pixels), feedback rendering
(48 cases / 5,280,000 pixels), and hardware H.264/HEVC encode/decode retain their
separately documented passing scopes. Explicit decoder GPU-ID selection remains
unresolved; automatic required-hardware selection works. No new codec claim this run.

Driver build `51bfd732cf824249b70981f0c36fe314`; executable SHA256
`7d06082f35959f900b5c59cb5f6d9e2efc67df13e935d338d7783524df63259b`.
QEMU image `sha256:51cbd7dcdbad2d6492ce83a263e9854c28620d67a1ea12ebc0562c6fab2605ad`.
[Latest qualification](findings/research/address-reclaim-desktop-20260916.md),
[artifact hashes](findings/research/address-reclaim-desktop-evidence-20260916.json),
[native retry analysis](findings/research/allocation-retry-analysis-20260916.md),
[visual fix](findings/research/feedback-decompression-20260916.md).

## Next work / remaining gates

1. Fresh workload after recovered QEMU closure; retain strict capture and recovery rules.
2. Guest-crash/command-channel failure and independent-host-boot qualification.
3. Broader applications, formats, render hazards and interprocess synchronization;
   page-table release beyond cached address reuse; reclamation performance cost.
4. Physical DCN output and measured performance. Historical direct OpenGL hang and
   live-validation crash remain unresolved; do not repeat without diagnosis.

No main merge/push before full desktop proof. Another exposure needs a named-boot
allowance and fresh MODE2 through tools/cycle.py. No vfio→amdgpu cycling.
[Roadmap](docs/ROADMAP.md).

## Next exposure allowance — post-closure workload

One additional exposure (twenty-first) on boot
`2508eb6d-ddf3-497d-9774-00a7ecebe3ed` for unchanged candidate280/metal-127,
attempt postclosure. Hypothesis: authorizing abnormal-closure recovery permits
fresh MODE2 and successful desktop/core execution followed by clean shutdown.
Falsified by reset, workload, capture, host-fault or recovery failure. Use cycle.py,
up to 6000 seconds; all existing gates intact, no vfio→amdgpu cycling.
