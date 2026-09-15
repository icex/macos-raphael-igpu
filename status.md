# Live status — 2026-09-15

## Current verdict

**Native Linux H264/HEVC hardware encoding and decoding pass. macOS encoding
remains unresolved.** A sustained Linux H264 run produced 600 correct frames.
The working Linux encoder also returns `0xffffffff` for the cache BAR, soft-reset
and LMA registers. These reads do not establish a dead VCPU or failed SRAM replay.
The previous claim of an unavoidable below-driver wall is unsupported.

## Latest completed investigation — native Linux

| Field | Value |
|---|---|
| Boot ID | `c782d007-ca85-409b-9cf5-ff12c1a8c6d5` |
| GPU / driver | `0000:7b:00.0`, Raphael `1002:13c0`, `amdgpu` |
| Render node | `/dev/dri/renderD129` (other GPU is renderD128) |
| Kernel / Mesa | `7.2.5-1-cachyos-bore` / `26.2.2-arch3.2` |
| Power control | `on` |
| Worktree / branch | `/home/bogdan/macos-vm/run/worktrees/linux-vcn-baseline` / `linux-vcn-baseline` |
| Final tested harness commit | `66b0727` |
| Final artifacts | `/home/bogdan/macos-vm/run/linux-vcn-c782d007-active` |

Three authorized bounded native sessions completed through `tools/cycle.py linux-vcn`:
`linux-vcn-c782d007`, `linux-vcn-c782d007-sram`, and `linux-vcn-c782d007-active`
under `/home/bogdan/macos-vm/run/`. The worktree status archive preserves allowances
naming this boot. No QEMU/VFIO exposure or GPU ledger entry; no reset, rebind or
reboot was performed. The boot journal contains a suspend/resume before testing.

### Independent outcomes

- **Function:** Software controls and repeated H264/HEVC hardware encode/decode
  passed in all three sessions. Each short output validated three 1280×720 frames,
  with maximum interior luma error 1 (H264) or 0 (HEVC). Sustained H264 produced
  600 frames / 20 seconds; independent software decode checked 535,095,000 luma
  values with maximum error 1. These results qualify the tested Linux workloads.
- **Identity/capture:** Explicit Raphael render node; firmware bytes match the
  macOS payload. Register trace, pre-PSP SRAM/shared snapshots and kernel logs
  retained. All trace loss/overrun counters zero. Initial boot-time PSP loading
  was not traced; workload-triggered DPG startup was captured.
- **Cleanup:** Workloads and capture containers stopped, private trace instance
  and kprobe removed, amdgpu retained, boot unchanged, power pinned. Only the
  existing `rgpu-inhibit` container remains. No GPU fault/reset/timeout in workload logs.
- **Qualification:** Linux codec baseline passes; this is not a macOS encoder,
  passthrough, physical scanout or complete desktop qualification.

Latest full host suite: **937 tests, OK, three skipped**. Log:
`/home/bogdan/macos-vm/run/linux-vcn-c782d007-active-tests.log`.

## What the comparison establishes

1. During working Linux encoding, POWER_STATUS=`906`, DPG_PAUSE=`c`, while
   cache BAR, SOFT_RESET and LMA reads return `ffffffff`. Retire the dead-core
   interpretation of these selected reads; their access behavior is not yet explained.
2. Linux sends real SMU `PowerUpVcn=6`, argument 0, response 1 through the same
   register addresses used by our macOS hook. The hook is not merely a dummy
   backend acknowledgment. Replies alone still do not measure physical power transitions.
3. VCN firmware version `04121015`, SMU version `00625300`, and the exact VCN
   payload SHA256 match macOS. Identical input does not prove identical PSP processing.
4. Linux submits **280 bytes / 35 SRAM pairs**. Modified macOS submits 288 bytes.
   The earlier interpretation of an MMIO command word as SRAM size was wrong.
   Clock/reset prerequisites match closely; source matching does not prove sufficiency.
5. Linux initializes the hardware decode ring **before** requesting the encoder
   DPG pause. ACK arrives in 74–81 microseconds in the final trace. Apple's
   requested-queue hardware initialization follows the pause call. A native-owned
   decoder-first startup has not been exercised by our macOS probes.
6. Linux exposes a 4096-byte shared window, flags `b40`; macOS exposes 96 bytes,
   flags `f47`. Both use SMU interface byte 2. Linux uses VRAM in this run but
   permits VRAM or GTT allocation. These differences are hypotheses, not proven defects.

Detailed evidence, exact sequence, limitations and next test:
[Linux/macOS comparison](/home/bogdan/macos-vm/run/worktrees/linux-vcn-baseline/findings/research/linux-vcn-baseline-20260915.md).

## Next discriminating experiment

The Linux capture request is complete and the iGPU remains attached to Linux.
For the next macOS experiment, verify whether the native decoder queue is already
allocated and inactive at the first encoder startup. Test its native ring setup
after engine initialization and before the first pause, preserving queue ownership
and active-count semantics. Capture RBC writes, shared reset bits, pause ACK and
encoded output. If that setup already occurs or does not change the timeout, it
is not a sufficient correction. Test shared-window size/flags separately.
No new macOS candidate was launched or claimed fixed during this Linux investigation.

## Last macOS result retained

Candidate `1.0.262` / card `metal-108`, run `08bd239e28b2248d7cbc547957b45574`,
build `3f2e6162e3c84d0cacc494c315f56e71`, built source `5ca2c53`:
encoder accepts frames 0/1 and stalls on frame 2. Desktop probe passed 1000
offscreen frames and 24 readback cases with zero mismatches. Overall run was
**INVALID/capture_loss**; shutdown `forced-after-shutdown-error`, recovery `recovered`.
Its boot `c369c74e-96ff-4c21-ae85-80ccb269f7d2` is historical, not live host state.

Candidate 262 worktree at `e6a9bca` includes a subsequent atomic capture-request
publication fix and better error details. That fix passes host tests but awaits
macOS hardware validation. Earlier driver robustness, DPG, software firmware,
static-mode and real SMU corrections remain in candidate branches. The six
robustness fixes were not a demonstrated encoder fix. Nothing merged or pushed.

Historical details:
[pre-Linux status](findings/research/status-archives/status-before-linux-baseline-20260915.md),
[independent review](/home/bogdan/macos-vm/run/worktrees/candidate-262/findings/research/encoder-independent-review-20260915.md).

Physical scanout and complete desktop presentation remain unqualified. Use candidate
worktrees and `tools/cycle.py`; preserve all identity, host-fault, capture, shutdown,
cleanup and 6000-second limits. Read [host safety](docs/host-safety.md) before hardware
work. No same-boot vfio→amdgpu cycling, no sudo on the normal path, no merge/push to
main before full desktop acceleration. A status update grants no additional launch.

## Candidate 263 allowance — current authorized macOS handoff

User explicitly requested switching to macOS and testing the Linux findings.
Allow one candidate263 launch on boot c782d007-ca85-409b-9cf5-ff12c1a8c6d5,
max6000seconds with manual stop after encoder output or first stall. Native Linux
initialization and codecs succeeded in this boot. Handoff amdgpu→vfio-pci once;
retain pinned power, disable PCI reset methods, fresh MODE2 and every cycle gate.
No subsequent amdgpu rebind this boot. Only record launch once QEMU/VFIO opens.
Candidate263 adds opt-in native-owned inactive decoder ring setup before first
encoder pause to the software-firmware+committed-DPG path tested in259/260.
If no valid decoder exists, log selection refusal and retain native behavior;
that outcome does not test the ordering hypothesis. Preserve queue ownership,
active counts, capture, recovery and desktop regressions.
