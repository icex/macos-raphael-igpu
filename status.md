# Live status — 2026-09-15

Candidate256: PGFSM and power-status waits pass; pause acknowledgment times out
at +94db1. Hardware H264 has no output. Desktop probe passes. Forced shutdown,
recovery recovered. Artifacts /home/bogdan/macos-vm/run/candidate-256-results/.
Real PowerUpVcn response1/version625300 observed, not a dummy acknowledgment.

Candidate257 tests Linux pre-reset-release register access setup omitted by
Apple secure SRAM builder: XX_MASK, XX_CHECK, LMI_CTRL2 and RB_ARB_CTRL. Keep
firmware path/cache values and exact wait trace. SRAM grows256->288 bytes with
capacity guard. Hypothesis falsified as sufficient if pause ACK still times out.

## One-run allowance
One launch candidate1.0.257 / metal-103 on boot
c369c74e-96ff-4c21-ae85-80ccb269f7d2 under current user instruction to continue
working/testing toward a solution. Fresh MODE2 through cycle.py, manual-reuse /
ack-risk, max6000seconds, existing host/identity/capture/recovery aborts intact.
Stop on encoded output or first stall. Host must remain vfio-pci/pinned awake.
No merge/push. Record outcomes after this run.
