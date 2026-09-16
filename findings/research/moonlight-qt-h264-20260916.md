# Moonlight-Qt + H.264: improved 4K streaming, Safari pacing still open

Run `560b1d7e8fea56b2c6f52fd7644d23f8`, candidate282, host boot
`2508eb6d-ddf3-497d-9774-00a7ecebe3ed`. Build and original codec evidence remain in
[the allocation-diagnostic investigation](allocation-log-thunk-20260916.md).
[Artifact hashes](moonlight-qt-h264-20260916.json).

## Observed result

The user initially reported HEVC at 4K60 delivering 20–30 FPS with even small
mouse movements, 60 idle, and sluggish cursor motion. We changed the running
Sunshine server from HEVC advertisement (`hevc_mode=2`) to H.264 only (`1`) and
restarted that app, preserving pairing and all ports. The user then installed
Moonlight-Qt and reported 4K60, clarified as better but imperfect: moving over a
transparent Safari window drops delivery to about 40 FPS.

**Both codec and client changed.** This is not a controlled client-only comparison,
and neither sustained 4K60 nor a GPU hardware ceiling has been established.
The original signed Sunshine application remains installed. The requested
Foundation replacement was cancelled; no Foundation app or dependencies were
installed. Its source and Darwin dependency archives were fetched on the host.
The guest bootstrap exited at a missing `/usr/bin/df` path before Homebrew setup;
its empty scratch directory was subsequently removed.

## Timing and source evidence

| Observation | Scope |
|---|---|
| HEVC encoder submits 451 frames / nominal 12 seconds, mean 23.91 ms | Earlier active stream; not client delivery |
| H.264 completes 663 submissions / nominal 12 seconds, mean 5.69 ms | Active Moonlight-Qt session, about 55 submissions/s; most calls 2–4 ms, 18 calls 32–65 ms and one 65–131 ms |
| Capture locks: 716 calls / nominal 12 seconds, total 1.232 s | HEVC capture reaches approximately 60 buffers/s; mean lock 1.72 ms, occasional 16–65 ms calls |
| Cursor positioning: 16 calls, total 114.688 ms | 13 short calls, one 16–32 ms and two 32–65 ms; too few events to qualify input latency |
| Later H.264 trace: 60 submissions in each of two complete seconds | Stream disconnected during the trace; dividing 128 submissions by the entire 13-second trace would be misleading |
| Retina status after tracing | 1920×1080 logical, 3840×2160 backing, 2×, nominal 60 Hz |

The HEVC worker samples are active: native encoder completion waits and Metal
preprocessing waits are both present. Thread sample counts overlap and cannot
be added as wall-time percentages. Sunshine's capture callback also waits in
`CVPixelBufferLockBaseAddress` → `IOSurfaceClientLock`. The short source audit
confirms its wrapper locks CPU access unconditionally, while `nv12_zero_device`
passes a retained CVPixelBuffer to VideoToolbox without reading CPU pixels.

Apple documents that CPU access requires paired locks, while GPU access does not
require that lock and locking can impair performance:
[CoreVideo documentation](https://developer.apple.com/documentation/corevideo/cvpixelbufferlockbaseaddress(_:_:)).
A [source candidate](../../patches/sunshine/README.md) skips CPU access only in the
selected NV12/P010 GPU path. It preserves CPU locks for software/unknown formats,
checks failed locks, and preserves the pixel-buffer lifetime. It is **unbuilt,
undeployed and has no demonstrated streaming benefit**. Capture's near-60 rate
also means this lock alone is not established as the primary bottleneck.

A separate HEVC trace sees 56 distinct CVPixelBuffer pointer values across 228
submissions, with stalls among reused pointers too. Pointer reuse does not prove
underlying IOSurface reuse. One multi-second submission in that instrumented
window may include observer effects; it is not assigned to a hardware mechanism.

## Current configuration and remaining work

Sunshine PID8638, hardware-only VideoToolbox, H.264 only, SDR 8-bit Rec.709,
62.988 Mbps requested stream bitrate. Backup:
`~/.config/sunshine/sunshine.conf.before-h264-ab-282`. LAN ports and credentials
are unchanged. Initial H.264 low-delay probing returns -12902, then the upstream
fallback succeeds without allowing software encoding. Three initial IDR warnings
remain recorded; no claim that startup or all content is qualified.

The first Safari-specific trace found no active session and therefore collected
no workload evidence. A second bounded reconnect-triggered attempt also found no active stream. The
prepared trace measures capture, encoder submissions, cursor positioning and
WindowServer together once the workload is available.
Do not call transparent composition the root cause from the user-visible trigger
alone; confirm the actual active workload and distinguish GPU contention from
capture/encode waits and client presentation pacing.

Actual GFX/VCN clocks are still unmeasured. The Apple dummy SMU backend does not
provide trustworthy physical telemetry. Linux SMU13.0.5 source offers clock and
metrics queries, but they transact through the shared mailbox; no concurrent host
mailbox polling or power/clock changes were performed.

Functional improvement is user-observed and H.264 submission timing is measured.
The current run's final capture validity, guest shutdown and host recovery are
still pending. These results do not close full desktop or release qualification.
