# Dynamic update compatibility: candidate 490

The same executable is verified on the latest requested/tested macOS15 and26
releases. Source2851b70c7cc3a1ee780cf4ad6004fbcda0c2db69, build
2daaac6345c144ee8cf968b73779ca7f, executable SHA256
242c97440e4c89925f40727870a7a0610cce860612cd1ad4c60ac98bb7301d83.

| System | Run | Rendering and capture | Shutdown and recovery |
| --- | --- | --- | --- |
|15.8.1 / 24H32 |f180fe096265ffef07892be523c8022e |61,274,112 pixels,0 errors; UID501 window119.9995fps; visible QEMU desktop |Native request,QEMU0; ordinary recovery authorizes |
|26.7.1 / 25G241 |de9b90614341d07412bdb2af6162043a |61,274,112 pixels,0 errors; correct moving self-captures; locked session,FPS unqualified |Native request,QEMU0; ordinary recovery authorizes |
|26.6 / 25G72 |b155128029f53a1ce9997d1e503c9d09 |61,274,112 pixels,0 errors; correct moving self-captures; FPS unqualified |Native request,QEMU0; ordinary recovery authorizes |

All three show Metal3, display on Navi23, WindowServer accelerator client and
all164 dynamically resolved kernel sites. No probe self patching is required.
Kernel entry families retain exact native object fields/call slots, moved
interior sites stay uniquely bounded by their owning symbols, and current
near-JE cleanup displacement is computed from discovered addresses. Complete
hybrid guards admit only relocations; VCN allocation replacement preserves the
current native call operand. The last three bounds checks now use discovered
addresses rather than old catalog keys. Active userspace Metal/VCN sites use
instruction/metadata discovery and private COW, with no build UUID allowlist.
Fresh GPU-less proof binds actual installed collections/userspace and probe to
the disk; unsupported or ambiguous code/ABI contracts refuse exposure.

The26.7.1 disk was updated natively from26.6 with the Apple-signed installer;
CPU boot53ECFB09-3845-4CCE-B25B-CF8AC2CA1B30 confirms25G241 and sealed snapshot
BC6D1999-8FB5-4043-95DB-DB8CB220D7AE. Update job removed and nonce revoked.
Package SHA256ca854f49dfdedbe78492c26d0e4172ee4d37573e2d375ca90c083d7615b6f48a.

26.7.1 submits228 frames/228 callbacks; self-capture bars547..626 and145..224.
26.6 submits151/151; bars560..639 and141..220. Both return zero presentation
timestamps; parent captures miss the pattern. Native session lock was observed
on26.7.1 and the host QEMU window visibly rendered that lockscreen. Unlocked
Tahoe desktop/FPS remain unqualified. Root offscreen throughput varies widely
(4fps on26.7.1,14fps on26.6,1601fps on15.8.1), despite similar measured GPU
command time (~0.4ms). These are different session states, not a controlled
performance regression comparison. No120fps Tahoe claim is made.

The first490 launch refused before exposure because the kernel journal rotated
past initialization. Existing retained-evidence admission now hash-pins same-boot
candidate489 host-before.json, which captured initialization directly. No gate
code was weakened; no exposure/ledger entry was consumed by that refusal.

User then requested latest-only qualification. The15.8 follow-up was cancelled
through the supervised handler during startup, before its probe. Forced shutdown
could not publish an ownership lease; the reviewed complete MODE2/noqueue
recovery passed and authorizes reuse. That cancelled run is not a test success.
No more older-version tests ran. Earlier candidate486's three Sequoia successes
remain historical evidence; they do not assert new490 live qualification on them.

Artifacts are under run/candidate-490-attempt-{24h32r1,25g241r1,25g72r1}-results.
15.8.1 host-desktop.jpg retains visible QEMU evidence. The original15.8.1 disk
was restored with unchanged inode,size andmtime (run/tahoe-update-tests/
restoration-receipt.json). Test clones remain independent. All current-known
matching update families are discovered dynamically; arbitrary future private
ABI changes may still require maintenance. Full-field4K120, physical HDMI,
all codecs, crash/fresh-boot qualification are outside this update milestone.

Installed launcher verification
-------------------------------
The actual installed raphael-macos entrypoint, using a temporary bounded card285
configuration, ran original15.8.1 disk with the same binary in run
e55634f192509584d986dc94a3cf7eb9 (attemptd20261013190151). CORE_PROBE_PASS,
61,274,112 pixels/zero errors,242 submitted/242 callbacks,238 timed frames at
59.9995fps. The guest display was actually60Hz (3840x2160 pixels,1920x1080
points), so presentation matches the selected mode. Correct moving self-capture
bars548..627 and148..227. Offscreen1000 frames/1.596s (~626.6fps),GPU0.418ms.
The installed stop action requested native shutdown; QEMU0 and ordinary recovery
authorizes=true. The user-selected60Hz mode was preserved. Normal installed
release.conf selects candidate490/metal286, with USB picker/clipboard/audio
preserved. No unbounded autonomous test was run.
