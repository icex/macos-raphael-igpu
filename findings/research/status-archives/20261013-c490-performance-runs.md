# Live status — 2026-10-13 — latest macOS15/26 dynamic driver verified

Candidate490: latest15.8.1/24H32 and 26.7.1/25G241 pass the same executable,
SHA256242c97440e4c89925f40727870a7a0610cce860612cd1ad4c60ac98bb7301d83,
build2daaac6345c144ee8cf968b73779ca7f. Both resolve164 kernel sites, show Metal3/
WindowServer/display on Navi23 and check61,274,112 pixels with zero errors.
15.8.1 window119.9995fps, correct moving self-captures and visible QEMU desktop.
26.7.1 correct moving self-captures; session locked, presentation timestamps0:
unlocked desktop/FPS unqualified. Same-binary26.6 also passes core checks.
Each successful run exits natively (QEMU0) and ordinary recovery authorizes reuse.
Evidence: findings/research/update-portability-20261013/latest-release-matrix.md.

User steering: latest releases suffice; stop older-version tests.15.8 follow-up
was cancelled during startup through supervised handler, before its probe.
Shutdown forced; ordinary recovery missing ownership lease. Complete reviewed
MODE2/noqueue recovery recovered/authorizes=true,no errors/no host faults:
run/c490-cancel-recovery.json. Original15.8.1 disk restored with identical
inode/size/mtime; active-test marker archived. No older tests will continue.
Host GPU remains vfio-pci,power/control=on; no same-boot amdgpu rebind/reboot.
Rotated initialization journal retained through existing hash-pinned same-boot
candidate489 evidence; all live admission and cleanup gates unchanged.

Desktop release490/metal-286 is installed, preserving USB picker/clipboard/audio.
Actual installed launcher bounded verification e55634f192509584d986dc94a3cf7eb9
passes61,274,112 pixels/zero errors and59.9995fps on the original disk's selected
60Hz mode. Stop action exits natively/QEMU0; ordinary recovery authorizes=true.
Guest/container stopped. Original user's15.8.1 OS/data retained; no old tests.
Bounded card285 remains for autonomous tests. Final1624 host tests/8skipped pass.
Next: integrate/push dev and wait for exact hosted tests/build.
No full-field4K120/physical-HDMI/all-codec/crash/fresh-boot qualification implied.


## One-command GPU test

- Output: `/home/user/macos-vm/run/candidate-490-attempt-perf15r1-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`


Latest-only matched benchmark15.8.1, run8a067c9a406fa23988c9c39d1f29aed9:
UID501, same candidate490, batched1280x1024/20001-triangle rendering and FP32
FMA compute,2 warmup+10 measured samples. Render GPU median2773.39fps,
wall2718.11fps; compute GPU283.55GFLOP/s,wall281.56GFLOP/s. Correctness checks
pass; exact native binary4f80e5cde526a3f5265e3feaf7375200e07caf95c95ffcfcabe2a7c823322d74
saved for26.7.1. Core probe/native shutdown/ordinary recovery all pass; no host
faults. Evidence: run/performance-24H32.json and candidate490 perf15r1 results.
Next: same-binary benchmark on independent26.7.1 clone; restore original after.


## One-command GPU test

- Output: `/home/user/macos-vm/run/candidate-490-attempt-perf26r1-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`

26.7.1 matched benchmark, run28cd33c3c81c78c3c80c00b09b3aad06: same driver,
UID501,60Hz background mode, renderGPU2784.71fps,computeGPU283.56GFLOP/s.
Triangle band4504 expected samples, zero render/compute errors. Native shutdown
and ordinary recovery pass. Native CPU-only boot retrieved exact strengthened
benchmark binary60d6f6a04372cd213980900c2de73a465f32a9b59ff0ddb69755db05d68849d4,
then shut down/sealed cleanly. Original15.8.1 disk restored. Next: final same-binary
15.8.1 rerun with explicit triangle-band verification, then publish comparison.


## One-command GPU test

- Output: `/home/user/macos-vm/run/candidate-490-attempt-perf15v2-results`
- Verdict: `INVALID`
- Boundary: `guest_panic:unknown`

Final15.8.1 benchmark rerun aa6d473efffbeebfe3c0759379bcea0c failed before
benchmark execution: kernel mcache.bigcl slab modified-after-free panic, then
nested traps; root command agent/SSH lost. This is not a benchmark result and
its cause is unproven. Supervised cancellation/forced shutdown preserved logs.
Ordinary recovery incomplete: engines halted/PSP rings destroyed, but SDMA RLC0
input remains enabled; reuse refused. Existing schema9 path now also admits an
explicitly non-authorizing incomplete prior receipt, with all MODE2/full64-HQD,
graphics/SDMA inactivity,PSP,identity/fault and immutable/single-use checks intact.
New eligibility/denial/shutdown tests and full1625 tests/8skipped pass.
Next: complete stopped-device requalification, then one bounded latest-only retry.

Stopped-device requalification passed: perf15v2-requalification.json reports
recovered/authorizes_launch=true, complete post-reset/post-PSP inactive scans,
zero errors/no host faults. Original incomplete receipt remains immutable.
No host reboot or amdgpu rebind. Next: bounded perf15v2r1 retry.


## One-command GPU test

- Output: `/home/user/macos-vm/run/candidate-490-attempt-perf15v2r1-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`
