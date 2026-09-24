# Raphael iGPU acceleration roadmap

Updated 2026-09-24. Latest display experiment: **1.0.330** (correct-color HiDPI120 and HDMI audio confirmed); prior streaming baseline: **1.0.284**; broader baseline: **1.0.280**. Full desktop acceleration
is **not qualified**. The reproduced Screen Sharing transparency defect is fixed
in candidate279 and retained in280. Candidate280 also passes strict capture and
clean recovery after visual, concurrent-client and codec workloads. The patched-QEMU
SMC dependency is now removed for the tested configuration via OpenCore/VirtualSMC. Broader desktop, memory, lifecycle, physical-display and
performance qualification remain open.

This is the current roadmap. [Live state and run authority](../status.md) are separate.
The [previous roadmap](../findings/research/status-archives/roadmap-before-20260916-refresh.md)
preserves the candidate159–194 history and review decisions; its dated launch budgets
and “next experiment” instructions do not describe today's host.

CI portability (2026-09-17): install image-analysis dependencies, fetch historical
source contracts, and use temporary Lilu/KVM fixtures in host tests. The Linux
regression and macOS source-build jobs remain required; see [CI setup](releases.md).

## Progress and remaining gates

| Milestone | State | Evidence and remaining work |
|---|---|---|
| M0 — Experiment identity and supervision | Implemented; maintained | Immutable manifests, loaded-build checks, capture, deadlines and cleanup. Fixed cycle image selection so preparation and admission use the same pinned emulator. Host suite: 1023 tests, OK (3 skipped). |
| M1 — Controlled starting state | Demonstrated for current workflow | One-way amdgpu→vfio-pci handoff, power/control=on, fresh MODE2 and clean-state receipts. Broad independent-host-boot qualification remains open. |
| M2 — Native startup failure localization | Completed for original blocker | False second SDMA instance and subsequent channel routing were traced; historical evidence retained. |
| M3 — Native engine startup repair | Demonstrated | Raphael topology/address adaptations reach native startup and completed Metal work. Preserve these fixes while diagnosing desktop rendering. |
| M4 — First correct Metal compute | Achieved | Candidate 194 checked 196,608 values and 4,096 rendered pixels; its overall capture remained inconclusive. Current280 desktop Metal baselines complete with verified device/build identity. |
| M5 — Rendering, memory and synchronization | Partial | Managed-texture copy correction retained; private/managed/IOSurface and multiple-format readback probes pass. Candidate280 passes48 BGRA8 feedback cases across four distinct-seed processes, including two concurrent clients. 32 measured buffer-reclamation rounds return process-local allocation to baseline with134,217,728 correct values. 144 texture recreation cases and32 cross-queue GPU-event rounds pass. Global VRAM/GART counters return near baseline after exit; GPU VA and long-duration qualification remain open. |
| M6 — Desktop and physical display | Visual fix verified; broader qualification open | Candidate279 fixes the reproduced feedback corruption. Fresh pixel checks, user observation and unobstructed native RFB captures on280 pass; longer desktop qualification remains. Candidate321 gives a full HiDPI60 picture;322 fixes native1080p interleaving. User confirms60Hz and reports120Hz appears to work; HDMI audio works (323);330 adds correct-color HiDPI120 and retains audio through tested60↔120 switches. |
| M7 — Lifecycle and host protection | Partial | Multiple guest-request shutdowns and authorizing recoveries observed on this boot, including eight complete 280 runs with the visual and logging fixes. One supervised QEMU closure/recovery/reset/relaunch/clean-shutdown sequence now passes its scoped checks; closure capture remains INVALID. Fresh-host-boot, guest-panic and repeated lifecycle qualification remain open. |
| M8 — Performance and release | Not qualified | Correctness first; no release, Metal3 conformance, game-support or full-desktop claim. The current experimental snapshot is published to main at the user’s request; development continues on dev. Publication does not close acceptance gates. |

## Blocker revalidation — 2026-09-16

