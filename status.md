# Live status — 2026-09-16

Candidate282's guarded allocation-diagnostic sampling patch is installed; generated
4K codec checks pass. The measured streaming comparison used **Moonlight-Qt
with hardware H.264**: the user reports 4K60, then clarifies it is better but still
imperfect: mouse motion over a transparent Safari window falls to about 40 FPS.
A 12-second server trace completes 663 submissions (~55/s), with a
5.69 ms mean and occasional 32–131 ms calls. Client and codec changed together;
neither alone is established as the cause of improvement. Sustained 4K60, latency,
remain open. Final capture, guest-request shutdown and recovery now pass.

## Current host / guest

- Host boot `2508eb6d-ddf3-497d-9774-00a7ecebe3ed`; GPU0000:7b:00.0 remains
  vfio-pci with power/control=on. Active application comparison run `526953460479934120e31312a466eccc`,
  attempt capturefix3, MODE2#178, exposure33. Interactive baseline passed;
  restored Retina3840×2160 backing at60Hz. Final capture/cleanup pending.
- Completed run `560b1d7e8fea56b2c6f52fd7644d23f8`, candidate282/metal130,
  MODE2#175, exposure32: valid CORE_PROBE_PASS; exited-after-guest-request;
  schema6 recovery `5c955d69cbbe4f5699fcf3d8fafc46c8`, authorizes_launch=true.
- Build `7a26b1a2f6694ae88ed889105de30bc7`, executable SHA256
  `9c7e5dffc64fef69e874ea3c8e7b940e9761caf53e31400d2dc68d1591724fc2`.
  Guarded ALLOCLOG sampling installed. Final capture valid; clean recovery does
  not close the streaming-performance blocker.
- Persisted Sunshine configuration keeps hardware-only H.264 and HEVC Main8
  (`hevc_mode=2`, `vt_software=disabled`), per user request. Pairing is preserved.
  Exact-instance LAN forwarding restored for capturefix3; web UI responds401
  as expected without credentials. Patched Sunshine is active after user-approved
  capture permission; hardware H.264 and HEVC detected. A temporary CLI-only
  max_bitrate=20000 comparison is awaiting client reconnect; config file unchanged.
- Retina was 1920×1080 logical /3840×2160 backing /2×/60Hz; login persistence
  still needs qualification. No 90/120Hz display claim.

### One-run continuation allowance

