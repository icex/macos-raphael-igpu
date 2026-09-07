# Candidate 1.0.157: actual compute failure after driver initialization

Container `ef72ac9b66a1b5441d4af83de919a8b7fd3ded500d328a0b9dcc84503900ac49`
started at 2026-09-07T20:07:53.545944994Z with a verified 180-second cap and
connected systemd-owned serial capture. The test waited for confirmation of
loaded version 1.0.157 and the final `AMDGraphicsAccelerator::powerUpHW -> 0`
result; 83 seconds remained at that point.

The getter changed native physical base 0 to `0x840000000`. Native CTX0 root was
`0x84fdfc001`, and its full table fit the visible aperture. Native memory fields
were MC base `0xf400000000`, physical base `0x840000000`, and delta `0xebc0000000`.
XQ2 accepted the argument and MQD image addresses, genuinely dequeued in 50 us,
and called native startKIQ. EOP_BASE readback remained zero, EOP_CONTROL 6,
and HQD_ERROR `0x100` persisted from before dequeue. The 32-dword submission
timed out with RPTR 0 and WPTR 32.

The GART walker found valid SYSTEM/SNOOPED/READ/WRITE entries for the ring and
poll/report page. QEMU `xp` independently read those exact guest RAM pages:
the full SET_RESOURCES/padding/WRITE_DATA frame is present; the poll word is 32,
while the report and completion stamp are zero. See `qemu-kiq-ram.txt`.

The automated probe enumerated Navi23 Metal 3 and compiled its shaders. Its
first compute command failed with status 5, Metal error code 1 and underlying
`e00002bd`. Zero command buffers, computed values, or rendered pixels completed.

The exact VM was explicitly stopped after the reads, before its cap. Host
kernel logs for this interval show only VFIO resetting/reset-done; no lockup,
oops, or GPU fault was observed. The work-session sleep inhibitor remains active.

The only logged MEC halt suppression occurs after the timeout. It is not evidence
for that suppression causing the initial failure. Neither EOP zero readback nor
the unchanged HQD error alone establishes hardware lock or register access semantics.