| Previously listed issue | Current classification | Revalidation |
|---|---|---|
| HEVC decode fails before kernel context creation | Resolved for automatic required-hardware selection | Fresh 120-frame hardware encode/decode pass; original 7-case/9,600-frame artifact hashes rechecked. |
| 4K /1080p HiDPI default | Scoped setup works; boot and transport qualification open | Isolated no-redundant-switch helper yields a crisp 1920×1080 logical / 3840×2160 backing desktop at nominal 60 Hz. A raw vncdotool black frame in the same working user session is a limited oracle; a prior mixed 90/120 Hz sequence did produce user-black and was cleanly restored. Requested 90/120 Hz are not proven modes. [Evidence](../findings/research/remote-retina-20260916.md). |
| PerfPowerServices continuously consumes a CPU core | Resolved on stock QEMU via OpenCore/VirtualSMC | Two fresh guest boots: one verified VirtualSMC provider,69 keys/end-of-list0xb8,0.0% CPU before/after work and after a service restart. Prior patched-QEMU passes retained; independent-host-boot durability remains open. |
| Green/purple transparency and smearing | Fixed for reproduced feedback defect in279 | Reversible native A/B intervention, fresh279/280 pixel passes, unobstructed280 native RFB panels and user reports clean Screen Sharing. Longer desktop qualification remains open. |
| Critical-event record overflow | Resolved for tested280 workload; finite capacity retained | Earlier smcpmio/279 overflow preserved as failures. Candidate280 finishes with398/512records,0drops and authorizing recovery; strict loss checks unchanged. |
| Explicit HEVC decoder GPU registry-ID selection | Confirmed remaining limitation | Fresh explicit-ID request returns -12906; automatic hardware request succeeds. Does not block automatic decoding. |
| No Metal execution / initial SDMA startup failure / pre-submit allocation failure | Superseded as current-baseline blockers | Current280 probe passed, completed GPU work and has a WindowServer accelerator client. Broader memory coverage remains open. |
| Same-boot restart impossible / reboot required after every run | Superseded as a blanket claim | Recorded guest-request shutdowns, authorizing recovery and subsequent starts. This is not universal crash or host stability qualification. |
| Candidate 278 direct OpenGL hang | Historical reproduced failure, not revalidated on current280 | Workload intentionally excluded pending first-draw diagnosis; do not claim it is fixed or a current280 reproduction. |
| Native large-block allocation diagnostics | Observed recoverable reclaim/retry for tested workloads | Native trace links all40 failed reclaim returns to subsequent same-thread/map success; CPU readbacks pass. Reclamation cost and broader failure cases remain open. |
| Live Metal validation crashes | Unresolved diagnostic limitation | Earlier CoreDisplay initialization crash; no successful validation verdict, no fresh repeat. |
| Main10/chroma | Short Main10 decode cases pass; hardware encoding limited to Main8 | 32 frames720p/1080p, full-plane luma/chroma exactly match software. Native GVA encoder advertises Main8 only and rejects Main10 before frames. Longer/arbitrary-content coverage remains open. |
| Physical output, broader concurrent resources/codecs, independent-host-boot lifecycle | Qualification gaps | Existing scoped passes do not establish these broader criteria. |

[Audit artifact hashes](../findings/research/blocker-revalidation-20260916.json).
Historical failures remain in findings; the active blocker list reflects the tested
current baseline. A closed root cause does not close broader acceptance criteria.

## Verified codec and CPU progress

**Hardware codecs:** H.264 decode/encode and HEVC encode/decode have reproduced
successes. Candidate 277 fixes HEVC decode by renaming only the marked Raphael PCI
IOService node from S30 to GFX0 before engine initialization. The prior claim that
this required an Apple XPC interposer or a topology redesign was incorrect.

Seven sustained cases completed **9,600 frames across two fresh guest boots on one
host boot**, with hardware decoder selection verified and every frame accounted for.
Those sustained cases cover Main8 4:2:0 synthetic patterns at720p/1080p. Additional
Main10 decode tests now pass32 frames at those sizes:71,884,800 full-plane luma/chroma
samples exactly match software. Native hardware HEVC encoder advertises Main8 only
and rejects Main10 before frames. Arbitrary media/HDR, long Main10 sequences,
concurrent codecs and guest-crash workloads remain unqualified.
[Main10 evidence](../findings/research/main10-qualification-20260916.md).
Explicit RequiredDecoderGPURegistryID still fails; automatic selection with
RequireHardwareAcceleratedVideoDecoder works.
A fresh audit on the corrected QEMU also passed 120 HEVC and 120 H.264 hardware
encode/decode frames at 720p; these are additional checks, not part of the original 9,600.
[Codec evidence](../findings/research/hevc-decode-qualification-20260916.json),
[resolver analysis](../findings/research/hevc-decode-appleGVA-20260916.md).

