# Restart-safe immutable console staging proposal — 2026-10-09

**Proposal only; unimplemented and not natively qualified.** This audit identifies
an implementation path toward restartable, atomic VM-manager output. It does not
change any experiment contract, authorize a live run, or establish production
readiness. The intended outcome is usable accelerated desktop output with normal
resize, input, audio, presenter restart and repeatable shutdown—not an indefinitely
expanding diagnostic fixture collection.

## Current implementation and exact compatibility boundary

Local references are relative to this repository at candidate393:

- `src/ConsoleBridge.cpp`: `RaphaelConsoleClient::clientMemoryForType` returns
  BAR0 for type0 and the fixed BAR1 staging descriptor for type1, only to the
  snapshot owner. `externalMethod` exposes selector0 mode(width,height), selector1
  ARM(), selector2 COMMIT(width,height,sequence) → ACK, selector3 CLOSE().
- `RaphaelConsole::snapshotArm` sets `snapshotLeased` permanently, including on
  ambiguous ARM readback. `snapshotCommit` requires the exact owner and checks
  host state/error/ACK. `snapshotClose`, called by client close and stop, writes
  RETIRE and detaches the owner. The retained one-shot rule prevents a stale
  userspace mapping from writing a later owner's shared staging pixels.
- `tools/console-presenter.m`: `RGPU_CONSOLE_SNAPSHOT=1` selects snapshots;
  unset/0 selects ordinary BAR0. SnapshotProtocol must equal1. The unchanged
  presenter arms only after ScreenCaptureKit starts, maps type1 as exactly32MiB,
  copies packed BGRA rows at offset0 with stride width*4, fences, and synchronously
  commits monotonically increasing owner-local sequences beginning at1. Exact
  returned ACK is mandatory; an ambiguous commit terminates capture. There is no
  userspace pixel-buffer header to repurpose. Normal dimensions are bounded to
  3840×2160 for this path. Mode updates and capture copies share a serial queue.
- `tools/console-support-launcher.sh` currently launches that sealed presenter
  without explicitly selecting snapshot mode. It owns holder, resize agent,
  presenter and awake assertion as children, retains the6000-second session
  budget, and terminates only those children during cleanup. Fixed-scale changes
  currently require an owned session restart. No restart loop exists.
- `tools/console-support-install.py::validate_capture` and the addon transaction
  preserve installed signed app bytes and capture provenance. External launch
  policy can select the existing snapshot implementation without replacing or
  re-signing the capture app or editing TCC. The current launcher should also
  explicitly control the snapshot environment rather than inherit it accidentally.

The QEMU contract is in
`findings/research/patches/qemu-10.1.2-bochs-snapshot-research.patch`:

| BAR2+0x700 offset | Existing meaning |
| --- | --- |
| 0x00 / 0x04 | magic0x52534731 / staging size32MiB |
| 0x08 / 0x0c | state0 available,1 armed,2 permanently retired / error |
| 0x10 / 0x14 | width / height |
| 0x18 / 0x1c | commit sequence write / acknowledged sequence read |
| 0x20 / 0x24 / 0x28 / 0x2c | published sequence / replaced count / published count / pending sequence |

`bochs_snapshot_write` copies BAR1 into a new owned DisplaySurface under BQL before
ACK. Pending snapshots can be replaced; published surfaces are retained by their
consumers. RETIRE discards pending output and invalidates ordinary mode state so
BAR0 fallback can resume. `bochs_display_gfx_update` publishes only complete pending
surfaces while armed. State2 cannot currently re-arm; sequence validation is global.
Migration is refused whenever the experimental capability is enabled. These
restrictions must remain intact until an explicitly reviewed replacement exists.

## Proposed implementation preserving the sealed presenter ABI

1. Allocate a fresh, zeroed32MiB `IOBufferMemoryDescriptor` for each newly armed
   IOUserClient connection; no physically contiguous allocation is needed. Type1
   returns only this private RAM descriptor. The fixed host-readable BAR1 becomes
   kernel-only and is never returned through any userspace memory type.
2. Preserve selectors, arguments, property1 and exact type1 length. For COMMIT,
   validate owner, dimensions, byte count and owner-local sequence; copy private
   RAM into the kernel BAR1 mapping; fence the kernel's stores; issue host commit;
   return the original owner-local sequence only after exact host acknowledgement.
   The presenter's existing fence does not replace the new kernel-side fence.
3. Serialize commit with close/stop and ownership handoff. Retain the source
   descriptor for the complete operation; detach the retiring owner before a new
   owner can publish. Never recycle its storage manually while mappings retain
   it. Retained old mappings then access only old private RAM, not a later owner's
   pixels. Reject re-ARM on the same connection: the legacy ABI has no caller epoch
   to distinguish delayed calls from that connection's earlier lease.
4. Add an explicit host capability/version for restartable sessions. Define fresh
   epoch acknowledgement, retirement/pending cancellation, sequence overflow and
   ambiguous-error behavior before coding. The driver translates owner-local
   sequence into host epoch/sequence identities. The existing host magic alone
   cannot authorize re-arm. Legacy host support must retain its one-shot behavior;
   do not implement this as simply clearing `snapshotLeased`.
