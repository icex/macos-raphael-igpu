# Allocation diagnostic sampling — 2026-09-16

Candidate281 tried to sample one allocation-failure kprintf call: first8, then
every1024 with a cumulative count. Native allocation attempts, counters, false
returns and retry behavior stay unchanged. Global logging is untouched.

## Observed installation failure

Run b29d3de37f74516698178fda2301f9d9 boots the expected281 binary and passes its
baseline Metal probe. ALLOCLOG reports guarded=1, installed=0, original=0.
The user again reports3–4FPS; because the patch is inactive, this does not
falsify or validate the performance hypothesis.

The exact X6000 callback base is0xffffff7faa922000. Do not use kmutil's unslid
address or the later HWLibs callback base. Bounded DTrace byte reads show:

- CALL atX6000+0x53370: `e8 9f 3d 18 f4`.
- Its signed-rel32 target is0xffffff7f9eaf9114.
- Target stub: `ff 25 56 40 01 00` (RIP-relative indirect JMP).
- Slot atstub+6+0x14056 contains0xffffff801e994da0, symbolized as kernel`kprintf.

The direct-call-target equality check was too strict. Candidate282 keeps exact
prefix/tail guards and verifies either a direct logger or oneFF25 stub whose
pointer equals resolved kernel `_kprintf`. Replacement remains a five-byte CALL,
with a checked signed-rel32 destination and original call return address.
Diagnostics now report target, resolved and expected logger plus reachability.

Initial diagnostic reads failed due to an unaligned int32 load, then unslid/wrong
image addresses. The first DTrace BEGIN error had no timer; it was interrupted
through authenticated SSH. Later probes have three-second timers. Those errors
are invalid observations, not GPU faults. A later encoder timing window collected
no samples after the client disconnected; do not present it as throughput evidence.

Retina's login job exited0 but backing was1080p after startup. One manual60Hz-only
helper invocation restored1920x1080 logical/3840x2160 backing. Login durability is
still open. Sunshine was restored on the same LAN ports. Shutdown/recovery results
and the actual282 performance comparison must be recorded separately.

[Artifact hashes](allocation-log-thunk-20260916.json).

Candidate281 completed with CORE_PROBE_PASS and valid capture; guest-requested
shutdown was clean and schema6 recovery authorizes relaunch. Candidate282 host
suite:965 tests OK, three skipped. Performance fix remains untested.
