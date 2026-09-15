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

## Completed readback attempt
Run 2a680945e239063f9a3c9e11d8083e37, build818054a6626e48d48b744cf54149d4fd,
MODE2 #116. cycle.py reran full suite successfully (934 tests, three skipped).
Hardware encoder correctly selected accelerator4294968033; frames0/1 accepted,
frame2 stalled, no encoded output. All33 final SRAM selections returnedffffffff
both post-submit and pause-failed. Port accessibility is unresolved; this does
not prove absent SRAM or firmware authentication failure. Native PGFSM and
POWER_STATUS waits passed, DPG_PAUSE ACK timed out. Desktop CORE_PROBE_PASS.
Shutdown forced, recovery recovered, host-after VM=false/vfio-pci/pinned.
Artifacts: candidate-260-attempt-readback-results. Allowance consumed.

Next source finding: prior static experiments retained POWER_STATUS.PG_MODE=1
(0x804), while software config selected static. Native static initializer never
clears bit2; Linux stop_dpg_mode explicitly clears it. Static path has not yet
been tested after explicitly exiting inherited DPG mode.