The user's latest instruction to proceed and fix motion-triggered streaming
latency authorizes the next bounded experiment. Extend this boot's allowance by
**one exposure (33)** on boot `2508eb6d-ddf3-497d-9774-00a7ecebe3ed` for
candidate282/metal130, attempt `capturefix3`: build/test the scoped Sunshine
GPU-buffer CPU-lock candidate and compare the same 4K60 workload. Prior run's
schema6 recovery authorizes relaunch. Use tools/cycle.py, fresh MODE2, maximum
6000 seconds, manual-reuse/ack-risk and all existing identity, host-fault,
capture, shutdown and cleanup gates. No vfio→amdgpu cycling or clock writes.
Exposure33 is now consumed by capturefix3; no additional launch is covered. The first staging attempt
(capturefix, MODE2#176) stopped at the unregistered282/131 card pair before QEMU;
no exposure consumed. The application comparison reuses the approved282/130
driver baseline and records its separate app hypothesis here. The second attempt
(capturefix2, MODE2#177) also stopped before QEMU because its isolated build
identity copy had not been prepared. Neither attempt consumed exposure33.

Candidate281 stopped cleanly with CORE_PROBE_PASS, valid capture and schema6
recovery authorizing relaunch. Its patch reported installed=0 because it compared
the import stub directly with kernel kprintf. User still observed3–4FPS.
Candidate282 validates the stub destination before changing only this diagnostic
CALL. Native allocation/retry/false returns/counters and global logging are unchanged.
[Investigation](findings/research/allocation-log-thunk-20260916.md).

## Current blocker and next observation

HEVC was confirmed at 62.988 Mbps while the user observed 20–30 FPS under mouse
motion and 60 idle. Active encoder stacks wait for native GPU completion and
Metal preprocessing. Capture still reaches approximately 60 buffers/s; its CPU
base-address locks cost 1.232 seconds total over 716 calls, with some 16–65 ms
calls. Those locks can contribute to uneven timing but do not explain the entire
encoder bottleneck. Cursor positioning also has occasional 16–65 ms calls.

After switching the server to H.264 and the user installing Moonlight-Qt, streaming
is visibly better. HEVC has since been re-enabled at the user’s request; measure
each codec separately for remaining pacing and input latency. The final moving
HEVC trace requested120FPS against a60Hz display:620 submissions/13.001s, with
full-second counts30–63 and mean20.67ms submission. The client reconnected at
60FPS at23:05:20, but the supervised deadline prevented a matching trace. Do not attribute the gain solely to the client or call 4K60 solved.
The capture-lock candidate is now live with user-approved Screen Recording access.
The valid CoreVideo probe records zero locks during active hardware capture, but
motion still slows everywhere on the desktop; the user confirms a clear picture.
A lighter trace completes553 submissions/13.001s, mean22.32ms. Native encoder
waits average20.70ms and Metal preprocessing waits7.83ms in a separate trace;
workers overlap, so those durations cannot be summed. Lock removal alone is
**not a sufficient fix**, and no matched throughput gain is established.
A temporary20Mbps CLI override at unchanged4K60 HEVC awaits client reconnect;
the first control trace had no active stream. Do not report a bitrate result.
[Live evidence](findings/research/sunshine-capturefix-live-20260916.json).
Foundation-sunshine replacement was cancelled by the user; the original app,
pairing and LAN ports are preserved. No Foundation binary or build dependencies
were installed. [Current evidence](findings/research/moonlight-qt-h264-20260916.md).

Prior scoped results remain: 24+60 generated 4K HEVC encode/decode frames,
689,188,500 checked luma samples, maximum error 2. Isolated 120-frame HEVC 4K
throughput is 64.75 FPS reused, 41.47 fresh and 58.89 pooled; H.264 reaches 76.77.
These simple patterns do not qualify real desktop streaming or establish the
hardware FPS ceiling. [Throughput investigation](findings/research/streaming-throughput-20260916.md),
[hardware capabilities](findings/research/9800x3d-streaming-capabilities-20260916.md).

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

1. Measure/fix4K remote delivery; preserve crisp Retina60Hz, then qualify login
   persistence.90/120Hz modes remain unproven. Screen Sharing RAW black captures
   are not a universal oracle for the user-visible Retina desktop.
2. Guest-crash/command-channel failure, repeated lifecycle and independent-host-boot
   qualification. One abnormal-QEMU-close/recovery/relaunch sequence has scoped evidence.
3. Broader applications, render hazards, interprocess synchronization and page-table
   release beyond cached address reuse. Historical direct OpenGL hang and live Metal
   validation crash remain unresolved; no blind reruns.
4. Physical DCN output, other hypervisors and measured performance/release qualification.

StockQEMU10.1.2/OpenCore/VirtualSMC1.3.7 works in the tested setup; two guest boots
verified0.0% PerfPowerServices CPU. Independent-host-boot durability remains open.
HEVC automatic required-hardware decode works; explicit GPU-ID selection remains
limited on this topology. Main10 decode passes scoped cases, encoder supports Main8.
[Roadmap](docs/ROADMAP.md), [setup](docs/stock-qemu-smc.md).

After each verified milestone update README/status/roadmap/current docs and push dev,
then fast-forward the clean local dev checkout. Do not push main without new authorization.
Licensing/provenance work remains tracked in[the audit](findings/research/licensing-audit-20260916.md).
The previous state and consumed allowances are[archived](findings/research/status-archives/status-before-allocation-thunk-20260916.md).


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-282-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`
