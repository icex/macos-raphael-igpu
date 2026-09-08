# Metal-001: the third same-boot launch retained GC queues

This was the third and final GPU launch permitted on host boot
`851d35df-7e63-4154-b70b-5cfa044913d6`. It consumed recovery
`fb853596d61e478daf6d4134ffc67f98`, which had destroyed both PSP rings after the
fully initialized candidate-166 run.

Candidate 166 again applied the one-instance SDMA topology and channel mapping. Hybrid engines
12 and 13 returned status 0, and KIQ stamps 1, 2 and 3 completed. The following native
`waitForHwStamp(1)` returned 0 before the Metal probe could run. The timeout dump found sixteen
active ME2 HQD selections across pipes 0–3. Even-pipe selections pointed at ring
`0xffbfec0000` / MQD `0xf40b707000`; odd-pipe selections pointed at the previous KIQ ring
`0xffbfea0000` / MQD `0xf40b706000`, with RPTR and WPTR both `0x60`. This is persistent GC/KIQ
state from the preceding fully started guest. PSP ring destruction alone does not provide a
repeatable clean state.

The panic after that timeout is contaminated by diagnostics. `wrapWaitStamp` performed a large
MMIO queue walk and several serial dumps in a native path that can hold a spin lock. The panic
backtrace enters `lck_spinlock_timeout_set_orig_ctid` and then recursively faults while handling
the trap. Candidate 167 removes all large timeout-side work and keeps only the bounded critical
record. The reclassified earliest failure is therefore `BASELINE_BLOCKED` at KIQ, rather than
the later unknown-symbol panic.

The guest command channel did not answer, so shutdown was a confirmed exact-container force
stop. The host remained healthy. Post-stop rootless recovery again received exact PSP responses
(`DESTROY_RINGS` after 7 polls, `DESTROY_GPCOM_RING` after 1), kept PCI command `0x0003`, and
reported no host fault. That transaction did not clear the active HQDs found above. The
three-launch ceiling remains exhausted; no fourth launch was attempted.
