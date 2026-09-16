# Linux AMDGPU teardown findings for Raphael / GC 10.3.6

Date: 2026-09-13
Scope: read-only source comparison for candidate 203 recovery

## Sources and exact upstream behavior

The source pin used below is the latest commit touching each file when this
research was performed. The links are immutable GitHub blob URLs, so the line
references remain reviewable:

* [`gfx_v10_0.c` at `a04c0c7e416490ee97af3b7768e6f21268fde54a`](https://github.com/torvalds/linux/blob/a04c0c7e416490ee97af3b7768e6f21268fde54a/drivers/gpu/drm/amd/amdgpu/gfx_v10_0.c)
* [`amdgpu_gfx.c` at `e9e0bd23b55aec41f45d46007cb3cb38d40f552b`](https://github.com/torvalds/linux/blob/e9e0bd23b55aec41f45d46007cb3cb38d40f552b/drivers/gpu/drm/amd/amdgpu/amdgpu_gfx.c)

For GC v10, `gfx_v10_0_hw_fini()` (`gfx_v10_0.c`, around lines 7564-7602)
first cancels GFX idle work and drops GFX IRQ references. While hardware access
is available, it calls `amdgpu_gfx_disable_kgq(adev, 0)` when asynchronous GFX
rings are enabled, then always calls `amdgpu_gfx_disable_kcq(adev, 0)`. It then
disables the GFX CP (`gfx_v10_0_cp_enable(..., false)`) and GUI-idle interrupt.
The function logs queue-disable errors but does not turn a failed queue disable
into proof of retirement.

`amdgpu_gfx_disable_kcq()` (`amdgpu_gfx.c`, around lines 581-628) allocates one
KIQ packet region per compute ring, emits `kiq_unmap_queues(..., RESET_QUEUES,
0, 0)`, commits the KIQ ring, and runs `amdgpu_ring_test_helper()`. The helper
is the completion check for the submitted KIQ work. `amdgpu_gfx_disable_kgq()`
(`amdgpu_gfx.c`, around lines 630-679) does the same for GFX rings, using
`PREEMPT_QUEUES`. Both routines require a ready KIQ scheduler and a valid
`kiq_unmap_queues` implementation; otherwise they return an error or no-op
during reset.

The v10 packet builder `gfx10_kiq_unmap_queues()` (`gfx_v10_0.c`, around lines
3766-3785) emits `PACKET3_UNMAP_QUEUES` with queue selection 0 and one queue.
It sets engine selection to 4 for a GFX ring and 0 for a compute ring, supplies
the ring's doorbell index, and writes zero address/sequence operands for
`RESET_QUEUES` and ordinary `PREEMPT_QUEUES`. Only
`PREEMPT_QUEUES_NO_UNMAP` carries a GPU address and sequence. Thus the ordinary
shutdown actions request firmware/scheduler queue removal; they are not merely
MMIO writes to `CP_HQD_ACTIVE`.

The v10 reset path reinforces the required ordering. `gfx_v10_0_reset_kcq()`
submits `RESET_QUEUES`, tests the KIQ ring, enters RLC safe mode, selects the
target ME/pipe/queue, and polls `CP_HQD_ACTIVE` until it clears (up to
`adev->usec_timeout`) before reinitializing the queue. A timeout is reported as
failure. This is the closest upstream analogue to a per-HQD retirement proof.

## Comparison with candidate 203 recovery

`tools/vfio-recover.py:2413+` currently walks all ME/pipe/queue selectors,
issues `CP_HQD_DEQUEUE=1`, and waits 50 ms per active HQD. It then rescans for
queues that appeared active. It correctly gives firmware dequeue the first
chance while MECs are running, disables global doorbell/write-pointer ingress,
halts SDMA and both CPs, and only afterward clears legacy GFX ring state. The
code comment correctly says that stale ring readbacks after unmap cannot prove
that the scheduler mapping was retired.

The nq2 receipt records 9 active HQDs, 1 dequeued, 8 dequeue timeouts, and
`host_kiq.status=blocked-active-hqd` for selectors 8, 10, 520, 522, 1032,
1034, 1544, and 1546. It later records `forced_inactive=8` and
`gfx_retirement_confirmed=false`. The final inactive register snapshot is
therefore evidence that ingress/visible state was cleared after CP halt; it is
not evidence that firmware retired the eight queues. The receipt's
`graphicsnotretired` interpretation is the honest one.

## Concrete design for crash cleanup

The recoverable path needs a pre-exit retirement phase, while QEMU still owns
the guest's DMA mappings and the KIQ can execute against valid queue memory:

1. Stop guest submission and prevent new doorbell traffic. Keep VFIO DMA
   mappings installed. Capture authenticated device identity and queue
   selectors before mutation.
2. For every known guest compute queue, issue the v10 `UNMAP_QUEUES` action
   `RESET_QUEUES` through a host KIQ ring, commit it, and wait for KIQ completion
   (the Linux pattern is `amdgpu_ring_test_helper`). Then select each HQD and
   poll `CP_HQD_ACTIVE` to zero, recording per-queue completion and timeout.
   For guest GFX rings, use `PREEMPT_QUEUES` first when preserving a ring is
   desired; use `RESET_QUEUES` when abandoning it during crash cleanup.
3. Only after all queue retirements are proven, disable doorbell ranges and
   pointer polling, halt MEC/ME and SDMA ingress, and clear stale ring
   programming. Read back every transition. Keep `authorizes_launch=false`
   unless every expected queue has a retirement proof.
4. Tear down QEMU and remove DMA mappings only after the retirement receipt is
   durable. A normal close can then proceed through VFIO release and the
   existing host identity/reset checks.

This ordering matters because `UNMAP_QUEUES` is GPU firmware work that can read
MQD, write-pointer, and queue memory. Removing guest mappings first can leave
the packet unable to complete, exactly the condition represented by the nq2
timeouts. Host KIQ retirement should therefore be a guest-alive shutdown
handshake, not a post-close fallback.

## Honest limit after forced close

If QEMU has already exited or VFIO has removed the guest mappings, a host-side
KIQ packet cannot be treated as safe merely because its MMIO doorbell is
reachable. If the HQD does not retire within the bounded poll, recovery may
halt processors, disable doorbells, clear ring registers, and preserve a
non-authorizing receipt, but it cannot prove scheduler/firmware retirement.
The safe policy is to quarantine the device for subsequent launches and require
the existing reset/rebind or reboot escape when available. Never convert a
zero-valued `CP_HQD_ACTIVE` read after forced clearing into a claim that the
firmware retired the queue.

## QEMU-owned transport while VFIO remains open

The host process cannot simply reopen the same VFIO group while QEMU owns its
VFIO file descriptors. A possible pre-exit transport is therefore to keep QEMU
alive, stop guest vCPU execution with a new QMP endpoint, and issue bounded
PCI-BAR accesses through QEMU's GDB stub. The current VM launcher exposes an
HMP UNIX monitor rather than QMP, so this requires a separate endpoint in a
future launcher change. This is a transport design to validate, not an
implementation or a claim that GDB itself performs AMD queue retirement.

QEMU's [official GDB documentation](https://qemu.readthedocs.io/en/v7.2.19/system/gdb.html#examining-physical-memory)
 says that `-s -S` exposes the stub and that
the stub can inspect/change guest state. Its `Qqemu.PhyMemMode:1` packet makes
GDB memory addresses guest physical addresses. QEMU's official `gdbstub`
[`gdbstub/system.c` implementation](https://gitlab.com/qemu-project/qemu/-/blob/v9.2.2/gdbstub/system.c#L500-520)
 routes physical-mode accesses through
`cpu_physical_memory_read/write()`, i.e. through the system address space. This
research does not claim that a GDB physical access reaches a VFIO BAR: the
safe first test must use QEMU's emulated `edu` device only. The documentation
does not promise that every passthrough device or width is writable through
GDB.

QMP [`stop`](https://qemu.readthedocs.io/en/master/interop/qemu-qmp-ref.html#command-stop)
 is the stable pause primitive: the QMP reference specifies that it
stops guest VM execution and emits a `STOP` event; `cont` resumes it. The pause
does not stop independent device DMA or force a PCI bus-master clear. It only
creates a window in which guest CPUs cannot immediately program more queues.
The protocol must therefore also disable the guest's submission path (for
example, a guest shutdown hook or a bus-master/doorbell gate) and verify that
no new doorbells or write pointers appear. If the guest is wedged, QMP stop
cannot make an in-flight queue safe by itself.

QMP [`query-pci`](https://qemu.readthedocs.io/en/master/interop/qemu-qmp-ref.html#command-query-pci)
 returns each guest PCI device's BAR `address`, `size`, and
`bar` number. The transport can authenticate the expected AMD device and use
the returned guest BAR address plus the known register offset. It must reject
an unassigned address (`-1`), a size/offset overrun, a device/BDF mismatch, or
an unexpected BAR layout. The existing `run-bounded-gdb.py` and
`gdb-kext-source.py` already provide identity-bound, bounded GDB connection,
transcript, timeout, and detach patterns; they currently inspect CPU/kernel
memory and do not implement MMIO register transactions.

The current launcher exposes an HMP UNIX monitor, not QMP. A standalone offline
prototype now exists at
`/home/bogdan/macos-vm/run/worktrees/candidate-203/tools/qemu-mmio-transport-probe.py`.
It uses the pinned candidate image with TCG only, q35/64 MiB, no default
devices, display, disk, KVM, VFIO, or DRI, and mounts only a temporary socket
directory. It starts the fixed QEMU `edu` device at PCI `04.0`, configures BAR0
to `0x10000000` through qtest CF8/CFC writes, verifies QMP `query-pci` identity
`1234:11e8` and BAR layout, then checks GDB physical mode using the documented
edu inversion register at BAR `+4`. This proves transport reachability to an
emulated device only; it says nothing about AMD retirement.

The authorized bounded emulator run completed successfully on 2026-09-13. Its
durable result is `/tmp/edu-probe-parent-rbkSmB/result/result.json`: QMP reported
edu `1234:11e8` at slot 04.0 with BAR0 address `0x10000000` and size `0x100000`,
QEMU status was `prelaunch`/`running=false`, GDB physical mode reported `1`,
and the edu inversion transaction returned bytes `87a9cbed` for the fixed
little-endian value `0x12345678`, then restored `00000000`. The exact container
CID was cleaned up and `docker inspect` confirmed it absent; no QEMU process
remained. Earlier bounded attempts failed before transport evidence (one had a
wrong fixed entrypoint and one had an identity comparison bug); their captured
stderr/result files were retained in their respective temporary output
directories and were not classified as transport passes.

### Runnable architecture for a CPU-only test

1. Start a separate pinned-image QEMU TCG test with a newly configured QMP
   endpoint and GDB stub. Use q35, 64 MiB, `-nodefaults`, `-display none`, no
   KVM, no disk, no VFIO, and only the fixed emulated `edu,id=edu0` device at
   PCI `04.0`. Query QMP capabilities, `query-pci`, and the fixed edu identity.
2. Send QMP `stop`; require the matching `STOP` event. In GDB, select physical
   mode and perform bounded BAR probes against the emulated edu device.
3. For this CPU-only transport test, configure edu BAR0 to guest physical
   `0x10000000` via qtest, then read/write the documented edu inversion register
   at BAR offset `+4` with a reversible value. Record GDB packet replies, width,
   guest physical address, and readback. This establishes only that the
   transport reaches the emulated device, not that queue firmware accepted a
   packet.
4. A later queue-retirement experiment can encode the existing selector loop
   as GDB physical BAR reads/writes, with a per-write readback and deadline,
   while preserving the current `quiesce_gc` receipt predicates. It must issue
   the actual KIQ/`UNMAP_QUEUES` sequence through valid queue memory; register
   clearing remains containment and cannot substitute for retirement proof.
5. Resume or terminate QEMU only after the receipt is durable. If any probe,
   stop event, identity check, or retirement poll fails, leave the run
   non-authorizing and follow the existing cleanup path.

This design solves the transport ownership problem only for a cooperative,
still-running QEMU. An abrupt QEMU kill can remove mappings before the queue
retirement handshake, and QMP/GDB cannot repair that race after the fact. The
existing forced-close fallback and its explicit `gfx_retirement_confirmed=false`
limit must remain.

## Recommendation

Add an explicit pre-QEMU-exit `retire_guest_queues` phase with per-selector KIQ
`RESET_QUEUES` submission, KIQ completion, and `CP_HQD_ACTIVE` polling. Pass its
receipt into `quiesce_gc` as an authenticated prerequisite. Retain the current
post-close fallback as containment only, with `gfx_retirement_confirmed=false`
on any timeout. This follows the upstream Linux teardown sequence while
preserving the project’s host safety and no-false-proof invariants. Where the
host cannot access VFIO directly because QEMU still owns the group, evaluate the
QMP-stop/GDB-physical-memory transport as a separate, bounded CPU-only probe
before attempting queue writes.
