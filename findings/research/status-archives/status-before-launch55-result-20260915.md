# Live status — 2026-09-15

Visible desktop corruption and hardware encoding remain unresolved. Worktree
/home/bogdan/macos-vm/run/worktrees/candidate-240 (mmhub-runtime-target).
Launch54/cardmetal-086 run245f9a245b3d621e48595da8662fbdfc, sourceb0734f5,
results /home/bogdan/macos-vm/run/candidate-240-results/; build identity in manifest.
Hostbootc369c74e-96ff-4c21-ae85-80ccb269f7d2, prelaunchMODE2reset88.
Guestboot53E7BD8C-D3D0-4EE5-AE06-AAB52B1F00A6, registry4294968025.

## Verified fix and remaining failure

Native MMHUB2.3 builder actually selected (MHG route1/select1, caller33eca, GC1,
unique exact PCI marker). Table ctx0/root/start/end1a740/1a940/1a942/1a944.
MMIO BEFORE encoder: CTX0 enabled1555481, root84fdfc001,
rangeffbfa00..ffffe00, L1TLB1d59. This fixes the separate HWLibs native GART
initialization defect; X6000 paging-table fix from233 remains necessary separately.
The diagnostic label tlb=1a8ec actually names framebuffer base, not TLB (label typo).

Desktop Metal probe passes. Additional derivative shader across two triangles
passes12 format/storage cases (surface-derivative.jsonl). Actual raw Linux
TigerVNC screenshot still shows same diagonal green/purple Safari/menu corruption
BEFORE encoder: tigervnc-corruption.jpg. No desktop rendering qualification.

H264 selected hardware encoder, submitted0/1, blocked on2/no frame callbacks.
VCN native query and context both retain valid PSP TMRf41f400000. Static initializer
returns0 despite firmware-ready timeout. Post-submit snapshot awake804/status0,
code cache readbackffffffff/ffffffff, MMHUBfault0, correct GART retained. Snapshot
is not guaranteed before native ring reset; zero ring pointers are not first-stall
proof. Hardware HEVC not tested on stalled engine. Earlier small software H264/HEVC
roundtrips pass. Common cause with visible corruption remains unproven.

## Cleanup and scope

Stopped through interactive stop-requested. Shutdown forced, harness recovered.
VM stopped, final MODE2reset89 CP_STAT0/RLC_CNTL0. Hostboot unchanged, vfio-pci
retained, power/control on, inhibitor active. No host reboot. Our VNC viewer and
SSH master closed. Host927 tests/3skipped pass; build succeeds. No new allowance.

## Next discriminating investigation

MMHUB correction is insufficient for VCN firmware readiness. Linux VCN startup
also sends platform PowerUpVcn through SMU13.0.5; Apple dummy SMU backend does not.
Audit native CGS indirect register transport and exact Raphael message mapping
before considering that intervention. No host SMU power command has been issued.
Do not equate all-ones protected-register read with bad software address (52
falsified that). Continue actual desktop corruption reproduction separately.
No merge/push to main. Superseded state archived under findings/research/status-archives/.

## Candidate241 launch55 allowance

One launch55 on boot c369c74e-96ff-4c21-ae85-80ccb269f7d2, fresh MODE2 via
tools/cycle.py, max6000s, existing abort/recovery paths. Test guarded native SMN
GetSmuVersion2 then documented Raphael PowerUpVcn6/arg0 before static init.
Exact current firmware version00625300 required; failures refuse initialization.
Verify actual native transport/replies and H264 frames, then HEVC only if healthy.
Stop on first stall. Host928 tests/3skipped pass, build succeeds. Worktree241.


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-241-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`
