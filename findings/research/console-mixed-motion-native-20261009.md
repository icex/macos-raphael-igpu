# Candidate376: sustained mixed motion, retired-buffer refusal and clean shutdown

Run35c4167dbec05e9d295b5f77b97a669c, metal207,1.0.376, MODE2#303,
bootba51b3c6-9420-4510-af69-38a42b3c79c7. RunHEAD282cd3b4185ba6698439381b26e73b52d3c530fc;
buildsource09e0e647aed19fcc3054594090256f26a5863343,
build579c3e28ca99490b831d2c06bfa38fdc,
executable95c59eeb757cdbe0541f26e3018317b48b3d4fdae875eb35cce0bd7f68f98312.
Same374 changed-bbox QEMU image96748992f5baee3b6884bc68445ceed04b6ebe2b00c6c9cbe360ad835ec2e890.
Same installed370 presenter53a18fedb172e7c774fa46b7406e7c1ebdd96d4193387a616a5945272138dd5e;
existing consent retained.377 adds read-only refusal context; eligibility unchanged.

## Function and measured scope

Three110-second fixtures alternate20-second localized token changes and smooth,
low-contrast full-field gradients. Actual-manager ROI observations last100seconds
from first valid token. Source DRAW IDs associate phases; no guest/host clock
subtraction. Full phases below exclude the brief final truncated observation.

| Case | Valid samples after startup | Invalid after startup | Startup invalid | Localized unique-ID intervals/s | Full-field unique-ID intervals/s |
|---|---:|---:|---:|---|---|
| HiDPI3840x2160 |4379|0|53|51.83–51.97|17.86–18.00|
| Native1920x1080 |5519|0|17|57.63–57.68|43.69–43.71|
| Instrumented HiDPI repeat |4367|0|34|see counter analysis|see counter analysis|

All14265 post-startup sampled tokens pass nonce/CRC/two-copy checks across330s
of requested workload and300s of observation. This is token-region integrity,
not all-pixel/fullframe/scanout qualification or universal desktop performance.
DRAW completion stays roughly60/s but does not prove composition or capture.
The presenter's source CRC checker **timed out before the first fixture** while
host controllers were prepared. This run provides no source CRC window; retain
that failure and prepare controllers before activation next time. Do not reuse
historical repeated source summaries as fresh evidence.

Actual manager screenshot c376-desktop-manager.png shows a readable ordinary
HiDPI desktop after fallback. Input was not rerun. Awake assertions remain1;
host sleep:idle blocker remains active. Physical HDMI/audio was not rerun.

## Counter discriminator and observer limit

A separately bounded125-second read-only sampler verified exact CID/StartedAt,
QEMU PID/startticks/namespace, domain metadata/UUID and uniquely discovered Bochs
BAR2. Only the snapshot diagnostic register bank was read through existing
libvirt QMP. All125 samples retain state1/error0 and counter conservation.
One-hertz polling can affect scheduling; maximum retained read bracket~102ms.

Guarded15-second localized interiors: accepted snapshots~57/s, QEMU surface
publications~51/s, manager sampled distinct IDs~51/s. Full-field interiors:
accepted~43/s, published~39/s, manager~14/s, but the timer observer itself only
runs~20/s there (291–299 samples/15s versus867 localized). Thus the lower manager
count cannot establish actual delivery rate or locate a unique bottleneck.
ACK/publication counts are not distinct source IDs. Publication is not client
presentation. Next use synchronous display-invalidate observations on the same
manager channel, retaining callback cost and widget redraw counts separately.

## Audio and lifecycle

First owned audio route attempt refused immediate post-move route verification;
no tone capture began. Original route/volume/mute/defaults and module cleanup
were independently verified. A new isolated retry passed default afplay stereo
997/1499Hz USB/QEMU/Pulse capture and independent restoration. This proves sample
delivery, not endpoint audibility or A/V synchronization; initial failure remains.

After orderly snapshot presenter exit, the corrected native control succeeds:
BAR0 maps/unmaps67108864bytes; ARM returnsNotReady; staging mapping returns
BadArgument with zero address/length. Close succeeds. This verifies bridge
regrant refusal with a functioning positive mapping control, not raw RETIRE
register readback. The original LaunchAgent SHA b1cc2d31065b3d5722782d8720029c3f0bbfd776239eb190c3a1c1ecbb858e82
is restored, ordinary3840x2160 capture starts, and display-awake assertions hold.
Client-crash retirement and production snapshot restart remain unqualified.

Closing the owned viewer leaves the exact VM alive. Harness stop-requested then
produces CORE_PROBE_PASS, earliest_failure=null, private terminal guest-shutdown
with process_exited=true. Both capture receipts record natural-container-exit,
shutdown_event_wait=true,~0.469s; console cleanEOF and critical recv-reset.
Recovery is recovered/authorizes_launch=true. This is a clean native shutdown;
374's forced-stop/D refusal remains unresolved and377 diagnostics were not
exercised here. No reboot, rebind or capture/identity/recovery gate weakening.

1298 host tests pass,8skip,53.257s. Release/debug build, source/card/archive/image
identity checks and dry-run pass. Previous374 dev hosted37951815825 test/build
passes. Broader motion/latency, crashes, fresh-user installation, other managers,
apps/codecs and VirtualBox remain open.

[Hashed artifacts](console-mixed-motion-native-evidence-20261009.json).
