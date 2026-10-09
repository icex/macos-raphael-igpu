# Candidate 348: separate presenter wall-time stages

This is instrumentation, not a copy optimization. Existing successful-frame
`CONSOLE` fields retain their meaning: `copy_avg_ms` starts before the pixel
buffer lock and ends after copying, SFENCE and any mode programming, before
unlock. Row memcpy, WC mapping, admission checks and bounded queue are unchanged.
Legacy reporting now happens after unlock to avoid charging printf to the new
worker duration. Dropped callbacks use relaxed atomic increments/loads because
the capture and processing queues differ.

`CONSOLE_TIMING` aggregates successful steady frames into approximately five
second windows (emitted on a completed frame, not a separate timer). It reports
frame count, total copied bytes, source-stride range, geometry and average/maximum
wall time for callback-to-worker, lock, row memcpy, SFENCE, mode check, unlock,
and worker entry through unlock. Total includes validation and miscellaneous
bookkeeping; stages need not sum to total. Queue time is separate from worker
time. Rejected or failed frames do not enter these statistics. No per-frame
logging is added. A geometry change flushes the previous window; its entire
frame is excluded from steady counters and gets a separate MODE record. The
transition mode time includes the existing mode log. A final short window may
remain unreported at shutdown. These are elapsed times, not CPU utilization,
GPU frame time, complete viewer frames, or an atomic-presentation guarantee.

Next native test: identical bounded moving-token workload at native 1080p and
1080 HiDPI, fixed ROI observer/profile; omit startup/mode records when comparing
steady stage costs. Large lock time points toward source synchronization. Large
row-copy/fence time warrants a separate contiguous-stride one-memcpy comparison,
with the existing per-row fallback and bounds preserved. It does not yet justify
assuming libc memcpy is inefficient or changing cache modes. Earlier WC evidence
is in console-resize-copy-20261008.md.

Offline validation: existing console host tests pass (94 tests, five optional
extension skips) and git diff --check passes. Those tests do not compile or run
this Objective-C code. No local macOS SDK was found; guest compilation, capture
consent for the changed signed executable, measured overhead and actual stage
results remain unqualified.
