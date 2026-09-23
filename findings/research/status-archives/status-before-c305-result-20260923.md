# Live status — 2026-09-23

## Candidate 304: normal display wake accepted; DMCUB still unresponsive

Run `f721fecfe53efb0fa0bef789c4e5314f`, metal-152, source `eee7966`,
boot `dc8add85-5070-419f-959d-6cc094c914be`, MODE2 #225.

- **Functional:** separate VBIOS SMU GetPmfwVersion succeeded (0x625300), then
  SetDisplayIdleOptimizations(0) succeeded. GPINT version request still timed out
  afterward. Inbox delivery disabled; no image/audio established.
- **Capture:** CORE_PROBE_PASS; final critical count 426.
- **Shutdown/recovery:** exited-after-guest-request, recovered,
  authorizes_launch=true. Post-run SMU query succeeds; no guest running.
- **Blocker:** CPU inbox access works (302); command consumption and independent
  GPINT are unresponsive (302–304), including after normal display-idle exit.
  GPINT1 interrupt and wake sources are enabled; firmware reset is deasserted.
  Existing VBIOS lacks encoder/transmitter/pixel-clock legacy command tables.
  No source-supported non-reset firmware recovery has been identified. Host
  reboot/gpu-bind requested for reinitialization under the no-guest-firmware-reset
  and no-same-boot-amdgpu-rebind rules. This is not a missing recovery receipt:
  same-boot GPU cycles remain authorized.
- **Next:** preserve the 32MiB host tail and inspect firmware responsiveness earlier
  around the existing PSP TMR unload/setup sequence before more delivery. The
  host firmware code is inside the original host TMR; reservation alone may not
  preserve PSP ownership. This is a hypothesis to audit, not established causation.

Evidence: `~/macos-vm/run/candidate-304-results/`,
`~/macos-vm/run/c304-post-mode2-probe.json`.
[Source audit](findings/research/host-dmcub-tmr-overlap-20260923.md).
Development stays on dev in candidate worktrees, pulling remote before each
candidate. SSH push works. Main unchanged. Host suite: 1007 tests OK, three skipped.
Candidate 305 / metal-153 is built (source `2c9e33e`), passes all 1007 host
tests and dry-run preflight, and is not launched. Launcher:
`~/macos-vm/run/c305-launch.sh`. It adds
early raw-MMIO GPINT observations around PSP transitions and requires a live
firmware response before delivering commands. Current boot remains blocked on
firmware responsiveness, independently of the valid GPU recovery receipt.

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


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-304-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-305-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`
