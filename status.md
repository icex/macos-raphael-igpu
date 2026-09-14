# Status

Updated after launch45, 2026-09-14. Host boot
`c369c74e-96ff-4c21-ae85-80ccb269f7d2`, GPU vfio-pci, power/control=on.
VM stopped; ledger45; final MODE2 reset71 CP_STAT=0/RLC_CNTL=0. No host reboot.

## Observed result

Candidate230 desktop probe passes again after removing RustDesk from the guest's
reopen-at-login list (backup retained). RustDesk --check-hwcodec-config was the
HEVC requester that triggered startup stalls. This is only a workaround.
TigerVNC now displays the desktop, but menus contain visible green/purple corruption.
User explicitly requires fixing that and broken encoders; neither is complete.
Software H264/HEVC roundtrips pass. Hardware H264 reproduces the VMPT/SDMA stall
from a responsive guest; no encoded frames complete. HEVC-alpha untested.

## Evidence and next work

[Audit](findings/research/tigervnc-reset-audit-20260914.md) records exact runs,
identity, screenshots, process/XPC attribution, backups, codec outcomes and packet
contents. Launch45 results: `/home/bogdan/macos-vm/run/candidate-230-attempt-without-rustdesk-results/`.
Its CORE_PROBE_PASS covers the earlier Metal probe only; the later encoder stalls
and visible corruption prevent full qualification. Shutdown forced/recovery incomplete,
followed by clean documented MODE2 reset71.

The captured VMPT IB writes/polls the legacy MMHUB2.0 register layout at0x13200
and leaves its hub1 framebuffer root unrepaired. Raphael MMHUB2.4.1 uses the2.3
layout in segment1 at0x1a000. Audit the native214-dword table and implement a guarded
correction in candidate233; verify the actual corrected IB and encoder frame output.
Do not assume this independently explains visual corruption.

Working directories: candidate230 hardware coordinator; candidate233
`/home/bogdan/macos-vm/run/worktrees/candidate-233` encoder/surface work.
No new launch allowance yet. Each next launch requires an explicit same-boot note
and fresh MODE2 through tools/cycle.py, max6000s with abort/cleanup checks intact.
User forbids host reboots. No merge or push main.

Host suite925 tests,3 skipped,no failures: `run/encoder-surface-host-tests.log`.
Original pre-existing supervision edit remains in candidate230's named stash.

## Candidate233 allowance

One user-authorized fix-validation launch on boot
`c369c74e-96ff-4c21-ae85-80ccb269f7d2`, candidate233/cardmetal-079, after fresh
MODE2 through tools/cycle.py. Bound6000s. First verify214-word table correction,
Metal regression output, then hardware H264/HEVC roundtrip while responsive.
Stop and capture immediately on a stall; no other codec on dirty state.
Hypothesis: the legacy MMHUB addresses cause the shared encoder stall. Corrected
addresses with the same stalled ACK would falsify this as a sufficient fix.
Visible corruption and HEVC-alpha remain independent required work.
