# Live status — 2026-09-16, handoff to Claude

## Current host and task boundary

User requested handoff to Claude. No further hardware run is in progress.
Live readback: boot `2508eb6d-ddf3-497d-9774-00a7ecebe3ed`, Raphael
`0000:7b:00.0` bound to **vfio-pci**, `power/control=on`, no QEMU process.
Candidate274 used this boot's single documented VM exposure allowance.
No vfio-pci → amdgpu rebinding within this boot. Keep PCI reset methods disabled.
Use `tools/cycle.py`, fresh identity/reset checks and the existing safety gates.
Full acceleration remains unqualified. Nothing merged or pushed to main.

## Progress and remaining blockers

| Area | Observed result | Remaining limit |
|---|---|---|
| Offscreen Metal | 274: 1,000 frames, zero sampled mismatches, all 24 readback cases pass | Does not qualify the full desktop/display path |
| macOS hardware decode | 272: decoder creation succeeds and hardware selection is true | First DecodeFrame blocks for 90 seconds; no callbacks; VCN0Dec stamp 1 hangs |
| macOS hardware encode | Earlier 263–269 accept frames 0/1 then block on frame 2 | No encoded callbacks; unresolved |
| Native Linux VCN | Current boot H.264/HEVC hardware encode/decode controls pass | Linux success does not establish the macOS protocol is correct |
| Latest cleanup | 274 exits after guest shutdown request; recovery receipt is recovered | Does not qualify recovery from a codec hang or host crash |
| Host application safety | Brave was lost during Linux → VFIO handoff | New client guard is fixture-tested, not yet validated on a native handoff |

## Candidate274 — latest completed macOS run

Worktree: `/home/bogdan/macos-vm/run/worktrees/candidate-274`.
Run `4f0993b19e9df2c334371e58eade7c32`, build
`9e81a985c4e743e5831f316a60df66b2`, source
`c81955f548641df9f5a767972f3652ddb7dab935`, harness HEAD
`182dbe8ac909c84eb1d63cd8a0dfc59d52085503`, card `metal-121`, MODE2 reset 133.
Artifacts: `/home/bogdan/macos-vm/run/candidate-274-results/`.

- Function: offscreen Metal probe passes, including managed texture/readback checks.
- Identity/capture: verdict valid, CORE_PROBE_PASS, exact build and route evidence;
  terminal capture acknowledged. See `verdict.json`, `probe.json`, running identity.
- Cleanup: `shutdown.json` says `exited-after-guest-request`; `recovery.json` says
  `recovered`, with no recovery kernel messages.
- Scope: coordinator requested normal stop to address the Brave incident.
  No codec workload was issued by the coordinator in this run. Diagnostic removal
  is NOT a demonstrated codec fix or proof that the host-crash cause is fixed.

274 is based on 272 and removes intrusive VCN diagnostics: SRAM LMA-selector
writes/readbacks, extra protected register reads and guessed-segment scans.
It retains real Raphael SMU/DPG initialization and the native queue paths.
It deliberately excludes 273's raw write-pointer patch.

## Brave incident and pending handoff guard

Before unbinding amdgpu, the captured kernel client list included **Brave, Code,
KWin and systemd-logind**. The coordinator incorrectly treated no engine counters
and disabled iGPU outputs as evidence that detaching the device was safe. The user
reported Brave was killed. No explicit kill command was sent to Brave; exact
process termination mechanism is not captured. Device detachment while clients
held it open was an avoidable mistake. Do not repeat that handoff.

Evidence: `/home/bogdan/macos-vm/run/linux-vcn-2508eb6d-control/handoff-client-check.txt`
and `/home/bogdan/macos-vm/run/handoff-2508eb6d/`.
Container client TGIDs were zero because of PID namespace visibility; those rows
still represented real open clients. Idle clients must block handoff too.

Uncommitted fix is isolated on branch `fix/gpu-handoff-clients`, worktree
`/home/bogdan/macos-vm/run/worktrees/gpu-handoff-clients`:

- `tools/gpu-client-check.sh`: reads kernel debugfs DRM client inventory, rejects
  any client row, missing/unknown inventory or ambiguous device identity; deduplicates
  debugfs symlink aliases. Does not depend on visible process IDs or engine activity.