**Current stock-QEMU solution:** VirtualSMC1.3.7/gen2 plus an exact OpenCore patch
marking only QEMU SMC ACPI presence absent. Keep QEMU's device for boot-time access.
Two fresh guest boots verify the sole AppleSMC belongs to VirtualSMC,69 keys with
correct end-of-list,0.0% PerfPowerServices, Metal,480 total hardware codec frames,
remote pixels and clean recovery. No additional GPU driver patch is required.
[Setup and compatibility matrix](stock-qemu-smc.md),
[evidence](../findings/research/smc-opencore-handoff-20260916.md).

**Earlier emulator remedy:** the 100% CPU loop was caused by missing QEMU AppleSMC key
index enumeration. The corrected emulator implements command 0x12, returns a key
after four index bytes, and returns 0xb8 past the last key. Native AppleSMC calls
verified all six keys and both tested out-of-range indices. On the fresh smcpmio
guest, PerfPowerServices was 0.0% CPU; after a service restart it was 0.1% CPU with
0.54 s cumulative CPU time, later 0.0% with the same cumulative time. No Apple service is disabled and no guest binary or
security setting was patched. Candidate279 and280 supply second through eleventh measured guest boots (all0.0% CPU, latest0.76s cumulative).
Longer observation and independent-host-boot durability remain open. The first emulator patch incorrectly waited for a length
byte and failed native testing; it is superseded.
[Root cause and native results](../findings/research/perfpower-smc-enumeration-20260916.md),
[emulator build identity](../findings/research/qemu-smc-pmio-build-20260916.json).

## M5 acceptance: memory and rendering

- [x] Independently checked compute and offscreen render/readback.
- [x] Targeted storage/format, upload/copy, blur and interpolation probes.
- [x] Bounded texture recreation: 144 cases across private/managed/IOSurface storage,
  BGRA8/RGBA8, two sizes and three distinct-seed clients; zero pixel/padding errors.
- [x] GPU-only cross-queue ordering: 32 shared-event rounds, consumer submitted first,
  33,554,432 correct values.
- [x] Explicit untracked-resource blit/compute/blit fences: 128 rounds,
  134,217,728 correct values on one queue.
- [x] Bounded Depth32Float_Stencil8 transitions and1×/4× color resolve:
  128 cases,49,625,792 pixels, zero mismatches.
  [Method/scope](../findings/research/depth-stencil-20260916.md).
- [x] Two-process IOSurface GPU visibility with host completion/pipe ordering:
  32 bidirectional rounds,49,363,648 pixels, zero mismatches.
  [Method/scope](../findings/research/iosurface-process-20260916.md).
- [x] Bounded GPU-only cross-process event sharing over typed XPC:33 consumer-first
  transfers,25,453,131 correct pixels; helper exit and VM recovery checks pass.
  [Evidence/scope](../findings/research/xpc-event-20260916.md).
- [ ] Broaden formats, cross-pass depth hazards and concurrent interprocess writers.
- [x] Exercise sequential independent processes, then concurrent clients with
  distinct data and bounded allocations:280, seeds3/7 sequential and11/29
  concurrent;48 BGRA8 feedback cases. Broader multi-queue coverage remains open.
- [x] Measure process-local managed/private buffer reclamation:32 measured rounds,
  48 MiB live resources, allocation returns exactly to544,768bytes;134,217,728
  values verified. [Method and limits](../findings/research/resource-reclamation-20260916.md).
- [x] Observe global backing counters respond to texture pressure and return near
  baseline after client exit; non-reusable orphan counters stay zero.
- [x] Observe GPU-buffer address recycling: 512 measured rounds, 6,144 recurring
  address assignments, 2,147,483,648 correct values; exact allocation return.
- [x] Larger 192 MiB buffer workload: four measured rounds, zero errors; native
  trace shows failed map/reclaim attempts followed by success.
- [ ] Prove page-table release beyond cached address recycling; broaden duration,
  formats and concurrent pressure, accounting for global background activity.

- [ ] Attribute a failure to its actual engine before making an SDMA/GFX diagnosis.

[Texture, global-accounting and event evidence](../findings/research/texture-memory-and-events-20260916.md).

