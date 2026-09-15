# Live status — 2026-09-15

Candidate260 run b11a5314e251cb1031266e0786560051 exposed the GPU after
an erroneous skip-tests launch despite a host suite cleanup error. Stopped
before codec workload; no VCN SRAM hypothesis exercised. Desktop CORE_PROBE_PASS
is recorded but this run is NOT qualified under the required host-green rule.
Shutdown exited-after-guest-request; recovery recovered; host-after VM=false,
vfio-pci, power pinned. MODE2 #115. Results: candidate-260-results.

Test error was TemporaryDirectory removal racing the orphan managed launcher's
SIGTERM cleanup. Fixture now waits for managed process exit via pidfd before
removing its files. Waiting also exposed SIGTERM RuntimeError swallowed by startup retry handlers.
Use SystemExit to reach existing BaseException failure-record and finally cleanup.

259 software firmware plus committing SRAM still timed out on DPG pause ACK.
Decoder-first API requests never reached VCN initialization. Encoder unresolved.

## One-run allowance
One additional launch candidate1.0.260 / metal-106 attempt readback on boot
c369c74e-96ff-4c21-ae85-80ccb269f7d2 under current user request for continued
work and testing. Only after full suite passes, fresh MODE2, cycle.py,
manual-reuse/ack-risk, max6000 seconds and all abort/cleanup paths intact.
Hypothesis: submitted SRAM is readable with expected final values via LMA port.
Read-selector writes can affect observation; no SRAM data writes added.
Stop after first encoder stall/readback or completed hardware output.
