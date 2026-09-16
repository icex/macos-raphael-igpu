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

## Candidate282 active patch and4K checks

Run560b1d7e8fea56b2c6f52fd7644d23f8, MODE2#175, exposure32, build
7a26b1a2f6694ae88ed889105de30bc7. ALLOCLOG guarded=1 installed=1,
resolved=expected=kernel kprintf; sampled cumulative messages execute. Baseline
Metal probe completes; live capture continues and final shutdown/recovery is pending.

Two independent4K HEVC generated-pattern encode/decode checks pass:24 then60 unique
frames,196,911,000 and492,277,500 checked luma samples; maximum error2 against limit8.
Both encoder and decoder report hardware=true. Encoding including CPU pattern
production and flush takes0.642473s for24frames and1.565685s for60frames. These
are not Sunshine capture/stream benchmarks, and bitrate/content differ.

During the second test, native failed allocation calls in the encoder service
average2007us/49=40.96us (max114us); WindowServer3052us/51=59.84us (max1593us).
Earlier active Sunshine traces averaged~1.9ms. This supports reduced logging cost,
but different workloads and instrumentation prevent an exact streaming speedup claim.
One attempted stream timing window had no connected client and no samples.
Actual Moonlight performance remains awaiting an active same-settings comparison.
