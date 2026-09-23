# Live status — 2026-09-23

## Candidate 300: host DMCUB tail reserved, inbox reads zero

Run `120b9e2929247fb4057dfa81e241d71c`, metal-148, source `befcae4`,
boot `dc8add85-5070-419f-959d-6cc094c914be`, MODE2 #221.

- **Functional:** native reservation increased from 2MiB to 32MiB, with cursor
  fb+0x7e000000 and correct native accounting. Guest PSP TMR now starts at
  fb+0x7d600000, size 10MiB, ending exactly below the protected host tail.
  Inbox reads changed from raw all-ones to raw zero: the access denial is removed,
  but the old commands are zero. Earlier guest TMR overlap likely erased them.
  DMCUB timer runs, SCRATCH0=0x43; no firmware load/start/reset was added.
  Header guard refuses delivery; no HDMI picture claimed.
- **Capture:** CORE_PROBE_PASS; complete final CR2 count=419, drop=0, trunc=0.
  Offscreen Metal probe passes; this does not qualify physical presentation.
- **Shutdown/recovery:** exited-after-guest-request, recovered,
  authorizes_launch=true. Post-run SMU version probe OK. No guest running.
- **Next:** same-boot investigation of inbox accessibility and validation, retaining
  the native tail reservation and existing firmware prohibition. Candidate 300's
  recovery receipt authorizes another cycle with the harness MODE2/identity checks.
  Zero inbox reads do not prove erased contents or that reboot is required; the
  earlier reboot requirement was an unsupported inference and is withdrawn.
  The retained-header guard currently refuses delivery; establish a source-backed
  accessibility check before changing that guard.

Evidence: `~/macos-vm/run/candidate-300-results/`,
`~/macos-vm/run/c300-post-mode2-probe.json`.
[Source audit and interval evidence](findings/research/host-dmcub-tmr-overlap-20260923.md).
299: Samsung woke with no signal; guest TMR overlapped inbox, clean capture and
recovery. [Prior status](findings/research/status-archives/status-before-c300-result-20260923.md).

Development uses dev directly in candidate worktrees, with a remote pull before
each candidate. HTTPS credentials are unavailable after reboot; SSH authentication is verified
and is being used to deliver dev. Candidate 301 was not launched. Candidate 302 / metal-150 is built to validate
an empty inbox by reversible readback, then attempt guarded delivery on this
authorized host boot. Native reservation and all harness gates remain intact.
Main remains unchanged. Host suite: 1005 tests OK, three skipped.

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
