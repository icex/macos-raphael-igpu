# Live status — 2026-10-13 — two macOS 15 versions verified; third in progress

Same candidate486 executable (compiled source 1123584ce6d16d6a0e2a777d47fa4a9349e51e13,
build 346c68aad1da425085095d74fc796325) passes live GPU tests on:
- 15.8.1 / 24H32: run 4d8855d4b09389190beed0794d1ba4a1.
- 15.7.9 / 24G830: run 96cb263761cb05390978eb05efdbb4a6.
Both CORE_PROBE_PASS: all 163 kernel sites discovered, WindowServer/display on
Navi23 Metal 3, 61,274,112 readback pixels per run with zero errors, ~120 fps
console-user window with correct drawable/self-capture. This does not establish
full-field 4K120, universal crash recovery or a fresh-host-boot qualification.
Both native shutdowns exit-after-guest-request / QEMU exit 0; both recoveries
recovered, authorizes_launch=true. Host boot 2e377991-b6d2-4fe5-81dd-fd6afe9999f7
remains usable. Last authorizing run is 96cb263761cb05390978eb05efdbb4a6.

Installer inputs 15.7.7 / 24G720 and 15.8 / 24H23 pass 163 kernel sites and all
six production userspace contracts without code/catalog changes. Offline checks
are separate from live GPU qualification. Unknown or ambiguous code/ABI refuses
exposure; arbitrary future private ABI changes may need maintenance.

Installed shortcut selects candidate486 / metal-281, preserving the USB picker.
Bounded shortcut run 02ba1491c5bc178274d034f196f8c7eb also CORE_PROBE_PASS with
native exit 0 and authorizing recovery. Dev 92d27aa2cc82b385e3904332110f6d084352c98f
has exact-commit hosted test/build success (Actions 38388366008; release skipped).
Full host suite 1620 tests, 8 skipped, green. New evidence documentation delivery pending.

Current VM is a GPU-less independent update-target clone of tested 15.7.9;
transferring verified 15.8 installer for the third live-version test. Original
15.8.1 disk remains run/macos15-update-tests/24H32-user-preserved.img; active-test.json
records restoration. Tested 15.7.9 clone is preserved separately. The old clone
contains a prepared Tahoe base but boots its verified sealed 15.7.9 snapshot;
its narrow root-agent bootstrap repair applies only to that clone.
User criterion: three separate 15.x versions working before macOS 26/updates.
No macOS 26 GPU qualification yet; verified 26.7.1 installer is retained.

Evidence: findings/research/update-portability-20261013/runtime-24h32.md,
runtime-24g830.md, installer-matrix.json and the exact run directories above.
Superseded live status: findings/research/status-archives/2026-10-13-c486-before-third-update.md.


## One-command GPU test

- Output: `/home/user/macos-vm/run/candidate-486-attempt-24h23r1-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`
