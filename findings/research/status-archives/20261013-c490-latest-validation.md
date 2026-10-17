# Live status — 2026-10-13 — macOS 15 delivered; 26.6 core probe passed

Unchanged candidate486 passed live Metal rendering/capture/cleanup on macOS
15.7.9/24G830,15.8/24H23 and15.8.1/24H32. Milestone integrated/pushed on dev
b7c76331638bdbebed9932a6221aeddd171b1f0a; exact hosted test/build green.
Installed launcher still selects qualified candidate486/metal281.

Candidate489 run40f9b15bfd15c5fe9ab2641836a9901b on26.6/25G72:
all164 kernel sites resolved, hybrid/SDMA entry routes succeed and VCN shared
allocation extension verifies. Same executable7a70b3b2857aac9876872e3dccba703d387f1de2dcc7c507adb0e5eafd17c1c0
build2164b9b5c5324ef082d715489e97b0d8 checks61,274,112 pixels with0 mismatches,
WindowServer accelerator client/display and Metal3 present. UID501 self-captures
show correct quadrants and moving bars526..605/143..222;211 submitted and
211 presentation callbacks, no failed buffers/missing drawables. Presentation
timestamps are0: FPS unqualified. Offscreen211 frames/3.00s(~70.3fps), slower
than macOS15; performance follow-up remains. Root parent window captures miss
the pattern; own UID501 captures pass. QEMU window exists, but host whole-screen
capture is occupied by another app, so direct QEMU visibility unqualified.

Capture CR2 terminal-prefix accepted. Native identity-bound shutdown exits
with QEMU0; ordinary recovery recovered/authorizes_launch=true. No noqueue
fallback needed. Host remains on vfio-pci,power/control=on. Full host suite
1624 tests/8 skipped passes. Evidence: run/candidate-489-results.

Candidate489 core milestone is delivered on dev b893a5f1f643d26dfba13c4ca7a4f68ffd87ba4a;
hosted run38418302889 test/build pass, release skipped.
Candidate490 removes the final three bounds checks tied to catalog offsets;
existing entryMatches now bounds reads at actual discovered addresses. Source
2851b70c7cc3a1ee780cf4ad6004fbcda0c2db69 builds cleanly, build
2daaac6345c144ee8cf968b73779ca7f, executable SHA256
242c97440e4c89925f40727870a7a0610cce860612cd1ad4c60ac98bb7301d83.
Host suite1624 tests/8skipped passes. Candidate490 retry de9b90614341d07412bdb2af6162043a passes CORE_PROBE_PASS on
26.7.1/25G241: all164 kernel sites, Metal3, WindowServer client/display,61,274,112
pixels/zero errors. UID501 submits228 frames/228 callbacks and its self-captures
show correct quadrants/moving bars547..626 and145..224. Session is locked
(CGSSessionScreenIsLocked=Yes); parent captures miss the pattern and presentation
timestamps are0, so unlocked desktop/FPS is unqualified. Offscreen12 frames/3.01s
(~4fps), GPU time0.435ms: performance is unqualified. Whole-host observation shows
the iGPU QEMU window rendering the macOS lockscreen correctly. Native shutdown
exits-after-guest-request; ordinary recovery recovered/authorizes_launch=true.
Evidence: run/candidate-490-attempt-25g241r1-results. No host faults observed.

Next: finish the independent clone's native26.7.1 update and run candidate490,
then regress26.6 and macOS15 with that same binary and deliver on dev/hosted CI.
No26 update/full-desktop/performance claim yet.
Original user's15.8.1 disk remains run/tahoe-update-tests/24H32-user-preserved.img;
mac_hdd_ng.img is the independent clone, now verified on sealed26.7.1/25G241,
boot53ECFB09-3845-4CCE-B25B-CF8AC2CA1B30, snapshotBC6D1999-8FB5-4043-95DB-DB8CB220D7AE.
Native installer job removed and nonce revoked. Fresh GPU-less compatibility
observation passed and the guest shut down before sealing the disk proof.
Candidate490 initial run effc3716d3ba715949daa1a2be28f3f9 refused before exposure
because the live kernel journal had rotated past amdgpu initialization; no GPU
ledger entry was consumed. Existing retained-evidence path now hash-pins the
same-boot candidate489 host-before snapshot (direct journal initialization proof),
without changing admission code or any current reset/recovery/fault checks.
Same-binary26.6/25G72 regression b155128029f53a1ce9997d1e503c9d09 also passes
CORE_PROBE_PASS: all164 sites,61,274,112 pixels/zero errors,151 submitted/151
callbacks, moving self-capture bars560..639 and141..220. Presentation timestamps
are0, FPS unqualified. Native shutdown exits-after-guest-request and ordinary
recovery recovered/authorizes_launch=true. No host faults observed.
Evidence: run/candidate-490-attempt-25g72r1-results.
Same-binary15.8.1/24H32 regression f180fe096265ffef07892be523c8022e passes
CORE_PROBE_PASS: all164 sites,61,274,112 pixels/zero errors,482 submitted/482
callbacks,480 timed frames at119.9995fps, no missing drawables/failed buffers.
Offscreen1000 frames/0.625s (~1601fps). QEMU desktop visibly correct; retained
host-desktop.jpg in run/candidate-490-attempt-24h32r1-results. Native shutdown
and ordinary recovery recovered/authorizes_launch=true. No host faults observed.
Next:15.8 and15.7.9 regressions with this same binary.
The tested26.6 disk is saved at run/tahoe-update-tests/25G72-live-tested.img;
independent15.8.1 crossversion clone and all four regression attempts prepared.
active-test.json records original/restoration paths. No physical-HDMI/full-field
4K120/crash/fresh-boot qualification is implied.


## One-command GPU test

- Output: `/home/user/macos-vm/run/candidate-490-attempt-25g241r1-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`


## One-command GPU test

- Output: `/home/user/macos-vm/run/candidate-490-attempt-25g72r1-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`


## One-command GPU test

- Output: `/home/user/macos-vm/run/candidate-490-attempt-24h32r1-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`


## One-command GPU test

- Output: `/home/user/macos-vm/run/candidate-490-attempt-24h23r1-results`
- Verdict: `INVALID`
- Boundary: `recovery_lease_pool_missing`
