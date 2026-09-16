# Candidate-195 TLS root-cause finding

Offline review of `/home/bogdan/macos-vm/run/metal-029-195f-output/serial.txt`
finds a stronger explanation for the crash than the removed `wireSysMemory`
experiment. The panic registers were:

```
RIP=0xffffff8058600000  RAX=0  RDI=0xffffff801c7234a0
RDX=0xffffff801c787c30  RCX=0xffffff907fa11b30  R14=1
RSP=0xffffffd35b6fbc08  RBP=0xffffffd35b6fbc30
```

The candidate-195 binary has `activeMapCommitWindow` at `a74a0` and
`submissionCommits` at `10bc30`. Subtracting either symbol address from its
runtime value gives the same inferred loaded base:

```
0xffffff801c7234a0 - 0xa74a0  = 0xffffff801c67c000
0xffffff801c787c30 - 0x10bc30 = 0xffffff801c67c000
```

The subtraction is internally consistent, although the loaded base was not
independently logged. The register pattern matches the wrapper frame: the map
TLV descriptor is in RDI, the map pointer is in R15, the submission store
pointer is in RDX, current-thread token is in RCX, and sequence/index state is
in R14/RAX. The stack fits the wrapper's saved frame. The fault RIP is an
invalid indirect target, not an authenticated TLV bootstrap function address.
The likely path is `wrapCommitIntoGPUPageTable` accessing
the `thread_local ActiveMapCommitWindow` TLS object while the native call is on
the relevant worker.

This is a bounded causal finding, not proof that all kernel TLS is unsupported:
the exact binary/register evidence identifies this diagnostic TLS dispatch as
the failure. Apple dyld's public TLV contract documents that on-disk TLV
pointers are replaced during preparation with real handlers; the dyld helper
implementation supplies the runtime access sequence. The guest kernel context
did not provide the expected user-space TLV bootstrap path.

## Repair

Remove the diagnostic `thread_local ActiveMapCommitWindow` and its per-map
correlation fields and logs. Keep `submissionCommits` aggregate observations
(`map`, worker token, result, sequence) so commit activity remains visible.
Per-map commit counts and sequence windows are unavailable after this repair;
they must not be represented by fabricated zero values.

The source rollback also removed the disproven early-disable and VMM force
interventions, restoring the native disable path and prior owned/ready VMM
condition. This finding does not establish native startup or Metal readiness.

## Validation boundary

The repository source was checked explicitly with the preflight helper by
overriding its source path to `src/RaphaelGPU.cpp`; the helper's other paths
still come from `/home/bogdan/macos-vm`, so this is not a complete independent
environment check. The release validator now rejects `__thread_vars`,
`__thread_bss`, and `__thread_data` sections and any `__tlv_bootstrap` string.
A private audited-working-source build was checked with that validator; its
dirty source state means it is not candidate or release authority.
