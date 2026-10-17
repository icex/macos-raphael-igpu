# Candidate 1.0.158: native EOP write is immediately invisible

The supervised VM started at 2026-09-07T20:27:09.619221962Z with its 180-second
cap and serial service verified after launcher exit. Exact container:
`654ddbaf72bf7e8ed5faee73e11e538fa1bb88d8d34114f3cf4066122a0c784e`.
Both the work session and serial service held sleep inhibitors.

XQ3 verified the native read entry and observed four matching native writes:

| Return offset | Register | Value | Immediate result through both read paths |
|---|---|---|---|
| `0x15253` | EOP low `0x322e` | `0xf40b7068` | zero before and after |
| `0x1527b` | EOP high `0x322f` | zero | zero before and after |
| `0x1533c` | EOP control `0x3230` | 6 | 6 before and after |
| `0x159e5` | HQD ACTIVE `0x320b` | 1 | zero before, 1 after |

All four calls used client `0xb`, flag 1, and the last observed native selector
write was 9 from the same context. The preceding XQ2 dequeue genuinely completed
in 50 us. HQD_ERROR was `0x100` before and after; physical PTB remained
`0x84fdfc001`. The EOP value was already invisible immediately after its write,
before activation. Neither a delayed disappearance on activation nor a difference
between the existing framebuffer and native GC read paths explains the result.
The shadow records an observed selector write, not a direct hardware identity read.

The serial kext-version line was interleaved, so the temporary readiness checker
could not validate that line. Native power-up had returned zero; a guest `kmutil
showloaded --list-only` query independently confirmed `as.rgpu.RaphaelGPU (1.0.158)`.
The prepared probe then enumerated Metal 3, compiled shaders, and failed its first
compute command with status 5 / underlying `e00002bd`. No commands, values, or
pixels completed. The exact VM was explicitly stopped before its existing cap.
Host kernel logs show VFIO resetting/reset-done and no observed lockup or GPU fault.

Mode2 now forwards native MEC halt requests during failure cleanup. This removes
the old suppression; no claim is made that cleanup alone repairs execution.

Firmware evidence: MEC LOAD_IP_FW succeeded, but AUTOLOAD_RLC returned
`0xffff000d`. The requested current TMR's MC range maps to physical
`[0x85f400000,0x85fe00000)`, which includes CPC IC `0x85f904000` at offset
`0x504000`. Unchanged IC addresses alone therefore do not prove retained host
code. The command response's firmware destination is not logged in this build.
