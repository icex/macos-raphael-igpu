# Status

Updated after launch50, 2026-09-15. Host boot
c369c74e-96ff-4c21-ae85-80ccb269f7d2, GPU vfio-pci, power/control=on.
VM stopped; ledger50; final MODE2 reset81 CP_STAT0/RLC_CNTL0. No host reboot.

## Current blockers

Candidate233 corrected MMHUB paging addresses and client roots: graphics/SDMA/VMPT
complete during H264 attempt. Candidate234 supplies missing Raphael VCN firmware,
native HW initialization0 and PSP firmware load succeed. Hardware H264 still
stalls on first VCN0EncLLQ submission. HEVC/alpha unqualified. Software H264/HEVC
pass. RustDesk startup removal remains a workaround, not the encoder fix.
Visible green/purple menu corruption from launch45 remains unresolved. Twelve
format/blending/IOSurface cases and CPU readback comparisons pass; these do not
qualify actual desktop composition/capture. No merge or push main.

Candidate235 proposed adding SMU-interface2 required by Linux for Raphael VCN3.1.2.
Launch49 never tested this: guarded allocation patch applied zero times; native
VCN initialization correctly refused. Live51-byte readback matches original.
Lilu applyLookupPatch uses currentAddress < endingAddress after subtracting patch
size. maxSize=N allows zero matches; N+1 permits exactly the intended start.
The existing X6000 start-failure cleanup patch has the same defect and logs FAILED.
Candidate236 corrects both bounds and retains complete VCN readback guard.

## Latest evidence

Launch49 candidate235/cardmetal-081 run eabcad5b32ed73f9d16e556621e218dd,
build7f169d2fc4744f199b0489858331d930, pre-reset78.
Results `/home/bogdan/macos-vm/run/candidate-235-results/` include guard-live-bytes.txt.
No Metal probe/encoder result. stop-requested is only consumed in interactive hold;
used experiment.py's documented SIGTERM cancellation handler after inspecting it,
preserving guest shutdown and recovery. Exited-after-guest-request; recovery failed
because native XH2 lease ownership was never produced. INVALID; final MODE2 reset81.
No host kernel fault observed. This does not falsify the SMU-interface hypothesis.

Latest functional run48: candidate234 attemptvmhub, run
e73d5a3641b70484bd95dcfcf1f38732. CPU/GPU surface comparisons pass; H264 stalls.
MMHUB before/after read-only snapshots contain no latched fault, but after snapshot
overlaps native reset/power gating; it cannot establish the first fault. Ring
capture ABI matches Linux (IB opcode2, VMID2, VA0x400010280,12 dwords). Forced
shutdown/recovered, MODE2 reset77 clean. See candidate234 results and research notes.

Work continues in `/home/bogdan/macos-vm/run/worktrees/candidate-236`.
No new launch allowance yet. User forbids host reboots; use tools/cycle.py and
explicit boot allowance, fresh MODE2, max6000s with existing abort/cleanup guards.


## Launch50 result

Candidate236/cardmetal-082 runb9e4f059c1cb51785b3cfc10c410b65d, build6ef41eab5ac1480cb7ea1cc047ee5b49. Results
`/home/bogdan/macos-vm/run/candidate-236-results/`. Both bounded patches apply:
VCNA allocation extension1,error0; X6000 failure cleanup patch ok. Shared bytes96,
flagsf47,SMU-interface2. Desktop probe passes. Hardware H264 still stalls at third
submit/no callbacks. Exact early before/first-submit/+2s MMIO captures show VCN
POWER_STATUS905 and gated registersdeadbeef, already before codec request; MMHUB
fault0. Field setup alone is insufficient. Native VCN defaults enable dynamic PG,
static PG and secure-DPG load; investigate native static initialization instead.
Firmware authentication via PSP must remain intact.

Actual raw TigerVNC Safari screenshot confirms visible diagonal corruption before
encoder: tigervnc-corruption.jpg. Additional two-triangle and interpolated texture
sampling probes each pass12 cases; they do not reproduce the real visual artifact.
Shader/capture/compositing coverage remains incomplete. Probe sources retained in
run/research/encoder-20260914; CPU surface baseline tracked in tests.
Shutdown forced, harness recovered, finalMODE2 reset81 clean. No new allowance.

## Candidate237 allowance

One launch51 on boot c369c74e-96ff-4c21-ae85-80ccb269f7d2, candidate237/cardmetal-083,
fresh MODE2 via tools/cycle.py, max6000s and existing abort/cleanup. Verify config
0/1/7=0, firmware mode0, native static initializer930f8 and its result. Check
powered VCN registers and actual H264 output, then HEVC only if responsive.
Continued stall with powered registers rejects static init as sufficient. Stop
on first failure, no further encoder on dirty state. Host927 tests/3 skipped pass.


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-237-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`
