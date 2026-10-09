# Live status — 2026-10-09

## Candidate358: explicit console stereo audio passes; first-entry input remains open

Run775fc7e86900090204edd78ae20f34a4, metal-200, build1.0.358,
MODE2#296, bootba51b3c6. Exact QEMU USB HAL output delivers expected stereo tones
through VM-only Pulse capture; frequencies/channel separation/silence pass.
Original stream route, volume/mute/defaults restored and owned sink/module removed,
independently verified. Default-application output and endpoint audibility untested.

Read-only GTK trace shows enter+button without motion after resize clicks at prior
guest position. Real motion restores mapping; subsequent five targets+token pass
at1000x760 and1080HiDPI without guest mode changes. Initial click opens Apple menu
outside fixture: fixture passed=true is not full transition qualification.
Next test continuous real pointer motion and default-application audio output.

CORE_PROBE_PASS, earliest_failure=null; genuine terminal guest-shutdown with
process_exited=true. Recovery recovered/authorizes_launch=true. VM/cycle stopped;
host awake. No reboot/rebind. [Evidence](findings/research/console-audio-native-20261009.md)
· [Hashed artifacts](findings/research/console-audio-native-evidence-20261009.json).

1236 host tests pass,8skip; staging87 pass. Audio inventory parser repair17focused
checks pass. Checked-in kext remains tested356;358 separately pinned.356 lifecycle
milestone is on devc24ff71; hosted37934370047 pending. Main unchanged. Broader
installation durability, desktop/codec/performance and VirtualBox remain open.
