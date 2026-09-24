# Live status — 2026-09-24

## Candidate320: native HDMI image visible, incorrect color/layout

Run309ef9a1e0b27ae7f7fab0b73f04ea45, MODE2#248, source9b5503b, metal168.
DET0=0x303 assigns missing192KiB; fetch timeout/underflow clear and flips complete.
User confirms **1080 HiDPI gives an image with pink hue**, low-resolution1080p is
interleaved/pink,30Hz black,120Hz not visibly usable. HiDPI live capture is3840x2160
pixels,8-bit HDMI, RGB encoder/FMT; low-resolution capture is1920x1080pixels,
10-bit HDMI. Correct image quality and120Hz remain unqualified. No test generator.
Awake assertions verified before tests. Core probe passed, finalCORE_PROBE_PASS,
complete capture; stop-requested, exited-after-guest-request, recovery authorizes
same-boot reuse. No GPU VM running after this run.1020 host tests pass (3 skipped).

Next: Linux dcn31_vpg_poweron wakes infoframe memory; live VPG0_MEM_PWR=0x110 shows
it is still forced asleep. Candidate321 will wake it before native packet writes,
retaining HiDPI to isolate the pink hue. Separately,10-bit low-resolution commands
have deep_color_ratio=0 and need investigation before120Hz qualification.
Evidence: [DET investigation](findings/research/dcn315-missing-det-20260924.md),
run/c320-det-scanout.json and c320-user-mode-scanout.json; complete receipts in
candidate-320-results. Temporary color-window capture failed and did not qualify
pixel correctness. HDMI audio remains host-owned; follows usable output.

Dev previously publishedc5570b0 via SSH (HTTPS token invalid). Candidate320 native
fetch milestone is ready for integration; main untouched. Fresh candidate branches,
fetch remote dev, autonomous test/reset authorization; no reboot or host sudo.

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
| Host regression | 1020 tests OK, three skipped |

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
checkout. Do not push main without new authorization. Prior live entries are [archived](findings/research/status-archives/status-before-display-port-20260917.md)
and [earlier](findings/research/status-archives/status-before-night-close-20260916.md).


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-319-results`
- Verdict: `INVALID`
- Boundary: `identity_or_route_missing`


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-319-attempt-fetch-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-320-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-321-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`
