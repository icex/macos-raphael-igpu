# Status

Updated after launch46, 2026-09-14. Host boot
`c369c74e-96ff-4c21-ae85-80ccb269f7d2`, GPU vfio-pci, power/control=on.
VM stopped; ledger46; final MODE2 reset73 CP_STAT=0/RLC_CNTL=0. No host reboot.

## Observed result

Candidate233 corrects the native MMHUB register table. Desktop Metal probe passes;
hardware H264 now stalls only on VCN0EncLLQ while VMPT, SDMA and graphics complete.
This removes the observed shared paging stall, but produces no encoded frames.
Visible green/purple menu corruption from launch45 remains unresolved. Hardware
HEVC and HEVC-alpha remain unqualified. Software H264/HEVC roundtrips passed on
launch45. RustDesk removed from reopen-at-login only as a startup workaround.

## Evidence and next work

Launch46 run `953a71a247c9dfea622129c4a598026c`, build
`aeadd6aac6584078b7fd944c58d82459`, candidate233/card metal-079, reset72.
Results: `/home/bogdan/macos-vm/run/candidate-233-results/`.
Serial confirms corrected context2 root register0x1a950 and engine6 request/ACK
0x1aa31/0x1aa32. Hardware H264 selects gva/hardware=true, accepts two submissions,
blocks on third and reaches90s deadline without callbacks. First pending channel15
is VCN0EncLLQ; SDMA12 completed/submitted234, VMPT16 completed/submitted80d.
WindowServer remains responsive. Do not call CORE_PROBE_PASS encoder success.
Shutdown forced; harness recovery reports recovered. Final MODE2 reset73 clean.
Host regression suite926 tests,3 skipped, no failures.

[Audit](findings/research/tigervnc-reset-audit-20260914.md) preserves identity,
functional, visual and cleanup outcomes. Investigate VCN initialization/firmware
and queue programming; independently extend format/IOSurface/compositing tests
for visible corruption. Neither task is complete. No new launch allowance yet.

Active worktree: `/home/bogdan/macos-vm/run/worktrees/candidate-233`.
User forbids host reboots. Use tools/cycle.py with fresh MODE2, explicit boot note,
6000s maximum and existing abort/cleanup checks. No merge or push main.
Original pre-existing supervision edit remains in candidate230's named stash.

## Candidate234 allowance

One fix-validation launch47 on boot c369c74e-96ff-4c21-ae85-80ccb269f7d2,
candidate234/cardmetal-080, fresh MODE2 via tools/cycle.py, max6000s.
Hypothesis: missing VCN firmware prevents engine startup. Verify supplied bytes,
native initialization result and actual encoded output. A supplied/accepted image
with continued queue stall rejects firmware supply alone as sufficient. First run
Metal regression and supplemental surface-format probe while responsive. Stop on
first stall; no further encoder on dirty state. Corruption remains required work.
Host926 tests/3 skipped plus firmware payload integrity test passed. Build complete.
