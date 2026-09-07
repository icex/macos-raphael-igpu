# Candidate 1.0.155: complete supervised execution capture

The container started at 2026-09-07T19:21:49.171189222Z. User-systemd supervision
was positively verified again after the launcher tool returned. Serial capture
continued through the KIQ failure and the real Metal test. The exact container
was explicitly stopped before its 180-second cap; the host remained responsive,
and the host kernel recorded only the normal VFIO reset/reset-done pair.

The Metal probe failed its first compute command with status 5 and
MTLCommandBufferErrorDomain code 1, underlying e00002bd (kIOReturnNoMemory).
There were zero completed command buffers, zero verified compute values, and
zero rendered pixels. See guest-output.txt for the complete native result.

The source candidate and boot arguments are identical to the first 1.0.155 test.
This capture establishes:

- Genuine dequeue completed in 50 microseconds; ACTIVE changed 1 to 0.
- Native startKIQ returned 0 after preparation.
- The native doorbell stayed at 32 dwords. After submission, RPTR stayed 0,
  EOP stayed 0, and HQD_ERROR was 0x100 (PQ_UTCL1_ERROR).
- HQD_ERROR was already 0x100 before dequeue, so its observation after submission
  does not prove a newly latched error.
- EOP_CONTROL 6 is intentional: native startKIQ requests 512 bytes and HWLibs
  computes log2(512/4)-1. It is not evidence of a rejected size write.
- The MC framebuffer base was 0xf400000000 from the earliest pre-TTL observation;
  the physical FB_OFFSET was 0x840000000. This run does not show a relocation.
- AMDHWMemory reserved was zero. The existing PTB repair refused that value,
  leaving the physical page-table root at 0x0fdfc001 instead of 0x84fdfc001.

The table spans BAR0 offsets [0x0fdfc000, 0x0fffe008), within the 256 MiB mapping.
The next source correction must use the physical carveout base and precede
invalidation. It does not require changing the correctly MC-based MQD/EOP
arguments or the native EOP size. See findings/GPU-RE.md for source derivation.
