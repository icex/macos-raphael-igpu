# Streaming investigation: end-of-night handoff — 2026-09-16

The user stopped work for the night. Do not resume launches from this note alone;
read current status, host/repository state and the next user instruction first.

## Outcome

The desktop remains visually clear. The user confirms that cursor motion causes
slowdown everywhere, not only over transparent Safari. Sustained4K60 streaming
and input latency are unresolved. No driver change was made in this experiment.

Sunshine's NV12/P010 CPU-lock removal builds and runs after the user granted its
separate Screen Recording permission. A valid CoreVideo probe records no matching
CPU locks in the active stream. The lighter4K60 HEVC trace still has553 submissions
in13.001s, mean22.32ms. User-visible clarity is a scoped observation, not a pixel
oracle or release qualification. The change is insufficient to fix streaming;
there is no matched original-versus-patched throughput improvement claim.

A separate native-stage trace measures421 AMD completion waits totalling8.714s
(mean20.70ms) and420 Metal preprocessing waits totalling3.289s (mean7.83ms).
These execute on overlapping workers: do not add their durations. Its first send
bucket is second3, so elapsed-time averages do not describe uninterrupted output.

A temporary20Mbps CLI cap at unchanged4K60 HEVC made the user's experience worse.
Two traces had240 and192 submissions/13s with multi-second outliers. This rejects
keeping that control as a remedy; it does not prove bitrate alone caused the
stalls. The cap was removed and the original configuration restored before stop.
HEVC remains enabled; no persistent bitrate or resolution downgrade was written.

## Exact setup

- Driver282, unchanged build7a26b1a2f6694ae88ed889105de30bc7;
  executable SHA2569c7e5dffc64fef69e874ea3c8e7b940e9761caf53e31400d2dc68d1591724fc2.
- Run526953460479934120e31312a466eccc, attemptcapturefix3, MODE2#178, exposure33,
  host boot2508eb6d-ddf3-497d-9774-00a7ecebe3ed.
- Retina1920×1080 logical /3840×2160 backing /60Hz; restore/check after login.
- Original signed app: `/Applications/Sunshine.app`, preserved for comparison.
- Experimental app: `/Applications/Sunshine Capture Fix.app`, ad-hoc signed,
  bundle ID`dev.raphaelgpu.sunshine.capturefix`. Not a self-contained release:
  it links guest Homebrew libraries and uses assets in its build directory.
- Guest source/build: `/Users/bogdan/Developer/sunshine-capturefix/`.
  Original upstream tagv2026.914.233613, commit63d35f702ee9e362e43263742981836ec0710384;
  pinned FFmpeg releasev2026.910.121303. Patch and build hashes are linked below.
- Configuration: `/Users/bogdan/.config/sunshine/sunshine.conf`, hardware
  VideoToolbox, `vt_software=disabled`, `hevc_mode=2`, `vt_realtime=enabled`.
  Do not print pairing/credential files. Experimental app was not made a login default.
- Existing LAN ports489xx/UFW rules remain; the exact-instance relay exits with
  the VM. A future run needs its own identity-bound forwarding/relay.
- Worktree `/home/bogdan/macos-vm/run/worktrees/candidate-282`;
  results `/home/bogdan/macos-vm/run/candidate-282-attempt-capturefix3-results`.

## Next discriminating work

1. Establish a matched original/patched4K60 HEVC control using the same pointer
   workload and fresh PIDs. Keep resolution, bitrate, content and client fixed;
   avoid simultaneous stack sampling when measuring frame timing.
2. Measure native resource-reclaim time alongside encoder waits. The live serial
   tail reached allocation-failure counter518144, with repeated12–62MiB requests
   and variable free capacity. These are recovered internal failures in earlier
   correctness tests, not proof of a leak or exhaustion. Reclaim *cost* in this
   stream remains unmeasured. Reuse `tests/allocation_reclaim_trace.d` and the
   existing host script`/home/bogdan/macos-vm/run/sunshine-reclaim-profile.sh`,
   validating native symbols before tracing. Correlate thread/process/time;
   do not infer GPU execution time from a blocked event wait.
3. If reclaim is not material, separate surface reuse, Metal preprocessing and
   native VCN completion. Do not invent GPU clocks from zero-valued compatibility
   counters or access the shared SMU mailbox concurrently from the host.
4. Input audit found CoreGraphics event posting followed by cursor warping in
   libvirtualhid. No cursor-policy change was built/tested; direct warp calls are
   usually sub-millisecond and do not alone explain the encoder stalls.

No further experiment tonight. Final shutdown/capture/recovery receipts and the
live host state belong in `status.md`; no new same-boot exposure is authorized by
this handoff. Earlier pre-exposure staging failures did not consume entries.

[Live measurements and hashes](sunshine-capturefix-live-20260916.json),
[build/initial rollback](sunshine-capturefix-build-20260916.json),
[allocation/retry semantics](allocation-retry-analysis-20260916.md),
[patch](../../patches/sunshine/README.md).
