# Live status — 2026-10-10 — native framebuffer loading failure

Candidate433 run4061015c26310a92abfa72f4c0a4a077 panicked during OSKext::start,
before any new build/route marker. The native framebuffer boot option was absent.
No native display/VBL qualification or launcher installation occurred. Archive
kmod version is1.0.433; panic lists as.rgpu.RaphaelGPU1.0.3,8192bytes. That runtime
identity mismatch needs investigation before another native build. Fault0x10 is
non-present instruction fetch, not proven NX permission failure. New subclass
adds IOFramebuffer imports even while its probe is disabled; loading changed.

Capture: INVALID/identity_or_route_missing. No core/desktop probe completed.
Shutdown: exact supervisor stop, forced-after-shutdown-error; runner retained.
Normal recovery failed because critical producer readiness was absent. Supported
stopped/noqueue inspection found idle queues and no host faults; execute returned
schema9 recovered, authorizes_launch=true. No reboot or driver rebind.
Receipt: ~/macos-vm/run/c433-noqueue-recovery.json. Run results:
~/macos-vm/run/candidate-433-results/. Host remains awake, vfio-pci, power/control=on;
no GPU VM running. Commit this status before the next cycle.

Native framebuffer prototype supplies detailed timing,60/120 modes and serialized
softwareVBL callbacks; builds/link and1539hosttests pass (8 skipped). It remains
unqualified. Launcher guard prevents concurrent native and capture mode ownership,
but is not installed in the guest yet. Dynamic Retina resize and5K transport are
unfinished;431's64MiB prototype is offline. Next inspect injected/prelinked kmod
identity, dependencies and duplicate bundle metadata; preserve the working baseline.
[Prototype plan](findings/research/console-native-framebuffer-plan-20261010.md).

432 verified native2560×1440/120 EDID acceptance, while same-process display clock
stayed30Hz. Mode reverted during long tests; sustainednative120 is unqualified.
430 baseline has correct4K Retina picture at120metadata, actualsource60Hz and
clientabout60/s localized/27/s full-field. Native1080p Metal readbacks passed.

Published dev/origin/dev e240b38ae1d878d429369e41ab5b1179108c2a26 retains clipboard/
GUI USB and1.0.428 binary; hosted CI38040411149 passed test/build. Main unchanged
at861ba5e.433 is local experimental work; no milestone publication. VirtualBox
remains deferred. Native120 clock and actual120fps delivery remain open.
