# Candidate402 private backing pool draft

Unbuilt/unqualified implementation for review, after candidate399's host timing
extension. Default-off `x-debug-snapshot-pool`; requires snapshot support and
CONFIG_PIXMAN. No guest ABI, BAR, epoch, copy/ACK order, migration behavior or
presenter identity change. No harness allowance or new runtime image yet.

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

Software tests are drafted, not run yet: production header extracted from the
patch, linked to actual GLib/Pixman, exercises retained image references, capacity
exhaustion, odd geometry reuse, pixel preservation, closed-pool refusal, delayed
final unref on another thread after device-owner close, and idle cleanup. They
qualify the backing/reference policy, not an actual QEMU DisplaySurface teardown
or arbitrary listeners. The existing actual device oracle gains `--pool` for
full-pixel restart, stale epochs, writes after ACK, pending retirement, geometry
and migration controls plus missing-prerequisite refusal. A separate native/QEMU
unrealize test and actual surface-wrapper retention proof remain required before
claiming full teardown qualification. No host timing improvement is yet measured.

Source premise and external-FD caveat are pinned in
`console-snapshot-recycling-design-20261010.md` and its source manifest. Unlike
recycling ordinary memfd images, pooled private RAM has no exported handle whose
lifetime could escape in-process image-reference tracking.

The additional bounded `tests/console_snapshot_pool_surface.py` witness is also
prepared, not executed. It validates source hashes, extracts the exact pinned
QEMU surface create/free and Pixman-unref wrappers, and runs an ASan/UBSan case
retaining a listener image across actual wrapper destruction and pool-owner close.
Only trace calls are stubbed; its scope is the non-GL Linux wrapper/reference
path, not full QEMU device-unrealize or external-FD consumers.
