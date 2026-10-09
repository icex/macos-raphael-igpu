# Live status —2026-10-10

## Candidate397: stage timings measured; no optimization claimed

Run `beb488f101c8ed33f8460d4a5ce6ce5e`, metal220, version1.0.397.
Build ID `997d0d87122748708e34a1fa05c70f08`, executable SHA256
`7a9bae3f74471c1b26b4f7d15144283776ef7c9a7ef7203f984075d4b99b599b`.
Manifest source9d5bb8b, built-from19b77a0. Opt-in stage timing only;
private staging ownership/cache/commit behavior remains the qualified395 design.

Actual manager4K source,1440×900/GDK1 viewport:4160 unique token IDs/100.023s,
zero invalid/duplicate samples. Localized phases~51/s, full-field~27/s;
phase5 short53-sample tail is not qualified. Normal desktop returned and was
visually verified. No new audio/input/full-frame/60Hz qualification.

61 kernel metric rows have intact numeric stages/counts/dropped;24 trailing
saturated flags are truncated. Motion windows37..58 contain5227 commits:
copy+fence1.549ms, geometry0.236ms, doorbell6.872ms, ACK checks1.316ms means.
Windows are not phase-aligned; the dominant doorbell interval is not solely
attributed to memcpy or a specific host routine. This is a measured discriminator,
not a performance gain/regression or implemented optimization.

CORE_PROBE_PASS, earliest failure null. CR2 replay snapshot18/365 records retains
one malformed line and incomplete snapshot7/76chunks/noEND. Shutdown is
exited-after-guest-request with private_terminal_verified=true. Both capture hooks
natural-container-exit/deferred/shutdown_event_wait=true~1.660s; console EOF,
critical recv-reset. Private guest-shutdown/process-exited and Docker exit0/no
container kills independently support natural completion. Recovery recovered,
authorizes_launch=true. GPU cycle ended; root owns subsequent software/native work.

Evidence: findings/research/console-snapshot-timing-native-20261009.md and its
26-artifact hash manifest, run/candidate-397-results, c397-fourk-analysis.json,
c397-kernel-timing-analysis.json. Capture imperfections remain explicit.

Last delivered dev: c1f64d055fb1161f55281972912d0cf4c4178f2f (tested395),
hosted37988921669 test/build green; main unchanged.396/397 remain candidate work.
Next discriminate doorbell/host snapshot work before optimizing.398 separately
prepares independent VBox disks/controller; no VirtualBox macOS boot, physical
passthrough or accelerated rendering qualification is claimed.


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-399-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`
