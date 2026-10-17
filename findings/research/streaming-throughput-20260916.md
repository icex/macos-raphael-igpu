# Remaining4K streaming cost — 2026-09-16

Historical measurements from candidate282 run560b1d7e8fea56b2c6f52fd7644d23f8,
which subsequently stopped with valid capture and clean recovery. The later
capturefix3 run also closed cleanly; its capture-lock patch did not fix motion
stalls. See the [end-of-night handoff](streaming-handoff-20260916.md) for current
results and next steps. No clock change was performed in these investigations.

## Live stream

User reports1080p60 and4K20–30FPS, with high VTEncoder GPU usage at4K.
A12-second active HEVC trace captures451 completed submissions,452 started,
10.783374seconds summed submission time (~23.91ms each). Most samples fall8–65ms;
this is~38 completed submissions/second, not proof of identical delivered client FPS.
Latest negotiated bitrate62,988,000, SDR8-bit. The exact frame dimensions were not
independently recorded in this timing window;4K is the requested user comparison.
Sunshine thread sample has409/440 samples inside VTCompressionSessionEncodeFrame,
mostly mutex/semaphore waits; broadcast thread waits for queued output. This
locates server backpressure, not the exact GPU sub-engine.

A stale VTEncoder PID sample failed; a later rediscovered PID sample was idle after
disconnection. Neither establishes active encoder internals. Two later bounded
stream/buffer traces found no active connection and produced no measurements.
IORegistry utilization/clock counters are zeros through the compatibility backend;
do not equate these with a real idle GPU or actual0MHz.

Correction: the Sunshine message "Minimum FPS target ~30" does NOT imply a30FPS
client request. Tagged source video.cpp sets the default to requested_framerate/2
for repeated frames when capture is quiet. The prior commentary inference was wrong.
[Exact source](https://github.com/LizardByte/Sunshine/blob/v2026.914.233613/src/video.cpp).

## Encoder-only discriminating probe

`tests/video_encoder_throughput_probe.m` requires hardware encode and reported
hardware=true. It enables realtime, no reordering, expected60FPS, key interval120,
average bitrate63Mbit/s. Six simple immutable NV12 IOSurfaces are filled before
measurement.12 warmup frames flush and must complete correctly; then120 measured
frames flush and must produce120 callbacks without error. A60-second alarm bounds it.
Frames vary among six simple quadrant patterns. These are throughput checks,
not decoder pixel-validation or complex desktop/actual63Mbit/s content benchmarks.

| Workload | FPS | Submission total | CPU buffer preparation | Encoded bytes |
|---|---:|---:|---:|---:|
| HEVC1080p reused |210.15|0.542921s|excluded setup|87176|
| HEVC4K reused |64.75|1.822936s|excluded setup|236584|
| H2644K reused |76.77|1.550131s|excluded setup|241624|
| HEVC4K fresh allocation/copy per frame |41.47|2.326805s|0.517694s|236584|
| HEVC4K CVPixelBufferPool/copy per frame |58.89|1.933365s|0.072795s|236584|

All modes complete120 callbacks, zero errors, required hardware. Pool reuse follows
CoreVideo ownership: release after submission; VideoToolbox's retained references
prevent recycling in-flight pixels. No original surface is mutated. Pool mode
isolates allocation recycling while retaining the same per-frame CPU copy.
Wall time minus preparation is explicitly not GPU-only time because work overlaps.

This refutes a universal4K30 cap for simple input, and demonstrates a controlled
buffer-allocation optimization. It does not yet demonstrate a Sunshine fix.
Sunshine's tagged NV12 path directly retains capture CVPixelBuffers rather than
copying them. Its capture pool's actual reuse and CPU accessibility have not been
measured; inserting another pool/copy blindly could add GPU readback stalls.
[Source](https://github.com/LizardByte/Sunshine/blob/v2026.914.233613/src/platform/macos/nv12_zero_device.cpp).

## Next fix boundary

Capture an uninterrupted4K60 motion session with current VTEncoder PID and count
input-buffer reuse alongside per-stage latency. If capture surfaces churn, test a
recyclable pool on actual captured frames before deploying an application change.
If buffers already recycle, isolate encoder preprocessing/completion and content
complexity instead. H264 has more measured headroom but real-stream gain is untested.

Clock audit: Linux SMU13.0.5 GetGfxclkFrequency is mailbox message15. Query transport
writes shared argument/message/response registers; VCLK/DCLK require metrics-table
DMA setup/transfer. No concurrent host mailbox polling was performed. A future
in-driver telemetry path needs verified shared-mailbox serialization and identity
checks; no blind frequency-setting change is justified by current evidence.

[Evidence hashes](streaming-throughput-20260916.json).
