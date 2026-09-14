# Candidate 204 same-boot recovery audit

Date: 2026-09-13  
Scope: read-only audit; no VFIO mutation, MMIO, QEMU, rebind, launch, or
permission change.

## Decision

Same-boot reuse is not currently evidence-supported. The exact current-run
blocker is the recovery receipt for boot
`2f77212f-34f5-4905-ba66-d8c68a860d78`, run
`195033a6ab780bae53d4a9fc05ff296e`, supervised CID
`a6df8582e104f32b8fb0d97aa6bc7e7cda731e3ae94abea2d838ba97fefa8860`, build
`282fd1f10ab248a4ba909eebf73fb7fd`: nine HQDs were active, one dequeued, and
eight timed out. The receipt records
`host_kiq.status=blocked-active-hqd`, `forced_inactive=8`,
`gfx_ring_clean=false`, `gfx_retirement_confirmed=false`,
`status=incomplete`, and `authorizes_launch=false`.

The post-cleanup zeros are containment evidence only. `CP_HQD_ACTIVE` was
cleared after both command processors were halted, followed by pointer and
ring-register clearing. That does not establish that firmware removed the
scheduler mappings. The device is presently idle with no VM and remains on
`vfio-pci`; this is a safe quarantine state, not same-boot launch authority.

## Code and upstream comparison

The current recovery loop first issues `CP_HQD_DEQUEUE=1` while MECs run and
waits up to 50 polls per active selector (`tools/vfio-recover.py:2441-2463`).
If any queue remains stuck, the code deliberately refuses to start the
temporary host KIQ (`:2465-2513`). It then halts processors, disables ingress,
and scrubs legacy ring/HQD state (`:2636-2690`). The source comment explicitly
states that clean readback cannot substitute for `host_kiq=retired`
(`:2636-2639`).

The launch gate independently requires zero dequeue timeouts and zero
`forced_inactive`, plus `gfx_retirement_confirmed` and complete graphics proof
(`:2848-2890`). Thus there is no identified code path in this revision that
mistakes `forced_inactive=8` for retirement. Treating the eight queues as
retired, or changing that receipt field, would relax a protection rather than
recover the device.

This matches the Linux comparison in
[`linux-raphael-teardown-203.md`](linux-raphael-teardown-203.md:15): GC v10
teardown submits `UNMAP_QUEUES` through a ready KIQ, checks KIQ completion, and
polls `CP_HQD_ACTIVE`; a timeout is failure. The same research explains why a
post-close host KIQ is unsafe: QEMU/VFIO may already have removed the guest DMA
mappings needed by the packet (`:67-103`). The current launcher also exposes
HMP rather than the proposed QMP pause transport (`:105-113`).

## Concrete offline validation

The useful regression is to replay the receipt with all final HQD reads zero
while retaining the recorded `dequeue_timeouts=8` and `forced_inactive=8`.
The validator must continue to return non-authorizing; a test that changes
either value to zero should be rejected as altered evidence. The existing
proof suite exercises this exact invariant: from the candidate-203 worktree,

    python3 -m unittest tests.test_kiq_recovery_proof

passes 16 tests, including rejection of `forced_inactive=1` even when host-KIQ
evidence is otherwise marked retired. This is the concrete flaw test to retain
if recovery code changes: a fake MMIO trace may show successful post-halt
`ACTIVE=0` readbacks, but must still produce `authorizes_launch=false` unless
each queue has a pre-cleanup firmware retirement proof.

The next constructive path is an offline design/test of a pre-exit handshake:
keep QEMU/VFIO mappings alive, stop guest submission, issue per-queue KIQ
`UNMAP_QUEUES`/completion, and poll each HQD before QEMU closes. It cannot be
validated against this already-closed run without hardware mutation, and it
must not be added as same-boot authority until its transport and receipt
contracts are independently tested.

## Bounded inert-guest GDB diagnostic (user-requested follow-up)

The user explicitly permits a bounded blocked-GPU diagnostic and accepts the
possibility of a host-side error, while retaining the no-reuse rule. This audit
does not authorize or claim that run. The narrow feasible shape is a pinned TCG
guest with inert HLT firmware, `-S`, no disk/OS execution, no generic graphics,
and the exact Raphael VFIO function. GDB would read CPU registers/backtraces
only; it would not read or write GPU BARs or issue macOS commands. The result
would be diagnostic-only with `authorizes_launch=false`.

The reset caveat is precise. The current empty `reset_method` disables the
device's selectable function reset method; it does not by itself disable every
possible bus reset. Linux VFIO's bus-reset eligibility requires all functions
in the relevant device set to be owned by VFIO. Here the shared bus includes
host-owned CCP and xHCI siblings, so the separate all-devices-owned guard must
reject a bus reset. QEMU 10.1.2's ATI reset quirk covers device IDs 6649,
665x, 67ax and 67bx; it does not match Raphael `13c0`. These conclusions use
the local running-kernel interfaces and the pinned QEMU 10.1.2 quirk source;
the running kernel's exact source package is not independently pinned here.

Even if all reset attempts return unsupported/refused, VFIO attachment still
exposes the device and QEMU may perform PCI configuration and region setup.
`-S` stops vCPUs but does not stop independent GPU DMA or retire the eight
forced-inactive HQDs. Therefore this diagnostic can test the attach/GDB
boundary and collect an error, but it cannot establish recovery or authorize a
same-boot Metal launch. The existing eight-HQD blocker and incomplete receipt
remain unchanged.
