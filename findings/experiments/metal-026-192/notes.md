# Candidate 192 / metal-026 evidence note

The immutable run directory is
`/home/bogdan/macos-vm/run/metal-026-192`, run ID
`575d67d557b07f98b186c0cfb024fcbd`, supervised CID
`91a0836c3827fc755f040c1f1deacc8462f4951d6670e6292fe70ea2f323908e`.

The checked verdict is `EXECUTION_FAILED` at `first_submission`. The unchanged
native Metal probe enumerated `AMD Radeon Navi23` with Metal 3, compiled its
shaders, committed, and timed out after five seconds with zero completed command
buffers, zero compute rounds, and zero readback pixels.

CR2 reached a valid terminal snapshot with 306 records and no corruption. The
generic fault group identified VMID 11, status `0xb0093b`, fault VA
`0x400300000`, and a stable worker-time root of `0xf40b709000` (raw MC-domain
looking value). The diagnostic software walk normalizes the root to the
physical `0x84b709000`; the relative walk shows a physical child table
`0x84b763000` whose level-0 PTE is zero, and the absolute walk shows the
corresponding level-1 entry as zero. These are worker-time observations after
the fault latch and do not prove fault-time root or child causality.

Recovery is incomplete and `authorizes_launch=false`. The recovery KIQ evidence
matches candidate 191: graphics KIQ `rptr=0`, report `0`, fence `0`, and
`wptr=256`; graphics retirement did not pass the final gate. No retry, debugger
attach, reset, rebind, or additional launch occurred.

Key SHA-256 identities:

- verdict: `307a429cd7fc6719b6284f5197b52e27542aea212409ac57dde01335c3bb7cd9`
- probe: `d3c686614989146fee69029a0a6e2901da0f0a79e9b05debdfe2c1bc6bc146ef`
- critical capture: `6cf7082b8f64ecdc0147eb9237f256dbade07843ebb72037a4098696c001cc66`
- recovery replay: `175cac21a8c3a8f65d0bf81ab265ab99bf7b33d55123011f011c1d44355a918b`
- recovery: `045f6daa72ca21d9c27161f6d908eb3a0d621f5122c961317e1748a5bfb0a4f6`
- host-after: `2be691de8bcc95bf658d8e2997f4b839c567e33f68f7bea21d5fc6e06749a203`
