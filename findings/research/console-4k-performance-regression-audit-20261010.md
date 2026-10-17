# Current priority: full-field4K performance in a normal QEMU window

The user requested all other roadmap work halted and no fullscreen host viewer.
Native framebuffer/120/5K work is preserved but not pursued. The target is usable
full-screen changing4K guest content; host windows stay normal-sized.

## Historical evidence

| Run | Actual guest source | Viewer | Localized decodedIDs/s | Full-field decodedIDs/s |
| --- | --- | --- | --- | --- |
| 397 | 3840×2160 scale1,60draw/s mixed | 1440×900/GDK1 scaled | ~51 | ~27 |
| 399 | Same | Same | 48.84–51.05 | 26.39–26.40 |
| 402 | Same, private host pool | Same | 57.14–57.43 | 24.87–25.15 |
| 430b | 1920×1080logical/3840×2160 backing, source60 despite120label | Same | 58.84–60.03 | 26.85–26.86 |

These comparable observations do not establish a new regression. They are decoded
token observations, not full-frame pixel validation, physical scanout or GPU FPS.
There was one sequential trial per configuration, host workload was not isolated,
and430 changes source scale/SPICErefresh. The final short phases are excluded.

Older381 holds4K source dimensions and changes physical viewport: scaled2560×1440
observed14.42/14.47 full-field IDs/s; matched3840×2160 observed34.50/34.94. However
its transport predates the402 pool and it is not an identical current control.
This supports examining renderer/scaler cost, not declaring a new transport gain.

The399→402 pool reduced host snapshot copy6.834→1.948ms and doorbell6.983→1.969ms,
while full-field client throughput remained about25–26/s. Lower copy cost alone
did not fix the full-field limit. Earlier366/347 observations contain invalid/torn
tokens and different producer cadence; their isolated higher rates are not clean
regression baselines.

Primary reports: console-snapshot-timing-native-20261009.md,
console-host-snapshot-timing-native-20261010.md,
console-snapshot-private-pool-native-20261010.md,
console-viewport-native-20261009.md and console-holder-comparison-20261010.md.
Raw analyses are under ~/macos-vm/run/c397-,c399-,c402-,c381-,c430-fourk-analysis.json.

## Fresh control

436 keeps the working GPU source and pool image, explicitSPICE60, same sealed
presenter,4K Retina source and1440×900 normal host window. Verify actual source
geometry/clock, viewport, errors and source→capture→publication→client counts.
Do not start host fullscreen or automatically grab keyboard/mouse. No other
roadmap experiments run concurrently. Host user activity is recorded as an
uncontrolled scheduling factor rather than stopped or treated as a regression.

435's proposed fullscreen attempts never produced valid measurements: combined
monitor geometry refused the exact viewport. Their empty results are excluded.
435 passed baselineMetal and later powered off; capture hooks aborted, recovery
authorized reuse. This does not prove clean shutdown or explain the initiating
poweroff. Next cycle is a performance control, not another native driver test.

## Candidate 436 completed control and attribution

Two 100-second controls B/C used actual 3840×2160 scale-1 source, approximately
60 draws/s, 1440×900/GDK1 viewer. Localized phases observed 55–57 IDs/s; full-field
phases 24.86–26.64. Both had zero invalid/duplicate tokens. Short final phases are
excluded. C was intended as Retina but reverted to scale 1: classify it as another
scale-1 control. E initially selected 1920×1080 logical with 3840×2160 backing,
then reverted and yielded 5459 invalid / 39 unique tokens; exclude throughput.

Raw B/C analyses: ~/macos-vm/run/c436-fourk-b-analysis.json and
c436-retina-c-analysis.json. No comparable new regression is established.

QEMU perf was taken during E, so it is hotspot evidence rather than a valid
Retina throughput comparison. Perf initially resolved host binaries; discard
those function labels. Container qemu ELF build ID a236e75e53a2e5eb5e352048d63948828f3f22c5
and raw DSO offsets 0x6e2f54/0x6e2f59 resolve to rgpu_diff_bbox, line 49.
The exact ELF and raw samples are retained under c436-perf-dso/ and
c436-qemu-perf-raw.txt. Optimize unchanged border comparisons with exact rectangle
equivalence, then test identical geometry/source/viewer against B/C. This is a
hypothesis, not an established cause of the entire full-field limit.

Run 8192b942c66179da66fcda9d9cc957a8 ended through the harness: guest-requested
exit and natural capture exits, private terminal verification; stopped-container
inspection reconciliation unavailable/mismatched. Recovery authorizes same-boot
reuse. No runner was killed; no new feature milestone is claimed.
