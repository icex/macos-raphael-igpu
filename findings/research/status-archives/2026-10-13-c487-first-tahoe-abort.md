# Live status — 2026-10-13 — three macOS 15 releases pass; macOS 26 next

One candidate486 executable (source 1123584ce6d16d6a0e2a777d47fa4a9349e51e13,
build 346c68aad1da425085095d74fc796325) passes live CORE_PROBE_PASS on:
- 15.7.9 / 24G830: 96cb263761cb05390978eb05efdbb4a6.
- 15.8 / 24H23: 07e58b88a6d4ac54228c39817904589a.
- 15.8.1 / 24H32: 4d8855d4b09389190beed0794d1ba4a1.
Each resolves 163 sites, uses Navi23 Metal 3 for WindowServer/display, checks
61,274,112 readback pixels with zero errors, and has correct console-user window
captures. 24G830/24H32 timed window presentation is ~120 fps. 24H23 has 193
presentation callbacks but zero presentedTime values, so FPS is unqualified.
Actual visible QEMU host-window evidence belongs to 24H32; no extra host-window
claim is made from a post-exit screenshot on 24H23. Full-field 4K120, general
crash recovery and fresh-host-boot qualification were not repeated here.
All three native shutdowns: exited-after-guest-request / QEMU exit 0. Recoveries
recovered, authorizes_launch=true. Last authorizing run is 07e58b88a6d4ac54228c39817904589a.
Host boot 2e377991-b6d2-4fe5-81dd-fd6afe9999f7 remains usable.

Original user 15.8.1 disk restored at mac_hdd_ng.img; no test VM running.
Independent tested 15.7.9/15.8 clones are retained in run/macos15-update-tests/.
15.8 was installed GPU-less from the verified signed package on a copy of tested
15.7.9. Temporary installer job removed and permit revoked. Narrow root-agent
bootstrap repair belongs only to the old test clones; original backup preserved.

Installed shortcut uses candidate486 / metal-281; bounded shortcut verification
also passes with authorizing recovery. Dev 1c60ef37e2012a079fa36b8ff06089ae1e34941c
has exact-commit hosted test/build success (Actions 38390930224). Full host suite
1620 tests / 8 skipped passes. Third-version evidence delivery is in progress.
No main publication. Installer-only 15.7.7 also passes kernel/userspace contracts.

User minimum of three distinct live 15.x versions is met. Proceeding to macOS 26
and updates: 26.7.1 / 25G241 package verified; 26.6 / 25G72 package downloading.
No macOS 26 GPU qualification yet. Automatic fresh disk-bound inspection remains
mandatory; unknown code/ABI refuses exposure. Arbitrary future private ABI changes
may need maintenance; there is no per-build address/UUID allowlist for active fixes.

Evidence: findings/research/update-portability-20261013/runtime-24g830.md,
runtime-24h23.md, runtime-24h32.md and installer-matrix.json.


## One-command GPU test

- Output: `/home/user/macos-vm/run/candidate-487-results`
- Verdict: `INVALID`
- Boundary: `identity_or_route_missing`
