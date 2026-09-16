# Live status — 2026-09-16

**Candidate 280 passes longer buffer/address, explicit GPU-fence and broader desktop checks.**
The reproduced transparency corruption remains fixed. Native allocation errors were
traced to successful reclaim/retry in earlier pressure tests. The user now confirms
visible, crisp 1080p HiDPI with 4K backing at60Hz; lowering Apple Screen Sharing
quality improves responsiveness. Full desktop and physical display acceptance remain open.

## Current host / guest

Guest **stopped cleanly** after run `2456747451ac073cf5fa0ea1657590cf`,
candidate280/metal-127/retinarestore, MODE2#172, thirtieth exposure on boot
`2508eb6d-ddf3-497d-9774-00a7ecebe3ed`. GPU remains vfio-pci, power/control=on.
Baseline Metal passes; strict capture valid. Shutdown is `exited-after-guest-request`;
schema6 recovery authorizes relaunch, CP_STAT0, no forced inactive queues or dequeue
timeouts. User-visible Retina1080p/4K backing works, but Sunshine4K throughput fails
at3–4FPS. These are separate results. The deadline and LAN relay ended normally.
Candidate281/metal-129 is now live as described below; its logging patch did not install.

Sunshine v2026.914.233613 official Intel DMG is installed. VideoToolbox is selected
with software fallback disabled; startup detects H.264 and HEVC Main8. Its streaming
API responds as Raphael macOS on48989; the authenticated web interface responds
on48990. LAN relay previously served192.168.0.43:48989, with web UI on48990;
serverinfo200 and authenticated UI401 verified through the LAN address.
UFW rules now allow the guest TCP/UDP port family from192.168.0.0/24 onenp9s0;
other-device connectivity remains to be checked.
Moonlight playback now works, but the user reports only3–4FPS at4K.
Server timing independently sees43 completed encoder submissions in12s.
Active samples reach AMD hardware encode, while native video-memory reclamation
has calls up to464ms; allocation/encode throughput is the current blocker.
The latest reconnect still logsHEVC, so H.264 A/B is not yet verified. [Setup](docs/sunshine.md),
[artifact hashes](findings/research/sunshine-lan-20260916.json).
Requested90/120FPS client settings are distinct from the observed60Hz desktop.

Prior run `aaa3f63204f17d12bcb4a8d855774cf1` (MODE2#171/exposure29) produced a
user-observed black desktop after a mixed mode/default sequence; public-mode rollback
failed.90/120Hz requests left a60Hz fallback. It shut down and recovered cleanly,
all CP/active/forced/timeout counters0 and no host faults. Its archived helper is
superseded by the isolated60Hz-only version. Repeated33,423,360-byte allocation
failures were correlated, not causal proof; the newer positive user observation
retracts the broader claim that Retina itself fails.
[Retina investigation and correction](findings/research/remote-retina-20260916.md).

Prior managed ownership checks pass96 cases/111,658,032 pixel comparisons with
no mismatches. [Evidence](findings/research/texture-ownership-20260916.md).

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
| Host regression | 961 tests OK, three skipped; final UDP relay burst/cleanup check also passes |

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
The remote4k and retinarestore exposure allowances are consumed. No additional
GPU exposure allowance is active. The current restore run remains supervised;
The user explicitly requested restoring the earlier working4K Retina at60Hz
on this fresh guest, excluding90/120Hz. This authorizes one bounded60Hz-only
configuration sequence on current boot `2508eb6d-ddf3-497d-9774-00a7ecebe3ed`
and existing exposure30, then read-only/functional checks. Avoid redundant public
mode switches; keep identity, capture, supervision and cleanup gates unchanged.
The previous mixed sequence did not isolate Retina itself as the cause. In the
fresh60Hz-only session, the user confirms visible/crisp Retina while standard RAW
RFB capture is black: that capture path cannot be treated as a universal desktop
oracle at this mode. Lowering Apple Screen Sharing quality improved responsiveness.
The user explicitly requested Sunshine/Moonlight installation and60/90/120FPS
choices; prepare those on the current supervised guest, preserving existing host
Sunshine and the original shutdown deadline. Desktop timings remain separately
measured; do not label client FPS choices as proven panel refresh.

Next: isolate and fix the measured4K encode/reclamation stalls,
keeping the user-confirmed Retina60Hz desktop. Use native-source analysis and the
optional4K readback probe if a rendering failure is reproduced.
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


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-280-attempt-remote4k-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`

## Prepared next experiment: allocation diagnostic budget

Candidate281 / metal-129 is being prepared; it is not yet deployed. Source timings
implicate the single native allocation-failure diagnostic in4K throughput stalls.
Only that guarded call site is redirected to first8/every1024 cumulative sampling;
no allocator outcome, reservation, timeout, global logger or recovery policy changes.
The current280 session stopped through its existing stop-file/cleanup path.
After clean recovery, authorize exactly one candidate281 exposure on host boot
`2508eb6d-ddf3-497d-9774-00a7ecebe3ed` (prospective31st exposure), via tools/cycle.py
and a fresh MODE2 receipt. This is the user-requested fix/test continuation, not
an extension of the current guest deadline. Retain4K Retina60Hz and Sunshine setup.

Candidate281 first staging attempt (`alloclog`) stopped before QEMU/VFIO exposure:
missing attempt-specific build identities. MODE2#173 was clean; no GPU ledger
entry consumed. Retry uses the already verified base candidate281 namespace;
the named-boot prospective31st exposure allowance above remains available.

## Candidate281 live result — logging hypothesis not yet tested

Run `b29d3de37f74516698178fda2301f9d9`, MODE2#174, exposure31 on the
named boot above. Build `d7ff9eef7f5e46c5b5be269655c9af10`. Baseline Metal
probe completes; live capture continues and shutdown/recovery remain pending.
`ALLOCLOG: guarded=1 installed=0 original=0`: unchanged3–4FPS cannot assess
the logging hypothesis. DTrace byte reads identify the CALL through `ff25`
RIP-relative import stub to `kernel`kprintf`, so direct-symbol equality was wrong.
Exact evidence: candidate-281-results/alloclog-bytes2-output.txt,
alloclog-stub-output.txt and alloclog-stub-detail-output.txt. Earlier reads using
unslid/wrong-image addresses are invalid diagnostics, not GPU faults; one unbounded
DTrace BEGIN failure was explicitly interrupted via authenticated SSH. Relay works.
Retina login job exited0 but backing reverted1080p; one manual60Hz-only configuration
restored1920x1080 logical/3840x2160 backing. Login durability remains open.
Sunshine LAN relay restored; user reconfirms3–4FPS. Candidate282 will validate the
import stub before installing the same bounded diagnostic sampling change.

## Candidate282 bounded follow-up allowance

After candidate281 clean shutdown/recovery, authorize exactly one prospective32nd
GPU exposure on boot `2508eb6d-ddf3-497d-9774-00a7ecebe3ed`, via tools/cycle.py
and a fresh MODE2 reset. Candidate282/metal130 validates the observed native
kprintf import thunk before redirecting the same five-byte CALL. No allocator
behavior or global logging changes. Build `7a26b1a2f6694ae88ed889105de30bc7`,
source `d1f336dc31e3116e3a337c76d6a331d3cf88ed59`, executable SHA256
`9c7e5dffc64fef69e874ea3c8e7b940e9761caf53e31400d2dc68d1591724fc2`.
This user-requested performance-fix continuation requires installed=1 before
interpreting throughput. Preserve4K Retina60Hz and existing recovery/capture gates.
The final281 encoder timing window was idle after client disconnect and yielded
no samples; it is not performance evidence.
