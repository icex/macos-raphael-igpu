# Live status — 2026-09-15

## Current result

**macOS hardware H264 remains unresolved after candidates263–266.** All four
passed the desktop probe, selected hardware encoding, accepted frames0/1,
and stalled on frame2 with no encoded callbacks (probe deadline124).

| Candidate | Change observed | Encoder result |
|---|---|---|
|263 / metal-109|Native-owned inactive decoder ring initialized before pause, returned0|PauseACK timeout +94db1; frame2 stall|
|264 / metal-110|Shared allocation4096 and SRAM d3=1000, decoder setup retained|Same pause timeout and stall; inherited pause request4 observed|
|265 / metal-111|Preinit pause4→0 verified, window4096 and decoder setup retained|New pauseACK still times out; frame2 stall|
|266 / metal-112|Shared buffer moved to VRAM f40fa97000; address/size in SRAM verified|Same pause timeout and frame2 stall|

MODE2 cleared the graphics state but retained the VCN pause request. Therefore
264 is not an independently fresh VCN startup, and its failure alone does not
conclusively eliminate the shared-size hypothesis. 263 began with pause0 and
demonstrates that decoder-first alone is not sufficient.

## Identity, capture and cleanup

- Live boot `c782d007-ca85-409b-9cf5-ff12c1a8c6d5`; GPU `0000:7b:00.0`,
  `vfio-pci`, `power/control=on`, PCI reset methods disabled.
- Native Linux baseline passed before the user-authorized Linux→VFIO handoff.
  Do not rebind to amdgpu this boot. Handoff artifacts: `run/handoff-c782d007`.
- 263: run `0c2f9fbdbbd63473ceae1905d381412d`, build `8d6ca8d6f132475cb4d881241a15fbc3`, source `b124552`.
- 264: run `4918fb503fd83d56cdb01010325cb7d3`, build `99a0f545f7534bb289c7525cb05517f2`, source `73ed1ec`.
- 265: run `374d4003eda33393be37aee3b5cfc190`, build `fcf1256a578143dc917a9c44c2abf210`, source `14e7f18`.
- 266: run `b42dff23b9eb8c1f1f307fc12c5425bd`, build `a614fd27afec481fa91a74533a845033`, source `27fcd95`.
- Results under `/home/bogdan/macos-vm/run/candidate-263-results` and
  `candidate-264-results`, `candidate-265-results` and `candidate-266-results`; source in corresponding candidate worktrees.
- All four harness verdicts **CORE_PROBE_PASS**, independently failed encoder probes.
  Critical capture survived all four. All shutdowns **forced**, all recovery
  receipts **recovered**. Only `rgpu-inhibit` remains running.
- Full host suites937tests OK, three skipped. No merge/push.
- MODE2 reset120 preceded263, reset121 preceded264. Reset122 preceded265, reset123 preceded266. Reset119 preceded a staging
  version-gate refusal before QEMU: no launch entry consumed. Four launches now
  recorded on this boot, allowance3.

## Next test

Candidate267 changes only shared present flags f47→b40 to match Linux. Preserve
field contents, 4KiB VRAM allocation, decoder setup, preinit unpause and software
firmware/SRAM path. 266 completed with CORE_PROBE_PASS, encoder deadline124,
forced shutdown and recovered cleanup. Current user explicitly resumed testing
and requested persistence until full acceleration issues are solved.

Linux is still the positive reference: H264/HEVC encode/decode and600 validated
H264 frames. Working Linux also reads cache/reset/LMA registers asffffffff;
those values do not establish a dead VCPU. Firmware payload and real SMU message6
transport match macOS. Shared flags remain untested; shared VRAM placement was observed in266
and was not sufficient; no claim that driver-level possibilities are exhausted.

[Linux comparison](/home/bogdan/macos-vm/run/worktrees/linux-vcn-baseline/findings/research/linux-vcn-baseline-20260915.md).
Physical scanout/full desktop remain unqualified. Use candidate worktrees and
cycle.py with max6000seconds, pinned power, identity/capture/host-fault/cleanup
checks, and boot-named launch allowances. No amdgpu cycling or merge/push.

## Candidate266 boot allowance extension
User authorized continued testing of Linux findings. Extend allowance3→4 on boot
c782d007-ca85-409b-9cf5-ff12c1a8c6d5 for this one allocation-domain experiment.
Require265 recovered (verified), fresh MODE2 and every existing safety/capture/
cleanup gate. Use cycle --manual-reuse --ack-risk, max6000seconds, manual stop
after encoder result/stall. No amdgpu rebind, reboot, merge or push.

## Candidate267 allowance
Extend allowance4→5 on boot c782d007-ca85-409b-9cf5-ff12c1a8c6d5 for the single
shared-flag-word comparison. 266 recovery verified; fresh MODE2 and all safety/
capture/cleanup gates required. Max6000seconds with manual stop at result/stall.
No vfio→amdgpu, reboot, merge or push.
