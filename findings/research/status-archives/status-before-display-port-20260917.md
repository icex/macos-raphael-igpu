# Status archive — superseded 2026-09-17 by the display-port session

## Host / final run

- Boot `2508eb6d-ddf3-497d-9774-00a7ecebe3ed`; GPU0000:7b:00.0 remains
  `vfio-pci`, `power/control=on`. Never cycle back to amdgpu within this boot.
- Run `526953460479934120e31312a466eccc`, candidate282/metal130,
  attemptcapturefix3, MODE2#178, exposure33: **valid CORE_PROBE_PASS**.
  Functional baseline passed; final capture valid; shutdown
  **exited-after-guest-request**; schema6 recovery **recovered**, authorizes_launch=true,
  receipt `2670fe978626419daa0b7bcb207d22e2`. Streaming performance is not qualified.
- Unchanged driver build `7a26b1a2f6694ae88ed889105de30bc7`, executable SHA256
  `9c7e5dffc64fef69e874ea3c8e7b940e9761caf53e31400d2dc68d1591724fc2`.
- Exposure33 allowance is consumed. Earlier capturefix/capturefix2 staging failures
  stopped before QEMU/VFIO and consumed no exposure. Recovery authorizes the
  technical relaunch path, not additional work after the user's stop instruction.
- LAN relay ended with this VM; UFW rules persist. Future forwarding must target
  the new exact container. Retina was1920×1080 logical /3840×2160 backing /60Hz;
  check/restore after login.90/120Hz remains unqualified.

## One-run continuation allowance (exposure34)

The user's instruction on 2026-09-17 to resume the Sunshine 4K60 slowness work and
test it end to end authorizes the next bounded experiment. Extend this boot's
allowance by **one exposure (34)** on boot `2508eb6d-ddf3-497d-9774-00a7ecebe3ed`
for candidate282/metal130, attempt `clock1`: unchanged driver build
`7a26b1a2f6694ae88ed889105de30bc7`; measure effective GPU clock/bandwidth in the
guest with `tests/gpu_clock_probe.m`, and measure delivered Moonlight-Qt FPS from
the Linux host at 4K60 HEVC/H.264 with cursor motion. Prior run's schema6 recovery
`2670fe978626419daa0b7bcb207d22e2` authorizes relaunch. Use tools/cycle.py, fresh
MODE2, maximum 6000 seconds; `--manual-reuse`/`--ack-risk` no longer exist (same-boot
reuse is admitted automatically from this recovery receipt) and all existing identity,
host-fault, capture, shutdown and cleanup gates apply. No vfio→amdgpu cycling; no clock
writes in this attempt (measurement only).

## Tonight's streaming result

The separate “Sunshine Capture Fix” app builds and runs with user-approved capture
permissions. It removes CPU base-address locks on hardware NV12/P010 buffers;
valid CoreVideo probes observed no such calls during streaming. The user reports
clear output, but cursor-motion stalls remain. A light4K60 HEVC trace completed
553 submissions/13.001s with mean22.32ms. **Lock removal alone is insufficient**;
no matched original-versus-patched throughput improvement is established.

Native encoder completion waits average20.70ms and Metal preprocessing waits7.83ms
in a separate trace. Worker waits overlap and must not be added. These measurements
are host-side wait durations, not isolated GPU-engine execution times.

The20Mbps CLI-only bitrate control felt worse and yielded240 and192 submissions
in two13s traces, with multi-second outliers. It was rejected and **removed before
shutdown**. Saved configuration remains hardware-only VideoToolbox, realtime,
`hevc_mode=2`; no resolution downgrade or persistent bitrate cap. The original
signed `/Applications/Sunshine.app` is intact. The experimental app is not a
self-contained release or a login default. Foundation replacement stays cancelled.
[Measurements, configuration rollback and final receipts](findings/research/sunshine-capturefix-live-20260916.json).

## Next session

1. Re-read live host/repository state and obtain the next user instruction before
   any run. Preserve normal lifecycle/identity/capture gates and per-boot accounting.
2. Establish matched original/patched4K60 HEVC motion controls. Separate client
   delivery, server submissions and cursor latency; avoid concurrent stack sampling.
3. Correlate native video-memory reclaim latency with encoder stalls. Live logs
   contain many recoverable allocation retries; their production cost is still
   unmeasured. Do not mistake failure counters for a proven leak or exhausted memory.
4. If reclaim is not material, isolate surface reuse, Metal preprocessing and VCN
   completion. Do not infer clocks from compatibility counters or probe the shared
   SMU mailbox concurrently from the host. No new allocator/cursor/power patch yet.

## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-284-results`
- Verdict: `INVALID`
- Boundary: `identity_or_route_missing`


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-284-attempt-r2-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-284-attempt-uma2g-results`
- Verdict: `INVALID`
- Boundary: `vmid2_entry_update_child_invalid`


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-284-attempt-uma2g2-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-284-attempt-uma2g3-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`
