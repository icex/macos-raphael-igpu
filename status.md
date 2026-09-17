# Live status — 2026-09-17, stopped for the day

**4K60 streaming is stable. A true 120Hz virtual display is proven but not yet permanent.**
No GPU guest is running. [Evidence](findings/research/encoder-pipeline-20260917.md).

- **Encoder:** candidate 284 (merged into `dev`) forces the VCN BALANCE preset through guarded COW
  patches in AMDRadeonVADriver2. 4K HEVC encodes in 11.15ms (88fps), matching Linux VAAPI.
- **VRAM:** the BIOS UMA carve-out is now 2GB, with zero allocation failures. The host classifier
  and recovery tools detect the carve-out size and base automatically (commits `5558426`,
  `3e6ad72`).
- **Capture:** guest Sunshine uses ScreenCaptureKit with session-range NV12
  (`patches/sunshine/*sckit-capture.patch`, `*capture-color-range.patch`). The user reports a stable
  stream with no stutter at 60fps. The app is signed with a stable local identity, so rebuilds keep
  its Screen Recording and Accessibility grants. The stock Sunshine.app was removed.
- **120Hz:** CoreDisplay derives the virtual display vsync from a mode-table integer field that is
  hardcoded to 60. A live WindowServer poke gave an 8.33ms VBL and 112–122 captured frames/s. The
  permanent 98-byte CoreDisplay patch is designed and assembler-verified but not built (roadmap
  item 1a). 4K live encoding tops out at ~66–83fps, so use 1440p/1080p for 120fps.
- **Last run:** host boot `7ee81442-5848-489e-9853-9fbeff78a8c2`; GPU 0000:7b:00.0 on `vfio-pci`.
  Run `a8ac7432f1896779b154f619594898e9` (candidate 284, metal-132, attempt uma2g3, MODE2#186):
  CORE_PROBE_PASS, shutdown **exited-after-guest-request**, recovery **recovered**
  (authorizes_launch=true, `57f800271df14d75b553062c4d75de08`).

## CI portability — 2026-09-17

Run `35143887854` failed on missing NumPy/Pillow, shallow Git history, a local-only
Lilu fixture and host KVM permissions. The repair supplies the CI dependencies and
history and makes both fixture tests independent of host installations. Local
validation: 965 Python tests OK (3 skipped), both software-UART qualifications
and all CI C++/sanitizer checks pass. Hosted validation follows on `dev`; this
changes no hardware qualification or launch authority.

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
| Host regression | 965 tests OK, three skipped |

Earlier texture recreation (144 cases / 131,031,576 pixels), feedback rendering
(48 cases / 5,280,000 pixels), and hardware H.264/HEVC encode/decode retain their
separately documented passing scopes. Explicit decoder GPU-ID selection remains
a selection limitation on the built-in topology; automatic required-hardware selection works.

Prior qualified280 driver build `51bfd732cf824249b70981f0c36fe314`; executable SHA256
`7d06082f35959f900b5c59cb5f6d9e2efc67df13e935d338d7783524df63259b`.
Current stock QEMU image `sha256:3a3c82c79bc4e73531f819ccdfa4053b3084efd7c1f645678dbf8b4b3a24369c`.
Default experiment pin now selects this stock image. VirtualSMC1.3.7/gen2 and the
exact OpenCore DSDT ownership patch are required; prior media backups remain available.
[Address/desktop qualification](findings/research/address-reclaim-desktop-20260916.md),
[artifact hashes](findings/research/address-reclaim-desktop-evidence-20260916.json),
[native retry analysis](findings/research/allocation-retry-analysis-20260916.md),
[visual fix](findings/research/feedback-decompression-20260916.md).


## Remaining roadmap

1. Sustained4K remote delivery and input latency; preserve crisp Retina60Hz,
   then qualify login persistence.90/120Hz modes remain unproven.
2. Guest-crash/command-channel failure, repeated lifecycle and independent-host-boot
   qualification. Existing clean stops do not qualify every failure mode.
3. Broader applications, render hazards, interprocess synchronization and page-table
   release. Historical direct OpenGL hang and live Metal validation crash remain open.
4. Physical DCN output, other hypervisors and measured performance/release qualification.

StockQEMU10.1.2/OpenCore/VirtualSMC1.3.7 works in this tested setup;
PerfPowerServices was0.0% CPU on two guest boots. Automatic required-hardware HEVC
decode works; explicit GPU-ID selection remains limited. Main10 decode has scoped
passes; hardware encode is Main8. [Roadmap](docs/ROADMAP.md).

After milestones update current docs, integrate/push dev and synchronize the local
checkout. Do not push main without new authorization. Prior live entries and
consumed allowances are [archived](findings/research/status-archives/status-before-night-close-20260916.md).


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
