# Capture refusal follow-up observations — candidate396

Diagnostics only. Candidate392 and394 reported the exact original QEMU leader
in stateR, one task, flags138412428, with a bound guest-shutdown event preceding
capture closure. The installed7.2.5 kernel header identifies PF_EXITING in those
flags; this indicates task exit has begun, not that memory/VFIO/file cleanup has
completed. Both original runs retain their capture-abort classification.

At the existing `libvirt-console-entry.py::refusal_diagnostics` call, this change
adds a descriptor-name count bracketed by leader stat/start-tick identity checks,
a second bounded task/stat sample, and a final leader identity check. It never
reads descriptor targets or stacks. It does not infer completion or alter the
original process refusal, wait admission, stop action, or recovery policy.

All operations share the existing20ms diagnostic budget checked between operations;
the existing external docker-exec/transport deadline remains the syscall bound.
There is no additional sleep, poll interval or grace. Each directory scan counts
at most64 entries plus one lookahead; each task scan reads at most8 stat records.
Stat reads remain limited to4096 bytes. Counts are racing observations, not atomic
snapshots. Truncation/errors are explicit; an inaccessible directory is never
reported as empty. No identity-rechecked descriptor count or second task sample
survives a failed final leader stat/start-tick check.

New receipt fields are `diag_fd_count`, `diag_fds_truncated`,
`diag_second_task_count`, `diag_second_tasks`, `diag_second_tasks_truncated`, and
`diag_final_stat`. The supervisor retains only bounded typed values and the
existing fixed error vocabulary with new `fd`, `task2`, `stat2` stages. Extra
untrusted fields and exception text are discarded. These values are copied only
after the exit proof has already refused; they cannot authorize a wait.

Behavioral tests cover populated and empty descriptor directories, unreadable and
truncated directories, identity changes during scanning, budget exhaustion without
budget renewal, private-target avoidance and second task observation. Host tests
verify populated diagnostics still cause the same immediate stop, without delay.
Native observation remains future work; no live process or original receipt was
changed. A future bounded-wait proposal would require separate review and must
continue to distinguish wait eligibility from actual process completion.
