# Live status — 2026-09-24

## Candidate 310: DCFCLK restoration accepted, DMCUB still unresponsive

Run `9ce06c40d7c3535e535d2b136e3fd95c`, metal-158, source `c5f65c5`,
boot `5074c0e5-b2f6-46da-99b2-299ba322b41e`, MODE2 #233.

- **Functional:** SMU accepted SetHardMinDcfclkByFreq(1000 MHz), returning
  1000 MHz after successful display-idle exit. Fresh GPINT query still timed out.
  This clock restoration alone does not restore DMCUB. Metal probe passed;
  physical HDMI remains unresolved.
- **Capture:** CORE_PROBE_PASS; no reported boundary.
- **Shutdown/recovery:** exited-after-guest-request; recovered,
  authorizes_launch=true. Same-boot reuse remains available.
- **Next:** investigate retained firmware execution and host teardown ownership.
  No DMCUB firmware restart/load is authorized by this result.

Evidence: `~/macos-vm/run/candidate-310-results/`.
[Retained timeout audit](findings/research/dmcub-register-timeout-20260923.md).
Host regression: 1017 tests OK, three skipped.
User instruction: no further commits/pushes to dev until meaningful progress.
310 source/card identities are committed only on the local candidate-310 branch;
dev and origin/dev remain 5371959. No candidate branch has been pushed.

## Reinitialization review prepared (no hardware run)

The user approved proceeding with the reviewed one-shot firmware-reinitialization
experiment. Candidate311 is being implemented locally; not yet launched.
[Review proposal](findings/research/dmcub-reinit-review-20260924.md) and
[pinned offline manifest](findings/research/dmcub-reinit-review-20260924.json)
specify one direct-load startup/GPINT test with HDMI command delivery disabled.
The planner verified firmware metadata, source/capture hashes, layout bounds and
non-overlap with retained windows; a modified VBIOS was rejected. The reviewed scope is now authorized. Candidate311 adds a default-off loader
and fake-transport failure tests; hardware execution awaits build and preflight.
All preparation remains uncommitted locally; dev/origin/dev remain5371959.

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
