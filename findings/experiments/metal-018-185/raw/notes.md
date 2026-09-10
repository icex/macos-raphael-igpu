# Candidate 185 frozen run archive

Run `2ef50dc9d8b466c5f2521208b5ba87ea` was the single authorized candidate-185 GPU invocation. The frozen verdict is `INVALID`, with earliest failure `identity_or_route_missing`, evidence `capture_loss`, `capture_loss`, and termination `RuntimeError: critical capture remained incomplete at exposure deadline`. No Metal probe result and no VMID1 fault data were produced.

The guest loaded candidate 185 and the earlier serial evidence included a WindowServer `AMDRadeonX6000Framebuffer` panic during `AmdPowerPlayHelper::powerUp` (`BGM event 0xc00c0203`). Dedicated COM2 critical producer readiness and CR2 transport never appeared; `critical.txt` contains only early OpenCore output.

Built-in shutdown recorded `exited-after-acpi-request`; guest identity transport failed, so no guest shutdown request was sent. Built-in schema-3 recovery refused with `dedicated critical producer readiness is absent or conflicting`; no authorizing recovery receipt was produced.

The final host snapshot shows the same boot, `vfio-pci`, accessible/awake device, active inhibitor, valid watchdog/pstore gates, no active VM, and no pending launch. The ledger is 2/3 used. Candidate 184 artifacts and authorities remain preserved separately.

Conservative unresolved actual GPU-cycle count is 7: candidates 179, 180, 181, 182, 183, GUI-183, and 185. Candidate 184 was refused before QEMU and is not counted.

This directory is an offline byte-exact archive; no source, VM file, ledger, receipt, device state, or old capture was modified.
