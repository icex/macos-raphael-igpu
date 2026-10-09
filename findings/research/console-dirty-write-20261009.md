# Candidate351: destination write cost, not a source-read diagnosis

Run `60b6600fc4514bab8b734e41b70ace39`, metal-194, build1.0.351,
MODE2#289 on bootba51b3c6. Native Metal/WindowServer/display probe passes.
This run compares actual retained ScreenCaptureKit frames under one read-only
lock: direct source→console and source→RAM→console, alternating order. Each
geometry gets eight samples. Full volatile destination comparison is outside
the timed legs. All32 comparisons pass across unoptimized and `-O2` builds of
the exact same source. The compiler change does not remove the slow writes.

| Build / geometry | Order | Direct ms | Source→RAM ms | RAM→console ms |
|---|---|---:|---:|---:|
| O0 /1920×1080 | direct first |5.443|0.237|0.307|
| O0 /1920×1080 | staged first |1.495|0.451|3.818|
| O0 /3840×2160 | direct first |17.168|1.918|16.960|
| O0 /3840×2160 | staged first |15.118|1.778|16.245|
| O2 /1920×1080 | direct first |5.502|0.227|0.968|
| O2 /1920×1080 | staged first |1.878|0.459|3.860|
| O2 /3840×2160 | direct first |15.372|1.791|15.364|
| O2 /3840×2160 | staged first |15.189|1.565|16.188|

These are four-sample means per order, including the first steady sample;
raw values and hashes are in the [evidence JSON](console-dirty-write-evidence-20261009.json).
Native second writes are often much cheaper regardless of source, while both
HiDPI writes remain costly. The RAM staging total is not a demonstrated win.
This points toward the common destination path or scheduling, not expensive
SCK source access. It does not measure cache attributes or page-fault counts.

Candidate352's separate owned-KVM software experiment tests dirty-log rearming
as a cause of first-write cost. That is a narrower mechanism test, not a direct
measurement of this Bochs run. Next compare opt-in full Bochs refresh without
its VGA dirty logging, preserving the default path and migration tracking.
Full refresh can increase host rendering/encoding work and does not make
presentation atomic. No performance milestone is claimed here.

## Protocol and limitations

Both guest binaries use source SHA256
`e23af5c8111d896bf6fddea65ad7494d80ab23e35891d508a7d3714587a1c77d`.
Signed O0 executable `ceb25aeca01297740cf93c107b4f8ac6dac0beb148fb3410b08754143e3f7716`;
signed O2 executable `368a69adb31ec9bcc317b6b3ddd4e01a11bee3dcf52ba785cd1e15c56ae45dbc`.
Permission was renewed through normal Settings UI for each installed bundle;
no TCC database or policy bypass. The user did not need to access Settings.

Each120-second moving-token fixture starts before presenter restart. Although
native mode was active before restart, the recreated virtual display defaults
to HiDPI, so the first eight samples are HiDPI, followed by an explicit native
switch. These are startup-adjacent diagnostic samples, not a steady throughput
benchmark. Both token fixtures complete (5149/5542 draws, not displayed frames).
Verification costs roughly0.4–0.75seconds native and3seconds HiDPI, perturbing
cache and scheduling. No cadence or GPU-fps conclusion is valid from this run.

The original LaunchAgent plist is restored, disabling source diagnostics. The
approved O2 executable remains installed; normal capture restarts, frames
advance and the desktop is visible in actual virt-manager. Screenshot
`run/c351-final-desktop.png` shows Settings/Activity Monitor/Notes with a flat
teal background; this is not full wallpaper/transparency qualification. Closing
the manager leaves the same container running. Display-awake assertions held.

Capture finishes CORE_PROBE_PASS with earliest_failure=null. Shutdown is
exited-after-guest-request, with a real guest-shutdown terminal receipt and
process_exited=true. Both EOF hooks take the already-reaped natural exit path
in about0.455seconds (completed_original_zombie=false). Thus this run does not
exercise the new failed-predicate diagnostic or explain350's zombie refusal.
Recovery is recovered/authorizes_launch=true. VM and runner are stopped;
the host sleep:idle inhibitor remains active.1181 host tests pass,8skip.
