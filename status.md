# Live status — 2026-09-16, after host crash

## Current host and qualification

User reports host crash during candidate273. Host rebooted to
`2508eb6d-ddf3-497d-9774-00a7ecebe3ed`; GPU0000:7b:00.0 is on amdgpu,
power/control=on,runtime active,no QEMU. No new VFIO handoff or launch performed.
Prior boot`c782d007-ca85-409b-9cf5-ff12c1a8c6d5` had12 exposures including273.
Do not reuse prior-boot recovery or allowance as current authorization evidence.
Full acceleration remains unqualified. No merge/push.

## Candidate273: incomplete host-crash run

Run`063833e5a790e948ed941f63fb1fd831`,build`08823221f09a46cdbbe1b394869048f1`,
sourcebf3c544,HEAD719062b,MODE2 reset132. Exact raw-wptr patch guard and submit
route report1. Results`run/candidate-273-results` contain a passing offscreen
probe (1000frames,zero sampled mismatches,24readback cases),running identity and
interactive-ready receipt. **No final verdict, shutdown or recovery receipt.**
Do not label273 CORE_PROBE_PASS or recovered based only on its probe.

Preserved logs in`run/candidate-273-crash-20260916`,SHA256 manifest included.
Serial ends after VCN SRAM readback diagnostic, during first VCN start. Video
context creation/capability return success, start entry present, start return absent.
No VCNQ submit entry captured, so the new write-pointer behavior was not observed.
Last logged power906; previously272 logged905. Exact crash-causing instruction is
unknown. Last persistent host kernel journal entry00:50:55,serial through00:52:16;
no panic/oops found in journal tail. Pstore inspected read-only via container:
empty;systemd-pstore archive empty. NMI watchdog and hardlockup panic enabled.
Missing logs do not establish a particular hardware/fabric failure mechanism.

Agent transport recorded a second command delivery at21:52:14UTC after the desktop
probe result, but no result. No273 codec-command artifact exists; its source/payload
is not established. Request clarification of the user's observed crash timing.

## Validated progress retained

272/run`cc4abd9fd50b3183b84ba6dd82392cb6`: exact guarded per-process AMDVA patch
selects native unsupported-DPM path. Decoder created(status0),hardware selected;
first DecodeFrame hangs90s(exit124),no callbacks,VCN0Dec stamp1 fails. Forced
guest shutdown,recovered host receipt,zero recovery kernel messages. This fixes
271's early PowerPlay unsupported request, not functional codec execution.
271 software control validated3frames,2675475lumas,maxerror1. Offscreen Metal
passed through273 before codec activity; full external/physical display remains
unqualified. Prior encoders263–269 accepted frames0/1,blocked frame2,no callbacks.
Linux baseline passed H264/HEVC and600validatedframes.

## Immediate investigation

Review/remove intrusive legacy VCN diagnostics before another macOS experiment.
`inspectVcnSram` writes the DPG LMA selector after SRAM commit; following VCNC,
VCNMM,VCNSEG,VCNSCAN read protected/power-gated and guessed-segment registers.
These were incorrectly treated as harmless read-only observation. The last serial
line places this diagnostic boundary before the missing start return; causality
is unproven. Linux already showsffffffff/deadbeef on a working VCN, so these probes
cannot support dead-VCPU claims and no longer answer a useful question.

Retain real Raphael SMU/DPG initialization, capability correction, native queue
ownership and host safety gates. Candidate273 raw-wptr change remains unqualified;
use272 functional baseline for isolating diagnostic removal. Continue offline
source and crash analysis before any new GPU exposure.

References: previous detailed status in status archives; candidate272 source audit
`findings/research/vcn-dpm-capability-20260916.md`;273 protocol hypothesis
`findings/research/vcn-raw-wptr-20260916.md`; Linux report under
`run/worktrees/linux-vcn-baseline/findings/research/linux-vcn-baseline-20260915.md`.

## Current-boot native Linux control

On boot`2508eb6d-ddf3-497d-9774-00a7ecebe3ed`, run the existing bounded Linux VCN
control via linux-vcn-baseline/tools/cycle.py linux-vcn without --sram. This uses
the native amdgpu driver, software/hardware codec controls and driver tracepoints;
no direct register sampling, kprobe SRAM capture, VFIO handoff or VM launch.
User resume/continued investigation authorizes the control. Preserve identity,
host-fault/capture/deadline checks and cleanup. Current iGPU renderD129 verified.
