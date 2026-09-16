# Live status — 2026-09-16

**Current blocker:** green/purple pixels and smearing in Screen Sharing around
transparent content. Native colored visual-effect panels still reproduce diagonal
artifacts. Full desktop acceleration and physical display remain unqualified.

## Running guest and host

- Candidate 277, driver 1.0.277; candidate 278's linear-swizzle driver change is rejected.
- Run `a169e87a3b282ebb6552150a77a9c232`, attempt `smcpmio`, card `metal-124`, MODE2#152.
- Results: `/home/bogdan/macos-vm/run/candidate-277-attempt-smcpmio-results`.
- Supervisor `rgpu-candidate277-smcpmio.service` has finished; guest is stopped.
- Host boot `2508eb6d-ddf3-497d-9774-00a7ecebe3ed`; GPU `0000:7b:00.0` remains
  `vfio-pci`, `power/control=on`. Actual container image and QEMU hash verified.
- Current baseline Metal probe completed; **shutdown completed; recovery failed capture validation**.
  Previous smcfinal run exited after guest request and recovered with CP_STAT=0.

## Verified progress

**PerfPowerServices CPU fix:** QEMU AppleSMC enumeration now responds after four
index bytes and returns 0xb8 at end of keys. Fresh guest PID152 measured 0.0% CPU,
0.67s cumulative; remained 0.0% after graphics work. A normal launchd service restart
produced PID1069 at 0.1% CPU / 0.54 s cumulative, later 0.0% with the same CPU time. Native AppleSMC probe passed all six
keys and both out-of-range cases. No service disabling, guest binary patch or
security change. Longer observation and a second guest boot remain open.
Image: `sha256:51cbd7dcdbad2d6492ce83a263e9854c28620d67a1ea12ebc0562c6fab2605ad`.
QEMU SHA256: `d52b825bd310a392f3d189948f58b3772833a26060b202e2d43a4175f20203f8`.
Evidence: `perfpower-startup-sample.txt`, `smc-native-output.txt`,
`perfpower-after-draw.txt`, `perfpower-restart1.txt` in this run's results.
[Analysis and rejected first patch](findings/research/perfpower-smc-enumeration-20260916.md).

**HEVC decode fixed:** exact marked PCI IOService S30→GFX0 rename; H.264 decode/
encode and HEVC encode/decode have reproduced successes. Seven sustained cases,
9,600 frames across two fresh guests on one host boot. Main, 8-bit 4:2:0,720p/1080p;
Main10, arbitrary media/chroma, concurrency and crash recovery remain unqualified.
Fresh corrected-QEMU checks additionally pass 120 HEVC and 120 H.264 hardware
encode/decode frames at 720p (max luma error0 and1 respectively).
Explicit decoder registry-ID selection still fails; automatic required-hardware
selection works. [Evidence](findings/research/hevc-decode-qualification-20260916.json).

Host regression suite: 937 tests, OK (3 skipped). Cycle image pin now reaches both
preparation and admission; prior prelaunch refusals consumed no GPU exposures.

## Revalidated blockers

- **Still reproduced:** green/purple transparency; explicit HEVC decoder registry-ID
  selection returns -12906 in a fresh audit. Automatic hardware decoding passes.
- **Resolved in tested scope:** original HEVC capability lookup; PerfPowerServices
  CPU loop; earlier no-Metal/startup failures no longer block current 277.
- **Qualification still missing:** physical output, Main10/arbitrary-media chroma,
  concurrent resource/codec coverage, independent-host-boot and crash lifecycle.
- **Historical, not re-run here:** candidate 278 OpenGL hang and the instrumented
  WindowServer validation crash. Neither is marked fixed.
- Blanket “same-boot reuse is impossible” is superseded by successful cleanups and
  subsequent starts; broad host/crash stability remains unqualified.

[Full audit and acceptance gates](docs/ROADMAP.md#blocker-revalidation--2026-09-16),
[artifact hashes](findings/research/blocker-revalidation-20260916.json).

## Active work and constraints

Trace native composition around corrupt surfaces; isolated shader/readback passes
are not desktop qualification. Raw RFB still reproduces corruption after the CPU
fix. Do not rerun the hanging direct OpenGL probe. Temporary earlier compositor
flags were restored; Metal validation environment was removed.
[Roadmap and acceptance gates](docs/ROADMAP.md).

The standing user instruction authorized this fourteenth exposure on the named
host boot, unchanged 277/card metal-124, corrected QEMU image, maximum 6000 seconds,
5400-second hold. All identity/capture-fatal/host-fault/shutdown/recovery aborts remain.
Stop through the run's `stop-requested` file; a future exposure needs its own named
boot allowance and fresh clean MODE2. No merge/push to main before full desktop proof.

## Candidate279 prepared

Native transparency has a controlled fix: expanding compressed render targets before
shader feedback clears the reproducer; restoring original bytes brings corruption
back. See findings/research/feedback-decompression-20260916.md. Candidate279 retains
277 topology/codecs and adds the guarded three-byte userspace repair; fresh guest
validation pending. Current277 guest remains supervised until normal stop.

## smcpmio closeout

Guest exited after the identity-bound guest shutdown request. CR2 final snapshot
contains512records and reports19drops; recovery refuses it with
`CriticalReplayError: CR2 snapshot reports loss`. Overall verdict INVALID; no
successful recovery receipt is claimed. Functional CPU/codec and controlled
visual-intervention evidence remain valid in their stated scopes. Host-after
reports no active VM, vfio-pci, initialized GPU and power pinned on.

## One-run allowance: candidate279

Standing user instruction to fix and continuously test the corruption authorizes
the fifteenth exposure on host boot2508eb6d-ddf3-497d-9774-00a7ecebe3ed, candidate279/
metal-126, corrected QEMU image51cbd7dc. Previous cleanup evidence is INVALID due
to CR2 overflow; do not relabel it or weaken the strict parser. Use the documented
manual-reuse/ack-risk cycle path and independent fresh MODE2 reset, requiring
CP_STAT=0 and RLC_CNTL=0 before launch. This is not automatic receipt-based reuse.
All identity, host-fault, capture-fatal, shutdown and recovery guards remain intact;
max6000seconds, manual stop after bounded visual/Metal/codec qualification.
Host suite937tests OK3skipped; build e9d918e94bc5d8e1f20d636ff65cf078d46ac0848650565f878bdec2f8fe5aee.
