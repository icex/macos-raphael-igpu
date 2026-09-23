# Live status — 2026-09-23

## Candidate 302: inbox writable; firmware did not consume command

Run `25a177f212dcd95fb62fb6ad46819ff7`, metal-150, source `aa5736a`,
boot `dc8add85-5070-419f-959d-6cc094c914be`, MODE2 #223.

- **Functional:** native host-tail reservation retained. Two complementary patterns
  in the empty inbox slot read back correctly; all 64 bytes restored and pointers
  unchanged. All 16 words of the first command passed readback. Firmware RPTR
  stayed at 0x17c0 after WPTR advanced to 0x1800, timing out at 100ms; delivery
  disabled itself. Timer advances, CNTL=0x900c6, SCRATCH0=0x43. This proves CPU
  access, not firmware responsiveness or physical HDMI output.
- **Capture:** CORE_PROBE_PASS, final critical record count 424. User reported Samsung **No signal**. Offscreen probe success is separate from physical presentation.
- **Shutdown/recovery:** exited-after-guest-request; recovered with
  authorizes_launch=true. Post-run SMU version query OK. No guest running.
- **Next:** query running firmware version through Linux's GPINT channel, independent
  of the inbox. No firmware load/start/reset. Same-boot cycle remains authorized.

Evidence: `~/macos-vm/run/candidate-302-results/`,
`~/macos-vm/run/c302-post-mode2-probe.json`.
[Source audit](findings/research/host-dmcub-tmr-overlap-20260923.md).
The first staging attempt stopped at an archive-path mismatch before QEMU; it
consumed MODE2 #222 but no launch ledger entry. Corrected artifact paths were
verified by the successful cycle. Candidate 301 was not launched.

Development uses dev directly in candidate worktrees, pulling remote before each
candidate. SSH push works; main is unchanged. Host suite: 1006 tests OK, three skipped.

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

- Output: `/home/bogdan/macos-vm/run/candidate-299-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-300-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-302-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-303-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`
