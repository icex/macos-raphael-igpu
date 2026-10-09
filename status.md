# Live status — 2026-10-09

## Candidate374: native HiDPI cadence improves; capture teardown still blocked

Runf5fd1fe85aeb7a340b0ac52a4d78157a, metal-206, build1.0.374,
MODE2#302, bootba51b3c6. Single changed-pixel SPICE rectangle preserves snapshot
ownership. Same370 presenter/fixture: HiDPI52.56 then51.24 distinct IDs/s sampled,
native57.86; all3553 post-startup manager token samples valid. These are lower
bounds for a localized workload, not60Hz/scanout/full-frame qualification.
First source check1724 decoded valid,2 unavailable; no decoded corruption.
Desktop screenshot, USB audio capture/restoration and ordinary fallback startup
pass. Existing-user startup/consent retained. Input not rerun.

After orderly snapshot exit, ARMNotReady and staging-mapBadArgument deny reuse;
checker expected a different mapping error and exits6. Not a lifecycle pass.
Original agent restored with awake ordinary3840x2160 capture.
CORE_PROBE_PASS, earliest_failure=null. Both initial capture proofs refuse PID113
stateD and force container stop; Docker exit137, private terminal absent. Outer
exited-after-guest-request is NOT clean shutdown.373 repeat137 fix not exercised.
GPU recovery independently recovered/authorizes_launch=true. Cycle stopped;
host remains awake, vfio-pci/power-on. No reboot/rebind.
[Evidence](findings/research/console-changed-bbox-native-20261009.md) ·
[Hashes](findings/research/console-changed-bbox-native-evidence-20261009.json).

1285 host tests pass,8skip. Dev5ec383d delivers370; hosted37948929898 test/build
green.374 delivery pending, main unchanged. Next: bounded read-only D-state
refusal diagnostics without weakening gates, corrected regrant positive/negative
control, and sustained localized/full-field workload. Broader apps/codecs,
fresh-user bootstrap, crash lifecycle, other managers and VirtualBox remain open.