Pass requires completed command buffers, correct CPU-checked results, no native
fault/timeout or cross-client contamination, and measured resource reclamation.
Passing isolated shaders does not establish correct desktop composition.

## M6 acceptance: correct desktop, then physical output

- [x] Verify actual WindowServer use of this accelerator.
- [x] Establish a native colored NSVisualEffectView reproducer and raw RFB capture.
- [x] Isolate and fix compressed render-target feedback corruption (candidate279).
- [x] Bounded Screen Sharing composition checks: three minutes of native window
  movement/resizing and two minutes of Safari transparency/scrolling; seven clean
  raw captures plus a clean post-pressure capture.
- [ ] Broaden ordinary application use and sustained desktop interaction beyond
  these sampled workloads; keep independent-boot and physical-output gates open.
- [x] Confirm the feedback repair on fresh279 and280 guest boots with working Metal
  and hardware H.264/HEVC encode/decode.
- [x] Map DCN 3.1.5 differences against Apple's DCN 3.02 path (registers, fields, power
  domains, clock manager, DMUB, VBIOS tables): see the display port plan.
  Hardware confirmation now covers the Samsung HDMI path; other outputs remain open.
- [x] Bring up DMCUB through native PSP with verified guest TMR placement and
  fresh firmware replies (candidate314,2026-09-24).
- [x] Deliver HDMI VBIOS commands and observe firmware consumption (candidate315).
- [x] Confirm a physically visible hardware test pattern on the Samsung (candidate318).
- [x] Restore native framebuffer fetch and confirm a visible HiDPI image (candidate320).
- [x] Restore full HiDPI60 picture and correct native1080p interleaving (321/322).
- [x] Enable actual HDMI audio; user confirms sound through Samsung audio output (323 and330).
- [x] Expose 1080 HiDPI at 120 Hz with correct colors and audible audio (329/330);
  retain audio through tested 120→60→120 switches. Broader lifecycle coverage remains open.
- [ ] Qualify modes, reconnection and higher resolutions after first stable output.

The historical pre-279 investigation placed corrupt pixels in the scanout/DisplayStream path before
remote encoding. A native screenshot can be clean while raw RFB remains corrupt;
therefore a screenshot alone is insufficient. Plain-alpha windows are clean in
the targeted comparison; colored native visual-effect panels reproduce diagonal
artifacts. Native blur, varying-half gradients and offset-viewport replays pass,
but do not reproduce the complete failing compositor state.

Candidate 278's linear-swizzle change did not fix the defect and is rejected.
Its direct OpenGL probe hung; do not repeat it without a diagnosis. Candidate280 is the
qualified reference for these broader rendering checks. Temporary precision, binning, filter-merging and dirty-region
controls did not resolve the corruption; their coverage limits are recorded.
The live validation attempt crashed during CoreDisplay initialization, so it gives
no validation verdict on the original defect. Candidate279 uses the native expansion path before render-target feedback.
Its single-pass reproducer passes12cases/1,320,000pixels after previously failing
private/native-barrier cases. Controlled native panels clear with the patch and
fail after restoration. The initial279 panel captures were obscured. Fresh280 foreground native panels
are unobstructed and clean in raw RFB captures0/2, after different animation frames.
Four distinct-seed280 processes pass48cases/5,280,000pixels, including two concurrent
clients. The later addressreuse run adds native moving/resizing windows and Safari blur/scrolling;
longer application use remains an acceptance gate. See [fix evidence](../findings/research/feedback-decompression-20260916.md).
[Display evidence](../findings/research/transparency-live-composition-20260916.md)
(probes are also retained in the candidate 278 research worktree).

## M7 acceptance: shutdown, recovery and independent boots

Retain distinct outcomes for functional output, identity/capture, shutdown/recovery
and overall qualification. An active run has **cleanup pending**, even when its
functional probe passes.

- [x] Identity-bound guest-request shutdown and independent full-container deadline.
- [x] Authorizing recovery receipts and successful bounded same-boot reinitialization.
- [x] Reject incomplete cleanup, forced HQD clears, nonzero CP status or missing proofs.
- [ ] Repeat representative desktop/codec workloads across independently initialized
  host boots and verify each complete lifecycle.
