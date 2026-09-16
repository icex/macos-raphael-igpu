# Live status — 2026-09-16

**Candidate 280 passes longer buffer/address, explicit GPU-fence and broader desktop checks.**
The reproduced transparency corruption remains fixed. Native allocation errors were
traced to successful reclaim/retry under pressure; the message alone is not a
reproduced correctness blocker. Full desktop and physical display acceptance remain open.

## Current host / guest

Guest **stopped** after run `2afa3401a71e99091aa8bdbd14c50fa7`,
candidate280/metal-127/iosurfaceprocess, MODE2#165, twenty-fourth exposure on boot
`2508eb6d-ddf3-497d-9774-00a7ecebe3ed`. GPU remains vfio-pci, power/control=on.
Two-process IOSurface:32 bidirectional rounds,49,363,648 correct pixels.
Baseline desktop probe/capture pass;370 critical records, no capture loss.
Guest-request shutdown; schema6 recovered/authorizes_launch=true, CP_STAT=0,
no forced clears/timeouts or recovery host faults. Overall **CORE_PROBE_PASS**.
[IOSurface evidence](findings/research/iosurface-process-20260916.md).
Prior depth/stencil/color resolve:128 cases,49,625,792 correct pixels.
[Depth/stencil evidence](findings/research/depth-stencil-20260916.md).

Prior Main10 decode:32 frames720p/1080p,71,884,800 luma/chroma values exactly
match software; hardware encoder advertises Main8 only and rejects Main10.
[Main10 evidence](findings/research/main10-qualification-20260916.md).
One abnormal-QEMU-closure/recovery/relaunch/workload/clean-shutdown sequence passes
its scoped checks; closure run itself remains INVALID for truncated terminal capture.
[Lifecycle evidence](findings/research/supervised-qemu-closure-result-20260916.md).

## Verified progress

| Area | Evidence and scope |
|---|---|
| Two-process IOSurface | 32 bidirectional GPU-copy rounds;49,363,648 pixels, zero mismatches; host completion orders transfers |
| Depth/stencil/MSAA | 128 cases at1×/4× and64×64/1003×769;49,625,792 correct pixels |
| Main10 decode | 32 frames, 720p/1080p, 71,884,800 full-plane luma/chroma samples, exact software-reference match |
| Buffer/address reuse | 512 measured rounds, 2,147,483,648 correct values; all 6,144 measured address assignments reused earlier ranges; allocation returns exactly to 544,768 bytes |
| Larger allocations | 192 MiB live resources, four measured rounds, 67,108,864 correct values, exact allocation return |
| Native reclaim | 81 traced calls: 41 true, 40 false; all 40 false returns followed by same-thread/map success; 1,525 internal wire failures observed |
| GPU fences | 128 untracked blit/compute/blit rounds, 134,217,728 correct values; prior cross-queue shared-event checks also pass |
| Native desktop | Three minutes of moving/resizing native material windows; four clean raw RFB captures |
| Safari | Two-minute transparency/blur/scrolling page; three clean captures plus clean desktop after larger-buffer pressure |
| PerfPowerServices | 0.0% CPU, latest 0.73 s cumulative; corrected QEMU on ten measured guest boots, all on one host boot |
| Host regression | 948 tests OK, three skipped |

Earlier texture recreation (144 cases / 131,031,576 pixels), feedback rendering
(48 cases / 5,280,000 pixels), and hardware H.264/HEVC encode/decode retain their
separately documented passing scopes. Explicit decoder GPU-ID selection remains
a selection limitation on the built-in topology; automatic required-hardware selection works.

Driver build `51bfd732cf824249b70981f0c36fe314`; executable SHA256
`7d06082f35959f900b5c59cb5f6d9e2efc67df13e935d338d7783524df63259b`.
QEMU image `sha256:51cbd7dcdbad2d6492ce83a263e9854c28620d67a1ea12ebc0562c6fab2605ad`.
[Address/desktop qualification](findings/research/address-reclaim-desktop-20260916.md),
[artifact hashes](findings/research/address-reclaim-desktop-evidence-20260916.json),
[native retry analysis](findings/research/allocation-retry-analysis-20260916.md),
[visual fix](findings/research/feedback-decompression-20260916.md).

## Next work / remaining gates

1. Guest-crash/command-channel failure, repeated lifecycle and independent-host-boot qualification.
2. Broader applications, formats, render hazards and interprocess synchronization;
   page-table release beyond cached address reuse; reclamation performance cost.
3. Physical DCN output and measured performance. Historical direct OpenGL hang and
   live-validation crash remain unresolved; do not repeat without diagnosis.

No main merge/push before full desktop proof. Another exposure needs a named-boot
allowance and fresh MODE2 through tools/cycle.py. No vfio→amdgpu cycling.
[Roadmap](docs/ROADMAP.md).

## Active offline work

Using the supplied decompilation plus matching native assembly to trace physical
display initialization. Current injected ROM contains four nonzero display paths;
empty published framebuffer properties do not prove an empty ATOM table. Boot parser
reads EFI properties from the PCI service; trace boot-display selection before patches.
Main10 decode is now qualified within the short synthetic scope above. Main10
hardware encoding remains unavailable in the native advertised profile set.
Two-process IOSurface visibility now passes within its host-ordered scope.
Next work: GPU-only interprocess events, broader formats/hazards and longer
workloads, plus source-guided physical-display/lifecycle investigation. No next
exposure allowance recorded yet.

Latest offline display audit: clock warnings return fallback frequencies; later
register polls exhaust. Native logger console filtering hides their caller details.
[Source/native audit](findings/research/display-clock-wait-20260916.md); exact wait
register/caller and startup link state remain the next discriminator.
