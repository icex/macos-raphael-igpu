# Status

Updated after launch48, 2026-09-14. Host boot
c369c74e-96ff-4c21-ae85-80ccb269f7d2. VM stopped; ledger48; GPU vfio-pci,
power/control=on. Final MODE2 reset77 CP_STAT0/RLC_CNTL0. No host reboot.

Candidate233 corrected shared MMHUB paging stall. Candidate234 supplies missing
Raphael VCN firmware: native HW initialization0 and PSP LOAD_IP_FW wireType13
status0, TMR0xf41f400000. VCN scratch now50/50 rather than deadbeef. Hardware
H264 still stalls at first VCN0EncLLQ submission; no encoded frames. WPTR2=20,
RPTR2=0, ringbase0xf40fb08000. SDMA/VMPT/graphics complete. Controlled stop after
confirmed stall; do not claim codec deadline fired. HEVC/alpha untested on234.

Desktop probe passes. New surface probe passes12 cases (BGRA8/RGBA8/RGBA16Float/
RGB10A2, private/managed/IOSurface, alpha blending) with0 mismatched pixels.
This does not qualify the desktop: visible menu corruption from launch45 remains
unresolved. Need CPU IOSurface readback/capture and actual TigerVNC visual retest.
Software H264/HEVC passed on230; RustDesk startup removal remains a workaround.

Run bbda0ca13aa5f9cfbc016a32534f909a, build6b82df99e281490e82cf720d72747b0a,
candidate234/cardmetal-080, prelaunch MODE2 reset74.
Results `/home/bogdan/macos-vm/run/candidate-234-results/` preserve surface probe
source/results and H264 trace. Shutdown forced; harness recovery recovered;
CORE_PROBE_PASS covers only earlier desktop probe. Host926 tests/3 skipped plus
new firmware integrity test passed. No merge or push main. User forbids reboots.

Next: read MMHUB fault/address configuration and VCN queue registers before and
after first submission to distinguish address translation from firmware commands.
Worktree `/home/bogdan/macos-vm/run/worktrees/candidate-234`.


Launch48 candidate234 attemptvmhub, run e73d5a3641b70484bd95dcfcf1f38732,
pre-reset76. Same H264 first-queue stall. CPU IOSurface comparison also passes
all12 cases. Read-only QEMU snapshot sees no latched MMHUB fault before/after;
after snapshot overlaps driver recovery/power gating (VCN registers deadbeef),
so does not establish the first fault. VRAM ring capture contains IB opcode2,
VMID2, VA0x400010280,12 dwords; fence opcode3. This agrees with Linux ring ABI.
Shutdown forced/recovered; final reset77 clean. No new launch allowance.
Next audit: Linux VCN3.1.2 explicitly sets SMU-interface2 in shared firmware
structure offset0x58; native Apple allocation is only0x58 bytes and omits it.
Need guarded allocation extension and field setup before native engine start.
