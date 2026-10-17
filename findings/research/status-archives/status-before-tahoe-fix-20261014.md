# Live status — 2026-10-14 — paused by user; Tahoe desktop regression unresolved

User requested a pause. No VM, GPU experiment, or launch supervisor is running.
No further hardware work is authorized by this status entry; a later explicit
resume is required. Host boot2e377991-b6d2-4fe5-81dd-fd6afe9999f7, GPU0000:7b:00.0
remains vfio-pci with power/control=on. Latest separate recovery receipt
run/candidate-494-vmabi4-requalification.json validates with errors=[],
authorizes_launch=true and kernel_faults=[]. Ordinary recovery for that run is
still immutable incomplete/non-authorizing. Do not confuse these two receipts.

## Current failure

User reports latest15.x was usable and26.x freezes. Latest retained versions:
15.8.1/24H32 and26.7.1/25G241. Earlier matched candidate490 offscreen render/
compute and readback passes do not establish an unlocked Tahoe desktop.
The active disk is26.7.1; latest15.8.1 remains in rollback. Do not test older releases.

Latest hardware run: candidate494 vmabi4, run0b504695909175c6fd2974d807c3c1bb,
results run/candidate-494-attempt-vmabi4-results. The native desktop Metal probe
passes (CORE_PROBE_PASS), but normal desktop interaction/remote access is unqualified.
First pending client is VTEncoderXPCServ PID808, Video channel15 VCN0EncLLQ stamp1;
graphics ring advances/drains. An earlier cosWaitForFunc timeout resolves to
25G241 HWLibs _wait_for_vcn_response (+0x8036e). Its request contains engine,
segment, register, expected value and mask; the actual failed fields remain missing.
Video-context teardown later holds the global accelerator mutex, blocking desktop
resource creation. This is a failure boundary, not a proven firmware root cause.

A distinct earlier candidate493 earlygate run859837b1298120ac07a14850eb389c37
had Weather PID496/VMID4 graphics stall BEFORE encoder creation, with no HEVC
hardware decode contexts. Thus video teardown and HEVC selection do not explain
all failures. Do not discard the earliest graphics-stall evidence.

Candidate494 captured first requests for VMIDs1..8: raw reprogram byte1 and roots
repaired to physical addresses. Native26 tests bit0 whereas our helper tests ==1;
that mismatch is not supported as this run's cause. Guarded MMHUB table repair
succeeds on15/26. Encode3_0_submit_frame retains queue fields/arithmetic; observed
binary differences are relocated references/call displacements.

## Preserved work and configuration

Candidate494 worktree/branch contains diagnostics and a recovery admission fix;
compiled source22a52be949e0dee37cd352d4f5addeef56be0e2c,
build6d37de612f5f49b1bad5f52db4639b59. No verified GPU repair is integrated into dev.
Candidates491-493 SDMA retry/HEVC gates are unverified and are not the default fix.
CoreMedia preference restored to original absence; Sunshine encoder=videotoolbox.
Apple sign-in OpenCore patches, authorized SSH key, guest data and identity retained.
The GPU run used experiments/pins-igpu-display-v15.json (frozen QEMU38193017...).
Use explicit matching pins; default pins.json selects a different image.

Two uncaptured candidate494 attempts provide no native regression evidence.
One cancellation consumed a launch reservation despite lacking usable capture;
its original ledger/artifacts remain. Full MODE2/noqueue recovery now accepts a
strictly bound uncaptured cancellation record, then still requires the same
complete idle scans, PSP teardown and live host/kernel checks. Audit that change
before reuse; do not remove ledger entries or fabricate recovery/shutdown evidence.
Latest full host suite:1626 tests pass,8 skipped. No GPU milestone/CI delivery claimed.

## Next investigation on an explicit resume

Capture the failed _wait_for_vcn_response request fields and native caller before
changing handshake behavior, then compare against latest15.x successful encoder
startup. Audit the retained Weather graphics stall separately. Correct the driver,
with dynamic instruction/ABI discovery rather than build allowlists or version
thresholds. Verify native Metal pixels, sustained usable desktop, hardware encoding,
remote display, and supervised shutdown/recovery. Xcode installation, QEMU close
confirmation and remaining remote-access work stay deferred until GPU stability.

Detailed evidence and Claude prompt: docs/claude-tahoe-regression-handoff.md.
Earlier status is preserved in findings/research/status-archives/.
