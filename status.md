# Live status — 2026-09-24

## Candidate321: full HiDPI picture; low-resolution interleaving remains

Run13246b9a0f02e33e0a4bb92d2e55f6d0, MODE2#249, source2242840, metal169.
VPG0 memory wake0x110→1 before native infoframe writes. User: "I see full picture"
and "default looks almost perfect, it just needs120hz". Verified awake1080HiDPI
(3840x2160pixels60Hz). Native AVI packet advertisesYCbCr444. Pixel correctness
has not been independently measured; no remaining pink complaint on this build.
Low-resolution1920x1080@60 still interleaved (user confirmed twice). HDMI packs
10-bit while PHYPLLA resync ratio remains0 (8-bit): HDMI0x11010019, PHY0x103.
Restored HiDPI before stopping. Core probe passed, finalCORE_PROBE_PASS, complete
capture; exited-after-guest-request, recovered/authorizes_launch=true. No VM now.
1020 host tests pass (3 skipped). Next322 aligns PHY deep-color ratio with native
HDMI packing, then qualifies1080p60 and120Hz. HiDPI120 is a separate4K link mode.
HDMI audio follows usable video; physical audio function remains host-owned.

Evidence: [VPG/deep-color investigation](findings/research/hdmi-vpg-and-deepcolor-20260924.md),
run/c321-vpg-scanout.json, c321-native60-scanout.json, c321-awake-check.txt,
c321-hidpi60.txt, c321-native60.txt, c321-restored-hidpi60.txt, candidate-321-results.
Native-fetch milestone89b5ab1 is published on dev via working SSH credentials.
This full-picture improvement is ready for integration; main unchanged. Fresh
candidate branches, remote dev fetched, autonomous tests/resets; no reboot or sudo.

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
