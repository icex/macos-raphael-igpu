# Live status — 2026-10-09

## Candidate348: timing blocked by capture permission; desktop restored

Run `c03cf6652ba2207e7b28074331e7e003`, metal-192, build1.0.348,
MODE2#287, bootba51b3c6. Native Metal/WindowServer/display checks pass.
Instrumented presenter compiles but ScreenCaptureKit rejects its changed signature
with TCC-3801. User cannot access settings now; no permission-policy bypass.
Attempted timing measurement invalid, no phase measurements or performance claim.
Original approved bundle restored; presenter frames and actual manager desktop
screenshot verified. New instrumented bundle retained separately.

Capture: CORE_PROBE_PASS, earliest_failure=null. Shutdown:
exited-after-guest-request, genuine controller terminal guest-shutdown/process exit.
Both EOF hooks natural-container-exit, completed zombie branch=false. Recovery:
recovered, authorizes_launch=true. VM/cycle stopped, host sleep:idle inhibitor
active. No reboot/rebind needed.

Next: synthetic CPU/IOSurface source copies into RAM and existing Bochs WC mapping,
with bounded timing and readback; no screen capture. This cannot reproduce SCK
producer synchronization. Native phase timing remains pending macOS permission.
347's delivered paired observer evidence remains valid; partial presentation,
automatic resize and broader lifecycle/desktop/boot qualification remain open.
1177 local tests pass,8 skipped. Dev277ff81 includes the hosted zombie-test fix;
hosted tests and macOS build both pass (run37919797361). Main unchanged.
[348 evidence](findings/research/console-timing-tcc-20261009.md) ·
[347 milestone](findings/research/console-roi-native-20261009.md) ·
[Previous status](findings/research/status-archives/status-before-348-20261009.md).
