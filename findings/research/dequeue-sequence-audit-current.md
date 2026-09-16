# Current KIQ dequeue sequence audit

Date: 2026-09-13. Scope: read-only comparison of candidate-203 `prepareKiq`
against Linux GFX10 (GC 10.3.6 compatible) and the candidate-204 same-boot
trace. No hardware action or source change was performed.

## Evidence

The initial candidate-204 run (`71d8cd7152bced52447c8e08e477ea67`, build
`282fd1f10ab248a4ba909eebf73fb7fd`, boot
`2f77212f-34f5-4905-ba66-d8c68a860d78`, CID
`ac3e8534195c4d075a66860b1dcfd7710b0bba56170fae6ce55d0bb838518ae3`) logged:

```
before dequeue: ACTIVE=1 RPTR=0x86 WPTR=0xa0 DEQUEUE=0
after queue preparation: ACTIVE=1 RPTR=0x86 WPTR=0xa0 DEQUEUE=1
dequeue TIMEOUT after 50000 us; descriptor unchanged, startKIQ blocked
```

The later candidate-205 hardware run reached native `startKIQ` and it returned
zero. Its post-native sample was `ACTIVE=1, RPTR=0, WPTR=0xa0, EOP=0,
DEQUEUE=0`, with the expected MQD address; the first wait-stamp still failed.
This proves native entry and return, but does not prove that each native write
was accepted or that the queue was made runnable.

The source is [candidate-203 `KiqQueuePreparation.hpp`](../../../../macos-vm/run/worktrees/candidate-203/src/KiqQueuePreparation.hpp)
(`prepareQueueForNativeStart`) and its call is
[`RaphaelGPU.cpp`](../../../../macos-vm/run/worktrees/candidate-203/src/RaphaelGPU.cpp)
around `prepareKiq`.

## Ranked findings

1. **Concrete sequence difference: timeout returns before Linux's post-wait writes.**
   `prepareQueueForNativeStart` writes `CP_HQD_DEQUEUE_REQUEST=1`, polls
   `ACTIVE`, and returns `DequeueTimeout` without writing `DEQUEUE_REQUEST=0`.
   The fetched Linux `gfx_v10_0_kiq_init_register` source has no timeout branch
   that clears `CP_HQD_ACTIVE`; after the bounded loop (whether it broke because
   ACTIVE cleared or reached the limit), it writes the MQD's dequeue value
   (normally zero), restores RPTR/WPTR, then disables the doorbell and proceeds
   with the complete HQD image. This candidate's log confirms the intermediate
   hardware residue (`DEQUEUE=1`). That is a real divergence, but it is not by
   itself a proven root cause: this candidate intentionally aborts before native
   start, and the phrase “descriptor unchanged” refers to the MQD image, not
   this hardware request register. Any future cleanup must restore the request
   to zero only in a separately authorized, bounded path; this report does not
   recommend adding that write blindly.

2. **Drain semantics can explain the timeout when old queue memory is gone.**
   Linux's KFD GFX10 `kgd_hqd_destroy` maps
   `KFD_PREEMPT_TYPE_WAVEFRONT_DRAIN` to `DRAIN_PIPE` (`DEQUEUE=1`),
   `WAVEFRONT_RESET` to `RESET_WAVES` (`2`), and `WAVEFRONT_SAVE` to `SAVE_WAVES`
   (`3`), then waits for `ACTIVE=0`. A drain may need the MEC/RLC to retire
   work and touch the old MQD/ring. With `RPTR=0x86`, `WPTR=0xa0` and a prior
   guest/QEMU lifecycle, waiting for drain can therefore remain stuck if the
   old ring or its translation is no longer usable. This is a plausible root
   cause, not proven causality. Linux's KIQ initialization itself uses drain
   (`1`), so replacing it with `2` is not an upstream-equivalent KIQ-start
   fix; wave reset requires proof of the selected queue, RLC state, and impact
   on in-flight work.

