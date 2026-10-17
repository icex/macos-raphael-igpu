# Live status — 2026-10-13 — dynamic latest-release compatibility and GPU comparison

Candidate490 installed (desktop card286):15.8.1/24H32 and26.7.1/25G241 pass the
same driver,164 dynamic kernel sites,61.3M readback pixels/zero errors, moving
self-captures, native shutdown and ordinary recovery.15.8.1 visible desktop/
presentation60–120fps matches selected mode. Unlocked Tahoe desktop/FPS remains
unqualified; no full-field4K120/physical-HDMI/all-codec/fresh-boot qualification.
Latest-only scope per user; older-version work cancelled, no further old tests.

Matched latest GPU benchmark now passes on both with exact binary60d6f6a...
and driver242c9744...: GPU render2762.31 vs2784.71fps, FP32 compute283.50 vs
283.56GFLOP/s. Correct ramp pixels/triangle band and compute readback on both.
Same60Hz background mode, UID501,2 warmups/10 samples; effect<1% render and
~0.02% compute. Evidence: update-portability-20261013/performance-latest.md.
Both benchmark runs end native/QEMU0; ordinary recovery authorizes. Guest stopped,
macOS26.7.1 now selected as desktop default; original15.8.1 preserved as rollback.
No Vulkan implementation.

One prior15.8.1 attempt panicked before benchmark in mcache.bigcl; cause unproven.
Forced shutdown/ordinary incomplete recovery preserved. Complete MODE2/noqueue
requalification recovered with all inactive scans/PSP/identity/host checks, no
reboot/amdgpu rebind. Path now supports explicitly non-authorizing incomplete
receipts; tests preserve denial/latest/shutdown/replay gates. Installed launcher
uses the same recovery path. Full1625 host tests/8skipped pass; native benchmark
compile/execution/correctness also pass. CLI stopped-status empty-result fix.

Hostvfio-pci,power/control=on; latest ordinary recovery authorizes reuse.
Compatibility milestone and matched benchmark/recovery/launcher follow-up are
integrated and pushed on dev. Code revision a00742e45326a23357a01474e03872a077b261d8
hosted CI38436834753 test/build passed; release job skipped (untagged dev).
Final audit confirms raw samples/correctness/run IDs, native exits/ordinary
recovery, restored disk, clean checkout and installed launcher/source agreement.
Latest requested update work and GPU render/compute comparison are delivered.


2026-10-13 default/cleanup follow-up: active mac_hdd_ng.img now uses the tested
26.7.1/25G241 image. Original15.8.1 moved to rollback/macos-15.8.1-24H32.img;
default-os.json records the selection. Cleanup reclaimed282.52GiB by removing unused installer extracts,
obsolete test images,old builds and clean worktrees; source branches/results/
uploads/ledger/recovery/current490 release/runtime pins are retained. Evidence:
run/cleanup-20261013-receipt.json. Installed launcher bounded default26 verification3c6b1b7cafaf37571079c78e1b7fc935
reports26.7.1/25G241, CORE_PROBE_PASS,61,274,112 pixels/zero errors and correct
moving self-captures (bars552..631/152..231). Native stop/QEMU0 and ordinary
recovery recovered/authorizes=true. Guest stopped. Cleanup completed:83 items,
282.52GiB reclaimed; current490/dev worktrees and runtime/evidence retained.
Documentation/progress follow-up is ready for dev delivery with exact hosted CI.

2026-10-13 interactive follow-up: user launch dcddfb97446d76dacdfbbea0503bbc4d
remains running on 26.7.1/25G241. Selecting logical2048x1152 (4096x2304
render pixels) left the copy path using5120x2880 output timing with4096-pixel
surface pitch. Serial rejects those surfaces, then reports zero copied frames;
SSH and input delivery remained alive. Restoring logical1920x1080 /3840x2160
at60Hz through CoreGraphics resumed QEMU frames (103 and99 frames/10s).
A QEMU pointer click dismissed the App Store onboarding sheet, confirming input
and visible updates. The working mode was saved with permanent display configuration;
no guest/host restart, GPU reset or shutdown was performed. This is a live mode
workaround, not a driver fix for scaled scanout geometry. General scaled-mode
support remains blocked. Evidence: run/serial.log, vm-launch.log and
findings/research/update-portability-20261013/interactive-scaled-mode.md.

