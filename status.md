# Live status — 2026-09-15

Full desktop acceleration remains unqualified: visible TigerVNC corruption persists,
and hardware H264 stalls. HEVC hardware has not been retested after current fixes.
Small software H264/HEVC round trips and limited Metal surface probes pass.

Worktree /home/bogdan/macos-vm/run/worktrees/candidate-238 (vcn-placement-trace).
Source5f186c0, builde14914203b324295b0843c41dc1088e1. Launch52/cardmetal-084,
run97685209eea2813158f9ad29a0fa0d4c, hostbootc369c74e-96ff-4c21-ae85-80ccb269f7d2,
prelaunch MODE2reset84. Guestboot85CE5BB4-4018-4DCB-B7B7-7D5CFBE7518A,
registry4294968035. Results /home/bogdan/macos-vm/run/candidate-238-results/.

## Latest functional result

Guarded query trace actually executes. FirmwareID14 native result0 loaded1 valid1
addressf41f400000 before and during native static initialization. Post-init context
retainsf41f400000, size8c150, registerbase7e00, shared GART addressffbfe52000.
This FALSIFIES bad PSP-query/context address as the explanation for all-ones code
cache readback in51. Register visibility/write permission remains unproven.
Static initializer returns0 despite50ms firmware-ready timeout. H264 hardware
encoder selected; third frame submit blocks and no encoded output. No further
codec on stalled state. Metal desktop probe passed but is not desktop qualification.

MMIO after-submit still shows code cache BARffffffff/ffffffff, VCNawake804, status0,
MMHUBfault0. Capture was late enough for native channel reset; its zero ring WPTR
cannot describe first submission. Native context trace is the discriminating result.
Artifacts: serial.txt, h264-hardware.jsonl, mmhub-vcn-after-submit.jsonl,
running-identity.json, probe.json.

## Corruption and next investigation

Launch50 raw Linux TigerVNC screenshot shows diagonal green/purple Safari/menu
corruption before any encoder: /home/bogdan/macos-vm/run/candidate-236-results/
tigervnc-corruption.jpg.12-case format/IOSurface CPU comparisons, quad and sampled
texture probes pass but do not reproduce the artifact. No common cause proven.

New memory-access lead: GFXHUB GARTCTX0 enabled1555401, rangeffbfa00..ffffe00,
root84fdfc001; MMHUBCTX0 disabled0, range0..3ffff, root85fc00001. VCN shared
bufferffbfe52000 requires GART. X6000 paging table fix does not cover HWLibs native
GVM register table (vm+510). Trace vm_10_1_get_register_offset32fbf and its table
initialization before proposing a mapping correction; no new hardware allowance.

## Cleanup

Stopped through interactive stop-requested. Shutdown forced, harness recovered.
VM stopped; final MODE2reset85 CP_STAT0/RLC_CNTL0. vfio-pci retained, power/control
on, same host boot, inhibitor active. No host reboot. Host927 tests/3skipped passed,
build succeeded. No merge/push to main. Prior state archived in
findings/research/status-archives/status-before-launch52-result-20260915.md.

## Candidate239 launch53 allowance

One launch53 on boot c369c74e-96ff-4c21-ae85-80ccb269f7d2, fresh MODE2 via
tools/cycle.py, max6000s, all abort/recovery paths preserved. Verify guarded native
MMHUB2.3 call delivery, CTX0/GART range before any encoder, then actual H264 output.
HEVC only if H264 succeeds and engines remain responsive; stop on first stall.
Worktree /home/bogdan/macos-vm/run/worktrees/candidate-239. Host927 tests/3skipped pass.
