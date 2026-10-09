# Live status — 2026-10-09

## Candidate352: full-refresh copy improvement; exact shutdown refusal captured

Run `7904cfef4aaa37f79efe02f604d921ac`, metal-195, build1.0.352,
MODE2#290, bootba51b3c6. Native Metal/WindowServer/display pass. Experimental
Bochs full refresh disables only VGA dirty logging at explicit SPICE60;
default image/profile and migration tracking unchanged. HiDPI row copies now
~1.48ms versus prior~16ms; all16 captured-frame byte checks pass.

Actual manager delivery44.186/50.084 native and31.758/34.882 HiDPI updates/s
(full/ROI observers). All fixtures finish, diagnostic flag removed and normal
desktop restored. Fixture itself produces~37–38HiDPI draws/s; no60Hz ceiling,
GPU FPS, atomicity or full desktop qualification claim. Next353 uses the SAME
image/presenter with full-refresh absent/OFF for a controlled CPU/cadence baseline.

Capture CORE_PROBE_PASS, earliest_failure=null. Outer shutdown:
exited-after-guest-request. Terminal absent: both EOF hooks (~0.370s) see PID113
stateZ with two tasks, completion_reason=not-sole-task. Keep strict proof;
investigate remaining-thread shutdown ordering. GPU recovery recovered,
authorizes_launch=true. VM/cycle stopped, host awake; no reboot/rebind needed.

1188 host tests pass,8skip; kext/manifest match352. Changes local, dev277ff81
hosted CI green, main unchanged. General desktop, lifecycle, window resize,
console audio/install durability and VirtualBox qualification remain open.
[Evidence](findings/research/bochs-full-refresh-native-20261009.md) ·
[Raw samples/receipts](findings/research/bochs-full-refresh-native-evidence-20261009.json) ·
[Previous status](findings/research/status-archives/status-before-352-20261009.md).


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-353-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`
