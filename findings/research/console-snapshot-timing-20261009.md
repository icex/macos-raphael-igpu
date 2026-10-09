# Candidate 397: bounded kernel commit timing discriminator

Implementation, not a native performance result. Opt in with
`rgpuconsoletiming=1`; absent or any other value leaves collection and logging off.
No presenter binary, capture identity, user-client selector, mapping/cache policy,
ownership, sequence, epoch or ACK behavior changes. This does not establish the
cause of the lower sampled 4K cadence in candidate 395.

`RaphaelConsole::snapshotCommit` samples monotonic uptime converted to nanoseconds.
Only successful commits contribute. Each `RaphaelConsole: timing` row reports one
physical geometry and successful count; each stage is **total/max nanoseconds**:

- `lock_ns`: before acquiring the provider lock through acquisition.
- `copy_fence_ns`: private WB RAM to BAR1 WC memcpy plus its existing SFENCE.
- `geometry_mmio_ns`: epoch (restart protocol), width and height stores and their
  existing synchronization.
- `doorbell_ns`: sequence store and synchronization. This includes the synchronous
  QEMU host callback, allocation/copy and scheduling/VM-exit effects; it cannot
  isolate QEMU memcpy alone.
- `ack_checks_ns`: sum of pre-copy state/error/previous ACK/epoch validation and
  post-doorbell state/error/new ACK/epoch validation.

These stages exclude ordinary ownership/argument checks, aggregation, logging,
unlock and userspace call overhead. Timestamp overhead and descheduling can affect
individual intervals; total/max are not CPU-time measurements. ACK still means the
host copied a snapshot, not that SPICE delivered or the viewer displayed it.

Storage is eight fixed geometry buckets. Additional geometries are counted in
`dropped_geometry` for that window. Counters saturate at UINT64_MAX, with explicit
`saturated=1`. No allocation or per-frame logging occurs. A successful commit can
flush at most eight rows after at least five seconds since window start; each row
carries the same window number and elapsed duration. Buckets then reset. At most
128 windows are emitted per provider lifetime. No timer or shutdown flush is
added: idle or short final windows remain unreported. Reports execute under the
existing lock and their cost is excluded from these stages but included in the
sealed presenter's whole selector-call timing, so compare that independently.

The smallest next native comparison is the same ordinary immutable presenter and
workload at 1440×900 and 3840×2160 with this boot argument enabled. Compare per-commit
means/maxima and the existing presenter `rows_*`, `snapshot_commit_*` and
`worker_total_*` timings. A large copy/fence increase supports investigating the
kernel WC copy; a large doorbell increase supports separately timing host allocation
and snapshot copy. Neither observation alone qualifies sustained display cadence.

Validation: `python3 -B -m unittest discover -s tests -p test_console_timing.py -v`
compiles and executes the production aggregate policy, exercising geometry
separation, bounded bucket admission, exact period boundary, reset, saturation,
lifetime cap and backward-time refusal to flush. No kext build or native run has
been performed for this change at this stage.
