# Hybrid experiment 002 — 2026-09-08

**Result: the native failure is the nonexistent second SDMA instance. Full Metal is
still unavailable.** This was a valid diagnostic experiment using source `f2dd1f2`,
candidate 1.0.164 build `79e17c018d744550bc435f2789174dde`, and host boot
`6249bbf8-5f73-484f-80a8-7f224467beb8`. The immutable manifest binds the source,
executable, KDK, ESP, configuration, QEMU image, guest build and probe.

The guest loaded the exact build and both diagnostic entry guards matched. KIQ
submissions completed and `powerUpHWEngines` returned true. The critical sequence then
recorded the native SDMA lookup inputs and result:

| Request | Native lookup | Result |
|---|---|---|
| engine type 10, global index 0, queue type 0 | counts `1,0,0,0`; instance found; capacity `1,1` | hybrid status 0 |
| engine type 11, global index 0, queue type 1 | counts `1,0,0,0`; instance found; capacity `1,1` | hybrid status 0 |
| engine type 10, global index 1, queue type 0 | counts `1,0,0,0`; no instance | hybrid status 4 |

`_IpiSdmaFindInstanceByEngineIndexAndType` walks the discovered instance arrays and
decrements the global index by each instance's capacity. With one discovered SDMA0
instance and capacity one for queue types 0 and 1, index 1 cannot resolve. The callback
is never reached. X6000's Navi23 `allocateHWEngines` at `0x9977c` nevertheless constructs
two SDMA objects at hardware offsets `0x3b8` and `0x3c0`. Generic
`initializeHWEngines` assigns array indices 1 and 2; `AMDGFX10SDMAEngine::init` converts
those to SDMA instance indices 0 and 1. The second object therefore produces the failing
request. This is a topology mismatch, not availability, timing, KIQ or an SDMA callback
failure.

All 25 critical records were captured with `dropped=0` and `truncated=0`. The Metal
probe was correctly skipped because native startup failed. There are still zero verified
Metal compute or render completions.

The root guest agent requested shutdown using the live build and guest boot UUID. The
exact container exited without fallback (`exited-after-guest-request`). Serial captured
APFS unmounts, `CPU halted`, `Shutdown!` and `systemWillShutdown`, with no nested panic.
The host retained the same boot ID, watchdogs and sleep inhibitor, and no matching host
fault was captured. This proves one orderly guest exit, but does not yet prove complete
GPU driver teardown or safe warm reuse; this boot must not be used for another GPU run.

**Next:** remove the second Navi23 SDMA object before generic engine initialization and
start only the surviving SDMA engine under a separate guarded boot argument. Preserve
the native first-engine return and driver-state progress bit. Do not alias instance 1 to
instance 0, fabricate a second discovery entry, or force a successful hybrid return.
Instrument native stop/power-off returns in the same candidate so the next distinct run
also tests teardown ordering.
