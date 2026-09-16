# Live status — 2026-09-15

## Current verdict

**Hardware video encoding remains unresolved.** Candidate 262 accepts H264 frames 0 and 1,
then stalls on frame 2 without encoded output. The evidence does not establish that every
driver path is correct or that the remaining failure is definitively below the driver.

The latest desktop probe completed 1000 offscreen frames with zero pixel mismatches and all
24 readback cases with zero mismatches. This is functional Metal evidence, not physical
scanout, complete desktop presentation, game/performance, or encoder qualification.
The latest overall run is **INVALID because critical serial capture failed during shutdown**.

## Latest experiment and source

| Field | Value |
|---|---|
| Candidate / card | `1.0.262` / `metal-108` |
| Run ID | `08bd239e28b2248d7cbc547957b45574` |
| Build ID | `3f2e6162e3c84d0cacc494c315f56e71` |
| Built source commit | `5ca2c53` |
| Current candidate worktree commit | `e6a9bca` — includes subsequent capture fix |
| Worktree | `/home/bogdan/macos-vm/run/worktrees/candidate-262` |
| Branch | `candidate-262-vcn-power-cycle` |
| Results | `/home/bogdan/macos-vm/run/candidate-262-results` |
| Last MODE2 reset | `/home/bogdan/macos-vm/run/mode2-reset-118.json` |

The experimental code and fixes remain in candidate worktrees. Updating this file does not
merge that code into this checkout. Nothing was merged or pushed to `main`.

## What the independent investigation established

- The existing platform hook sends real Raphael SMU commands through native CGS/BGM transport;
  it is not merely the dummy backend acknowledging a power request.
- The DPG failure was localized to the pause acknowledgment wait: register `1:0x14`, expected
  `8`, mask `8`, native caller `+0x94db1`. Preceding PGFSM and power-status waits succeed.
  The DPG PGFSM wait expects an off state; its success does not prove the core powered on.
- Candidate 259 tested software firmware placement plus native-owned, committed SRAM.
  It still failed the pause acknowledgment. This experiment still uses PSP for SRAM submission.
- Candidate 260 readback returned `0xffffffff` for every selected SRAM entry. The read port
  may be inaccessible; these results do not establish SRAM contents or successful replay.
- Earlier static initialization retained the hardware DPG-mode bit. Candidate 261 cleared it,
  and its native static power-on wait succeeded, but the encoder still stalled. Selective
  inaccessible register reads do not establish that the entire VCN core is powered off.
- Candidate 262 sent `PowerDownVcn=5` then `PowerUpVcn=6` before first initialization, with
  zero active queues. Both returned success; static mode and the power-on wait succeeded.
  The encoder still stalled. Replies alone do not prove a physical power-domain transition.
- Hardware H264/HEVC decoder sessions were rejected by VideoToolbox before VCN initialization
  (pinned GPU: `-12906`; automatic hardware selection: `-12913`). The software decoder control
  passed. Decoder-first hardware startup remains unexercised.

Detailed review:
[encoder-independent-review-20260915.md](/home/bogdan/macos-vm/run/worktrees/candidate-262/findings/research/encoder-independent-review-20260915.md).

## Fixes and validation

The candidate branches retain the earlier driver robustness corrections and include:

- Guarded software-firmware SRAM allocation and initialization routing.
- Static initialization that explicitly leaves inherited hardware DPG mode.
- Supervision termination that escapes startup retry handlers and reaches cleanup.
- Atomic publication of critical capture shutdown requests, retaining exclusive creation and
  strict validation; capture errors now preserve exception class and errno.

The capture publication race is demonstrated in source and covered by a regression test.
It is consistent with candidate 262's failure, but causality is unconfirmed because the old
collector reported only `serial capture failed`. This correction awaits hardware validation.

Latest full host suite: **936 tests run, OK, three skipped**. Log:
`/home/bogdan/macos-vm/run/candidate-262-host-tests-capture-fix.log`.
The candidate 262 binary predates the capture correction; the correction changes host tooling.

## Cleanup and verified host state

Candidate 262 shutdown: `forced-after-shutdown-error` because the critical capture service was
not running. Overall qualification: `INVALID/capture_loss`. Recovery receipt: `recovered`.
These outcomes are independent of the passing desktop probe and failing encoder workload.

Read-only host verification during this status update:

| Field | Value |
|---|---|
| Boot ID | `c369c74e-96ff-4c21-ae85-80ccb269f7d2` |
| GPU | `0000:7b:00.0`, bound to `vfio-pci` |
| `power/control` | `on` |
| VM container | stopped; only `rgpu-inhibit` is running |

