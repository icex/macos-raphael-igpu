# Live status — 2026-10-10 — native framebuffer prototype offline


Candidate433 implements an opt-in native IOFramebuffer with detailed timing,
capacity-bounded60/120 modes and serialized softwareVBL callbacks. ABI builds
compiled/linked; kernel matching, display timing, output and teardown remain
untested. The external support launcher suppresses competing holder/presenter
when the native driver is ready. Preparation cardmetal227 keeps native disabled
and must install this launcher guard before a later opt-in cycle. Host remains
awake; no GPU VM is running. Source/policy and callback-lifetime audit complete;
full regression checks and sealed preparation build are next.
[Plan](findings/research/console-native-framebuffer-plan-20261010.md).

Candidate432 attempt b, runc81e8cb4dd4835f93a655a26322341fb, completed.
QEMU EDID adds native2560×1440/120Hz and1280×720 HiDPI. Same-process mode
readback120Hz and CVDisplayLink period33,333,333ns demonstrate that EDID labels
do not supply120Hz pacing. Source fixture599 draws/20seconds started on native
HiDPI, but mode reverted to saved1080p/85Hz before its final readback. Sustained
native1440p120 output is unqualified; that reversion's cause remains open.
Real-client screenshots establish changing native desktop content at1080p.

Capture: INCONCLUSIVE/probe_completion_missing. Root helper preparation overlapped
harness gx relay before probe completion; probe.json contains the compile reply,
not a Metal result. This cannot establish a GPU regression or passing core probe.
Future guest commands must wait for recorded probe completion, not only container
startup. Separate native mode/clock evidence remains in raw captures.
Shutdown: request sent, forced stop. Recovery: recovered, authorizes_launch=true.
Host awake, vfio-pci retained, power/control=on; no GPU VM running.
Receipts: ~/macos-vm/run/candidate-432-attempt-b-results/.
[Evidence](findings/research/console-native-edid-result-20261010.md).

Next: native framebuffer timing/VBL and mode implementation; preserve the existing
holder until Retina sizing, refresh, and capture are qualified. Candidate431's
uncommitted64MiB/5K prototype is offline. Native arbitrary resize and true120fps
remain open. Candidate430 baseline: correct4K Retina120 metadata, actualsource60,
clientabout60/s localized and27/s full-field; valid core capture, forced shutdown,
authorizing recovery. Native presenter-only1080p Metal readbacks previously passed.

432 tests1536 passed (8 skipped). Local research only; no new milestone publication.
Published dev/origin/dev e240b38ae1d878d429369e41ab5b1179108c2a26 has clipboard/
GUI USB and1.0.428 binary; hosted CI38040411149 passed test/build. Main unchanged
at861ba5e. VirtualBox deferred. Prior432 launch refused before domain creation
because supervisor omitted EDID; forwarding fix is tested. MODE2 resets325–327
passed; first two attempts produced no guest output.