Interactive run dcddfb97446d76dacdfbbea0503bbc4d stopped natively after live
scaled-mode recovery; CORE_PROBE_PASS, correct moving self-captures, QEMU0 and
ordinary recovery recovered/authorizes=true. New Tahoe authentication diagnosis:
AKAnisetteError -8008/-8025 and DeviceIdentity/attestation errors, hv_vmm_present=1,
clock/network/en0-built-in healthy. Two unique equal-length OpenCore sysctl-name
patches prepared for Darwin25; boot config backed up and raw/qcow readback matched.
Guest stopped; post-boot authentication verification pending. SSH key added to
UID501 authorized_keys with existing keys retained. No credentials/identity regenerated.


## One-command GPU test

- Output: `/home/user/macos-vm/run/candidate-494-attempt-vmabi-results`
- Verdict: `INVALID`
- Boundary: `identity_or_route_missing`

Candidate494 vmabi was refused before launch/exposure: a MODE2 recovery receipt
was mistakenly supplied to the distinct legacy --noqueue-reuse qualification
argument. No serial bytes, no QEMU/VFIO launch and no GPU ledger entry. Retry uses
automatic same-boot receipt admission, preserving all gates. Host suite passed.


## One-command GPU test

- Output: `/home/user/macos-vm/run/candidate-494-attempt-vmabi2-results`
- Verdict: `INVALID`
- Boundary: `identity_or_route_missing`

Candidate494 vmabi2 stopped through the runner cancellation handler before a
container/QEMU existed, because the default pin selects the older base QEMU
image. Retry explicitly uses pins-igpu-display-v15.json, matching prior GPU runs.
No native execution or GPU regression verdict is inferred from either refusal.


## One-command GPU test

- Output: `/home/user/macos-vm/run/candidate-494-attempt-vmabi3-results`
- Verdict: `INVALID`
- Boundary: `identity_or_route_missing`

The uncaptured startup cancellation consumed its launch reservation. Its original
artifacts and ledger are preserved. MODE2/noqueue recovery now also binds an
uncaptured cancellation's manifest, empty serial/critical capture, null shutdown,
wrapper identity/error, stopped host snapshot and kernel messages. This admission
only reaches the same fresh MODE2, full inactive queue/SDMA scans, PSP teardown and
live host/kernel gates; ordinary guest shutdown checks remain intact. Targeted
recovery tests and full1626-test host suite pass (8 skips). Separate startup
requalification authorizes_launch=true, errors=[], kernel_faults=[].


## One-command GPU test

- Output: `/home/user/macos-vm/run/candidate-494-attempt-vmabi4-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`

Candidate494 vmabi4 run0b504695909175c6fd2974d807c3c1bb (26.7.1/25G241),
normal CoreMedia preferences and hardware Sunshine encoder, reproduced an
unusable desktop. Native desktop Metal probe passed (CORE_PROBE_PASS); this
is pixel/function evidence, not full desktop qualification. First captured client
requests VMIDs1..8 all have raw reprogram byte1 and repaired physical roots,
so the noncanonical reprogram-byte hypothesis is not supported by this run.
Graphics ring advances/drains while first pending client VTEncoderXPCServ
PID808 is Video, channel15 VCN0EncLLQ stamp1. Earlier cosWaitForFunc timeout
callback resolves exactly to HWLibs25G241 _wait_for_vcn_response (+0x8036e).
That callback checks a native register against an expected masked value; the
request register/mask have not yet been captured, so its cause is unresolved.
Native24H32/25G241 encode3_0_submit_frame disassembly differs in relocated
references/call displacements, with matching queue fields and pointer arithmetic.
Full process spindump confirms the same downstream VideoContext teardown lock.
Read-only first-client/frozen-context diagnostics are not a driver fix.
Supervised stop was forced; immutable ordinary recovery incomplete/false.
Separate candidate-494-vmabi4-requalification.json reports recovered,
authorizes_launch=true, errors=[], kernel_faults=[]; no guest is running.
Next: identify the timed-out native VCN register/expected mask and compare its
startup sequence with the latest15.x successful encoder evidence. No disable,
software fallback, fabricated stamp completion, or dev milestone is claimed.
