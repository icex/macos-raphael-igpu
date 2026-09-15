# Live status — 2026-09-15

Candidate 253 supplied the five cache-window SRAM values; its hardware H264 test
still hung without encoded output. A zero initializer return does not establish
firmware execution. The PSP/decryption root-cause claim is unproven.

Candidate 254 is an isolated secure-DPG clock-gate correction under audit.
Native secure builder +0x9403e passes CGC_CTRL value 0x104/0x105 to CGC_GATE;
native unsecure builder and Linux write zero. Preserve all candidate-253
firmware/loading and cache-window behavior for this comparison.

Host checked: boot c369c74e-96ff-4c21-ae85-80ccb269f7d2, vfio-pci,
power/control=on; no QEMU running. No hardware result for 254 yet.
Original ~/src and candidate-253 dirty status files remain untouched.
No merge or push to main. Broad source/assumption audit is in progress.

## Candidate 254 allowance

One additional launch on boot `c369c74e-96ff-4c21-ae85-80ccb269f7d2`,
candidate 1.0.254 / metal-100, to test the source-supported CGC_GATE correction.
Authorized by the current user's request to find and fix the encoder code.
Use tools/cycle.py with fresh MODE2 reset, --manual-reuse --ack-risk,
max 6000 seconds, existing identity/capture/host-fault/cleanup aborts intact.
Stop manually after codec result or first stall. Count only after VFIO exposure.
Success requires corrected gate log, completed hardware encode output, and
separately recorded desktop probe/identity/cleanup outcomes.
