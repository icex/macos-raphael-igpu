# Native hybrid branch follow-up map (offline, 24G830)

This map now includes the hardware-confirmed hybrid-002 branch result.

TtlCreateHybridEngine 0x9876b validates all three pointers, calls
`ttlIsHwAvailable` at 0x987a2, and rejects false at 0x987ae with status 4.
It calls getSwipFromEngineType at 0x987c5; GC=7 dispatches to
ipiGcCreateHybridQueue 0xa6387; SDMA=2 dispatches to
ipiSdmaCreateHybridQueue 0xa7a27. Either child's Boolean false also gives status 4.
An unsupported SWIP asserts and returns 4. Successful child gives status 0.

The availability helper 0xafa40 tests dev+0xb0 bits 0,1,2. The direct
writer is ttlSetDeviceState 0xaf930, which replaces one bit using state index
and low-byte Boolean. Direct call sites establish:

| State index / bit | Observed direct producer | Setting / clearing call sites |
|---|---|---|
| 0 / 1 | TtlNotifySurpriseRemoval and TtlUnsetSurpriseRemoval | 0x9a75f / 0x9a7a3 |
| 1 / 2 | TtlRtsResetAdapter | 0x9975e / 0x99818 |
| 2 / 4 | TtlRtsSetPowerState | 0x99b27, argument from event path r12b |
| 3 / 8 | ipi_gvm_hw_init / ipi_psp_hw_init | not tested by availability |
| 4 / 16 | reset / PSP initialization | not tested by availability |

TtlRtsSetPowerState 0x999e8 sets state2 after TlsExecuteEventSeq; the flag
value comes from which requested event path was selected, not its success status.
Do not label every set state2 a failed power transition without decoding the request.
These are direct-call findings; they do not prove absence of indirect aliases/writes.

GC hybrid engine types 13/14 call gc+0x80 with translated queue request;
type12 has a separate graphics request path. Native callback returns integer0
success, while this outer GC child returns Boolean success. SDMA finds an instance
from request+8 and engine type, finds one of two free queue slots, and calls
instance+0x70. Its integer0 callback result is converted to Boolean success.
The native SDMA entry begins with a relative branch; do not route it without
validating displaced instruction handling. A safe caller/GC entry is preferable.

Source: local re/hwlibs.asm and re/hwlibs.nm for the SHA-pinned 24G830 HWLibs.
No register access, guest execution, state changes, or proposed force-success patch.


## Topology and next observation

Observed163: native HY types10 and11 succeed, then type10 fails. X6 SDMA init
0x6b7b2 writes its engine index to +0x1a4/+0x1ac; start 0x6ba52 forwards it for
each ring. AMDHardware::startHWEngines 0x6ffd2 iterates at least two SDMA engines.
Hardware discovery enumerates only one; see experiments/hybrid-001-163.

The current164 hook observes IpiSdmaFindInstanceByEngineIndexAndType 0xa7312
ONLY when called from 0xa7a74 (return address0xa7a79). It logs the original
index/type and returned pointer presence, context instance counts2c/30/34/38,
selected queue capacities58/5c/60, occupancy of slots30/48 and callback70.
The first16 bytes are complete position-independent instructions; the first
branch begins at+16. The result and all native input arguments are preserved.
No CPU or hardware queue writes are added; logging still affects timing.

The record proves a null selector return at the real native caller if observed.
It does not by itself prove callback success or complete Metal execution. A
successful earlier index0 lookup cannot satisfy the experiment's required index1
observation. Counts are software snapshots, not raw register probes.

Upstream reference: [Linux v6.12 IP discovery](https://github.com/torvalds/linux/blob/v6.12/drivers/gpu/drm/amd/amdgpu/amdgpu_discovery.c)
counts SDMA instances across HWIDs42/43/68/69. Its
[SDMA backend](https://github.com/torvalds/linux/blob/v6.12/drivers/gpu/drm/amd/amdgpu/sdma_v5_2.c)
uses the discovered instance count for ring setup. This pinned reference is not
the running CachyOS7.2.3 kernel; live discovery is recorded separately.

## Hardware-confirmed cause (candidate 164)

Hybrid-002 recorded SDMA type0/index0 and type1/index0 resolving against counts
`1,0,0,0`, then type0/index1 returning null before the instance callback. X6000's
Navi23 `allocateHWEngines` at 0x9977c unconditionally constructs two SDMA objects at
hardware+0x3b8 and +0x3c0. Generic `initializeHWEngines` passes array indices 1 and 2;
`AMDGFX10SDMAEngine::init` at 0x6b7b2 subtracts one and stores instance indices 0 and 1
for both ring requests. The second object is therefore the producer of the rejected
index1 request.

The native `startHWEngines` count is `2 * byte[hardware+0xc2] + 2`, so its minimum is
two and no capability-field value represents Raphael's single SDMA instance. A correct
compatibility path must remove the second object before generic initialization and use
one-engine start semantics while preserving the real first-engine result and trace bit.
Aliasing index1 onto instance0 would collide with the two handles already owned by the
first object and leave a false engine exposed to clients.
