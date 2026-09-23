# Live status — 2026-09-23

## HDMI: candidate 297 completed, delivery blocked by inaccessible inbox

Run `f877ded2ff28ffbbfe241275270db0b3`, card `metal-145`, source `ab45629`,
boot `90122d1c-38ea-40af-9c35-ed2b6899c281`, MODE2 #218.

- **Functional:** DMCUB timer advances, SCRATCH0=0x43. Inbox CW4 maps to
  `fb+0x7fae5400`, beyond the 256 MiB PCI BAR. MM_INDEX reads returned zero for
  all four previous command slots: `UNUSABLE (0/4 sane headers, MM_INDEX)`.
  The delivery gate stayed closed; pixel-clock/encoder/transmitter commands were
  log-only. No guest panic observed. Samsung EDID is published as AppleDisplay;
  the desktop Metal probe passed offscreen checks with zero reported mismatches,
  but window presentation was not verified. Physical picture awaits user report.
- **Capture/qualification:** INVALID (`identity_or_route_missing`), with an
  incomplete CR2 transport line. Probe success does not qualify HDMI or capture.
- **Shutdown/recovery:** stop-requested plus the existing vm-supervision shutdown
  path stopped the container forcibly. The experiment recorded already-stopped;
  this is NOT a clean guest shutdown. Recovery receipt says recovered,
  `authorizes_launch=true`; post-run SMU version probe answered OK, CP_STAT=0.
- **Evidence:** `~/macos-vm/run/candidate-297-results/` (serial, probe, verdict,
  shutdown and recovery), `run/c297-post-mode2-probe.json`, `run/c297-post-dcn.json`.
- **Next discriminator:** establish why MM_INDEX reads zero: audit native CGS
  access against direct BAR MMIO and independently verify address translation
  before allowing inbox writes. Never load, start or reset DMCUB in the guest.

## Current host and delivery

No guest running after 297. GPU stays on vfio-pci with power/control=on.
Same-boot recovery is authorized; a fresh MODE2 reset remains required by cycle.py.
Candidate 296-d belonged to the prior boot and has no completed result receipts;
the host was already rebooted before this session. No recovery success is claimed for it.
GitHub authentication for icex and remote dev access verified. Candidates 291–297
are cumulative development, not physical-display qualification. Host suite: 1004
run, OK with three skips. Candidate 297 card capped at 6000 seconds.

HDMI audio follows a verified picture; USB/streaming audio retains its prior scope.
[Handoff](findings/research/handoff-hdmi-dmub-20260923.md),
[DCN research](findings/research/dcn315-first-init-20260923.md).
Superseded live entries: [archive](findings/research/status-archives/status-before-c297-20260923.md).

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
checkout. Do not push main without new authorization. Prior live entries are [archived](findings/research/status-archives/status-before-display-port-20260917.md)
and [earlier](findings/research/status-archives/status-before-night-close-20260916.md).






## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-298-results`
- Verdict: `INVALID`
- Boundary: `identity_or_route_missing`
