# Candidate374: changed-rectangle native performance improvement

Runf5fd1fe85aeb7a340b0ac52a4d78157a, metal-206, version1.0.374,
build225e2e5708344c8bbe3f4764c88064e1, source7e3f670,
runHEAD ee7c84e8715aaad48bc5a10ff0cd7970f6f5b6c4, MODE2#302, bootba51b3c6.

## Controlled change

The separately pinned image
96748992f5baee3b6884bc68445ceed04b6ebe2b00c6c9cbe360ad835ec2e890
adds one changed-pixel bounding rectangle versus the initialized SPICE mirror.
First/changed-size surfaces get a full update; unchanged frames get none. Snapshot
staging, one-shot ownership and acknowledged immutable surfaces are unchanged.
The exact image passes full-pixel black/colored/resize/4K software controls;
[software/image evidence](console-changed-bbox-software-20261009.md).
All182 dependencies, base layers and runtime config match the prior base.

The installed370 presenter SHA53a18fedb172e7c774fa46b7406e7c1ebdd96d4193387a616a5945272138dd5e
starts automatically on this guest boot with existing consent, then arms once.
No reinstallation or permission renewal is needed. Native fixture executable
2140622c3a79c95d55b290e56d321dd05006822370044358f0e4daa386e3bb47 and actual-manager
ROI extension eef02417a5e190031c827e481bf9c0512d401e7af66cc2ecef6eca9956df8d8c
match370. Same nonce/CRC/two-copy protocol, new nonce per case, explicit60Hz,
mode order HiDPI→native→HiDPI and20s observers are retained. First fixture60s,
repeats30s. No heavy software work or overlapping guest relays during measurement.
A separate host shutdown-witness137 fix is present but does not affect display;
its new branch was not exercised during374 teardown.

## Native observations

| Case | Valid manager samples / after-startup samples | Invalid | Distinct IDs/s,370 →374 |
|---|---:|---:|---:|
|1080HiDPI /3840x2160|1158 /1158|0|14.239 →52.557|
|Native1920x1080|1238 /1238|0|41.008 →57.861|
|HiDPI again|1157 /1157|0|14.314 →51.235|

All3553 post-startup samples are valid. Startup errors52/41/9 respectively are
retained separately; exact categories/counts are in manager-analysis.json.
The comparison is a sampling lower-bound improvement, not exact delivery/scanout
or GPU FPS. Observer scheduling improves too; it must not be subtracted from
presenter/source rates to infer an exact number of lost frames. The20s windows
do not qualify sustained60Hz or full-frame integrity across arbitrary content.

Only the first case has a new30s source check:1724 decoded valid tokens,2 unavailable,
1722 unique/2duplicates, no decoded CRC/torn/backward failures.1100 manager samples
bracketed by valid interior source IDs are valid. Later logs repeat this completed
source summary; they do not add source-check coverage. Busy-dropped and uncaptured
upstream frames remain excluded. Steady presenter processing is about57.8frames/s,
lock3.5–3.7ms, row copy1.65–1.69ms, commit7.3–7.4ms and worker12.5–12.8ms.
These timings are not GPU FPS or isolated memcpy costs. The fixture mostly changes
a small token band; whole-field/mixed-motion endurance is the next discriminator.

The actual manager desktop screenshot is readable without visible corruption.
Ordinary default afplay USB/QEMU/Pulse stereo997/1499Hz phases pass; original
routing, volume, mute, defaults and owned-module removal are independently verified.
No endpoint audibility/A-V sync or new input result is claimed.

## Regrant control and fallback

A separately compiled native control runs after orderly snapshot-owner exit.
ARM returns NotReady(e00002d8), staging-map1 returns BadArgument(e00002c2), close0.
No staging mapping is granted. However the checker expected NotReady for both
operations and exits6; this is a failed checker result, not a completed lifecycle
qualification. Next add successful BAR0 mapping as a positive control and require
denied BAR1 without over-specific failure-code assumptions. No RETIRE register
readback or presenter-crash/client-death result is established here.

Regardless of that checker failure, the restore script bootstraps the exact original
LaunchAgent SHA b1cc2d31065b3d5722782d8720029c3f0bbfd776239eb190c3a1c1ecbb858e82,
verifies fresh ordinary3840x2160 capture and awake assertions, then raises the test
failure. The guest relay's host exit0 is not evidence the checker passed; retained
output contains the failed result. Closing the owned viewer leaves the same VM alive.

## Shutdown, capture and recovery are separate

CORE_PROBE_PASS, earliest_failure=null; outer shutdown.json says
exited-after-guest-request. **This is not a clean-shutdown pass:** both initial
capture witnesses see original PID113 in D state, refuse and invoke immediate-stop.
Both have deferred=false; console observes cleanEOF, critical recv-reset. Docker
records SIGTERM/SIGKILL and container exit137. The private terminal.json is absent;
there is a bound guest SHUTDOWN event but no private completion receipt.
Do not infer process completion from the outer harness outcome. The373 eligible
repeat-witness137 fix never runs because the initial proof is refused.

Recovery independently records recovered/authorizes_launch=true. The cycle is
stopped; GPU stays vfio-pci/power-on and host sleep:idle inhibition remains active.
No reboot/rebind.1285 host tests pass,8skip before exposure; deep build/card/image
and dry-run checks pass. Next preserve D-state refusal while collecting bounded
read-only process diagnostics, fix the regrant checker, then perform sustained
localized/full-field testing. Neither this performance milestone nor publication
qualifies all lifecycle paths, broader apps/codecs, other managers or VirtualBox.
[Artifact hashes](console-changed-bbox-native-evidence-20261009.json).
