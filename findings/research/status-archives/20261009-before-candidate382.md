# Live status — 2026-10-09

## Candidate381: pixel-matched console windows avoid a major scaling bottleneck

Run96304b2a4befa1d44b4ce442c295a86d,metal209,1.0.381,MODE2#305,
bootba51b3c6. Same374 changed-bbox image and installed370 presenter/consent.
Three110s mixed fixtures,300s synchronous actual-manager ROI observation.
3840×2160 guest in1280×720 logical/GDK2 viewport: full-field14.42/14.47
observed IDs/s. Same4K guest in1920×1080/GDK2:34.50/34.94.
2560×1440 guest in1280×720/GDK2:57.58/57.50. Geometry verified throughout.
This supports avoiding client scaling; it does not qualify universal60Hz,
arbitrary-window resize or all VM managers. Upstream ACK changes remain explicit.

14,160 valid manager token samples,22 startup-invalid,0 post-start invalid.
One terminating callback in matched4K was unfinished and has no decoded sample
or completed cost. First nonce alone has30s source checks:1583 valid,7 unavailable,
0CRC/torn; it does not cover all cases. Candidate379 rare errors remain unresolved.
Whole-window draw costs are not phase-specific GPU/scanout times.

Audio first attempt refused a route change and restored independently; retry
passes48k stereo997/1499Hz, independently restored route/volume/mute/defaults/module.
Retired snapshot owner denies ARM/staging regrant; positive legacyBAR0 mapping
passes. Original agent restored, awake3840×2160 ordinary capture and readable
actual-manager screenshot verified. Viewer closure preserves exact VM identity.
Input not rerun; endpoint audibility/A-V sync unqualified.

CORE_PROBE_PASS/earliest_failure=null. Private terminal guest-shutdown and
process_exited=true; Docker die exit0 with no kill/stop. Both captures complete
via container-stopped-during-shutdown-wait (~0.394s), shutdown_event_wait=true,
deferred=true, completed_original_zombie=false; witness exit137 is not VM exit.
Console clean EOF, critical recv-reset retained. Parser retains terminal-prefix
incomplete snapshot7 (404 chunks,no end), corrupt_lines0; terminal snapshot18.
Recovery recovered/authorizes_launch=true. Cycle stopped; host awake,vfio-pci/on.
374 forced-stop D-state race remains unresolved;377 diagnostics not exercised.

1318 host tests pass,8skip before run; exact build/identity/dry-run pass.
Delivery suite:1318 tests pass,8skip (48.991s). Delivered to dev447131e; exact-commit hosted37963569176 test/build green,
release skipped. Main unchanged. Next: bounded standard SPICE
resize transport and remaining4K throughput/correctness/lifecycle qualification.
AppleVirtIOConsole personality exists in guest24G830; attachment/tty untested.
[Evidence](findings/research/console-viewport-native-20261009.md) ·
[Hashes](findings/research/console-viewport-native-evidence-20261009.json).


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-382-results`
- Verdict: `INVALID`
- Boundary: `identity_or_route_missing`
