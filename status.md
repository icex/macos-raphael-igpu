# Live status — 2026-09-24

## Candidate319 baseline diagnostic: early boot panic, recovered

Run009f47866783045e30571237b1c44a3a, MODE2#246, source5131613,
metal167. Kernelmanagerd panicked in OSKext::copyInfo at12.47s, before display
unblank/allocation diagnostics. No functional display result. Final INVALID,
missing native lease; supervised forced closure (not clean guest shutdown).
Separate c319-panic-noqueue-recovery.json reports recovered/authorizes_launch=true.
Unchanged-build retry follows; all1020 host tests pass (3 skipped). Dev milestone
c5570b0 was pushed via SSH and remote ref verified; HTTPS token is invalid.

## Candidate318: user sees HDMI test pattern; clean capture and recovery

Run338d9498eb9e7e029f0f73570450b41f, MODE2#245,
boot5074c0e5-b2f6-46da-99b2-299ba322b41e, source19f6e6e, metal166.
Results `~/macos-vm/run/candidate-318-attempt-pattern-results/`.

- **Functional:** user confirmed visible patterns on the Samsung via iGPU HDMI,
  then described fuzziness and interleaving after mode changes. Explicit OPP0
  RGB generator readback661001, dimensions1920x1080. Native1080p60, HDMI enabled,
  scrambling off, AVMUTE0. Firmware reload/3 queries passed;14 commands consumed.
  This demonstrates visible downstream output, not correct pixel layout, desktop
  scanout, or HDMI audio. HUBP surface-in-use remains0. DCHVM active/prefetch-done.
- **Awake/capture:** verified UserIsActive=1 and PreventUserIdleDisplaySleep=1
  using launchd-owned bounded caffeinate. Core probe passed; finalCORE_PROBE_PASS,
  critical replay complete without loss. Native1080p120 was programmed in316/317
  but black;317 awake1080p60 was also black. SR1032 alone was not sufficient.
- **Shutdown/recovery:** stop-requested through harness, exited-after-guest-request,
  recovered/authorizes_launch=true. No running GPU VM after this run.
- **Evidence:** [research record](findings/research/visible-hdmi-pattern-20260924.md),
  run/c318-pattern-scanout.json, c318-awake-check.txt, c318-awake-60hz.txt.
- **Next:** restore framebuffer fetch and inspect formatting; distinguish expected
  squares from reported interleaving. Always verify awake assertions before screen
  tests. HDMI audio follows a usable image; audio function remains host-owned.

1020 host tests OK (3 skipped); build/card validation passed. First318 attempt
panicked in corecrypto FIPS POST before Raphael loaded, required supervised forced
closure and separate authorizing noqueue recovery. Retry used the unchanged build.
User authorizes autonomous tests/resets. Fresh candidate worktrees; fetch remote dev
before each. No reboot, host sudo or vfio-to-amdgpu rebind used. Candidate316–318 changes are integrated into dev; 1020 integration tests pass
(3 skipped). This commit is the visible-pattern milestone for publication. Main
remains untouched.

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
