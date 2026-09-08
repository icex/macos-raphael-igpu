# SDMA hybrid-engine failure and compatibility boundary

Status: hardware cause verified with candidate 1.0.164; candidate 1.0.165 repair is
implemented and validated offline, but has not yet run on the physical iGPU.

## Captured failure

Hybrid-002 recorded the following native requests after all KIQ stamps completed:

| Engine request | Global instance | Native selector | Callback status |
|---|---:|---|---|
| SDMA type 10 / queue 0 | 0 | found | 0 |
| SDMA type 11 / queue 1 | 0 | found | 0 |
| SDMA type 10 / queue 0 | 1 | not found | not called |

The selector context reported instance counts `1,0,0,0`. The failed request therefore
does not represent a resource shortage or callback error: Apple asked TTL for a second
physical SDMA instance that Raphael does not expose.

## 24G830 ABI and producer

`TtlCreateHybridEngine` receives a request whose engine type is at `+0x0` and global
SDMA instance index is at `+0x8`. `ipiSdmaCreateHybridQueue` at HWLibs `0xa7a27`
maps engine type 10 to queue type 0 and type 11 to queue type 1. Its instance selector
uses counts at context offsets `+0x2c/+0x30/+0x34/+0x38`, instance arrays at
`+0x40/+0x48/+0x50/+0x58`, a `0xd8` byte instance stride, and per-queue capacities
at instance `+0x58 + 4*queueType`. A null instance becomes Boolean false and then
status 4 at the outer API. The per-instance callback at `+0x70` is never invoked for
the captured index-1 request.

The bad index is produced in AMDRadeonX6000 rather than HWLibs:

- `AMDNavi23Hardware::allocateHWEngines` (`0x9977c`) always constructs two
  `AMDSDMAEngine_GC_10_3_4` objects at hardware offsets `+0x3b8` and `+0x3c0`.
- `AMDHardware::initializeHWEngines` (`0x6fd4e`) passes each engine-array index to
  the object's virtual `init` method.
- `AMDGFX10SDMAEngine::init` (`0x6b7b2`) reads that engine enum, subtracts one and
  stores the resulting global instance index for both queue requests at object
  offsets `+0x1a4` and `+0x1ac`.
- `AMDHardware::startHWEngines` (`0x6ffd2`) computes its SDMA loop bound as
  `2 * byte[hardware+0xc2] + 2`. Its minimum is two, so the Navi23 capability field
  cannot encode Raphael's one-instance topology.

The return contracts are low-byte Boolean for engine initialization and start.
`AMDGFX10SDMAEngine::start` (`0x6ba52`) returns its actual hybrid-creation result;
the generic start loop returns false for a null slot or a false child result and writes
progress bit `0x200` in the trace word at handler-trace offset `+8`.

Linux v6.12's pinned `amdgpu_discovery.c` independently counts the SDMA IP instances
reported by discovery and its SDMA setup loops use that count. It therefore does not
manufacture a second instance merely because the surrounding GPU family often has two.

## Candidate 1.0.165 repair

The `rgpusdma=1` compatibility gate makes one owner-level topology correction:

1. Require the original Raphael GC 10.3.6 discovery observation, all five exact X6000
   routes, and the exact `rgpu,raphael-target` OSData marker on the IOPCIDevice that also
   carries the grafted `ATY,bin_image`. `ocprop.py` couples those properties on one
   OpenCore device path; this prevents the spoofed `0x73ff` ID from selecting a real
   Navi23 object in a multi-GPU guest.
2. Before generic engine initialization, detach the object at hardware `+0x3c0` and
   release it through OSObject vtable slot `+0x28`.
3. Leave the real first object at `+0x3b8` unchanged.
4. Start that surviving object through its native virtual `start` method at `+0x148`,
   return its real Boolean result and reproduce native trace bit `0x200`.
5. Keep native generic initialization, power-up, stop, power-off and free behavior.
   Those loops already skip null slots. Apple's `AMDHardware::free` uses the same
   `release` slot and clears each engine pointer, so the removed object is neither
   leaked nor released twice.

The production gate selects the measured one-instance plan only for the Raphael target.
Experiment preparation and launch-time checks reject a missing, altered or moved target
marker. The runtime gate independently compares every marker byte and requires the VBIOS,
AMD vendor and spoofed Navi23 device ID on the same IOPCIDevice.
Counts outside the supported one-or-two-instance domain fail closed in the host-testable
topology helper, where a valid two-instance input is also proven unchanged. First-engine
failure remains failure. The repair does not alias instance 1 to instance 0, change a TTL
return, create a fake handle, touch MMIO or claim command completion.

## Falsifiable next result

Hybrid-003 predicts only type-10/index-0 and type-11/index-0 requests, both with native
status 0, followed by `AMDHardware::startHWEngines -> 1`. KIQ stamps must remain valid.
The repair passes only if the existing native probe then completes correct compute output
and rendered pixels. A different native failure becomes the next measured boundary; device
enumeration or startup alone is not Metal acceleration.

Primary evidence: `findings/experiments/hybrid-002-164/` and the SHA-pinned local 24G830
X6000/HWLibs disassembly identified in `findings/baseline-identities.json`.
