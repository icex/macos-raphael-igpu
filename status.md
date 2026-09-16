# Live status — 2026-09-16

**Candidate 280 passes longer buffer/address, explicit GPU-fence and broader desktop checks.**
The reproduced transparency corruption remains fixed. Native allocation errors were
traced to successful reclaim/retry under pressure; the message alone is not a
reproduced correctness blocker. Full desktop and physical display acceptance remain open.

## Current host / guest

Guest **stopped** after run `f846abef4a573a0059fbe0ecdd28ecfc`,
candidate280/metal-127/main10, MODE2#163, twenty-second exposure on boot
`2508eb6d-ddf3-497d-9774-00a7ecebe3ed`. GPU remains vfio-pci, power/control=on.
Baseline desktop probe/capture pass;398 critical records, no capture loss.
Guest-request shutdown; schema6 recovered/authorizes_launch=true, CP_STAT=0,
no forced clears/timeouts or recovery host faults. Overall **CORE_PROBE_PASS**.

Main10 hardware decode passes32 frames at720p/1080p,71,884,800 luma/chroma samples
exactly matching software reference. Main10 hardware encode is rejected before frames;
native hardware encoder advertises Main8 only. Prior Main8 encoding remains valid.
[Main10 evidence](findings/research/main10-qualification-20260916.md).
One abnormal-QEMU-closure/recovery/relaunch/workload/clean-shutdown sequence also
passes its scoped checks; the closure run itself remains INVALID for truncated capture.
[Lifecycle evidence](findings/research/supervised-qemu-closure-result-20260916.md).

## Verified progress

| Area | Evidence and scope |
|---|---|
| Main10 decode | 32 frames, 720p/1080p, 71,884,800 full-plane luma/chroma samples, exact software-reference match |
| Buffer/address reuse | 512 measured rounds, 2,147,483,648 correct values; all 6,144 measured address assignments reused earlier ranges; allocation returns exactly to 544,768 bytes |
| Larger allocations | 192 MiB live resources, four measured rounds, 67,108,864 correct values, exact allocation return |
| Native reclaim | 81 traced calls: 41 true, 40 false; all 40 false returns followed by same-thread/map success; 1,525 internal wire failures observed |
| GPU fences | 128 untracked blit/compute/blit rounds, 134,217,728 correct values; prior cross-queue shared-event checks also pass |
| Native desktop | Three minutes of moving/resizing native material windows; four clean raw RFB captures |
| Safari | Two-minute transparency/blur/scrolling page; three clean captures plus clean desktop after larger-buffer pressure |
| PerfPowerServices | 0.0% CPU, latest 0.75 s cumulative; corrected QEMU on eight measured guest boots, all on one host boot |
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
Next work: depth/stencil/MSAA, interprocess visibility and broader workloads,
plus source-guided physical-display and lifecycle investigation.

## Next exposure allowance — depth/stencil and resolve

One additional exposure (twenty-third) on boot
`2508eb6d-ddf3-497d-9774-00a7ecebe3ed`, unchanged candidate280/metal-127,
attempt depthstencil. Hypothesis: depth/stencil state transitions and1×/4× color
resolve preserve a CPU-predicted left/right image, including odd dimensions.
128 cases;20s command waits and180s process alarm. Source setDepthStencilState
also updates native primitive binning; existing global no-binning guard remains.
Compile first; unsupported samples, shader/command failure or any mismatched pixel
leaves this scope unqualified. Use cycle.py fresh MODE2 and all standard6000s
supervision/capture/host-fault/shutdown/recovery guards. No vfio→amdgpu cycling.
