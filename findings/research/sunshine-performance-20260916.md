# 4K Sunshine: hardware encode path, severe reclamation stalls

Run `2456747451ac073cf5fa0ea1657590cf`, candidate280, same supervised
retinarestore exposure30. [Artifact hashes](sunshine-performance-20260916.json).

LAN pairing and actual desktop streaming now work. The user reports HEVC at4K
and about4FPS, slower than Apple Screen Sharing. This is a reproduced usability
failure, not a successful low-latency streaming milestone. No delivered-FPS trace
or Moonlight screenshot has been captured independently yet.

## Observed active stream

Sunshine selected `hevc_videotoolbox`, SDR8-bit, about89.388Mbps, nominal60FPS.
Configuration requires VideoToolbox with software fallback disabled. Active
sampling of VTEncoderXPCService3490 follows AppleGVAHEVCEncoder into
`AMDRadeonVADriver2::VAUveEncoder::EncodePicture`, native submitDataBuffers and
IOAccelResourceFinishEvent, plus Metal command-buffer waits. This establishes
hardware-driver participation despite the user's0%GPU process counter; it does
not qualify its throughput. Sunshine's session-video thread was in
VTCompressionSessionEncodeFrame in277/282 samples (mostly semaphore/mutex waits).

An initial earlier counter read landed after disconnect and must not be used to
infer active encoder utilization. The later samples are from a connected session.

## Native reclaim timing

A bounded12-second DTrace aggregates native IOAcceleratorFamily2
`freeWaitToPrepareVidMap` entry/return by current PID, with nested calls tracked
per thread/depth. No AMD entry was patched or routed. Results:

| Process | Summed reclaim time | Maximum call | Failed wire returns |
|---|---:|---:|---:|
| Sunshine |4,547,039µs |457,857µs |2,577 |
| VTEncoderXPCService |3,195,320µs |463,990µs |1,800 |
| WindowServer |3,387,273µs |459,508µs |3,375 |

These times can overlap and include nested intervals; do not sum them into a
single wall-time percentage. They include DTrace overhead and are not uninstrumented
performance benchmarks. They demonstrate expensive reclamation during the failing
workload, beyond the earlier observation that failed allocations can eventually
recover correctly. Full causal attribution needs a same-workload intervention.

A separate5-second host observation found2,639 allocation-failure lines/366,647
serial bytes and91.3ms relayCPU. The host Ethernet link reports1000/full. Relay
socket snapshots report no drops. These observations argue against simple link
capacity or relay CPU saturation, but do not independently rule out network loss,
client decoding or packet burst behavior.

## Source and next comparison

Tagged Sunshine sources already choose NV12 capture and retain the CVPixelBuffer
for VideoToolbox, avoiding a separate generic CPU swscale conversion on that path:
[display.mm](https://github.com/LizardByte/Sunshine/blob/v2026.914.233613/src/platform/macos/display.mm),
[nv12_zero_device.cpp](https://github.com/LizardByte/Sunshine/blob/v2026.914.233613/src/platform/macos/nv12_zero_device.cpp).
Capture uses AVFoundation AVCaptureScreenInput in this tag; the presence of
ScreenCaptureKit in loaded libraries alone does not identify the actual capture path.
No configurable capture queue-depth setting was found. The requested speed and
reference-frame properties are rejected/ignored by the native encoder, per its log.

Next compare H.264 at the same4K/60FPS client settings, retaining the60Hz Retina
desktop. Time capture/encode entry points if available, then investigate native
UMA allocation/reservation policy using the supplied24G830 sources. Do not inflate
VRAM beyond the discovered physical capacity or suppress allocation errors as a
substitute for fixing the stalls. Final session shutdown/recovery remains pending.

## Direct encoder timing follow-up

A12-second PID-provider trace of Sunshine's avcodec_send_frame and
VTCompressionSessionEncodeFrame independently records44 started /43 completed
submissions and11,692,838µs inside completed send calls. Most take131–262ms;
eight take524–1049ms. VT and outer send histograms match. This directly locates a
major throughput limit before network transmission. Observer overhead remains a
qualification limit, but agrees with the user's3–4FPS observation.

The user reported3FPS after the requested H.264 comparison; however, the new
21:02:34 session log still selectsHEVC. Do not claim a confirmed H.264 A/B result.
`sunshine-encode-timing-output.txt` contains the trace and exact session log.

## Failure-path logging hypothesis

A separate12-second trace of allocateLargeBlocks shows failed calls consuming
3.048s(WindowServer),4.006s(VTEncoder),4.048s(Sunshine) across1,646/2,150/2,183
failures. Nested allocPages calls consume only35–39ms per process in that window.
Another12-second trace sees total_free consume15–21ms per process. These are
separate workload windows, not an exact subtraction; the gap strongly motivates
isolating the failure diagnostic. Profile-provider samples yielded no stacks and
are not evidence of where CPU time was spent.

Exact24G830 assembly has one kprintf call atX6000+0x53370 on the failure path,
after free-space queries and before native failure-count updates. Preserve
allocation results and counters. A call-site-specific sampled logger is the next
candidate; no global printf hook, pool inflation or recovery-gate change is justified.
