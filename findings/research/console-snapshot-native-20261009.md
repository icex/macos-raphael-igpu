# Candidate370: immutable snapshots in the native VM-manager console

Run5059bb80d8140ba8234bc31fb7fda4fc, metal-205, version1.0.370,
build5dd91fea9b9340a2a6aa020c70c6b0d4, build source11f0440,
runHEAD7f202822fae359aaafc4812b41e0752594797473; MODE2#301, bootba51b3c6.

## Change and controls

The experimental QEMU image bba6164ddc5e1a6ca75b891f38c0fdc0a778cdc07fda13abb6e753f4259a5a55
adds a separate32MiB Bochs staging BAR, a one-shot ownership lease and synchronous
copy acknowledgements. Each commit creates a QEMU-owned immutable surface; the guest
can reuse staging only after ACK. SPICE emits one bounding rectangle per update.
Both interventions are combined here, so this run does not isolate their contributions.
Software overwrite-after-ACK/full-pixel and token controls precede this run;
[software evidence](console-snapshot-software-20261009.md).

The exact container-built QEMU executable is
7c94c7e7287faf7acc7b432c0d45fb43237be16821f03bd6599baf3302b6c300.
Snapshot is opt-in in both the exact launch contract and guest presenter; stock
pins/default BAR0 path remain unchanged. Migration is refused when snapshot is on.
The copied checked-in driver matches the hardware-tested release archive; this is
an experimental feature, not a production release or general restart protocol.

Native Appleclang17/SDK15.5 compilation and transactional installation succeeded.
Presenter SHA53a18fedb172e7c774fa46b7406e7c1ebdd96d4193387a616a5945272138dd5e,
source package SHA2de9bd21d28b11acc4cb9f8f5e1b370b316a35be4f776b35728b48938dde84ee.
Normal capture initially failed TCC-3801 after the signature changed. Normal
Screen Recording Settings renewal restored capture; no TCC database/policy edits.
Snapshot remained disabled until that succeeded, then armed once after SCK started.
Fresh logs confirm SnapshotProtocol1, armed=1 and acknowledged commits.
Original LaunchAgent bytes were restored on disk while its live process kept the
snapshot environment. Awake assertions were verified. No concurrent guest relays
or heavy builds ran during measurement.

## Observed output

| Case, sequential within one lease | Valid manager samples after first valid | Invalid after first valid | Distinct IDs/s sampled |
|---|---:|---:|---:|
| 1920x1080 HiDPI /3840x2160 pixels |389|0|14.239|
| Native1920x1080 |851|0|41.008|
| HiDPI again |384|0|14.314|

Each observer runs20s after its first valid token inside actual virt-manager,
using the exact native ROI extension. Startup failures are retained separately:
51,37,14 respectively, all before first valid sample. Fresh finite prerendered
fixtures use different nonces. The first case lasts60s; repeats30s. Mode changes
occur without restarting the snapshot owner. A real manager screenshot shows a
correct desktop after the first fixture. Input was not rerun.

Only the first HiDPI case has a new30s capture-source diagnostic window:1284 decoded
source tokens valid,17 unavailable observations, zero decoded CRC/torn/backward
failures. The unavailable bucket combines several conditions and is not identified
more precisely.1282 unique/2duplicate; firstID1,lastID1783. Busy-dropped/upstream
uncaptured frames are excluded.361 manager samples bracketed by valid interior
source IDs are all valid. Later logs repeat that completed source summary; they
are not new source measurements.

These results improve on368's partial manager tokens, but do not prove complete
frame atomicity or all desktop workloads. HiDPI observer sampling was only about
19.45 samples/s; distinct ID rates are lower bounds, not delivery/scanout/GPU FPS.
Presenter steady copies are about42/s, synchronous snapshot_commit about10ms and
worker total about16.6ms. Commit includes MMIO exits, copying and scheduling/BQL
waits; it is not an isolated memcpy measurement. Full-frame SPICE work remains a
performance hypothesis.60Hz output is unqualified.

## Audio, fallback and lifecycle

Ordinary default afplay through USB/QEMU/Pulse passes stereo997/1499Hz channel
order/silence checks. Capture and tone exit0. Original route, volume, mute, defaults
and owned-module removal were independently verified. Endpoint audibility, other
applications and A/V synchronization remain unqualified.

Orderly snapshot-owner bootout followed by the original ordinary LaunchAgent
produces fresh3840x2160 BAR0 capture with no snapshot log, and awake assertions.
Original plist SHA b1cc2d31065b3d5722782d8720029c3f0bbfd776239eb190c3a1c1ecbb858e82
is restored exactly. This verifies fallback capture startup, not explicit RETIRE
readback or same-guest re-ARM refusal. No presenter crash/re-ARM test was performed.
Closing the owned viewer leaves the exact VM alive.

CORE_PROBE_PASS, earliest_failure=null; genuine private guest-shutdown terminal
with process_exited=true and harness exited-after-guest-request. GPU recovery is
recovered/authorizes_launch=true. However both capture hooks enter shutdown-event
wait then report CommandFailure137 at exit-wait after~0.384s, outcome immediate-stop.
Console saw cleanEOF; critical saw recv-reset. These are NOT natural-capture-exit
passes; the wait-witness/container-exit race remains under investigation. Preserve
this distinction despite valid probe/recovery and completed guest shutdown.

1274 host tests passed,8skip before exposure; identity/build/card/dry-run gates
passed. Cycle is stopped; host sleep:idle inhibitor remains active. No reboot/rebind.
Next: explain the capture-wait race, then software-qualify a single changed-pixel
bounding rectangle to reduce transport work while preserving immutable ownership.
[Artifact hashes](console-snapshot-native-evidence-20261009.json).