- `tools/gpu-bind.sh`: requires the companion helper and checks before preparation
  and again immediately before driver_override/unbind. No client termination.
- `tests/test_gpu_clients.py`: fixtures cover idle and namespace-hidden clients,
  other GPU clients, missing/unknown inventory, aliases and gate placement.
- Host suite: **945 tests passed, 3 skipped**, log
  `/home/bogdan/macos-vm/run/gpu-handoff-clients-tests.log`.

Pending review: guard is not installed into copied handoff scripts and has not been
hardware-tested; copy both helper files together. Update host-safety documentation.
A snapshot check has a check-to-unbind race: it does not prevent a new DRM open.
Do not claim atomic exclusion. Arrange for applications/compositor to stop using
this GPU before initial handoff; do not kill/restart user applications automatically.
There is no bypass flag in the new check. No new handoff is needed in this boot.

## Linux control after reboot

`/home/bogdan/macos-vm/run/linux-vcn-2508eb6d-control/result.json`:
H.264/HEVC software, hardware and repeated hardware encodes exit 0. Three-frame
software/hardware decodes validate 2,675,475 luma values each, maximum error 1 for
H.264 and 0 for HEVC. Capture complete, workloads stopped, no kernel faults.
Used `linux-vcn-baseline/tools/cycle.py linux-vcn` without `--sram`; no raw register
sampling. amdgpu was retained until the subsequent handoff described above.

Earlier Linux captures already showed working VCN with protected registers reading
ffffffff/deadbeef. Retract prior claims that these values alone prove a dead VCPU,
that PSP authentication is the definitive wall, or that all driver fixes are exhausted.

## Decoder progress and host crash evidence

272 fixes a concrete early failure: our PowerPlay startup bypass left native DPM
unsupported, while AMDVA advertised it as supported and sent a failing power request.
The guarded process-private AMDVA patch selects its native unsupported-DPM path.
Decoder creation/hardware selection now succeeds; actual frame execution still hangs.
Source audit: candidate272 `findings/research/vcn-dpm-capability-20260916.md`.
272 run `cc4abd9fd50b3183b84ba6dd82392cb6`; forced shutdown, recovered receipt.
271 software control validated three frames. Do not call this working hardware decode.

273 run `063833e5a790e948ed941f63fb1fd831`, build
`08823221f09a46cdbbe1b394869048f1`, MODE2 reset 132, old boot
`c782d007-ca85-409b-9cf5-ff12c1a8c6d5` (12 exposures).
Metal probe passed, then user reported host crash. No final verdict/shutdown/recovery.
Serial ends at `VCNSR post-submit` during first VCN start, before start return or
any `VCNQ` submission entry. Raw-wptr behavior was therefore not observed.
The following source region reads protected registers; this is a suspect diagnostic
boundary, not a proven crash instruction. Journal/pstore did not capture a panic.
Raw evidence and SHA manifest: `/home/bogdan/macos-vm/run/candidate-273-crash-20260916/`.
Second guest-command delivery exists in transport logs but its payload/initiator
is unresolved; no codec-command result artifact exists. See candidate274 research
`findings/research/candidate273-host-crash-20260916.md`.

## Suggested continuation for Claude

1. Review the uncommitted client guard and finish its documentation before any
   future Linux-to-VFIO handoff. Preserve user applications.
2. Start from 274's diagnostic-removal baseline for the next bounded decode-first
   experiment, with an explicitly recorded boot allowance and all cycle gates.
   A codec run has not yet tested that baseline.
3. Compare actual native queue/firmware protocol with Linux. 273's raw-wptr change
   remains unqualified. Apple publishes the high bit to both shared wptr and
   SCRATCH2; Linux captures show raw values. Do not confuse source support with a
   completed hardware test. Avoid restoring intrusive protected-register probes.
4. Keep codec execution, display qualification and crash/reuse qualification separate.
   Read project safety docs and live state before resuming; dated status is not a
   substitute for current hardware checks.

Previous detailed state is archived in
`findings/research/status-archives/status-before-claude-handoff-20260916.md`.
