# Live status — 2026-09-16

**Candidate 280 passes longer buffer/address, explicit GPU-fence and broader desktop checks.**
The reproduced transparency corruption remains fixed. Native allocation errors were
traced to successful reclaim/retry under pressure; the message alone is not a
reproduced correctness blocker. Full desktop and physical display acceptance remain open.

## Current host / guest

Guest **stopped** after run `964787995e1a5e34fcc7b651ae6c716b`,
candidate280/metal-127/ownership, MODE2#170, twenty-eighth exposure on boot
`2508eb6d-ddf3-497d-9774-00a7ecebe3ed`. GPU remains vfio-pci, power/control=on.
Managed texture ownership/LOAD checks pass:96 cases across two seeded processes,
111,658,032 pixel comparisons, no pixel or padding mismatches. RGBA8/BGRA8,
64×64/1003×769, explicit synchronization, partial CPU updates and retained color
contents; no IOSurface/depth extension implied. Raw1920×1080 desktop capture clean.
Strict capture valid:384 records/snapshot11; **CORE_PROBE_PASS**. Guest-request
shutdown and schema6 recovery pass, CP_STAT/active/forced clears/timeouts all0,
no host kernel faults. [Ownership evidence](findings/research/texture-ownership-20260916.md).

Stock QEMU10.1.2 with OpenCore/VirtualSMC1.3.7 remains the tested setup. Prior two
fresh guest boots verified one AppleSMC on VirtualSMC,69 keys/end-of-list,0.0%
PerfPowerServices CPU, hardware video and clean recovery. Ownership run adds a
third guest boot on this host boot; no new SMC/codec measurement in this run.
[SMC evidence](findings/research/smc-opencore-handoff-20260916.md),
[stock-QEMU setup](docs/stock-qemu-smc.md). Independent-host-boot durability remains open.

Prior Main10 decode:32 frames720p/1080p,71,884,800 luma/chroma values exactly
match software; hardware encoder advertises Main8 only and rejects Main10.
[Main10 evidence](findings/research/main10-qualification-20260916.md).
One abnormal-QEMU-closure/recovery/relaunch/workload/clean-shutdown sequence passes
its scoped checks; closure run itself remains INVALID for truncated terminal capture.
[Lifecycle evidence](findings/research/supervised-qemu-closure-result-20260916.md).

## Verified progress

| Area | Evidence and scope |
|---|---|
| Managed texture ownership | 96 cases;111,658,032 pixel comparisons; synchronized CPU writes and retained LOAD color contents, zero mismatches |
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
| Stock QEMU / PerfPowerServices | OpenCore/VirtualSMC fix passes two guest boots,0.0% CPU, latest0.86s; prior patched-QEMU evidence retained separately |
| Host regression | 958 tests OK, three skipped |

Earlier texture recreation (144 cases / 131,031,576 pixels), feedback rendering
(48 cases / 5,280,000 pixels), and hardware H.264/HEVC encode/decode retain their
separately documented passing scopes. Explicit decoder GPU-ID selection remains
a selection limitation on the built-in topology; automatic required-hardware selection works.

Driver build `51bfd732cf824249b70981f0c36fe314`; executable SHA256
`7d06082f35959f900b5c59cb5f6d9e2efc67df13e935d338d7783524df63259b`.
Current stock QEMU image `sha256:3a3c82c79bc4e73531f819ccdfa4053b3084efd7c1f645678dbf8b4b3a24369c`.
Default experiment pin now selects this stock image. VirtualSMC1.3.7/gen2 and the
exact OpenCore DSDT ownership patch are required; prior media backups remain available.
[Address/desktop qualification](findings/research/address-reclaim-desktop-20260916.md),
[artifact hashes](findings/research/address-reclaim-desktop-evidence-20260916.json),
[native retry analysis](findings/research/allocation-retry-analysis-20260916.md),
[visual fix](findings/research/feedback-decompression-20260916.md).

## Next work / remaining gates

1. Full3840×2160 Screen Sharing: mode exposure, actual backing/capture pixels,
   composition correctness and separately measured remote frame delivery. User priority2026-09-16.
2. Guest-crash/command-channel failure, repeated lifecycle and independent-host-boot qualification.
3. Broader applications, formats, render hazards and interprocess synchronization;
   page-table release beyond cached address reuse; reclamation performance cost.
4. Physical DCN output and measured performance. Historical direct OpenGL hang and
   live-validation crash remain unresolved; do not repeat without diagnosis.

The user requested publication of the current `dev` snapshot to `main` on2026-09-16.
Development continues on `dev`; full desktop qualification remains open. Another
exposure needs a named-boot allowance and fresh MODE2 through tools/cycle.py.
No vfio→amdgpu cycling.
[Roadmap](docs/ROADMAP.md).

## Current work

The immediate patched-QEMU dependency is removed for the tested setup. Compatibility
now lives in OpenCore/VirtualSMC, with no new RaphaelGPU driver patch. README, roadmap
and the general QEMU guide describe the stock setup and scoped native results.
The ownership allowance is consumed. One additional exposure is allowed on boot
`2508eb6d-ddf3-497d-9774-00a7ecebe3ed` for candidate280/metal-127/remote4k,
exposure29 if VFIO opens. Test a reversible60-second CGVirtualDisplay at3840×2160
and, if successful,1920×1080 HiDPI with3840×2160 backing. Hypothesis: the fallback
virtual display mode list, rather than an accelerator limit, explains the1080p
ceiling. Refused creation, incorrect backing dimensions, unusable capture or failed
removal blocks this approach; no native driver patch is included. The user additionally requested1080p HiDPI
as the default and60/90/120Hz choices; investigate those timings within this
exposure and install only a verified, reversible user-session default. Preserve lower-resolution fallback. Use tools/cycle.py with fresh
MODE2 CP_STAT=0/RLC_CNTL=0 and all identity/capture/shutdown/recovery gates intact.

Next: bounded feasibility for full4K/Retina Screen Sharing, per the user’s request;
if it needs a substantial detour, return to the remaining roadmap.
Broader configurations, lifecycle, rendering tests and physical output follow. The Reims CPU/GPU ownership task now passes its managed-texture scope.
Visual-oracle, plane/view/depth and heap-alias tests remain open.
[Audit](findings/research/reims-vgpu-audit-20260916.md).

Physical output remains source-guided work: clock warnings fall back; later register
polls exhaust, with caller details filtered from serial. Exact wait register/caller
and startup link state remain unobserved. Broader applications, formats, performance
and crash/fallback durability remain open. Other hypervisors are unqualified.

Milestones update README/status/roadmap, push dev and fast-forward the clean local dev
checkout. Main remains the user-published experimental snapshot; development is on dev.

## Licensing review — 2026-09-16

BSD-3-Clause and third-party notices added. Both KDK-extracted TOC patterns have
exact matches in pinned AMD linux-firmware files; vendor-only generation is
proposed, not implemented. SDK terms, executable notices and broader provenance
remain open. [Audit](findings/research/licensing-audit-20260916.md). No hardware run
or functional qualification change.


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-280-attempt-ownership-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`
