# End-to-end coordinator validation — 2026-09-08

Prepared and ran with explicit `gpu:false`, source `2a91a76`. Actual QEMU
had zero VFIO arguments and the exact prepared image ID. The recorded build
`90fc73c8b2e74ad79ecc2db3eb85ad4c` matches the candidate executable and ESP.
Critical sequence 0 was complete; dropped and truncated counts were zero.
The coordinator stopped on that record, requested ACPI shutdown, and confirmed
its exact-CID forced fallback after the 20-second grace period. This is not
native graceful shutdown or GPU teardown. Kernel monitoring continued through
cleanup; no matching host fault was captured. Boot ID remained unchanged,
iGPU owner remained amdgpu, and no physical-GPU boot reservation was created.

`GPULESS_CAPTURE_CHECK` deliberately has `valid:false`: there was no GPU route,
hybrid call or Metal execution to classify. The automated validation establishes
candidate delivery, critical-record capture, bounded coordination and cleanup.
Together with 75 passing regression tests and reviewed abort paths, this passes
T1–T4's prerequisites for the separately gated physical experiment.
