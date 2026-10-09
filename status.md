# Live status — 2026-10-09

## Candidate356: native socket-reset shutdown completes; viewport transition open

Run `684122f412ad335d91c07cdfece852dd`, metal-199, build1.0.356,
MODE2#295, bootba51b3c6. Native Metal/WindowServer/display pass; awake HiDPI
desktop visible in actual virt-manager. Normal1288x909 and fullscreen1920x1080
pass five target clicks and exact keyboard token, no guest mode changes.
Small1000x760 records two initial clicks at stale center, then all targets and
token delivered; retain as failed, investigate pointer motion/enter after resize.
Viewer close preserves exact VM; reopening displays desktop.

Critical final bytes/hash match quiesce ACK. Critical recv-reset104 and console
cleanEOF are distinct. Both hooks observe natural container exit~0.373s, real
terminal guest-shutdown/process_exited=true. CORE_PROBE_PASS, earliest_failure=null.
New pending-worker shutdown-event wait not exercised by native hooks.
Recovery recovered/authorizes_launch=true; VM/cycle stopped, host awake.
No reboot/rebind needed. [Evidence](findings/research/libvirt-reset-native-20261009.md)
· [Hashed receipts](findings/research/libvirt-reset-native-evidence-20261009.json).

1224 host tests pass,8skip (also rechecked for359 delivery); stage87 pass before
exposure. Checked-in kext and manifest match the tested356 bundle
(SHA72361929…); delivery remains pending.353 HiDPI milestone and CI correction are on
devdefc0f4, hosted37930517553 test/build green.354–356 lifecycle work local pending
delivery review. Main unchanged. Next: resize transition discrimination and console
USB audio qualification. Installation durability, broader desktop/codec workloads
and VirtualBox remain open.
