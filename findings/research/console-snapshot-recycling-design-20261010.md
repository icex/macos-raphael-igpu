# Host-private snapshot recycling design audit

Proposal pending implementation and software/native qualification. Candidate399's
initial host window8 has284 commits, copy1749958us, allocation4354us,
pending-free33595us, pending-present28. These parent-reported provisional values
put copy including first-touch near6.16ms; they do not isolate RAM bandwidth.

Pinned runtime399 image is
`sha256:ef2d8d7843120042950a5de3b8070fa455092c597602ffd2d66cba83ffc29864`,
QEMU binary`866e4ce4c0ecaad0392369d9f0d96e6a304ce081585c8585bd5f9cf1919ac686`.
The baseline inspected source is QEMU10.1.2 with the six c394 patches under
`/home/bogdan/macos-vm/run/c394-restart-snapshot/qemu-10.1.2/`; c399's additive timing
patch does not change its ownership. Exact source hashes are in the adjacent JSON.

## Ownership evidence

- `ui/console.c:467–500` creates shareable snapshot images through Pixman helpers.
  `ui/qemu-pixman.c:274–341` uses memfd backing and an image-destruction callback;
  `util/memfd.c:108–159` allocates/maps and unmaps/closes it. First copy can fault in
  fresh pages, a cost not necessarily visible in allocation timing alone.
- `ui/console.c:811–847` switches listeners then frees the old DisplaySurface.
  `qemu_free_displaysurface:542` unrefs its Pixman image. Freeing the surface
  wrapper alone does not prove the backing has no remaining references.
- `ui/spice-display.c:339–389` retains `ssd->surface` as a Pixman reference.
  Refresh435 takes the SSD mutex, then update176–185 copies the source to a mirror
  and separately allocated QXL bitmap. Spice-thread release255 frees that bitmap,
  not the snapshot backing. This is the relevant admitted non-GL SPICE path.
- `ui/vnc.c:832–833` also retains a Pixman reference.
- Crucially `ui/dbus-listener.c:527–565` can duplicate/export a shareable FD to
  another process. Final in-process Pixman release does not prove the external
  process has unmapped that FD. Generic recycling of exported memfd backing is
  therefore not justified by final Pixman reference alone.

## Proposed narrow solution

Opt in to a device-local bounded pool of **host-private, non-exported RAM**. Every
pooled DisplaySurface must have SHAREABLE_NONE. Build a new Pixman image wrapper
for each lease around externally owned backing, with a destroy callback that
returns the backing only at final image release. Never retain the old Pixman image
in the pool: that would prevent its final-release callback. Never overwrite the
current/published image, reclaim at ACK, or assume two buffers always suffice.

When no slot is idle, allocate the existing fresh surface as fallback, preserving
its existing shareable ownership/destructor unchanged; never insert fallback memfd
storage into this pool. Bound pooled total bytes and slot count independently of
fallback images retained by existing consumers. A full overwrite is required before
ACK/publication, including after geometry changes; no stale pixels may be exposed.

Pool state outlives its device through explicit backing references. Teardown marks
it closed and detaches the device owner, frees idle slots, and leaves outstanding
images immutable until their callbacks finally free the remaining private blocks.
Callbacks may run under listener locks and must not acquire BQL, invoke display
callbacks, touch Bochs state, or reverse lock ordering. Use only the pool's own
mutex/reference bookkeeping; do not make Pixman reference operations concurrently
on an image without the existing caller synchronization.

ARM/RETIRE still cancel only the unpublished pending surface. Delayed listeners
may hold an old epoch's image indefinitely without blocking a fresh fallback or
allowing cross-epoch writes. Geometry reuse must match capacity/stride rules and
must not leak old padding/content. The no-pool default, epoch validation, migration
refusal and ACK-after-full-copy ordering remain unchanged.

Required software evidence: hold extra Pixman references across DisplaySurface and
device/pool destruction; prove no early recycle, safe delayed final callbacks,
closed-pool release, byte/slot caps and geometry transitions; actual QEMU full-pixel
restart/stale-epoch/write-after-ACK controls; default/fallback/share-handle checks.
Then compare matched native workload timings and immutable output. No performance
improvement is established by this proposal.
