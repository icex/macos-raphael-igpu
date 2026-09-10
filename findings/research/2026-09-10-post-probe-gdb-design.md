# Post-probe GDB lifecycle limitation and qualification design

This is an unimplemented design. It is not qualified and must not change or
delay candidate 191.

## Verified current limitation

The coordinator reserves the probe plus cleanup interval in
`tools/experiment.py:2382-2384`. The probe itself blocks for as long as 50
seconds (`2547-2560`). When readiness permits it, `run_one` calls the probe at
`2819-2821`, immediately leaves the observation loop at `2822`, and calls guest
shutdown with a 20-second grace at `2830-2831`. The probe result is not
published as `probe.json` until after shutdown and capture collection at
`2894-2899`.

Therefore an external process cannot learn an actual probe failure from the
frozen output before shutdown begins. Attaching concurrently would race guest
shutdown and could stop a guest that still owns DMA mappings. The current GDB
runner cannot supply the missing lifecycle: it reserves 25 seconds for cleanup
and refuses to start with less than 10 seconds of capture time
(`tools/run-bounded-gdb.py:98-101`), while its VMID1 initialization breakpoint
may already have passed. No safe bounded post-failure GDB capture is available
in the current coordinator.

## Proposed GPU-less qualification

A future, separately reviewed protocol could:

1. After an authenticated probe failure, atomically publish a write-once record
   binding the probe result, run ID, exact supervised CID, manifest hash, and
   current deadline.
2. Enter the follow-up state only when a fixed debugger budget still leaves at
   least the existing 25-second cleanup reserve. Otherwise proceed directly to
   shutdown.
3. Require the runner to validate that record, CID, running identity, serial
   readiness identity, and deadline before attaching. It must target a
   deliberately repeatable CPU-only test boundary; an initialization breakpoint
   that may have passed is not a valid qualification target.
4. Require bounded detach and a write-once, CID-bound completion result. The
   coordinator waits only for that result or the fixed debugger deadline, then
   performs the normal shutdown. Attach failure, timeout, malformed identity,
   or failed detach is a capture failure and never authorizes extending the
   exposure or cleanup deadlines.
5. Exercise success, target-not-hit, attach failure, detach failure, timeout,
   and shutdown paths without a passed-through GPU. A later GPU failure would
   still need a repeatable post-failure driver boundary derived from the actual
   failure before this protocol could collect useful driver state.

Offline tests alone would validate ordering, identity binding, and failure
semantics. A GPU-less VM qualification would be required to demonstrate the
real attach/detach/shutdown lifecycle. Neither has been implemented or run.
