# Candidate348: presenter timing blocked by TCC, approved desktop restored

Run `c03cf6652ba2207e7b28074331e7e003`, metal-192, build1.0.348,
MODE2#287, bootba51b3c6. Initial native Metal/WindowServer/display checks pass.
The instrumented presenter compiles inside macOS; compiled source SHA256
`d94b47c7c8b7dff47568f9d2d38d04025caa37448cccd2df06d949fda2ab5666`,
binary SHA256`e7480a068948697689e693fd2be5fdf643573531cd9c544d81c9aaa57d1a1021`.
The old app is backed up before replacement. Its replacement ad-hoc signature
is not accepted by ScreenCaptureKit: TCC error-3801, user declined capture.
The user cannot access settings now. No permission database or policy is changed.

The attempted ROI-native measurement is **invalid**: the presenter was absent,
the orchestration stops at a missing measurement summary, and its final sampler
has no valid tokens. Its AppKit fixture is stopped/removed, and its viewer closed.
No split lock/copy timing or performance improvement is established.

The original approved bundle is restored from the backup; executable SHA256
`3deb9ea3880084ebadd9708686ef625f8568e65bb90299ca6b19c080ecbab59b`.
The presenter runs again, emits frames, and the actual manager screenshot shows
macOS settings/desktop. The new instrumented bundle is retained separately.
Display-awake assertions remain active. The timing test remains pending explicit
macOS permission; continue independently with own synthetic buffers, which do
not capture screen contents and cannot model SCK/GPU producer synchronization.

Capture: CORE_PROBE_PASS, earliest_failure=null. Outer shutdown:
exited-after-guest-request. Actual terminal.json: guest-shutdown/process_exited=true.
Both EOF handlers defer to natural-container-exit in about0.626s; completed zombie
branch=false (already reaped). Recovery: recovered, authorizes_launch=true.
VM/cycle stopped, host awake, no reboot/rebind needed.

1177 local host tests pass,8 skipped. This candidate is not a delivered timing
milestone. Dev277ff81 separately fixes the hosted process-test portability issue;
[hosted tests and macOS build pass](https://github.com/icex/macos-raphael-igpu/actions/runs/37919797361).
[Artifacts and hashes](console-timing-tcc-evidence-20261009.json).
