# Recovery lease and critical replay guest verification

Date: 2026-09-10

This is an offline implementation handoff. It does not claim a successful GPU
run, Metal execution, desktop acceleration, crash recovery, or permission to
launch a hardware experiment. No VM, VFIO/MMIO access, sudo, deployment,
release build, git commit, or push was performed during this review.

## Implemented production boundary

- `src/RecoveryLease.hpp` defines the immutable 80-byte OWNED record and the
  separate 104-byte POOL record. Publication clears the state DWORD, copies the
  remaining DWORDs, fences, writes state last, fences, and verifies complete
  readback. Serialization now uses `__builtin_memcpy` rather than aliasing a
  record through `uint32_t *`.
- `src/RecoveryLifetime.hpp` adds the 88-byte schema-3 lifetime marker at lease
  offset `0x200`. VALID is published only after exact ACTIVE pool readback and
  while schema 2 remains `PoolVerified`; ordinary clients become eligible only
  after the lifetime readback succeeds. ABORT writes and verifies ABORTING
  before changing any mutable body word, then commits an immutable ABORT.
- Lease phases are atomic. Ownership is claimed before preflight/native append,
  all forward transitions use compare-and-swap, and invalidation is a terminal
  atomic store. A concurrent abort cannot be overwritten by a late ACTIVE
  commit. V2 is invalidated before an owner writes ABORTING, closing the KIQ
  admission window during persistent abort publication.
- `wrapVmmSetVSReady` verifies the exact Raphael hardware owner and the exact
  `AMDHardware::appendToReservedVRAMOffset` vtable target before the native
  type-0 append. It validates the resulting lease against the current decoded
  GART before writing OWNED. A rejected or duplicate epoch does not call native
  VMM initialization or the forced early VMM allocator path.
- The exact memory-object/hardware-object pair that acquired the lease is
  published after VMM range validation. `wrapHwMemEnable` checks that identity
  and the exact `AMDHWMemory::reserve` vtable target before Apple's native pool
  mutation. A mismatch emits terminal `XH2 ABORT reason=pool-owner` and returns
  false.
- `wrapHwMemEnable` has the native Boolean ABI. The shared helper also masks the
  modeled native result to AL, so dirty upper EAX bits cannot turn false into
  success. Apple's initializer runs once; the complete lease address is then
  reserved from both pools. Both element starts and exact free-byte decreases
  must agree before POOL ACTIVE publication admits clients.
- OWNED and POOL locator text emits nonce LOW_HIGH, matching the serialized
  fields and host parser. Duplicate ready/pool epochs and a rejected VMM range
  emit `XH2 ABORT`, which the strict host parser treats as fatal.
- Scalar readiness is
  `XV2 VMM phase=early|native enable=<u> base=<hex> arena=<ptr> pool0=<ptr> pool1=<ptr>`.
  The native record is emitted after a returned enable=true call only; shutdown
  disable therefore cannot supersede startup readiness. The existing native
  entry diagnostic is a critical `CRLOG`, so a return-time stall retains the
  before-call context when the critical stream can be replayed.
- `tools/preflight.py` now gates the v2 bool ABI, exact owner/vtable/GART order,
  schema-3 lifetime ordering, one native pool initialization, duplicate aborts,
  and enable-only readiness.
  The old v1 cap/activation assertions were removed rather than bypassed.
- `src/CriticalReplay.hpp` emits complete immutable critical-record snapshots as
  bounded `RGPU_CR2` chunks plus one integrity-bound `RGPU_END2` manifest. The
  format uses zlib-compatible CRC-32 per chunk and CRC-32 plus FNV-1a64 over the
  full snapshot. These checks detect accidental loss or corruption; they are not
  an authentication mechanism. `RGPU_END2 state=complete` proves snapshot
  completeness, not a terminal guest lifecycle.

Primary production references are `src/RaphaelGPU.cpp:4019`,
`src/RaphaelGPU.cpp:4040`, `src/RaphaelGPU.cpp:4159`,
`src/RaphaelGPU.cpp:5195`, and `src/RaphaelGPU.cpp:5229`. Shared sequencing is
in `src/RecoveryLease.hpp:323` and `src/RecoveryLease.hpp:381`.

## Offline evidence

Focused guest and wire tests:

```sh
python3 tests/test_recovery_lease_source.py
python3 tests/test_recovery_lifetime_v3.py
python3 tests/test_critical_replay.py
```

Result: 22 tests passed (8 production-source, 7 lifetime-wire, 7 replay-wire).

Sanitized helper fixture:

