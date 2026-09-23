# Live status — 2026-09-23

## HDMI: candidate 298 isolates an inaccessible inbox address

Run `b062b9e3a17f7c79591df33095b47efd`, metal-146, source `7c152f4`,
boot `90122d1c-38ea-40af-9c35-ed2b6899c281`, MODE2 #219.

- **Functional:** four nonzero BAR controls match both raw MM_DATA and CGS reads
  (offsets 0x101c, 0x1020, 0x1418, 0x141c). Four inbox headers at
  `fb+0x7fae5ac0..0x7fae5b80` return raw `0xffffffff`, while CGS returns zero.
  Generic indirect access works; Apple's validated accessor hides failed reads.
  Inbox delivery remains disabled. Offscreen Metal probe passed with zero
  reported mismatches; window presentation was not verified.
- **Physical output:** user confirmed Samsung **no signal** for candidate 297.
  298 is a read-only access diagnostic, not a delivery fix; no picture claimed.
- **Capture/qualification:** INVALID. Final CR2 snapshot has count=512, drop=5,
  trunc=0. This is producer capacity loss, not permission to relax the gate.
- **Shutdown/recovery:** guest-request shutdown completed (`exited-after-guest-request`).
  Recovery failed with `CriticalReplayError: CR2 snapshot reports loss`.
  No authorizing receipt: **same-boot launch is blocked; reboot + user gpu-bind required**.
  The post-run SMU version probe still answered OK and CP_STAT=0; neither substitutes
  for a recovery receipt.
- **Evidence:** `~/macos-vm/run/candidate-298-results/` and
  `~/macos-vm/run/c298-post-mode2-probe.json`.
- **Next:** reduce nonessential diagnostic CR2 volume while preserving recovery
  records and loss gates; audit the inaccessible address range and address domains.
  Never load/start/reset DMCUB firmware from the guest.

[Access-path evidence](findings/research/c298-indirect-access-20260923.md).
Previous 297 result: ring refused, offscreen probe passed, incomplete capture,
forced stop, authorizing recovery and responsive SMU. [Archive](findings/research/status-archives/status-after-c297-before-c298-20260923.md).
296-d belonged to the previous boot and has no completed recovery receipt.

No guest running after 298. GPU remains vfio-pci, power/control=on. GitHub icex
authentication works. Candidates 291–297 integrated on remote dev at 153a23d;
298 and the archived 291–293 branch-tip verdicts are delivered at 761774b. 1004 host tests OK (three skips).
HDMI audio remains gated on verified physical video; prior USB/Moonlight audio
and remote-rendering evidence retain their separate scope.

## Next candidate prepared

Candidate 299 / metal-147 is built and dry-run clean (1004 tests OK, three skips),
not launched. It reduces optional CR2 logging while preserving critical failures,
and probes indirect reads around the PCI aperture boundary. Launch script:
`~/macos-vm/run/c299-launch.sh`. It remains gated on a fresh boot and user gpu-bind;
no same-boot recovery exception was introduced. Linux/Apple source audit is in the
[access-path note](findings/research/c298-indirect-access-20260923.md).

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
