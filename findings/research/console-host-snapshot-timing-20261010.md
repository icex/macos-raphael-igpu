# Candidate399 host snapshot timing discriminator

Diagnostic patch only; QEMU build/device execution and native qualification remain
pending. This does not implement surface reuse or change immutable ownership.
Candidate397 preliminary guest measurements place more time in the synchronous
commit doorbell than in private-RAM-to-WC copying. Doorbell wall time also includes
VM-exit, dispatch, BQL contention and scheduling; it is not pure host memcpy.

## Exact base and additive patch

Runtime baseline is `raphael-qemu:c394-restart-snapshot`, image
`sha256:2fc501c44cb60dd5cd7c85b1c4462d2fbcb621415acc356327ba8c7443050467`,
QEMU executable SHA256
`4f285bcee5a6b3609158a76080a8901b61bd4787852e3006d599ae5400d2f22d`.
Retained build inputs: `/home/bogdan/macos-vm/run/c394-qemu-runtime/inputs.json`,
`build.sh` and `Dockerfile`. QEMU10.1.2 archive SHA256
`9d75f331c1a5cb9b6eb8fd9f64f563ec2eab346c822cb97f8b35cd82d3f11479`.

Apply `patches/qemu-10.1.2-bochs-snapshot-timing.patch` after the existing six
patches, preserving their order: explicit non-GL refresh, Bochs full-refresh,
legacy snapshot, SPICE single rectangle, SPICE changed bounding box, restart
snapshot. The extension adds `x-debug-snapshot-timing=false`; enabling it without
`x-debug-snapshot=true` is rejected. No launcher allowance or deployment is added.
Existing migration refusal, legacy/restart protocol and ownership remain intact.

## Measurements and bounds

Successful validated commit path samples `g_get_monotonic_time()` around:

1. `qemu_create_displaysurface`: allocation wall time.
2. Full BAR1→fresh-surface memcpy: includes first-touch page faults.
3. Superseded pending-surface release: includes the existing replacement-counter
   update and `qemu_free_displaysurface`, even when pending is null.

At this pinned source, `ui/console.c:467` creates a shareable image through
`ui/qemu-pixman.c:307`; `util/memfd.c:108` uses memfd/ftruncate/mmap. Destination
pages can be instantiated during the copy, so moving latency between allocation
and copy does not by itself demonstrate bandwidth or allocation dominance.

Each stderr row gives window number, host monotonic start/end microseconds,
physical geometry, successful commits, observed allocation/copy/free calls,
pending-present/null counts, and stage total/max microseconds. All three stages
complete exactly once per recorded successful commit. A fatal allocation failure
has no completed sample. Free-call count includes null no-op calls; pending-present
is the count of actual superseded surfaces. No RETIRE/ARM/exit frees are included.

Eight fixed geometry buckets, saturated uint64 counters and explicit saturation
flag; untracked additional geometry count. Saturated rows must not be used for
means or derived count conservation. At most eight rows per five-second-or-longer
window,128 windows per device lifetime. Clock calls stop at this cap. Windows
flush only on successful commits, with no timer/teardown flush; idle/final partial
windows are not reported. All access is under existing BQL serialization.

Sampling excludes prior dispatch/BQL wait and validation. Logging/aggregation occur
after ACK assignment but before callback return, so guest doorbell timing includes
their bounded overhead. Subtracting unmatched host/guest windows is not a precise
wait measurement; align monotonic windows/workload geometry and acknowledge sample
boundaries and clock overhead. No surface reuse or guest-staging reference is added.

## Build and qualification plan

Use a new isolated source/build directory and separately named runtime image, not
the existing image. Replay the six pinned patches plus this extension using the
retained base-image build recipe (KVM/SPICE/slirp/VNC enabled), record all input,
archive, executable and image hashes. Do not use a host-TCG-only binary as runtime
proof. Before native staging, run actual qtest/QMP full-pixel restart, stale epoch,
legacy/default-off and migration-refusal controls through the exact runtime image.
Check opt-in rows and default absence, guard rejection, count consistency and
geometry change handling. Parent owns runtime build approval/integration and all
native runs.

Software validation so far: patch dry-run applies to retained six-patch source;
`test_qemu_snapshot_timing.py` compiles and executes the production header from the
patch, exercising per-geometry counts/totals/max, pending counts, bucket bound,
period boundary, reset, saturation and lifetime cap. This is policy validation,
not a QEMU build or device test.
