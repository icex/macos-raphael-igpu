# Candidate347: native ROI observer and successful controller shutdown

Run `fe659d623c40c9650ca999f83ae39635`, metal-191, build1.0.347,
MODE2#286 on bootba51b3c6. Native Metal, WindowServer ownership and display-on-device
checks pass. Same driver and explicit SPICE60 image as345; stock image remains default.
Display-awake assertions are verified. All four fixtures finish, the normal desktop
returns (actual manager screenshot inspected), and closing the viewer preserves the guest.

## Fresh paired measurements

Actual virt-manager, one connection, sequential full-native/ROI-native/full-HiDPI/
ROI-HiDPI cases, fresh nonces,60-second AppKit fixtures,30-second sample windows,
16ms timer. Native1920×1080 and HiDPI3840×2160 both have1920×1080 logical size.
ROI loads the explicitly hashed local extension, reacquiring its surface every callback.

| Observer/mode | Distinct tokens | Tokens/s | Median sampling ms | Invalid after first valid | Guest draws in60s |
|---|---:|---:|---:|---:|---:|
|full-native|915|30.497|2.228|22|1994|
|roi-native|910|30.323|1.363|20|2086|
|full-hidpi|590|19.664|5.222|98|2032|
|roi-hidpi|756|25.198|1.452|88|3021|

ROI reduces observer cost in both modes. Native delivery is effectively unchanged;
HiDPI sampled delivery improves in this sequential pair. This is one matched run,
not randomized repeated performance qualification.345's earlier50updates/s native
result is not reproduced here; guest draw production also varies. These are sampled
buffer tokens, not GPU fps, host scanout, complete atomic frames or absolute latency.
Intermediate token failures remain. The optional observer retains the default full
pixbuf mode and does not alter presentation. [Software controls](console-roi-observer-20261009.md).

The guest presenter reports about20ms in its combined buffer-lock/copy interval
at HiDPI, with dropped capture callbacks. That interval does not isolate memcpy:
next split lock, copy/fence and unlock timing before selecting an optimization.

## Capture and shutdown

CORE_PROBE_PASS, earliest_failure=null. Outer shutdown: exited-after-guest-request.
Actual identity-bound terminal.json records guest-shutdown/process_exited=true.
Both EOF hooks defer and record natural-container-exit in about0.386seconds.
GPU recovery is recovered, authorizes_launch=true. VM/cycle stopped; host remains
awake. No reboot/rebind.

**The new completed-zombie branch was not exercised:** both hook receipts have
completed_original_zombie=false (original process already reaped). This validates
another native natural exit with the change present, not the race-specific fix.
The exact completed-zombie proof has real software-QEMU and live-worker rejection
controls; native zombie-branch coverage remains open.
[Proof and software evidence](libvirt-zombie-20261009.md).

## Build and delivery

1176 host tests pass,8 skipped; the5 optional real ROI-extension guard tests pass
separately. Build source9ea6d79908b48447621a79cd0abc0a3348caa8de;
run/card commit729356700cf99105cc028d3cd809ae0c27826cb5.
Checked-in executable and manifest match347. No physical-HDMI qualification added.
Use `tools/cycle.py --candidate 347 --card metal-191 --pins experiments/pins-spice60.json`.
[Artifacts and hashes](console-roi-native-evidence-20261009.json).
