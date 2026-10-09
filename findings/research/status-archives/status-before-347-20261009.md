# Live status — 2026-10-09

## Candidate345: faster sampled console; native exit receipt blocked by zombie state

Run `e5c19e2555990ca2df1d9ac171c73fac`, metal-190, build1.0.345,
MODE2#285 on bootba51b3c6. Native Metal/WindowServer ownership and paused explicit
refresh admission pass. Actual virt-manager renders1080p and1080HiDPI awake.
Thirty-second samples observe1500/676 distinct tokens,49.993/22.529updates/s,
versus342's29.823/18.496. These are sampled console rates, not GPU fps or scanout.
After-first invalid tokens35/113 and median sampler cost2.257/5.330ms remain.
Both60-second fixtures complete and the normal desktop returns.

Capture: valid CORE_PROBE_PASS, no earliest failure. Outer shutdown:
exited-after-guest-request. GPU recovery: recovered, authorizes_launch=true.
VM and cycle stopped; host sleep:idle blocker remains active. No reboot/rebind.
**Native terminal receipt absent:** both EOF handlers see original QEMU PID113
in stateZ and immediately stop the container.343's earlier natural-exit pass
remains valid but did not cover this reaping timing. Next: source-audit and
software-test a strict completed-process proof; separately qualify a small-region
observer to reduce sampling overhead. Atomic presentation and broader lifecycle
remain open.

1157 host tests pass,3 skipped. Candidate kext/manifest match345. Explicit
`experiments/pins-spice60.json` selects the experimental refresh image; default
pins remain stock. Candidate343 is delivered ondev29b462e, hosted tests/build
green.345 remains local pending the lifecycle follow-up.
[Evidence](findings/research/native-refresh-20261009.md) ·
[Hashes](findings/research/native-refresh-evidence-20261009.json) ·
[Previous status](findings/research/status-archives/status-before-345-20261009.md).
