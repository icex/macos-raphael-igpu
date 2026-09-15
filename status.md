# Live status — 2026-09-15

## Current result

**macOS hardware H264 remains unresolved after candidates263–265.** All three
passed the desktop probe, selected hardware encoding, accepted frames0/1,
and stalled on frame2 with no encoded callbacks (probe deadline124).

| Candidate | Change observed | Encoder result |
|---|---|---|
|263 / metal-109|Native-owned inactive decoder ring initialized before pause, returned0|PauseACK timeout +94db1; frame2 stall|
|264 / metal-110|Shared allocation4096 and SRAM d3=1000, decoder setup retained|Same pause timeout and stall; inherited pause request4 observed|
|265 / metal-111|Preinit pause4→0 verified, window4096 and decoder setup retained|New pauseACK still times out; frame2 stall|

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
- Results under `/home/bogdan/macos-vm/run/candidate-263-results` and
  `candidate-264-results` and `candidate-265-results`; source in corresponding candidate worktrees.
- All three harness verdicts **CORE_PROBE_PASS**, independently failed encoder probes.
  Critical capture survived all three. All shutdowns **forced**, all recovery
  receipts **recovered**. Only `rgpu-inhibit` remains running.
- Full host suites937tests OK, three skipped. No merge/push.
- MODE2 reset120 preceded263, reset121 preceded264. Reset122 preceded265. Reset119 preceded a staging
  version-gate refusal before QEMU: no launch entry consumed. Three launches now
  recorded on this boot, allowance3.

## Next test

Candidate266 will change only the native shared allocation class2→0, preserving
4096bytes, flags, firmware mode, decoder setup and preinit unpause. Update both
allocator argument and stored release metadata. Confirm actualGPUaddress before
claiming VRAM backing; capture shared words. 265 cleanup is recovered. Clearing
stale request bits was demonstrated but did not make encoding work.

Linux is still the positive reference: H264/HEVC encode/decode and600 validated
H264 frames. Working Linux also reads cache/reset/LMA registers asffffffff;
those values do not establish a dead VCPU. Firmware payload and real SMU message6
transport match macOS. Shared flags and memory placement remain separate
untested differences; no claim that driver-level possibilities are exhausted.

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

## Candidate266 observation and candidate267 extension
266 shared buffer moved to VRAM f40fa97000, SRAM NC0low0fa97000/highf4/size1000
verified, decoder init and pause cleanup selected; fresh pause ACK stilltimeout.
Final output and cleanup pending; require recovered receipt before267.

User authorized continued testing. Extend allowance4→5 on boot
c782d007-ca85-409b-9cf5-ff12c1a8c6d5 for one isolated shared-flags experiment.
Candidate267 changes only shared present flags f47→b40 matching capturedLinux,
keeping field contents, memoryclass0/VRAM,4096size, decoder init, unpause and
softwarefirmware/SRAM. Guard priorflags exactlyf47; lognewflags andlegacyCGCmode.
Max6000seconds; manual-reuse/ack-risk after266 recovery andfreshMODE2, all guards
retained. No amdgpu rebind/reboot/merge/push.
