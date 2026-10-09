# Live status — 2026-10-09

## Candidate343: native guest shutdown now retains the terminal receipt

Run `6b0f22ab5a91cb3a3cf51404e4f0459b`, metal-189, build1.0.343,
MODE2#284 on bootba51b3c6. Native Metal/WindowServer ownership passes and the
awake macOS desktop is visible in actual virt-manager. Guest SSH service still
answers; closing the viewer leaves the same container running.

Capture: valid CORE_PROBE_PASS, no earliest failure. Both EOF handlers record
natural-container-exit after about0.454seconds. Native libvirt terminal.json
records guest-shutdown/process_exited=true for the exact run and QEMU identity.
Outer shutdown: exited-after-guest-request. GPU recovery: recovered,
authorizes_launch=true. VM/container and cycle stopped; host sleep:idle blocker
remains active. No reboot/rebind. Omitting the unused container SSH daemon fixes
this native missing-receipt case without weakening process visibility or the
immediate stop when QEMU is still alive.

This is one native guest-shutdown pass, not crash/independent-boot qualification.
Next: isolated software A/B of QEMU nongl SPICE refresh, separately measuring
partial token updates. Candidate342's sampled manager-buffer delivery remains
29.82updates/s at1080p and18.50 at1080HiDPI; these are not GPU fps. Atomic
presentation, host-window resize and broader lifecycle/performance remain open.

Full host suite:1136 tests pass,3 skipped. Checked-in executable/manifest match343.
[Native evidence](findings/research/libvirt-native-terminal-20261009.md) ·
[Artifact hashes](findings/research/libvirt-native-terminal-evidence-20261009.json) ·
[Previous status](findings/research/status-archives/status-before-343-20261009.md).
