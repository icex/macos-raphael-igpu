# Candidate 203 memory-domain audit

Candidate 203 implements automatic VRAM capacity discovery from validated
GFXHUB framebuffer base/top registers and the confirmed `IOMemoryMap` length.
The shared helper rejects zero, reversed, high-bit, and overflowing bounds; it
also validates provider total/visible capacities against the raw framebuffer
and BAR-visible capacities. Native provider pool fields are preserved.

Recovery and BAR-backed diagnostics use the discovered visible capacity. Native
VMM validation uses the logical framebuffer total. Provider total/visible
selects the primary or secondary native cursor: primary ranges stay within
provider-visible memory, while secondary ranges begin at provider-visible
memory and end within provider-total memory. Prediction runs after lease
allocation and is compared with the native post-allocation range.

Offline verification passed:

- C++ recovery lease/helper, reservation, GART, and VM diagnostic fixtures.
- 32 recovery/lifetime Python tests.
- Authentic source/KDK preflight; stdout is preserved at
  `/home/bogdan/macos-vm/run/capacity-auto-offline-203d/preflight-203d.out`.
- Release artifact:
  `/home/bogdan/macos-vm/run/capacity-auto-offline-203d/RaphaelGPU-1.0.203-experimental.zip`
  with SHA-256
  `e4d79c67a5e289748244b3189e890102f3de22afeb322fe5d74229f8b67a3713`.

No QEMU or hardware run was performed for this implementation. Runtime
provider cursor behavior, guest stability, Metal submission, and desktop
acceleration remain untested and unqualified. Existing queue-retirement and
recovery quarantine remains unchanged.
