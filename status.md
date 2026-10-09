# Live status — 2026-10-10

## Candidate 401: actual VirtualBox desktop, without GPU acceleration

BootC UUID `1a0740c7-3655-481e-a5f5-e7dac76dee1e` reaches the macOS desktop.
The hardware owner verified Terminal marker `VBOX401_INPUT_OK`, one vCPU,
macOS build 24G830 and awake assertions. The loader matches bootB; only the CPU
count changed from eight to one. Both runs use emulated TSC at 4294967295 Hz.
No monotonicity panic occurred during approximately 238 seconds. This supports
an SMP contribution; it does not prove the root cause or qualify sustained use.
No Raphael/VFIO device, Metal acceleration or accelerated VBox transport was used.

Shutdown was forced. A noninteractive sudo request required a password; the ACPI
shutdown dialog was confirmed, but Terminal's background caffeinate job blocked
completion. The controller powered off the VM at its deadline. Immediate
unregister failed while the GUI held its session lock. Root later verified the
exact UUID/configuration powered off, unregistered it and confirmed list absence.
Original error receipts remain intact; this is not natural guest shutdown.

## Candidate 399: accelerated-console timing result

QEMU run `1849f3959a4a38e15836c9364554f76f` ended with verified private guest
shutdown/process exit, Docker exit 0 without kill events and authorizing recovery.
Both capture receipts report `container-stopped-during-shutdown-wait` with deferred
and event-wait flags. CR2 snapshot 18 retains 365 records, zero corrupt lines and
no incomplete snapshots under terminal-prefix tolerance.

The 4K manager observation contains 4036 unique token IDs in 100.006 seconds with
zero invalid/duplicate samples; the short final phase is excluded. Host snapshot
copy including first touch averages 6.834 ms, allocation 0.02058 ms and pending free
0.09521 ms; guest doorbell averages 6.983 ms. This measures cost, not an optimization.
The late `c399-desktop.png` captured the wrong host window and is excluded from
returned-desktop evidence. Input/audio qualification remains scoped to prior runs.

Both the 399 GPU cycle and 401 software VM are stopped. Root owns later launches.
Evidence: `findings/research/console-host-snapshot-timing-native-20261010.md` and
`findings/research/virtualbox-single-cpu-native-20261010.md`.

## Local validation and publication

Candidate 404 integrates 399 instrumentation/tested binary and 401 software desktop
and input evidence. The checked-in executable is exact tested 399 build
`f868a8dae9664e469b2011390547c5ca`, source
`b7e17c09679eb3e78e1be9895d2d5be550a06391`, SHA256
`d8257d14791c7f1cee6050c250a4327cb35bde75e0bf0036c1bbc470b939ceaa`.
Its binary and manifest match the canonical archive byte for byte and the native
run identity; receipt: `run/c404-binary-provenance.json`.

Integrated host suite: 1469 tests passed, 8 skipped, 56.196 seconds
(`run/c404-full-suite.log`). Published commit refs and their hosted test/build
results are tracked in [GitHub Actions](https://github.com/icex/macos-raphael-igpu/actions).
The preceding `c1f64d0` milestone has verified green hosted test/build results.
Main's physical 330 baseline is unchanged. VirtualBox Metal/GPU transport, SMP
timekeeping, graceful GUI shutdown, 4K at 60 Hz and first-user console-only installation
remain open. A software desktop is not acceleration.
