# Live status — 2026-10-09

## Candidate370: snapshot console tokens pass; performance remains open

Run5059bb80d8140ba8234bc31fb7fda4fc, metal-205, build1.0.370,
MODE2#301, bootba51b3c6. Native opt-in immutable QEMU snapshots plus single-rectangle
SPICE updates: HiDPI389/389, native851/851, HiDPI-repeat384/384 manager samples
valid after connection startup. Correct desktop screenshot; default USB audio
capture and independently checked routing restoration pass. Input not rerun.
First source window1284 decoded valid,17 unavailable; no decoded corruption.
HiDPI14.24/14.31 distinct IDs/s and native41.01 are observer lower bounds, not
scanout/GPU FPS or60Hz qualification. Combined changes do not isolate one cause.

Normal Screen Recording consent renewal and orderly BAR0 fallback startup pass;
original LaunchAgent restored exactly. One-shot lease must not be rearmed within
the same device lifetime; crash/re-ARM refusal and explicit retirement not tested.
CORE_PROBE_PASS, earliest_failure=null; genuine guest-shutdown/process_exited,
exited-after-guest-request. Both capture hooks instead report immediate-stop,
CommandFailure137 at exit-wait~0.384s; do not claim natural capture exit. Recovery
recovered/authorizes_launch=true. Cycle stopped; host remains awake. No reboot/rebind.
[Evidence](findings/research/console-snapshot-native-20261009.md) ·
[Hashes](findings/research/console-snapshot-native-evidence-20261009.json).

1274 host tests pass,8skip, including delivery checks. Candidate370 tested kext
and milestone docs are integrated into dev; hosted validation pending. Prior368
hosted37944403991 test/build green. Main unchanged. Next: investigate capture
wait-witness race and test single changed-pixel rectangle in software before next
native comparison. Fresh-user bootstrap, sustained performance, repeated crash
lifecycle, broader apps/codecs, other managers and VirtualBox remain open.