- [ ] Qualify guest-crash/QEMU-closure paths and command-channel-unavailable fallback.
- [ ] Preserve host-fault evidence and resolve remaining host-stability limits without
  intentionally provoking a host lockup.

No vfio-pci→amdgpu cycling within a boot; power/control stays on. Use tools/cycle.py
and candidate worktrees. Fresh MODE2 and the prior run's valid recovery receipt admit
additional exposure automatically; a reset receipt alone is not authorization, and
there is no flag or status.md allowance note. No host sudo on the normal path.
Preserve every identity, capture-fatal, host-fault,
shutdown and recovery abort. Current authorized runs allow up to 6000 seconds with
manual stop; this replaces the historical 180-second limit. See
[host safety](host-safety.md) and [experiment procedure](running-an-experiment.md).

## M8 acceptance: measured usability and release

- [ ] Measure GPU and wall time only after visual correctness; separate shader
  compilation, transfers and execution.
- [ ] Record fixed-resolution desktop frame times, duration and visual defects.
- [ ] Require three independently initialized host-boot sessions with the core suite,
  plus three successful bounded lifecycle cycles after M7 qualification.
- [ ] Publish exact build hashes, tested features and unresolved limitations.

Games and Metal3 conformance remain unqualified. Do not infer application support
from device enumeration or passing microbenchmarks.

## Next work, in order

0. **Physical display and HDMI audio (user priority, 2026-09-17).**
   [Port plan and evidence](../findings/research/display-dcn315-port-20260917.md),
   [HDMI audio plan](../findings/research/hdmi-audio-passthrough-20260917.md),
   [host freeze analysis](../findings/research/dcn315-dmcub-host-crash-20260917.md).
   - DCN3.02 register translation and Samsung EDID reads work. Native PSP DMCUB
     reload/start and HDMI command delivery are demonstrated (314/315).
   - Candidate318 produces a physically visible RGB test pattern at native1080p60.
     The historical fuzziness/interleaving was subsequently fixed in321/322.
     [Evidence](../findings/research/visible-hdmi-pattern-20260924.md).
   - Fetch and native1080p layout now work (320–322). Native120Hz appears to work
     according to the user;329/330 add confirmed correct-color1080HiDPI120 and audible audio.
   - Verify guest awake assertions and active HDMI before every physical observation.
     Keep native host-safety, capture, shutdown and recovery checks intact.
   - HDMI audio works on323 and330: function7b:00.1 is paired with the GPU;
     same-slot pairing, passthrough and audible playback are confirmed through
     the Samsung headphone output (2 channels, 48 kHz).
1. **Full 4K remote desktop streaming (user priority, updated 2026-09-17).** 4K60 is
   now stable. Three fixes got there: the VCN preset patch (candidate 284, encode 11ms at 4K,
   equal to Linux), a 2GB BIOS UMA carve-out (no allocation failures; host tools detect the
   carve-out automatically), and Sunshine ScreenCaptureKit capture with session-range NV12
   (no Sunshine GPU transfers; the user reports no stutter at 60fps).
   [Evidence](../findings/research/encoder-pipeline-20260917.md). Remaining, in order:
   a. **Permanent 120Hz virtual display.** macOS CoreDisplay fills every virtual display
      mode's integer refresh with 60 and derives vsync from it. A live WindowServer memory
      poke proved true 120Hz (8.33ms VBL, 112–122 capture frames/s). Build the designed
      98-byte guarded COW patch in `_CGXVirtualDisplayApply` (CoreDisplay UUID
      `B52FFBDE-B5F7-3F53-8D5E-2A822E7EE75E`, TEXT+0x371de) as a candidate 285 target
      applied in WindowServer, then verify the VBL delta and 1440p120/1080p120 stream rates.
   b. Persist the 120Hz CGVirtualDisplay holder as a LaunchAgent (currently a test
      holder in `/var/tmp`), and Sunshine's high priority (renice -20, taskpolicy tier 0).
   c. 4K above ~66–83fps is limited by the serialized VT plugin path (Metal pre-pass
      ~5ms + VCN ~10ms). Only pursue this if 4K90 matters; 4K120 is beyond this VCN.
   d. Login persistence of the display helper and physical output remain separate gates.
