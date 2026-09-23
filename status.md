# Live status — 2026-09-23

## Candidate 307: early kernel panic; fingerprint untested

Run `f5dbd9efeff69ca6b5a76084bea2492b`, metal-155, source `6488386`,
boot `5074c0e5-b2f6-46da-99b2-299ba322b41e`, MODE2 #228.

- **Functional:** guest panicked at about 10.4 seconds in launchd/kernel event
  handling, before host reservation or the DMCUB code fingerprint. Cause is
  unresolved. No new instruction-memory or physical HDMI result.
- **Capture:** serial includes the early panic and recursive traps; wrapper INVALID,
  identity_or_route_missing. This run did not reach the Metal probe.
- **Shutdown/recovery:** forced through identity-bound vm-supervision shutdown
  (request_sent=true); runner later recorded already-stopped. Not a clean shutdown.
  Recovery failed: missing XH2 ownership record. No authorizing reuse receipt.
- **Manual cleanup follow-up:** standalone vfio-recover refused the current run
  with `guest host-KIQ reservation launch nonce does not match`. Capture-repair
  proof also refused this run type. SMU version probe and MODE2 reset both
  succeeded on the same boot; CP_STAT=0, RLC_CNTL=0, PCI config unchanged.
- **Next:** resolve the missing-lease recovery admission for this early panic.
  Hardware reboot necessity is NOT established; the earlier reboot request was
  premature. A successful MODE2 reset is real evidence, but the current harness
  still requires an additional valid recovery receipt before relaunch.

305 established GPINT timeout before guest TMR changes on a fresh boot.
Another identical reboot/bind is not an established HDMI fix.
Manual evidence: `~/macos-vm/run/c307-manual-cleanup.json`,
`~/macos-vm/run/c307-cleanup-smu-probe.json`,
`~/macos-vm/run/c307-cleanup-mode2-reset.json`.
Evidence: `~/macos-vm/run/candidate-307-results/` and cycle log.
[Source audit](findings/research/host-dmcub-tmr-overlap-20260923.md).
Work stays on dev in candidate worktrees; pull remote before each candidate.
Host suite for 307: 1007 tests OK, three skipped. Main unchanged.

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
