# Live status — 2026-10-09

## Candidate361: default application audio and continuous pointer entry pass

Run4078e49c09b0a4fa591ca4a6df2511ca, metal-201, build1.0.361,
MODE2#297, bootba51b3c6. Ordinary afplay through existing default QEMU USB output
passes stereo frequency/channel/silence checks in VM-only Pulse capture. Original
host route/volume/mute/defaults restored, owned sink/module removed; guest defaults
unchanged. Endpoint audibility and broader A/V synchronization unqualified.

Actual virt-manager resizes1288x909→1000x760. Continuous relative pointer entry
produces GTK motion before first guest click; five targets and exact token pass,
zero misses, no guest mode changes (1080HiDPI).358 enter-without-motion failure
remains distinct; stationary-pointer resize/automatic resolution remain unqualified.

CORE_PROBE_PASS, earliest_failure=null; genuine guest-shutdown/process_exited
terminal. Both hooks complete naturally~0.394s; critical reset distinct fromEOF.
Recovery recovered/authorizes_launch=true. VM/cycle stopped; host awake.
No reboot/rebind. [Evidence](findings/research/console-default-audio-input-20261009.md)
· [Hashed artifacts](findings/research/console-default-audio-input-evidence-20261009.json).

1241 host tests pass,8skip. Checked-in kext/manifest match tested361 build
1ab964d9844d4dd5aa4acd20b139d2c3; reviewed milestone ready for dev, hosted validation pending.358 milestone is on
dev121a4ac, hosted37935096265 test/build green; main unchanged. Next optimized
console helper package/install provenance and rollback, then clean-user first-use
and second-boot qualification. Broader performance/desktop/codecs and VirtualBox open.
