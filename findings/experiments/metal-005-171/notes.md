# metal-005 / candidate 1.0.171

This was the first reset-free launch after the 2026-09-08 host boot and the first recovery
that authorized another launch without a reboot. Native KIQ stamps 1 through 6, one-instance
SDMA startup, `AMDHardware::startHWEngines`, and `AMDGraphicsAccelerator::powerUpHW` all
succeeded. WindowServer then stalled the shared `SDMA0_PAGE` channel on a VMID 2 indirect
buffer at `0x400100000` before any Metal probe result.

The original verdict incorrectly named the later KIQ stamp 28 timeout as the first failure.
That KIQ timeout appears at serial line 10713 after the first SDMA paging timeout at line 3189.
The corrected classifier preserves raw terminal line ordering and reports
`sdma_vm_context_missing`: the `programAndInvalidateVM` hook never ran on this command-stream
VM-programming path, so it could not supply the required context evidence.

Recovery is authorizing: both active HQDs dequeued on their first poll, no queue was force
cleared, `CP_STAT` and `CP_CPC_BUSY_STAT` read zero, SDMA was halted, both PSP teardown commands
were confirmed, PCI reset methods remained empty, and the host kernel journal did not advance.
The receipt permits one targeted same-boot follow-up.