3. **The pre-start helper does not establish the Linux KIQ scheduler contract.**
   Linux `gfx_v10_0_kiq_setting` writes `RLC_CP_SCHEDULERS` with the selected
   ME/pipe/queue and enable bit `0x80`; its `gfx_v10_0_kiq_init_register`
   then programs the complete HQD image (EOP, MQD, PQ, report/poll addresses,
   doorbell, VMID, persistent state, and finally ACTIVE). Candidate code only
   edits the MQD image and performs queue ingress/dequeue checks before calling
   Apple's native `startKIQ`. Native code may perform these operations, but
   this run never reached that call, so the scheduler marker and full image
   remain unverified. Do not add an RLC scheduler write or manually activate a
   queue without a measured native-vs-Linux state diff.

The primary local Linux source is
`/home/bogdan/macos-vm/run/research/metal-integration-20260909/cache/linux-stable-v7.2.3/drivers/gpu/drm/amd/amdgpu/gfx_v10_0.c`, SHA-256
`39de93ff6255423855ad3434d415d867b55dc0c0c268410fba3950af9355a473`.
The exact excerpt is lines 7047–7069: request `1`, poll ACTIVE, then restore
dequeue/RPTR/WPTR and disable the doorbell. For a current upstream URL, the
same file was fetched at commit
[`2f0c1cf72f4682178506f513bbf015e591b1aa4a`](https://github.com/torvalds/linux/blob/2f0c1cf72f4682178506f513bbf015e591b1aa4a/drivers/gpu/drm/amd/amdgpu/gfx_v10_0.c).
The KFD enum mapping was checked in the fetched upstream
[`amdgpu_amdkfd_gfx_v10.c`](https://github.com/torvalds/linux/blob/2f0c1cf72f4682178506f513bbf015e591b1aa4a/drivers/gpu/drm/amd/amdgpu/amdgpu_amdkfd_gfx_v10.c):
`DRAIN_PIPE=1`, `RESET_WAVES=2`, `SAVE_WAVES=3`, and `kgd_hqd_destroy` selects
that value before polling ACTIVE. The register masks match GC10.3: poll enable
is bit 31, doorbell enable bit 30, and dequeue request is field bits 0..3.

## What a debugger can measure next

At the authenticated `startKIQ` boundary, capture a timestamped per-write/read
trace for: `CP_PQ_WPTR_POLL_CNTL`, `CP_HQD_PQ_DOORBELL_CONTROL`,
`CP_HQD_DEQUEUE_REQUEST` plus `CP_HQD_DEQUEUE_STATUS`, `CP_HQD_ACTIVE`,
`CP_HQD_ERROR`, `CP_HQD_PQ_RPTR/WPTR`, `CP_HQD_PQ_BASE`, `CP_MQD_BASE_ADDR`,
EOP registers, `RLC_CP_SCHEDULERS`, `CP_CPC_STATUS`, MEC instruction pointers,
and `CP_HQD_IQ_TIMER`. Also inspect the old ring/MQD physical addresses and
VM fault status while mappings are still valid. This can distinguish a pending
drain, an unserviced dequeue request, and a scheduler/MEC-not-running state.

The minimum discriminating observation is whether `DEQUEUE_STATUS` shows a
pending IQ request and whether `ACTIVE` changes when the request is `1`; the
next is whether a controlled, separately authorized `2` request clears the
same selected HQD. A timeout must remain non-authorizing. No recommendation is
made here to force `ACTIVE=0`, issue `DEQUEUE=2`, write RLC scheduler state, or
reboot/reset; each changes firmware/queue state and is unsafe without those
measurements and the existing recovery gates.

## Native-call boundary and fallback comparison

The Apple X6000 path is `AMDGFX10KIQHWChannel::startKIQ` at X6000 offset
`0x8e670`; it dispatches the TTL virtual command at `0x8e706`. Its GC helper
`_gc_create_kiq_queue_10_3` is the HWLibs queue setup routine that candidate
comments identify as the source of the active wait. The earlier pre-start gate
blocked that call; candidate 205 reached it and returned zero. The post-native
sample above establishes the boundary, but not successful execution or
readback acceptance of each native register write.

For the Linux-equivalent sequence, the next writes after the active wait are,
in order: `CP_HQD_DEQUEUE_REQUEST = mqd->cp_hqd_dequeue_request` (normally 0),
`CP_HQD_PQ_RPTR = mqd->cp_hqd_pq_rptr`, `CP_HQD_PQ_WPTR_LO/HI` from the MQD,
then `CP_HQD_PQ_DOORBELL_CONTROL = 0`; EOP/MQD/PQ base and control/report/poll
registers follow, with ACTIVE written only at the end. The exact local excerpt
is `gfx_v10_0.c:7052–7069` in the source and SHA recorded above. This sequence
does not prove that Apple's binary has identical writes, only what must be
captured at a reached native call.

There are two distinct fallbacks in the candidate and they must not be conflated:

* `wrapGcCheckRegEq` has a candidate-only active fallback that writes
  `CP_HQD_ACTIVE=0` after 64 predicate polls. It is explicitly disabled for
  `mqdFixMode == 2` (`if (isHqd && mqdFixMode == 2) return r`), so mode 2 does
  not permit this forced-active clear. The log text calling this “upstream's
  manual disable” is inaccurate for the fetched `gfx_v10_0_kiq_init_register`
  branch; Linux does not clear ACTIVE there on timeout. The Linux per-queue
  reset helper is a different function: it enters RLC safe mode and uses
  `DEQUEUE=2` plus `SPI_COMPUTE_QUEUE_RESET=1`.
* `prepareQueueForNativeStart` is the mode-2 pre-start gate. A failed drain
  prevents native queue reprogramming entirely, whereas Linux's init routine
  proceeds to overwrite the HQD after its bounded wait. That is a deliberate
  safety choice, but it means mode 2 cannot test whether full MQD/HQD
  reprogramming would recover a stale active queue. It should remain a
  hypothesis boundary, not be labeled a demonstrated cause.

The smallest useful experiment is therefore diagnostic first: reach a native
`startKIQ` only with a verified isolated MQD/EOP image and a separate explicit
mode that records every native GC write, including the request restoration and
whether native proceeds after an active timeout. Do not reuse the candidate-only
forced ACTIVE clear for mode 2. If an experimental “native restore” mode is
ever designed, its admission predicate must verify MQD/ring physical addresses,
VM translation and mapping lifetime, selector identity, and a reserved EOP
buffer before allowing the post-wait writes; timeout must still produce a
non-authorizing result. No implementation is proposed by this audit.

## Direct HWLibs disassembly (important correction)

`0x8e670` is the X6000 `AMDGFX10KIQHWChannel::startKIQ` entry in
`/home/bogdan/macos-vm/re/x6000.asm`, not a HWLibs entry. The X6000 method
dispatches the TTL virtual command at `0x8e706`; the candidate-204 GDB run
confirmed its wrapper returns `0xe00002bc` before the native call, so this
method has still not been observed in the current failure.

The actual GC HWLibs implementation is
`/home/bogdan/macos-vm/re/hwlibs.asm`, `_gc_create_kiq_queue_10_3` at
`0x14fb0`. Its active branch is unambiguous:

```
1540f..15433  read CP_HQD_ACTIVE (0x1fab); if bit 0 set, write DEQUEUE=1
15438..15478  wait for (ACTIVE & 1)==0, timeout argument 0x1f4 (500 ms)
1547d..154a1  on timeout, call _gc_assertion("Timed out on dequeue request!")
154a6..154c7  write DEQUEUE=0 unconditionally (success or timeout)
154cc..15539  write RPTR (0x1fb3)=0, WPTR_LO (0x1fdf)=0, WPTR_HI (0x1fe0)=0
```

It then continues with normal EOP/base/control/HQD programming. Thus the
candidate's 50 ms preflight is shorter than Apple's 500 ms wait, and, more
significantly, converts Apple's “assert then restore and reprogram” path into
“return error before native call.” This is the concrete mechanism by which the
mode-2 guard can prevent the only known native recovery sequence from running.
It remains unsafe to copy that sequence blindly: Apple asserts on timeout and
continues despite potentially stale queue state, while a forced restore can
make the GPU touch invalid guest addresses. The first safe experiment is a
mode that only records native writes after a separately verified isolated
MQD/ring mapping; it must retain a non-authorizing result on timeout.

The candidate-only `wrapGcCheckRegEq` active fallback is distinct from this
HWLibs path. It writes `CP_HQD_ACTIVE=0` after 64 predicate polls, but mode 2
explicitly bypasses it. The disassembly shows that HWLibs itself does not
write ACTIVE=0 in `_gc_create_kiq_queue_10_3`; it restores DEQUEUE/RPTR/WPTR
and proceeds after reporting the timeout.

## Recovery pool absence

The `recovery_lease_pool_missing` verdict after candidate-204 is expected from
the observed control flow, not evidence that pool publication raced or was
merely omitted by instrumentation. In `RaphaelGPU.cpp`,
`publishRecoveryPoolStatus` is called only by `wrapHwMemEnable` after
`establishPools` has obtained the real memory object, discovered pool
pointers/sizes, performed the native reserve, and validated ownership. The KIQ
preflight returned before native `startKIQ` and before the later allocation
path reached `wrapHwMemEnable`; no exact pool geometry existed that could be
truthfully published as ACTIVE.

Publishing an ACTIVE pool earlier would weaken the lease invariant: it would
claim reserved, owner-bound pool ranges before `enableAllocations` and the
native reserve/readbacks had succeeded. A narrow instrumentation improvement
could emit an explicit “pool publication not reached: KIQ preflight failed”
diagnostic, but must not synthesize an ACTIVE record. The existing refusal is
therefore the correct safety behavior; the missing pool is a consequence of
the early KIQ return and should remain a distinct invalid/incomplete run
outcome.

The bounded cleanup consequence is narrower: an OWNED lease marker alone is
useful for identifying the exact launch, but it is not sufficient authority for
the schema-3 host-KIQ path. Schema-3 authentication deliberately requires the
committed ACTIVE pool record and lifetime marker, because host scratch/MQD/EOP
addresses must be proven inside the reserved ranges. If KIQ fails before
`wrapHwMemEnable`, cleanup may retain the OWNED evidence and perform only the
existing non-mutating identity/state checks; it must refuse scratch writes or
host-KIQ recovery when the pool record is absent. A future harness diagnostic
can record this prerequisite failure explicitly, but should not promote OWNED
to ACTIVE or publish guessed pool geometry.

## GFX10 per-queue reset applicability

The fetched `gfx_v10_0_kiq_reset_hw_queue` at lines 3821--3874 is a KIQ-issued
reset of a target queue. For a compute target it enters RLC safe mode, takes
the SRBM mutex, selects the supplied ME/pipe/queue, writes
`CP_HQD_DEQUEUE_REQUEST=2` and `SPI_COMPUTE_QUEUE_RESET=1`, waits for
`CP_HQD_ACTIVE=0`, restores selector zero, and exits safe mode. Normal GFX10
KIQ initialization at lines 7037--7069 uses `DEQUEUE=1` and does not invoke
this helper. The same source advertises per-queue reset support for compute and
graphics rings only when not SR-IOV and ring reset is enabled (around lines
4960--4964); that does not establish that resetting the KIQ itself is safe in
this warm-guest case.

Thus `RESET_WAVES`/`DEQUEUE=2` is a separate per-queue reset operation, not the
missing tail of KIQ creation. Applying it to a presumed MEC/pipe/queue tuple
requires measured queue identity and RLC-safe-mode capability; this audit finds
no basis to issue it to the KIQ. The next discriminating observation is native
write tracing at the HWLibs calls for dequeue, RPTR, WPTR-LO/HI, EOP and MQD,
plus readback of `CP_HQD_ERROR`, `CP_HQD_DEQUEUE_STATUS`, and `CP_HQD_ACTIVE`.
Existing tracing filters native callers and does not cover all pointer writes,
so `WPTR=0xa0` and `EOP=0` alone cannot distinguish stale state from a rejected
write.

## Native setup while MEC is halted

The complete `_gc_create_kiq_queue_10_3` body (`/home/bogdan/macos-vm/re/hwlibs.asm:14fb0--15a73`)
contains no direct `CP_MEC_CNTL` or `CP_ME_CNTL` write and no MEC-running wait
when the initial `CP_HQD_ACTIVE` read is already zero. The only bounded wait is
the `gc_cos_wait_for` ACTIVE-clear at `15438--15478`, reached only after an
initial ACTIVE bit of one. The body does call register-offset, assertion,
read-register and write-register helpers, so those helper effects still need
to remain instrumented.

With initial ACTIVE zero, the native write set is: GRBM selector construction
(`GRBM_GFX_CNTL` at `1514e`), EOP base low/high/control (`1524e`, `15276`,
`15337`), HQD control fields (`1538b`, `153df`, `155a3`, `155cc`, `15623`,
`15688`, `156b0`, `15738`, `1579a`, `15890`, `158bf`, `15936`), MQD base and
control (`1595b`, `159b7`), PQ base low/high (`15688`, `156b0`), report/poll
addresses (`1579a`, `157c9`, `15890`, `158bf`), and ACTIVE=1 (`159e0`), followed
by selector zero (`15a06`). The active-only branch additionally writes
DEQUEUE=1, waits, then DEQUEUE=0/RPTR=0/WPTR-HI=0/WPTR-LO=0
(`15433`, `15478`, `154c7`, `154ed`, `15513`, `15539`).

This makes a halt-MEC/native-program experiment technically plausible: native
setup itself has no observed MEC-unhalt operation, and the prior host-KIQ
recovery already programs HQD/EOP while halted. It remains conditional on exact
descriptor/mapping ownership and native callback read/write tracing; native
assertion/helper behavior and the final ACTIVE=1 write must be read back before
releasing MEC. A successful ACTIVE readback still proves software state only,
not queue execution or retirement.

## MEC topology and KIQ selector

Linux GFX10.3.6 (`gfx_v10_0.c:4775--4788`) configures two MECs, four pipes per
MEC, and four queues per pipe. The current upstream `amdgpu_gfx_kiq_acquire`
selection code explicitly requires queue 0 and skips pipes 2/3 on MEC 2 because
those pipes have caused problems; it then stores `ring->me = mec + 1`,
`ring->pipe = pipe`, and `ring->queue = queue` ([`amdgpu_gfx.c`, lines
2630--2670](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/amd/amdgpu/amdgpu_gfx.c)).
Apple's forced `ME=2, pipe=1, queue=0` is therefore the Linux-compatible
preferred coordinate, not evidence of an unsupported MEC2 selector. The
observed MEC2 pipe1/3 and even-queue aliases show a hardware/readback routing
property, but do not by themselves identify the KIQ as the wrong queue.

The topology result narrows the next check: capture the native selector write
and selected `CP_HQD_MQD_BASE_ADDR`/`CP_HQD_PQ_BASE` under exactly `2/1/0`, then
compare each alias only as a diagnostic. Do not retarget the KIQ to MEC1 or
another pipe based on aliasing alone.

## Existing forced-inactive recovery boundary

The repository's prior candidate-204 recovery does have an evidenced software
deactivation path, but it is a containment fallback. `quiesce_gc()` first
disables write-pointer polling, requests `DEQUEUE=1` for every active HQD, and
rescans. Only after stuck queues are identified does it halt SDMA/ME/MEC,
disable global and per-queue ingress, and write `CP_HQD_ACTIVE=0`,
`DEQUEUE=0`, RPTR=0 and WPTR=0 for each stuck selector, with readback. The
exact source is `tools/vfio-recover.py:2415--2688`. The candidate-204 receipt
records `dequeue_timeouts=8`, `forced_inactive=8`, while
`gfx_retirement_confirmed=false`; the final inactive readback therefore proves
register containment only, not firmware retirement or safe DMA quiescence.

This gives a concrete mechanism for a narrowly experimental pre-native path,
but its prerequisites are materially stronger than the current mode-2 timeout
predicate: authenticated ownership and live mappings for every native MQD/PQ/EOP
address, disabled ingress, halted command processors, exact selector identity,
and a separate non-authorizing result whenever firmware dequeue did not retire.
Calling native HQD programming after merely writing `ACTIVE=0` while MEC remains
live would not reproduce this safe order and could make native code touch stale
guest memory. The existing recovery result supports testing the mechanism only
as an explicitly opt-in experiment; it does not endorse automatic pre-native
`ACTIVE=0`, and Linux's normal KIQ init does not treat that write as proof of
retirement.

The repository provides one narrower ordering fact: `retire_legacy_gfx_with_host_kiq()`
halts both MECs before populating its independently authenticated BAR-backed
ring, MQD and EOP, writes the HQD image while halted, enables the host queue,
and only afterward releases MEC2. This demonstrates that direct HQD/EOP
programming can occur while MEC is halted, but does not demonstrate that
Apple's native `startKIQ` is safe to call in that state; native CP/MEC halt
writes and waits must first be captured. Any proposed experiment would need to
save MEC control, close polling/doorbell ingress, halt MECs, perform exact
selector/descriptor/lifetime checks, clear and read back the selected HQD, call
native under a non-authorizing transaction, and restore MEC control only after
native writes are traced. It must not use the old global CP surgery or infer
retirement from `ACTIVE=0`.

## Selector side-effect audit of the native callback

In candidate-203, the reachable `wrapGcCgsWrite2` chain does not write
`GRBM_GFX_CNTL` while `_gc_create_kiq_queue_10_3` is calling it. It calls
`beginNativeKiqTrace`; eligible trace points call `traceNativeKiqState`, whose
`fbRead` and native read callback are read-only. The original GC write then
executes, `noteSelectorWrite` updates only shadow variables, and the CPC-stall
diagnostic also uses `fbRead` only. The mode-2 path forwards native halt and
dequeue writes unchanged. No function in this callback chain calls
`fbWrite(..., kGcGrbmGfxCntl, ...)`, so there is no source evidence that the
diagnostic hook changes the selector mid-native-call.

Selector writes occur in the caller after native return: `wrapKiqStart` selects
the KIQ before `reportKiqPreparation`, clears selector zero afterward, and only
then optionally calls `dumpMecQueues`; that dump walks selectors and restores
zero at its end. Thus the second-run `WPTR=0x20`/previous-submit and `EOP=0`
samples cannot be attributed to a mid-native diagnostic selector reset. The
remaining instrumentation gap is coverage: `beginNativeKiqTrace` admits only
four native return addresses (EOP low/high/control and ACTIVE), so dequeue,
RPTR, WPTR low/high, MQD and selector writes are not individually logged or
read back. A native write can therefore have returned success while hardware
retained the observed value.

The `WPTR=0x20` observation belongs to candidate 205, not the unexercised
candidate-206 halted transaction. Candidate 206 was refused by its halt helper
because the hardware WPTR remained nonzero; no candidate-206 native post-state
exists. In X6000 `submitKIQFrame` (`x6+0x5c716`), `commitBlock(0x20)` updates the
command-ring software write position at command-ring offsets `+0x54` (wrapped
write position) and `+0x58` (committed count), then the ring vtable call at
`0x5c748` publishes the hardware write pointer/doorbell before
`waitForHwStamp` at `0x5c75a`. Any future retained-WPTR experiment must compare
those software fields, the CPU-written 32-dword frame and the hardware WPTR;
`0x20` must not be treated as a universal reset value.

The MEC halt register for the proposed transaction is the GC10.3 variant
`CP_MEC_CNTL_Sienna_Cichlid`, offset `0x0f55`, `BASE_IDX=0`; this is exactly
the candidate constant `kGcSeg0 + 0x0f55` (`kGcCpMecCntl`). Linux selects this
variant for GC IP 10.3.0--10.3.7 in `gfx_v10_0.c:6624--6647`, writing the two
halt bits `MEC_ME1_HALT | MEC_ME2_HALT`. It is not the generic offset from
another generation. The transaction must save/read back this variant and
preserve unrelated bits. No additional global `CP_PQ_STATUS` or doorbell-range
gate is required; the existing queue-local WPTR-poll and HQD-doorbell closure
remain the ingress controls under review.
### Exact KIQ ring publication path (X6000 static disassembly)

The KIQ ring is an `AMDGFX10ComputeRing` allocated by `PM4Engine::allocateAndInitHWChannels` (`x6000.asm:689c0–689e5`), whose vptr is installed by the `AMDGFX10ComputeRing` constructor (`61054–61074`).  The virtual call at `submitKIQFrame` `0x5c748` (`[ring->vptr + 0x158]`) resolves through that vtable to `AMDRTRing::submit` at `0x5fa4e`, not to an HWLibs routine.  `submit` compares the bounded software tail at `ring+0x54` with the last-published tail at `ring+0xd8`; when changed, it calls the ring vtable `+0x1c0`, executes `sfence` (`0x5fa71–0x5fa77`), then calls vtable `+0x178` (`0x5fa7d–0x5fa85`) and records `+0x54` into `+0xd8`.  Thus the publication fence is explicit in this path, after frame stores and before tail publication.

The ring field units are distinct: `+0x30` is capacity in dwords; `+0x54` is the modulo software tail in dwords (`getRingBlock` multiplies it by four at `0x3339e`); `+0x58` is a cumulative dword count. `writeData`/`commitBlock` add raw dword counts to `+0x58` (`0x33306`, `0x333b0`), so describing `+0x58` as bytes is incorrect. `AMDRTRing::writeTail` (`0x5f996`) shifts the cumulative dword count by the ring's `+0xa0` unit shift before writing the KIQ writeback/doorbell destinations (`+0xc8` and `+0xc0` on its KIQ flag branch). The hardware publication input selected by `AMDRTRing::submit` is therefore the current `+0x54` tail, while the actual writeback value is derived from cumulative `+0x58`; they must not be conflated.

`getKIQFrame` (`0x5c788–0x5c7cf`) reserves 0x20 dwords and initializes every one of the 32 dwords through the channel vtable `+0x1f0`. `submitSetResourcesPacket` then overwrites the packet fields, calls channel vtable `+0x328` (`0x8e3ec–0x8e458`) to copy/write the completed frame, and only then enters `submitKIQFrame`: `ring->commitBlock(0x20)` (`0x5c73a–0x5c743`), virtual ring `submit` (`0x5c748`), then `waitForHwStamp` (`0x5c75a`). A deferred-MEC release must therefore stay held through `getKIQFrame`, packet fill, `+0x328`, `commitBlock`, and the `+0x158` call; releasing after native start but before this sequence leaves the retained old tail (`candidate-205 WPTR 0x20`) fetchable. Candidate-206 never reached native, so it has no post-native WPTR measurement.

The concrete vtable `+0x328` target for `AMDGFX10KIQHWChannel` is `writeDataCmdPacket` at `0x8e62a` (constructor vptr address-point `0x1825c8`, slot `0x1828f0`). It writes at `frame+0x40`: dword 16 `0xc0033700`, dword 17 `0x00100500`, dwords 18/19 stamp destination low/high (`channel+0xc8 & ~3`, `channel+0xcc`), and dword 20 from `getCommandSubmitTimestamp` (`0x4c26c`), which returns `channel+0x80+1`. SET_RESOURCES starts dword 0 `0xc006a000`, dword 1 `0x0028ffff`; dword 2 is initialized to `0xffffffff` and is conditionally replaced by the queue-type rotation; dword 3 remains zero. `getKIQFrame` initializes all 32 dwords first; `submitKIQFrame` then increments `+0x80`, so an initially zero channel produces stamp 1. Validate these fields and destination against captured channel state, without imposing guessed equality on every dword.
