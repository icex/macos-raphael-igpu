# Raphael iGPU acceleration roadmap

Updated 2026-09-16. Current driver: **candidate 1.0.280**. Full desktop acceleration
is **not qualified**. The reproduced Screen Sharing transparency defect is fixed
in candidate279 and retained in280. Candidate280 also passes strict capture and
clean recovery after visual, concurrent-client and codec workloads. The remaining
priority is memory, broader lifecycle, physical-display and performance qualification.

This is the current roadmap. [Live state and run authority](../status.md) are separate.
The [previous roadmap](../findings/research/status-archives/roadmap-before-20260916-refresh.md)
preserves the candidate159–194 history and review decisions; its dated launch budgets
and “next experiment” instructions do not describe today's host.

## Progress and remaining gates

| Milestone | State | Evidence and remaining work |
|---|---|---|
| M0 — Experiment identity and supervision | Implemented; maintained | Immutable manifests, loaded-build checks, capture, deadlines and cleanup. Fixed cycle image selection so preparation and admission use the same pinned emulator. Host suite: 938 tests, OK (3 skipped). |
| M1 — Controlled starting state | Demonstrated for current workflow | One-way amdgpu→vfio-pci handoff, power/control=on, fresh MODE2 and clean-state receipts. Broad independent-host-boot qualification remains open. |
| M2 — Native startup failure localization | Completed for original blocker | False second SDMA instance and subsequent channel routing were traced; historical evidence retained. |
| M3 — Native engine startup repair | Demonstrated | Raphael topology/address adaptations reach native startup and completed Metal work. Preserve these fixes while diagnosing desktop rendering. |
| M4 — First correct Metal compute | Achieved | Candidate 194 checked 196,608 values and 4,096 rendered pixels; its overall capture remained inconclusive. Current280 desktop Metal baselines complete with verified device/build identity. |
| M5 — Rendering, memory and synchronization | Partial | Managed-texture copy correction retained; private/managed/IOSurface and multiple-format readback probes pass. Candidate280 passes48 BGRA8 feedback cases across four distinct-seed processes, including two concurrent clients. 32 measured buffer-reclamation rounds return process-local allocation to baseline with134,217,728 correct values. 144 texture recreation cases and32 cross-queue GPU-event rounds pass. Global VRAM/GART counters return near baseline after exit; GPU VA and long-duration qualification remain open. |
| M6 — Desktop and physical display | Visual fix verified; broader qualification open | Candidate279 fixes the reproduced feedback corruption. Fresh pixel checks, user observation and unobstructed native RFB captures on280 pass; longer desktop qualification remains. Physical DCN 3.1.5 output is a separate unqualified path. |
| M7 — Lifecycle and host protection | Partial | Multiple guest-request shutdowns and authorizing recoveries observed on this boot, including three complete280 runs with the visual and logging fixes. Fresh-host-boot, crash-path and repeated lifecycle qualification remain open. |
| M8 — Performance and release | Not qualified | Correctness first; no release, Metal3 conformance, game-support or full-desktop claim. No merge/push to main before demonstrated usable desktop acceleration. |

## Blocker revalidation — 2026-09-16

| Previously listed issue | Current classification | Revalidation |
|---|---|---|
| HEVC decode fails before kernel context creation | Resolved for automatic required-hardware selection | Fresh 120-frame hardware encode/decode pass; original 7-case/9,600-frame artifact hashes rechecked. |
| PerfPowerServices continuously consumes a CPU core | Resolved in corrected QEMU, observed on five guest boots | Native enumeration passes;0.0% after startup, graphics work and one service restart. Guest boots279/280 (including both reclamation attempts) are also0.0%; independent-host-boot durability remains open. |
| Green/purple transparency and smearing | Fixed for reproduced feedback defect in279 | Reversible native A/B intervention, fresh279/280 pixel passes, unobstructed280 native RFB panels and user reports clean Screen Sharing. Longer desktop qualification remains open. |
| Critical-event record overflow | Resolved for tested280 workload; finite capacity retained | Earlier smcpmio/279 overflow preserved as failures. Candidate280 finishes with398/512records,0drops and authorizing recovery; strict loss checks unchanged. |
| Explicit HEVC decoder GPU registry-ID selection | Confirmed remaining limitation | Fresh explicit-ID request returns -12906; automatic hardware request succeeds. Does not block automatic decoding. |
| No Metal execution / initial SDMA startup failure / pre-submit allocation failure | Superseded as current-baseline blockers | Current280 probe passed, completed GPU work and has a WindowServer accelerator client. Broader memory coverage remains open. |
| Same-boot restart impossible / reboot required after every run | Superseded as a blanket claim | Recorded guest-request shutdowns, authorizing recovery and subsequent starts. This is not universal crash or host stability qualification. |
| Candidate 278 direct OpenGL hang | Historical reproduced failure, not revalidated on current280 | Workload intentionally excluded pending first-draw diagnosis; do not claim it is fixed or a current280 reproduction. |
| Native large-block allocation diagnostics | Existing unresolved allocation path, not a new texture-test failure | Present before new probes and in earlier passing280 captures. Trace caller/fallback; successful readbacks do not explain internal allocation failures. |
| Live Metal validation crashes | Unresolved diagnostic limitation | Earlier CoreDisplay initialization crash; no successful validation verdict, no fresh repeat. |
| Physical output, Main10/chroma, concurrent resources/codecs, independent-host-boot lifecycle | Qualification gaps, not newly reproduced failures | Remain open because no adequate passing evidence exists; not labeled fixed or tested-failing. |

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
These cover Main, 8-bit 4:2:0 synthetic patterns at 720p/1080p. Main10, arbitrary media
and chroma fidelity, concurrent codecs and crash recovery remain unqualified.
Explicit RequiredDecoderGPURegistryID still fails; automatic selection with
RequireHardwareAcceleratedVideoDecoder works.
A fresh audit on the corrected QEMU also passed 120 HEVC and 120 H.264 hardware
encode/decode frames at 720p; these are additional checks, not part of the original 9,600.
[Codec evidence](../findings/research/hevc-decode-qualification-20260916.json),
[resolver analysis](../findings/research/hevc-decode-appleGVA-20260916.md).

