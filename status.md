# Live status — 2026-10-09

## Candidate366: guest-boot persistence passes; HiDPI cadence remains incomplete

Run4e1ee174e75b04e804e28d3efd614d9e, metal-203, build1.0.366,
MODE2#299, bootba51b3c6. Existing installed console app starts after guest reboot
with unchanged presenter hash and no renewed permission. Correct desktop visible
in actual virt-manager. Awake assertions verified. Audio/input not rerun.

ABBA source cadence: baseline draw calls33.063/53.647 per second; paced prerendered
60.000/60.001. Manager valid unique IDs23.633/35.300/24.900/25.967 per second;
partial tokens remain. Draw calls are not completed composition; manager sampling
is not GPU FPS or scanout. Next: bounded actual readonly capture-source token check.

CORE_PROBE_PASS, earliest_failure=null; genuine guest-shutdown/process_exited.
Both capture exits natural~0.451s, shutdown_event_wait=false. Recovery
recovered/authorizes_launch=true. VM/cycle stopped; host remains awake. No reboot.
[Evidence](findings/research/console-cadence-native-20261009.md) ·
[Hashes](findings/research/console-cadence-native-evidence-20261009.json).

1264 host tests pass,8skip. Checked-in kext/manifest match tested366
build65c6d6549d144f319d2a7e84f905d202; delivery pending. Dev2d90bfe delivers364 installer/docs/tested binary;
hosted37939711494 test/build green. Main unchanged.366 delivery pending.
Fresh-user/console-only bootstrap, frame atomicity/performance, broader desktop,
codecs, managers and VirtualBox remain open.
