# Live status — 2026-10-10

## Candidate401: actual VirtualBox desktop, without GPU acceleration

BootC UUID `1a0740c7-3655-481e-a5f5-e7dac76dee1e` reaches the macOS desktop.
The hardware owner verified Terminal marker `VBOX401_INPUT_OK`, one vCPU,
macOS build24G830 and awake assertions. The loader matches bootB; only the CPU
count changed from eight to one. Both runs use emulated TSC at4294967295Hz.
No monotonicity panic occurred during approximately238 seconds. This supports
an SMP contribution; it does not prove the root cause or qualify sustained use.
No Raphael/VFIO device, Metal acceleration or accelerated VBox transport was used.

Shutdown was forced. A noninteractive sudo request required a password; the ACPI
shutdown dialog was confirmed, but Terminal's background caffeinate job blocked
completion. The controller powered off the VM at its deadline. Immediate
unregister failed while the GUI held its session lock. Root later verified the
exact UUID/configuration powered off, unregistered it and confirmed list absence.
Original error receipts remain intact; this is not natural guest shutdown.

## Candidate399: accelerated-console timing result

QEMU run `1849f3959a4a38e15836c9364554f76f` ended with verified private guest
shutdown/process exit, Docker exit0 without kill events and authorizing recovery.
Both capture receipts report `container-stopped-during-shutdown-wait` with deferred
and event-wait flags. CR2 snapshot18 retains365 records, zero corrupt lines and
no incomplete snapshots under terminal-prefix tolerance.

The4K manager observation contains4036 unique token IDs in100.006 seconds with
zero invalid/duplicate samples; the short final phase is excluded. Host snapshot
copy including first touch averages6.834ms, allocation0.02058ms and pending free
0.09521ms; guest doorbell averages6.983ms. This measures cost, not an optimization.
The late `c399-desktop.png` captured the wrong host window and is excluded from
returned-desktop evidence. Input/audio qualification remains scoped to prior runs.

Both the399 GPU cycle and401 software VM are stopped. Root owns later launches.
Evidence: `findings/research/console-host-snapshot-timing-native-20261010.md` and
`findings/research/virtualbox-single-cpu-native-20261010.md`.

## Delivery preparation

Candidate404 integrates399 instrumentation/tested binary and401 software desktop
and input evidence. The checked-in executable is exact tested399 build
`f868a8dae9664e469b2011390547c5ca`, source
`b7e17c09679eb3e78e1be9895d2d5be550a06391`, SHA256
`d8257d14791c7f1cee6050c250a4327cb35bde75e0bf0036c1bbc470b939ceaa`.
Its binary and manifest match the canonical archive byte for byte and the native
run identity; receipt: `run/c404-binary-provenance.json`.

Integrated host suite:1469 tests passed,8 skipped,56.196s
(`run/c404-full-suite.log`). Root review, dev push and hosted CI are pending;
last completed delivery remains `c1f64d0`/tested395 with green hosted CI.
Main's physical330 baseline is unchanged. VirtualBox Metal/GPU transport, SMP
timekeeping, graceful GUI shutdown,4K60 and first-user console-only installation
remain open. A software desktop is not acceleration.
