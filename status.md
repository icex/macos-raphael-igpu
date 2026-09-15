# Live status — 2026-09-15

## Current result

**Offscreen Metal passes; hardware H264 remains unresolved through candidate268.**
All263–268 passed1000 offscreen frames with zero sampled pixel mismatches and the
24-case readback matrix. All hardware encoders selected GVA hardware, accepted
frames0/1, stalled on frame2, produced no callbacks and hit probe deadline124.
CORE_PROBE_PASS covers the desktop probe, not the separate codec probe.

| Candidate | Observed intervention | Result |
|---|---|---|
|263|Native inactive decoder ring initialized before pause|Pause ACK failed|
|264|Shared allocation/window4096bytes|Same; inherited pause4 confounds freshness|
|265|Preinit unpause4→0|New pause ACK still failed|
|266|Shared buffer moved to VRAM|Same|
|267|Shared flags f47→b40|Same|
|268|PSP mode0, native SRAM ownership, zero firmware/stack placeholders|All guards and firmware-loaded query pass; same pause/frame2 stall|

268 follow-up hardware-decode probe never reached decoder creation: it stalled
at software encoder creation after the hardware encoder hang. This is dirty-state
behavior, not evidence that hardware decode fails. Fresh decode-first test pending.

## Identity and cleanup

Boot `c782d007-ca85-409b-9cf5-ff12c1a8c6d5`, GPU0000:7b:00.0 on vfio-pci,
power/control=on, PCI reset methods disabled. Native Linux baseline preceded the
user-authorized Linux→VFIO handoff. **No amdgpu rebind this boot.**

- 267: run1127597f31560ab35dbaf46baa05cdad, build589d40a85f0c4333be158bdba134dbb3, source1bf1578, MODE2 reset124.
- 268: run7a6e65cd000f2d91b6635d7758194477, build4ff2486909654de18c323ccf5c115ccd, source094ee6f, MODE2 reset125.
- Results `/home/bogdan/macos-vm/run/candidate-N-results`; source corresponding candidate worktrees.
- All six harness verdicts CORE_PROBE_PASS; critical capture and identity validated.
  All shutdowns forced, not clean guest shutdowns; all recovery receipts recovered.
- 268 full host suite937tests OK, three skipped. Initial software-allocation fixture
  was updated to verify native ownership and refusal without context mutation.
- Six launches recorded this boot. Earlier staging/fixture prelaunch refusals did
  not consume launches. No merge or push.

## Display evidence and remaining scope

267 has an AMD-backed1280x1024 display and WindowServer accelerator client.
Window drawable readback11616 sampled pixels, wrong0; two own-window captures
match quadrant patterns and show moving bar spans241..280→44..83. Whole-display
window-region captures show wallpaper only, screen_capture_preflight=false;
zero nonzero-time presentations. Capture privacy versus actual desktop composition
remains unresolved. 268 also has a correct drawable readback. Screen Sharing
responds on host127.0.0.1:5900 with RFB003.889; no external frame qualification yet.
Watchable external desktop, physical scanout, codecs and long-run lifecycle remain
unqualified; do not equate offscreen success with completion.

## Next discriminating test: candidate269

Linux's positive DPG trace has no PGFSM_CONFIG write and observed PGFSM_STATUS
2aaa8aa0 (masked2a2a8aa0). Apple secure init+9442a calls939d1 after realSMUPowerUp6,
writing all-off config2a2aaaaa and waiting for masked all-off state2a2aaaaa.
269 changes that exact initial secure-DPG write to native core-on config2a2a9aa5
and the real wait to2a2a8aa0; preserve POWER_STATUS anti-hang setup, firmware/SRAM,
shared fields and decoder setup. Guard target, mode0, IP30001, initializer943cf,
unstarted engine and zero active queues; require write/wait routes. Propagate a
failed actual on-state wait. Log state after SRAM, allowing legitimate DPG gating.
Hypothesis: the native all-off transition removes Linux's startup precondition.
A verified on-state transition with unchanged pause/encode failure rejects this
as sufficient. This is not a confirmed root cause yet.

Extend allowance6→7 on boot c782d007-ca85-409b-9cf5-ff12c1a8c6d5 for this power-state
comparison under the user's continued-testing instruction. Require268 recovered
(verified), fresh MODE2, unchanged identity/capture/host-fault/shutdown/cleanup gates,
max6000seconds, manual stop at result/stall. No reboot, amdgpu rebind, merge or push.

Linux reference: `/home/bogdan/macos-vm/run/worktrees/linux-vcn-baseline/findings/research/linux-vcn-baseline-20260915.md`.
Linux H264/HEVC encode/decode and600 validated H264 frames passed. Working Linux
also reads cache/reset/LMA registers asffffffff and UVD_STATUS asdeadbeef; these
values do not prove a dead VCPU. No claim that driver-level options are exhausted.