2. Qualify supervised QEMU closure and guest-crash/command-channel failure paths,
   then representative workloads on independently initialized host boots.
   Supervised HMP quit now has positive cleanup evidence: five queues dequeued,
   graphics ring retired, CP_STAT=0, authorizing recovery. Strict overall verdict
   remains INVALID due truncated terminal capture. A fresh post-closure guest now
   passes the desktop probe, clean shutdown and authorizing recovery.
   Panic/fallback/repetition/independent host boots remain open.
   [Closure evidence](../findings/research/supervised-qemu-closure-result-20260916.md).
3. Broaden desktop applications, formats and interprocess synchronization; measure
   reclamation cost and page-table release beyond observed address recycling.
4. Progress physical display and measured performance qualification after those gates.

Allocation failure messages have now been traced through native reclaim/retry:
all 40 failed reclaim calls in the larger-buffer capture are followed by success
for the same thread/map, while all CPU readbacks pass. The message alone is not a
reproduced correctness blocker for these workloads; performance cost remains open.
[Native analysis](../findings/research/allocation-retry-analysis-20260916.md).

Candidate 280 closes the immediate capture-loss blocker: 398, 370, 387 and 372
critical records in four completed runs, no loss, guest-request shutdown and
authorizing recovery. [Latest address/desktop qualification](../findings/research/address-reclaim-desktop-20260916.md),
[artifact hashes](../findings/research/address-reclaim-desktop-evidence-20260916.json).

One owner controls hardware and the guest command channel. Review the hypothesis,
baseline and evidence after three experiments on an unexplained failure; repeated
non-discriminating toggles are not progress. Report observed results and scope,
not an invented completion percentage. Historical investigations and review records
remain available in the archived roadmap and findings.

## Source basis for remaining driver work

Use the user-provided `macos-vm/re/decompiled-24G830` sources, checking inferred
prototypes against matching disassembly and vtables before implementation. The
allocation investigation already combines those sources with live native tracing.
Physical HDMI bring-up now has a working Samsung HiDPI120/audio path. The native
`reportCapabilities_LinkInfo` at +0xe074 omitted FRL signal cases; candidate330
publishes HDMI audio metadata while preserving the native transport. DCN315 clock
selection and infoframe SRAM wake were independently required for correct output.
[Source audit, Linux references and physical evidence](../findings/research/hdmi-hidpi120-20260924.md).

The earlier [boot-path analysis](../findings/research/display-boot-path-20260916.md)
and [clock/wait audit](../findings/research/display-clock-wait-20260916.md) remain
historical evidence. Their proposed first-picture probes are superseded by this
milestone. Remaining work includes HDCP errors and broader lifecycle/monitor testing.

## Portability: remove the patched-QEMU dependency

The immediate QEMU source-patch dependency is removed for the tested setup.
OpenCore hides QEMU SMC's ACPI presence while VirtualSMC supplies the native service;
QEMU's device remains available for boot-time key access. No RaphaelGPU binary change.

- [x] Audit the repository's host patch: its only QEMU modification implements SMC
  enumeration; GPU topology uses standard VFIO options and guest adaptations.
- [x] Implement guest-side ownership with VirtualSMC1.3.7/gen2 and a guarded
  OpenCore DSDT patch, retaining PerfPowerServices and existing GPU capabilities.
- [x] Verify on stock QEMU10.1.2/Sequoia24G830: two guest boots on one host boot,
  sole VirtualSMC-backed AppleSMC, bounded enumeration/end-of-list, low CPU before
  and after work/restart, Metal/codec/remote-desktop checks and clean recovery.
- [x] Publish the [stock-QEMU setup and compatibility matrix](stock-qemu-smc.md);
  preserve the older patched-QEMU/config pair for rollback.
- [ ] Broaden duration, independent host boots and QEMU/macOS versions. Successful
  login/desktop boot is observed; comprehensive secure-service testing remains open.
- [ ] Record per-hypervisor prerequisites: physical PCIe exposure, BAR mappings,
  interrupts, DMA/IOMMU, ROM/OpenCore delivery and reset/cleanup support.
- [ ] Investigate VirtualBox separately: virtual display adapters are not Raphael
  passthrough. Verify actual version/build support before promising acceleration.

[Native evidence and exact source/binary identities](../findings/research/smc-opencore-handoff-20260916.md).
General example files alone are not hardware validation. All other hypervisors stay
unqualified. These passes do not establish physical sensor accuracy or power management.

