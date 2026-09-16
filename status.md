# Live status — 2026-09-16

**Candidate 280 passes longer buffer/address, explicit GPU-fence and broader desktop checks.**
The reproduced transparency corruption remains fixed. Native allocation errors were
traced to successful reclaim/retry under pressure; the message alone is not a
reproduced correctness blocker. Full desktop and physical display acceptance remain open.

## Current host / guest

Guest **stopped** after run `11879a5f49bb2cece67bdbcf31d8c308`,
candidate280/metal-127/xpcevent2, MODE2#167, twenty-fifth exposure on boot
`2508eb6d-ddf3-497d-9774-00a7ecebe3ed`. GPU remains vfio-pci, power/control=on.
XPC-imported GPU event:one preliminary plus32 extended consumer-first transfers,
25,453,131 correct pixels. All helpers acknowledged shutdown and became absent.
Baseline/capture pass,382 critical records; clean guest-request shutdown and schema6
recovered/authorizes_launch=true, CP_STAT=0, no forced clears/timeouts/host faults.
Overall **CORE_PROBE_PASS**. [XPC event evidence](findings/research/xpc-event-20260916.md).
Prior host-ordered two-process IOSurface and depth/stencil/MSAA checks also pass.

Prior Main10 decode:32 frames720p/1080p,71,884,800 luma/chroma values exactly
match software; hardware encoder advertises Main8 only and rejects Main10.
[Main10 evidence](findings/research/main10-qualification-20260916.md).
One abnormal-QEMU-closure/recovery/relaunch/workload/clean-shutdown sequence passes
its scoped checks; closure run itself remains INVALID for truncated terminal capture.
[Lifecycle evidence](findings/research/supervised-qemu-closure-result-20260916.md).

## Verified progress

| Area | Evidence and scope |
|---|---|
| Cross-process GPU events | Typed XPC import;33 consumer-first transfers,25,453,131 correct pixels |
| Two-process IOSurface | 32 bidirectional GPU-copy rounds;49,363,648 pixels, zero mismatches; host completion orders transfers |
| Depth/stencil/MSAA | 128 cases at1×/4× and64×64/1003×769;49,625,792 correct pixels |
| Main10 decode | 32 frames, 720p/1080p, 71,884,800 full-plane luma/chroma samples, exact software-reference match |
| Buffer/address reuse | 512 measured rounds, 2,147,483,648 correct values; all 6,144 measured address assignments reused earlier ranges; allocation returns exactly to 544,768 bytes |
| Larger allocations | 192 MiB live resources, four measured rounds, 67,108,864 correct values, exact allocation return |
| Native reclaim | 81 traced calls: 41 true, 40 false; all 40 false returns followed by same-thread/map success; 1,525 internal wire failures observed |
| GPU fences | 128 untracked blit/compute/blit rounds, 134,217,728 correct values; prior cross-queue shared-event checks also pass |
| Native desktop | Three minutes of moving/resizing native material windows; four clean raw RFB captures |
| Safari | Two-minute transparency/blur/scrolling page; three clean captures plus clean desktop after larger-buffer pressure |
| PerfPowerServices | 0.0% CPU, latest 0.76 s cumulative; corrected QEMU on eleven measured guest boots, all on one host boot |
| Host regression | 953 tests OK, three skipped |

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

## Current work

User priority: remove the patched-QEMU SMC dependency through an OpenCore/guest
solution, then validate on stock QEMU and separately qualify other hypervisors.
Current OpenCore has VirtualSMC disabled; native source detects and avoids an
already active SMC device, so enabling the kext blindly is not a demonstrated fix.
The README now summarizes current capabilities, goals and setup; detailed evidence
remains here and in the roadmap. General QEMU setup examples are published, with
CPU-only paused-QEMU configuration validation. No new GPU allowance is recorded.

Parallel Reims source audit completed at pinned commit `69a57dd69a6958e946c03b73e02db331f330f435`.
Reviewed test designs now inform open visual, CPU/GPU ownership, plane/view/depth
and heap-alias roadmap tasks. No external code imported, GPU run or new functional
qualification. Reims still requires custom QEMU and does not fix SMC enumeration.
[Audit and provenance](findings/research/reims-vgpu-audit-20260916.md).

Physical output remains source-guided work: clock warnings fall back; later register
polls exhaust, with caller details filtered from serial. Exact wait register/caller
and startup link state remain unobserved. Broader applications, formats, performance,
independent boots and crash/fallback durability remain open.

Milestones must update README/status/roadmap, push dev and fast-forward the clean
local dev checkout; preserve unrelated changes and stashes.
