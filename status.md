# Live status — 2026-09-15

Candidate259 run8d676fd6fb660a9083e8d675aada18e2, build9579538d50b54db7a472fa8e5c88559f.
Software FW mode1 + allocated committing SRAM ran: firmwaref40fa98000,
initializer+943cf, pre-release additions observed. PGFSM/power waits passed,
pause ACK +94db1 timed out. Hardware encoder accepted2frames then stalled.
Desktop CORE_PROBE_PASS. Forced shutdown, recovery recovered, VM stopped,
vfio-pci/power-on retained. MODE2 before run112. One-run allowance consumed.
This rejects PSP firmware placement as the sole cause, not all PSP/SRAM effects.

Software decoder control produced3correct frames/maxlumaerror1. Its hardware
Boolean query is unsupported(-12900), so the initial probe conservatively
reported failure; revised probe records unknown and uses required hardware plus
actual matching GPU registry for the hardware case. Recheck software control.

## Decoder-first one-run allowance
One additional launch candidate1.0.259 / metal-105 --attempt decodefirst on boot
c369c74e-96ff-4c21-ae85-80ccb269f7d2, under current user request to continue toward
a solution. Same kext binary. Fresh MODE2 and all cycle safety gates. Run software
control, then hardware decoder before any hardware encoder. Linux DPG startup
initializes decode ring first; native start_queue pauses before ring initialization.
Test whether decode-first startup changes the VCPU/pause/encode outcome. Record
both successful output and failure independently. max6000seconds, manual stop on
first stall or completion; vfio-pci/pinned awake, no main merge/push.