## Reims source-audit follow-ups

Research complete at Reims `69a57dd69a6958e946c03b73e02db331f330f435`, with
its pinned QEMU submodule also reviewed. [Audit and source references](../findings/research/reims-vgpu-audit-20260916.md).
These are independently implemented qualification tasks, not confirmed Raphael bugs.
No external code was imported or runtime results reproduced; the translator dependency
was not audited. The tested stock-QEMU/SMC path is now verified; broader portability remains open.

- [ ] **M6: expected content versus remote pixels.** Add declared regions and visible
  frame tokens to composition checks; compare raw RFB captures against independent
  expected patterns. Reject stale frames and wrong geometry in host-only instrument
  checks. Account for scale/color transfer and verify retained areas after updates.
- [x] **M5: mixed CPU/GPU ownership — managed textures.** 96 fresh-resource cases
  across two seeded processes pass RGBA8/BGRA8 at64×64/1003×769: explicit GPU-to-CPU
  sync, partial CPU update and LOAD-only/CPU-only/combined controls preserve changed
  and untouched regions.111,658,032 pixel comparisons, zero pixel/padding mismatches;
  valid strict capture and clean shutdown/recovery. Every control includes initial
  texture synchronization/readback; this does not qualify IOSurface ownership or
  retained depth. [Evidence](../findings/research/texture-ownership-20260916.md).
- [ ] **M5: plane and subresource isolation.** Import biplanar IOSurfaces through public
  APIs as R8/RG8 textures; check per-plane geometry, pitch and distinct content. Add
  mip/slice views and prove changing one leaves other subresources unchanged.
- [ ] **M5: retained depth/stencil.** Write in one pass, LOAD in another and verify a
  CPU-known comparison mask. Keep depth resolve, aspect copies and independent-client
  isolation as distinct cases; current color-resolve passes do not establish them.
- [ ] **M5: bounded heap alias lifetime.** Complete work before making a resource
  aliasable, prove reuse of its heap offset and verify new content. Keep actual
  page-table release dependent on native unmap/invalidate and backing evidence.

Use supported AMD storage modes and native synchronization contracts. Give cases
stable semantic IDs, bounded waits and mandatory result accounting; retain capture,
shutdown and recovery checks. Existing cross-process consumer-first GPU events already
have stronger local evidence than importing Reims' basic event tests would add.

Reims' virtual GOP, Vulkan/Metal translation and custom QEMU device do not establish
Raphael DCN output, VCN support, VFIO recovery or VirtualBox passthrough. Its pinned
AppleSMC still lacks key-index enumeration; our separately tested OpenCore/VirtualSMC
solution closes that dependency for stock QEMU. Other roadmap gates remain open. Root and
Cargo license metadata differ; resolve applicable terms before considering source reuse.

## Licensing and distribution follow-up

- Implement the [audited vendor-only firmware sourcing plan](../findings/research/licensing-audit-20260916.md)
  after authorization; preserve exact bytes and all existing match checks.
- Resolve SDK per-file/OS restrictions and executable source-notice obligations;
  review other native patterns/excerpts and historical release assets.
- BSD-3-Clause and verified third-party licence documents are now included.
  Documentation work does not establish complete legal or hardware qualification.

Candidate282's streaming investigation ended with valid capture, a clean
guest-request shutdown and authorizing recovery. Motion performance remains
open; the final120FPS-request/60Hz-display trace requires a matching4K60 control.
[Final evidence](../findings/research/safari-motion-20260916.json).

## Physical HDMI milestone — 2026-09-24

Candidates 321–323 establish a full 1920×1080 logical / 3840×2160 backing
HDMI picture at 60 Hz, correct native 1920×1080 at 60 Hz, and audible HDMI
audio through the Samsung headphone output. Native 1080p at 120 Hz is listed
and the user reports it appears to work; sustained timing is not qualified.
Candidate330 now provides that HiDPI120 link with correct colors and audible
HDMI audio. Default audio routing and playback survive tested120→60→120 switches.
[Evidence and residual log errors](../findings/research/hdmi-hidpi120-20260924.md).
DisplayPort, HDR, broader monitors and independent-host-boot durability remain open.

[Current setup and scope](hdmi-status.md) ·
[Historical bring-up](../findings/research/status-archives/hdmi-bringup-roadmap-20260924.md).
