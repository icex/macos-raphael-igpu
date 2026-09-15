# Live status — 2026-09-15

261 cleared inherited DPG_MODE, static PGFSM wait passed, encoder still stalled.
Forced shutdown, recovery recovered. Results candidate-261-results.
262 tests retained VCN state: guarded SMU PowerDownVcn5/PowerUpVcn6 pair
before first native static initialization with no active queues. Source enum:
macos-vm/ref/linux/smu13/smu_v13_0_5_ppsmc.h; argument0 per Linux PPT backend.
No claim that successful SMU reply alone proves physical domain transition.

## One-run allowance
One launch candidate262/metal-108 on boot c369c74e-96ff-4c21-ae85-80ccb269f7d2
under current user request for continued testing toward solution. Fresh MODE2,
full host suite, cycle.py/manual-reuse/ack-risk, max6000seconds, all host,
identity, capture, shutdown and recovery aborts intact. No host rebind or
reboot. Stop after first stall or completed encoded output. No merge/push.