**PerfPowerServices:** the 100% CPU loop was caused by missing QEMU AppleSMC key
index enumeration. The corrected emulator implements command 0x12, returns a key
after four index bytes, and returns 0xb8 past the last key. Native AppleSMC calls
verified all six keys and both tested out-of-range indices. On the fresh smcpmio
guest, PerfPowerServices was 0.0% CPU; after a service restart it was 0.1% CPU with
0.54 s cumulative CPU time, later 0.0% with the same cumulative time. No Apple service is disabled and no guest binary or
security setting was patched. Candidate279 and280 supply second through fifth passing guest boots (all 0.0% CPU, latest 0.77s cumulative).
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
- [ ] Broaden formats, compute/render hazards, fences and event sharing beyond these
  exact tested paths.
- [x] Exercise sequential independent processes, then concurrent clients with
  distinct data and bounded allocations:280, seeds3/7 sequential and11/29
  concurrent;48 BGRA8 feedback cases. Broader multi-queue coverage remains open.
- [x] Measure process-local managed/private buffer reclamation:32 measured rounds,
  48 MiB live resources, allocation returns exactly to544,768bytes;134,217,728
  values verified. [Method and limits](../findings/research/resource-reclamation-20260916.md).
- [x] Observe global backing counters respond to texture pressure and return near
  baseline after client exit; non-reusable orphan counters stay zero.
- [ ] Measure GPU virtual-address reclamation and long-duration memory pressure;
  account for global background activity and reusable caches.

- [ ] Attribute a failure to its actual engine before making an SDMA/GFX diagnosis.

[Texture, global-accounting and event evidence](../findings/research/texture-memory-and-events-20260916.md).

Pass requires completed command buffers, correct CPU-checked results, no native
fault/timeout or cross-client contamination, and measured resource reclamation.
Passing isolated shaders does not establish correct desktop composition.

## M6 acceptance: correct desktop, then physical output

- [x] Verify actual WindowServer use of this accelerator.
- [x] Establish a native colored NSVisualEffectView reproducer and raw RFB capture.
- [x] Isolate and fix compressed render-target feedback corruption (candidate279).
- [ ] Verify clean transparent windows, animation and ordinary desktop interaction
  through Screen Sharing, with repeatable captures and no new GPU faults.
- [x] Confirm the feedback repair on fresh279 and280 guest boots with working Metal
  and hardware H.264/HEVC encode/decode.
- [ ] Map real connectors/HPD/AUX/PHY and DCN 3.1.5 differences; implement only
  demonstrated incompatibilities, beginning with one changing 1080p60 output.
- [ ] Qualify modes, reconnection and higher resolutions after first stable output.

Current evidence puts corrupt pixels in the scanout/DisplayStream path before
remote encoding. A native screenshot can be clean while raw RFB remains corrupt;
therefore a screenshot alone is insufficient. Plain-alpha windows are clean in
the targeted comparison; colored native visual-effect panels reproduce diagonal
artifacts. Native blur, varying-half gradients and offset-viewport replays pass,
but do not reproduce the complete failing compositor state.

Candidate 278's linear-swizzle change did not fix the defect and is rejected.
Its direct OpenGL probe hung; do not repeat it without a diagnosis. Use280 as the
current hardware baseline. Temporary precision, binning, filter-merging and dirty-region
controls did not resolve the corruption; their coverage limits are recorded.
The live validation attempt crashed during CoreDisplay initialization, so it gives
no validation verdict on the original defect. Candidate279 uses the native expansion path before render-target feedback.
Its single-pass reproducer passes12cases/1,320,000pixels after previously failing
private/native-barrier cases. Controlled native panels clear with the patch and
fail after restoration. The initial279 panel captures were obscured. Fresh280 foreground native panels
are unobstructed and clean in raw RFB captures0/2, after different animation frames.
Four distinct-seed280 processes pass48cases/5,280,000pixels, including two concurrent
clients. Longer desktop use remains an acceptance gate. See [fix evidence](../findings/research/feedback-decompression-20260916.md).
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
and candidate worktrees. Fresh MODE2 and a recorded boot-specific allowance are
required for additional exposure; a reset receipt alone is not authorization.
No host sudo on the normal path. Preserve every identity, capture-fatal, host-fault,
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

1. Trace the existing native allocation failures to callers/fallbacks; distinguish
   capacity/fragmentation from failed API work. Measure GPU-VA reclamation and
   longer pressure behavior beyond the passing texture/global-counter checks.
2. Broaden normal desktop and synchronization coverage on280; keep observing the
   SMC CPU fix without disabling the service.
3. Complete M7 independent-host-boot and crash/closure lifecycle gates.
4. Progress physical display and measured performance qualification after those gates.

Candidate280 closes the immediate capture-loss blocker:398,370 and387 critical records
in three completed runs, no loss, guest-request shutdown and authorizing recovery. See
[initial 280 evidence](../findings/research/candidate-280-qualification-20260916.json) and
[latest texture/event evidence](../findings/research/texture-memory-and-events-evidence-20260916.json).

One owner controls hardware and the guest command channel. Review the hypothesis,
baseline and evidence after three experiments on an unexplained failure; repeated
non-discriminating toggles are not progress. Report observed results and scope,
not an invented completion percentage. Historical investigations and review records
remain available in the archived roadmap and findings.
