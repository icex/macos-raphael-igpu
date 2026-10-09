# Live status — 2026-10-09

## Candidate368: source tokens intact; partial tokens arise downstream

Run177c406a3d3e1c39bdf5327649c5dbd7, metal-204, build1.0.368,
MODE2#300, bootba51b3c6. Reviewed diagnostic presenter compiled/installed natively;
normal Screen Recording renewal required after changed ad-hoc signature.
HiDPI1742/1742 and native1738/1738 processed source tokens valid in complete30s
windows, while bracketed manager samples contain633/1065 and35/1116 invalids.
This narrows beyond the checked source regions; it does not identify a single
framebuffer/QEMU/SPICE stage, prove source stability after checking or60Hz output.

Original LaunchAgent restored after both cases; normal capture, awake assertions
and actual-manager desktop pass. Input/audio not rerun. CORE_PROBE_PASS, earliest
failure null; genuine guest-shutdown/process_exited. Both capture exits natural
~0.415s, shutdown_event_wait=false. Recovery recovered/authorizes_launch=true.
Cycle stopped; host remains awake. No reboot/rebind.
[Evidence](findings/research/console-source-token-native-20261009.md) ·
[Hashes](findings/research/console-source-token-native-evidence-20261009.json).

1268 host tests pass,8skip. Dev a815827 delivers366 persistence/docs/tested binary;
hosted37942471484 test/build green.368 delivery pending; main unchanged.
Next: exclusive staging plus acknowledged immutable host snapshot software proof,
then native comparison. Fresh-user bootstrap, performance/atomicity, broader
applications/codecs, other managers and VirtualBox remain open.
