# Status

Updated after launch47, 2026-09-14. Host boot
c369c74e-96ff-4c21-ae85-80ccb269f7d2. VM stopped; ledger47; GPU vfio-pci,
power/control=on. Final MODE2 reset75 CP_STAT0/RLC_CNTL0. No host reboot.

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

## Launch48 allowance

One diagnostic repeat candidate234/cardmetal-080 attemptvmhub on boot
c369c74e-96ff-4c21-ae85-80ccb269f7d2. Fresh MODE2 through tools/cycle.py,
max6000s, existing abort/cleanup intact. Read only documented MMHUB fault/root/
aperture and VCN ring registers via QEMU monitor using verified guest BAR5.
Compare before/after first encoder command. Stop after stall, no further encoder
on dirty state. Run additional surface CPU-readback before encoder. Hypothesis:
VCN cannot fetch its ring through MMHUB; fault/address evidence discriminates this
from command ABI/firmware scheduling. No speculative address writes.