No host rebinding or reboot occurred. The experiment allowance was consumed. This status update
performs no hardware test and grants no additional launch allowance.

## Next run — Linux baseline after reboot

The user requested the next hardware investigation under Linux, **after a host reboot with
this iGPU attached to Linux's `amdgpu` driver**. Do not rebind it from `vfio-pci` to `amdgpu`
within the current boot. This is the next test plan, not a claim that reboot or testing occurred.

### Prepare and identify

- Prepare capture tools and storage before reboot so initial driver/firmware bring-up can be
  recorded, including any tracing that must be enabled at boot. Use a candidate worktree.
- After reboot, record the new boot ID, physical PCI identity (Raphael `1002:13c0`; rediscover
  its BDF), driver binding, kernel, BIOS/VBIOS, firmware files and hashes, and codec/tool versions.
  Verify that the selected DRM render node belongs to this iGPU rather than another GPU.
- Record the concrete run allowance against that new boot ID before exposure. The current
  boot's consumed allowance does not carry over. Use the experiment harness; if its current
  macOS-only assumptions prevent a native Linux run, prepare and test the necessary support
  while retaining identity, bounded duration, capture-fatal and cleanup checks.

### Establish actual codec function

- Run a software control and explicit hardware H264 encode on the Raphael render node. Match
  the macOS probe's input pattern, resolution (`1280 × 720`), frame count, format and codec
  settings where supported; record unavoidable differences.
- Preserve commands, stdout/stderr, exit status, timing and encoded files. Check completed frame
  counts, decode the output, and validate image content. Device enumeration, firmware loading
  and accepted submissions alone do not establish successful hardware encoding.
- Test HEVC encoding and hardware H264/HEVC decoding separately, recording unsupported modes
  distinctly from hangs or corrupt output. Confirm hardware selection rather than software
  fallback. Repeat successful short workloads to check reproducibility and idle/resume behavior.

### Capture the Linux pipeline

- Preserve boot and workload kernel logs, IP discovery, firmware versions/hashes and load
  results, PSP placement/submission information available through supported instrumentation,
  SMU requests/replies, power/clock transitions, and relevant VCN ring/interrupt/fence events.
- Capture the sequence around VCN power-up, DPG/static selection, SRAM construction/submission,
  firmware/cache/stack/shared-memory programming, VCPU reset release, decode-ring setup,
  encoder-ring setup and pause acknowledgment. Include before/after state and timestamps.
- Use available driver tracing/debug interfaces; add narrowly scoped instrumentation only for
  missing observations. Document unavailable or inaccessible registers and observer effects.
  Retain raw traces and the exact instrumentation source, not just a narrative summary.
- Record workload completion or the first failure, then stop workloads and verify host/device
  health. Keep the iGPU attached to Linux for this baseline run; do not switch into macOS in
  the same experiment. Preserve separate functional, identity/capture and cleanup outcomes.

### Compare with macOS and choose the fix

Build a stage-by-stage comparison against the exact macOS artifacts, especially candidates
259 (software firmware plus committed SRAM), 260 (DPG readback), 261 (static mode corrected)
and 262 (SMU power-cycle request pair). Compare:

1. Firmware identity and loading mode, address domains, buffer sizes/alignment and shared ABI.
2. SMU/PSP transactions and actual power/clock observations.
3. Register/SRAM values **and ordering**, including reset release and decode-before-encode setup.
4. Pause handshake, queue submission, interrupts/fences and completed encoded output.
5. Reset history, native Linux versus passthrough environment, and cleanup behavior.

Identify the earliest supported divergence, then implement and test a targeted macOS correction.
Do not assume Linux succeeds: if Linux also fails, preserve that failure and investigate its
baseline before attributing the macOS stall to Apple's driver or firmware authentication.

## Other remaining limits

- The capture publication correction passes host tests but awaits hardware validation before
  relying on another qualified macOS run.
- Physical scanout and complete desktop presentation remain unqualified. Historical guest
  display-preference and Screen Sharing restoration notes are archived; their current state
  was not rechecked during the encoder investigation.

Run experiments through `tools/cycle.py` from candidate worktrees. Before hardware work, verify
live state and read [host safety](docs/host-safety.md) and
[experiment instructions](docs/running-an-experiment.md). No same-boot `vfio-pci` to `amdgpu`
cycling, no sudo on the normal path, and no merge/push to `main` before full desktop acceleration.
Record exposure only once QEMU/VFIO opens; any allowance extension must name the current boot.
Preserve the 6000-second maximum and all host-fault, identity, capture, shutdown and cleanup aborts.

Superseded status, preserved verbatim:
[status-before-candidate-262-sync-20260915.md](findings/research/status-archives/status-before-candidate-262-sync-20260915.md).