5. Keep the host bank/header private to the driver. New epoch metadata belongs in
   host control registers or another kernel-only control region, not at offset0
   of the sealed presenter's32MiB pixel mapping. Keep exact dimensions and format
   per commit, including odd1× modes, and initialize first-frame/resize output.
6. Select the new path through a validated external launcher policy. Preserve the
   existing sealed app, normal capture consent, owned-child cleanup and finite
   run budget. Failures must be visible; ordinary BAR0 fallback must explicitly
   report that it has lost immutable transport. Do not introduce an unbounded
   restart loop or silently claim atomic output after fallback.

This requires a fresh guest running the new driver: a fixed bank already exposed
by the old driver cannot safely become private merely by changing a boolean.
Treat shutdown and fresh-owner startup as transactions, including allocation/map
failure after ARM. A current cooperating presenter is still part of the contract:
private RAM prevents a retired owner contaminating the next owner, but does not
freeze a malicious current owner writing concurrently with its own commit.

## IOKit alternatives and evidence limits

The local SDK headers are under
`/home/bogdan/macos-vm/build/MacKernelSDK-master/Headers/IOKit/`:

- `IOBufferMemoryDescriptor.h::inTaskWithOptions` documents shared kernel/user
  allocation, cache attributes, default wired kernel storage and allocation that
  may block. Allocate outside inappropriate locks/interrupt context; account for
  retained allocations and bound refusal rather than retaining unbounded32MiB
  buffers across stale owners.
- `IOMemoryDescriptor.h::createMappingInTask`, `IOMemoryMap::unmap` and `redirect`
  provide mapping operations. Complete alias revocation would require recording
  every mapping and proving teardown/VM semantics. The current client does not do
  that. Redirecting to null can block future faults; that is not a simple benign
  substitute for stale-owner isolation.

Apple primary upstream source inspected on2026-10-09:

- [IOUserClient.cpp](https://raw.githubusercontent.com/apple-oss-distributions/xnu/main/iokit/Kernel/IOUserClient.cpp):
  `mapClientMemory64` obtains the descriptor through `clientMemoryForType`, merges
  userspace map flags and creates the mapping. `clientDied` invokes `clientClose`.
  This supports the proposed ownership path, not proof of actual crash cleanup.
- [IOMemoryDescriptor.cpp](https://raw.githubusercontent.com/apple-oss-distributions/xnu/main/iokit/Kernel/IOMemoryDescriptor.cpp):
  `IOMemoryMap::unmap`, `taskDied`, `free` and `redirect` expose distinct mapping and
  descriptor lifetimes. Tracking one mapping does not establish that every alias
  has been revoked. Private backing allocations avoid relying on that assertion.

These are current upstream source and local SDK API observations, **not a pinned
24G830 kernel implementation audit**. Native descriptor lifetime, crash callbacks,
cache behavior and mapping aliases still require qualification on24G830. In
particular, the sealed presenter permits `RGPU_CONSOLE_CACHE=wc`; new RAM mappings
must not allow incompatible cached aliases. Determine the supported map-policy
mechanism explicitly rather than assuming descriptor options override user flags.

Generation-only validation is insufficient when old userspace still writes the
same physical BAR bank. Revocation could avoid the extra copy, but proving all
aliases inaccessible is a larger and more fragile prerequisite than fresh private
RAM. Thus private backing plus a versioned host session is the preferred bounded
implementation direction, subject to performance measurement.

## Cost and completion criteria for the next implementation

An extra4K BGRA copy moves33,177,600 payload bytes per frame: at60fps about1.99GB/s
copied, or roughly3.98GB/s additional read/write traffic before cache effects.
There is at least32MiB extra active staging storage; stale retained mappings can
retain old allocations. These are arithmetic estimates, not measured throughput.
Kernel copy time, scheduling delay and QEMU host-copy cost must be measured before
calling this a production improvement.

The next iteration should implement the ownership and host protocol together,
then qualify the actual installed presenter—not stop after isolated diagnostics:

- Fresh owner succeeds repeatedly without changing the signed app or consent;
  old connection methods and retained old-mapping writes cannot corrupt new output.
- Close/death during commit, failed map/allocation and ambiguous ACK retire safely;
  no stale pending surface crosses a new epoch. Resource accounting stays bounded.
- Same holder/presenter resize, odd1× and2× modes, viewer reconnect, stationary
  pointer, keyboard and audio remain usable. Normal session restart restores the
  immutable path rather than silently falling back to ordinary BAR0.
- Whole-frame integrity across mixed motion/resize and measured cadence/copy cost
  complement token observations. ACK proves host copying, not manager delivery.
- Supervised shutdown/capture/recovery receipts and existing identity/migration
  refusal gates remain independent acceptance requirements.

Existing orderly retirement, denied regrant and ordinary fallback evidence does
not qualify client-death retirement or this proposed restartable design. No code,
load-bearing spec, capture app, live device or authorization gate was changed by
this audit.
