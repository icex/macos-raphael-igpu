# Status

Updated after launch49, 2026-09-15. Host boot
c369c74e-96ff-4c21-ae85-80ccb269f7d2, GPU vfio-pci, power/control=on.
VM stopped; ledger49; final MODE2 reset79 CP_STAT0/RLC_CNTL0. No host reboot.

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
because native XH2 lease ownership was never produced. INVALID; final MODE2 reset79.
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

## Candidate236 allowance

One launch50 on boot c369c74e-96ff-4c21-ae85-80ccb269f7d2, candidate236/cardmetal-082,
fresh MODE2 via tools/cycle.py, max6000s and existing abort/cleanup. Validate both
patch deliveries, shared allocation0x60/SMU-interface2, then Metal and actual
H264/HEVC output. Capture registers promptly after first encode begin. Abort on
first failure and do not run other encoders on dirty state. Same SMU hypothesis
as235, which never delivered the intervention. Host927 tests/3 skipped passed.
