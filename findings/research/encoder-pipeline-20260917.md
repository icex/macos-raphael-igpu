# Encoder pipeline and GPU clock probes — 2026-09-17

Run `5ad1627419ec01d27fb81565d59c8a26` (candidate282/metal130, attempt `clock1`,
MODE2#180, exposure34, boot `2508eb6d-ddf3-497d-9774-00a7ecebe3ed`), unchanged driver
build `7a26b1a2f6694ae88ed889105de30bc7`. Guest at Retina1920×1080 logical /
3840×2160 backing /60Hz, Sunshine Capture Fix app running idle. Raw outputs are in
`~/macos-vm/run/candidate-282-attempt-clock1-results/` (`probe1-output.txt`,
`pipeline2-output.txt`, `pipeline3-output.txt`). No driver change; measurement only.

## GPU compute is not clock-starved

`tests/gpu_clock_probe.m` (Metal, hardware-required device "AMD Radeon Navi23"):

| Measurement | Result |
|---|---:|
| 3840×2160 RGBA8 → NV12 compute pass, GPU time | 1.41ms min /1.43ms mean |
| Blit copy 256MiB private→private | 55.8GB/s median (GPU time) |
| Compute float4 copy | 47.5GB/s median |
| Trivial kernel commit→completion round trip | 0.12ms min /0.15ms mean |

The FMA-chain FLOPS figure (2.5TFLOPS, ~5× the 2-CU peak) is a compiler artifact and
is not evidence of anything. The conversion and bandwidth numbers are consistent with
a healthy GFX clock; the earlier 7.8ms "Metal preprocessing" waits inside
VTEncoderXPCService are therefore queueing/serialization, not shader cost.

## VideoToolbox hardware encode has a fixed per-frame cost

`tests/video_encoder_pipeline_probe.m` (hardware required, AllowFrameReordering=false,
ExpectedFrameRate=60, MaxKeyFrameInterval=120, 12 warmup + 120 measured frames, six
rotating NV12 IOSurfaces, submissions back-to-back). Per-frame `EncodeFrame` call time
and submit→callback latency were recorded.

| Codec | Size | Bitrate | Realtime | Content | Encode call ms | Latency ms | fps | In flight max |
|---|---|---:|---|---|---:|---:|---:|---:|
| HEVC | 3840×2160 | 40M | off | simple | 15.31 | 46.1 | 64.2 | 2 |
| HEVC | 3840×2160 | 40M | on | noise | 15.71 | 47.3 | 62.6 | 2 |
| HEVC | 3840×2160 | 40M | off | noise | 15.75 | 47.4 | 62.5 | 2 |
| HEVC | 3840×2160 | 10M | on | simple | 15.25 | 46.0 | 64.5 | 2 |
| HEVC | 3840×2160 | 80M | on | simple | 15.09 | 45.5 | 65.2 | 2 |
| H.264 | 3840×2160 | 40M | on | simple | 12.87 | 25.7 | 77.0 | 1 |
| H.264 | 3840×2160 | 40M | on | noise | 134.6 | 269.9 | 7.4 | 1 |
| HEVC | 2560×1440 | 40M | on | noise | 7.49 | 22.5 | 131.4 | 2 |
| HEVC | 1920×1080 | 20M | on | noise | 4.50 | 32.0 | 211.7 | 6 |

All hardware-required sessions reported `UsingHardwareAcceleratedVideoEncoder=true`,
120 callbacks, zero errors. `kVTCompressionPropertyKey_PrioritizeEncodingSpeedOverQuality`
and `kVTCompressionPropertyKey_MaxFrameDelayCount` are refused with-12900 by this
encoder (the FFmpeg `prio_speed=1` that Sunshine sets is therefore a logged no-op).

Findings:

1. HEVC 4K costs 15.1–15.7ms per frame regardless of content (flat quadrants vs
   per-pixel noise), bitrate (10–80Mbit/s) and the realtime flag. That is a fixed
   pixel rate of roughly 500Mpixel/s (1440p7.5ms,1080p4.5ms scale the same way).
2. `VTCompressionSessionEncodeFrame` blocks for that whole time; at most two frames
   are ever in flight. Sunshine's `avcodec_send_frame` and FFmpeg's `vtenc_frame`
   are asynchronous by construction (no `MaxFrameDelayCount` is set anywhere), so
   the serialization lives inside Apple's AMD VideoToolbox plugin, matching last
   night's 409/440 samples blocked in `VTCompressionSessionEncodeFrame`.
3. With a 16.7ms frame budget and 15.5ms of mandatory encoder time, any other GPU
   contention (WindowServer compositing under cursor motion, Sunshine's capture
   conversion, the plugin's own Metal pass) pushes 4K60 below60fps. This explains
   why motion, not content, triggers the slowdown, and why the 20Mbit/s cap changed
   nothing.
4. H.264 is15% cheaper on normal content (12.9ms) but its rate control ignores the
   cap on pathological content (8.6MB frames). 1440p HEVC has ample headroom.

## Interpretation and next discriminating test

Nothing in the guest manages GPU clocks: Apple PowerPlay runs as the dummy backend
and the driver's only SMU traffic is `PowerUpVcn` on the Raphael13.0.5 mailbox. A VCN3
encoder at full VCLK should exceed this pixel rate by a wide margin, so a low VCLK DPM
state is the leading hypothesis for the fixed 15.5ms. Candidate283 (card metal-131)
adds opt-in `rgpuvcnclk=<MHz>` (`SetHardMinVcn`=7 then `SetSoftMaxVcn`=17, the same
pair Linux `smu_v13_0_5_set_soft_freq_limited_range` uses for `SMU_VCLK`, non-fatal,
logged as `VCNCLK:`) and `rgpusmuquery=1` (`GetGfxclkFrequency`=15 and
`GetEnabledSmuFeatures`=16, logged as `SMUQ:`). Message ids were verified against
the Linux `smu_v13_0_5_ppsmc.h`. Rerunning the same probe matrix under candidate283
is the discriminating test: a large drop below 15ms confirms the clock hypothesis; an
unchanged 15.5ms with an accepted request rules it out and leaves H.264/1440p/pipeline
work as the remaining levers.

## Run closure

The run stayed interactive overnight; its runner process was killed when the host
session ended, so the container was force-stopped (`outcome: forced`, exit137) without
a guest-request shutdown and the supervision deadline timer did not stop it at its
deadline. Recovery was replayed through the harness's own `recover_v2` path:
schema6 `recovered`, `authorizes_launch=true`, receipt `e0d1af5efcb44d6dbd9070fe5de06bae`.
Moonlight-Qt6.1.0 is installed on the host as a user Flatpak; pairing was never
completed (PIN entry required), so no client-side frame-rate figures exist yet.

## Linux-side VCN ceiling (same hardware, host boot 3c3ae1cb, 2026-09-17 08:40)

After a host reboot, amdgpu owned the iGPU (`renderD129`, Mesa26.2.2 radeonsi
raphael_mendocino). `~/macos-vm/run/linux-hevc-ceiling.sh` encoded raw NV12 clips from
RAM through VAAPI (`-vf hwupload`, `-g 120 -bf 0`, 600 frames), sampling the active DPM
levels during each run. DPM tables: VCLK 400/1200MHz, DCLK 300/1028MHz, GFX 600/700/2200MHz.

| Clip | Codec | auto DPM (VCLK1200, GFX600) | profile_peak (VCLK1200, GFX2200) | manual VCLK400 |
|---|---|---:|---:|---:|
| 3840×2160 testsrc2 | HEVC | 91fps | 91fps | 28fps |
| 3840×2160 noise | HEVC | 91fps | 92fps | – |
| 3840×2160 testsrc2 | H.264 | 91fps | 91fps | – |
| 2560×1440 | HEVC | 182fps | 187fps | – |
| 1920×1080 | HEVC | 319fps | 329fps | – |

The encoder is a fixed pixel-rate engine whose speed scales with VCLK (28→91fps for
400→1200MHz) and is independent of GFX clock and content. Its true 4K ceiling is
**11ms per frame (91fps)** at the maximum 1200MHz VCLK, for both HEVC and H.264.

Interpretation for the guest: 64fps (15.5ms) lies between the two VCLK levels, so
the guest VCN already runs at 1200MHz under load; the missing ~4.5ms per frame is
the serialized VideoToolbox plugin path (Metal pre-pass + XPC + completion wait),
and under live streaming the Metal waits grew to 7.8ms. Because the SMU keeps GFX
at 600MHz for light bursty load (as the auto-DPM column shows), the plugin's and
WindowServer's per-frame GPU work most likely runs at 600MHz during streaming.
Candidate283 therefore gains `rgpugfxclk=<MHz>` (SetHardMinGfxClk=21) beside
`rgpuvcnclk` (set to the real 1200MHz maximum) and the telemetry query.
[Log](../../../macos-vm/run/linux-hevc-ceiling-20260917.log) (host path).

## Candidate283: full clock floors do not change encode cost

Run `c409763be71e3ee009bb8a8dd23c3b58` (candidate283/metal131, host boot
`3c3ae1cb-0799-4810-8a2c-638184ac286e`, MODE2#181, first launch of the boot, no reuse
flags). Build `43ac858ac0df400788cc2b6a411b4b74`, source commit `28ac036`. Boot arguments
`rgpuvcnclk=1200 rgpudclk=1028 rgpugfxclk=2200 rgpusmuquery=1`, applied after PowerUpVcn:

```text
VCNCLK: requested=1200 hardmin-response=1 softmax-response=1 applied=1
DCLK: requested=1028 hardmin-response=1 softmax-response=1 applied=1
GFXCLK: requested=2200 hardmin-response=1 applied=1
SMUQ: gfxclk-response=1 gfxclk-mhz=2200 features-response=1 features=0006ff37a15fefbf
```

The first attempt encoded VCLK unshifted; Linux `smu_v13_0_5_set_soft_freq_limited_range`
sends VCLK as MHz<<16 and DCLK unshifted on the same two messages, which the final build
matches. Same probe matrix as clock1:

| Codec | Size | Content | clock1 encode ms / fps | candidate283 encode ms / fps |
|---|---|---|---:|---:|
| HEVC | 3840×2160 | simple | 15.25 / 64.5 | 15.04 / 65.4 |
| HEVC | 3840×2160 | noise | 15.71 / 62.6 | 15.81 / 62.3 |
| H.264 | 3840×2160 | simple | 12.87 / 77.0 | 12.70 / 78.1 |
| HEVC | 2560×1440 | noise | 7.49 / 131.4 | 7.40 / 132.9 |
| HEVC | 1920×1080 | noise | 4.50 / 211.7 | 4.44 / 214.8 |

Clock floors are not the limiter. A dtrace of `VTEncoderXPCService` during a 900-frame 4K
HEVC encode attributes the time: `AMDRadeonVADriver2 waitForStatusEvent` 14.0–15.0ms on
376 of 379 frames (a single tight peak, not polling quanta), Metal `waitUntilCompleted`
2.5–3.4ms, memory copies ~0.3ms per frame, little CPU. Per-pixel VCN cost is a constant
~1.37× the Linux VAAPI whole-pipeline figure at 1080p, 1440p and 4K, so the difference is
in the work the encoder is asked to do, not latency or clocks. The next test compares the
encode session parameters Apple's plugin programs (preset, pre-encode, VBAQ, deblocking)
with Mesa's defaults.

## Root cause: Apple's plugin never sends a VCN encoding preset

Same run, live dtrace of `VTEncoderXPCService` from process start (`dtrace -W`). Apple's
`AMDRadeonVADriver2` configures the VCN3 HEVC session with config IDs 0x1, 0x13, 0xc, 0xd,
0xe and then 0x10 per frame; the preset setter (ID 0x15) is never called, and no public or
private VideoToolbox key reaches it (`kVTCompressionPropertyKey_Priority` 0–4 accepted and
ignored; `LowLatencyMode` refused with −12900). `Vcn3EncHevcCommand::buildGeneralCommand`
emits `addPresetEncodeModePacket` only when command-info flag 0x1c is set, and that function
emits nothing unless the stored preset is SPEED/BALANCE/QUALITY (0x01000006–8). The stored
value is 0, so no preset op ever reaches the firmware. Mesa radeonsi sends a preset op every
frame; its effective HEVC default is BALANCE.

Destructive dtrace A/B in the encoder process only (flag 0x1c set, preset written), 4K,
240 frames each:

| Session | Encode call ms | fps | VCN wait µs | Mean bytes/frame |
|---|---:|---:|---:|---:|
| HEVC, no preset (Apple default) | 15.78 | 62.8 | 15,365 | 720,567 |
| HEVC, QUALITY | 13.80 | 71.9 | 13,435 | 720,325 |
| HEVC, BALANCE | 12.05 | 82.3 | 11,785 | 719,126 |
| HEVC, SPEED | 12.05 | 82.3 | 11,780 | 719,126 |
| HEVC, statistics packet off | 15.83 | 62.6 | 15,386 | 720,567 |
| HEVC, quality-tuning fields zeroed | 15.68 | 63.2 | 15,196 | 709,199 |
| H.264, no preset | 12.81 | 77.7 | 12,472 | 2,014 (simple) |
| H.264, BALANCE | 11.07 | 90.0 | 10,726 | 2,014 (simple) |

The firmware default without a preset op is slower than its explicit QUALITY mode. BALANCE
and SPEED are identical on this firmware. This closes most of the gap to Linux (11ms whole
pipeline) and gives 4K60 HEVC ~4.6ms of headroom per frame instead of ~0.9ms.

Candidate284 delivers the fix as three guarded copy-on-write byte patches in the encoder
process through the existing AMDRadeonVADriver2 image-patch path (`rgpuvcnpreset=1`):
`addPresetEncodeModePacket` loads a constant BALANCE op, and the HEVC and H.264 builders call
it every frame. Output validity still needs a decode or live stream check.

## Candidate284: preset fix delivered by the kext

Run `b0b2203cac7f308cda074d150d24af9b` (candidate284/metal132, attempt `r2`, MODE2#183, host
boot `3c3ae1cb`). The first attempt (`f5db7368`) was refused before QEMU by a flagless-reuse
admission bug: `reserve_boot` validated schema-6 receipts without the manifest's recovery helper
hashes. Fixed in commit `7dd9cc0` with a regression test that fails without the fix; suite 972 OK.

Serial shows every encoder process patched at all three sites (`VCNPRESET: COW target=
preset-value|hevc-gate|avc-gate ... p=0 w=0 r=0 v=0`). Same probe matrix, no dtrace attached:

| Codec | Size | Content | Before (283) ms / fps | Candidate284 ms / fps |
|---|---|---|---:|---:|
| HEVC | 3840×2160 | simple | 15.04 / 65.4 | 11.15 / 88.2 |
| HEVC | 3840×2160 | noise | 15.81 / 62.3 | 11.87 / 82.9 |
| HEVC | 3840×2160 | simple, realtime off | 15.13 / 65.0 | 11.12 / 88.5 |
| H.264 | 3840×2160 | simple | 12.70 / 78.1 | 10.92 / 90.8 |
| HEVC | 2560×1440 | noise | 7.40 / 132.9 | 5.86 / 168.1 |
| HEVC | 1920×1080 | noise | 4.44 / 214.8 | 3.41 / 279.3 |

4K HEVC now matches the Linux VAAPI whole-pipeline figure (11ms, 91fps) on the same silicon.
Further knobs on top of the patch, dtrace A/B (4K HEVC noise, VCN wait ~11.7ms throughout):
SAO disable 11.80ms, deblocking disable 11.84ms, both 11.75ms, i.e. no material change. The
live deblocking packet already carries the SAO-disable field set, which is why SPEED and BALANCE
measure identically. The remaining per-frame cost is the VCN hardware itself.

## Live stream: VRAM exhaustion, not the encoder, limits the desktop stream

Same candidate284 run, user streaming 4K60 HEVC from Moonlight on the host while using the
desktop and then playing a YouTube video in Safari. User reports ~40fps on the desktop, 15–20fps
with the video, and occasional 2–3s freezes.

- First 11s, light use: Sunshine submitted 56–60 frames/s; VCN wait mean 11.0ms; Metal pre-pass 3.6ms.
- 60s of normal use: 31–61 submissions/s, most seconds 35–50; worst VCN wait per second 25–72ms.
- 20s with more activity: VCN wait mostly 8–12ms but per-second averages 15–19ms in the slow seconds;
  the Metal pre-pass is bimodal, ~60% at 2–4ms and ~40% at 8–30ms. WindowServer commits 220–350 Metal
  command buffers/s with no clean 1:1 correlation.
- YouTube playing: encode VCN wait averages 25–36ms, then 86ms; Sunshine 18–25 then ~11 frames/s.
  `VTDecoderXPCService` made no AMDRadeonVADriver2 decode calls (software decode), guest CPU 89% idle
  on 8 vCPUs, host 88% idle, so neither VCN sharing nor CPU starvation explains it.
- The guest reports `VRAM (Total): 512 MB`. The sampled allocation-failure log (one line per 1,024
  failures) reached 1,017,856 failures and added 79 lines in 20s during playback (~4,000 failures/s).
  Failing requests are 22–33MB (a 3840×2160 BGRA surface is 33.2MB) with 8–72MB VRAM free.

Conclusion: the 512MB BIOS UMA carve-out cannot hold a 4K Retina desktop, browser video and 4K
encoder surfaces, so the driver continuously evicts and retries allocations, stalling GPU waits in
both the encoder's Metal pre-pass and its completion path. Next test: raise the BIOS UMA frame buffer
size (2–4GB) and repeat the same live measurements. Reduce Transparency showed no benefit (the video
started during that window) and was reverted.

## 2GB UMA: VRAM stalls gone, capture path is the next limit

Host boot `7ee81442-5848-489e-9853-9fbeff78a8c2`, BIOS UMA frame buffer 2GB. amdgpu reported
2048MiB; the guest kext derived `FB base=0xf400 top=0xf47f offset=0x7e0` from the FB_LOCATION
registers (physical base moved 0x840000000→0x7e0000000). The first run (`688172f0…`, attempt `uma2g`)
booted but was classified INVALID and failed recovery because host tools still hardcoded the 512MB
aperture and `CONFIG_MEMSIZE 0x200`. Commits `5558426` and `3e6ad72` derive the carve-out from the
boot's MODE2 receipt and the serial `XR: … FB base/top/offset` line everywhere. Run
`324d8b6ea3ab75e34708b952f4e91528` (attempt `uma2g2`) was CORE_PROBE_PASS, with zero allocation
failures, and the user confirmed 4K60 was fixed.

At 120Hz and Retina, with the mouse moving, the stream still dropped to 10–70fps. Ruled out by
measurement: encode, VRAM, slirp networking (0% UDP loss up to 120 frame bursts/s), guest CPU, GPU
saturation and the AMD submission path. Sunshine's AVFoundation capture did two synchronous
`VTPixelTransfer` Metal jobs per frame: scaling, plus an NV12 range conversion because capture was
video range while Moonlight requested full range. With the mouse moving, those command buffers waited
avg 7ms and max 100ms behind WindowServer (`renice -20` plus `taskpolicy` tier 0: avg 5, max 38).

## Sunshine: capture color range and ScreenCaptureKit

Two guest Sunshine patches, both applied to the capture-lock baseline and deployed to
`/Applications/Sunshine Capture Fix.app`:

- `patches/sunshine/v2026.914.233613-capture-color-range.patch` captures NV12 in the session's range
  (`420f` for full range), which removes the encoder's range-conversion transfer.
- `patches/sunshine/v2026.914.233613-sckit-capture.patch` ports upstream Sunshine PR #5511
  (SCStream capture, AVFoundation fallback) and adds a log line naming the backend. Zero-copy NV12 and
  full-range handling are carried into the SCKit path. The delta is relative to the color-range state.

Result (run `a8ac7432f1896779b154f619594898e9`, attempt `uma2g3`): Sunshine performs no GPU work of its
own anymore. The stream is fully paced, and the user reports it "100% more stable… no more stuttering"
at 60fps. Operational notes:
- Every ad-hoc re-sign drops the Screen Recording and Accessibility TCC grants. Sunshine then aborts
  with "Unable to find display or encoder" (every encoder probe fails with no frames) and mouse and
  keyboard input stop working. The app is now signed with a stable local identity
  ("RaphaelGPU Sunshine Local Signing", designated requirement `identifier
  "dev.raphaelgpu.sunshine.capturefix" and certificate leaf = H"7d000ad2…d64d"`; keychain under
  `~/Developer/sunshine-capturefix/signing` in the guest), so future rebuilds keep the grants.
  Grants were re-added once by the user (Screen Recording 13:17, Accessibility 13:25).
- The stock `/Applications/Sunshine.app` was removed (zip backup in
  `~/Developer/sunshine-capturefix/`); a second copy had failed to bind RTSP port 49010.
- After every new guest run, QEMU `hostfwd_add` rules for tcp 48984/48989/48990/49010 and udp
  48998–49000 must be added before the LAN relay reaches Sunshine. Otherwise Moonlight shows the host
  offline.

## 120Hz: macOS virtual displays vsync at a hardcoded 60Hz

With SCKit at a 120Hz virtual display mode and a 4K120 Moonlight session, the stream stayed at ~60fps.
WindowServer ran `CGXUpdateDisplay` only ~52 times/s in every mode (1080p, 1440p, Retina, 60/120Hz),
at 16ms/32ms intervals with <1ms per update, although `CGXScheduleUpdateDisplay` asked ~95 times/s.
SCKit copied every update, so capture was not the limit. `CDDisplay::refresh_timing` reported a VBL
delta of 16,666,668ns on an exact 1/60s grid.

CoreDisplay `VFBGetVBLTiming` (24G830 address 0x7ff80407ee4b) uses period = 1/int(mode[cur]+0x24)
when VFB byte +0x308 is 1 (true for CGVirtualDisplay). The mode table is `[[dev+0x160]+0x178]`, with
0xd4-byte entries and the current index at +0x74. `_CGXVirtualDisplayApply` builds each entry: it
copies the constant vector `{32, 8, 3, 60}` into +0x18..+0x27 and later writes the correct 16.16
refresh into +0xbc. So the 16.16 field reads 0x780000 (120) while the integer field is always 60.
`CGVirtualDisplaySettings.refreshDeadline` does not change this.

Live proof: a destructive dtrace `copyout` wrote 120 into the current entry's +0x24 inside
WindowServer (`~/macos-vm/run/c284-vfbpoke.sh`). The VBL delta became 8,333,334ns and SCKit delivered
112–122 frames/s. The poke is lost on a mode change or display re-creation. BetterDisplay users report
the same 60Hz ceiling for virtual screens.

What 120Hz exposes: at 4K the VT plugin spends ~5ms on a Metal pre-pass plus ~10ms waiting for VCN per
frame, serialized, so Sunshine sent only 66–83 frames/s from 120 captured. The uneven drops look worse
than a steady 60. Safari also caps page animation (testufo) at 60fps ("Prefer Page Rendering Updates
near 60fps"). 4K120 is not reachable on this VCN. 1440p120 (5.9ms encode) and 1080p120 should be.

### Permanent fix design (not yet built): guarded COW patch in CoreDisplay

Image `/System/Library/Frameworks/CoreDisplay.framework/Versions/A/CoreDisplay` (dyld shared cache,
24G830), UUID `B52FFBDE-B5F7-3F53-8D5E-2A822E7EE75E`, unslid `__TEXT` 0x7ff80404a000. Patch 98 bytes at
TEXT+0x371de (0x7ff8040811de..0x7ff80408123f) inside `_CGXVirtualDisplayApply`'s mode loop, where
r14 = entry+0x30:

```
original: 448b759cf20f108520fffffff20f5905a6f20b00f20f580566f10b00660f3a0bc009f2480f2cc0
          488b4d88488b8978010000440fafbd34ffffff488bb528ffffff4139f78b9578ffffff410f4fd5
          899578ffffff488b9568ffffff898411bc000000
patched:  0f1f4000f20f108520fffffff20f5905a6f20b00f20f580566f10b00f2480f2cc04189868c000000
          c1e8107505b83c000000418946f4448b759c440fafbd34ffffff488bb528ffffff4139f77e074489
          ad78ffffff0f1f8000000000660f1f440000
```

The patched code computes fixed = trunc(refresh*65536+0.5) exactly as before (the redundant floor
`roundsd` is dropped), stores it at +0xbc, and stores `fixed>>16` at +0x24, keeping 60 when that is 0.
It moves `mov r14d,[rbp-0x64]` after the writes and replaces the `cmovg edx` store with `jle; mov
[rbp-0x88],r13d`, so the flags for the following `cmovg esi,r15d` still come from `cmp r15d,esi`. The
rip-relative `mulsd`/`addsd` stay at their original addresses, and eax/rcx/rdx are dead after the
region. The encoding was verified with GNU `as`/`objdump` (98 bytes). Delivery: a new
`RaphaelTextureDiag` target (same mechanism as the VCN preset targets) that must apply in WindowServer
before the 120Hz virtual display is created. The display holder must then apply its modes after
WindowServer is patched.
