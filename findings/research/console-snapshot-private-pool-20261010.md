# Candidate402 private backing pool experiment

Software-qualified implementation for a bounded native experiment, after
candidate399's host timing extension. Default-off `x-debug-snapshot-pool`; requires snapshot support and
CONFIG_PIXMAN. No guest ABI, BAR, epoch, copy/ACK order, migration behavior or
presenter identity change. The exact optional harness profile is `restart-timing-pool`; all historical
profiles remain unchanged.

The extension replaces only the fresh-surface allocation choice when opted in.
It obtains a new Pixman wrapper over one of three32MiB private RAM blocks; each
DisplaySurface has SHAREABLE_NONE and the allocated flag. It still copies every
active pixel from BAR1 before assigning ACK. No direct guest-memory reference is
published. If the pool is exhausted or private allocation/image creation fails,
the unchanged QEMU shareable fresh allocation remains fallback. Such fallback
backing is never enrolled in the pool.

Each block owns a pool reference through reserved, leased and idle states. The
device owns one separate reference. Pool closure happens before pending-image
release and `graphic_console_close`; it marks closed, frees idle blocks and drops
the device reference. Leased blocks retain independently alive pool state. Their
final Pixman callbacks free blocks and release slot/byte accounting after closure,
or return blocks to idle while open. Callbacks do not call display functions,
acquire BQL/listener locks or dereference the device. The only additional lock is
GMutex, ordered after existing caller locks. Actual Pixman reference operations
still require their existing caller synchronization.

The strict pool cap is three reserved/live/idle blocks and96MiB backing. This is
not a cap on all existing QEMU listener/fallback allocations. Slot reservation is
under lock before allocating; all allocation failures undo their reservation.
Geometry changes create new wrappers with exact packed width*4 stride over the
same capacity; full active payload copy precedes publication. Old wrappers remain
immutable until final reference release, even across RETIRE/ARM epochs.

Software qualification now passes: actual production header linked to GLib/Pixman,
retained references, capacity exhaustion, odd geometry reuse, pixel preservation,
closed-pool refusal, delayed final unref on another thread, allocation failure and
counter saturation. The actual image QMP/qtest oracle verifies full pixels after
ACK overwrites and stale epochs, pending retirement, geometry changes and migration
refusal. It also unrealizes the real device with one published front surface and a
second pending snapshot. This does not simulate every possible display listener.
No native host timing improvement is yet measured.

Source premise and external-FD caveat are pinned in
`console-snapshot-recycling-design-20261010.md` and its source manifest. Unlike
recycling ordinary memfd images, pooled private RAM has no exported handle whose
lifetime could escape in-process image-reference tracking.

The source-pinned `tests/console_snapshot_pool_surface.py` witness passes under
ASan/UBSan. It extracts the exact QEMU surface create/free and Pixman unref wrappers,
retains an extra image reference across wrapper destruction and pool-owner close,
and verifies every payload byte before final release. Only trace calls are stubbed;
its scope is the non-GL Linux wrapper/reference path, not external FD consumers.

## Reviewed implementation checks and bounded counters

Production-header tests and the exact surface-wrapper ASan/UBSan witness now pass.
The witness output is retained in `run/c402-surface-lifetime-stats` (earlier
pre-counter run separately retained). No QEMU device/unrealize result is claimed
by those tests. Real-image software qualification follows separately.

When host timing is enabled, a separate `bochs-snapshot-pool` line is emitted only
at the existing timing-window boundary, at most128 times. Counts are cumulative
for the pool lifetime, saturated uint64 with an explicit flag. `attempts` counts
completed private-pool requests; `success` counts returned images; `fallback`
counts requests returning NULL to the original fresh allocator. `created` counts
successfully allocated private backing blocks, even if the subsequent Pixman
wrapper allocation fails; `reused` counts successful image leases from idle blocks.
Fallback reasons partition into capacity, closed, invalid geometry and allocation
failure. Allocation failure includes block metadata, payload or Pixman-wrapper
failure; it does not report failure of the subsequent original QEMU fallback,
whose existing error-abort semantics remain unchanged. Slot/byte snapshots and
counters are read under the pool mutex. Saturated counters must not be used for
conservation/rate claims. A temporary request reference protects failure accounting
if close overlaps an in-flight allocation.

Tests check real outcome counts, deterministic backing-allocation failure with
reservation rollback, and saturation, in addition to lifetime/pixel/cap controls.

## Exact runtime results

The isolated runtime image is
`sha256:6d91e1ff4192f9c0fe693a171a2a2bbdb7b9d2a96b184e17a38776a2119c2bfa`;
QEMU executable SHA256 is
`d492aea82778470aff201ffeeb8ab45977192e721e8a100e444253f6bff24164`.
All 182 runtime dependency hashes match candidate399. The eight ordered patches,
archive and build script are pinned in `run/c402-qemu-runtime/inputs.json`.
Default pool-off restart, legacy, host-timing, and pool-on restart oracles pass.
The pool window records seven attempts, three created backing blocks, four reused
leases, seven successes, zero fallbacks, three slots and 100663296 bytes.
Forced capacity and allocation fallbacks are qualified by production-header tests;
this short actual-device run did not force a fallback. No per-frame telemetry.

The exact no-Pixman Bochs translation unit also compiles in a separate configured
build; this is not a linked no-Pixman runtime test. The initially incorrect Ninja
target name and its failure remain preserved beside the successful correct target.
All software containers exited and were removed; no physical devices were exposed.
Artifact hashes and explicit scopes are retained in
`console-snapshot-pool-software-evidence-20261010.json`.