```sh
g++ -std=c++17 -O1 -pthread -fsanitize=address,undefined \
  -fno-omit-frame-pointer tests/test_recovery_lease.cpp \
  -o /tmp/test_recovery_lease
ASAN_OPTIONS=detect_leaks=1 UBSAN_OPTIONS=halt_on_error=1 \
  /tmp/test_recovery_lease
```

Result: `Recovery lease v2 fixtures passed`.

The lease race fixture was also run with `g++ -fsanitize=thread`; it performs
1,000 simultaneous ownership attempts and 2,000 ACTIVE-commit/invalidation
races. Result: passed with no ThreadSanitizer report. The lifetime gate fixture
also passed under ThreadSanitizer.

The lifetime and replay C++ fixtures passed with AddressSanitizer and
UndefinedBehaviorSanitizer. The replay boundary vector is two records of 184
and 511 bytes, split into 18 chunks, and matches the host parser's exact chunk
and manifest checksums.

The source-grounded cap regression is the assertion named
`preserved VMM arena escapes the old 240 MiB cap but fits 256 MiB` in
`tests/test_recovery_lease.cpp:152`. It checks
`0x0b708000 + 0x04400000 = 0x0fb08000`, which exceeds 240 MiB and remains within
256 MiB. The preceding fixture also checks a native top-down lease followed by
the 68 MiB VMM reservation with exact half-open adjacency.

Whole production translation-unit syntax:

```sh
clang++ -fsyntax-only src/RaphaelGPU.cpp \
  -target x86_64-apple-macos10.15 -nostdinc -nostdinc++ \
  -I /home/bogdan/macos-vm/build/MacKernelSDK-master/Headers \
  -I /home/bogdan/macos-vm/build/liludbg/Lilu.kext/Contents/Resources \
  -DPRODUCT_NAME=RaphaelGPU -DMODULE_VERSION=1.0.179 \
  -DAPPLE_KEXT_ASSERTIONS=1 -fapple-kext -fno-builtin -fno-common \
  -fno-exceptions -fno-rtti -fno-asynchronous-unwind-tables -mkernel -O2 \
  -fno-c++-static-destructors -mmmx -msse -msse2 -msse3 -mssse3 \
  -mfpmath=sse -std=c++17 -Wno-deprecated-declarations
```

Result: exit 0.

Route ownership and whitespace checks:

```sh
python tools/route-domains.py src/RaphaelGPU.cpp
git diff --check
```

Results: `route binary ownership: passed`; `git diff --check` exit 0.

Exact-KDK preflight was run from a temporary mirror containing the current
repository source and preflight script, with symlinks to the existing 24G830
KDK binaries, nm listings, `route-domains.py`, and `milestones.py` under
`/home/bogdan/macos-vm`. Result:

```text
preflight: route scopes checked, constants checked, prologues checked,
recovery-v2/v3 ordering checked, patterns unique
```

This validates the exact symbols and route prologues without copying the
candidate into the deployment tree or building a kext.

An earlier broad Python discovery run occurred while the host harness was being
edited concurrently. Its current boundary was 413 passes and 15 experiment
fixture errors, all rejected at the new schema-v2 manifest gate before their
intended mocked paths. The harness agent owns that integration; these are not
counted as passing guest verification and must be green before an artifact gate.

## Astra assessment and limits

The Astra H1 is accepted as the strongest source-grounded next hypothesis:
the preserved 68 MiB VMM arena ends at `0x0fb08000`, outside the old 240 MiB
software-pool cap but within 256 MiB. The traced null path explains why VMM
allocator fields can remain absent even when the paging channel exists.

H1 remains unverified at runtime. The offline evidence does not establish that
the failed Metal mapping selected this path, that native arena clearing will
complete, or that correct GPU work follows. The first admitted hardware result
must show POOL ACTIVE and a final native VMM record with non-null `+0x58`,
`+0x78`, and `+0x80`, followed by the unchanged compute/render probe.

This implementation is intentionally one epoch per guest boot. Duplicate or
invalid lifetime transitions fail closed. A late invalidation after VALID starts
an immutable ABORT transition when BAR access remains available; an absent,
partial, ABORTING, corrupt, or ABORT marker does not authorize host recovery.
The hooks do not prove suspend/resume support or prevent mutations that a parent
native callback might perform before these routed boundaries.
The live GART must be decodable when OWNED is established; otherwise the lease
is rejected. Existing normal-cleanup evidence does not prove recovery from all
guest crashes, forced QEMU termination, or historical host hangs.
